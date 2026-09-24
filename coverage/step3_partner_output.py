"""
step3_partner_output.py — Merge + partner column renaming.

Inputs: raw preprocessed Kobo sheets (XML header names)

Merges:
  household_info = child_infoo INNER JOIN main on UUID
                   child_infoo drives row count (1 row per child)
                   households without children are excluded
  net_info       = net_repeat INNER JOIN main on UUID
                   net_repeat drives row count (1 row per net)
                   households without nets are excluded

After merge, step_3_map_file.xlsx applied to each output sheet:
  - Only columns listed in the map are kept
  - Columns renamed from XML names to partner-facing names
  - Column order follows mapping file order

Workbook filename: SARMAAN_II_COVERAGE_{STATE}_{CYCLE}_CLEANED.xlsx
"""

import logging
import pandas as pd
from config import (
    OUTPUT_DIR, MERGE_SHEET_HOUSEHOLD, MERGE_SHEET_NET,
    VALIDATION_STATUS_APPROVED,
)
from naming import build_filename

logger = logging.getLogger(__name__)


def _filter_approved(df: pd.DataFrame, status_col: str, label: str) -> pd.DataFrame:
    if status_col not in df.columns:
        logger.warning(f"  [{label}] Approval column '{status_col}' not found — no filtering applied")
        return df
    before = len(df)
    df = df[df[status_col] == VALIDATION_STATUS_APPROVED].copy()
    logger.info(f"  [{label}] Approval filter: {before} -> {len(df)} rows kept")
    return df


def _apply_map_as_filter_and_rename(
    df: pd.DataFrame,
    mapping: dict[str, str],
    label: str,
) -> pd.DataFrame:
    """
    Keep ONLY columns in mapping, rename them, preserve mapping order.
    """
    missing = [k for k in mapping if k not in df.columns]
    if missing:
        logger.warning(
            f"  [{label}] {len(missing)} mapped columns not found in merged data "
            f"(skipped): {missing[:8]}{'...' if len(missing) > 8 else ''}"
        )
    keep = {src: dst for src, dst in mapping.items() if src in df.columns}
    df_out = df[list(keep.keys())].rename(columns=keep)
    logger.info(
        f"  [{label}] {len(df_out.columns)} columns retained and renamed "
        f"from {len(df.columns)} merged columns"
    )
    return df_out


def run_step3(
    raw_sheets: dict[str, pd.DataFrame],
    step3_maps: dict[str, dict[str, str]],
) -> dict[str, pd.DataFrame]:
    """
    raw_sheets  — { logical_key: DataFrame } preprocessed raw Kobo data
    step3_maps  — { 'household_info': {...}, 'net_info': {...} }
    Returns { 'household_info': DataFrame, 'net_info': DataFrame }
    """
    logger.info("=" * 50)
    logger.info("STEP 3 — Merge raw data + apply partner mapping")

    df_main        = raw_sheets.get("main",        pd.DataFrame()).copy()
    df_child_infoo = raw_sheets.get("child_infoo", pd.DataFrame()).copy()
    df_net_repeat  = raw_sheets.get("net_repeat",  pd.DataFrame()).copy()

    for name, df in [("main", df_main), ("child_infoo", df_child_infoo), ("net_repeat", df_net_repeat)]:
        if df.empty:
            raise ValueError(f"Sheet '{name}' is missing or empty — cannot proceed with Step 3")

    # ── Filter to approved submissions ────────────────────────────────────────
    df_main        = _filter_approved(df_main,        "_validation_status",             "main")
    df_child_infoo = _filter_approved(df_child_infoo, "_submission__validation_status", "child_infoo")
    df_net_repeat  = _filter_approved(df_net_repeat,  "_submission__validation_status", "net_repeat")

    # ── Identify UUID join columns ────────────────────────────────────────────
    def _find_col(df, label, *candidates):
        for c in candidates:
            if c in df.columns:
                return c
        raise KeyError(
            f"Could not find UUID column in '{label}'. "
            f"Tried: {candidates}. Available: {list(df.columns)[:10]}"
        )

    main_uuid  = _find_col(df_main,        "main",        "_uuid")
    infoo_uuid = _find_col(df_child_infoo, "child_infoo", "_submission__uuid")
    net_uuid   = _find_col(df_net_repeat,  "net_repeat",  "_submission__uuid")

    # ── Merge 1: household_info = child_infoo INNER JOIN main ─────────────────
    # child_infoo drives row count — 1 row per child
    # Households without children are excluded
    logger.info(f"  Merging child_infoo ({len(df_child_infoo)}) + main ({len(df_main)}) on UUID")
    df_household = pd.merge(
        df_child_infoo, df_main,
        left_on=infoo_uuid,
        right_on=main_uuid,
        how="inner",
        suffixes=("", "_main"),
    )
    logger.info(f"  household_info: {len(df_household)} rows")

    # ── Merge 2: net_info = net_repeat INNER JOIN main ────────────────────────
    # net_repeat drives row count — 1 row per net
    # Households without nets are excluded
    logger.info(f"  Merging net_repeat ({len(df_net_repeat)}) + main ({len(df_main)}) on UUID")
    df_net = pd.merge(
        df_net_repeat, df_main,
        left_on=net_uuid,
        right_on=main_uuid,
        how="inner",
        suffixes=("", "_main"),
    )
    logger.info(f"  net_info: {len(df_net)} rows (should match net_repeat: {len(df_net_repeat)})")

    # ── Apply mapping as filter + rename ──────────────────────────────────────
    df_household = _apply_map_as_filter_and_rename(
        df_household, step3_maps.get("household_info", {}), "household_info"
    )
    df_net = _apply_map_as_filter_and_rename(
        df_net, step3_maps.get("net_info", {}), "net_info"
    )

    output_sheets = {
        MERGE_SHEET_HOUSEHOLD: df_household,
        MERGE_SHEET_NET:       df_net,
    }

    # Build dynamic filename
    filename = build_filename(df_main, "CLEANED")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / filename
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in output_sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    logger.info(f"Step 3 local file saved: {output_path}")
    logger.info("Step 3 complete")

    return output_sheets
