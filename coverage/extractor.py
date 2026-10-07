"""
extractor.py — Pulls all submissions from KoboToolbox as an Excel export with
XML headers, which keeps the group/repeat structure as separate sheets.

The export is built by Kobo in the background, the way the Export button on
the Kobo website does it:
  1. Read the saved export settings (KOBO_EXPORT_SETTINGS_ID).
  2. Reuse an export of this form with the same settings if there is one:
     a finished one from the last KOBO_EXPORT_MAX_AGE_HOURS (default 24) is
     downloaded straight away; one Kobo is still building is waited for.
     Otherwise ask Kobo to start a new export.
  3. Check every few seconds until Kobo reports it complete, for up to
     KOBO_EXPORT_TIMEOUT_MINUTES (default 60). An export that is not ready
     yet is left on Kobo, so the next run picks it up instead of starting over.
  4. Download the finished file. Only exports this run started are deleted
     from Kobo afterwards; exports made on the Kobo website are left alone.
Asking for the file in one request (export-settings/<id>/data.xlsx) makes
Kobo build it while the request waits, which times out (504) on large forms.

Returns a dict of { sheet_name: pd.DataFrame } for all 4 sheets,
plus the detected main sheet name.
"""

import io
import logging
import os
import time

import requests
import pandas as pd

from config import KOBO_API_TOKEN, KOBO_BASE_URL, KOBO_ASSET_UID, KOBO_EXPORT_SETTINGS_ID, KNOWN_REPEAT_SHEETS

logger = logging.getLogger(__name__)

POLL_SECONDS = 10
EXPORT_TIMEOUT_MINUTES = float(os.getenv("KOBO_EXPORT_TIMEOUT_MINUTES", "60"))
EXPORT_MAX_AGE_HOURS = float(os.getenv("KOBO_EXPORT_MAX_AGE_HOURS", "24"))
RETRY_STATUSES = {429, 500, 502, 503, 504}
BUILDING = ("created", "processing")


def _request(method: str, url: str, **kwargs) -> requests.Response:
    """One Kobo API call, retried a few times on busy-server errors."""
    headers = {"Authorization": f"Token {KOBO_API_TOKEN}", **kwargs.pop("headers", {})}
    for attempt in range(1, 5):
        response = requests.request(method, url, headers=headers, timeout=120, **kwargs)
        if response.status_code not in RETRY_STATUSES or attempt == 4:
            response.raise_for_status()
            return response
        wait = 15 * attempt
        logger.warning(f"Kobo returned {response.status_code} for {method} {url} — retrying in {wait}s")
        time.sleep(wait)
    raise AssertionError("unreachable")


def _created(export: dict) -> pd.Timestamp:
    return pd.to_datetime(export.get("date_created"), utc=True, errors="coerce")


def _age(export: dict) -> str:
    created = _created(export)
    if pd.isna(created):
        return "unknown age"
    minutes = int((pd.Timestamp.now(tz="UTC") - created).total_seconds() // 60)
    return f"created {created:%Y-%m-%d %H:%M} UTC, {minutes} min ago"


def _matching_exports(asset_url: str, settings: dict) -> list[dict]:
    """This form's recent exports made with the same settings, newest first."""
    rows = _request("GET", f"{asset_url}/exports/", params={"limit": 100}).json().get("results", [])
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=EXPORT_MAX_AGE_HOURS)
    matching = []
    for export in rows:
        data = export.get("data") or {}
        same = data.get("type") == settings.get("type") and all(
            data[k] == v for k, v in settings.items() if k in data
        )
        created = _created(export)
        if same and not pd.isna(created) and created >= cutoff:
            matching.append(export)
    return sorted(matching, key=_created, reverse=True)


def _delete(export_url: str, uid: str) -> None:
    try:
        _request("DELETE", export_url)
    except Exception as e:
        logger.warning(f"Could not delete Kobo export {uid}: {e}")


def _download_export() -> bytes:
    if not (KOBO_ASSET_UID and KOBO_EXPORT_SETTINGS_ID):
        raise ValueError("Kobo download needs an asset_uid and an export_settings_id for the round")
    asset_url = f"{KOBO_BASE_URL}/api/v2/assets/{KOBO_ASSET_UID}"

    # 1. The saved export settings (XML headers, one sheet per repeat, ...)
    saved = _request("GET", f"{asset_url}/export-settings/{KOBO_EXPORT_SETTINGS_ID}/").json()
    settings = saved.get("export_settings") or {}
    logger.info(f"Using saved export '{saved.get('name', KOBO_EXPORT_SETTINGS_ID)}' "
                f"(type {settings.get('type', '?')})")

    # 2. Reuse a recent export with the same settings, or start a new one
    existing = _matching_exports(asset_url, settings)
    finished = next((e for e in existing if e.get("status") == "complete"), None)
    building = next((e for e in existing if e.get("status") in BUILDING), None)
    started_here = False
    if finished:
        logger.info(f"Reusing finished Kobo export {finished['uid']} ({_age(finished)})")
        export = finished
    elif building:
        logger.info(f"Kobo is already building export {building['uid']} ({_age(building)}) — waiting for it")
        export = building
    else:
        export = _request("POST", f"{asset_url}/exports/", json=settings).json()
        started_here = True
        logger.info(f"Kobo export {export['uid']} started — waiting for Kobo to build it")
    export_url = f"{asset_url}/exports/{export['uid']}/"

    # 3. Wait until it is built
    deadline = time.monotonic() + EXPORT_TIMEOUT_MINUTES * 60
    while export.get("status") != "complete":
        status = export.get("status")
        if status == "error":
            if started_here:
                _delete(export_url, export["uid"])
            raise RuntimeError(f"Kobo could not build the export: {export.get('messages') or export}")
        if time.monotonic() > deadline:
            # Left on Kobo on purpose: the next run waits for it instead of starting over
            raise TimeoutError(
                f"Kobo export {export['uid']} not ready after {EXPORT_TIMEOUT_MINUTES:g} minutes "
                f"(last status '{status}'). It stays on Kobo: run again later and the pipeline "
                f"picks it up, or wait longer with KOBO_EXPORT_TIMEOUT_MINUTES."
            )
        time.sleep(POLL_SECONDS)
        export = _request("GET", export_url).json()

    # 4. Download the finished file
    logger.info(f"Kobo export {export['uid']} complete — downloading")
    content = _request("GET", export["result"]).content
    if started_here:
        _delete(export_url, export["uid"])
    return content


def fetch_kobo_data() -> tuple[dict[str, pd.DataFrame], str]:
    """
    Download data from KoboToolbox as an Excel export with XML headers.
    Returns:
        sheets      — dict of { sheet_name: DataFrame }
        main_sheet  — the auto-detected name of the primary (main) sheet
    """
    logger.info(f"Fetching data from Kobo: form {KOBO_ASSET_UID} on {KOBO_BASE_URL}")
    content = _download_export()
    logger.info(f"Download complete — {len(content):,} bytes")

    # Parse all sheets from the downloaded Excel file
    excel_data = pd.read_excel(
        io.BytesIO(content),
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
