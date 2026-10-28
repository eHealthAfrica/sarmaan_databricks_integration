# SARMAAN Pharmacy

Two ways the Pharmacy data is loaded:

| | Where | What |
|---|---|---|
| **Databricks pipeline** (new) | `pipeline/`, `notebooks/run_pharmacy_pipeline.py` | Kobo → `bronze`, `silver`, `gold`, `restricted` in `eha_ghi_sarmaan_dev` / `eha_ghi_sarmaan_prod` |
| Postgres scripts (current) | `pharmacy_stager_auditor zamfara.py`, `pharmacy_loader.py` | Kobo → staging Excel + audit PDF → `sarmaan2data.pharmacy_information` |

The tables follow the Pharmacy ERD (`docs/erd/`, live at https://ehealthafrica.github.io/sarmaan_databricks_integration/pharmacy/) and the decisions in `architecture.py`, which are the same as Coverage, AMR and Mortality.

## Tables

The form has no repeats: one row per pharmacy or drug shop, one table per layer.

| Schema | Table | Contents |
|---|---|---|
| `bronze` | `pharmacy` | The Kobo export as downloaded, every column STRING, plus `_ingested_at`, `_run_id`, `_source_system`, `_source_asset`, `_pipeline_version`. **Append-only**: every run adds its rows. |
| `silver` | `pharmacy` | Every submission, the Postgres column names and values, all STRING, plus `root_uuid` and `_run_id` |
| `silver` | `pharmacy_validation_issues` | One row per issue found by a run; identifier values masked |
| `gold` | `pharmacy` | Approved submissions only, typed, **no identifiers** |
| `restricted` | `pharmacy_identifiers` | Enumerator and pharmacist names, the enumerator's phone (STRING), witness name, GPS, the pharmacist's signature and the shop photo (it shows the shop's name), same key as gold |

**Key:** `root_uuid`, Kobo's `meta/rootUuid`, which stays the same when a submission is edited.

**Values match Postgres.** Each column is filled the way `pharmacy_stager_auditor zamfara.py` fills it: yes/no answers as `Yes`/`No`, settlement type and gender capitalised, multiple-choice option columns `0`/`1` → `No`/`Yes`, numeric LGA codes from older form versions → LGA name (`map/pharmacy/zamfara_pharmacy_lga_lookup.csv`), and `start_time`, `end_time`, `date_of_consent`, `training_year` stored as dates. `cycle` has no question in the form: it is the round's `cycle` from `config/kobo_assets.yml` (`Year 1`) instead of a constant in the code.

Column list and gold types: `map/pharmacy/gold_types.csv` (Postgres order).

## Running in Databricks

1. **Form:** the round is an entry under `pharmacy:` in [../config/kobo_assets.yml](../config/kobo_assets.yml): `zamfara_c1`. Its saved export (`export_settings_id`) must use XML values and headers. The Kobo token comes from the `sarmaan` secret scope.
2. Open `pharmacy/notebooks/run_pharmacy_pipeline`, set **round**, **dry_run** and **catalog**, and **Run all**. Start with `dry_run = true`.
3. Each run keeps the raw Kobo file, `run.log` and `issues.csv` in `/Volumes/<catalog>/bronze/landing/pharmacy/<round>/<time>/`.

**What stops a run** (nothing is loaded): an empty or repeated key. **Warnings** (the run continues): a mapped column missing from the export, an LGA code not in the lookup, or a value that does not fit its gold type; all are listed in `issues.csv`.

An existing table is never altered. If a run needs a column a table lacks, it stops before writing anything.

## Tests

```
python -m unittest discover -s pharmacy/tests -v
```

They build a made-up export from the real Pharmacy column list and check approval filtering, the key, identifiers, the Postgres value rules (yes/no, option columns, LGA codes, dates, cycle) and the blocking check. No Kobo or Databricks needed.
