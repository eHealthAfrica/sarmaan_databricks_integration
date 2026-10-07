"""
config.py — All pipeline settings.

Which Kobo form to run is chosen by KOBO_ROUND (e.g. zamfara_c1), looked up in
config/kobo_assets.yml at the repo root. The Kobo API token comes from the
Databricks secret scope "sarmaan" when running in Databricks, or from .env
when testing on a laptop. Other settings come from environment variables or
.env (copy .env.example -> .env).
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
REPO_DIR    = BASE_DIR.parent
MAPPING_DIR = BASE_DIR / "mappings"
# Where the step outputs (Excel) and logs go. Defaults to the coverage folder;
# in Databricks the notebook points it at a temporary folder so survey data is
# never written into the Git folder.
WORK_DIR    = Path(os.getenv("COVERAGE_WORK_DIR", str(BASE_DIR)))
OUTPUT_DIR  = WORK_DIR / "outputs"
LOG_DIR     = WORK_DIR / "logs"

# Mapping files
STEP1_MAP             = MAPPING_DIR / "step_1_map_file.xlsx"
STEP2_MAP             = MAPPING_DIR / "step_2_map_file.xlsx"
STEP3_MAP             = MAPPING_DIR / "step_3_map_file.xlsx"
STEP5_MAP             = MAPPING_DIR / "step_5_map_file.xlsx"
COMPLETENESS_TEMPLATE = MAPPING_DIR / "completeness_and_standardization_template.xlsx"

# ── KoboToolbox ───────────────────────────────────────────────────────────────
KOBO_ASSETS_FILE = REPO_DIR / "config" / "kobo_assets.yml"
KOBO_STREAM      = "coverage"
KOBO_ROUND       = os.getenv("KOBO_ROUND", "").strip().lower()   # e.g. zamfara_c1
SECRET_SCOPE     = os.getenv("SARMAAN_SECRET_SCOPE", "sarmaan")


def get_dbutils():
    """Databricks' dbutils when running in Databricks, else None (laptop)."""
    try:
        from pyspark.sql import SparkSession
        from pyspark.dbutils import DBUtils
    except ImportError:
        return None
    spark = SparkSession.getActiveSession()
    return DBUtils(spark) if spark else None


def _kobo_token() -> str:
    dbutils = get_dbutils()
    if dbutils is not None:
        return dbutils.secrets.get(SECRET_SCOPE, "kobo-token")
    token = os.getenv("KOBO_API_TOKEN", "")
    if not token:
        raise ValueError("No Kobo token: set KOBO_API_TOKEN in .env (laptop) or run in Databricks")
    return token


def kobo_asset(stream: str, round_name: str) -> dict:
    """The kobo_assets.yml entry for a stream and round, with defaults applied."""
    assets = yaml.safe_load(KOBO_ASSETS_FILE.read_text(encoding="utf-8")) or {}
    entries = assets.get(stream) or {}
    if round_name not in entries:
        raise ValueError(
            f"'{round_name}' is not listed under '{stream}' in {KOBO_ASSETS_FILE.name}. "
            f"Listed: {', '.join(sorted(entries))}"
        )
    entry = {**(assets.get("defaults") or {}), **(entries[round_name] or {})}
    if not entry.get("asset_uid"):
        raise ValueError(f"'{stream}.{round_name}' in {KOBO_ASSETS_FILE.name} has no asset_uid yet")
    return entry


if KOBO_ROUND:
    _asset = kobo_asset(KOBO_STREAM, KOBO_ROUND)
    KOBO_BASE_URL           = _asset.get("base_url", "https://kf.kobotoolbox.org").rstrip("/")
    KOBO_ASSET_UID          = _asset["asset_uid"]
    KOBO_EXPORT_SETTINGS_ID = _asset.get("export_settings_id") or ""
else:   # laptop testing with .env, no round chosen
    KOBO_BASE_URL           = os.getenv("KOBO_BASE_URL", "https://kf.kobotoolbox.org").rstrip("/")
    KOBO_ASSET_UID          = os.getenv("KOBO_ASSET_UID", "")
    KOBO_EXPORT_SETTINGS_ID = os.getenv("KOBO_EXPORT_SETTINGS_ID", "")

KOBO_API_TOKEN = _kobo_token()

# Sampling frame (location code -> name lookup) for the chosen round:
# mappings/rounds/<round>/dat.csv. Without a round, mappings/dat.csv.
if KOBO_ROUND:
    DAT_FILE = MAPPING_DIR / "rounds" / KOBO_ROUND / "dat.csv"
    if not DAT_FILE.exists():
        raise FileNotFoundError(f"No sampling frame for '{KOBO_ROUND}': expected {DAT_FILE}")
else:
    DAT_FILE = MAPPING_DIR / "dat.csv"

# ── Load target (step 6) ─────────────────────────────────────────────────────
# databricks (default) | postgres | both
# "both" loads the same run into Postgres and Databricks, for the parallel run
# before switching over.
LOAD_TARGET = os.getenv("LOAD_TARGET", "databricks").strip().lower()

# ── Databricks ────────────────────────────────────────────────────────────────
# Server hostname and HTTP path: SQL Warehouses > (your warehouse) > Connection details.
DATABRICKS_SERVER_HOSTNAME = os.getenv("DATABRICKS_SERVER_HOSTNAME", "")
DATABRICKS_HTTP_PATH       = os.getenv("DATABRICKS_HTTP_PATH", "")
# Sign in with EITHER a personal access token (DATABRICKS_TOKEN) OR a service
# principal (DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET, OAuth).
DATABRICKS_TOKEN         = os.getenv("DATABRICKS_TOKEN", "")
DATABRICKS_CLIENT_ID     = os.getenv("DATABRICKS_CLIENT_ID", "")
DATABRICKS_CLIENT_SECRET = os.getenv("DATABRICKS_CLIENT_SECRET", "")

# Unity Catalog names (architecture review; see architecture.py):
#   catalog    -> eha_ghi_sarmaan_dev (development) or eha_ghi_sarmaan_prod (production)
#   bronze     -> coverage_*              (step 1: every submission, all text, lineage columns)
#   silver     -> coverage_*              (step 2: every submission, readable names)
#   gold       -> coverage_*              (step 5: approved only, typed, no identifiers)
#   restricted -> coverage_*_identifiers  (names, phones, GPS, card images for gold rows)
DATABRICKS_CATALOG           = os.getenv("DATABRICKS_CATALOG", "eha_ghi_sarmaan_dev")
DATABRICKS_BRONZE_SCHEMA     = os.getenv("DATABRICKS_BRONZE_SCHEMA", "bronze")
DATABRICKS_SILVER_SCHEMA     = os.getenv("DATABRICKS_SILVER_SCHEMA", "silver")
DATABRICKS_GOLD_SCHEMA       = os.getenv("DATABRICKS_GOLD_SCHEMA", "gold")
DATABRICKS_RESTRICTED_SCHEMA = os.getenv("DATABRICKS_RESTRICTED_SCHEMA", "restricted")
# Volume where step 6 stages Parquet files before merging them into tables.
DATABRICKS_STAGING_VOLUME = os.getenv(
    "DATABRICKS_STAGING_VOLUME", f"/Volumes/{DATABRICKS_CATALOG}/bronze/landing"
)

# ── PostgreSQL (only when LOAD_TARGET is postgres or both) ───────────────────
PG_HOST     = os.getenv("PG_HOST", "localhost")
PG_PORT     = os.getenv("PG_PORT", "5432")
PG_DB       = os.getenv("PG_DB", "")
PG_USER     = os.getenv("PG_USER", "")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")

# Target schemas in the database. The DB already stores coverage data as:
#   raw   -> raw_data.coverage_household / coverage_all_children / coverage_net_info / coverage_children_1_59
#   clean -> sarmaan2data.coverage_household / coverage_all_children / coverage_net_info / coverage_children_1_59
# These must be pointed at so appends land in the existing tables (no new tables).
PG_RAW_SCHEMA   = os.getenv("PG_RAW_SCHEMA", "raw_data")
PG_CLEAN_SCHEMA = os.getenv("PG_CLEAN_SCHEMA", "sarmaan2data")

# ── Output file names (local only) ───────────────────────────────────────────
# Step 2 and Step 3 filenames are built dynamically by naming.py
# Format: SARMAAN_II_COVERAGE_{STATE}_{CYCLE}_RAW.xlsx / _CLEANED.xlsx
STEP1_FILENAME = "01_raw_xml_export.xlsx"
STEP4_FILENAME = "04_validation_report.xlsx"
STEP5_FILENAME = "05_db_ready.xlsx"

# ── Sheet names ───────────────────────────────────────────────────────────────
KNOWN_REPEAT_SHEETS = ["child_info", "net_repeat", "child_infoo", "g_polygon_ward", "g_polygon_ward2"]

MERGE_SHEET_HOUSEHOLD = "household_info"
MERGE_SHEET_NET       = "net_info"

VALIDATION_STATUS_APPROVED = "validation_status_approved"
