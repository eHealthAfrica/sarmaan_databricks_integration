""" Loader - Mortality (Household / Female / Pregnancy History) """

import os
import sys
import pandas as pd
from sqlalchemy import create_engine, inspect, text
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIGURATION ──────────────────────────────────────────────────────────
MORTALITY_DIR = os.getenv("MORTALITY_DIR", r"C:\Users\victoria.akinyemi\Desktop\Projects\Mortality\database")
STAGING_EXCEL = os.path.join(MORTALITY_DIR, "pipeline_output", "mortality", "STAGING_mortality_data.xlsx")

POSTGRES_CONFIG = {
    "host": os.getenv("PG_HOST", "127.0.0.1"),
    "port": os.getenv("PG_PORT", "5439"),
    "database": os.getenv("PG_DATABASE", "mortality"),
    "user": os.getenv("PG_USER", "db_user"),
    "password": os.getenv("PG_PASSWORD"),  # set this in a local .env file - never hardcode it here
}

TARGET_SCHEMA = "mortalitydata"

# Load order matters: household must be committed before female (female
# references household via household_code / concatenated_id), and female
# before pregnancy (pregnancy references the mother via mother_code / its own
# parent_index chain). Loading out of order won't break a plain append, but
# keeping this order makes any future FK constraints / triggers safe.
TABLES = [
    ("household", "household_mortality"),
    ("female", "females_mortality"),
    ("pregnancy", "pregnancy_mortality"),
]

def ts(): return datetime.now(timezone.utc).strftime("%H:%M:%S")

def get_engine():
    if not POSTGRES_CONFIG["password"]:
        sys.exit("ERROR: PG_PASSWORD is not set. Create a .env file next to this script with PG_HOST, "
                 "PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD (see .env.example).")
    url = (f"postgresql+psycopg2://{POSTGRES_CONFIG['user']}:{POSTGRES_CONFIG['password']}"
           f"@{POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}/{POSTGRES_CONFIG['database']}")
    return create_engine(url)

def existing_ids(engine, table, id_col="concatenated_id"):
    """Pull concatenated_id values already in the target table, so re-running
    the loader on the same staging file doesn't create duplicate rows."""
    # A missing table means nothing is loaded yet; any other error stops the
    # load rather than appending without the check.
    if not inspect(engine).has_table(table, schema=TARGET_SCHEMA):
        print(f"[{ts()}] {TARGET_SCHEMA}.{table} does not exist yet - nothing to check against.")
        return set()
    with engine.connect() as conn:
        result = conn.execute(text(f'SELECT "{id_col}" FROM {TARGET_SCHEMA}.{table}'))
        return {row[0] for row in result}

def load_table(engine, sheet_name, table_name):
    print(f"[{ts()}] Reading '{sheet_name}' sheet from {STAGING_EXCEL}...")
    df = pd.read_excel(STAGING_EXCEL, sheet_name=sheet_name, dtype=str)

    if "concatenated_id" in df.columns:
        already_loaded = existing_ids(engine, table_name)
        if already_loaded:
            before = len(df)
            df = df[~df["concatenated_id"].isin(already_loaded)]
            skipped = before - len(df)
            if skipped:
                print(f"[{ts()}] Skipping {skipped} row(s) already present in {table_name} (matched on concatenated_id)")

    if df.empty:
        print(f"[{ts()}] Nothing new to load into {table_name}.")
        return

    print(f"[{ts()}] Appending {len(df)} row(s) to {TARGET_SCHEMA}.{table_name}...")
    df.to_sql(name=table_name, con=engine, schema=TARGET_SCHEMA, if_exists="append", index=False)
    print(f"[{ts()}] SUCCESS: {table_name} updated.")

def main():
    print(f"[{ts()}] PHASE 2: Loading staged mortality data...")
    engine = get_engine()
    for sheet_name, table_name in TABLES:
        load_table(engine, sheet_name, table_name)
    print(f"[{ts()}] All tables processed.")

if __name__ == "__main__":
    main()
