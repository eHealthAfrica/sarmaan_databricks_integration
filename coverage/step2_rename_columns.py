"""
step2_rename_columns.py — Column renaming with strict mapping filter.

Sheet names in output workbook:
  main     -> Household Code
  child_info  -> Child_Info
  net_repeat  -> Net_repeat
  child_infoo -> Child_Infoo

Workbook filename is built dynamically:
  SARMAAN_II_COVERAGE_{STATE}_{CYCLE}_RAW.xlsx
  State comes from dat.csv -> state_Label
  Cycle comes from main sheet -> unique_code prefix
"""

import logging
import pandas as pd
from config import OUTPUT_DIR
from naming import build_filename

logger = logging.getLogger(__name__)

# Output sheet names for Step 2 workbook
OUTPUT_SHEET_NAMES = {
    "main":        "Household Code",
    "child_info":  "Child_Info",
    "net_repeat":  "Net_repeat",
    "child_infoo": "Child_Infoo",
}


def _apply_strict_map(df: pd.DataFrame, mapping: dict[str, str], sheet_key: str) -> pd.DataFrame:
    """
    Keep ONLY columns listed in mapping (as keys), in mapping order.
    Rename them to mapping values.
    Anything not in the mapping is dropped.
    """
    missing_from_data = [k for k in mapping if k not in df.columns]
    if missing_from_data:
        logger.warning(
            f"  [{sheet_key}] {len(missing_from_data)} mapped columns not in data "
            f"(skipped): {missing_from_data[:8]}{'...' if len(missing_from_data) > 8 else ''}"
        )

    dropped = [c for c in df.columns if c not in mapping]
    if dropped:
        logger.info(
            f"  [{sheet_key}] {len(dropped)} columns not in mapping — dropped"
        )

    keep = {src: dst for src, dst in mapping.items() if src in df.columns}
    df_out = df[list(keep.keys())].rename(columns=keep)
    logger.info(f"  [{sheet_key}] {len(df_out.columns)} columns kept and renamed")
    return df_out


def run_step2(
    raw_sheets: dict[str, pd.DataFrame],
    step2_maps: dict[str, dict[str, str]],
) -> dict[str, pd.DataFrame]:
    """
    raw_sheets  — { logical_key: DataFrame } preprocessed raw data
    step2_maps  — { logical_key: { xml_col: readable_col } } from mappings.py
    Returns { output_sheet_name: DataFrame }
    """
    logger.info("=" * 50)
    logger.info("STEP 2 — Strict column filter + rename")

    output_sheets = {}
    for key, out_name in OUTPUT_SHEET_NAMES.items():
        if key not in raw_sheets:
            logger.warning(f"  Sheet '{key}' not found in raw data — skipping")
            continue

        mapping = step2_maps.get(key, {})
        if not mapping:
            logger.warning(f"  No mapping found for '{key}' — sheet skipped")
            continue

        df = _apply_strict_map(raw_sheets[key], mapping, key)
        output_sheets[out_name] = df
        logger.info(f"  '{out_name}': {len(df)} rows, {len(df.columns)} cols")

    # Build dynamic filename
    main_df = raw_sheets.get("main", pd.DataFrame())
    filename = build_filename(main_df, "RAW")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / filename
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in output_sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    logger.info(f"Step 2 local file saved: {output_path}")
    logger.info("Step 2 complete")

    return output_sheets
