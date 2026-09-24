"""
mappings.py — Loads all mapping files from the mappings/ folder at startup.

Mapping file conventions:
  All files use two key columns: column_label -> db_column_name
  Extra columns (Question/Label, Variable Name etc) are ignored.
  Blank rows are skipped.
"""

import logging
from pathlib import Path
import pandas as pd
from config import STEP1_MAP, STEP2_MAP, STEP3_MAP, STEP5_MAP, COMPLETENESS_TEMPLATE

logger = logging.getLogger(__name__)


def _load_two_col_map(path: Path, sheet: str) -> dict[str, str]:
    """
    Load column_label -> db_column_name mapping from a sheet.
    Handles sheets with extra columns — only uses column_label and db_column_name.
    Skips rows where either value is blank.
    """
    df = pd.read_excel(path, sheet_name=sheet, dtype=str).fillna("")

    # Find column_label and db_column_name regardless of position
    cols = [c.strip() for c in df.columns]
    df.columns = cols

    if "column_label" not in cols or "db_column_name" not in cols:
        logger.warning(
            f"Sheet '{sheet}' in {path.name} missing 'column_label' or "
            f"'db_column_name' columns. Found: {cols}"
        )
        return {}

    mapping = {}
    for _, row in df.iterrows():
        src = str(row["column_label"]).strip()
        dst = str(row["db_column_name"]).strip()
        if src and dst and src != "nan" and dst != "nan":
            mapping[src] = dst
    return mapping


# ── Step 1 mappings ───────────────────────────────────────────────────────────

def load_step1_maps() -> dict[str, dict[str, str]]:
    wb = pd.ExcelFile(STEP1_MAP)
    sheet_names = wb.sheet_names
    logger.info(f"Step 1 map sheets: {sheet_names}")
    keys = ["main", "child_info", "net_repeat", "child_infoo"]
    result = {}
    for key, sheet in zip(keys, sheet_names):
        result[key] = _load_two_col_map(STEP1_MAP, sheet)
        logger.info(f"  Step1[{key}] ({sheet}): {len(result[key])} mappings loaded")
    return result


# ── Step 2 mappings ───────────────────────────────────────────────────────────

def load_step2_maps() -> dict[str, dict[str, str]]:
    wb = pd.ExcelFile(STEP2_MAP)
    sheet_names = wb.sheet_names
    logger.info(f"Step 2 map sheets: {sheet_names}")
    keys = ["main", "child_info", "net_repeat", "child_infoo"]
    result = {}
    for key, sheet in zip(keys, sheet_names):
        result[key] = _load_two_col_map(STEP2_MAP, sheet)
        logger.info(f"  Step2[{key}] ({sheet}): {len(result[key])} mappings loaded")
    return result


# ── Step 3 mappings ───────────────────────────────────────────────────────────

def load_step3_maps() -> dict[str, dict[str, str]]:
    result = {}
    for sheet in ["household_info", "net_info"]:
        result[sheet] = _load_two_col_map(STEP3_MAP, sheet)
        logger.info(f"  Step3[{sheet}]: {len(result[sheet])} mappings loaded")
    return result


# ── Step 5 mappings ───────────────────────────────────────────────────────────

def load_step5_maps() -> dict[str, dict[str, str]]:
    result = {}
    for sheet in ["household_info", "child_info", "net_repeat", "child_infoo"]:
        result[sheet] = _load_two_col_map(STEP5_MAP, sheet)
        logger.info(f"  Step5[{sheet}]: {len(result[sheet])} mappings loaded")
    return result


# ── Completeness rules ────────────────────────────────────────────────────────

def load_completeness_rules() -> dict[str, list[str]]:
    df = pd.read_excel(
        COMPLETENESS_TEMPLATE, sheet_name="Completeness", dtype=str
    ).fillna("")
    result = {}
    for col in df.columns:
        key = col.strip().replace(" sheet", "").strip()
        rules = [str(v).strip() for v in df[col] if str(v).strip()]
        result[key] = rules
        logger.info(f"  Completeness[{key}]: {len(rules)} rules loaded")
    return result


# ── Standardization columns ───────────────────────────────────────────────────

def load_standardization_cols() -> dict[str, list[str]]:
    df = pd.read_excel(
        COMPLETENESS_TEMPLATE, sheet_name="Standardization", dtype=str
    ).fillna("")
    result = {}
    for col in df.columns:
        key = col.strip()
        cols = [str(v).strip() for v in df[col] if str(v).strip()]
        result[key] = cols
        logger.info(f"  Standardization[{key}]: {len(cols)} columns")
    return result
