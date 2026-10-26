# SARMAAN AMR (AntiMicrobial Resistance)

Two ways the AMR data is loaded:

| | Where | What |
|---|---|---|
| **Databricks pipeline** (new) | `pipeline/`, `notebooks/run_amr_pipeline.py` | Kobo → `bronze`, `silver`, `gold`, `restricted` in `eha_ghi_sarmaan_dev` / `eha_ghi_sarmaan_prod` |
| Postgres scripts (current) | `* stager_and_auditor_Zamfara.py`, `* loader LIVE.py` | Kobo → staging Excel + audit PDF → `sarmaan2data.amr_*` |

The tables follow the AMR ERD (`docs/erd/`, built by `docs/generate_erd.py`) and the decisions in `architecture.py`, which are the same as Coverage.

## Tables

| Schema | Tables | Contents |
|---|---|---|
| `bronze` | `amr_household`, `amr_mother`, `amr_child` | The Kobo export as downloaded, every column STRING, plus `_ingested_at`, `_run_id`, `_source_system`, `_source_asset`, `_pipeline_version`. **Append-only**: every run adds its rows. |
| `silver` | same three | Every submission, DB column names, all STRING, plus `root_uuid` and `_run_id` |
| `silver` | `amr_validation_issues` | One row per issue found by a run; identifier values masked |
| `gold` | same three | Approved submissions only, typed, **no identifiers** |
| `restricted` | `amr_*_identifiers` | Names, phone numbers (STRING), GPS and signatures of the gold rows, same key |

**Keys:** household `root_uuid`; mother `root_uuid + mother_code`; child `root_uuid + child_code`, pointing at its mother on `root_uuid + mother_code`. `root_uuid` is Kobo's `meta/rootUuid`, which stays the same when a submission is edited.

**Columns:** `map/amr/zamfara_gold_types.csv` lists every silver/gold column, its gold type and `export_column` (where it comes from in the export). A blank `export_column` means the form has no question for it: location and cycle are copied from the household, `concatenated_id` is built as in Postgres, and the rest load as NULL.

## Running in Databricks

1. **Form:** the round is an entry under `amr:` in [../config/kobo_assets.yml](../config/kobo_assets.yml) (`zamfara_c1`). The Kobo token comes from the `sarmaan` secret scope.
2. Open `amr/notebooks/run_amr_pipeline`, set **round**, **dry_run** and **catalog**, and **Run all**. Start with `dry_run = true`.
3. Each run keeps the raw Kobo file, `run.log` and `issues.csv` in `/Volumes/<catalog>/bronze/landing/amr/<round>/<time>/`.

**What stops a run** (nothing is loaded): an empty or repeated key, or a child whose mother is not in the same submission. **Warnings** (the run continues): a mapped column missing from the export, or a value that does not fit its gold type; both load as NULL and are listed in `issues.csv`.

An existing table is never altered. If a run needs a column a table lacks, it stops before writing anything.

## Tests

```
python -m unittest discover -s amr/tests -v
```

They build a made-up export from the real AMR column list and check approval filtering, keys, identifiers, value recoding and the blocking checks. No Kobo or Databricks needed.
