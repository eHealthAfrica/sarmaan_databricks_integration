""" Stager & Auditor Mother """

# Dependencies:
import io, os, sys, requests, pandas as pd
from dotenv import load_dotenv
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from xml.sax.saxutils import escape
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

MAPPING_FILE = os.path.join(MAP_DIR, "amr", "zamfara_mother_map.csv")

KOBO_EXPORT_URL = "https://kf.kobotoolbox.org/api/v2/assets/aks5TQaYbfgGvhCigjGAvp/export-settings/esBAy9ZfJutvuffFDgu3Bqt/data.xlsx"
KOBO_SHEET_MOTHER = "mother_information"
KOBO_SHEET_HH     = "SARMAAN II BASELINE ZAMFARA ..." 

STAGING_EXCEL = os.path.join(SARMAAN_DIR, "pipeline_output", "zamfara_amr_c1", "STAGING_mother_data.xlsx")
AUDIT_PDF     = os.path.join(SARMAAN_DIR, "pipeline_output", "zamfara_amr_c1", "mother_audit_report.pdf")

# Mapping raw Kobo geo headers to DB names for the merge
GEO_MAPPING = {
    "state_name": "state",
    "Confirm your LGA": "lga",
    "Confirm your ward": "ward",
    "Confirm your community": "community",
    "Q10. Cycle": "cycle"
}

# Columns to skip in the PDF report
AUDIT_SKIP_LIST = [
    "state", "lga", "ward", "community", "mother_id", "household_code",
    "mother_code", "mother_name", "mother_age", "no_children_less_1_month", 
    "no_children_1_59_month", "mother_uuid", "submission_id", "concatenated_id",
    "index", "parent_index", "cycle", "mother_signature_url", "father_name",
    "mother_marital_status", "household_code_pull"
]

VALUE_RECODE_MAP = {}

def ts(): 
    return datetime.now(timezone.utc).strftime("%H:%M:%S")

# ─── LOGIC ──────────────────────────────────────────────────────────────────

def load_assets(path):
    m_df = pd.read_csv(path)
    m_df.loc[m_df['kobo_name'] == 'household_code_pull', 'db_name'] = 'household_code_pull'
    
    keep_df = m_df.dropna(subset=['db_name'])
    rename_map = dict(zip(keep_df['kobo_name'], keep_df['db_name']))
    drop_list = m_df[m_df['action'].str.lower() == 'drop']['kobo_name'].tolist()
    db_order = keep_df['db_name'].tolist()
    return rename_map, drop_list, db_order

def transform_logic(df, rename_map, drop_list, db_order):
    # 1. DROP FIRST
    df = df.drop(columns=[c for c in drop_list if c in df.columns])

    # 2. RENAME SECOND
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        
    # 3. DERIVE CONCATENATED ID
    if "mother_uuid" in df.columns and "parent_index" in df.columns:
        df["concatenated_id"] = df["mother_uuid"].astype(str) + "_" + df["parent_index"].astype(str)

    # 4. Duplicate Check
    if "mother_code" in df.columns:
        dupes = df[df.duplicated(subset=['mother_code'], keep=False)]
        if not dupes.empty:
            print(f"[{ts()}] WARNING: Found {len(dupes)} rows with duplicate mother_codes!")
    
    # 5. Align columns
    for col in db_order:
        if col not in df.columns: df[col] = None
    return df[db_order]

def generate_audit_report(df, output_path):
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    story = [Paragraph("SARMAAN II - Mother Data Audit", styles["Title"]), Spacer(1, 12)]
    
    if "mother_code" in df.columns:
        dupes = df[df.duplicated(subset=['mother_code'], keep=False)]
        if not dupes.empty:
            warning_style = ParagraphStyle('Warning', parent=styles['Normal'], textColor=colors.red, fontName='Helvetica-Bold')
            story.append(Paragraph("CRITICAL: Duplicate Mother Codes Found", styles["Heading2"]))
            dupe_list = ", ".join(dupes['mother_code'].unique().astype(str))
            story.append(Paragraph(f"Duplicates: {escape(dupe_list)}", warning_style))
            story.append(Spacer(1, 20))

    report_columns = [c for c in df.columns if c not in AUDIT_SKIP_LIST]
    for col in report_columns:
        clean = df[col].dropna().loc[df[col].astype(str).str.strip() != ""]
        if clean.empty: continue
        freq = clean.value_counts().reset_index()
        freq.columns = ["Value", "Counts"]
        data = [["Value", "Counts"]] + [[str(r[0]), str(int(r[1]))] for r in freq.head(50).values]
        t = Table(data, colWidths=[350, 100], repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor("#2F5496")),
            ('TEXTCOLOR',(0,0),(-1,0),colors.white),
            ('GRID',(0,0),(-1,-1),0.5,colors.grey),
            ('FONTSIZE', (0,0), (-1,-1), 8)
        ]))
        story.append(KeepTogether([Paragraph(escape(str(col)), styles["Heading3"]), t]))
        story.append(Spacer(1, 15))
    doc.build(story)

def download_kobo_export():
    headers = {"Authorization": f"Token {KOBO_TOKEN}"} if KOBO_TOKEN else {}
    resp = requests.get(KOBO_EXPORT_URL, headers=headers, timeout=300)
    if resp.status_code != 200:
        sys.exit(f"ERROR: Kobo download failed with status {resp.status_code} - check KOBO_TOKEN")
    return resp

def main():
    print(f"[{ts()}] Starting Phase 1: Mother Extraction & Audit...")
    rename_map, drop_list, db_order = load_assets(MAPPING_FILE)
    
    resp = download_kobo_export()
        
    content = io.BytesIO(resp.content)
    
    try:
        df_mother = pd.read_excel(content, sheet_name=KOBO_SHEET_MOTHER, dtype=str, engine='openpyxl')
        df_hh = pd.read_excel(content, sheet_name=KOBO_SHEET_HH, dtype=str, engine='openpyxl')
    except Exception as e:
        print(f"[{ts()}] ERROR reading Excel: {e}")
        return
    
    # 3. SURGICAL MERGE
    hh_cols_to_pull = ["_uuid", "unique_code"] + list(GEO_MAPPING.keys())
    hh_subset = df_hh[[c for c in hh_cols_to_pull if c in df_hh.columns]].copy()
    
    rename_dict = {**GEO_MAPPING, "unique_code": "household_code_pull", "_uuid": "link_key"}
    hh_subset = hh_subset.rename(columns=rename_dict)

    df_mother = df_mother.merge(
        hh_subset, 
        left_on="_submission__uuid", 
        right_on="link_key", 
        how="left"
    )

    # 4. Transform
    clean_df = transform_logic(df_mother, rename_map, drop_list, db_order)
    
    # 5. Save
    os.makedirs(os.path.dirname(STAGING_EXCEL), exist_ok=True)
    clean_df.to_excel(STAGING_EXCEL, index=False)
    print(f"[{ts()}] STAGING FILE SAVED: {STAGING_EXCEL}")
    
    # 6. PDF
    generate_audit_report(clean_df, AUDIT_PDF)
    print(f"[{ts()}] AUDIT PDF SAVED: {AUDIT_PDF}")

if __name__ == "__main__":
    main()