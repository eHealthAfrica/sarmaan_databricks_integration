"""
kobo.py — Download the Mortality form from KoboToolbox as an Excel export with XML
headers (one sheet per repeat), the same way as coverage/extractor.py:

  1. Export settings: the round's saved export (export_settings_id), or
     settings.DEFAULT_EXPORT_SETTINGS when it has none.
  2. Reuse an export of this form with the same settings from the last
     KOBO_EXPORT_MAX_AGE_HOURS (default 24), finished or still building;
     otherwise ask Kobo to start a new one.
  3. Check every few seconds until Kobo reports it complete. An export that is
     not ready in time is left on Kobo, so the next run picks it up.
  4. Download the file. Only exports this run started are deleted from Kobo.

Asking for the file in one request makes Kobo build it while the request
waits, which times out (504) on large forms.
"""

import io
import logging
import os
import time

import pandas as pd
import requests

from .settings import DEFAULT_EXPORT_SETTINGS, Settings

logger = logging.getLogger(__name__)

POLL_SECONDS = 10
EXPORT_MAX_AGE_HOURS = float(os.getenv("KOBO_EXPORT_MAX_AGE_HOURS", "24"))
RETRY_STATUSES = {429, 500, 502, 503, 504}
BUILDING = ("created", "processing")


class Kobo:
    def __init__(self, s: Settings):
        self.s = s
        self.asset_url = f"{s.kobo_base_url}/api/v2/assets/{s.kobo_asset_uid}"

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """One Kobo API call, retried a few times on busy-server errors."""
        headers = {"Authorization": f"Token {self.s.kobo_token}"}
        for attempt in range(1, 5):
            response = requests.request(method, url, headers=headers, timeout=120, **kwargs)
            if response.status_code not in RETRY_STATUSES or attempt == 4:
                response.raise_for_status()
                return response
            wait = 15 * attempt
            logger.warning(f"Kobo returned {response.status_code} for {method} {url} — retrying in {wait}s")
            time.sleep(wait)
        raise AssertionError("unreachable")

    def _settings(self) -> dict:
        if not self.s.kobo_export_settings_id:
            logger.info("No saved export for this round — using XML headers, one sheet per repeat")
            return dict(DEFAULT_EXPORT_SETTINGS)
        saved = self._request(
            "GET", f"{self.asset_url}/export-settings/{self.s.kobo_export_settings_id}/").json()
        logger.info(f"Using saved export '{saved.get('name', self.s.kobo_export_settings_id)}'")
        return saved.get("export_settings") or {}

    def _matching(self, settings: dict) -> list[dict]:
        """This form's recent exports made with the same settings, newest first."""
        rows = self._request("GET", f"{self.asset_url}/exports/", params={"limit": 100}).json().get("results", [])
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=EXPORT_MAX_AGE_HOURS)
        found = []
        for export in rows:
            data = export.get("data") or {}
            same = data.get("type") == settings.get("type") and all(
                data[k] == v for k, v in settings.items() if k in data)
            created = pd.to_datetime(export.get("date_created"), utc=True, errors="coerce")
            if same and not pd.isna(created) and created >= cutoff:
                found.append((created, export))
        return [e for _, e in sorted(found, key=lambda p: p[0], reverse=True)]

    def _delete(self, export: dict) -> None:
        try:
            self._request("DELETE", f"{self.asset_url}/exports/{export['uid']}/")
        except Exception as e:
            logger.warning(f"Could not delete Kobo export {export['uid']}: {e}")

    def download(self) -> bytes:
        settings = self._settings()
        existing = self._matching(settings)
        export = (next((e for e in existing if e.get("status") == "complete"), None)
                  or next((e for e in existing if e.get("status") in BUILDING), None))
        started_here = export is None
        if started_here:
            export = self._request("POST", f"{self.asset_url}/exports/", json=settings).json()
            logger.info(f"Kobo export {export['uid']} started — waiting for Kobo to build it")
        else:
            logger.info(f"Reusing Kobo export {export['uid']} (status {export.get('status')}, "
                        f"created {export.get('date_created')})")

        deadline = time.monotonic() + self.s.export_wait_minutes * 60
        while export.get("status") != "complete":
            if export.get("status") == "error":
                if started_here:
                    self._delete(export)
                raise RuntimeError(f"Kobo could not build the export: {export.get('messages') or export}")
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Kobo export {export['uid']} not ready after {self.s.export_wait_minutes:g} minutes. "
                    f"It stays on Kobo: run again later and it is picked up.")
            time.sleep(POLL_SECONDS)
            export = self._request("GET", f"{self.asset_url}/exports/{export['uid']}/").json()

        content = self._request("GET", export["result"]).content
        logger.info(f"Kobo export {export['uid']} downloaded — {len(content):,} bytes")
        if started_here:
            self._delete(export)
        return content


def read_export(content: bytes) -> dict[str, pd.DataFrame]:
    """Every sheet of the export, all values as text ('' for blank)."""
    return pd.read_excel(io.BytesIO(content), sheet_name=None, dtype=str, na_filter=False)
