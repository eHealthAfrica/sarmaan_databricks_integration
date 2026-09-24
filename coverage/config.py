"""
config.py — All pipeline settings loaded from environment variables.
Copy .env.example -> .env and fill in your values before running.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
MAPPING_DIR = BASE_DIR / "mappings"
OUTPUT_DIR  = BASE_DIR / "outputs"
LOG_DIR     = BASE_DIR / "logs"

# Mapping files
STEP1_MAP             = MAPPING_DIR / "step_1_map_file.xlsx"
STEP2_MAP             = MAPPING_DIR / "step_2_map_file.xlsx"
STEP3_MAP             = MAPPING_DIR / "step_3_map_file.xlsx"
STEP5_MAP             = MAPPING_DIR / "step_5_map_file.xlsx"
COMPLETENESS_TEMPLATE = MAPPING_DIR / "completeness_and_standardization_template.xlsx"

# ── KoboToolbox ───────────────────────────────────────────────────────────────
KOBO_API_TOKEN          = os.environ["KOBO_API_TOKEN"]
KOBO_ASSET_UID          = os.environ["KOBO_ASSET_UID"]
KOBO_BASE_URL           = os.getenv("KOBO_BASE_URL", "https://kf.kobotoolbox.org")
KOBO_EXPORT_SETTINGS_ID = os.environ["KOBO_EXPORT_SETTINGS_ID"]

# ── PostgreSQL ────────────────────────────────────────────────────────────────
PG_HOST     = os.getenv("PG_HOST", "localhost")
PG_PORT     = os.getenv("PG_PORT", "5432")
PG_DB       = os.environ["PG_DB"]
PG_USER     = os.environ["PG_USER"]
PG_PASSWORD = os.environ["PG_PASSWORD"]

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
