""" Stager & Auditor Child """

import io, os, sys, requests, pandas as pd
from dotenv import load_dotenv
from datetime import datetime, timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

load_dotenv()

# ─── CONFIGURATION ──────────────────────────────────────────────────────────
SARMAAN_DIR = os.getenv("SARMAAN_DIR", r"C:\Users\victoria.akinyemi\Desktop\Projects\SARMAAN\SARMAAN 2\database")
KOBO_TOKEN = os.getenv("KOBO_TOKEN")  # Kobo API token - set in .env, never hardcode

MAPPING_FILE = os.path.join(SARMAAN_DIR, "zamfara_child_map.csv")

KOBO_EXPORT_URL = "https://kf.kobotoolbox.org/api/v2/assets/aks5TQaYbfgGvhCigjGAvp/export-settings/esBAy9ZfJutvuffFDgu3Bqt/data.xlsx"

KOBO_SHEET_CHILD  = "child_info"
KOBO_SHEET_MOTHER = "mother_information"
KOBO_SHEET_HH     = "SARMAAN II BASELINE ZAMFARA ..." 

STAGING_EXCEL = os.path.join(SARMAAN_DIR, "pipeline_output", "zamfara_amr_c1", "STAGING_child_data.xlsx")
AUDIT_PDF     = os.path.join(SARMAAN_DIR, "pipeline_output", "zamfara_amr_c1", "child_audit_report.pdf")

GEO_MAPPING = {
    "state_name": "state",
    "Confirm your LGA": "lga",
    "Confirm your ward": "ward",
    "Confirm your community": "community",
    "Q10. Cycle": "cycle"
}

YES_NO_COLUMNS = [
    "Q67. Current Feeding Mode/Breastfeeding",
    "Q67. Current Feeding Mode/Formula",
    "Q67. Current Feeding Mode/Family Diet",
    "Q67. Current Feeding Mode/Pap/Cereals and milk",
    "Q74d. Which of the following drugs are you aware for management of Acute Diarrhoea? (If you are knowledgeable)/Oral Rehydration Salt (ORS)",
    "Q74d. Which of the following drugs are you aware for management of Acute Diarrhoea? (If you are knowledgeable)/Zinc tablet",
    "Q74d. Which of the following drugs are you aware for management of Acute Diarrhoea? (If you are knowledgeable)/Metronidazole",
    "Q74d. Which of the following drugs are you aware for management of Acute Diarrhoea? (If you are knowledgeable)/Probiotics",
    "Q74d. Which of the following drugs are you aware for management of Acute Diarrhoea? (If you are knowledgeable)/Seven keys",
    "Q74d. Which of the following drugs are you aware for management of Acute Diarrhoea? (If you are knowledgeable)/Septrin/Clotrimazole",
    "Q74g. Which Antibiotics did you give your child?/Septrin (Cotrimoxazole)",
    "Q74g. Which Antibiotics did you give your child?/Penicillin((Ampicillin/Ampiclox/Augmentin)",
    "Q74g. Which Antibiotics did you give your child?/Metronidazole (Flagyl)",
    "Q74g. Which Antibiotics did you give your child?/Erythromycin",
    "Q74g. Which Antibiotics did you give your child?/Azithromycin",
    "Q74g. Which Antibiotics did you give your child?/I don't know",
    "Q74g. Which Antibiotics did you give your child?/Others",
    "Q75b. Which Antimalarial drug did you give your child?/Fansidar/Maloxine",
    "Q75b. Which Antimalarial drug did you give your child?/Artemisinin Combination Therapies (ACT)",
    "Q75b. Which Antimalarial drug did you give your child?/Chloroquine",
    "Q75b. Which Antimalarial drug did you give your child?/Don't know",
    "Q76c. Type of sample/Rectal Swab", "Q76c. Type of sample/Nasal Swab"
]

AUDIT_SKIP_LIST = [
    "id","state", "lga", "ward", "community", "cycle", "child_id","household_code_pull",
    "mother_code_pull","child_code","household_code","mother_code","child_name","child_dob","child_age",
    "child_weight","child_height_cm","sample_date_collected","sample_time_collected",
    "child_uuid","submission_id","concatenated_id","index","parent_index","father_name","mother_name","sample_barcode"
]

def ts(): return datetime.now(timezone.utc).strftime("%H:%M:%S")

# ─── DATA LOGIC ─────────────────────────────────────────────────────────────

def load_assets(path):
    m_df = pd.read_csv(path)
    m_df.loc[m_df['kobo_name'] == 'household_code_pull', 'db_name'] = 'household_code_pull'
    m_df.loc[m_df['kobo_name'] == 'mother_code_pull', 'db_name'] = 'mother_code_pull'
    keep_df = m_df.dropna(subset=['db_name'])
    rename_map = dict(zip(keep_df['kobo_name'], keep_df['db_name']))
    drop_list = m_df[m_df['action'].str.lower() == 'drop']['kobo_name'].tolist()
    db_order = keep_df['db_name'].tolist()
    return rename_map, drop_list, db_order

def transform_logic(df, rename_map, drop_list, db_order):
    recode_dict = {"0": "No", "0.0": "No", "1": "Yes", "1.0": "Yes"}
    for col in YES_NO_COLUMNS:
        if col in df.columns:
            # map only non-null values - astype(str) would turn blanks into the literal string "nan"
            df[col] = df[col].map(lambda v: recode_dict.get(str(v).strip(), v) if pd.notna(v) else v)
    
    df = df.drop(columns=[c for c in drop_list if c in df.columns])
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    
    if "child_code" in df.columns:
        dupes = df[df.duplicated(subset=['child_code'], keep=False)]
        if not dupes.empty: print(f"[{ts()}] WARNING: Duplicate child_codes found!")
            
    for col in db_order:
        if col not in df.columns: df[col] = None
    return df[db_order]

# ─── AUDIT REPORT LOGIC (MATCHED TO MOTHER/HH FORMAT) ───────────────────────

def generate_audit_report(df, output_path):
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    story = [Paragraph("SARMAAN II - Child Data Audit", styles["Title"]), Spacer(1, 12)]
    
    # 1. Critical Duplicate Check Section
    if "child_code" in df.columns:
        dupes = df[df.duplicated(subset=['child_code'], keep=False)]
        if not dupes.empty:
            warning_style = ParagraphStyle('Warning', parent=styles['Normal'], textColor=colors.red, fontName='Helvetica-Bold')
            story.append(Paragraph("CRITICAL: Duplicate Child Codes Found", styles["Heading2"]))
            dupe_list = ", ".join(dupes['child_code'].unique().astype(str))
            story.append(Paragraph(f"Duplicates: {dupe_list}", warning_style))
            story.append(Spacer(1, 20))

    # 2. Variable Frequencies
    report_columns = [c for c in df.columns if c not in AUDIT_SKIP_LIST]
    for col in report_columns:
        clean = df[col].dropna().loc[df[col].astype(str).str.strip() != ""]
        if clean.empty: continue
        
        freq = clean.value_counts().reset_index()
        freq.columns = ["Value", "Counts"]
        
        data = [["Value", "Counts"]] + [[str(r[0]), str(int(r[1]))] for r in freq.head(50).values]
        t = Table(data, colWidths=[350, 100], repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor("#2F5496")), # Dark Blue
            ('TEXTCOLOR',(0,0),(-1,0),colors.white),
            ('GRID',(0,0),(-1,-1),0.5,colors.grey),
            ('FONTSIZE', (0,0), (-1,-1), 8)
        ]))
        story.append(KeepTogether([Paragraph(f"{col}", styles["Heading3"]), t]))
        story.append(Spacer(1, 15))
        
    doc.build(story)
    print(f"[{ts()}] AUDIT PDF SAVED: {output_path}")

def download_kobo_export():
    headers = {"Authorization": f"Token {KOBO_TOKEN}"} if KOBO_TOKEN else {}
    resp = requests.get(KOBO_EXPORT_URL, headers=headers, timeout=300)
    if resp.status_code != 200:
        sys.exit(f"ERROR: Kobo download failed with status {resp.status_code} - check KOBO_TOKEN")
    return resp

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    print(f"[{ts()}] Starting Phase 1: Child Extraction...")
    rename_map, drop_list, db_order = load_assets(MAPPING_FILE)
    
    resp = download_kobo_export()
    content = io.BytesIO(resp.content)
    
    df_child = pd.read_excel(content, sheet_name=KOBO_SHEET_CHILD, dtype=str, engine='openpyxl')
    df_mother = pd.read_excel(content, sheet_name=KOBO_SHEET_MOTHER, dtype=str, engine='openpyxl')
    df_hh = pd.read_excel(content, sheet_name=KOBO_SHEET_HH, dtype=str, engine='openpyxl')

    # 1. Prepare Anchors
    df_mother['mother_anchor'] = df_mother['_submission__uuid'].astype(str) + "_" + df_mother['_index'].astype(str)
    df_child['child_anchor'] = df_child['_submission__uuid'].astype(str) + "_" + df_child['_parent_index'].astype(str)
    df_child['concatenated_id'] = df_child['child_anchor']

    # 2. Cleanup existing columns
    cols_to_clear = ['household_code', 'mother_code']
    df_child = df_child.drop(columns=[c for c in cols_to_clear if c in df_child.columns])

    # 3. Merge Mother ID
    mother_subset = df_mother[['mother_anchor', 'Mother ID']].copy().rename(columns={'Mother ID': 'mother_code'})
    df_child = df_child.merge(mother_subset, left_on='child_anchor', right_on='mother_anchor', how='left')
    df_child["mother_code_pull"] = df_child["mother_code"]

    # 4. Merge Household Code & Geo
    hh_subset = df_hh[["_uuid", "unique_code"] + list(GEO_MAPPING.keys())].copy()
    hh_rename = {**GEO_MAPPING, "unique_code": "household_code", "_uuid": "hh_link"}
    hh_subset = hh_subset.rename(columns=hh_rename)
    df_child = df_child.merge(hh_subset, left_on="_submission__uuid", right_on="hh_link", how="left")
    df_child["household_code_pull"] = df_child["household_code"]

    # 5. Transform & Save
    clean_df = transform_logic(df_child, rename_map, drop_list, db_order)
    clean_df = clean_df.loc[:, ~clean_df.columns.duplicated()].copy()
    
    os.makedirs(os.path.dirname(STAGING_EXCEL), exist_ok=True)
    clean_df.to_excel(STAGING_EXCEL, index=False)
    print(f"[{ts()}] STAGING FILE SAVED: {STAGING_EXCEL}")

    # 6. Audit Phase
    generate_audit_report(clean_df, AUDIT_PDF)

if __name__ == "__main__":
    main()