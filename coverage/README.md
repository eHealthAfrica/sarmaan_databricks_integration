# SARMAAN Coverage pipeline

KoboToolbox → transform → validate → PostgreSQL (`raw_data` and `sarmaan2data` schemas).

What it reads from Kobo and writes to the database is described in [SCHEMA.md](SCHEMA.md).

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
├── step6_db_loader.py        ← upserts into raw_data.* and sarmaan2data.* in one transaction
├── mappings/                 ← step_1/2/3/5 map files, completeness template, dat.csv (sampling frame)
├── outputs/                  ← local outputs (git-ignored: contain survey data)
├── logs/                     ← one log per run (git-ignored)
├── requirements.txt
└── .env.example              ← copy to .env and fill in
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in the Kobo token, asset UID, export settings ID and Postgres details
```

## Running

```bash
python main.py              # all steps
python main.py --step 1     # one step
python main.py --step 4 5   # re-run validation and DB mapping from the latest local outputs
python main.py --step 6     # load the latest 01_raw_xml_export.xlsx and 05_db_ready.xlsx into Postgres
```

When a step runs without the earlier steps, it loads the **most recently written** local output for those steps.

| Step | Local output | What it does |
|---|---|---|
| 1 | `01_raw_xml_export.xlsx` | Raw export, 4 sheets, with PK/FK columns added |
| 2 | `SARMAAN_II_COVERAGE_{STATE}_{CYCLE}_RAW.xlsx` | Kobo names → readable names |
| 3 | `SARMAAN_II_COVERAGE_{STATE}_{CYCLE}_CLEANED.xlsx` | Approved submissions merged into `household_info` + `net_info` |
| 4 | `04_validation_report.xlsx` | Completeness and standardization issues; the run stops if there are any |
| 5 | `05_db_ready.xlsx` | Approved submissions with DB column names |
| 6 | (database) | Upsert into `raw_data.coverage_*` and `sarmaan2data.coverage_*` |

## Database load (step 6)

- **Upsert:** rows are inserted or updated on the table's primary key, so re-running the same state and cycle doesn't create duplicates.
- **Schema safety:** existing tables are never altered. If a mapped column is missing from the table, the run stops.
- **Duplicate guard:** a household UUID that already exists under a different primary key stops the run.
- **Orphan check:** child rows whose household isn't in the batch stop the run.
- **Transaction:** everything is in one transaction. Any error rolls back the whole load.

## Updating mappings

Edit the Excel files in `mappings/`. Changes take effect on the next run, with no code changes.
