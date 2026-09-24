"""
step6_db_loader.py — Append data into the existing PostgreSQL schemas.

RAW tables  ->  raw_data schema (Step 1 output, all TEXT columns):
  raw_data.coverage_household
    PK: index_uuid                       (_index + _uuid, no separator)
  raw_data.coverage_all_children
    PK: child_id_submission__uuid        (child_id + _submission__uuid, no separator)
    FK: _parent_index_submission__uuid   -> raw_data.coverage_household.index_uuid
  raw_data.coverage_net_info
    PK: net_id_submission__uuid          (net_id + _submission__uuid, no separator)
    FK: _parent_index_submission__uuid   -> raw_data.coverage_household.index_uuid
  raw_data.coverage_children_1_59
    PK: child_idd_submission__uuid       (child_idd + _submission__uuid, no separator)
    FK: _parent_index_submission__uuid   -> raw_data.coverage_household.index_uuid

CLEAN tables ->  sarmaan2data schema (Step 5 output, typed columns):
  sarmaan2data.coverage_household
    PK: concatenated_id
  sarmaan2data.coverage_all_children
    PK: child_id_childd_uuid
    FK: concatenated_id                  -> sarmaan2data.coverage_household.concatenated_id
  sarmaan2data.coverage_net_info
    PK: net_id_net_uuid
    FK: concatenated_id                  -> sarmaan2data.coverage_household.concatenated_id
  sarmaan2data.coverage_children_1_59
    PK: child_id_child_uuid
    FK: concatenated_id                  -> sarmaan2data.coverage_household.concatenated_id

RULES:
  - Pipeline appends into the EXISTING tables above. Never create a new table
    or alter an existing one once it exists.
  - If a target table already exists, every insert column MUST already exist in
    it; any mismatch is a hard error (no ALTER TABLE, no silent NULL columns).
  - Upsert (ON CONFLICT PK DO UPDATE): re-running the same state/cycle merely
    updates existing rows — no duplicates are ever created.
  - Household identity guard: a household UUID that already exists in a target
    table under a DIFFERENT primary key is rejected (aborts the sync) instead
    of being inserted as a duplicate.
  - Every column in the map must exist in the data — missing source columns are
    filled with NULL after a clear warning.
  - FK integrity is checked against the parent rows in the same batch before
    inserting child rows.
"""

import logging
import os
import re

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values, execute_batch

from config import (
    OUTPUT_DIR,
    STEP1_FILENAME,
    STEP5_FILENAME,
    MAPPING_DIR,
    PG_RAW_SCHEMA,
    PG_CLEAN_SCHEMA,
    PG_HOST,
    PG_PORT,
    PG_DB,
    PG_USER,
    PG_PASSWORD,
)

logger = logging.getLogger(__name__)

# ── Clean table definitions ────────────────────────────────────────────────────
# (sheet_name, table_name, pk_col, fk_col, parent_table, parent_pk)
CLEAN_TABLE_CHAIN = [
    (
        "Household Code",
        "coverage_household",
        "concatenated_id",
        None,
        None,
        None,
    ),
    (
        "Child_Info",
        "coverage_all_children",
        "child_id_childd_uuid",
        "concatenated_id",
        "coverage_household",
        "concatenated_id",
    ),
    (
        "Net_repeat",
        "coverage_net_info",
        "net_id_net_uuid",
        "concatenated_id",
        "coverage_household",
        "concatenated_id",
    ),
    (
        "Child_Infoo",
        "coverage_children_1_59",
        "child_id_child_uuid",
        "concatenated_id",
        "coverage_household",
        "concatenated_id",
    ),
]

# Map clean sheet name → mapping key in step5_maps
CLEAN_SHEET_TO_MAP_KEY = {
    "Household Code": "household_info",
    "Child_Info":     "child_info",
    "Net_repeat":     "net_repeat",
    "Child_Infoo":    "child_infoo",
}

# ── Raw table definitions ─────────────────────────────────────────────────────
# (sheet_name, table_name, pk_col, fk_col, parent_table, parent_pk)
RAW_TABLE_CHAIN = [
    (
        "main_sheet",
        "coverage_household",
        "index_uuid",
        None,
        None,
        None,
    ),
    (
        "child_info",
        "coverage_all_children",
        "child_id_submission__uuid",
        "_parent_index_submission__uuid",
        "coverage_household",
        "index_uuid",
    ),
    (
        "net_repeat",
        "coverage_net_info",
        "net_id_submission__uuid",
        "_parent_index_submission__uuid",
        "coverage_household",
        "index_uuid",
    ),
    (
        "child_infoo",
        "coverage_children_1_59",
        "child_idd_submission__uuid",
        "_parent_index_submission__uuid",
        "coverage_household",
        "index_uuid",
    ),
]

# Computed columns to build BEFORE mapping — (new_col, col_a, col_b, separator)
op = {
    "main_sheet": [
        # PK: _index + _uuid (no separator)
        ("index_uuid", "_index", "_uuid", ""),
    ],
    "child_info": [
        # PK: child_id + _submission__uuid (no separator)
        ("child_id_submission__uuid", "child_id", "_submission__uuid", ""),
        # FK -> household.index_uuid: _parent_index + _submission__uuid (no sep)
        ("_parent_index_submission__uuid", "_parent_index", "_submission__uuid", ""),
    ],
    "net_repeat": [
        # PK: net_id + _submission__uuid (no separator)
        ("net_id_submission__uuid", "net_id", "_submission__uuid", ""),
        # FK -> household.index_uuid: _parent_index + _submission__uuid (no sep)
        ("_parent_index_submission__uuid", "_parent_index", "_submission__uuid", ""),
    ],
    "child_infoo": [
        # PK: child_idd + _submission__uuid (no separator)
        ("child_idd_submission__uuid", "child_idd", "_submission__uuid", ""),
        # FK -> household.index_uuid: _parent_index + _submission__uuid (no sep)
        ("_parent_index_submission__uuid", "_parent_index", "_submission__uuid", ""),
    ],
}

# Household identity guard: table -> (df_uuid_col, df_pk_col, db_uuid_col, db_pk_col).
# The dataframe columns come straight from the export/mapping files (raw uses
# the pre-rename '_uuid'), while the DB columns are the stored table names.
# Prevents a household UUID that already exists under a different PK from being
# inserted again (would create a duplicate household across re-exports).
RAW_UUID_GUARD = {
    "coverage_household": ("_uuid", "index_uuid", "uuid", "index_uuid"),
}
CLEAN_UUID_GUARD = {
    "coverage_household": ("household_uuid", "concatenated_id", "household_uuid", "concatenated_id"),
}


# ── DB connection ─────────────────────────────────────────────────────────────

def _get_connection():
    # Use constants from config.py (already loaded from .env at import time)
    # rather than reading os.environ directly — avoids failures when .env has
    # not been explicitly loaded by the caller.
    return psycopg2.connect(
        host=PG_HOST,
        port=int(PG_PORT),
        database=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
    )


def _qualified(schema: str, table: str) -> str:
    """Return a schema-qualified, quoted table identifier."""
    return f'"{schema}"."{table}"'


# ── Build computed columns ────────────────────────────────────────────────────

def _build_computed_cols(
    df: pd.DataFrame,
    sheet_key: str,
) -> pd.DataFrame:
    """
    Build computed columns (concatenations) from raw source columns.
    These are required for PK/FK before the mapping runs.
    """
    df = df.copy()
    for new_col, col_a, col_b, sep in op.get(sheet_key, []):
        if new_col in df.columns:
            logger.info(f"  [{sheet_key}] '{new_col}' already exists — skipping computation")
            continue
        missing = [c for c in [col_a, col_b] if c not in df.columns]
        if missing:
            logger.warning(
                f"  [{sheet_key}] Cannot build '{new_col}' — "
                f"source columns missing: {missing}"
            )
            df[new_col] = ""
            continue
        df[new_col] = df[col_a].astype(str) + sep + df[col_b].astype(str)
        logger.info(
            f"  [{sheet_key}] Built '{new_col}' = "
            f"'{col_a}' + '{sep}' + '{col_b}' ({len(df)} rows)"
        )
    return df


# ── Column validation and gap filling ────────────────────────────────────────

def _validate_and_fill_columns(
    df: pd.DataFrame,
    mapping: dict[str, str],
    sheet_name: str,
    table_name: str,
) -> pd.DataFrame:
    """
    Check for mapped columns missing from data.
    Rather than aborting, add missing columns as empty (NULL) so the
    DB table always has every column defined in the mapping file.
    Logs a warning for each missing column so you are notified.
    """
    df = df.copy()
    missing = [src for src in mapping if src not in df.columns]
    if missing:
        logger.warning(
            f"  [{sheet_name}] {len(missing)} mapped column(s) not found in data "
            f"— will be created as NULL in '{table_name}': {missing}"
        )
        for col in missing:
            df[col] = None  # empty column — will sync as NULL to DB
    else:
        logger.info(
            f"  [{sheet_name}] All {len(mapping)} mapped columns present"
        )
    return df


# ── Table creation / verification (never mutates existing tables) ────────────

def _table_exists(cur, schema: str, table: str) -> bool:
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = %s AND table_name = %s);",
        (schema, table),
    )
    return cur.fetchone()[0]


def _create_table(
    cur,
    db_cols: list[str],
    schema: str,
    table: str,
    pk_col: str,
    fk_col: str | None,
    parent_table: str | None,
    parent_pk: str | None,
) -> None:
    """
    Create a brand-new table (raw, all TEXT). Only called when the table does
    NOT already exist — existing tables are never modified.
    """
    qualified = _qualified(schema, table)
    cols_sql = ",\n    ".join(f'"{c}" TEXT' for c in db_cols)

    constraints = [f'PRIMARY KEY ("{pk_col}")']
    if fk_col and parent_table and parent_pk:
        constraints.append(
            f'FOREIGN KEY ("{fk_col}") '
            f'REFERENCES {_qualified(schema, parent_table)}("{parent_pk}") '
            f'ON DELETE CASCADE'
        )

    constraints_sql = ",\n    ".join(constraints)

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {qualified} (
            {cols_sql},
            {constraints_sql}
        );
    """)
    logger.info(
        f"  Created '{qualified}' "
        f"(PK: {pk_col}"
        + (f", FK: {fk_col} -> {schema}.{parent_table}.{parent_pk})" if fk_col else ")")
    )


def _create_clean_table(
    cur,
    schema: str,
    table: str,
    columns: list[tuple[str, str]],
    pk_col: str,
    fk_col: str | None,
    parent_table: str | None,
    parent_pk: str | None,
) -> None:
    """
    Create a brand-new clean table with the mapping's data types.
    Only called when the table does NOT already exist — existing tables are
    never modified.
    """
    qualified = _qualified(schema, table)
    cols_sql = ",\n    ".join(f'"{name}" {typ}' for name, typ in columns)

    constraints = [f'PRIMARY KEY ("{pk_col}")']
    if fk_col and parent_table and parent_pk:
        constraints.append(
            f'FOREIGN KEY ("{fk_col}") '
            f'REFERENCES {_qualified(schema, parent_table)}("{parent_pk}") '
            f'ON DELETE CASCADE'
        )
    constraints_sql = ",\n    ".join(constraints)

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {qualified} (
            {cols_sql},
            {constraints_sql}
        );
    """)
    logger.info(
        f"  Created '{qualified}' "
        f"(PK: {pk_col}"
        + (f", FK: {fk_col} -> {schema}.{parent_table}.{parent_pk})" if fk_col else ")")
    )


def _verify_table_columns(
    cur,
    schema: str,
    table: str,
    columns: list[str],
    label: str,
) -> None:
    """
    Existing table: every column we intend to write MUST already exist.
    Raise instead of ALTER TABLE — keeps the database schema untouched.
    """
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s;",
        (schema, table),
    )
    existing = {row[0] for row in cur.fetchall()}
    missing = [c for c in columns if c not in existing]
    if missing:
        raise ValueError(
            f"[{label}] '{schema}.{table}' is missing {len(missing)} column(s) "
            f"required by the mapping: {missing}. "
            f"Add them to the database or fix the mapping file — the pipeline "
            f"will NOT alter an existing table."
        )
    logger.info(f"  [{label}] '{schema}.{table}' schema OK — all {len(columns)} columns present")


# ── Duplicate protection ─────────────────────────────────────────────────────

def _check_uuid_conflict(
    cur,
    schema: str,
    table: str,
    df: pd.DataFrame,
    df_uuid_col: str,
    df_pk_col: str,
    db_uuid_col: str,
    db_pk_col: str,
    label: str,
) -> int:
    """
    Reject any incoming household whose UUID already exists in the target table
    under a DIFFERENT primary key. This is the main guard against duplicates
    (e.g. a re-export where Kobo renumbered _index and PK would otherwise change).

    Returns the number of rows that already exist under the SAME PK
    (plain updates — no duplicates).
    """
    if df_uuid_col not in df.columns or df_pk_col not in df.columns:
        logger.warning(
            f"  [{label}] UUID guard skipped — '{df_uuid_col}' or '{df_pk_col}' "
            f"missing from data"
        )
        return 0

    pairs = []
    for u, p in zip(df[df_uuid_col], df[df_pk_col]):
        u_s = "" if pd.isna(u) else str(u).strip()
        p_s = "" if pd.isna(p) else str(p).strip()
        if u_s and u_s.lower() != "nan":
            pairs.append((u_s, p_s))
    if not pairs:
        return 0

    existing_map: dict[str, str] = {}
    unique_uuids = sorted({u for u, _ in pairs})
    chunk_size = 1000
    for i in range(0, len(unique_uuids), chunk_size):
        chunk = unique_uuids[i:i + chunk_size]
        cur.execute(
            f'SELECT "{db_uuid_col}", "{db_pk_col}" '
            f'FROM {_qualified(schema, table)} '
            f'WHERE "{db_uuid_col}"::text = ANY(%s);',
            (chunk,),
        )
        for u, p in cur.fetchall():
            if u is not None:
                existing_map[str(u)] = "" if p is None else str(p)

    conflicts = [
        (u, p, existing_map[u])
        for u, p in pairs
        if u in existing_map and str(existing_map[u]) != str(p)
    ]
    if conflicts:
        sample = conflicts[:5]
        raise ValueError(
            f"[{label}] ABORT: {len(conflicts)} household UUID(s) already exist "
            f"in '{schema}.{table}' under a DIFFERENT primary key. Inserting "
            f"them would create duplicates. Examples (uuid, new PK, existing PK): "
            f"{sample}. This usually means a re-export renumbered indices — "
            f"use the same Kobo export settings used to build the table."
        )

    existing_count = sum(1 for u, _ in pairs if u in existing_map)
    logger.info(
        f"  [{label}] UUID guard OK — {len(pairs)} households "
        f"({len(pairs) - existing_count} new, {existing_count} already present "
        f"will be updated, 0 duplicates)"
    )
    return existing_count


# ── Upsert ────────────────────────────────────────────────────────────────────

def _upsert(
    cur,
    df: pd.DataFrame,
    mapping: dict[str, str],
    table: str,
    pk_col: str,
) -> int:
    """
    Select and rename columns per mapping in exact order, then upsert.
    ON CONFLICT on pk_col: update all other columns.
    """
    ordered_src = [src for src in mapping if src in df.columns]
    df_insert = df[ordered_src].copy()
    df_insert.columns = [mapping[src] for src in ordered_src]
    df_insert = df_insert.where(pd.notna(df_insert), None)

    cols = [f'"{c}"' for c in df_insert.columns]
    rows = [tuple(row) for row in df_insert.itertuples(index=False, name=None)]

    update_cols = [c for c in df_insert.columns if c != pk_col]
    update_sql = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)

    sql = f"""
        INSERT INTO {table} ({", ".join(cols)})
        VALUES %s
        ON CONFLICT ("{pk_col}") DO UPDATE SET
            {update_sql}
    """
    execute_values(cur, sql, rows, page_size=100)
    logger.info(f"  Upserted {len(rows)} rows into '{table}'")
    return len(rows)


# ── Clean table helpers ───────────────────────────────────────────────────────

def _load_clean_types() -> dict[str, dict[str, str]]:
    """Load {sheet: {db_column_name: data_type}} from step5 mapping file."""
    result = {}
    path = MAPPING_DIR / "step_5_map_file.xlsx"
    for sheet in ["household_info", "child_info", "net_repeat", "child_infoo"]:
        df = pd.read_excel(path, sheet_name=sheet, dtype=str).fillna("")
        type_map = {}
        for _, row in df.iterrows():
            db = str(row.get("db_column_name", "")).strip()
            dt = str(row.get("data_type", "")).strip()
            if db and dt and db != "nan" and dt != "nan":
                type_map[db] = dt
        result[sheet] = type_map
    return result


def _normalize_type(raw_type: str) -> str:
    """Convert mapping data_type string to valid PostgreSQL type."""
    t = raw_type.strip().lower()
    t = re.sub(r"\s+", " ", t)

    type_map = {
        "small int": "SMALLINT",
        "smallint": "SMALLINT",
        "integer": "INTEGER",
        "int": "INTEGER",
        "bigint": "BIGINT",
        "double precision": "DOUBLE PRECISION",
        "uuid": "UUID",
        "date": "DATE",
        "timestamp without timezone": "TIMESTAMP",
        "timestamp without time zone": "TIMESTAMP",
    }
    for pattern, pg_type in type_map.items():
        if t == pattern or t.startswith(pattern + "("):
            return pg_type

    if t.startswith("character varying"):
        m = re.match(r"character\s+varying\s*\(\s*(\d+)\s*\)", t)
        if m:
            return f"VARCHAR({m.group(1)})"
        return "TEXT"

    ENUM_TYPES = {
        "enum", "enu", "consent_enum", "gender_enum", "settlement_type_enum",
        "yes_no_enum", "agree_disagree", "treat_value", "child_gender_enum",
        "child_drug_enum", "azm_card_enum", "enu-yes or no",
    }
    if t in ENUM_TYPES or t.endswith("_enum"):
        return "TEXT"

    if t.startswith("enum") or t.startswith("enu"):
        return "TEXT"

    return "TEXT"


def _upsert_clean(
    cur,
    df: pd.DataFrame,
    columns: list[tuple[str, str]],
    table: str,
    pk_col: str,
) -> int:
    """Upsert into clean table with typed columns."""
    col_names = [name for name, _ in columns]
    col_types = {name: typ for name, typ in columns}

    df_clean = df[[c for c in col_names if c in df.columns]].copy()
    # Replace pandas/ numpy NaN with Python None
    df_clean = df_clean.where(pd.notna(df_clean), None)

    cols = [f'"{c}"' for c in df_clean.columns]

    # Build rows with proper type handling
    rows = []
    for row in df_clean.itertuples(index=False, name=None):
        clean_row = []
        for j, val in enumerate(row):
            col_name = df_clean.columns[j]
            raw_type = col_types.get(col_name, "TEXT")
            t = raw_type.upper()

            if val is None:
                clean_row.append(None)
                continue

            s = str(val).strip()
            if s == "" or s.lower() == "nan":
                clean_row.append(None)
                continue

            if t in ("SMALLINT", "INTEGER", "BIGINT"):
                try:
                    clean_row.append(str(int(float(s))))
                except (ValueError, TypeError):
                    clean_row.append(None)
            elif t == "DOUBLE PRECISION":
                try:
                    clean_row.append(str(float(s)))
                except (ValueError, TypeError):
                    clean_row.append(None)
            elif t == "DATE":
                # Postgres DATE rejects datetime strings — strip the time component.
                clean_row.append(s[:10] if len(s) >= 10 else s)
            elif t == "TIMESTAMP":
                s = s.replace("T", " ")
                tz_m = re.search(r"[+\-]\d{2}:\d{2}$", s)
                if tz_m:
                    s = s[:tz_m.start()]
                elif s.endswith("Z"):
                    s = s[:-1]
                clean_row.append(s)
            elif t.startswith("VARCHAR"):
                m = re.match(r"varchar\(\s*(\d+)\s*\)", t, re.IGNORECASE)
                if m:
                    max_len = int(m.group(1))
                    if len(s) > max_len:
                        logger.warning(
                            f"  [{table}] Column '{col_name}': truncating {len(s)} chars to {max_len} — '{s[:50]}...'"
                        )
                        s = s[:max_len]
                clean_row.append(s)
            else:
                clean_row.append(s)

        rows.append(tuple(clean_row))

    update_cols = [c for c in df_clean.columns if c != pk_col]
    update_sql = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)

    sql = f"""
        INSERT INTO {table} ({", ".join(cols)})
        VALUES ({", ".join(["%s"] * len(cols))})
        ON CONFLICT ("{pk_col}") DO UPDATE SET
            {update_sql}
    """
    try:
        execute_batch(cur, sql, rows, page_size=100)
    except Exception as e:
        if "value too long" in str(e).lower() or "varchar" in str(e).lower():
            logger.error(f"  [{table}] Finding oversized VARCHAR columns...")
            for j, col_name in enumerate(df_clean.columns):
                raw_type = col_types.get(col_name, "TEXT")
                m = re.match(r"varchar\(\s*(\d+)\s*\)", raw_type, re.IGNORECASE)
                if m:
                    max_len = int(m.group(1))
                    for i, row_tuple in enumerate(rows):
                        val = row_tuple[j]
                        if val is not None and len(str(val)) > max_len:
                            logger.error(
                                f"  Col '{col_name}' (max {max_len}): row {i} has {len(str(val))} chars = '{str(val)[:80]}'"
                            )
                            break
        raise
    logger.info(f"  Upserted {len(rows)} rows into '{table}'")
    return len(rows)


# ── Raw sync ──────────────────────────────────────────────────────────────────

def _check_fk_integrity(
    df: pd.DataFrame,
    fk_col: str,
    parent_df: pd.DataFrame,
    parent_pk: str,
    sheet_name: str,
    parent_table: str,
) -> None:
    """Log FK values that have no matching parent PK."""
    if not fk_col:
        return
    # A child row with no FK at all is also an orphan - Postgres would accept
    # a NULL FK, so it has to be caught here.
    blank = df[fk_col].isna() | (df[fk_col].astype(str).str.strip().isin(["", "nan", "None"]))
    if blank.any():
        raise ValueError(
            f"FK violation: {int(blank.sum())} row(s) in '{sheet_name}' have an empty "
            f"'{fk_col}' (no parent household in '{parent_table}')"
        )
    fk_vals = set(str(v) for v in df[fk_col].dropna().unique() if str(v).strip())
    parent_pk_vals = set(str(v) for v in parent_df[parent_pk].dropna().unique() if str(v).strip())
    missing = fk_vals - parent_pk_vals
    if missing:
        logger.error(
            f"  [{sheet_name}] {len(missing)} FK value(s) in '{fk_col}' "
            f"have no match in '{parent_table}.{parent_pk}'"
        )
        for v in sorted(missing)[:10]:
            logger.error(f"    FK='{v}' — no parent found")
        if len(missing) > 10:
            logger.error(f"    ... and {len(missing) - 10} more")
        raise ValueError(
            f"FK violation: {len(missing)} orphaned row(s) in '{sheet_name}' "
            f"— FK '{fk_col}' values missing from '{parent_table}.{parent_pk}'"
        )
    logger.info(
        f"  [{sheet_name}] FK integrity OK — "
        f"{len(fk_vals)} unique FK values all present in '{parent_table}'"
    )


def _sync_raw(
    cur,
    sheets: dict[str, pd.DataFrame],
    maps: dict[str, dict[str, str]],
) -> None:
    schema = PG_RAW_SCHEMA
    logger.info(f"  --- RAW SYNC (raw tables -> {schema}.*) ---")

    # Normalise map key: load_step1_maps() returns "main" but RAW_TABLE_CHAIN
    # and the Step-1 export sheet name are both "main_sheet". Accept either.
    if "main" in maps and "main_sheet" not in maps:
        maps = {("main_sheet" if k == "main" else k): v for k, v in maps.items()}

    # Step 1: Build computed columns on all sheets
    logger.info("  Building computed columns...")
    for sheet_key in ["main_sheet", "child_info", "net_repeat", "child_infoo"]:
        if sheet_key in sheets:
            sheets[sheet_key] = _build_computed_cols(sheets[sheet_key], sheet_key)

    # Step 2: Validate and fill missing columns on ALL sheets
    logger.info("  Validating columns and filling gaps...")
    for sheet_name, table, pk_col, fk_col, parent_table, parent_pk in RAW_TABLE_CHAIN:
        df = sheets.get(sheet_name, pd.DataFrame())
        if df.empty:
            raise ValueError(f"SYNC ABORTED — '{sheet_name}' is empty")
        mapping = maps.get(sheet_name, {})
        if not mapping:
            raise ValueError(f"SYNC ABORTED — No mapping for '{sheet_name}'")
        sheets[sheet_name] = _validate_and_fill_columns(df, mapping, sheet_name, table)
    logger.info("  Column validation complete")

    # Step 3: Upsert in chain order (households first, then children)
    for sheet_name, table, pk_col, fk_col, parent_table, parent_pk in RAW_TABLE_CHAIN:
        df = sheets[sheet_name]
        mapping = maps[sheet_name]

        # DB column names in exact mapping order — ALL mapped cols
        db_cols = [mapping[src] for src in mapping]

        if not _table_exists(cur, schema, table):
            _create_table(cur, db_cols, schema, table, pk_col, fk_col, parent_table, parent_pk)
        else:
            logger.info(f"  '{schema}.{table}' exists — verifying schema")
            _verify_table_columns(cur, schema, table, db_cols, sheet_name)

        # Household duplicate guard (raw PK is index_uuid, identity is _uuid)
        if table in RAW_UUID_GUARD:
            _check_uuid_conflict(cur, schema, table, df, *RAW_UUID_GUARD[table], sheet_name)

        # Check FK integrity BEFORE insert (against in-memory parent data)
        if fk_col and parent_table:
            parent_sheet = next(
                (s for s, t, _, _, _, _ in RAW_TABLE_CHAIN if t == parent_table),
                None
            )
            if parent_sheet and parent_sheet in sheets:
                _check_fk_integrity(
                    df, fk_col, sheets[parent_sheet], parent_pk,
                    sheet_name, f"{schema}.{parent_table}",
                )

        _upsert(cur, df, mapping, _qualified(schema, table), pk_col)


# ── Clean sync ────────────────────────────────────────────────────────────────

def _sync_clean(
    cur,
    sheets: dict[str, pd.DataFrame],
    types: dict[str, dict[str, str]],
) -> None:
    schema = PG_CLEAN_SCHEMA
    logger.info(f"  --- CLEAN SYNC (clean tables -> {schema}.*) ---")

    for sheet_name, table, pk_col, fk_col, parent_table, parent_pk in CLEAN_TABLE_CHAIN:
        df = sheets.get(sheet_name, pd.DataFrame())
        if df.empty:
            raise ValueError(f"CLEAN SYNC ABORTED — '{sheet_name}' is empty")

        map_key = CLEAN_SHEET_TO_MAP_KEY[sheet_name]
        type_map = types.get(map_key, {})

        # Build column list: (db_column_name, postgres_type) in dataframe order.
        # Start with columns present in the dataframe, then append any DB columns
        # that the type_map declares but are absent from the output. These extra
        # columns are written as NULL so the insert stays complete.
        columns = []
        for col in df.columns:
            raw_type = type_map.get(col, "TEXT")
            pg_type = _normalize_type(raw_type)
            columns.append((col, pg_type))

        df_cols_set = set(df.columns)
        for db_col, raw_type in type_map.items():
            if db_col not in df_cols_set:
                pg_type = _normalize_type(raw_type)
                columns.append((db_col, pg_type))
                df[db_col] = None
                logger.warning(
                    f"  [{sheet_name}] DB column '{db_col}' missing from step5 output "
                    f"— inserted as NULL (check mapping file for duplicate source labels)"
                )

        if not columns:
            raise ValueError(f"CLEAN SYNC ABORTED — No columns for '{sheet_name}'")

        if not _table_exists(cur, schema, table):
            _create_clean_table(
                cur, schema, table, columns, pk_col, fk_col, parent_table, parent_pk
            )
        else:
            logger.info(f"  '{schema}.{table}' exists — verifying schema")
            _verify_table_columns(cur, schema, table, [c for c, _ in columns], sheet_name)

        # Household duplicate guard (clean PK is concatenated_id, identity is household_uuid)
        if table in CLEAN_UUID_GUARD:
            _check_uuid_conflict(cur, schema, table, df, *CLEAN_UUID_GUARD[table], sheet_name)

        # Check FK integrity
        if fk_col and parent_table:
            parent_sheet = next(
                (s for s, t, _, _, _, _ in CLEAN_TABLE_CHAIN if t == parent_table),
                None
            )
            if parent_sheet and parent_sheet in sheets:
                _check_fk_integrity(
                    df, fk_col, sheets[parent_sheet], parent_pk,
                    sheet_name, f"{schema}.{parent_table}",
                )

        _upsert_clean(cur, df, columns, _qualified(schema, table), pk_col)


# ── Entry point ───────────────────────────────────────────────────────────────

def run_step6(
    raw_sheets: dict[str, pd.DataFrame] | None = None,
    clean_sheets: dict[str, pd.DataFrame] | None = None,
    raw_maps: dict[str, dict[str, str]] | None = None,
    clean_maps: dict[str, dict[str, str]] | None = None,
) -> None:
    logger.info("=" * 50)
    logger.info("STEP 6 — Append to PostgreSQL")

    if raw_sheets is None:
        path = OUTPUT_DIR / STEP1_FILENAME
        if not path.exists():
            raise FileNotFoundError(f"Step 1 output not found: {path}")
        logger.info(f"  Loading raw data from: {path}")
        raw_sheets = pd.read_excel(path, sheet_name=None, dtype=str)

    conn = _get_connection()
    cur = conn.cursor()
    logger.info("  Database connection established")

    try:
        _sync_raw(cur, raw_sheets, raw_maps)

        # Guard: both clean_sheets and clean_maps must be supplied together.
        if bool(clean_sheets) ^ bool(clean_maps):
            raise ValueError(
                "run_step6: supply both clean_sheets and clean_maps together, "
                "or omit both. Got only one of them."
            )
        if clean_sheets and clean_maps:
            types = _load_clean_types()
            _sync_clean(cur, clean_sheets, types)

        conn.commit()
        logger.info("  Sync committed successfully")

        logger.info("Step 6 complete")

    except Exception as e:
        conn.rollback()
        logger.error(f"Step 6 FAILED — rolled back: {e}")
        raise
    finally:
        cur.close()
        conn.close()