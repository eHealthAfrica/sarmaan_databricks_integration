"""
extractor.py — Pulls all submissions from KoboToolbox using the XML-header
export endpoint, which preserves the group/repeat structure as separate sheets.

Returns a dict of { sheet_name: pd.DataFrame } for all 4 sheets,
plus the detected main sheet name.
"""

import io
import logging

import requests
import pandas as pd

from config import KOBO_API_TOKEN, KOBO_BASE_URL, KOBO_ASSET_UID, KOBO_EXPORT_SETTINGS_ID, KNOWN_REPEAT_SHEETS

logger = logging.getLogger(__name__)


def fetch_kobo_data() -> tuple[dict[str, pd.DataFrame], str]:
    """
    Download data from KoboToolbox as an Excel export with XML headers.
    Returns:
        sheets      — dict of { sheet_name: DataFrame }
        main_sheet  — the auto-detected name of the primary (main) sheet
    """
    url = (
        f"{KOBO_BASE_URL}/api/v2/assets/{KOBO_ASSET_UID}/export-settings/"
    )

    # Use the export-settings endpoint with XML header labels
    export_url = (
        f"{KOBO_BASE_URL}/api/v2/assets/{KOBO_ASSET_UID}/"
        f"export-settings/{KOBO_EXPORT_SETTINGS_ID}/data.xlsx"
    )

    headers = {"Authorization": f"Token {KOBO_API_TOKEN}"}

    logger.info(f"Fetching data from Kobo: {export_url}")
    response = requests.get(export_url, headers=headers, timeout=120)
    response.raise_for_status()

    logger.info(f"Download complete — {len(response.content):,} bytes")

    # Parse all sheets from the downloaded Excel file
    excel_data = pd.read_excel(
        io.BytesIO(response.content),
        sheet_name=None,          # load ALL sheets
        dtype=str,                # keep everything as string initially
        na_filter=False,          # don't convert empty strings to NaN yet
    )

    sheets = {name: df for name, df in excel_data.items()}
    logger.info(f"Sheets found: {list(sheets.keys())}")

    # Auto-detect main sheet (whichever is NOT one of the 3 known repeat sheets)
    known = set(KNOWN_REPEAT_SHEETS)
    main_candidates = [s for s in sheets if s not in known]

    if len(main_candidates) != 1:
        raise ValueError(
            f"Expected exactly 1 main sheet, found: {main_candidates}. "
            f"Known repeat sheets: {KNOWN_REPEAT_SHEETS}. "
            f"All sheets: {list(sheets.keys())}"
        )

    main_sheet = main_candidates[0]
    logger.info(f"Auto-detected main sheet: '{main_sheet}'")

    return sheets, main_sheet
