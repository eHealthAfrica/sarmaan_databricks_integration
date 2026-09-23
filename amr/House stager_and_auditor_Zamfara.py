""" Stager & Auditor - Household """

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

MAPPING_FILE = os.path.join(MAP_DIR, "amr", "zamfara_household_map.csv")

KOBO_EXPORT_URL = "https://kf.kobotoolbox.org/api/v2/assets/aks5TQaYbfgGvhCigjGAvp/export-settings/esBAy9ZfJutvuffFDgu3Bqt/data.xlsx"
KOBO_SHEET = "SARMAAN II BASELINE ZAMFARA ..."

STAGING_EXCEL = os.path.join(SARMAAN_DIR, "pipeline_output", "zamfara_amr_c1", "STAGING_household_data.xlsx")
AUDIT_PDF     = os.path.join(SARMAAN_DIR, "pipeline_output", "zamfara_amr_c1", "household_audit_report.pdf")

AUDIT_SKIP_LIST = [
    "start_time", "end_time", "enumerator_name", "enumerator_phone_number",
    "date_of_consent", "witness_name", "start_timme", "state", "lga", "ward", "community",
    "household_consent_name", "latitude", "longitude", "household_number",
    "household_code", "household_name", "household_age", "related_to_head_household_name",
    "related_to_head_household_age", "total_no_persons_household",
    "no_wives_0_59_months", "no_children_0_59_months", "no_children_1_59_months",
    "no_children_0_28_days", "no_wives_caregivers", "manifest_url",
    "household_uuid", "end_timme", "submission_id", "concatenated_id",
    "index", "person_completed_household_questionnaire_signature_url",
    "phone_number", "household_number2"
]

VALUE_RECODE_MAP = {
    "education_type_quranic": {"0": "No", "1": "Yes", "0.0": "No", "1.0": "Yes"},
    "education_type_western": {"0": "No", "1": "Yes", "0.0": "No", "1.0": "Yes"},
}

def ts(): return datetime.now(timezone.utc).strftime("%H:%M:%S")

# ─── LOGIC ──────────────────────────────────────────────────────────────────

def load_assets(path):
    m_df = pd.read_csv(path)
    keep_df = m_df.dropna(subset=['db_name'])
    rename_map = dict(zip(keep_df['kobo_name'], keep_df['db_name']))
    drop_list = m_df[m_df['action'].str.lower() == 'drop']['kobo_name'].tolist()
    db_order = keep_df['db_name'].tolist()
    return rename_map, drop_list, db_order

def transform_logic(df, rename_map, drop_list, db_order):
    # 1. Drop and Rename
    # Kobo now exports complete state, LGA, ward, and community names — no lookup needed.
    df = df.drop(columns=[c for c in drop_list if c in df.columns])
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # 2. Value Recoding
    for col, mapping in VALUE_RECODE_MAP.items():
        if col in df.columns:
            df[col] = df[col].map(lambda v, m=mapping: m.get(str(v).strip(), v))

    # 3. Derive ID
    if "household_uuid" in df.columns and "index" in df.columns:
        df["concatenated_id"] = df["household_uuid"].astype(str) + "_" + df["index"].astype(str)

    # 4. Duplicate Check
    if "household_code" in df.columns:
        dupes = df[df.duplicated(subset=['household_code'], keep=False)]
        if not dupes.empty:
            print(f"[{ts()}] WARNING: Found {len(dupes)} rows with duplicate household codes!")
        else:
            print(f"[{ts()}] SUCCESS: All household codes are unique.")

    # Align columns to DB order
    for col in db_order:
        if col not in df.columns:
            df[col] = None
    return df[db_order]

def generate_audit_report(df, output_path):
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    story = [Paragraph("SARMAAN II - Household Data Audit", styles["Title"]), Spacer(1, 12)]

    if "household_code" in df.columns:
        dupes = df[df.duplicated(subset=['household_code'], keep=False)]
        if not dupes.empty:
            warning_style = ParagraphStyle('Warning', parent=styles['Normal'], textColor=colors.red, fontName='Helvetica-Bold')
            story.append(Paragraph("CRITICAL: Duplicate Household Codes Found", styles["Heading2"]))
            dupe_list = ", ".join(dupes['household_code'].unique().astype(str))
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
    rename_map, drop_list, db_order = load_assets(MAPPING_FILE)

    resp = download_kobo_export()
    raw_df = pd.read_excel(io.BytesIO(resp.content), sheet_name=KOBO_SHEET, dtype=str)

    clean_df = transform_logic(raw_df, rename_map, drop_list, db_order)

    os.makedirs(os.path.dirname(STAGING_EXCEL), exist_ok=True)
    clean_df.to_excel(STAGING_EXCEL, index=False)
    print(f"[{ts()}] STAGING FILE SAVED (All Columns): {STAGING_EXCEL}")

    generate_audit_report(clean_df, AUDIT_PDF)
    print(f"[{ts()}] AUDIT PDF SAVED (Filtered): {AUDIT_PDF}")

if __name__ == "__main__":
    main()
