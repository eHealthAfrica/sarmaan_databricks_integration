"""
preprocessor.py — Raw data transformations applied to ALL sheets before
any step runs. Changes here flow through every output automatically.

Transformations:
  0. Drop unnamed columns (e.g. 'Unnamed: 307') — Excel artefacts

  1. Split child_names11 on '-':
       child_names11  -> name part (before '-'), stripped
       agee_eligible  -> number only (after '-'), inserted IMMEDIATELY after child_names11
     Applied to: child_info AND child_infoo (wherever the column exists)

  2. Map location codes -> actual names using mappings/dat.csv
     Applies to: main sheet only
       states        (code) -> state_Label     (name)   e.g. Kaduna -> Kaduna
       lgas          (code) -> lga_Label       (name)   e.g. 601   -> Chikun
       wards         (code) -> ward_Label      (name)   e.g. 6011  -> Nassarawa
       community_name(code) -> settlement_Label(name)   e.g. 60111 -> Gayan Road B
"""

import logging
import pandas as pd
from config import MAPPING_DIR

logger = logging.getLogger(__name__)
DAT_FILE = MAPPING_DIR / "dat.csv"


def apply_all(sheets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    sheets = {k: df.copy() for k, df in sheets.items()}

    # 0. Drop unnamed columns from all sheets
    for key in sheets:
        sheets[key] = _drop_unnamed_cols(sheets[key], key)

    # 1. Split child_names11 on both child_info and child_infoo
    for key in ["child_info", "child_infoo"]:
        if key in sheets:
            sheets[key] = _split_child_names(sheets[key], key)

    # 2. Map lga, ward, and community codes on main sheet
    if "main" in sheets:
        sheets["main"] = _map_location_codes(sheets["main"])

    return sheets


# ── Transform 0: drop unnamed columns ────────────────────────────────────────

def _drop_unnamed_cols(df: pd.DataFrame, sheet_key: str) -> pd.DataFrame:
    unnamed = [c for c in df.columns if str(c).startswith("Unnamed:")]
    if unnamed:
        df = df.drop(columns=unnamed)
        logger.info(f"  [{sheet_key}] Dropped {len(unnamed)} unnamed column(s)")
    return df


# ── Transform 1: split child_names11, insert agee_eligible right after ───────

def _split_child_names(df: pd.DataFrame, sheet_key: str) -> pd.DataFrame:
    col = "child_names11"
    if col not in df.columns:
        logger.info(f"  [{sheet_key}] '{col}' not found — skipping split")
        return df

    col_index = df.columns.get_loc(col)

    split = df[col].astype(str).str.split("-", n=1, expand=True)

    # Overwrite child_names11 with name part only
    df[col] = split[0].str.strip()

    # Build agee_eligible series
    if split.shape[1] > 1:
        age_series = (
            split[1]
            .str.strip()
            .str.extract(r"(\d+)")[0]
            .fillna("")
        )
    else:
        age_series = pd.Series("", index=df.index)

    # Insert agee_eligible immediately after child_names11
    # If it already exists, drop it first so we can reinsert in the right position
    if "agee_eligible" in df.columns:
        df = df.drop(columns=["agee_eligible"])

    df.insert(col_index + 1, "agee_eligible", age_series)

    logger.info(
        f"  [{sheet_key}] Split 'child_names11' -> 'child_names11' + 'agee_eligible' "
        f"(inserted at position {col_index + 1}, {len(df)} rows)"
    )
    return df


# ── Transform 2: map lga / ward / community codes -> names ───────────────────
#
# dat.csv columns used:
#   lga_Name       (code)  ->  lga_Label       (name)
#   ward_Name      (code)  ->  ward_Label      (name)
#   settlement_Name(code)  ->  settlement_Label(name)
#
# Kobo form columns mapped (XML names as they arrive from the API):
#   states         -> state name
#   lgas           -> lga label
#   wards          -> ward label
#   community_name -> settlement label

# Each tuple: (dat_code_col, dat_label_col, form_col)
# Covers both old-style column names (states/lgas/wards/community_name used by
# some forms) and new-style (q1_States/q2_LGAs/q3_Wards/q4_Community used by
# forms like Bauchi where location columns retain the XML question names).
_LOCATION_MAPPINGS = [
    ("state_Name",      "state_Label",       "states"),
    ("lga_Name",        "lga_Label",         "lgas"),
    ("ward_Name",       "ward_Label",        "wards"),
    ("settlement_Name", "settlement_Label",  "community_name"),
    # q-prefixed variants (Bauchi and similar forms)
    ("lga_Name",        "lga_Label",         "q2_LGAs"),
    ("ward_Name",       "ward_Label",        "q3_Wards"),
    ("settlement_Name", "settlement_Label",  "q4_Community"),
]


def _map_location_codes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Replace numeric codes in location columns with human-readable labels
    from dat.csv. Covers both old-style column names (states/lgas/wards/
    community_name) and q-prefixed names (q1_States/q2_LGAs/q3_Wards/
    q4_Community) used by forms where Kobo retains the XML question names.

    State is handled separately: dat.csv may store state_Name as a text
    label (e.g. 'Bauchi') rather than a numeric code, so we derive the
    state→label lookup from lga_Name→state_Label (every LGA code implies
    a state) and apply it to both 'states' and 'q1_States'.

    Columns absent from the data are silently skipped.
    """
    if not DAT_FILE.exists():
        logger.warning(
            "  [main] 'dat.csv' not found in mappings/ — "
            "lga/ward/community codes will not be mapped."
        )
        return df

    try:
        dat = pd.read_csv(DAT_FILE, dtype=str).fillna("")
        dat.columns = [c.strip() for c in dat.columns]
    except Exception as e:
        logger.warning(f"  [main] Could not read dat.csv — {e}. Codes kept as-is.")
        return df

    # ── State lookup: derive numeric-code → state_Label via lga_Name ─────────
    # dat.csv state_Name may be text (e.g. 'Bauchi') or numeric. Build a
    # reliable code→label map by inferring state code from lga_Name prefix:
    # lga code '201' starts with '2' → state code '2' → 'Bauchi'.
    # Also support dat.csv where state_Name IS a numeric code directly.
    state_code_to_label: dict[str, str] = {}
    if "lga_Name" in dat.columns and "state_Label" in dat.columns:
        for _, row in dat.iterrows():
            lga_code = str(row["lga_Name"]).strip()
            state_label = str(row["state_Label"]).strip()
            if lga_code.isdigit() and len(lga_code) >= 2:
                # Infer state code as the leading digit(s) before lga suffix
                # Convention: lga 201-206 → state 2, lga 601-606 → state 6
                state_code = lga_code[:len(lga_code) - 2]  # e.g. '201'→'2', '601'→'6'
                if state_code and state_label:
                    state_code_to_label[state_code] = state_label
    # Also add any numeric state_Name entries directly from dat.csv
    if "state_Name" in dat.columns and "state_Label" in dat.columns:
        for _, row in dat.iterrows():
            sn = str(row["state_Name"]).strip()
            sl = str(row["state_Label"]).strip()
            if sn.isdigit() and sl:
                state_code_to_label[sn] = sl

    for state_col in ("states", "q1_States"):
        if state_col not in df.columns:
            continue
        original = df[state_col].copy()
        df[state_col] = (
            df[state_col].astype(str).str.strip()
            .map(state_code_to_label)
            .fillna(original)
        )
        mapped = (df[state_col] != original.astype(str).str.strip()).sum()
        logger.info(
            f"  [main] '{state_col}': {mapped} code(s) replaced with labels "
            f"using dat.csv lga_Name-derived state lookup"
        )

    # ── LGA / Ward / Community lookups ────────────────────────────────────────
    for dat_code_col, dat_label_col, form_col in _LOCATION_MAPPINGS:
        if form_col not in df.columns:
            logger.info(f"  [main] '{form_col}' not in data — skipping")
            continue

        if dat_code_col not in dat.columns or dat_label_col not in dat.columns:
            logger.warning(
                f"  [main] dat.csv missing '{dat_code_col}' or '{dat_label_col}' — "
                f"cannot map '{form_col}'. Found: {list(dat.columns)}"
            )
            continue

        # Build code -> label lookup (deduplicated)
        code_to_label = dict(
            zip(dat[dat_code_col].str.strip(), dat[dat_label_col].str.strip())
        )

        original = df[form_col].copy()
        df[form_col] = (
            df[form_col].astype(str).str.strip()
            .map(code_to_label)
            .fillna(original)
        )
        mapped = (df[form_col] != original.astype(str).str.strip()).sum()
        logger.info(
            f"  [main] '{form_col}': {mapped} code(s) replaced with labels "
            f"using dat.csv '{dat_code_col}' -> '{dat_label_col}'"
        )

    return df
