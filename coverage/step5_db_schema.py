"""
step5_db_schema.py — Build DB-ready output from Step 2 output.

Input: Step 2 output sheets (Step 2 db_column_name = Step 5 column_label)

Approval filter (applied BEFORE all other transforms):
  Only approved submissions are kept.  Step 2 renames the raw Kobo
  validation-status columns as follows:
    Household Code : _validation_status           -> validationstatus
    Child_Info     : _submission__validation_status -> validation_status
    Net_repeat     : _submission__validation_status -> validationstatus
    Child_Infoo    : _submission__validation_status -> validationstatus
  Approved value (Kobo): "validation_status_approved"

Missing columns situation after Step 2:
  - Child_Info, Net_repeat, Child_Infoo are missing:
      q1_States, q2_LGAs, q3_Wards, q4_Community, q6_HH_number, unique_code
    These exist on Household Code and are joined in via UUID
  - Child_Info is also missing _submission__uuid (Step2 renamed it to 'uuid')
    We add it back as an alias before mapping
  - concatenated_id, cycle, _index are computed and added before mapping

Flow:
  0. Filter to approved submissions only
  1. Join admin columns from Household Code into child sheets via UUID
  2. Add _submission__uuid alias on Child_Info (Step2 renamed it to 'uuid')
  3. Add concatenated_id (using Step2 column names)
  4. Add cycle to Household Code only (using Step2 'unique_code' column)
  5. Standardization (0->no, 1->yes)
  6. Apply Step5 mapping — strict filter + rename in mapping file order

UUID columns in Step2 output:
  Household Code : uuid  (was _uuid)
  Child_Info     : uuid  (was _submission__uuid)
  Net_repeat     : uuid  (was _submission__uuid)
  Child_Infoo    : _submission__uuid  (unchanged in step2)

concatenated_id uses Step2 column names:
  Household Code : index + uuid  (no separator)
  Child_Info     : index + uuid  (no separator)  (index = _parent_index in step2)
  Net_repeat     : index + uuid  (no separator)  (index = _parent_index in step2)
  Child_Infoo    : _parent_index + _submission__uuid  (no separator)
"""

import logging
import re
import pandas as pd
from config import OUTPUT_DIR, STEP5_FILENAME, VALIDATION_STATUS_APPROVED

logger = logging.getLogger(__name__)

SHEET_TO_MAP_KEY = {
    "Household Code": "household_info",
    "Child_Info":     "child_info",
    "Net_repeat":     "net_repeat",
    "Child_Infoo":    "child_infoo",
}

PREFIX_TO_CYCLE = {
    "B":  "Baseline",
    "C1": "Baseline",
    "C2": "Second",
    "C3": "Third",
    "C4": "Fourth",
}

# UUID column name in Step2 output for each sheet
STEP2_UUID = {
    "Household Code": "uuid",
    "Child_Info":     "uuid",
    "Net_repeat":     "uuid",
    "Child_Infoo":    "_submission__uuid",
}

# Index column name in Step2 output for concatenated_id
STEP2_INDEX = {
    "Household Code": "index",
    "Child_Info":     "index",
    "Net_repeat":     "index",
    "Child_Infoo":    "_parent_index",
}

# Source columns for PK building in child tables (step2 column names)
PK_COLS = {
    "Child_Info":  ("child_id", "_submission__uuid"),   # child_id_childd_uuid
    "Net_repeat":  ("net_ID", "uuid"),                   # net_id_net_uuid
    "Child_Infoo": ("child_idd", "_submission__uuid"),   # child_id_child_uuid
}

# Admin columns that exist on Household Code but missing on child sheets
ADMIN_COLS = ["q1_States", "q2_LGAs", "q3_Wards", "q4_Community",
              "q6_HH_number", "unique_code"]


# ── Step 0: Filter to approved submissions only ───────────────────────────────
#
# Step 2 renames the Kobo validation-status columns:
#   Household Code : _validation_status            -> validationstatus
#   Child_Info     : _submission__validation_status -> validation_status
#   Net_repeat     : _submission__validation_status -> validationstatus
#   Child_Infoo    : _submission__validation_status -> validationstatus
#
# We check whichever column name is present (robust to future rename changes).

_STEP2_STATUS_COLS = {
    "Household Code": ["validationstatus", "_validation_status"],
    "Child_Info":     ["validation_status", "validationstatus", "_submission__validation_status"],
    "Net_repeat":     ["validationstatus", "_submission__validation_status"],
    "Child_Infoo":    ["validationstatus", "_submission__validation_status"],
}


def _filter_approved_sheets(
    sheets: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """
    Keep only rows whose validation status equals VALIDATION_STATUS_APPROVED.
    Applied per sheet using the Step-2-renamed column names.
    Child sheets are further filtered to UUIDs that remain after the
    Household Code filter, so FK integrity is preserved.
    """
    result = {}

    # 1. Filter Household Code first and collect surviving UUIDs
    hh = sheets.get("Household Code", pd.DataFrame()).copy()
    approved_uuids: set | None = None

    if not hh.empty:
        status_col = next(
            (c for c in _STEP2_STATUS_COLS.get("Household Code", []) if c in hh.columns),
            None,
        )
        if status_col:
            before = len(hh)
            hh = hh[hh[status_col] == VALIDATION_STATUS_APPROVED].copy()
            logger.info(
                f"  [Step5 filter] Household Code: {before} -> {len(hh)} rows "
                f"(kept approved via '{status_col}')"
            )
            uuid_col = STEP2_UUID.get("Household Code", "uuid")
            if uuid_col in hh.columns:
                approved_uuids = set(hh[uuid_col].astype(str).str.strip())
        else:
            logger.warning(
                "  [Step5 filter] Household Code: no validation-status column found "
                f"(tried {_STEP2_STATUS_COLS['Household Code']}) — no filter applied"
            )
        result["Household Code"] = hh
    else:
        result["Household Code"] = hh

    # 2. Filter child sheets — by their own status AND by approved household UUIDs
    for sheet_name in ["Child_Info", "Net_repeat", "Child_Infoo"]:
        df = sheets.get(sheet_name, pd.DataFrame()).copy()
        if df.empty:
            result[sheet_name] = df
            continue

        before = len(df)
        status_col = next(
            (c for c in _STEP2_STATUS_COLS.get(sheet_name, []) if c in df.columns),
            None,
        )

        if status_col:
            df = df[df[status_col] == VALIDATION_STATUS_APPROVED].copy()
            logger.info(
                f"  [Step5 filter] {sheet_name}: {before} -> {len(df)} rows "
                f"(kept approved via '{status_col}')"
            )
        else:
            logger.warning(
                f"  [Step5 filter] {sheet_name}: no validation-status column found "
                f"(tried {_STEP2_STATUS_COLS.get(sheet_name, [])}) — no status filter applied"
            )

        # Also drop rows whose parent household was not approved
        if approved_uuids is not None:
            uuid_col = STEP2_UUID.get(sheet_name, "uuid")
            if uuid_col in df.columns:
                before2 = len(df)
                df = df[df[uuid_col].astype(str).str.strip().isin(approved_uuids)].copy()
                dropped = before2 - len(df)
                if dropped:
                    logger.info(
                        f"  [Step5 filter] {sheet_name}: dropped {dropped} additional row(s) "
                        f"whose household UUID was not approved"
                    )

        result[sheet_name] = df

    return result


# ── Step 1: Join admin columns from Household Code into child sheets ──────────

def _join_admin_cols(sheets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    main = sheets.get("Household Code", pd.DataFrame())
    if main.empty:
        logger.warning("  Household Code is empty — cannot join admin cols")
        return sheets

    main_uuid = STEP2_UUID["Household Code"]  # "uuid"
    if main_uuid not in main.columns:
        logger.warning(f"  '{main_uuid}' not found on Household Code — cannot join")
        return sheets

    # Only join admin cols that actually exist on Household Code
    available_admin = [c for c in ADMIN_COLS if c in main.columns]
    if not available_admin:
        logger.warning("  No admin columns found on Household Code — skipping join")
        return sheets

    main_slim = main[[main_uuid] + available_admin].drop_duplicates(subset=main_uuid)
    result = {"Household Code": main}

    for sheet_name in ["Child_Info", "Net_repeat", "Child_Infoo"]:
        if sheet_name not in sheets:
            continue
        df = sheets[sheet_name].copy()
        child_uuid = STEP2_UUID[sheet_name]

        if child_uuid not in df.columns:
            logger.warning(
                f"  [{sheet_name}] '{child_uuid}' not found — skipping admin join"
            )
            result[sheet_name] = df
            continue

        # Only join cols that are actually missing from this sheet
        to_join = [c for c in available_admin if c not in df.columns]
        if not to_join:
            logger.info(f"  [{sheet_name}] Admin cols already present — skipping join")
            result[sheet_name] = df
            continue

        slim = main_slim[[main_uuid] + to_join]
        df = pd.merge(
            df, slim,
            left_on=child_uuid,
            right_on=main_uuid,
            how="left",
            suffixes=("", "_main"),
        )

        # Clean up
        suffix_cols = [c for c in df.columns if c.endswith("_main")]
        df = df.drop(columns=suffix_cols, errors="ignore")
        df = df.reset_index(drop=True)
        df = df.loc[:, ~df.columns.duplicated(keep="first")]

        logger.info(
            f"  [{sheet_name}] Joined {len(to_join)} admin cols: {to_join}"
        )
        result[sheet_name] = df

    return result


# ── Step 2: Restore _submission__uuid alias on Child_Info ─────────────────────

def _restore_submission_uuid(
    sheets: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """
    Child_Info step2 renames _submission__uuid -> uuid.
    Step5 map expects _submission__uuid as source. Add it back as alias.
    """
    result = dict(sheets)
    df = result.get("Child_Info")
    if df is None:
        return result

    df = df.copy()
    if "uuid" in df.columns and "_submission__uuid" not in df.columns:
        df["_submission__uuid"] = df["uuid"]
        logger.info("  [Child_Info] Restored '_submission__uuid' alias from 'uuid'")
    result["Child_Info"] = df
    return result


# ── Step 3: Add concatenated_id ───────────────────────────────────────────────

def _add_concatenated_id(
    sheets: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """
    Build FK concatenated_id = uuid + "_" + index for all sheets.
    This matches household PK so child FK → household PK.
    """
    result = {}
    for sheet_name, df in sheets.items():
        df = df.copy()
        uuid_col  = STEP2_UUID.get(sheet_name, "uuid")
        index_col = STEP2_INDEX.get(sheet_name, "index")

        missing = [c for c in [uuid_col, index_col] if c not in df.columns]
        if missing:
            logger.warning(
                f"  [{sheet_name}] concatenated_id: {missing} not found — empty"
            )

        uid = df[uuid_col].astype(str) if uuid_col in df.columns \
              else pd.Series("", index=df.index)
        idx = df[index_col].astype(str) if index_col in df.columns \
              else pd.Series("", index=df.index)

        df["concatenated_id"] = uid + "_" + idx
        logger.info(f"  [{sheet_name}] concatenated_id: {uuid_col} + '_' + {index_col}")
        result[sheet_name] = df

    return result


def _add_household_fk(
    sheets: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """
    Overwrite concatenated_id on child tables to use household index.

    _add_concatenated_id sets concatenated_id = uuid + index, but for repeat
    tables `index` is the row's own repeat index, not the household's index.
    This overwrites concatenated_id = uuid + household_index by joining
    to Household Code via uuid.
    """
    result = {}
    hh = sheets.get("Household Code", pd.DataFrame())
    hh_uuid = STEP2_UUID["Household Code"]

    # Build household lookup: uuid -> index
    hh_lookup = None
    if not hh.empty and hh_uuid in hh.columns and "index" in hh.columns:
        hh_lookup = hh[[hh_uuid, "index"]].drop_duplicates(subset=hh_uuid)
        hh_lookup = hh_lookup.set_index(hh_uuid)["index"]

    for sheet_name, df in sheets.items():
        df = df.copy()
        uuid_col = STEP2_UUID.get(sheet_name, "uuid")

        # Household Code — concatenated_id is already correct (uuid + household index)
        if sheet_name == "Household Code":
            result[sheet_name] = df
            continue

        if hh_lookup is None or uuid_col not in df.columns:
            logger.warning(
                f"  [{sheet_name}] concatenated_id FK: lookup not available or "
                f"'{uuid_col}' missing — using existing"
            )
            result[sheet_name] = df
            continue

        # Overwrite concatenated_id with household FK values
        hh_idx = df[uuid_col].map(hh_lookup)
        matched = hh_idx.notna().sum()   # count before astype(str) turns NaN into "nan"
        uid = df[uuid_col].astype(str)
        # Unmatched rows get a non-matching id ("<uuid>_") on purpose so Step 6's
        # FK check rejects them. fillna first: with pandas' string dtype,
        # astype(str) keeps NaN, and uuid + "_" + NaN would give an empty FK.
        df["concatenated_id"] = uid + "_" + hh_idx.fillna("").astype(str)
        logger.info(
            f"  [{sheet_name}] concatenated_id FK fixed: {uuid_col} + household.index "
            f"({matched}/{len(df)} matched via uuid join)"
        )
        if matched < len(df):
            logger.warning(
                f"  [{sheet_name}] {len(df) - matched} row(s) have no matching household "
                f"- Step 6 will reject them as orphans"
            )
        result[sheet_name] = df
    return result


def _add_pk_columns(
    sheets: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """
    Build PK columns for child clean tables (no separator):
      Child_Info  → child_id_childd_uuid  = child_id + _submission__uuid
      Net_repeat  → net_id_net_uuid       = net_ID + uuid
      Child_Infoo → child_id_child_uuid   = child_idd + _submission__uuid
    """
    result = {}
    for sheet_name, df in sheets.items():
        df = df.copy()
        if sheet_name in PK_COLS:
            col_a, col_b = PK_COLS[sheet_name]
            missing = [c for c in [col_a, col_b] if c not in df.columns]
            if missing:
                logger.warning(
                    f"  [{sheet_name}] Cannot build PK — missing: {missing}"
                )
            else:
                pk_col = f"{col_a}_{col_b}".replace("__uuid", "_uuid")
                # Map to the actual db column names from mapping
                if sheet_name == "Child_Info":
                    pk_col = "child_id_childd_uuid"
                elif sheet_name == "Net_repeat":
                    pk_col = "net_id_net_uuid"
                elif sheet_name == "Child_Infoo":
                    pk_col = "child_id_child_uuid"

                df[pk_col] = df[col_a].astype(str) + df[col_b].astype(str)
                logger.info(
                    f"  [{sheet_name}] Built PK '{pk_col}' = "
                    f"'{col_a}' + '{col_b}' ({len(df)} rows)"
                )
        result[sheet_name] = df

    return result


# ── Step 4: Add cycle to Household Code ──────────────────────────────────────

def _add_cycle(sheets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    result = dict(sheets)
    df = result.get("Household Code")
    if df is None:
        return result

    df = df.copy()
    col = "unique_code"
    cycle_value = ""

    if col in df.columns:
        values = [v.strip() for v in df[col].astype(str)
                  if v.strip() and v.strip().lower() != "nan"]
        if values:
            match = re.match(r"([A-Za-z]+\d*)", values[0])
            if match:
                prefix = match.group(1).upper()
                cycle_value = PREFIX_TO_CYCLE.get(prefix, prefix)
                logger.info(f"  Cycle: '{values[0]}' -> prefix '{prefix}' -> '{cycle_value}'")
    else:
        logger.warning("  'unique_code' not found on Household Code — cycle will be empty")

    df["cycle"] = cycle_value
    logger.info(f"  Added 'cycle' = '{cycle_value}' ({len(df)} rows)")
    result["Household Code"] = df
    return result


# ── Step 5: Standardization ───────────────────────────────────────────────────

def _apply_standardization(
    sheets: dict[str, pd.DataFrame],
    std_cols: dict[str, list[str]],
) -> dict[str, pd.DataFrame]:
    all_std_cols = set()
    for col_list in std_cols.values():
        all_std_cols.update(col_list)

    logger.info(f"  Standardization: {len(all_std_cols)} unique columns to check")
    found_cols = set()
    result = {}

    for sheet_name, df in sheets.items():
        df = df.copy()
        cols_in_sheet = [c for c in all_std_cols if c in df.columns]
        found_cols.update(cols_in_sheet)
        changed = 0
        for col in cols_in_sheet:
            before = df[col].astype(str).str.strip()
            df[col] = before.replace({"0": "no", "1": "yes", "0.0": "no", "1.0": "yes"})
            changed += (df[col] != before).sum()
        logger.info(
            f"  [{sheet_name}] {len(cols_in_sheet)} cols standardized, "
            f"{changed} values converted"
        )
        result[sheet_name] = df

    not_found = all_std_cols - found_cols
    if not_found:
        logger.warning(
            f"  Standardization: {len(not_found)} template columns not found: "
            f"{sorted(not_found)}"
        )
    else:
        logger.info("  Standardization: all template columns found")

    return result


# ── Step 6: Apply DB mapping ──────────────────────────────────────────────────

def _apply_db_mapping(
    df: pd.DataFrame,
    mapping: dict[str, str],
    label: str,
) -> pd.DataFrame:
    missing = [k for k in mapping if k not in df.columns]
    if missing:
        logger.warning(
            f"  [{label}] {len(missing)} mapped columns still missing "
            f"after join: {missing}"
        )
    keep = {src: dst for src, dst in mapping.items() if src in df.columns}
    df_out = df[list(keep.keys())].rename(columns=keep)
    logger.info(
        f"  [{label}] {len(df_out.columns)} DB columns produced "
        f"(from {len(df.columns)} available, in mapping order)"
    )
    return df_out


# ── Main ──────────────────────────────────────────────────────────────────────

def run_step5(
    step2_sheets: dict[str, pd.DataFrame],
    step5_maps: dict[str, dict[str, str]],
    std_cols: dict[str, list[str]],
) -> dict[str, pd.DataFrame]:
    """
    step2_sheets — { sheet_name: DataFrame } from Step 2
                   keys: 'Household Code', 'Child_Info', 'Net_repeat', 'Child_Infoo'
    step5_maps   — { map_key: { col_label: db_col } } from mappings.py
    std_cols     — { template_sheet: [col_names] } from mappings.py
    """
    logger.info("=" * 50)
    logger.info("STEP 5 — Build DB-ready output from Step 2 data")

    sheets = {k: df.copy() for k, df in step2_sheets.items()}

    # 0. Filter to approved submissions only (clean DB must not contain not-approved)
    logger.info("  Step 5.0: Filtering to approved submissions only...")
    sheets = _filter_approved_sheets(sheets)

    # 1. Join admin cols from Household Code into child sheets
    logger.info("  Step 5.1: Joining admin columns into child sheets...")
    sheets = _join_admin_cols(sheets)

    # 2. Restore _submission__uuid on Child_Info
    logger.info("  Step 5.2: Restoring column aliases...")
    sheets = _restore_submission_uuid(sheets)

    # 3. Add concatenated_id
    logger.info("  Step 5.3: Adding concatenated_id...")
    sheets = _add_concatenated_id(sheets)

    # 3b. Add PK columns for child clean tables
    logger.info("  Step 5.3b: Adding PK columns for clean tables...")
    sheets = _add_pk_columns(sheets)

    # 3c. Add household FK for child tables
    logger.info("  Step 5.3c: Adding household FK for child tables...")
    sheets = _add_household_fk(sheets)

    # 4. Add cycle to Household Code
    logger.info("  Step 5.4: Adding cycle...")
    sheets = _add_cycle(sheets)

    # 5. Standardization
    logger.info("  Step 5.5: Standardization...")
    sheets = _apply_standardization(sheets, std_cols)

    # 6. Apply DB mapping — strict filter + rename in mapping order
    logger.info("  Step 5.6: Applying DB mapping...")
    mapped_sheets = {}
    for sheet_name, df in sheets.items():
        map_key = SHEET_TO_MAP_KEY.get(sheet_name)
        if not map_key:
            logger.warning(f"  No map key for '{sheet_name}' — skipping")
            continue
        mapping = step5_maps.get(map_key, {})
        if not mapping:
            logger.warning(f"  No mapping for '{map_key}' — skipping")
            continue
        mapped_sheets[sheet_name] = _apply_db_mapping(df, mapping, map_key)

    # Write output
    output_path = OUTPUT_DIR / STEP5_FILENAME
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in mapped_sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    logger.info(f"Step 5 local file saved: {output_path}")
    logger.info("Step 5 complete")

    return mapped_sheets
