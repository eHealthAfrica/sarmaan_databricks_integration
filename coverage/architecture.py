"""
architecture.py — Architecture review decisions for the Databricks layers.

Shared by step6_databricks_loader.py (what is loaded) and docs/generate_erd.py
(what the ERD shows), so the two cannot drift apart.

  - Kobo rootUuid is the key in every layer (pending the key spike). It stays
    the same when a submission is edited, unlike _uuid and _index.
  - Bronze carries lineage metadata; _run_id is carried into silver and gold.
  - Identifier columns (names, phones, GPS, card images) live in the
    restricted schema, keyed 1:1 to the gold tables, not in gold.
  - Phone numbers are STRING, never BIGINT (keeps leading zeros and +234).
  - coverage_validation_issues masks failing values of identifier columns.
"""

import re

PARENT = "coverage_household"
CHILD_TABLES = ["coverage_all_children", "coverage_net_info", "coverage_children_1_59"]

# ── Keys ──────────────────────────────────────────────────────────────────────
# rootUuid column per layer. Bronze keeps Kobo's export names.
ROOT_UUID = {
    "bronze": {PARENT: "meta_rootuuid", "*": "_submission_meta_rootuuid"},
    "silver": {"*": "root_uuid"},
    "gold": {"*": "root_uuid"},
}
# Row id inside a repeat group: child key = (rootUuid, row id)
ROW_ID = {
    "bronze": {"coverage_all_children": "child_id", "coverage_net_info": "net_id",
               "coverage_children_1_59": "child_idd"},
    "silver": {"coverage_all_children": "child_id", "coverage_net_info": "net_ID",
               "coverage_children_1_59": "child_idd"},
    "gold": {"coverage_all_children": "child_id", "coverage_net_info": "net_id",
             "coverage_children_1_59": "child_id"},
}
# The submission _uuid column per layer, used to look up the rootUuid
SUBMISSION_UUID = {
    "bronze": {PARENT: "uuid", "*": "_submission__uuid"},
    "silver": {PARENT: "uuid", "coverage_all_children": "uuid", "coverage_net_info": "uuid",
               "coverage_children_1_59": "_submission__uuid"},
    "gold": {PARENT: "household_uuid", "coverage_all_children": "childd_uuid",
             "coverage_net_info": "net_uuid", "coverage_children_1_59": "child_uuid"},
}


def root_col(layer: str, table: str) -> str:
    return ROOT_UUID[layer].get(table, ROOT_UUID[layer]["*"])


def uuid_col(layer: str, table: str) -> str:
    return SUBMISSION_UUID[layer].get(table, SUBMISSION_UUID[layer].get("*"))


def keys(layer: str, table: str) -> tuple[list[str], list[str]]:
    """(primary key, foreign key to coverage_household) for a layer table."""
    root = root_col(layer, table)
    if table == PARENT:
        return [root], []
    return [root, ROW_ID[layer][table]], [root]


# ── Lineage metadata ──────────────────────────────────────────────────────────
BRONZE_METADATA = [
    ("_ingested_at", "TIMESTAMP"),
    ("_run_id", "STRING"),
    ("_source_system", "STRING"),
    ("_source_asset", "STRING"),
    ("_pipeline_version", "STRING"),
]
RUN_ID = "_run_id"
SOURCE_SYSTEM = "kobotoolbox"

# ── Identifiers (gold -> restricted) ─────────────────────────────────────────
# land_telephone / mobile_telephone are yes/no "owns a phone" answers, so they
# stay in gold.
IDENTIFIERS = {
    "coverage_household": [
        "enumerator_name", "enumerator_phone_number", "household_name",
        "related_to_head_household_name", "hh_phoneno", "latitude", "longitude",
    ],
    "coverage_all_children": ["child_name"],
    "coverage_children_1_59": ["child_name", "azm_card_image", "azm_card_url"],
}
PHONE_COLUMNS = {"enumerator_phone_number", "hh_phoneno"}


def restricted_table(gold_table: str) -> str:
    return f"{gold_table}_identifiers"


# Validation issues use the step 3 / step 4 column names, which differ from
# gold, so masking matches by name. It errs on the side of masking.
_IDENTIFIER_NAME = re.compile(
    r"name|phone|gps|geopoint|latitude|longitude|altitude|precision|card_image|image",
    re.IGNORECASE,
)


def is_identifier_column(column: str) -> bool:
    return bool(column) and bool(_IDENTIFIER_NAME.search(str(column)))


MASK = "***"
