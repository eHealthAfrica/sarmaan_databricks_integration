# sarmaan_databricks_integration

Stage, audit and load pipelines for SARMAAN survey data (KoboToolbox -> Postgres).

| Folder | Stager & auditor (phase 1) | Loader (phase 2) | Target |
|---|---|---|---|
| `amr/` | Household, Mother, Child stagers (Zamfara) | Household, Mother, Child loaders | `sarmaan_2.sarmaan2data.amr_*` |
| `pharmacy/` | Pharmacy stager (Zamfara) | Pharmacy loader | `sarmaan_2.sarmaan2data.pharmacy_information` |
| `mortality/` | Household / Female / Pregnancy stager | Mortality loader | `mortality.mortalitydata.*` |
| `coverage/` | 6-step pipeline: `python main.py` (see [coverage/README.md](coverage/README.md)) | Step 6 upsert | `raw_data.coverage_*` and `sarmaan2data.coverage_*` |

Each run has two phases:

1. **Stage & audit.** Pull the Kobo export, apply the mapping CSV, write `STAGING_*.xlsx` and an audit PDF (value frequencies plus duplicate-code warnings). Review both before loading.
2. **Load.** Append the reviewed staging file to Postgres. Rows whose `concatenated_id` is already in the table are skipped, so it is safe to re-run.

## Setup

```
pip install -r requirements.txt
cp .env.example .env   # then fill in PG_PASSWORD, KOBO_TOKEN and the data folders
```

Mapping files are in `map/amr/`, `map/pharmacy/` and `map/mortality/`. See [docs/SCHEMA.md](docs/SCHEMA.md) (AMR, Pharmacy, Mortality) and [coverage/SCHEMA.md](coverage/SCHEMA.md) (Coverage) for what each pipeline reads and writes.

AMR order: run household, then mother, then child (child and mother pull codes from the parent sheets).

## Security

- Credentials come only from environment variables or `.env`, which is git-ignored. On Databricks, use a secret scope.
- Data files (`*.xlsx`, `*.csv`, `*.pdf`) are git-ignored because they contain personal and health data. The only data-format files committed are the column mappings in `map/` and `coverage/mappings/`, which contain no survey data.
