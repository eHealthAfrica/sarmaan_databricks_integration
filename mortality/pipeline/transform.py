"""
transform.py — Build every Mortality table in memory from the Kobo export, and
check them. Nothing here talks to Databricks, so it can be tested on a laptop.

Layers (the rules are in mortality/architecture.py; see the Mortality ERD):
  bronze      the export as downloaded: every column STRING, names lowercased
              (meta/rootUuid -> meta_rootuuid), plus lineage columns.
              Appended on every run, never updated.
  silver      every submission, the Postgres column names and values (the map
              files' transforms, as the Postgres stager applies them), all
              STRING, keyed on root_uuid (+ mother_code / pregnancy_code).
  gold        approved submissions only, typed, no identifier columns.
  restricted  the identifier columns of the gold rows, same key as gold.

Values, as in mortality/stager_auditor_mortality.py:
  - each keep/review row of map/mortality/<sheet>_map.csv: export column ->
    DB column through its transform (recodes.py);
  - household lga / ward / community: first non-blank of several form fields;
    household_no_category from hh_category; state from the round's config
    when the export leaves it blank (the current form has no state question);
  - women and pregnancies take state, lga, ward and community from their
    household; concatenated_id as in Postgres.
Columns and gold types come from map/mortality/gold_types.csv (Postgres order).

Checks: a key that is blank or repeated, a woman without her household, or a
pregnancy without its woman BLOCKS the run (nothing is loaded). Mapped columns
missing from the export and values that do not fit their gold type are
WARNINGS: the run continues and they load as NULL.
"""

import csv
import logging
import re
from dataclasses import dataclass, field

import pandas as pd

import architecture as arch

from . import recodes
from .settings import APPROVED, GOLD_TYPES_FILE, MAP_FILES

logger = logging.getLogger(__name__)

SHEETS = ["household", "female", "pregnancy"]
SOURCE_SYSTEM = "kobotoolbox"
ISSUES_TABLE = "mortality_validation_issues"
ISSUE_COLUMNS = ["_run_id", "logged_at", "table_name", "layer", "check_type", "blocking",
                 "row_key", "column_name", "value", "value_masked", "issue"]

# Columns in the export that identify the submission and its approval
ROOT = {"household": "meta/rootUuid", "*": "_submission_meta/rootUuid"}
SUBMISSION_UUID = {"household": "_uuid", "*": "_submission__uuid"}
STATUS = {"household": "_validation_status", "*": "_submission__validation_status"}
# Household fields built from several form fields (first non-blank wins)
COALESCE = {
    "lga": (["lgas", "lga_confirm", "lgas_k"], recodes.simple_capitalize),
    "ward": (["ward", "wards", "ward_confirm"], recodes.underscore_to_space),
    "community": (["community_confirm", "community_name", "check_hh"], recodes.underscore_to_space),
}
# Household columns the pipeline fills itself, so a missing export column is
# not reported for them (state comes from the round's config when blank)
HOUSEHOLD_FILLED = set(COALESCE) | {"state", "household_no_category"}
# Copied from the household onto women and pregnancies
FROM_HOUSEHOLD = ["state", "lga", "ward", "community"]
# Kobo system columns kept in Postgres, and concatenated_id = <uuid>_<index>
SYSTEM = {
    "household": {"household_uuid": "_uuid", "index": "_index", "submission_id": "_id"},
    "female": {"female_uuid": "_submission__uuid", "parent_index": "_parent_index",
               "index": "_index", "submission_id": "_submission__id"},
    "pregnancy": {"pregnancy_uuid": "_submission__uuid", "parent_index": "_parent_index",
                  "index": "_index", "submission_id": "_submission__id"},
}
CONCATENATED_ID = {
    "household": ("household_uuid", "index"),
    "female": ("female_uuid", "parent_index"),
    "pregnancy": ("pregnancy_uuid", "parent_index"),
}


@dataclass
class Table:
    layer: str
    sheet: str
    name: str
    df: pd.DataFrame                  # values are str or None
    types: dict[str, str]
    pk: list[str] = field(default_factory=list)
    fk: list[str] = field(default_factory=list)
    parent: str | None = None         # parent table name
    parent_pk: list[str] = field(default_factory=list)
    append: bool = False              # bronze: INSERT only
    parent_layer: str | None = None   # when the parent is in another layer

    @property
    def schema(self) -> str:
        return self.layer

    @property
    def parent_schema(self) -> str:
        return self.parent_layer or self.layer


@dataclass
class RunInfo:
    run_id: str
    ingested_at: str                  # UTC, "YYYY-MM-DD HH:MM:SS"
    source_asset: str
    pipeline_version: str


@dataclass
class Built:
    tables: list[Table]
    issues: pd.DataFrame

    @property
    def blocking(self) -> pd.DataFrame:
        return self.issues[self.issues["blocking"] == "true"]


def _get(mapping: dict, sheet: str) -> str:
    return mapping.get(sheet, mapping.get("*"))


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "nan", "None")


def _text(df: pd.DataFrame) -> pd.DataFrame:
    """All values as str, blanks as None."""
    df = df.astype(object)
    elementwise = getattr(df, "map", None) or df.applymap   # pandas < 2.1 has only applymap
    return elementwise(lambda v: None if _blank(v) else str(v).strip())


# ── Inputs ────────────────────────────────────────────────────────────────────

def gold_types() -> dict[str, list[dict]]:
    out = {s: [] for s in SHEETS}
    with open(GOLD_TYPES_FILE, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["table"]].append(row)
    return out


def map_rows(sheet: str) -> list[dict]:
    """The map rows the Postgres stager applies directly (keep/review, with an
    export column, not derived/coalesced)."""
    with open(MAP_FILES[sheet], encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows
            if r["action"].strip().lower() in ("keep", "review")
            and r["kobo_name"].strip() and r["db_name"].strip()
            and not r["transform"].strip().startswith(("derived", "coalesce"))]


def split_sheets(sheets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Find the household, female and pregnancy sheets by their columns, so a
    renamed sheet does not break the run."""
    found = {}
    for name, df in sheets.items():
        cols = set(df.columns)
        if "_parent_index" not in cols and "_uuid" in cols:
            sheet = "household"
        elif "preg_id" in cols or "motherid" in cols:
            sheet = "pregnancy"
        elif "mother_id" in cols or "female_position" in cols:
            sheet = "female"
        else:
            logger.info(f"  Export sheet '{name}' is not used")
            continue
        if sheet in found:
            raise ValueError(f"Two export sheets look like the {sheet} sheet: '{found[sheet][0]}' and '{name}'")
        found[sheet] = (name, df)
    missing = [s for s in SHEETS if s not in found]
    if missing:
        raise ValueError(f"Export has no {', '.join(missing)} sheet. Sheets: {list(sheets)}. "
                         f"Is the saved export set to XML values and headers?")
    for s in SHEETS:
        logger.info(f"  {s}: sheet '{found[s][0]}', {len(found[s][1])} rows")
    return {s: _text(found[s][1]) for s in SHEETS}


# ── Keys ──────────────────────────────────────────────────────────────────────

def _roots(export: dict[str, pd.DataFrame]) -> dict[str, list]:
    """rootUuid for every row of every sheet. Kobo sets meta/rootUuid to
    'uuid:' + _uuid on first submission and keeps it on edits; a blank one is
    filled the same way, and women/pregnancies take their household's (the
    female sheet has no rootUuid column of its own)."""
    hh = export["household"]
    for col in (ROOT["household"], SUBMISSION_UUID["household"]):
        if col not in hh.columns:
            raise ValueError(f"Household sheet has no '{col}' column")
    hh_roots = [r if r else (f"uuid:{u}" if u else None) for r, u in zip(hh[ROOT["household"]], hh["_uuid"])]
    by_uuid = {u: r for u, r in zip(hh["_uuid"], hh_roots) if u}
    out = {"household": hh_roots}
    for s in ("female", "pregnancy"):
        df = export[s]
        own = df[ROOT["*"]] if ROOT["*"] in df.columns else pd.Series([None] * len(df), index=df.index)
        out[s] = [o or by_uuid.get(u) for o, u in zip(own, df[SUBMISSION_UUID["*"]])]
    return out


def _approved_roots(export: dict[str, pd.DataFrame], roots: dict[str, list]) -> set:
    hh = export["household"]
    status = STATUS["household"]
    if status not in hh.columns:
        raise ValueError(f"Household sheet has no '{status}' column: cannot tell which submissions are approved")
    return {r for r, st in zip(roots["household"], hh[status]) if r and st == APPROVED}


# ── Layers ────────────────────────────────────────────────────────────────────

def _bronze(export, roots, run: RunInfo) -> list[Table]:
    tables = []
    for s in SHEETS:
        df = export[s].copy()
        df[_get(ROOT, s)] = roots[s]
        names = [arch.bronze_name(c) for c in df.columns]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            raise ValueError(f"[{s}] export columns collide once lowercased: {repeated}")
        df.columns = names
        meta = {"_ingested_at": run.ingested_at, "_run_id": run.run_id, "_source_system": SOURCE_SYSTEM,
                "_source_asset": run.source_asset, "_pipeline_version": run.pipeline_version}
        for k, v in meta.items():
            df[k] = v
        types = {c: "STRING" for c in df.columns}
        types["_ingested_at"] = "TIMESTAMP"
        tables.append(Table("bronze", s, arch.TABLES[s], df, types, append=True))
    return tables


def _silver(export, roots, types, run: RunInfo, default_state: str, issues: list) -> dict[str, pd.DataFrame]:
    """Silver frames keyed by sheet (all STRING, Postgres names and values, root_uuid first)."""
    frames = {}
    for s in SHEETS:
        src = export[s]
        out = pd.DataFrame(index=src.index)
        missing = []
        for r in map_rows(s):
            col, name = r["kobo_name"].strip(), r["db_name"].strip()
            if col in src.columns:
                out[name] = recodes.apply(src[col], r["transform"])
            elif name not in out.columns:
                out[name] = None
                if not (s == "household" and name in HOUSEHOLD_FILLED):
                    missing.append(f"{name} <- {col}")
        if s == "household":
            for name, (cols, fn) in COALESCE.items():
                out[name] = fn(recodes.coalesce(src, cols))
            if "hh_category" in src.columns:
                out["household_no_category"] = recodes.hh_category_range(src["hh_category"])
            state = out["state"] if "state" in out.columns else pd.Series([None] * len(out), index=out.index)
            out["state"] = [v if not _blank(v) else (default_state or None) for v in state]
        for name, col in SYSTEM[s].items():
            out[name] = recodes.passthrough(src[col]) if col in src.columns else None
        a, b = CONCATENATED_ID[s]
        out["concatenated_id"] = [f"{x}_{y}" if x and y else None for x, y in zip(out[a], out[b])]
        if missing:
            issues.append(_issue(run, arch.TABLES[s], "silver", "mapped_column_missing", False, None, None, None,
                                 f"{len(missing)} mapped column(s) not in the export, loaded as NULL: "
                                 f"{', '.join(missing)}"))
            logger.warning(f"  [{s}] {len(missing)} mapped column(s) not in the export — NULL: {missing}")
        out.insert(0, arch.ROOT_UUID, roots[s])
        frames[s] = out

    # Location is only on the household sheet
    hh = frames["household"].drop_duplicates(arch.ROOT_UUID).set_index(arch.ROOT_UUID)
    for s in ("female", "pregnancy"):
        for col in FROM_HOUSEHOLD:
            frames[s][col] = frames[s][arch.ROOT_UUID].map(hh[col])

    # Postgres column order from gold_types.csv; any column not built is NULL
    for s in SHEETS:
        cols = [arch.ROOT_UUID] + [r["db_name"] for r in types[s]]
        for c in cols:
            if c not in frames[s].columns:
                frames[s][c] = None
        frames[s] = frames[s][cols].copy()
        frames[s][arch.RUN_ID] = run.run_id
    return frames


def _typed(value, sql_type: str):
    """(clean value as text, ok). Same rules as the AMR gold loader."""
    if value is None:
        return None, True
    s = str(value).strip()
    if sql_type in ("INT", "BIGINT"):
        try:
            f = float(s)
            return (str(int(f)), True) if f == int(f) else (None, False)
        except (ValueError, OverflowError):
            return None, False
    if sql_type == "DOUBLE":
        try:
            return str(float(s)), True
        except ValueError:
            return None, False
    if sql_type == "DATE":
        d = pd.to_datetime(s[:10], errors="coerce", format="%Y-%m-%d")
        return (d.strftime("%Y-%m-%d"), True) if not pd.isna(d) else (None, False)
    if sql_type == "TIMESTAMP_NTZ":
        t = s.replace("T", " ")
        t = re.sub(r"(Z|[+\-]\d{2}(:?\d{2})?)$", "", t)   # keep the time Kobo recorded
        d = pd.to_datetime(t, errors="coerce")
        return (d.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], True) if not pd.isna(d) else (None, False)
    return s, True


def _gold(silver, approved, types, run: RunInfo, issues: list) -> list[Table]:
    gold, restricted = [], []
    for s in SHEETS:
        df = silver[s][silver[s][arch.ROOT_UUID].isin(approved)].copy()
        col_types = {arch.ROOT_UUID: "STRING", arch.RUN_ID: "STRING"}
        for row in types[s]:
            name = row["db_name"]
            t = "STRING" if name in arch.PHONE_COLUMNS else row["type"]
            col_types[name] = t
            if t == "STRING":
                continue
            cleaned = [_typed(v, t) for v in df[name]]
            bad = [(k, v) for k, v, (_, ok) in zip(df[arch.ROOT_UUID], df[name], cleaned) if not ok]
            if bad:
                ident = name in arch.IDENTIFIERS.get(s, [])
                issues.append(_issue(run, arch.TABLES[s], "gold", "type", False, bad[0][0], name,
                                     arch.MASK if ident else bad[0][1],
                                     f"{len(bad)} value(s) are not {t}; loaded as NULL"))
            df[name] = [c for c, _ in cleaned]

        pk, fk = arch.KEYS[s]
        parent = arch.PARENT[s]
        ids = arch.IDENTIFIERS.get(s, [])
        missing = [c for c in ids if c not in df.columns]
        if missing:
            raise ValueError(f"[{s}] identifier column(s) {missing} are not in the mapping")
        if ids:
            rdf = df[pk + ids + [arch.RUN_ID]].copy()
            restricted.append(Table(
                "restricted", s, arch.restricted_table(s), rdf, {c: col_types[c] for c in rdf.columns},
                pk, pk, arch.TABLES[s], pk, parent_layer="gold"))
        gdf = df.drop(columns=ids)
        gold.append(Table(
            "gold", s, arch.TABLES[s], gdf, {c: col_types[c] for c in gdf.columns}, pk, fk,
            arch.TABLES[parent] if parent else None, arch.PARENT_KEYS.get(s, [])))
    return gold + restricted


def _silver_tables(silver) -> list[Table]:
    out = []
    for s in SHEETS:
        pk, fk = arch.KEYS[s]
        parent = arch.PARENT[s]
        df = silver[s]
        out.append(Table("silver", s, arch.TABLES[s], df, {c: "STRING" for c in df.columns}, pk, fk,
                         arch.TABLES[parent] if parent else None, arch.PARENT_KEYS.get(s, [])))
    return out


# ── Checks ────────────────────────────────────────────────────────────────────

def _issue(run, table, layer, check, blocking, key, column, value, text) -> dict:
    return {"_run_id": run.run_id, "logged_at": run.ingested_at, "table_name": table, "layer": layer,
            "check_type": check, "blocking": "true" if blocking else "false",
            "row_key": None if key is None else str(key), "column_name": column,
            "value": None if value is None else str(value),
            "value_masked": "true" if value == arch.MASK else "false", "issue": text}


def _key_text(row) -> str:
    return " | ".join(str(v) for v in row)


def _check_keys(t: Table, run, issues: list) -> None:
    if not t.pk:
        return
    keys = t.df[t.pk]
    blank = keys.apply(lambda c: c.map(_blank)).any(axis=1)
    for _, row in t.df[blank].iterrows():
        issues.append(_issue(run, t.name, t.layer, "blank_key", True, _key_text(row[t.pk]), ", ".join(t.pk),
                             None, f"Row has an empty key ({', '.join(t.pk)})"))
    dup = t.df[~blank & t.df.duplicated(subset=t.pk, keep=False)]
    for key, group in dup.groupby(t.pk, sort=True):
        key = key if isinstance(key, tuple) else (key,)
        issues.append(_issue(run, t.name, t.layer, "duplicate_key", True, _key_text(key), ", ".join(t.pk),
                             None, f"{len(group)} rows share this key"))


def _check_parents(tables: list[Table], run, issues: list) -> None:
    by_name = {(t.layer, t.name): t for t in tables}
    for t in tables:
        if not t.fk or t.layer == "restricted":
            continue
        parent = by_name[(t.layer, t.parent)]
        parent_keys = set(map(tuple, parent.df[t.parent_pk].itertuples(index=False, name=None)))
        for key in t.df[t.fk].itertuples(index=False, name=None):
            if tuple(key) not in parent_keys:
                issues.append(_issue(run, t.name, t.layer, "no_parent", True, _key_text(key), ", ".join(t.fk),
                                     None, f"No row in {t.layer}.{t.parent} with this key"))


# ── Entry point ───────────────────────────────────────────────────────────────

def build(sheets: dict[str, pd.DataFrame], run: RunInfo, default_state: str = "") -> Built:
    export = split_sheets(sheets)
    types = gold_types()
    roots = _roots(export)
    approved = _approved_roots(export, roots)
    logger.info(f"  {len(approved)} of {len(export['household'])} household submission(s) approved")

    issues: list[dict] = []
    bronze = _bronze(export, roots, run)
    silver = _silver(export, roots, types, run, default_state, issues)
    tables = bronze + _silver_tables(silver) + _gold(silver, approved, types, run, issues)
    for t in tables:
        if t.layer in ("silver", "gold"):
            _check_keys(t, run, issues)
    _check_parents(tables, run, issues)
    for t in tables:
        t.df = _text(t.df)
    return Built(tables, pd.DataFrame(issues, columns=ISSUE_COLUMNS))
