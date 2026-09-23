""" Stager & Auditor - Pharmacy """

# Dependencies:
import io, os, sys, requests, pandas as pd
from dotenv import load_dotenv
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

load_dotenv()

# ─── CONFIGURATION ──────────────────────────────────────────────────────────
SARMAAN_DIR = os.getenv("SARMAAN_DIR", r"C:\Users\victoria.akinyemi\Desktop\Projects\SARMAAN\SARMAAN 2\database")
KOBO_TOKEN = os.getenv("KOBO_TOKEN")  # Kobo API token - set in .env, never hardcode
# mapping CSVs live in the repo's map/ folder
MAP_DIR = os.getenv("MAP_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "map"))

MAPPING_FILE = os.path.join(MAP_DIR, "pharmacy", "zamfara_pharmacy_map.csv")
LGA_LOOKUP_FILE = os.path.join(MAP_DIR, "pharmacy", "zamfara_pharmacy_lga_lookup.csv")

KOBO_EXPORT_URL = "https://kf.kobotoolbox.org/api/v2/assets/aLcuF4wGExja3LrSZxEEnB/export-settings/esoXu2auPC68oteb2G3UuGA/data.xlsx"
KOBO_SHEET = "SARMAAN II BASELINE ZAMFARA ..."

STAGING_EXCEL = os.path.join(SARMAAN_DIR, "pipeline_output", "zamfara_pharmacy_c1", "STAGING_pharmacy_data.xlsx")
AUDIT_PDF     = os.path.join(SARMAAN_DIR, "pipeline_output", "zamfara_pharmacy_c1", "pharmacy_audit_report.pdf")

CYCLE = "Year 1"  # existing Zamfara rows in db were loaded with NULL cycle; set per ingest

AUDIT_SKIP_LIST = [
    "start_time", "end_time", "enumerator_name", "enumerator_phone_number",
    "pharmacy_photo_url", "pharmacist_name", "pharmacist_signature_url",
    "date_of_consent", "witness_name", "start_timme", "state", "lga", "ward",
    "latitude", "longitude", "pharmacy_number", "pharmacy_code",
    "pharmacist_age", "training_year", "experience_years",
    "people_count_ask_antibitoics", "people_count_sell_antibitoics_with_prescription",
    "people_count_sell_antibitoics_no_prescription", "combine_antibiotics_count",
    "days_antibiotics_injection", "pharmacy_uuid", "submission_id",
    "concatenated_id", "index"
]

# Yes/No radio questions: Kobo label casing varies by form version (yes/Yes/no/No)
YESNO_RECODE_COLS = [
    "consent", "witness", "know_antibiotics", "trained_antibiotics_use",
    "prescriptions_before_antibiotics", "sell_less_than_required_antibiotics",
    "combine_antibiotics", "antibiotics_prevent_infection",
    "administer_antibiotic_injections",
]
YESNO_MAP = {"yes": "Yes", "no": "No"}

VALUE_RECODE_MAP = {
    "settlement_type": {"rural": "Rural", "urban": "Urban"},
    "pharmacist_gender": {"male": "Male", "female": "Female"},
}

# Multi-select split columns: Kobo exports 0/1, db stores No/Yes
BINARY_PREFIXES = (
    "define_antibiotics_", "prescriptions_before_antibiotics_reason_",
    "prescriptions_before_antibiotics_no_reason_", "suspected_conditions_antibiotics_",
    "administer_antibiotic_injections_name_", "antibiotics_in_shop_",
)
BINARY_MAP = {"0": "No", "1": "Yes", "0.0": "No", "1.0": "Yes"}

# Datetime columns truncated to date to match existing db convention
DATE_TRUNCATE_COLS = ["start_time", "end_time", "date_of_consent", "training_year"]

def ts(): return datetime.now(timezone.utc).strftime("%H:%M:%S")

# ─── LOGIC ──────────────────────────────────────────────────────────────────

def load_assets(map_path, lga_path):
    m_df = pd.read_csv(map_path)
    keep_df = m_df[m_df['action'].str.lower() == 'keep'].copy()
    keep_df['kobo_name'] = keep_df['kobo_name'].fillna("")
    rename_map = dict(zip(keep_df.loc[keep_df['kobo_name'] != "", 'kobo_name'],
                          keep_df.loc[keep_df['kobo_name'] != "", 'db_name']))
    drop_list = m_df[m_df['action'].str.lower() == 'drop']['kobo_name'].tolist()
    db_order = keep_df['db_name'].tolist()

    lga_df = pd.read_csv(lga_path, dtype=str)
    lga_map = dict(zip(lga_df['lga_code'], lga_df['lga_name']))
    return rename_map, drop_list, db_order, lga_map

def transform_logic(df, rename_map, drop_list, db_order, lga_map):
    # 1. Drop and Rename
    df = df.drop(columns=[c for c in drop_list if c in df.columns])
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # 2. LGA lookup: older form versions export the numeric LGA code, newer export names
    if "lga" in df.columns:
        df["lga"] = df["lga"].map(lambda v: lga_map.get(str(v).strip(), v))
        unresolved = df.loc[df["lga"].astype(str).str.fullmatch(r"\d+", na=False), "lga"].unique()
        if len(unresolved):
            print(f"[{ts()}] WARNING: Unresolved LGA codes: {list(unresolved)} - update {LGA_LOOKUP_FILE}")

    # 3. Value Recoding
    for col in YESNO_RECODE_COLS:
        if col in df.columns:
            df[col] = df[col].map(lambda v: YESNO_MAP.get(str(v).strip().lower(), v) if pd.notna(v) else v)
    for col, mapping in VALUE_RECODE_MAP.items():
        if col in df.columns:
            df[col] = df[col].map(lambda v, m=mapping: m.get(str(v).strip().lower(), v) if pd.notna(v) else v)
    for col in df.columns:
        if col.startswith(BINARY_PREFIXES) and not col.endswith("_specified"):
            df[col] = df[col].map(lambda v: BINARY_MAP.get(str(v).strip(), v) if pd.notna(v) else v)

    # 4. Date truncation (db stores dates only for these)
    for col in DATE_TRUNCATE_COLS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], format="mixed", errors="coerce").dt.strftime("%Y-%m-%d")

    # 5. Constants & Derived ID
    df["cycle"] = CYCLE
    if "pharmacy_uuid" in df.columns and "index" in df.columns:
        df["concatenated_id"] = df["pharmacy_uuid"].astype(str) + "_" + df["index"].astype(str)

    # 6. Duplicate Check
    if "pharmacy_code" in df.columns:
        dupes = df[df.duplicated(subset=['pharmacy_code'], keep=False)]
        if not dupes.empty:
            print(f"[{ts()}] WARNING: Found {len(dupes)} rows with duplicate pharmacy codes!")
        else:
            print(f"[{ts()}] SUCCESS: All pharmacy codes are unique.")

    # Align columns to DB order
    for col in db_order:
        if col not in df.columns:
            df[col] = None
    return df[db_order]

def generate_audit_report(df, output_path):
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    story = [Paragraph("SARMAAN II - Pharmacy Data Audit", styles["Title"]), Spacer(1, 12)]

    if "pharmacy_code" in df.columns:
        dupes = df[df.duplicated(subset=['pharmacy_code'], keep=False)]
        if not dupes.empty:
            warning_style = ParagraphStyle('Warning', parent=styles['Normal'], textColor=colors.red, fontName='Helvetica-Bold')
            story.append(Paragraph("CRITICAL: Duplicate Pharmacy Codes Found", styles["Heading2"]))
            dupe_list = ", ".join(dupes['pharmacy_code'].unique().astype(str))
            story.append(Paragraph(f"The following codes appear multiple times: {dupe_list}", warning_style))
            story.append(Spacer(1, 20))

    report_columns = [c for c in df.columns if c not in AUDIT_SKIP_LIST]

    for col in report_columns:
        clean = df[col].dropna().loc[df[col].astype(str).str.strip() != ""]
        if clean.empty:
            continue

        freq = clean.value_counts().reset_index()
        freq.columns = ["Value", "Counts"]

        data = [["Value", "Counts"]] + [[str(r[0]), str(int(r[1]))] for r in freq.head(50).values]
        t = Table(data, colWidths=[350, 100], repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2F5496")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 0), (-1, -1), 8)
        ]))
        story.append(KeepTogether([Paragraph(f"{col}", styles["Heading3"]), t]))
        story.append(Spacer(1, 15))

    doc.build(story)

def download_kobo_export():
    headers = {"Authorization": f"Token {KOBO_TOKEN}"} if KOBO_TOKEN else {}
    resp = requests.get(KOBO_EXPORT_URL, headers=headers, timeout=300)
    if resp.status_code != 200:
        sys.exit(f"ERROR: Kobo download failed with status {resp.status_code} - check KOBO_TOKEN")
    return resp

def main():
    print(f"[{ts()}] Starting Phase 1: Extraction & Audit...")
    rename_map, drop_list, db_order, lga_map = load_assets(MAPPING_FILE, LGA_LOOKUP_FILE)

    resp = download_kobo_export()
    raw_df = pd.read_excel(io.BytesIO(resp.content), sheet_name=KOBO_SHEET, dtype=str)

    clean_df = transform_logic(raw_df, rename_map, drop_list, db_order, lga_map)

    os.makedirs(os.path.dirname(STAGING_EXCEL), exist_ok=True)
    clean_df.to_excel(STAGING_EXCEL, index=False)
    print(f"[{ts()}] STAGING FILE SAVED (All Columns): {STAGING_EXCEL}")

    generate_audit_report(clean_df, AUDIT_PDF)
    print(f"[{ts()}] AUDIT PDF SAVED (Filtered): {AUDIT_PDF}")

if __name__ == "__main__":
    main()
