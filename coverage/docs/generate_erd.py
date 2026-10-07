"""
generate_erd.py — Build the Coverage ERD from the mapping files.

Writes one DBML file per layer (paste into https://dbdiagram.io, or open with
any DBML tool) and erd_columns.json (every column, for the HTML ERD page):

  docs/erd/coverage_bronze.dbml   Step 1 map + metadata columns   (all STRING)
  docs/erd/coverage_silver.dbml   Step 2 map + keys               (all STRING)
  docs/erd/coverage_gold.dbml     Step 5 map + types, plus the restricted
                                  identifier tables
  docs/erd/index.html             The ERD page (index.template.html + the data),
                                  published in the sarmaan-coverage-erd repo

The columns come from the mapping files; the architecture review decisions
are applied on top (see ARCHITECTURE below). Re-run after editing a mapping
file:  python docs/generate_erd.py   (from the coverage folder)
"""

import json
import os
import sys
from pathlib import Path

COVERAGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COVERAGE_DIR))
# config.py requires the Kobo settings; the ERD does not use them
for key in ("KOBO_API_TOKEN", "KOBO_ASSET_UID", "KOBO_EXPORT_SETTINGS_ID"):
    os.environ.setdefault(key, "unused")

import pandas as pd  # noqa: E402

from load_common import (  # noqa: E402
    CLEAN_TABLE_CHAIN,
    CLEAN_SHEET_TO_MAP_KEY,
    RAW_TABLE_CHAIN,
    _load_clean_types,
)
from mappings import load_step1_maps, load_step2_maps, load_step5_maps  # noqa: E402
from step5_db_schema import build_silver  # noqa: E402
from step6_databricks_loader import ISSUES_COLUMNS, ISSUES_TABLE, _databricks_type  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "erd"

# ── ARCHITECTURE: the same rules the loader applies (architecture.py) ───────
import architecture as arch  # noqa: E402
from config import (  # noqa: E402
    DATABRICKS_BRONZE_SCHEMA as BRONZE,
    DATABRICKS_SILVER_SCHEMA as SILVER,
    DATABRICKS_GOLD_SCHEMA as GOLD,
    DATABRICKS_RESTRICTED_SCHEMA as RESTRICTED,
)

CATALOGS = ["eha_ghi_sarmaan_dev", "eha_ghi_sarmaan_prod"]
PARENT = arch.PARENT
BRONZE_METADATA = arch.BRONZE_METADATA
RUN_ID = (arch.RUN_ID, "STRING")
IDENTIFIERS = arch.IDENTIFIERS
PHONE_COLUMNS = arch.PHONE_COLUMNS
LAYER_KEY = {BRONZE: "bronze", SILVER: "silver", GOLD: "gold"}

STEP1_KEY = {"main_sheet": "main", "child_info": "child_info",
             "net_repeat": "net_repeat", "child_infoo": "child_infoo"}
STEP2_KEY = {"Household Code": "main", "Child_Info": "child_info",
             "Net_repeat": "net_repeat", "Child_Infoo": "child_infoo"}


def _col(name, type_, tag=None):
    c = {"name": name, "type": type_}
    if tag:
        c["tag"] = tag
    return c


def _table(schema, name, columns, source, pk=(), fk=(), parent=None,
           parent_schema=None, parent_pk=(), card=None, note=""):
    return {
        "schema": schema, "name": name, "source": source, "note": note,
        "pk": list(pk), "fk": list(fk), "parent": parent,
        "parent_schema": parent_schema, "parent_pk": list(parent_pk), "card": card,
        "columns": columns,
    }


# ── Columns from the mapping files ────────────────────────────────────────────

def _bronze_columns() -> dict[str, list[dict]]:
    maps = load_step1_maps()
    return {table: [_col(db, "STRING") for db in maps[STEP1_KEY[sheet]].values()]
            for sheet, table, *_ in RAW_TABLE_CHAIN}


def _silver_columns() -> dict[str, list[dict]]:
    maps = load_step2_maps()
    # One placeholder row per sheet with every Step 2 column (repeats kept),
    # run through the same build_silver() the loader uses.
    step2 = {}
    for sheet, key in STEP2_KEY.items():
        names = list(maps[key].values())
        step2[sheet] = pd.DataFrame([["x"] * len(names)], columns=names)
    sheets = build_silver(step2)
    return {table: [_col(c, "STRING") for c in sheets[sheet].columns]
            for sheet, table, *_ in CLEAN_TABLE_CHAIN}


def _gold_columns() -> dict[str, list[dict]]:
    maps = load_step5_maps()
    types = _load_clean_types()
    out = {}
    for sheet, table, *_ in CLEAN_TABLE_CHAIN:
        key = CLEAN_SHEET_TO_MAP_KEY[sheet]
        type_map = types.get(key, {})
        names = list(dict.fromkeys(list(maps[key].values()) + list(type_map)))
        out[table] = [_col(c, _databricks_type(type_map.get(c, "TEXT"))) for c in names]
    return out


# ── Architecture applied on top ───────────────────────────────────────────────

def _keys(layer, table):
    """(pk, fk) for a layer table: rootUuid, plus the row id for repeat groups."""
    return arch.keys(LAYER_KEY[layer], table)


def _ensure_first(columns, name):
    """Put the key column first, adding it if the mapping does not produce it."""
    rest = [c for c in columns if c["name"] != name]
    return [_col(name, "STRING", "key")] + rest


def _layer_tables(layer, cols_by_table, source_of, extra_cols):
    tables = []
    for table, columns in cols_by_table.items():
        pk, fk = _keys(layer, table)
        columns = _ensure_first(columns, pk[0])
        missing = [k for k in pk if k not in {c["name"] for c in columns}]
        assert not missing, f"{layer}.{table}: key column(s) {missing} not in the mapping"
        columns = columns + [_col(n, t, "metadata") for n, t in extra_cols]
        parent_pk = _keys(layer, PARENT)[0]
        tables.append(_table(
            layer, table, columns, source_of(table), pk, fk,
            PARENT if fk else None, layer if fk else None, parent_pk if fk else (),
            "many" if fk else None,
        ))
    return tables


def bronze_tables():
    src = {t: f"step_1_map_file.xlsx ({STEP1_KEY[s]})" for s, t, *_ in RAW_TABLE_CHAIN}
    return _layer_tables(BRONZE, _bronze_columns(), src.get, BRONZE_METADATA)


def silver_tables():
    src = {t: f"step_2_map_file.xlsx ({STEP2_KEY[s]}) + keys" for s, t, *_ in CLEAN_TABLE_CHAIN}
    tables = _layer_tables(SILVER, _silver_columns(), src.get, [RUN_ID])
    types = {"logged_at": "TIMESTAMP", "value_masked": "BOOLEAN"}
    issues = [_col(c, types.get(c, "STRING"), "metadata" if c == arch.RUN_ID else None)
              for c in ISSUES_COLUMNS]
    tables.append(_table(
        SILVER, ISSUES_TABLE, issues, "Step 4 validation report",
        note="value is masked (value_masked = true) when column_name is an identifier column",
    ))
    return tables


def gold_tables():
    src = {t: f"step_5_map_file.xlsx ({CLEAN_SHEET_TO_MAP_KEY[s]})" for s, t, *_ in CLEAN_TABLE_CHAIN}
    gold_cols = _gold_columns()

    restricted = []
    for table, ids in IDENTIFIERS.items():
        by_name = {c["name"]: c for c in gold_cols[table]}
        missing = [n for n in ids if n not in by_name]
        assert not missing, f"gold.{table}: identifier column(s) {missing} not in the mapping"
        pk, _ = _keys(GOLD, table)
        id_cols = [_col(n, "STRING" if n in PHONE_COLUMNS else by_name[n]["type"], "identifier")
                   for n in ids]
        # Same key types as the gold table, so the 1:1 foreign key lines up
        key_cols = [_col(k, by_name[k]["type"] if k in by_name else "STRING", "key") for k in pk]
        restricted.append(_table(
            RESTRICTED, arch.restricted_table(table), key_cols + id_cols + [_col(*RUN_ID, "metadata")],
            f"moved out of gold.{table}", pk, pk, table, GOLD, pk, "one",
            note=f"one row per gold.{table} row; access restricted",
        ))
        gold_cols[table] = [c for c in gold_cols[table] if c["name"] not in ids]

    return _layer_tables(GOLD, gold_cols, src.get, [RUN_ID]) + restricted


# ── Output ────────────────────────────────────────────────────────────────────

def _ident(name: str) -> str:
    return name if name.replace("_", "").isalnum() and not name[0].isdigit() else f'"{name}"'


def _cols_ref(cols):
    return _ident(cols[0]) if len(cols) == 1 else "(" + ", ".join(_ident(c) for c in cols) + ")"


def to_dbml(layer: str, tables: list[dict]) -> str:
    lines = [f"// SARMAAN II Coverage — Databricks catalogs {' / '.join(CATALOGS)}, layer: {layer}",
             "// Keys use Kobo rootUuid (pending the key spike).",
             "// Generated by coverage/docs/generate_erd.py from the mapping files. Do not edit.", ""]
    for t in tables:
        lines.append(f"Table {t['schema']}.{t['name']} {{")
        for c in t["columns"]:
            attrs = []
            if len(t["pk"]) == 1 and c["name"] == t["pk"][0]:
                attrs.append("pk")
            if c.get("tag") in ("metadata", "identifier"):
                attrs.append(f"note: '{c['tag']}'")
            suffix = f" [{', '.join(attrs)}]" if attrs else ""
            lines.append(f"  {_ident(c['name'])} {c['type'].lower()}{suffix}")
        if len(t["pk"]) > 1:
            lines += ["", "  indexes {", f"    {_cols_ref(t['pk'])} [pk]", "  }"]
        note = f"{len(t['columns'])} columns. Source: {t['source']}." + (f" {t['note']}." if t["note"] else "")
        lines.append(f"  Note: '{note}'")
        lines.append("}")
        lines.append("")
    for t in tables:
        if t["fk"]:
            op = ">" if t["card"] == "many" else "-"
            lines.append(f"Ref: {t['schema']}.{t['name']}.{_cols_ref(t['fk'])} {op} "
                         f"{t['parent_schema']}.{t['parent']}.{_cols_ref(t['parent_pk'])}")
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    layers = {BRONZE: bronze_tables(), SILVER: silver_tables(), GOLD: gold_tables()}
    for layer, tables in layers.items():
        for t in tables:
            names = [c["name"].lower() for c in t["columns"]]
            assert len(names) == len(set(names)), f"{t['schema']}.{t['name']} repeats a column"
        (OUT_DIR / f"coverage_{layer}.dbml").write_text(to_dbml(layer, tables), encoding="utf-8")
        counts = ", ".join(f"{t['schema']}.{t['name']} {len(t['columns'])}" for t in tables)
        print(f"{layer}: {counts}")
    data = json.dumps({"catalogs": CATALOGS, "layers": layers}, separators=(",", ":"))
    (OUT_DIR / "erd_columns.json").write_text(data, encoding="utf-8")
    # Self-contained ERD page (the sarmaan-coverage-erd repo's index.html)
    template = (OUT_DIR / "index.template.html").read_text(encoding="utf-8")
    assert template.count("__DATA__") == 1
    (OUT_DIR / "index.html").write_text(template.replace("__DATA__", data), encoding="utf-8")
    print(f"Written to {OUT_DIR}")


if __name__ == "__main__":
    main()
