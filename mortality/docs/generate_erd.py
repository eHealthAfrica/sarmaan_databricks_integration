"""
generate_erd.py — Build the Mortality ERD (household -> female -> pregnancy) for
the Databricks layers, the same way as amr/docs/generate_erd.py.

Reads:
  map/mortality/export_columns.txt   the Kobo export's columns (XML headers)   -> bronze
  map/mortality/gold_types.csv       DB columns, gold types, export source       -> silver, gold
  mortality/architecture.py          keys, lineage columns, identifiers          -> all layers
Writes (mortality/docs/erd/):
  mortality_bronze.dbml, mortality_silver.dbml, mortality_gold.dbml   paste into https://dbdiagram.io
  erd_columns.json                                                     every column, for the page
  index.html                                                           the ERD page (index.template.html + data)

gold_types.csv was built from map/mortality/{household,female,pregnancy}_map.csv
(the Postgres columns, in the Postgres order) and the form (mortality_form.csv):
  type           from the column's transform and form question type
  export_column  where the value comes from in the export (blank = no Kobo column)
  other_sources  further export columns the Postgres stager fell back to
  status         review = the stager's mapping was never confirmed for this column

Run from the repo root:  python mortality/docs/generate_erd.py
"""

import csv
import json
import sys
from pathlib import Path

MORTALITY_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = MORTALITY_DIR.parent
sys.path.insert(0, str(MORTALITY_DIR))

import architecture as arch  # noqa: E402

MAP_DIR = REPO_DIR / "map" / "mortality"
OUT_DIR = Path(__file__).resolve().parent / "erd"
CATALOGS = ["eha_ghi_sarmaan_dev", "eha_ghi_sarmaan_prod"]
SHEETS = ["household", "female", "pregnancy"]
# Filled by the pipeline although the export has no column for them
PIPELINE_FILLED = {"state", "lga", "ward", "community", "concatenated_id"}


def _col(name, type_, tag=None):
    c = {"name": name, "type": type_}
    if tag:
        c["tag"] = tag
    return c


def _table(schema, name, columns, source, pk, fk=(), parent=None, parent_schema=None,
           parent_pk=(), card=None, note=""):
    return {"schema": schema, "name": name, "source": source, "note": note,
            "pk": list(pk), "fk": list(fk), "parent": parent, "parent_schema": parent_schema,
            "parent_pk": list(parent_pk), "card": card, "columns": columns}


# ── Inputs ────────────────────────────────────────────────────────────────────

def export_columns() -> dict[str, list[str]]:
    sheets, current = {}, None
    for line in (MAP_DIR / "export_columns.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sheets[current] = []
        else:
            sheets[current].append(line)
    return sheets


def gold_types() -> dict[str, list[dict]]:
    """{sheet: [row, ...]} in the Postgres column order."""
    out = {s: [] for s in SHEETS}
    with open(MAP_DIR / "gold_types.csv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["table"]].append(row)
    return out


def _tag(sheet, row):
    if row["db_name"] in arch.IDENTIFIERS.get(sheet, []):
        return "identifier"
    if not row["export_column"] and row["db_name"] not in PIPELINE_FILLED:
        return "empty"
    return None


# ── Layers ────────────────────────────────────────────────────────────────────

def bronze_tables(columns: dict[str, list[str]]) -> list[dict]:
    tables = []
    for sheet in SHEETS:
        cols = [_col(arch.bronze_name(c), "STRING") for c in columns[sheet]]
        cols += [_col(n, t, "metadata") for n, t in arch.BRONZE_METADATA]
        pk, fk = arch.BRONZE_KEYS[sheet]
        parent = arch.PARENT[sheet]
        tables.append(_table(
            "bronze", arch.TABLES[sheet], cols, f"Kobo export, sheet '{sheet}' (XML headers)", pk, fk,
            arch.TABLES[parent] if parent else None, "bronze" if parent else None,
            arch.BRONZE_PARENT_KEYS.get(sheet, []), "many" if parent else None,
        ))
    return tables


def _keyed(sheet, rows, type_of):
    """root_uuid first, then the mapping's columns, then _run_id."""
    cols = [_col(arch.ROOT_UUID, "STRING", "key")]
    cols += [_col(r["db_name"], type_of(r), _tag(sheet, r)) for r in rows]
    cols.append(_col(arch.RUN_ID, "STRING", "metadata"))
    return cols


def silver_tables(types: dict[str, list[dict]]) -> list[dict]:
    tables = []
    for sheet in SHEETS:
        pk, fk = arch.KEYS[sheet]
        parent = arch.PARENT[sheet]
        tables.append(_table(
            "silver", arch.TABLES[sheet], _keyed(sheet, types[sheet], lambda r: "STRING"),
            f"map/mortality/{sheet}_map.csv (all submissions)", pk, fk,
            arch.TABLES[parent] if parent else None, "silver" if parent else None,
            arch.PARENT_KEYS.get(sheet, []), "many" if parent else None,
        ))
    return tables


def gold_tables(types: dict[str, list[dict]]) -> list[dict]:
    gold, restricted = [], []
    for sheet in SHEETS:
        pk, fk = arch.KEYS[sheet]
        parent = arch.PARENT[sheet]
        ids = arch.IDENTIFIERS.get(sheet, [])

        def gtype(r):
            return "STRING" if r["db_name"] in arch.PHONE_COLUMNS else r["type"]

        all_cols = _keyed(sheet, types[sheet], gtype)
        by_name = {c["name"]: c for c in all_cols}
        missing = [n for n in ids if n not in by_name]
        assert not missing, f"{sheet}: identifier column(s) {missing} not in the mapping"

        gold.append(_table(
            "gold", arch.TABLES[sheet], [c for c in all_cols if c["name"] not in ids],
            f"map/mortality/{sheet}_map.csv (approved only)", pk, fk,
            arch.TABLES[parent] if parent else None, "gold" if parent else None,
            arch.PARENT_KEYS.get(sheet, []), "many" if parent else None,
        ))
        if ids:
            rcols = [_col(k, by_name[k]["type"], "key") for k in pk]
            rcols += [_col(n, by_name[n]["type"], "identifier") for n in ids]
            rcols.append(_col(arch.RUN_ID, "STRING", "metadata"))
            restricted.append(_table(
                "restricted", arch.restricted_table(sheet), rcols,
                f"moved out of gold.{arch.TABLES[sheet]}", pk, pk, arch.TABLES[sheet], "gold", pk, "one",
                note=f"one row per gold.{arch.TABLES[sheet]} row; access restricted",
            ))
    return gold + restricted


# ── Output ────────────────────────────────────────────────────────────────────

def _ident(name: str) -> str:
    return name if name.replace("_", "").isalnum() and not name[0].isdigit() else f'"{name}"'


def _cols_ref(cols):
    return _ident(cols[0]) if len(cols) == 1 else "(" + ", ".join(_ident(c) for c in cols) + ")"


def to_dbml(layer: str, tables: list[dict]) -> str:
    lines = [f"// SARMAAN II Mortality — Databricks catalogs {' / '.join(CATALOGS)}, layer: {layer}",
             "// Keys use Kobo rootUuid (pending the key spike).",
             "// Generated by mortality/docs/generate_erd.py. Do not edit.", ""]
    for t in tables:
        lines.append(f"Table {t['schema']}.{t['name']} {{")
        for c in t["columns"]:
            attrs = []
            if len(t["pk"]) == 1 and c["name"] == t["pk"][0]:
                attrs.append("pk")
            if c.get("tag") in ("metadata", "identifier"):
                attrs.append(f"note: '{c['tag']}'")
            if c.get("tag") == "empty":
                attrs.append("note: 'no question in this form'")
            lines.append(f"  {_ident(c['name'])} {c['type'].lower()}" + (f" [{', '.join(attrs)}]" if attrs else ""))
        if len(t["pk"]) > 1:
            lines += ["", "  indexes {", f"    {_cols_ref(t['pk'])} [pk]", "  }"]
        note = f"{len(t['columns'])} columns. Source: {t['source']}." + (f" {t['note']}." if t["note"] else "")
        lines += [f"  Note: '{note}'", "}", ""]
    for t in tables:
        if t["fk"]:
            op = ">" if t["card"] == "many" else "-"
            lines.append(f"Ref: {t['schema']}.{t['name']}.{_cols_ref(t['fk'])} {op} "
                         f"{t['parent_schema']}.{t['parent']}.{_cols_ref(t['parent_pk'])}")
    return "\n".join(lines) + "\n"


PAGE = {
    "page_title": "SARMAAN Mortality ERD",
    "title": "Mortality physical data model",
    "eyebrow": 'Databricks · catalogs <span class="mono">eha_ghi_sarmaan_dev</span> / '
               '<span class="mono">eha_ghi_sarmaan_prod</span> · Mortality survey',
    "pending": "<b>Keys pending the key spike.</b> Every table is keyed on the Kobo "
               '<span class="mono">rootUuid</span>, which stays the same when a submission is edited. '
               "Women add their mother code and pregnancies their pregnancy code; a pregnancy points at its woman "
               "on rootUuid + mother code. <b>To confirm on the first export:</b> "
               '<span class="mono">state</span> and <span class="mono">settlement_cluster</span> come from '
               "questions in an older form version, and columns marked review were never confirmed in the "
               "Postgres mapping. Dev and prod catalogs have the same schemas and tables.",
    "about": {
        "bronze": "<b>bronze</b> · every Kobo submission as downloaded (XML headers), all columns STRING, "
                  'keyed on Kobo rootUuid, with lineage columns <span class="mono">_ingested_at</span>, '
                  '<span class="mono">_run_id</span>, <span class="mono">_source_system</span>, '
                  '<span class="mono">_source_asset</span>, <span class="mono">_pipeline_version</span>.',
        "silver": "<b>silver</b> · all submissions with the Mortality mapping's names, keyed on "
                  '<span class="mono">root_uuid</span> (+ mother/pregnancy code), carrying <span class="mono">_run_id</span>.',
        "gold": "<b>gold</b> · approved submissions only, typed from the mapping and the form's question types, keyed on "
                '<span class="mono">root_uuid</span> (+ mother/pregnancy code), carrying <span class="mono">_run_id</span>. '
                'Names, phones, GPS and the interview audio are in <span class="mono">restricted</span>, one row per gold row.',
    },
    "restricted_note": "<b>restricted</b> · identifier columns moved out of gold: names, phone numbers (STRING), "
                       "GPS and the interview audio recording. Each table has the same key as the gold table it "
                       "belongs to, one row per gold row (1:1). Access is limited to approved users.",
    "footer": "Generated by mortality/docs/generate_erd.py from the Mortality export columns, the Mortality "
              "mapping files and gold_types.csv, with the architecture review decisions in mortality/architecture.py. "
              "Primary and foreign keys are informational in Databricks; the loader's checks enforce them.",
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    types = gold_types()
    layers = {"bronze": bronze_tables(export_columns()), "silver": silver_tables(types), "gold": gold_tables(types)}
    for layer, tables in layers.items():
        for t in tables:
            names = [c["name"].lower() for c in t["columns"]]
            dupes = sorted({n for n in names if names.count(n) > 1})
            assert not dupes, f"{t['schema']}.{t['name']} repeats column(s) {dupes}"
            for k in t["pk"] + t["fk"]:
                assert k in names, f"{t['schema']}.{t['name']}: key column '{k}' not in the table"
        (OUT_DIR / f"mortality_{layer}.dbml").write_text(to_dbml(layer, tables), encoding="utf-8")
        print(f"{layer}: " + ", ".join(f"{t['schema']}.{t['name']} {len(t['columns'])}" for t in tables))
    data = json.dumps({"catalogs": CATALOGS, **PAGE, "layers": layers}, separators=(",", ":"))
    (OUT_DIR / "erd_columns.json").write_text(data, encoding="utf-8")
    template = (OUT_DIR / "index.template.html").read_text(encoding="utf-8")
    assert template.count("__DATA__") == 1
    (OUT_DIR / "index.html").write_text(template.replace("__DATA__", data), encoding="utf-8")
    print(f"Written to {OUT_DIR}")


if __name__ == "__main__":
    main()
