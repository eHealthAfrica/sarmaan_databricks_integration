"""
architecture.py — Architecture review decisions for the Mortality Databricks layers.

The same rules as coverage/architecture.py and amr/architecture.py, applied to
Mortality's three tables (household -> female -> pregnancy). Used by
docs/generate_erd.py now, and by the Mortality Databricks pipeline when it is
built, so the two cannot drift apart.

  - Kobo rootUuid is the key in every layer (pending the key spike).
    Women and pregnancies add their code, which the form builds:
      household  rootUuid
      female     rootUuid + mother_code     (form field mother_id, e.g. B-11_14_4_9_014_01)
      pregnancy  rootUuid + pregnancy_code  (form field preg_id, e.g. B-11_14_4_9_014_01_01)
    A pregnancy points at its woman on rootUuid + mother_code (form field motherid).
  - Bronze carries lineage metadata; _run_id is carried into silver and gold.
  - Identifier columns (names, phones, GPS, the interview audio) live in the
    restricted schema, keyed 1:1 to the gold tables, not in gold.
  - Phone numbers are STRING, never BIGINT.
  - Gold holds approved submissions only (Kobo validation status).
"""

import re

TABLES = {                      # sheet -> table name in every layer
    "household": "mortality_household",
    "female": "mortality_female",
    "pregnancy": "mortality_pregnancy",
}
PARENT = {"household": None, "female": "household", "pregnancy": "female"}


# ── Bronze: the Kobo export with XML headers ─────────────────────────────────
# Names are written as Kobo exports them, lowercased, with any other character
# -> "_" (meta/rootUuid -> meta_rootuuid), as in AMR and Coverage bronze.
def bronze_name(kobo_column: str) -> str:
    return re.sub(r"[^0-9a-z_]", "_", kobo_column.lower())


BRONZE_KEYS = {
    "household": (["meta_rootuuid"], []),
    "female": (["_submission_meta_rootuuid", "mother_id"], ["_submission_meta_rootuuid"]),
    "pregnancy": (["_submission_meta_rootuuid", "preg_id"], ["_submission_meta_rootuuid", "motherid"]),
}
# The parent columns each bronze foreign key points at
BRONZE_PARENT_KEYS = {
    "female": ["meta_rootuuid"],
    "pregnancy": ["_submission_meta_rootuuid", "mother_id"],
}

# ── Silver / gold / restricted: the Mortality mapping's DB names ─────────────
ROOT_UUID = "root_uuid"
KEYS = {
    "household": ([ROOT_UUID], []),
    "female": ([ROOT_UUID, "mother_code"], [ROOT_UUID]),
    "pregnancy": ([ROOT_UUID, "pregnancy_code"], [ROOT_UUID, "mother_code"]),
}
PARENT_KEYS = {
    "female": [ROOT_UUID],
    "pregnancy": [ROOT_UUID, "mother_code"],
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
# Names, phone numbers, GPS and the interview audio recording (a voice
# identifies a person). own_mobile_phone / smart_mobile_phone are yes/no
# answers and stay in gold; enum_id is a staff code, not a person's name.
IDENTIFIERS = {
    "household": [
        "enumerator_name", "enumerator_phone_number", "household_consent_name", "witness_name",
        "household_name", "related_to_head_household_name", "respondent_phone_number",
        "latitude", "longitude", "audio", "audio_url",
    ],
    "female": ["female_name"],
    "pregnancy": ["child_alive_name"],
}
PHONE_COLUMNS = {"enumerator_phone_number", "respondent_phone_number"}


def restricted_table(sheet: str) -> str:
    return f"{TABLES[sheet]}_identifiers"


# Shown instead of the value of an identifier column in mortality_validation_issues
MASK = "***"
