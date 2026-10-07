"""
load_common.py — Table definitions and checks shared by the Step 6 loaders
(step6_db_loader.py for Postgres, step6_databricks_loader.py for Databricks).

Nothing here talks to a database.
"""

import logging

import pandas as pd

from config import MAPPING_DIR

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


# ── Clean table types ─────────────────────────────────────────────────────────

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


# ── FK integrity ──────────────────────────────────────────────────────────────

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
