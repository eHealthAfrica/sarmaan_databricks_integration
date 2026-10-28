"""
transform.py — Build every Pharmacy table in memory from the Kobo export, and
check them. Nothing here talks to Databricks, so it can be tested on a laptop.

The form has no repeats: one row per pharmacy or drug shop, one table per
layer (the rules are in pharmacy/architecture.py; see the Pharmacy ERD):
  bronze      the export as downloaded: every column STRING, names lowercased
              (meta/rootUuid -> meta_rootuuid), plus lineage columns.
              Appended on every run, never updated.
  silver      every submission, the Postgres column names and values, all
              STRING, keyed on root_uuid.
  gold        approved submissions only, typed, no identifier columns.
  restricted  the identifier columns of the gold rows, same key as gold.

Values, as in "pharmacy/pharmacy_stager_auditor zamfara.py" (keep the two in
step until the Postgres scripts are retired):
  - each keep row of map/pharmacy/zamfara_pharmacy_map.csv: export column ->
    DB column;
  - lga: numeric codes from older form versions -> LGA name
    (zamfara_pharmacy_lga_lookup.csv);
  - yes/no answers -> Yes/No; settlement type and gender capitalised;
    multiple-choice option columns 0/1 -> No/Yes;
  - start_time, end_time, date_of_consent, training_year -> date only;
  - cycle from the round's config ("Year 1"): the form has no cycle question;
  - concatenated_id = <uuid>_<index>, as in Postgres.
Columns and gold types come from map/pharmacy/gold_types.csv (Postgres order).

Checks: a key that is blank or repeated BLOCKS the run (nothing is loaded).
Mapped columns missing from the export, LGA codes not in the lookup and
values that do not fit their gold type are WARNINGS: the run continues.
"""

import csv
import logging
import re
from dataclasses import dataclass, field

import pandas as pd

import architecture as arch

from .settings import APPROVED, GOLD_TYPES_FILE, LGA_LOOKUP_FILE, MAP_FILE

logger = logging.getLogger(__name__)

SHEET = "pharmacy"
SOURCE_SYSTEM = "kobotoolbox"
ISSUES_TABLE = "pharmacy_validation_issues"
ISSUE_COLUMNS = ["_run_id", "logged_at", "table_name", "layer", "check_type", "blocking",
                 "row_key", "column_name", "value", "value_masked", "issue"]

ROOT, SUBMISSION_UUID, STATUS = "meta/rootUuid", "_uuid", "_validation_status"

# ── The Postgres stager's value rules ────────────────────────────────────────
YESNO_COLUMNS = [
    "consent", "witness", "know_antibiotics", "trained_antibiotics_use",
    "prescriptions_before_antibiotics", "sell_less_than_required_antibiotics",
    "combine_antibiotics", "antibiotics_prevent_infection",
    "administer_antibiotic_injections",
]
YESNO = {"yes": "Yes", "no": "No"}
VALUE_RECODES = {
    "settlement_type": {"rural": "Rural", "urban": "Urban"},
    "pharmacist_gender": {"male": "Male", "female": "Female"},
}
# Multiple-choice option columns: Kobo exports 0/1, Postgres stores No/Yes
BINARY_PREFIXES = (
    "define_antibiotics_", "prescriptions_before_antibiotics_reason_",
    "prescriptions_before_antibiotics_no_reason_", "suspected_conditions_antibiotics_",
    "administer_antibiotic_injections_name_", "antibiotics_in_shop_",
)
BINARY = {"0": "No", "1": "Yes", "0.0": "No", "1.0": "Yes"}
DATE_ONLY = ["start_time", "end_time", "date_of_consent", "training_year"]
# Kobo system columns kept in Postgres
SYSTEM = {"pharmacy_uuid": "_uuid", "submission_id": "_id", "index": "_index"}
# Filled by the pipeline, so a missing export column is not reported for them
FILLED = {"cycle", "concatenated_id"} | set(SYSTEM)


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


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "nan", "None")


def _text(df: pd.DataFrame) -> pd.DataFrame:
    """All values as str, blanks as None."""
    df = df.astype(object)
    elementwise = getattr(df, "map", None) or df.applymap   # pandas < 2.1 has only applymap
    return elementwise(lambda v: None if _blank(v) else str(v).strip())


def _recode(series: pd.Series, mapping: dict, lower: bool = True) -> pd.Series:
    return series.map(lambda v: None if _blank(v) else mapping.get(str(v).strip().lower() if lower
                                                                  else str(v).strip(), str(v).strip()))


def _date_only(series: pd.Series) -> pd.Series:
    out = pd.to_datetime(series, format="mixed", errors="coerce").dt.strftime("%Y-%m-%d")
    return out.where(out.notna(), None)


# ── Inputs ────────────────────────────────────────────────────────────────────

def gold_types() -> list[dict]:
    with open(GOLD_TYPES_FILE, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def map_rows() -> list[dict]:
    """The keep rows of the Pharmacy map that have an export column."""
    with open(MAP_FILE, encoding="utf-8-sig") as fh:
        return [r for r in csv.DictReader(fh)
                if r["action"].strip().lower() == "keep" and r["kobo_name"].strip() and r["db_name"].strip()]


def lga_lookup() -> dict[str, str]:
    with open(LGA_LOOKUP_FILE, encoding="utf-8-sig") as fh:
        return {r["lga_code"].strip(): r["lga_name"].strip() for r in csv.DictReader(fh)}


def pick_sheet(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """The pharmacy sheet: the one with _uuid and no _parent_index (the form
    has no repeats, but a sheet name can change)."""
    found = [(n, df) for n, df in sheets.items() if "_uuid" in df.columns and "_parent_index" not in df.columns]
    if len(found) != 1:
        raise ValueError(f"Expected one submission sheet, found {[n for n, _ in found]}. Sheets: {list(sheets)}. "
                         f"Is the saved export set to XML values and headers?")
    name, df = found[0]
    logger.info(f"  pharmacy: sheet '{name}', {len(df)} rows")
    return _text(df)


# ── Layers ────────────────────────────────────────────────────────────────────

def _roots(src: pd.DataFrame) -> list:
    """Kobo sets meta/rootUuid to 'uuid:' + _uuid on first submission and keeps
    it on edits; a blank one is filled the same way."""
    if SUBMISSION_UUID not in src.columns:
        raise ValueError(f"Pharmacy sheet has no '{SUBMISSION_UUID}' column")
    own = src[ROOT] if ROOT in src.columns else pd.Series([None] * len(src), index=src.index)
    return [r if r else (f"uuid:{u}" if u else None) for r, u in zip(own, src[SUBMISSION_UUID])]


def _bronze(src, roots, run: RunInfo) -> Table:
    df = src.copy()
    df[ROOT] = roots
    names = [arch.bronze_name(c) for c in df.columns]
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        raise ValueError(f"Export columns collide once lowercased: {repeated}")
    df.columns = names
    meta = {"_ingested_at": run.ingested_at, "_run_id": run.run_id, "_source_system": SOURCE_SYSTEM,
            "_source_asset": run.source_asset, "_pipeline_version": run.pipeline_version}
    for k, v in meta.items():
        df[k] = v
    types = {c: "STRING" for c in df.columns}
    types["_ingested_at"] = "TIMESTAMP"
    return Table("bronze", SHEET, arch.TABLES[SHEET], df, types, append=True)


def _silver(src, roots, types, run: RunInfo, cycle: str, issues: list) -> pd.DataFrame:
    # Columns are collected first and the frame is built once (many columns)
    data: dict[str, pd.Series] = {}
    missing = []
    for r in map_rows():
        col, name = r["kobo_name"].strip(), r["db_name"].strip()
        if col in src.columns:
            data[name] = src[col]
        elif name not in data:
            data[name] = pd.Series([None] * len(src), index=src.index, dtype=object)
            if name not in FILLED:
                missing.append(f"{name} <- {col}")
    for name, col in SYSTEM.items():
        data[name] = src[col] if col in src.columns else pd.Series([None] * len(src), index=src.index, dtype=object)
    out = pd.DataFrame(data, index=src.index)

    # The stager's value rules
    if "lga" in out.columns:
        lookup = lga_lookup()
        out["lga"] = out["lga"].map(lambda v: None if _blank(v) else lookup.get(str(v).strip(), str(v).strip()))
        codes = sorted({v for v in out["lga"].dropna() if re.fullmatch(r"\d+", v)})
        if codes:
            issues.append(_issue(run, "silver", "lga_code_unknown", False, None, "lga", None,
                                 f"LGA code(s) {codes} are not in zamfara_pharmacy_lga_lookup.csv; kept as codes"))
    for c in YESNO_COLUMNS:
        if c in out.columns:
            out[c] = _recode(out[c], YESNO)
    for c, mapping in VALUE_RECODES.items():
        if c in out.columns:
            out[c] = _recode(out[c], mapping)
    for c in out.columns:
        if c.startswith(BINARY_PREFIXES) and not c.endswith("_specified"):
            out[c] = _recode(out[c], BINARY, lower=False)
    for c in DATE_ONLY:
        if c in out.columns:
            out[c] = _date_only(out[c])
    out["cycle"] = cycle or None
    out["concatenated_id"] = [f"{u}_{i}" if not _blank(u) and not _blank(i) else None
                              for u, i in zip(out["pharmacy_uuid"], out["index"])]

    if missing:
        issues.append(_issue(run, "silver", "mapped_column_missing", False, None, None, None,
                             f"{len(missing)} mapped column(s) not in the export, loaded as NULL: {', '.join(missing)}"))
        logger.warning(f"  [pharmacy] {len(missing)} mapped column(s) not in the export — NULL: {missing}")

    cols = [arch.ROOT_UUID] + [r["db_name"] for r in types]
    out = out.reindex(columns=cols)                      # Postgres order; any column not built is NULL
    out[arch.ROOT_UUID] = roots
    out[arch.RUN_ID] = run.run_id
    return out.astype(object).where(out.notna(), None)


def _typed(value, sql_type: str):
    """(clean value as text, ok). Same rules as the AMR and Mortality gold loaders."""
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
        t = re.sub(r"(Z|[+\-]\d{2}(:?\d{2})?)$", "", s.replace("T", " "))
        d = pd.to_datetime(t, errors="coerce")
        return (d.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], True) if not pd.isna(d) else (None, False)
    return s, True


def _gold(silver, approved, types, run: RunInfo, issues: list) -> list[Table]:
    df = silver[silver[arch.ROOT_UUID].isin(approved)].copy()
    col_types = {arch.ROOT_UUID: "STRING", arch.RUN_ID: "STRING"}
    for row in types:
        name = row["db_name"]
        t = "STRING" if name in arch.PHONE_COLUMNS else row["type"]
        col_types[name] = t
        if t == "STRING":
            continue
        cleaned = [_typed(v, t) for v in df[name]]
        bad = [(k, v) for k, v, (_, ok) in zip(df[arch.ROOT_UUID], df[name], cleaned) if not ok]
        if bad:
            ident = name in arch.IDENTIFIERS[SHEET]
            issues.append(_issue(run, "gold", "type", False, bad[0][0], name, arch.MASK if ident else bad[0][1],
                                 f"{len(bad)} value(s) are not {t}; loaded as NULL"))
        df[name] = [c for c, _ in cleaned]

    pk, _ = arch.KEYS[SHEET]
    ids = arch.IDENTIFIERS[SHEET]
    missing = [c for c in ids if c not in df.columns]
    if missing:
        raise ValueError(f"Identifier column(s) {missing} are not in the mapping")
    rdf = df[pk + ids + [arch.RUN_ID]].copy()
    restricted = Table("restricted", SHEET, arch.restricted_table(SHEET), rdf,
                       {c: col_types[c] for c in rdf.columns}, pk, pk, arch.TABLES[SHEET], pk, parent_layer="gold")
    gdf = df.drop(columns=ids)
    gold = Table("gold", SHEET, arch.TABLES[SHEET], gdf, {c: col_types[c] for c in gdf.columns}, pk)
    return [gold, restricted]


# ── Checks ────────────────────────────────────────────────────────────────────

def _issue(run, layer, check, blocking, key, column, value, text) -> dict:
    return {"_run_id": run.run_id, "logged_at": run.ingested_at, "table_name": arch.TABLES[SHEET],
            "layer": layer, "check_type": check, "blocking": "true" if blocking else "false",
            "row_key": None if key is None else str(key), "column_name": column,
            "value": None if value is None else str(value),
            "value_masked": "true" if value == arch.MASK else "false", "issue": text}


def _check_keys(t: Table, run, issues: list) -> None:
    keys = t.df[t.pk[0]]
    blank = keys.map(_blank)
    if blank.any():
        issues.append(_issue(run, t.layer, "blank_key", True, None, t.pk[0], None,
                             f"{int(blank.sum())} row(s) have an empty {t.pk[0]}"))
    dup = t.df[~blank & keys.duplicated(keep=False)]
    for key, group in dup.groupby(t.pk[0], sort=True):
        issues.append(_issue(run, t.layer, "duplicate_key", True, key, t.pk[0], None,
                             f"{len(group)} rows share this key"))


# ── Entry point ───────────────────────────────────────────────────────────────

def build(sheets: dict[str, pd.DataFrame], run: RunInfo, cycle: str = "") -> Built:
    src = pick_sheet(sheets)
    types = gold_types()
    roots = _roots(src)
    if STATUS not in src.columns:
        raise ValueError(f"Pharmacy sheet has no '{STATUS}' column: cannot tell which submissions are approved")
    approved = {r for r, st in zip(roots, src[STATUS]) if r and st == APPROVED}
    logger.info(f"  {len(approved)} of {len(src)} submission(s) approved")

    issues: list[dict] = []
    silver = _silver(src, roots, types, run, cycle, issues)
    pk, _ = arch.KEYS[SHEET]
    silver_table = Table("silver", SHEET, arch.TABLES[SHEET], silver, {c: "STRING" for c in silver.columns}, pk)
    tables = [_bronze(src, roots, run), silver_table] + _gold(silver, approved, types, run, issues)
    for t in tables:
        if t.layer in ("silver", "gold"):
            _check_keys(t, run, issues)
    for t in tables:
        t.df = _text(t.df)
    return Built(tables, pd.DataFrame(issues, columns=ISSUE_COLUMNS))
