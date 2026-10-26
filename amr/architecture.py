"""
architecture.py — Architecture review decisions for the AMR Databricks layers.

The same rules as coverage/architecture.py, applied to AMR's three tables
(household -> mother -> child). Used by docs/generate_erd.py now, and by the
AMR Databricks loader when it is built, so the two cannot drift apart.

  - Kobo rootUuid is the key in every layer (pending the key spike).
    Mothers and children add their code, which the form makes unique:
      household  rootUuid
      mother     rootUuid + mother_code       (form field unique_code1, "Mother ID")
      child      rootUuid + child_code        (form field child_id)
    A child points at its mother on rootUuid + mother_code (form field motherid).
  - Bronze carries lineage metadata; _run_id is carried into silver and gold.
  - Identifier columns (names, phones, GPS, signatures) live in the restricted
    schema, keyed 1:1 to the gold tables, not in gold.
  - Phone numbers are STRING, never BIGINT.
  - Gold holds approved submissions only (Kobo validation status).
"""

TABLES = {                      # sheet -> table name in every layer
    "household": "amr_household",
    "mother": "amr_mother",
    "child": "amr_child",
}
PARENT = {"household": None, "mother": "household", "child": "mother"}

# ── Bronze: the Kobo export with XML headers ─────────────────────────────────
# Names are written as Kobo exports them, lowercased, with "/" "-" "." -> "_"
# (meta/rootUuid -> meta_rootuuid), as in Coverage bronze.
def bronze_name(kobo_column: str) -> str:
    out = kobo_column.lower()
    for ch in "/-.":
        out = out.replace(ch, "_")
    return out


BRONZE_KEYS = {
    "household": (["meta_rootuuid"], []),
    "mother": (["_submission_meta_rootuuid", "unique_code1"], ["_submission_meta_rootuuid"]),
    "child": (["_submission_meta_rootuuid", "child_id"], ["_submission_meta_rootuuid", "motherid"]),
}
# The parent columns each bronze foreign key points at
BRONZE_PARENT_KEYS = {
    "mother": ["meta_rootuuid"],
    "child": ["_submission_meta_rootuuid", "unique_code1"],
}

# ── Silver / gold / restricted: the AMR mapping's DB names ───────────────────
ROOT_UUID = "root_uuid"
KEYS = {
    "household": ([ROOT_UUID], []),
    "mother": ([ROOT_UUID, "mother_code"], [ROOT_UUID]),
    "child": ([ROOT_UUID, "child_code"], [ROOT_UUID, "mother_code"]),
}
PARENT_KEYS = {
    "mother": [ROOT_UUID],
    "child": [ROOT_UUID, "mother_code"],
}

# ── Lineage metadata ──────────────────────────────────────────────────────────
BRONZE_METADATA = [
    ("_ingested_at", "TIMESTAMP"),
    ("_run_id", "STRING"),
    ("_source_system", "STRING"),
    ("_source_asset", "STRING"),
    ("_pipeline_version", "STRING"),
]
RUN_ID = "_run_id"

# ── Identifiers (gold -> restricted) ─────────────────────────────────────────
# Names, phone numbers, GPS and signature images. own_mobile_phone /
# smart_mobile_phone / have_phone_number are yes/no answers and stay in gold;
# the sample manifest photo and sample barcode identify specimens, not people.
IDENTIFIERS = {
    "household": [
        "enumerator_name", "enumerator_phone_number", "witness_name",
        "household_consent_name", "household_name", "related_to_head_household_name",
        "phone_number", "latitude", "longitude",
        "person_completed_household_questionnaire_signature_url",
    ],
    "mother": ["mother_name", "father_name", "mother_signature_url"],
    "child": ["child_name", "father_name", "mother_name"],
}
PHONE_COLUMNS = {"enumerator_phone_number", "phone_number"}


def restricted_table(sheet: str) -> str:
    return f"{TABLES[sheet]}_identifiers"
