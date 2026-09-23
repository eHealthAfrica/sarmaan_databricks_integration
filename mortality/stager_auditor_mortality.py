""" Stager & Auditor - Mortality (Household / Female / Pregnancy History) """

# Dependencies:
import sys, os
import pandas as pd
import openpyxl
from datetime import datetime, timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

# ─── CONFIGURATION ──────────────────────────────────────────────────────────
# Set MORTALITY_DIR in .env to point at your data folder, or pass the input file as a CLI arg:
#   python stager_auditor_mortality.py "path\to\kobo_export.xlsx"
MORTALITY_DIR = os.getenv("MORTALITY_DIR", r"C:\Users\victoria.akinyemi\Desktop\Projects\Mortality\database")
DEFAULT_INPUT_FILE = os.path.join(MORTALITY_DIR, "kobo_exports", "mortality_export.xlsx")

MAPPING_DIR = os.path.join(MORTALITY_DIR, "mapping")
HOUSEHOLD_MAP_FILE = os.path.join(MAPPING_DIR, "household_map.csv")
FEMALE_MAP_FILE = os.path.join(MAPPING_DIR, "female_map.csv")
PREGNANCY_MAP_FILE = os.path.join(MAPPING_DIR, "pregnancy_map.csv")

OUTPUT_DIR = os.path.join(MORTALITY_DIR, "pipeline_output", "mortality")
STAGING_EXCEL = os.path.join(OUTPUT_DIR, "STAGING_mortality_data.xlsx")
AUDIT_PDF = os.path.join(OUTPUT_DIR, "mortality_audit_report.pdf")

# Sheet names inside the kobo export. The main/household sheet's name is the
# form title (Excel truncates to 31 chars) so we just take the first sheet.
FEMALE_SHEET = "female"
PREGNANCY_SHEET = "pregnancy_history"

# The kobo 'states' field exports blank for this pilot cluster (it's a single-state pilot).
# Used as a fallback only when the raw 'states' value is empty.
DEFAULT_STATE = "Yobe"

# Fields skipped in the per-column frequency audit (ids, free text, gps, etc.)
AUDIT_SKIP_LIST = [
    "household_uuid", "female_uuid", "pregnancy_uuid", "index", "parent_index",
    "submission_id", "concatenated_id", "household_code", "mother_code",
    "pregnancy_code", "female_name", "child_alive_name", "household_consent_name",
    "witness_name", "household_name", "related_to_head_household_name",
    "respondent_phone_number", "enumerator_phone_number", "latitude", "longitude",
    "audio", "audio_url", "start_time", "end_time", "start_timme", "end_timme",
    "date_of_consent", "enumerator_name",
]

# ─── VALUE RECODES (kobo raw code -> db label) ──────────────────────────────
BINARY_YESNO = {"1": "Yes", "1.0": "Yes", "0": "No", "0.0": "No"}
YESNO_TITLECASE = {"yes": "Yes", "no": "No"}

LABEL_RECODES = {
    "water_source": {
        "covered_well": "Covered well", "public_tap": "Public tap",
        "uncovered_well": "Uncovered well", "borehole": "Borehole",
        "piped_into_dwelling": "Piped into dwelling",
        "mairuwa_garuwa": "Cart with small tanks (Mairuwa/Garuwa)",
        "tanker_truck": "Tanker Truck",
        "surface_water": "Surface water (River/Dam/Lake/Pond/Stream/Canal/Irrigation channel)",
        "others": "Others", "rainwater": "Rainwater", "spring": "Spring",
    },
    "toilet_facility": {
        "pit_latrine": "Pit latrine", "water_closet": "Water closet",
        "vip_latrine": "VIP latrine", "no_toilet": "No toilet (bush/field)",
        "bucket_pan": "Bucket/Pan", "others": "Other",
    },
    "rubbish": {
        "dumped_in_open_space": "Dumped in open space", "burnt": "Burnt",
        "dumped_in_public_bin": "Dumped in public bin", "collected": "Collected",
        "buried": "Buried", "others": "Others",
    },
    "washing_hand": {
        "in_yard": "In yard/plot",
        "no_handwashing_place": "No handwashing place in dwelling/yard/plot",
        "bucket_jug": "Bucket/Jug/Kettle", "no_permission_to_see": "No permission to see",
        "in_dwelling": "In dwelling",
    },
    "washing_place": {
        "detergent": "Detergent (Powder/Liquid/Paste)", "ash_mud": "Ash/Mud/Sand",
        "soap": "Bar or Liquid soap",
    },
    "school_level_cat": {"primary": "Primary", "secondary": "Secondary", "higher_e": "Higher"},
    "future_pregnancies": {"later": "Later", "no_more": "No more/none"},
    "pregnancy_type": {"1": "Single", "1.0": "Single", "2": "Twins", "2.0": "Twins",
                        "3": "Triplet", "3.0": "Triplet", "4": "Quadruplets", "4.0": "Quadruplets"},
    "pregnancy_outcome": {"alive": "Born Alive", "dead": "Born dead", "miscarriage": "Miscarriage and Abortion"},
    "month_name": {
        "1": "January", "1.0": "January", "2": "February", "2.0": "February",
        "3": "March", "3.0": "March", "4": "April", "4.0": "April",
        "5": "May", "5.0": "May", "6": "June", "6.0": "June",
        "7": "July", "7.0": "July", "8": "August", "8.0": "August",
        "9": "September", "9.0": "September", "10": "October", "10.0": "October",
        "11": "November", "11.0": "November", "12": "December", "12.0": "December",
    },
    # household_status: only code '1' observed in the sample - add more codes here as they appear
    "household_status": {"1": "Respondent present"},
    "floor_material": {"earth": "Earth/Sand", "others": "Others"},
    "cooking_stove": {"three_stone_stove": "Three stone stove", "others": "Others", "open_fire": "Open Fire"},
    "toilet_facility_location": {
        "in_own_yard_plot": "In own yard/plot", "in_own_dwelling": "In own dwelling",
        "elsewhere": "Elsewhere",
    },
    "relationship": {
        "spouse": "Spouse", "son_or_daughter": "Son or Daughter", "parent": "Parent",
        "sibling": "Sibling", "other_relative": "Other Relative", "grandchild": "Grandchild",
        "son_in_law_or_daughter_in_law": "Son-in-law or Daughter-in-law",
        "parent_in_law": "Parent-in-law",
    },
    "school_level": {"higher_e": "Higher", "secondary": "Secondary", "primary": "Primary"},
    "child_vaccinated": {"yes": "Yes", "no": "No", "don't_know": "Dont know", "dont_know": "Dont know"},
    "child_age_category": {
        "1259": "12 - 59 months", "more_5": "Greater than 5 years",
        "111": "1 - 11 months", "less_1": "0 - 28 days",
    },
    "child_age_alive_later_died_category": {
        "less_than_1": "Less than 1 month", "greater_than_1": "Greater than 1 year",
        "equal_1": "12 months or 1 year",
    },
}

# ─── EXACT DB COLUMN ORDER (must match target Postgres tables) ─────────────
HOUSEHOLD_DB_COLUMNS = [
    "start_time","end_time","enumerator_name","enumerator_phone_number","enum_id","consent",
    "household_head_consent","household_consent_name","date_of_consent","witness","witness_name",
    "start_timme","state","lga","ward","community","settlement_cluster","women_15_49","latitude",
    "longitude","household_no_category","household_number","household_code","cycle","settlement_type",
    "language_communication","other_language_communication","household_status","head_household",
    "household_name","gender_head_household","household_age","related_to_head_household_name",
    "related_to_head_household_live","related_to_head_household_stay","related_to_head_household_age",
    "related_to_head_household_gender","related_to_head_household","related_to_head_household_others",
    "education","education_type_quranic","education_type_western","school_level","school_level_primary",
    "school_level_secondary","own_mobile_phone","smart_mobile_phone","respondent_phone_number",
    "television","electric_iron","fan","refrigerator","electricity","generator","bank_account","watch",
    "floor_material","floor_material_others","cooking_stove","cooking_stove_others","drinking_water_source",
    "drinking_water_source_others","cooking_water_source","cooking_water_source_others","no_sleeping_rooms",
    "toilet_facility_type","toilet_facility_type_others","shared_toilet_facility","toilet_facility_location",
    "waste_disposal","waste_disposal_others","household_handwash_use","household_handwash_use_others",
    "household_handwash_observed","total_no_persons_household","current_women_10_55","end_timme","audio",
    "audio_url","household_uuid","index","submission_id","concatenated_id",
]

FEMALE_DB_COLUMNS = [
    "state","lga","ward","community","household_code","female_id","mother_code","female_name",
    "birth_year","birth_month","female_age","female_dob","education","school_level_quranic",
    "school_level_western","school_level_cat","school_level_attained_primary_secondary",
    "school_level_attained_higher","birthing_status","children_living_together","sons_living_together",
    "daughters_living_together","children_living_elsewhere","sons_living_elsewhere",
    "daughters_living_elsewhere","children_alive_later_died","boys_alive_later_died",
    "girls_alive_later_died","sum_children_alive","sum_children_dead","sum_alive_dead_children",
    "confirm_birthing_no","miscarriage_abortion_pregnancy","miscarriage_abortion_count",
    "miscarriage_count","total_pregnancies","pregnancy_id","agg_child_still_alive",
    "agg_child_alive_death","agg_dead_miscarrage","pregnancy_status","pregnancy_report",
    "pregnancy_length_weeks","pregnancy_length_months","pregnancy_decision","future_pregnancies",
    "female_uuid","parent_index","index","submission_id","concatenated_id",
]

PREGNANCY_DB_COLUMNS = [
    "state","lga","ward","community","household_code","mother_code","pregnancy_id","pregnancy_code",
    "pregnancy_form","birth_form","birth_status","child_alive_name","child_alive_gender",
    "child_alive_later_died_gender","child_age_category","child_month_less_1_month",
    "child_day_less_1_month","child_dob_less_1_month","child_year_alive_later_died",
    "child_month_alive_later_died","child_day_alive_later_died","child_dob_alive_later_died",
    "child_year_1_11_month","child_month_1_11_month","child_day_1_11_month","child_dob_1_11_month",
    "child_year_12_59_month","child_month_12_59_month","child_day_12_59_month","child_dob_12_59_month",
    "child_year_greater_5_years","child_month_greater_5_years","child_day_greater_5_years",
    "year_pregnancy_ended","month_pregnancy_ended","day_pregnancy_ended","pregnancy_report",
    "miscarriage_pregnancy_report","pregnancy_report_length_weeks","pregnancy_report_length_months",
    "miscarriage_pregnancy_length_weeks","miscarriage_pregnancy_length_months","child_age_less_1_month",
    "child_age_less_1_11_month","child_age_less_12_59_month","child_age_greater_5_years",
    "child_still_alive","child_age_1_11_last_birthday","child_age_1_to_more_than_5_years_last_birthday",
    "child_age_alive_later_died_category","child_age_months_alive_later_died",
    "child_age_alive_later_died_less_1_month","child_age_days_alive_later_died","first_birthday",
    "child_age_alive_later_died_less_1_year","child_age_alive_later_died_1_less_month",
    "child_age_alive_later_died_greater_1_year","child_age_alive_later_died_less_2_year",
    "child_living_together","child_vaccinated","child_ever_vaccinated","child_alive_still",
    "child_alive_death","birth_form_dead","birth_form_miscarriage","index","parent_index",
    "pregnancy_uuid","submission_id","concatenated_id",
]

def ts(): return datetime.now(timezone.utc).strftime("%H:%M:%S")

# ─── TRANSFORM HELPERS ──────────────────────────────────────────────────────

def int_cast(series):
    """float-string -> int-string, e.g. '39.0' -> '39', '019' -> '19'. Blank stays blank."""
    def f(v):
        v = "" if v is None else str(v).strip()
        if v == "" or v.lower() == "nan":
            return None
        try:
            return str(int(float(v)))
        except (ValueError, TypeError):
            return v
    return series.map(f)

def strip_leading_zero(series):
    return int_cast(series)

def binary_yesno(series):
    def f(v):
        v = "" if v is None else str(v).strip()
        return BINARY_YESNO.get(v, None if v == "" or v.lower() == "nan" else v)
    return series.map(f)

def yesno_titlecase(series):
    def f(v):
        v = "" if v is None else str(v).strip()
        if v == "" or v.lower() == "nan":
            return None
        return YESNO_TITLECASE.get(v.lower(), v)
    return series.map(f)

def simple_capitalize(series):
    """First letter uppercase, rest unchanged - for already-lowercase single/plain words
    ('potiskum' -> 'Potiskum', 'hausa' -> 'Hausa'). Does not fix free-text typos."""
    def f(v):
        v = "" if v is None else str(v).strip()
        if v == "" or v.lower() == "nan":
            return None
        return v[0].upper() + v[1:] if v else v
    return series.map(f)

def label_recode(series, recode_name):
    mapping = LABEL_RECODES[recode_name]
    def f(v):
        v = "" if v is None else str(v).strip()
        if v == "" or v.lower() == "nan":
            return None
        return mapping.get(v.lower(), mapping.get(v, v))
    return series.map(f)

def underscore_to_space(series):
    def f(v):
        v = "" if v is None else str(v).strip()
        if v == "" or v.lower() == "nan":
            return None
        return v.replace("_", " ")
    return series.map(f)

def date_truncate(series):
    return pd.to_datetime(series, format="mixed", errors="coerce").dt.strftime("%Y-%m-%d")

def datetime_full_utc(series):
    """Full kobo timestamp -> 'YYYY-MM-DD HH:MM:SS+00', rounded to the nearest second."""
    dt = pd.to_datetime(series, format="mixed", errors="coerce")
    return dt.dt.round("s").dt.strftime("%Y-%m-%d %H:%M:%S+00")

def datetime_short_tz(series):
    """Kobo short time-of-day '10:57:00.000+01:00' -> db format '10:57:00+01'."""
    def f(v):
        v = "" if v is None else str(v).strip()
        if v == "" or v.lower() == "nan":
            return None
        dt = pd.to_datetime(v, format="mixed", errors="coerce")
        if pd.isna(dt):
            return v
        offset = dt.strftime("%z")  # e.g. +0100
        offset_short = offset[:3] if offset else ""
        return dt.strftime("%H:%M:%S") + offset_short
    return series.map(f)

def submission_time_utc(series):
    """Kobo _submission_time '2025-11-29 10:26:53.000' -> db 'end_timme' format with '+00' suffix."""
    dt = pd.to_datetime(series, format="mixed", errors="coerce")
    return dt.dt.round("s").dt.strftime("%Y-%m-%d %H:%M:%S+00")

def hh_category_range(series):
    """'1100' -> '001 - 100', '101200' -> '101 - 200' (end is always last 3 digits)."""
    def f(v):
        v = "" if v is None else str(v).strip()
        if v == "" or v.lower() == "nan":
            return None
        end = v[-3:]
        try:
            start = int(end) - 99
        except ValueError:
            return v
        return f"{start:03d} - {end}"
    return series.map(f)

def int_cast_dk99(series):
    """int_cast, but code 99 means 'do not know' rather than a literal day/value."""
    casted = int_cast(series)
    return casted.map(lambda v: "Don't know" if v == "99" else v)

def passthrough(series):
    def f(v):
        v = "" if v is None else str(v).strip()
        if v.lower() == "nan":
            return None
        return v if v != "" else None
    return series.map(f)

TRANSFORM_FUNCS = {
    "none": passthrough,
    "int_cast": int_cast,
    "strip_leading_zero": strip_leading_zero,
    "binary_yesno": binary_yesno,
    "yesno_titlecase": yesno_titlecase,
    "simple_capitalize": simple_capitalize,
    "date_truncate": date_truncate,
    "datetime_full_utc": datetime_full_utc,
    "datetime_short_tz": datetime_short_tz,
    "submission_time_utc": submission_time_utc,
    "underscore_to_space": underscore_to_space,
    "hh_category_range": hh_category_range,
    "int_cast_dk99": int_cast_dk99,
}

def apply_transform(series, transform):
    transform = (transform or "none").strip()
    if transform.startswith("label_recode:"):
        return label_recode(series, transform.split(":", 1)[1])
    fn = TRANSFORM_FUNCS.get(transform, passthrough)
    return fn(series)

def coalesce(df, cols):
    """First non-blank value across cols, left to right."""
    out = pd.Series([None] * len(df), index=df.index, dtype=object)
    for c in cols:
        if c not in df.columns:
            continue
        vals = df[c].map(lambda v: None if v is None or str(v).strip() == "" or str(v).strip().lower() == "nan" else str(v).strip())
        out = out.where(out.notna(), vals)
    return out

# ─── LOADING ─────────────────────────────────────────────────────────────────

def read_sheet(wb, sheet_name):
    ws = wb[sheet_name]
    rows = ws.iter_rows(values_only=True)
    header = list(next(rows))
    data = [list(r) for r in rows]
    return pd.DataFrame(data, columns=header)

def load_kobo_export(input_file):
    print(f"[{ts()}] Reading kobo export: {input_file}")
    wb = openpyxl.load_workbook(input_file, read_only=True, data_only=True)
    main_sheet_name = wb.sheetnames[0]
    main_df = read_sheet(wb, main_sheet_name)
    if FEMALE_SHEET not in wb.sheetnames:
        sys.exit(f"ERROR: expected sheet '{FEMALE_SHEET}' not found in workbook. Sheets present: {wb.sheetnames}")
    if PREGNANCY_SHEET not in wb.sheetnames:
        sys.exit(f"ERROR: expected sheet '{PREGNANCY_SHEET}' not found in workbook. Sheets present: {wb.sheetnames}")
    female_df = read_sheet(wb, FEMALE_SHEET)
    preg_df = read_sheet(wb, PREGNANCY_SHEET)
    print(f"[{ts()}] household rows: {len(main_df)}, female rows: {len(female_df)}, pregnancy rows: {len(preg_df)}")
    return main_df, female_df, preg_df

def load_map(path):
    return pd.read_csv(path, dtype=str).fillna("")

# ─── GENERIC MAP APPLICATION ─────────────────────────────────────────────────

def apply_mapping(source_df, map_df, table_label, warnings):
    """Applies all action in (keep, review) rows from a mapping dataframe.
    Rows with action == 'review' still get applied (best-effort) but are logged
    as warnings so a human can confirm them against the live form logic.
    Rows with an empty kobo_name/db_name or a transform starting with
    'derived'/'coalesce' are skipped here - those are computed separately."""
    out = pd.DataFrame(index=source_df.index)
    for _, row in map_df.iterrows():
        action = row["action"].strip().lower()
        if action not in ("keep", "review"):
            continue
        kobo_col = row["kobo_name"].strip()
        db_col = row["db_name"].strip()
        transform = row["transform"].strip()
        if not kobo_col or not db_col:
            continue
        if transform.startswith("derived") or transform.startswith("coalesce"):
            continue
        if kobo_col not in source_df.columns:
            warnings.append(f"[{table_label}] kobo column '{kobo_col}' (-> {db_col}) not found in export - left blank")
            out[db_col] = None
            continue
        out[db_col] = apply_transform(source_df[kobo_col], transform)
        if action == "review":
            warnings.append(f"[{table_label}] '{kobo_col}' -> '{db_col}' is UNVERIFIED (no/low sample data to confirm) - please check against form logic")
    return out

# ─── HOUSEHOLD ───────────────────────────────────────────────────────────────

def process_household(main_df, map_df, warnings):
    out = apply_mapping(main_df, map_df, "household", warnings)

    out["lga"] = simple_capitalize(coalesce(main_df, ["lgas", "lga_confirm", "lgas_k"]))
    out["ward"] = underscore_to_space(coalesce(main_df, ["ward", "wards", "ward_confirm"]))
    out["community"] = underscore_to_space(coalesce(main_df, ["community_confirm", "community_name", "check_hh"]))
    out["household_no_category"] = hh_category_range(main_df["hh_category"]) if "hh_category" in main_df.columns else None

    # 'states' is blank in every sample row for this pilot cluster - fall back to the known constant.
    # If a future export spans more than one state, replace this with a proper lookup.
    if "state" in out.columns:
        out["state"] = out["state"].where(out["state"].notna() & (out["state"].astype(str).str.strip() != ""), DEFAULT_STATE)
    else:
        out["state"] = DEFAULT_STATE

    out["household_uuid"] = passthrough(main_df["_uuid"])
    out["index"] = passthrough(main_df["_index"].astype(str))
    out["submission_id"] = passthrough(main_df["_id"].astype(str))
    out["concatenated_id"] = out["household_uuid"].astype(str) + "_" + out["index"].astype(str)

    for col in HOUSEHOLD_DB_COLUMNS:
        if col not in out.columns:
            out[col] = None
    return out[HOUSEHOLD_DB_COLUMNS]

# ─── FEMALE ──────────────────────────────────────────────────────────────────

def process_female(female_df, household_out, map_df, warnings):
    out = apply_mapping(female_df, map_df, "female", warnings)

    out["female_uuid"] = passthrough(female_df["_submission__uuid"])
    out["parent_index"] = passthrough(female_df["_parent_index"].astype(str))
    out["index"] = passthrough(female_df["_index"].astype(str))
    out["submission_id"] = passthrough(female_df["_submission__id"].astype(str))
    # FK to household: household's own concatenated_id = household_uuid + "_" + household's own
    # index (== this row's parent_index)
    out["concatenated_id"] = out["female_uuid"].astype(str) + "_" + out["parent_index"].astype(str)

    # join in location fields from the processed household table via household_code
    loc_cols = ["household_code", "state", "lga", "ward", "community"]
    hh_loc = household_out[loc_cols].drop_duplicates(subset="household_code")
    out = out.merge(hh_loc, on="household_code", how="left", suffixes=("", "_hh"))

    missing_hh = ~out["household_code"].isin(hh_loc["household_code"])
    if missing_hh.any():
        warnings.append(f"[female] {missing_hh.sum()} row(s) reference a household_code not found in the household sheet (orphan female records)")

    for col in FEMALE_DB_COLUMNS:
        if col not in out.columns:
            out[col] = None
    return out[FEMALE_DB_COLUMNS]

# ─── PREGNANCY HISTORY ───────────────────────────────────────────────────────

def process_pregnancy(preg_df, household_out, map_df, warnings):
    out = apply_mapping(preg_df, map_df, "pregnancy", warnings)

    out["pregnancy_uuid"] = passthrough(preg_df["_submission__uuid"])
    out["parent_index"] = passthrough(preg_df["_parent_index"].astype(str))
    out["index"] = passthrough(preg_df["_index"].astype(str))
    out["submission_id"] = passthrough(preg_df["_submission__id"].astype(str))
    # FK to female: female's own index-based key = pregnancy_uuid + "_" + parent_index (== mother's own _index)
    out["concatenated_id"] = out["pregnancy_uuid"].astype(str) + "_" + out["parent_index"].astype(str)

    loc_cols = ["household_code", "state", "lga", "ward", "community"]
    hh_loc = household_out[loc_cols].drop_duplicates(subset="household_code")
    out = out.merge(hh_loc, on="household_code", how="left", suffixes=("", "_hh"))

    missing_hh = ~out["household_code"].isin(hh_loc["household_code"])
    if missing_hh.any():
        warnings.append(f"[pregnancy] {missing_hh.sum()} row(s) reference a household_code not found in the household sheet (orphan pregnancy records)")

    for col in PREGNANCY_DB_COLUMNS:
        if col not in out.columns:
            out[col] = None
    return out[PREGNANCY_DB_COLUMNS]

# ─── DUPLICATE / INTEGRITY CHECKS ───────────────────────────────────────────

def check_duplicates(df, subset_col, label, warnings):
    if subset_col not in df.columns:
        return
    dupes = df[df.duplicated(subset=[subset_col], keep=False) & df[subset_col].notna()]
    if not dupes.empty:
        vals = ", ".join(sorted(set(dupes[subset_col].astype(str)))[:25])
        warnings.append(f"[{label}] {len(dupes)} row(s) share a duplicate {subset_col}: {vals}" + (" ..." if dupes[subset_col].nunique() > 25 else ""))
        print(f"[{ts()}] WARNING: {len(dupes)} duplicate {subset_col} values in {label}")
    else:
        print(f"[{ts()}] SUCCESS: all {subset_col} values unique in {label}")

# ─── AUDIT PDF ───────────────────────────────────────────────────────────────

def generate_audit_report(tables, warnings, output_path):
    """tables: list of (label, dataframe) tuples."""
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    story = [Paragraph("Mortality Pipeline - Data Audit", styles["Title"]), Spacer(1, 12)]

    story.append(Paragraph(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", styles["Normal"]))
    for label, df in tables:
        story.append(Paragraph(f"{label}: {len(df)} rows", styles["Normal"]))
    story.append(Spacer(1, 16))

    if warnings:
        warning_style = ParagraphStyle("Warning", parent=styles["Normal"], textColor=colors.red)
        story.append(Paragraph(f"CRITICAL / REVIEW ITEMS ({len(warnings)})", styles["Heading2"]))
        for w in warnings:
            story.append(Paragraph(w, warning_style))
        story.append(Spacer(1, 20))
    else:
        story.append(Paragraph("No warnings raised.", styles["Normal"]))
        story.append(Spacer(1, 20))

    for label, df in tables:
        story.append(Paragraph(f"--- {label} ---", styles["Heading1"]))
        report_columns = [c for c in df.columns if c not in AUDIT_SKIP_LIST]
        for col in report_columns:
            clean = df[col].dropna()
            clean = clean.loc[clean.astype(str).str.strip() != ""]
            if clean.empty:
                continue
            freq = clean.value_counts().reset_index()
            freq.columns = ["Value", "Counts"]
            data = [["Value", "Counts"]] + [[str(r[0]), str(int(r[1]))] for r in freq.head(30).values]
            t = Table(data, colWidths=[350, 100], repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2F5496")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]))
            story.append(KeepTogether([Paragraph(f"{col}", styles["Heading3"]), t]))
            story.append(Spacer(1, 12))

    doc.build(story)

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INPUT_FILE
    warnings = []

    print(f"[{ts()}] Starting Phase 1: Extraction, Transform & Audit...")
    main_df, female_df, preg_df = load_kobo_export(input_file)

    household_map = load_map(HOUSEHOLD_MAP_FILE)
    female_map = load_map(FEMALE_MAP_FILE)
    pregnancy_map = load_map(PREGNANCY_MAP_FILE)

    household_out = process_household(main_df, household_map, warnings)
    female_out = process_female(female_df, household_out, female_map, warnings)
    pregnancy_out = process_pregnancy(preg_df, household_out, pregnancy_map, warnings)

    check_duplicates(household_out, "household_code", "household", warnings)
    check_duplicates(household_out, "concatenated_id", "household", warnings)
    check_duplicates(pregnancy_out, "pregnancy_code", "pregnancy", warnings)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with pd.ExcelWriter(STAGING_EXCEL, engine="openpyxl") as writer:
        household_out.to_excel(writer, sheet_name="household", index=False)
        female_out.to_excel(writer, sheet_name="female", index=False)
        pregnancy_out.to_excel(writer, sheet_name="pregnancy", index=False)
    print(f"[{ts()}] STAGING FILE SAVED: {STAGING_EXCEL}")

    generate_audit_report(
        [("Household", household_out), ("Female", female_out), ("Pregnancy History", pregnancy_out)],
        warnings, AUDIT_PDF,
    )
    print(f"[{ts()}] AUDIT PDF SAVED: {AUDIT_PDF}")

    if warnings:
        print(f"[{ts()}] {len(warnings)} item(s) flagged for review - see the audit PDF for details.")

if __name__ == "__main__":
    main()
