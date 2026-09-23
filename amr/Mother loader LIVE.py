""" Mother Loader """

import os
import sys
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# CONFIGURATION
SARMAAN_DIR = os.getenv("SARMAAN_DIR", r"C:\Users\victoria.akinyemi\Desktop\Projects\SARMAAN\SARMAAN 2\database")
STAGING_EXCEL = os.path.join(SARMAAN_DIR, "pipeline_output", "zamfara_amr_c1", "STAGING_mother_data.xlsx")
POSTGRES_CONFIG = {
    "host": os.getenv("PG_HOST", "127.0.0.1"),
    "port": os.getenv("PG_PORT", "5439"),
    "database": os.getenv("PG_DATABASE", "sarmaan_2"),
    "user": os.getenv("PG_USER", "db_user"),
    "password": os.getenv("PG_PASSWORD"),  # set this in a local .env file - never hardcode it here
}
TARGET_TABLE = "amr_mother_information"
TARGET_SCHEMA = "sarmaan2data"

def ts():
    return datetime.now(timezone.utc).strftime("%H:%M:%S")

def get_engine():
    if not POSTGRES_CONFIG["password"]:
        sys.exit("ERROR: PG_PASSWORD is not set. Create a .env file (see .env.example).")
    url = (f"postgresql+psycopg2://{POSTGRES_CONFIG['user']}:{POSTGRES_CONFIG['password']}"
           f"@{POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}/{POSTGRES_CONFIG['database']}")
    return create_engine(url)

def existing_ids(engine, id_col="concatenated_id"):
    """concatenated_id values already in the target table, so re-running the
    loader on the same staging file doesn't create duplicate rows."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f'SELECT "{id_col}" FROM {TARGET_SCHEMA}.{TARGET_TABLE}'))
            return {row[0] for row in result}
    except Exception as e:
        print(f"[{ts()}] WARNING: could not read existing ids ({e}). Proceeding without dedup check.")
        return set()

def load_to_postgres():
    print(f"[{ts()}] PHASE 2: Loading edited data from {STAGING_EXCEL}...")

    df = pd.read_excel(STAGING_EXCEL, dtype=str)

    if 'household_code_pull' in df.columns:
        df = df.drop(columns=['household_code_pull'])
        print(f"[{ts()}] Dropped 'household_code_pull' column.")

    engine = get_engine()

    if "concatenated_id" in df.columns:
        already_loaded = existing_ids(engine)
        before = len(df)
        df = df[~df["concatenated_id"].isin(already_loaded)]
        if before - len(df):
            print(f"[{ts()}] Skipping {before - len(df)} row(s) already present (matched on concatenated_id)")
    if df.empty:
        print(f"[{ts()}] Nothing new to load.")
        return

    print(f"[{ts()}] Appending {len(df)} rows to {TARGET_TABLE}...")
    df.to_sql(name=TARGET_TABLE, con=engine, schema=TARGET_SCHEMA, if_exists="append", index=False)
    print(f"[{ts()}] SUCCESS: Mother data ingested.")

if __name__ == "__main__":
    load_to_postgres()
