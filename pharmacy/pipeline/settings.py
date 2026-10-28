"""
settings.py — Settings for the Pharmacy Databricks pipeline.

Which Kobo form to run is chosen by the round (e.g. zamfara_c1), looked up
under `pharmacy:` in config/kobo_assets.yml. The entry also gives the round's
`cycle` (e.g. "Year 1"): the form has no cycle question. The Kobo API token comes from the
Databricks secret scope "sarmaan" (key kobo-token), or from KOBO_API_TOKEN in
the environment when testing on a laptop.

Everything is read when a run starts (Settings.load), not at import, so one
notebook session can run several rounds.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

PHARMACY_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = PHARMACY_DIR.parent
MAP_DIR = REPO_DIR / "map" / "pharmacy"
KOBO_ASSETS_FILE = REPO_DIR / "config" / "kobo_assets.yml"
GOLD_TYPES_FILE = MAP_DIR / "gold_types.csv"
MAP_FILE = MAP_DIR / "zamfara_pharmacy_map.csv"
LGA_LOOKUP_FILE = MAP_DIR / "zamfara_pharmacy_lga_lookup.csv"

STREAM = "pharmacy"
SECRET_SCOPE = "sarmaan"
APPROVED = "validation_status_approved"

# Used when the round has no saved export (export_settings_id): XML names as
# headers, one sheet per repeat, multiple-choice answers also split into one
# 0/1 column per option, and media files as links (<question>_URL).
DEFAULT_EXPORT_SETTINGS = {
    "type": "xls",
    "lang": "_xml",
    "hierarchy_in_labels": False,
    "group_sep": "/",
    "multiple_select": "both",
    "fields_from_all_versions": True,
    "include_media_url": True,
    "xls_types_as_text": False,
}


@dataclass
class Settings:
    round: str
    catalog: str
    dry_run: bool
    kobo_base_url: str
    kobo_asset_uid: str
    kobo_export_settings_id: str
    kobo_token: str
    cycle: str = ""
    blank_status_is_approved: bool = False
    export_wait_minutes: float = 60
    pipeline_version: str = "unknown"

    @property
    def landing_dir(self) -> str:
        """Volume folder for this round's raw exports and run logs."""
        return f"/Volumes/{self.catalog}/bronze/landing/pharmacy/{self.round}"

    @classmethod
    def load(cls, round_name: str, catalog: str, dry_run: bool,
             export_wait_minutes: float = 60, pipeline_version: str = "",
             dbutils=None) -> "Settings":
        entry = kobo_asset(round_name)
        return cls(
            round=round_name,
            catalog=catalog,
            dry_run=dry_run,
            kobo_base_url=entry.get("base_url", "https://kf.kobotoolbox.org").rstrip("/"),
            kobo_asset_uid=entry["asset_uid"],
            kobo_export_settings_id=entry.get("export_settings_id") or "",
            kobo_token=_kobo_token(dbutils),
            cycle=entry.get("cycle", ""),
            blank_status_is_approved=bool(entry.get("blank_status_is_approved", False)),
            export_wait_minutes=export_wait_minutes,
            pipeline_version=pipeline_version or "unknown",
        )


def kobo_asset(round_name: str) -> dict:
    """The kobo_assets.yml entry for a Pharmacy round, with defaults applied."""
    assets = yaml.safe_load(KOBO_ASSETS_FILE.read_text(encoding="utf-8")) or {}
    entries = assets.get(STREAM) or {}
    if round_name not in entries:
        raise ValueError(
            f"'{round_name}' is not listed under '{STREAM}' in {KOBO_ASSETS_FILE.name}. "
            f"Listed: {', '.join(sorted(entries))}"
        )
    entry = {**(assets.get("defaults") or {}), **(entries[round_name] or {})}
    if not entry.get("asset_uid"):
        raise ValueError(f"'{STREAM}.{round_name}' in {KOBO_ASSETS_FILE.name} has no asset_uid yet")
    return entry


def _kobo_token(dbutils) -> str:
    if dbutils is not None:
        return dbutils.secrets.get(SECRET_SCOPE, "kobo-token")
    token = os.getenv("KOBO_API_TOKEN", "")
    if not token:
        raise ValueError("No Kobo token: run in Databricks, or set KOBO_API_TOKEN on a laptop")
    return token
