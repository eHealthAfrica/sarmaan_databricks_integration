"""
step6_databricks_loader.py — Load Coverage data into Databricks (Unity Catalog).

Targets (catalog and schema names come from config.py / .env; the layout
follows the architecture review, see architecture.py):
  <catalog>.bronze.coverage_*      Step 1 output: every submission, all STRING,
                                   plus lineage metadata columns
  <catalog>.silver.coverage_*      Step 2 output: every submission, readable
                                   names, all STRING, plus _run_id
  <catalog>.silver.coverage_validation_issues
                                   Step 4 report, appended when validation
                                   fails; identifier values masked
  <catalog>.gold.coverage_*        Step 5 output: approved only, typed, plus
                                   _run_id, WITHOUT identifier columns
  <catalog>.restricted.coverage_*_identifiers
                                   Names, phones (STRING), GPS and card images,
                                   one row per gold row, same key

Keys (pending the key spike): Kobo rootUuid in every layer.
  coverage_household       PK rootUuid
  child tables             PK (rootUuid, row id); FK rootUuid -> coverage_household
  restricted tables        same PK as their gold table; FK -> that gold table

Load order:
  1. Prepare every table in memory: map columns, attach rootUuid, split the
     identifiers off gold, reject blank or repeated keys and child rows with
     no household.
  2. Create missing tables. An existing table is never altered: a column the
     mapping needs but the table lacks stops the run.
  3. Upload each table as a Parquet file to the staging volume.
  4. MERGE each table on its key: bronze, silver, gold, restricted.
  5. Delete the staged files.

Databricks has no transaction across tables. Steps 1-3 write no rows, and
before step 4 the loader records each table's version: if any MERGE fails, it
RESTOREs every table it already changed in this run.

Databricks records PRIMARY KEY / FOREIGN KEY constraints but does not enforce
them, so the checks in step 1 are what keep the tables clean.
"""

import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import architecture as arch
from config import (
    BASE_DIR,
    KOBO_ASSET_UID,
    DATABRICKS_SERVER_HOSTNAME,
    DATABRICKS_HTTP_PATH,
    DATABRICKS_TOKEN,
    DATABRICKS_CLIENT_ID,
    DATABRICKS_CLIENT_SECRET,
    DATABRICKS_CATALOG,
    DATABRICKS_BRONZE_SCHEMA,
    DATABRICKS_SILVER_SCHEMA,
    DATABRICKS_GOLD_SCHEMA,
    DATABRICKS_RESTRICTED_SCHEMA,
    DATABRICKS_STAGING_VOLUME,
)
from load_common import (
    CLEAN_TABLE_CHAIN,
    CLEAN_SHEET_TO_MAP_KEY,
    RAW_TABLE_CHAIN,
    _build_computed_cols,
    _validate_and_fill_columns,
    _load_clean_types,
    _check_fk_integrity,
)
from step5_db_schema import build_silver

logger = logging.getLogger(__name__)

ISSUES_TABLE = "coverage_validation_issues"
ISSUES_COLUMNS = [
    "_run_id", "logged_at", "sheet", "row_index", "row_id",
    "check_type", "rule", "column_name", "value", "value_masked", "issue",
]

NUMERIC_TYPES = ("SMALLINT", "INT", "BIGINT", "DOUBLE")


@dataclass
class TableLoad:
    schema: str
    table: str
    label: str                                # sheet name, for messages
    df: pd.DataFrame                          # DB column names; values str or None
    types: dict[str, str]                     # column -> Databricks type
    pk: list[str] = field(default_factory=list)
    fk: list[str] = field(default_factory=list)
    parent_schema: str | None = None
    parent_table: str | None = None
    parent_pk: list[str] = field(default_factory=list)
    staged_path: str = ""

    @property
    def fq(self) -> str:
        return _fq(self.schema, self.table)

    @property
    def name(self) -> str:
        return f"{self.schema}.{self.table}"


# ── SQL helpers ───────────────────────────────────────────────────────────────

def _q(name: str) -> str:
    """Quote an identifier."""
    return "`" + str(name).replace("`", "``") + "`"


def _fq(schema: str, table: str) -> str:
    return f"{_q(DATABRICKS_CATALOG)}.{_q(schema)}.{_q(table)}"


def _lit(value: str) -> str:
    """Quote a string literal."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _cols(names: list[str]) -> str:
    return ", ".join(_q(n) for n in names)


def _connect(staging_dir: Path):
    from databricks import sql

    host = DATABRICKS_SERVER_HOSTNAME.replace("https://", "").strip().rstrip("/")
    if not (host and DATABRICKS_HTTP_PATH):
        raise ValueError(
            "Databricks load needs DATABRICKS_SERVER_HOSTNAME and "
            "DATABRICKS_HTTP_PATH in .env"
        )
    kwargs = {
        "server_hostname": host,
        "http_path": DATABRICKS_HTTP_PATH,
        # PUT may only read files from this folder
        "staging_allowed_local_path": str(staging_dir),
    }
    if DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET:
        from databricks.sdk.core import Config, oauth_service_principal

        def credentials_provider():
            return oauth_service_principal(Config(
                host=f"https://{host}",
                client_id=DATABRICKS_CLIENT_ID,
                client_secret=DATABRICKS_CLIENT_SECRET,
            ))
        kwargs["credentials_provider"] = credentials_provider
    elif DATABRICKS_TOKEN:
        kwargs["access_token"] = DATABRICKS_TOKEN
    else:
        raise ValueError(
            "Databricks load needs DATABRICKS_TOKEN, or DATABRICKS_CLIENT_ID and "
            "DATABRICKS_CLIENT_SECRET, in .env"
        )
    return sql.connect(**kwargs)


# ── Values and types ──────────────────────────────────────────────────────────

def _blank(v) -> bool:
    return v is None or bool(pd.isna(v)) or str(v).strip() in ("", "nan", "None")


def _as_text_frame(df: pd.DataFrame) -> pd.DataFrame:
    """All values as str, missing as None (bronze and silver are all STRING)."""
    return df.astype(object).map(lambda v: None if bool(pd.isna(v)) else str(v))


def _databricks_type(raw_type: str) -> str:
    """Convert a step_5_map data_type to a Databricks type."""
    t = re.sub(r"\s+", " ", raw_type.strip().lower())
    if t in ("small int", "smallint"):
        return "SMALLINT"
    if t in ("int", "integer"):
        return "INT"
    if t == "bigint":
        return "BIGINT"
    if t == "double precision":
        return "DOUBLE"
    if t == "date":
        return "DATE"
    if t.startswith("timestamp"):
        return "TIMESTAMP_NTZ"
    # character varying(n), uuid, enums, text
    return "STRING"


def _typed_value(val, sql_type: str) -> str | None:
    """Clean one value for a typed gold column (same rules as the Postgres loader)."""
    if val is None or bool(pd.isna(val)):
        return None
    s = str(val).strip()
    if s == "" or s.lower() == "nan":
        return None
    if sql_type in ("SMALLINT", "INT", "BIGINT"):
        try:
            return str(int(float(s)))
        except (ValueError, TypeError, OverflowError):
            return None
    if sql_type == "DOUBLE":
        try:
            return str(float(s))
        except (ValueError, TypeError):
            return None
    if sql_type == "DATE":
        return s[:10]
    if sql_type == "TIMESTAMP_NTZ":
        s = s.replace("T", " ")
        tz_m = re.search(r"[+\-]\d{2}:\d{2}$", s)
        if tz_m:
            s = s[:tz_m.start()]
        elif s.endswith("Z"):
            s = s[:-1]
        return s
    return s


def _pipeline_version() -> str:
    if os.getenv("PIPELINE_VERSION"):
        return os.environ["PIPELINE_VERSION"]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR,
            capture_output=True, text=True, check=True, timeout=10,
        )
        return f"git-{out.stdout.strip()}"
    except Exception:
        return "unknown"


@dataclass
class RunInfo:
    run_id: str
    ingested_at: str
    source_asset: str
    pipeline_version: str


def _new_run() -> RunInfo:
    now = datetime.now(timezone.utc)
    return RunInfo(
        run_id=now.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6],
        ingested_at=now.strftime("%Y-%m-%d %H:%M:%S"),
        source_asset=KOBO_ASSET_UID,
        pipeline_version=_pipeline_version(),
    )


def _with_root(df: pd.DataFrame, root: str, values) -> pd.DataFrame:
    """Set the rootUuid column: in place if the mapping has it, else first."""
    df = df.copy()
    if root in df.columns:
        df[root] = list(values)
    else:
        df.insert(0, root, list(values))
    return df


# ── Prepare (in memory, no database) ─────────────────────────────────────────

def _prepare_bronze(
    sheets: dict[str, pd.DataFrame],
    maps: dict[str, dict[str, str]],
    run: RunInfo,
) -> tuple[list[TableLoad], dict[str, str]]:
    """Bronze tables, plus the household _uuid -> rootUuid lookup."""
    # load_step1_maps() returns "main"; the Step 1 export sheet is "main_sheet"
    if "main" in maps and "main_sheet" not in maps:
        maps = {("main_sheet" if k == "main" else k): v for k, v in maps.items()}

    frames = {}
    for sheet_name, table, *_ in RAW_TABLE_CHAIN:
        df = sheets.get(sheet_name, pd.DataFrame())
        if df.empty:
            raise ValueError(f"LOAD ABORTED — '{sheet_name}' is empty")
        mapping = maps.get(sheet_name, {})
        if not mapping:
            raise ValueError(f"LOAD ABORTED — No mapping for '{sheet_name}'")
        df = _build_computed_cols(df, sheet_name)
        df = _validate_and_fill_columns(df, mapping, sheet_name, table)
        out = df[list(mapping)].copy()
        out.columns = [mapping[src] for src in mapping]
        frames[table] = (sheet_name, _as_text_frame(out))

    # rootUuid: Kobo sets meta/rootUuid to "uuid:<_uuid>" on first submission and
    # keeps it on edits. Fill the rare blank one the same way.
    _, hh = frames[arch.PARENT]
    root, sub = arch.root_col("bronze", arch.PARENT), arch.uuid_col("bronze", arch.PARENT)
    for col in (root, sub):
        if col not in hh.columns:
            raise ValueError(f"LOAD ABORTED — bronze household has no '{col}' column")
    blank = hh[root].map(_blank)
    if blank.any():
        logger.warning(f"  [bronze] {int(blank.sum())} household(s) without rootUuid — set to 'uuid:' + _uuid")
        hh.loc[blank, root] = "uuid:" + hh.loc[blank, sub].astype(str)
    lookup = {str(u).strip(): r for u, r in zip(hh[sub], hh[root]) if not _blank(u)}

    meta = {
        "_ingested_at": run.ingested_at, "_run_id": run.run_id,
        "_source_system": arch.SOURCE_SYSTEM, "_source_asset": run.source_asset,
        "_pipeline_version": run.pipeline_version,
    }
    loads = []
    for table, (sheet_name, df) in frames.items():
        pk, fk = arch.keys("bronze", table)
        if table != arch.PARENT:
            root, sub = arch.root_col("bronze", table), arch.uuid_col("bronze", table)
            from_parent = df[sub].map(lambda u: lookup.get(str(u).strip()) if not _blank(u) else None)
            own = df[root] if root in df.columns else pd.Series([None] * len(df), index=df.index)
            df = _with_root(df, root, [o if not _blank(o) else p for o, p in zip(own, from_parent)])
        df = df.copy()
        for name, value in meta.items():
            df[name] = value
        types = {c: "STRING" for c in df.columns}
        types["_ingested_at"] = "TIMESTAMP"
        loads.append(TableLoad(
            DATABRICKS_BRONZE_SCHEMA, table, sheet_name, df, types, pk, fk,
            DATABRICKS_BRONZE_SCHEMA if fk else None, arch.PARENT if fk else None,
            arch.keys("bronze", arch.PARENT)[0] if fk else [],
        ))
    return loads, lookup


def _root_from_lookup(df: pd.DataFrame, col: str, lookup: dict[str, str], label: str) -> list:
    if col not in df.columns:
        raise ValueError(f"[{label}] no '{col}' column to look up the rootUuid")
    return [lookup.get(str(u).strip()) if not _blank(u) else None for u in df[col]]


def _prepare_silver(
    step2_sheets: dict[str, pd.DataFrame],
    lookup: dict[str, str],
    run: RunInfo,
) -> list[TableLoad]:
    sheets = build_silver(step2_sheets)
    loads = []
    for sheet_name, table, *_ in CLEAN_TABLE_CHAIN:
        df = sheets.get(sheet_name, pd.DataFrame())
        if df.empty:
            raise ValueError(f"LOAD ABORTED — silver '{sheet_name}' is empty")
        df = _as_text_frame(df)
        roots = _root_from_lookup(df, arch.uuid_col("silver", table), lookup, f"silver {sheet_name}")
        df = _with_root(df, arch.root_col("silver", table), roots)
        df[arch.RUN_ID] = run.run_id
        pk, fk = arch.keys("silver", table)
        loads.append(TableLoad(
            DATABRICKS_SILVER_SCHEMA, table, sheet_name, df, {c: "STRING" for c in df.columns},
            pk, fk, DATABRICKS_SILVER_SCHEMA if fk else None, arch.PARENT if fk else None,
            arch.keys("silver", arch.PARENT)[0] if fk else [],
        ))
    return loads


def _prepare_gold(
    sheets: dict[str, pd.DataFrame],
    types: dict[str, dict[str, str]],
    lookup: dict[str, str],
    run: RunInfo,
) -> list[TableLoad]:
    """Gold tables without identifiers, plus the restricted identifier tables."""
    gold, restricted = [], []
    for sheet_name, table, *_ in CLEAN_TABLE_CHAIN:
        df = sheets.get(sheet_name, pd.DataFrame())
        if df.empty:
            raise ValueError(f"LOAD ABORTED — gold '{sheet_name}' is empty")
        df = df.astype(object).copy()
        _check_column_names(list(df.columns), sheet_name)

        # Columns the mapping declares but step 5 did not produce are loaded as NULL
        type_map = types.get(CLEAN_SHEET_TO_MAP_KEY[sheet_name], {})
        for db_col in type_map:
            if db_col not in df.columns:
                df[db_col] = None
                logger.warning(
                    f"  [{sheet_name}] DB column '{db_col}' missing from step5 output "
                    f"— loaded as NULL (check mapping file for duplicate source labels)"
                )

        col_types = {c: _databricks_type(type_map.get(c, "TEXT")) for c in df.columns}
        for c in arch.PHONE_COLUMNS & set(col_types):
            col_types[c] = "STRING"
        for col in df.columns:
            df[col] = [_typed_value(v, col_types[col]) for v in df[col]]

        root = arch.root_col("gold", table)
        df = _with_root(df, root, _root_from_lookup(df, arch.uuid_col("gold", table), lookup, f"gold {sheet_name}"))
        col_types[root] = "STRING"
        pk, fk = arch.keys("gold", table)

        ids = arch.IDENTIFIERS.get(table, [])
        missing = [c for c in ids if c not in df.columns]
        if missing:
            raise ValueError(f"[{sheet_name}] identifier column(s) {missing} not in the gold data")
        if ids:
            rdf = df[pk + ids].copy()
            rdf[arch.RUN_ID] = run.run_id
            rtypes = {c: col_types.get(c, "STRING") for c in rdf.columns}
            restricted.append(TableLoad(
                DATABRICKS_RESTRICTED_SCHEMA, arch.restricted_table(table), f"{sheet_name} identifiers",
                rdf, rtypes, pk, pk, DATABRICKS_GOLD_SCHEMA, table, pk,
            ))
            df = df.drop(columns=ids)

        df[arch.RUN_ID] = run.run_id
        col_types[arch.RUN_ID] = "STRING"
        gold.append(TableLoad(
            DATABRICKS_GOLD_SCHEMA, table, sheet_name, df,
            {c: col_types[c] for c in df.columns}, pk, fk,
            DATABRICKS_GOLD_SCHEMA if fk else None, arch.PARENT if fk else None,
            arch.keys("gold", arch.PARENT)[0] if fk else [],
        ))
    return gold + restricted


def _check_column_names(columns: list[str], label: str) -> None:
    by_lower: dict[str, list[str]] = {}
    for c in columns:
        by_lower.setdefault(str(c).lower(), []).append(str(c))
    repeated = [names for names in by_lower.values() if len(names) > 1]
    if repeated:
        raise ValueError(
            f"[{label}] column names repeat (Databricks ignores case): {repeated}"
        )


def _check_table(load: TableLoad) -> None:
    """Keys must be present, non-blank and unique: MERGE would otherwise
    insert duplicate rows, since Databricks does not enforce primary keys."""
    _check_column_names(list(load.df.columns), load.label)
    for col in load.pk + load.fk:
        if col not in load.df.columns:
            raise ValueError(f"[{load.label}] key column '{col}' is missing from the data")
    if not load.pk:
        return

    blank = load.df[load.pk].apply(lambda s: s.map(_blank)).any(axis=1)
    if blank.any():
        raise ValueError(
            f"[{load.label}] {int(blank.sum())} row(s) have an empty key "
            f"({', '.join(load.pk)}) — cannot load into {load.name}"
        )
    repeated = load.df[load.df.duplicated(subset=load.pk, keep=False)]
    if not repeated.empty:
        examples = repeated[load.pk].drop_duplicates().head(5).values.tolist()
        raise ValueError(
            f"[{load.label}] {len(repeated)} row(s) share a key ({', '.join(load.pk)}) "
            f"— cannot load into {load.name}. Examples: {examples}"
        )
    logger.info(f"  [{load.label}] {load.name}: {len(load.df)} rows, keys OK")


def _check_layer_fks(loads: list[TableLoad]) -> None:
    by_table = {(load.schema, load.table): load for load in loads}
    for load in loads:
        parent = by_table.get((load.parent_schema, load.parent_table))
        if load.fk and parent is not None and len(load.fk) == 1:
            _check_fk_integrity(
                load.df, load.fk[0], parent.df, load.parent_pk[0],
                load.label, parent.name,
            )


# ── Database steps ────────────────────────────────────────────────────────────

def _existing_columns(cur, schema: str, table: str) -> set[str] | None:
    """Lower-cased column names of the table, or None if it does not exist."""
    cur.execute(
        f"SELECT column_name FROM {_q(DATABRICKS_CATALOG)}.information_schema.columns "
        f"WHERE table_schema = :schema AND table_name = :table",
        {"schema": schema.lower(), "table": table.lower()},
    )
    cols = {str(row[0]).lower() for row in cur.fetchall()}
    return cols or None


def _ensure_table(cur, load: TableLoad) -> None:
    """Create a missing table; never alter an existing one."""
    existing = _existing_columns(cur, load.schema, load.table)
    if existing is not None:
        missing = [c for c in load.df.columns if c.lower() not in existing]
        if missing:
            raise ValueError(
                f"[{load.label}] '{load.name}' is missing {len(missing)} column(s) "
                f"required by the mapping: {missing}. "
                f"Add them to the table or fix the mapping file — the pipeline "
                f"will NOT alter an existing table."
            )
        logger.info(f"  [{load.label}] '{load.name}' schema OK — all {len(load.df.columns)} columns present")
        return

    col_sql = [
        f"{_q(c)} {load.types[c]}" + (" NOT NULL" if c in load.pk else "")
        for c in load.df.columns
    ]
    if load.pk:
        col_sql.append(f"CONSTRAINT {_q(load.table + '_pk')} PRIMARY KEY ({_cols(load.pk)})")
    if load.fk:
        col_sql.append(
            f"CONSTRAINT {_q(load.table + '_fk')} FOREIGN KEY ({_cols(load.fk)}) "
            f"REFERENCES {_fq(load.parent_schema, load.parent_table)} ({_cols(load.parent_pk)})"
        )
    # Column mapping allows names Delta otherwise rejects (e.g. spaces)
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS {load.fq} (\n  "
        + ",\n  ".join(col_sql)
        + "\n) TBLPROPERTIES ('delta.columnMapping.mode' = 'name')"
    )
    logger.info(
        f"  Created '{load.name}' (PK: {', '.join(load.pk) or '-'}"
        + (f"; FK: {', '.join(load.fk)} -> {load.parent_schema}.{load.parent_table})" if load.fk else ")")
    )


def _ensure_staging_volume(cur) -> None:
    parts = DATABRICKS_STAGING_VOLUME.strip("/").split("/")
    if len(parts) != 4 or parts[0] != "Volumes":
        raise ValueError(f"DATABRICKS_STAGING_VOLUME must be /Volumes/<catalog>/<schema>/<volume>, got '{DATABRICKS_STAGING_VOLUME}'")
    _, catalog, schema, volume = parts
    try:
        cur.execute(f"CREATE VOLUME IF NOT EXISTS {_q(catalog)}.{_q(schema)}.{_q(volume)}")
    except Exception as e:
        raise ValueError(
            f"Staging volume {DATABRICKS_STAGING_VOLUME} does not exist and could not be "
            f"created ({e}). Ask a workspace admin to run databricks/setup_catalog.sql."
        ) from e


def _stage(cur, load: TableLoad, local_dir: Path, run_id: str) -> None:
    """Upload the table as Parquet. Columns are named c0..cN so any column
    name survives; _source_sql renames them back."""
    arrays = [pa.array(load.df[c].tolist(), type=pa.string()) for c in load.df.columns]
    names = [f"c{i}" for i in range(len(arrays))]
    local = local_dir / f"{run_id}_{load.schema}_{load.table}.parquet"
    pq.write_table(pa.Table.from_arrays(arrays, names=names), local)

    remote = f"{DATABRICKS_STAGING_VOLUME.rstrip('/')}/_staging/{local.name}"
    cur.execute(f"PUT {_lit(local.as_posix())} INTO {_lit(remote)} OVERWRITE")
    load.staged_path = remote


def _source_sql(load: TableLoad) -> str:
    """SELECT over the staged file with DB column names and types."""
    parts = []
    for i, col in enumerate(load.df.columns):
        t = load.types[col]
        if t == "STRING":
            expr = f"c{i}"
        elif t in NUMERIC_TYPES or t == "BOOLEAN":
            expr = f"try_cast(c{i} AS {t})"   # already cleaned; bad values -> NULL
        else:
            expr = f"CAST(c{i} AS {t})"       # bad dates stop the load
        parts.append(f"{expr} AS {_q(col)}")
    return (
        f"SELECT {', '.join(parts)} "
        f"FROM read_files({_lit(load.staged_path)}, format => 'parquet')"
    )


def _merge(cur, load: TableLoad) -> None:
    cols = list(load.df.columns)
    on = " AND ".join(f"t.{_q(k)} = s.{_q(k)}" for k in load.pk)
    update = ", ".join(f"t.{_q(c)} = s.{_q(c)}" for c in cols if c not in load.pk)
    cur.execute(
        f"MERGE INTO {load.fq} AS t "
        f"USING ({_source_sql(load)}) AS s "
        f"ON {on} "
        + (f"WHEN MATCHED THEN UPDATE SET {update} " if update else "")
        + f"WHEN NOT MATCHED THEN INSERT ({_cols(cols)}) "
        f"VALUES ({', '.join('s.' + _q(c) for c in cols)})"
    )


def _version(cur, load: TableLoad) -> int:
    cur.execute(f"DESCRIBE HISTORY {load.fq} LIMIT 1")
    return int(cur.fetchone()[0])


def _merge_all(cur, loads: list[TableLoad]) -> None:
    """MERGE in order; on failure restore the tables already changed."""
    done: list[tuple[TableLoad, int]] = []
    try:
        for load in loads:
            before = _version(cur, load)
            _merge(cur, load)
            done.append((load, before))
            logger.info(f"  Merged {len(load.df)} rows into '{load.name}'")
    except Exception:
        logger.error("  MERGE failed — restoring the tables already changed in this run")
        for load, version in reversed(done):
            try:
                cur.execute(f"RESTORE TABLE {load.fq} TO VERSION AS OF {version}")
                logger.error(f"  Restored '{load.name}' to version {version}")
            except Exception as e:
                logger.error(
                    f"  Could not restore '{load.name}': {e}. Run by hand: "
                    f"RESTORE TABLE {load.fq} TO VERSION AS OF {version}"
                )
        raise


def _remove_staged(cur, loads: list[TableLoad]) -> None:
    for load in loads:
        if not load.staged_path:
            continue
        try:
            cur.execute(f"REMOVE {_lit(load.staged_path)}")
        except Exception as e:
            logger.warning(f"  Could not delete staged file {load.staged_path}: {e}")


# ── Entry points ──────────────────────────────────────────────────────────────

def prepare_all(raw_sheets, raw_maps, step2_sheets, clean_sheets) -> list[TableLoad]:
    """Build and check every table in memory (no database). Used by the load
    and by `main.py --dry-run`."""
    run = _new_run()
    bronze, lookup = _prepare_bronze(raw_sheets, raw_maps, run)
    silver = _prepare_silver(step2_sheets, lookup, run)
    gold = _prepare_gold(clean_sheets, _load_clean_types(), lookup, run)
    for loads in (bronze, silver, gold):
        for load in loads:
            _check_table(load)
        _check_layer_fks(loads)
    return bronze + silver + gold


def run_step6_databricks(
    raw_sheets: dict[str, pd.DataFrame],
    raw_maps: dict[str, dict[str, str]],
    step2_sheets: dict[str, pd.DataFrame],
    clean_sheets: dict[str, pd.DataFrame],
) -> None:
    logger.info("=" * 50)
    logger.info(f"STEP 6 — Load into Databricks ({DATABRICKS_CATALOG})")

    all_loads = prepare_all(raw_sheets, raw_maps, step2_sheets, clean_sheets)
    run_id = all_loads[0].df["_run_id"].iloc[0]
    logger.info(f"  Run {run_id}: {len(all_loads)} tables prepared")

    staging_dir = Path(tempfile.mkdtemp(prefix="sarmaan_stage_"))
    try:
        with _connect(staging_dir) as conn, conn.cursor() as cur:
            logger.info("  Databricks connection established")
            _ensure_staging_volume(cur)
            try:
                for load in all_loads:
                    _ensure_table(cur, load)
                for load in all_loads:
                    _stage(cur, load, staging_dir, run_id)
                _merge_all(cur, all_loads)
            finally:
                _remove_staged(cur, all_loads)
    except Exception as e:
        logger.error(f"Step 6 (Databricks) FAILED: {e}")
        raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    logger.info(f"Step 6 (Databricks) complete — run {run_id}")


def _mask_issues(issues: pd.DataFrame) -> pd.DataFrame:
    """Hide failing values of identifier columns, in `value` and in the issue text."""
    issues = issues.copy()
    masked = []
    for i, row in issues.iterrows():
        cols = [row.get("column_name")] + re.findall(r"\[([^\]]+)\]", str(row.get("issue") or ""))
        hit = any(arch.is_identifier_column(c) for c in cols if c and not _blank(c))
        if hit:
            if not _blank(row.get("value")):
                issues.at[i, "value"] = arch.MASK
            issues.at[i, "issue"] = re.sub(r"'[^']*'", f"'{arch.MASK}'", str(row.get("issue") or ""))
        masked.append("true" if hit else "false")
    issues["value_masked"] = masked
    return issues


def log_validation_issues(report_path: Path) -> None:
    """Append the Step 4 report to silver.coverage_validation_issues."""
    sheets = pd.read_excel(report_path, sheet_name=None, dtype=str)
    frames = [df for df in sheets.values() if "issue" in df.columns]
    if not frames:
        return
    issues = pd.concat(frames, ignore_index=True).rename(columns={"column": "column_name"})
    run = _new_run()
    for col in ISSUES_COLUMNS:
        if col not in issues.columns:
            issues[col] = None
    issues["_run_id"] = run.run_id
    issues["logged_at"] = run.ingested_at
    issues = _mask_issues(issues)[ISSUES_COLUMNS]

    types = {c: "STRING" for c in ISSUES_COLUMNS}
    types["logged_at"] = "TIMESTAMP"
    types["value_masked"] = "BOOLEAN"
    load = TableLoad(
        DATABRICKS_SILVER_SCHEMA, ISSUES_TABLE, "validation issues",
        _as_text_frame(issues), types,
    )

    staging_dir = Path(tempfile.mkdtemp(prefix="sarmaan_stage_"))
    try:
        with _connect(staging_dir) as conn, conn.cursor() as cur:
            _ensure_staging_volume(cur)
            try:
                _ensure_table(cur, load)
                _stage(cur, load, staging_dir, run.run_id)
                cur.execute(f"INSERT INTO {load.fq} ({_cols(ISSUES_COLUMNS)}) {_source_sql(load)}")
            finally:
                _remove_staged(cur, [load])
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
    masked = (issues["value_masked"] == "true").sum()
    logger.info(f"  Recorded {len(issues)} validation issue(s) in '{load.name}' "
                f"({masked} masked; run {run.run_id})")
