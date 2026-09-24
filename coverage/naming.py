"""
naming.py — Dynamic workbook filename generator.

Logic:
  - State   : read from the 'states' column of the main sheet.
              The preprocessor decodes state codes -> names via dat.csv.
              As a safety net, if the value is still a numeric code when
              build_filename() is called, it is resolved directly from
              dat.csv (state_Name -> state_Label) so the filename always
              contains the human-readable state name (e.g. "Kaduna").
  - Cycle   : read from main sheet, column 'unique_code', first non-blank value.
              Extract prefix (characters before first digit or end of string):
              B or C1 -> BASELINE
              C2      -> C2
              C3      -> C3
              C4      -> C4
  - Format  : SARMAAN_II_COVERAGE_{STATE}_{CYCLE}_{SUFFIX}.xlsx
              e.g. SARMAAN_II_COVERAGE_KADUNA_BASELINE_RAW.xlsx
"""

import logging
import re
import pandas as pd
from config import MAPPING_DIR

logger = logging.getLogger(__name__)

DAT_FILE = MAPPING_DIR / "dat.csv"

PREFIX_TO_CYCLE = {
    "B":  "BASELINE",
    "C1": "BASELINE",
    "C2": "C2",
    "C3": "C3",
    "C4": "C4",
}


def _dat_state_lookup() -> dict[str, str]:
    """Return {state_Name_code: state_Label_name} from dat.csv."""
    if not DAT_FILE.exists():
        return {}
    try:
        dat = pd.read_csv(DAT_FILE, dtype=str).fillna("")
        dat.columns = [c.strip() for c in dat.columns]
        if "state_Name" in dat.columns and "state_Label" in dat.columns:
            return dict(zip(dat["state_Name"].str.strip(), dat["state_Label"].str.strip()))
    except Exception:
        pass
    return {}


def _get_state(main_df: pd.DataFrame) -> str:
    """
    Read the implementing state name from the 'states' column of the main sheet.
    The preprocessor decodes state codes -> names via dat.csv before this runs.
    As a safety net, if the value is still a numeric code, look it up in dat.csv
    directly so the filename always uses the human-readable state name.
    """
    col = "states"
    if col not in main_df.columns:
        logger.warning(f"naming: '{col}' column not found in main sheet — using 'UNKNOWN_STATE'")
        return "UNKNOWN_STATE"

    values = [
        v.strip() for v in main_df[col].astype(str)
        if v.strip() and v.strip().lower() != "nan"
    ]
    if not values:
        logger.warning("naming: 'states' column is empty — using 'UNKNOWN_STATE'")
        return "UNKNOWN_STATE"

    raw = values[0]

    # Safety net: if still a numeric code, resolve via dat.csv directly
    if raw.isdigit():
        lookup = _dat_state_lookup()
        if raw in lookup:
            resolved = lookup[raw]
            logger.info(
                f"naming: 'states' value '{raw}' is a code — "
                f"resolved to '{resolved}' via dat.csv"
            )
            raw = resolved
        else:
            logger.warning(
                f"naming: 'states' code '{raw}' not found in dat.csv — using code as-is"
            )

    state = raw.upper().replace(" ", "_")
    logger.info(f"naming: state -> '{state}'")
    return state


def _get_cycle(main_df: pd.DataFrame) -> str:
    """Extract cycle from unique_code column of main sheet."""
    col = "unique_code"
    if col not in main_df.columns:
        logger.warning(f"naming: '{col}' column not found in main sheet — using 'UNKNOWN_CYCLE'")
        return "UNKNOWN_CYCLE"

    values = [v.strip() for v in main_df[col].astype(str) if v.strip() and v.strip() != "nan"]
    if not values:
        logger.warning("naming: 'unique_code' column is empty — using 'UNKNOWN_CYCLE'")
        return "UNKNOWN_CYCLE"

    sample = values[0]
    # Extract prefix: letters up to and including first digit group
    # e.g. "C1-ADM-001" -> "C1", "B-ADM-001" -> "B", "C2_ADM_001" -> "C2"
    match = re.match(r"([A-Za-z]+\d*)", sample)
    if not match:
        logger.warning(f"naming: could not extract prefix from '{sample}' — using 'UNKNOWN_CYCLE'")
        return "UNKNOWN_CYCLE"

    prefix = match.group(1).upper()
    cycle = PREFIX_TO_CYCLE.get(prefix, prefix)
    logger.info(f"naming: unique_code sample='{sample}', prefix='{prefix}', cycle='{cycle}'")
    return cycle


def build_filename(main_df: pd.DataFrame, suffix: str) -> str:
    """
    Build the full workbook filename.
    suffix: 'RAW' or 'CLEANED'
    Returns e.g. 'SARMAAN_II_COVERAGE_KADUNA_C2_RAW.xlsx'
    """
    state = _get_state(main_df)
    cycle = _get_cycle(main_df)
    filename = f"SARMAAN_II_COVERAGE_{state}_{cycle}_{suffix}.xlsx"
    logger.info(f"naming: filename built -> '{filename}'")
    return filename
