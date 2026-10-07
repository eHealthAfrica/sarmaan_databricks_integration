# SARMAAN Coverage pipeline

KoboToolbox → transform → validate → Databricks catalog `eha_ghi_sarmaan_dev` / `eha_ghi_sarmaan_prod` (`bronze`, `silver`, `gold`, `restricted` schemas). Postgres (`raw_data` and `sarmaan2data` schemas) is still supported for the parallel run before switch-over.

What it reads from Kobo and writes to the database is described in [SCHEMA.md](SCHEMA.md). Table and column names are the same in Postgres and Databricks.

## Files

```
coverage/
├── main.py                   ← entry point
├── config.py                 ← settings, read from .env
├── extractor.py              ← downloads the Kobo export (XML headers, one sheet per repeat)
├── preprocessor.py           ← drops Excel artefacts, splits child_names11, decodes location codes via dat.csv
├── naming.py                 ← output file names: SARMAAN_II_COVERAGE_{STATE}_{CYCLE}_{RAW|CLEANED}.xlsx
├── mappings.py               ← loads the mapping files
├── step1_raw_export.py       ← raw export + PK/FK columns
├── step2_rename_columns.py   ← Kobo names → readable names (strict filter)
├── step3_partner_output.py   ← approved only; merge into household_info / net_info for partners
├── step4_validation.py       ← completeness + standardization rules (stops the run on any issue)
├── step5_db_schema.py        ← approved only; DB column names, keys, cycle, 0/1 → no/yes
├── step6_databricks_loader.py ← MERGE into <catalog>.bronze/silver/gold/restricted (default)
├── architecture.py           ← architecture review rules: keys, metadata, identifiers, masking
├── step6_db_loader.py        ← Postgres: upserts into raw_data.* and sarmaan2data.* in one transaction
├── load_common.py            ← table definitions and checks shared by both loaders
├── databricks/setup_catalog.sql ← staging volume (the catalog and schemas already exist)
├── docs/generate_erd.py      ← builds the ERD (docs/erd/index.html) from the mappings + architecture.py
├── mappings/                 ← step_1/2/3/5 map files, completeness template
│   └── rounds/<round>/dat.csv ← sampling frame (location codes → names) per state/round
├── notebooks/run_coverage_pipeline.py ← Databricks notebook: run one state/round
├── outputs/                  ← local outputs (git-ignored: contain survey data)
├── logs/                     ← one log per run (git-ignored)
├── requirements.txt
└── .env.example              ← copy to .env and fill in
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in the Kobo token, asset UID, export settings ID and Databricks details
```

## Running

```bash
python main.py              # all steps
python main.py --step 1     # one step
python main.py --step 4 5   # re-run validation and DB mapping from the latest local outputs
python main.py --step 6     # load the latest step 1, 2 and 5 outputs into the LOAD_TARGET
python main.py --dry-run    # all steps; step 6 builds and checks the Databricks tables but writes nothing
```

When a step runs without the earlier steps, it loads the **most recently written** local output for those steps.

| Step | Local output | What it does |
|---|---|---|
| 1 | `01_raw_xml_export.xlsx` | Raw export, 4 sheets, with PK/FK columns added |
| 2 | `SARMAAN_II_COVERAGE_{STATE}_{CYCLE}_RAW.xlsx` | Kobo names → readable names |
| 3 | `SARMAAN_II_COVERAGE_{STATE}_{CYCLE}_CLEANED.xlsx` | Approved submissions merged into `household_info` + `net_info` |
| 4 | `04_validation_report.xlsx` | Completeness and standardization issues; the run stops if there are any |
| 5 | `05_db_ready.xlsx` | Approved submissions with DB column names |
| 6 | (database) | Load into Databricks and/or Postgres, set by `LOAD_TARGET` |

## Database load (step 6)

`LOAD_TARGET` in `.env` picks where step 6 writes: `databricks` (default), `postgres`, or `both` (the same run to both, for the parallel run before switch-over).

### Databricks layers

Catalog: `eha_ghi_sarmaan_dev` (development) or `eha_ghi_sarmaan_prod` (production), set by `DATABRICKS_CATALOG`. The rules below come from the architecture review and live in [architecture.py](architecture.py).

| Schema | Filled from | Tables | Contents |
|---|---|---|---|
| `bronze` | Step 1 | `coverage_household`, `coverage_all_children`, `coverage_net_info`, `coverage_children_1_59` | Every submission, all columns as text, plus `_ingested_at`, `_run_id`, `_source_system`, `_source_asset`, `_pipeline_version` |
| `silver` | Step 2 | same four tables | Every submission (approved or not), readable column names, plus `root_uuid` and `_run_id` |
| `silver` | Step 4 | `coverage_validation_issues` | One row per failed check, appended when validation stops a run; failing values of identifier columns are masked (`value_masked`) |
| `gold` | Step 5 | same four tables | Approved submissions only, typed columns, plus `root_uuid` and `_run_id`; **no identifier columns** |
| `restricted` | Step 5 | `coverage_household_identifiers`, `coverage_all_children_identifiers`, `coverage_children_1_59_identifiers` | Names, phone numbers (`STRING`), GPS and card images, one row per gold row, same key |

**Keys (pending the key spike):** Kobo rootUuid in every layer (`meta_rootuuid` / `_submission_meta_rootuuid` in bronze, `root_uuid` in silver and gold). `coverage_household` is keyed on it; child tables on rootUuid + their row id, with rootUuid as the foreign key to the household. A household with no rootUuid gets `uuid:` + its `_uuid`, which is what Kobo sets on first submission.

Files are staged in the volume `/Volumes/<catalog>/bronze/landing/_staging/` during a load and deleted afterwards. The loader creates the volume if it is missing and your group may create it; otherwise an admin runs [databricks/setup_catalog.sql](databricks/setup_catalog.sql).

### Safeguards (both targets)

- **Upsert:** rows are inserted or updated on the table's primary key (`MERGE` in Databricks), so re-running the same state and cycle doesn't create duplicates.
- **Schema safety:** existing tables are never altered. If a mapped column is missing from the table, the run stops.
- **Duplicate guard (Postgres):** a household UUID that already exists under a different primary key stops the run. In Databricks the rootUuid key makes this unnecessary: an edited or re-exported submission keeps its rootUuid.
- **Orphan check:** child rows whose household isn't in the batch stop the run.
- **Keys (Databricks):** Databricks records primary and foreign keys but doesn't enforce them, so the loader also stops on blank or repeated primary keys in the batch.
- **All or nothing:** Postgres runs everything in one transaction. Databricks has no transaction across tables, so the loader runs every check before writing, notes each table's version, and if a `MERGE` fails it restores the tables it already changed (`RESTORE TABLE … TO VERSION AS OF …`).

### Running in Databricks

1. **Forms:** each state/round is an entry in [../config/kobo_assets.yml](../config/kobo_assets.yml) (`asset_uid`, `export_settings_id`). The Kobo token is read from the `sarmaan` secret scope (key `kobo-token`), so nothing secret is in the repo.
2. **Sampling frame:** each round has its location lookup at `mappings/rounds/<round>/dat.csv`.
3. **Run:** in the `eha-ghi-dev` workspace, open the repo as a Git folder, open `notebooks/run_coverage_pipeline`, set the widgets (`round`, `dry_run`, `catalog`) and **Run all**. Start with `dry_run = true`: it runs every step and checks the tables but writes nothing.
4. **Outputs:** the step outputs (Excel) and the log are saved to `/Volumes/<catalog>/bronze/landing/coverage/<round>/<time>/`. The notebook loads through its own Spark session, so it needs no Databricks login settings.

You need membership of `sarmaan-engineers` (read/write on `bronze`, `silver`, `gold`, `restricted`, and the `sarmaan` secret scope).

**Adding a state/round:** add its entry to `kobo_assets.yml` and its `dat.csv` under `mappings/rounds/<round>/`.

### Running on a laptop (testing)

In `.env`, set `KOBO_ROUND` (or `KOBO_ASSET_UID` + `KOBO_EXPORT_SETTINGS_ID`) and `KOBO_API_TOKEN`; for the Databricks load also `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH` (SQL Warehouses → your warehouse → Connection details), `DATABRICKS_CATALOG`, and `DATABRICKS_TOKEN`. Then `python main.py --dry-run` and `python main.py`.

## Updating mappings

Edit the Excel files in `mappings/`. Changes take effect on the next run, with no code changes.
