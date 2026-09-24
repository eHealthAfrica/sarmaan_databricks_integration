"""
step1_raw_export.py — Raw XML export.

Kobo repeat hierarchy:
  coverage_household (main_sheet)
  coverage_all_children (child_info)
  coverage_net_info (net_repeat)
  coverage_children_1_59 (child_infoo)

Key rule: The PK on coverage_household (index_uuid) is the FK on ALL other tables.

PK/FK columns added to each sheet (no separators):
  main_sheet:
    index_uuid                      = _index + _uuid
    concatenated_id                 = same as index_uuid
  child_info:
    child_id_submission__uuid       = child_id + _submission__uuid
    _parent_index_submission__uuid  = _parent_index + _submission__uuid
    concatenated_id                 = same as _parent_index_submission__uuid
  net_repeat:
    net_id_submission__uuid         = net_id + _submission__uuid
    _parent_index_submission__uuid  = _parent_index + _submission__uuid
    concatenated_id                 = same as _parent_index_submission__uuid
  child_infoo:
    child_idd_submission__uuid      = child_idd + _submission__uuid
    _parent_index_submission__uuid  = _parent_index + _submission__uuid
    concatenated_id                 = same as _parent_index_submission__uuid
"""

import logging

import pandas as pd

from config import OUTPUT_DIR, STEP1_FILENAME

logger = logging.getLogger(__name__)

OUTPUT_SHEET_NAMES = {
    "main":        "main_sheet",
    "child_info":  "child_info",
    "net_repeat":  "net_repeat",
    "child_infoo": "child_infoo",
}


def _add_key_columns(df: pd.DataFrame, sheet_key: str) -> pd.DataFrame:
    """Add PK/FK columns at the END of the dataframe."""
    df = df.copy()

    if sheet_key == "main":
        _concat(df, "index_uuid", "_index", "_uuid")
        df["concatenated_id"] = df["index_uuid"]

    elif sheet_key == "child_info":
        _concat(df, "child_id_submission__uuid", "child_id", "_submission__uuid")
        _concat(df, "_parent_index_submission__uuid", "_parent_index", "_submission__uuid")
        df["concatenated_id"] = df["_parent_index_submission__uuid"]

    elif sheet_key == "net_repeat":
        _concat(df, "net_id_submission__uuid", "net_id", "_submission__uuid")
        _concat(df, "_parent_index_submission__uuid", "_parent_index", "_submission__uuid")
        df["concatenated_id"] = df["_parent_index_submission__uuid"]

    elif sheet_key == "child_infoo":
        _concat(df, "child_idd_submission__uuid", "child_idd", "_submission__uuid")
        _concat(df, "_parent_index_submission__uuid", "_parent_index", "_submission__uuid")
        df["concatenated_id"] = df["_parent_index_submission__uuid"]

    return df


def _concat(df: pd.DataFrame, col_name: str, col_a: str, col_b: str) -> None:
    """Concatenate two columns into a new column (no separator)."""
    missing = [c for c in [col_a, col_b] if c not in df.columns]
    if missing:
        logger.warning(f"  Cannot build '{col_name}' — missing source columns: {missing}")
        df[col_name] = ""
        return
    df[col_name] = df[col_a].astype(str) + df[col_b].astype(str)
    logger.info(f"  Built '{col_name}' = '{col_a}' + '{col_b}'")


def run_step1(sheets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """
    sheets — { logical_key: DataFrame } preprocessed by preprocessor.py
    Returns { output_sheet_name: DataFrame } with PK/FK columns at end.
    """
    logger.info("=" * 50)
    logger.info("STEP 1 — Raw XML export")

    output_sheets = {}
    for key, out_name in OUTPUT_SHEET_NAMES.items():
        if key not in sheets:
            logger.warning(f"  Sheet key '{key}' not found — skipping")
            continue
        df = _add_key_columns(sheets[key], key)
        output_sheets[out_name] = df
        logger.info(f"  {key} -> '{out_name}': {len(df)} rows, {len(df.columns)} cols")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / STEP1_FILENAME
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in output_sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    logger.info(f"Step 1 local file saved: {output_path}")
    logger.info("Step 1 complete")

    return output_sheets
