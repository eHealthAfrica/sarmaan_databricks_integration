"""
recodes.py — The Mortality value transforms, copied from
mortality/stager_auditor_mortality.py so that silver and gold hold the same
values as the Postgres tables (needed for the parity check). Keep the two in
step: a change to a recode in one belongs in the other, until the Postgres
scripts are retired.

Each map row (map/mortality/*_map.csv) names its transform:
  none, int_cast, strip_leading_zero, binary_yesno, yesno_titlecase,
  simple_capitalize, date_truncate, datetime_full_utc, datetime_short_tz,
  submission_time_utc, underscore_to_space, hh_category_range, int_cast_dk99,
  label_recode:<name>
Timestamps keep the time Kobo recorded ('YYYY-MM-DD HH:MM:SS'): see
datetime_full_utc.
"""

import re

import pandas as pd

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
    # household_status: only code '1' observed so far - add more codes here as they appear
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


def _blank(v) -> bool:
    return v is None or str(v).strip() == "" or str(v).strip().lower() == "nan"


def int_cast(series):
    """float-string -> int-string, e.g. '39.0' -> '39', '019' -> '19'. Blank stays blank."""
    def f(v):
        if _blank(v):
            return None
        v = str(v).strip()
        try:
            return str(int(float(v)))
        except (ValueError, TypeError):
            return v
    return series.map(f)


def binary_yesno(series):
    return series.map(lambda v: None if _blank(v) else BINARY_YESNO.get(str(v).strip(), str(v).strip()))


def yesno_titlecase(series):
    return series.map(lambda v: None if _blank(v) else YESNO_TITLECASE.get(str(v).strip().lower(), str(v).strip()))


def simple_capitalize(series):
    """First letter uppercase, rest unchanged ('potiskum' -> 'Potiskum')."""
    def f(v):
        if _blank(v):
            return None
        v = str(v).strip()
        return v[0].upper() + v[1:]
    return series.map(f)


def label_recode(series, recode_name):
    mapping = LABEL_RECODES[recode_name]
    def f(v):
        if _blank(v):
            return None
        v = str(v).strip()
        return mapping.get(v.lower(), mapping.get(v, v))
    return series.map(f)


def underscore_to_space(series):
    return series.map(lambda v: None if _blank(v) else str(v).strip().replace("_", " "))


def date_truncate(series):
    out = pd.to_datetime(series, format="mixed", errors="coerce").dt.strftime("%Y-%m-%d")
    return out.where(out.notna(), None)


_WALL_CLOCK = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})")


def datetime_full_utc(series):
    """Kobo timestamp '2025-11-29T10:26:53.000+01:00' -> '2025-11-29 10:26:53'.

    Despite its name, the Postgres stager keeps the local time Kobo recorded
    and only appends '+00'. The same local time is kept here, without the
    misleading '+00', so the values match Postgres digit for digit and load
    as TIMESTAMP_NTZ like Coverage and AMR."""
    def f(v):
        if _blank(v):
            return None
        m = _WALL_CLOCK.match(str(v).strip())
        return f"{m.group(1)} {m.group(2)}" if m else str(v).strip()
    return series.map(f)


def datetime_short_tz(series):
    """Kobo time of day '10:57:00.000+01:00' -> '10:57:00+01'."""
    def f(v):
        if _blank(v):
            return None
        v = str(v).strip()
        dt = pd.to_datetime(v, format="mixed", errors="coerce")
        if pd.isna(dt):
            return v
        offset = dt.strftime("%z")
        return dt.strftime("%H:%M:%S") + (offset[:3] if offset else "")
    return series.map(f)


def submission_time_utc(series):
    """Kobo _submission_time (already UTC, no offset) -> 'YYYY-MM-DD HH:MM:SS'."""
    return datetime_full_utc(series)


def hh_category_range(series):
    """'1100' -> '001 - 100', '101200' -> '101 - 200' (the end is the last 3 digits)."""
    def f(v):
        if _blank(v):
            return None
        v = str(v).strip()
        end = v[-3:]
        try:
            start = int(end) - 99
        except ValueError:
            return v
        return f"{start:03d} - {end}"
    return series.map(f)


def int_cast_dk99(series):
    """int_cast, but code 99 means 'do not know' rather than a day or value."""
    return int_cast(series).map(lambda v: "Don't know" if v == "99" else v)


def passthrough(series):
    return series.map(lambda v: None if _blank(v) else str(v).strip())


TRANSFORMS = {
    "none": passthrough,
    "int_cast": int_cast,
    "strip_leading_zero": int_cast,
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


def apply(series, transform: str):
    transform = (transform or "none").strip()
    if transform.startswith("label_recode:"):
        return label_recode(series, transform.split(":", 1)[1])
    return TRANSFORMS.get(transform, passthrough)(series)


def coalesce(df, cols):
    """First non-blank value across cols, left to right."""
    out = pd.Series([None] * len(df), index=df.index, dtype=object)
    for c in cols:
        if c in df.columns:
            vals = df[c].map(lambda v: None if _blank(v) else str(v).strip())
            out = out.where(out.notna(), vals)
    return out
