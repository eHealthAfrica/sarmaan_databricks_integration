"""
architecture.py — Architecture review decisions for the Pharmacy Databricks layers.

The same rules as coverage/, amr/ and mortality/architecture.py, applied to
Pharmacy's single table (one row per pharmacy or drug shop; the form has no
repeats). Used by docs/generate_erd.py now, and by the Pharmacy Databricks
pipeline when it is built, so the two cannot drift apart.

  - Kobo rootUuid is the key in every layer (pending the key spike).
  - Bronze carries lineage metadata; _run_id is carried into silver and gold.
  - Identifier columns (names, phones, GPS, the signature and the shop photo,
    which shows the shop's name) live in the restricted schema, keyed 1:1 to
    the gold table, not in gold.
  - Phone numbers are STRING, never BIGINT.
  - Gold holds approved submissions only (Kobo validation status).
"""

import re

TABLES = {"pharmacy": "pharmacy"}   # sheet -> table name in every layer
PARENT = {"pharmacy": None}


# ── Bronze: the Kobo export with XML headers ─────────────────────────────────
# Names are written as Kobo exports them, lowercased, with any other character
# -> "_" (meta/rootUuid -> meta_rootuuid), as in the other streams' bronze.
def bronze_name(kobo_column: str) -> str:
    return re.sub(r"[^0-9a-z_]", "_", kobo_column.lower())


BRONZE_KEYS = {"pharmacy": (["meta_rootuuid"], [])}
BRONZE_PARENT_KEYS = {}

# ── Silver / gold / restricted: the Pharmacy mapping's DB names ──────────────
ROOT_UUID = "root_uuid"
KEYS = {"pharmacy": ([ROOT_UUID], [])}
PARENT_KEYS = {}

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
# Names, phone numbers, GPS, the pharmacist's signature and the shop photo
# (it shows the shop's name, so it identifies the pharmacist). The pharmacist's
# age, sex, religion and ethnicity are survey answers and stay in gold.
IDENTIFIERS = {
    "pharmacy": [
        "enumerator_name", "enumerator_phone_number", "pharmacist_name", "witness_name",
        "latitude", "longitude", "pharmacy_photo_url", "pharmacist_signature_url",
    ],
}
PHONE_COLUMNS = {"enumerator_phone_number"}


def restricted_table(sheet: str) -> str:
    return f"{TABLES[sheet]}_identifiers"


# Shown instead of the value of an identifier column in pharmacy_validation_issues
MASK = "***"
