# SARMAAN Mortality

Two ways the Mortality data is loaded:

| | Where | What |
|---|---|---|
| **Databricks pipeline** (new) | `pipeline/`, `notebooks/run_mortality_pipeline.py` | Kobo → `bronze`, `silver`, `gold`, `restricted` in `eha_ghi_sarmaan_dev` / `eha_ghi_sarmaan_prod` |
| Postgres scripts (current) | `stager_auditor_mortality.py`, `loader_mortality.py` | Kobo export file → staging Excel + audit PDF → `mortality.mortalitydata.*` |

The tables follow the Mortality ERD (`docs/erd/`, live at https://ehealthafrica.github.io/sarmaan_databricks_integration/) and the decisions in `architecture.py`, which are the same as Coverage and AMR.

## Tables

| Schema | Tables | Contents |
|---|---|---|
| `bronze` | `mortality_household`, `mortality_female`, `mortality_pregnancy` | The Kobo export as downloaded, every column STRING, plus `_ingested_at`, `_run_id`, `_source_system`, `_source_asset`, `_pipeline_version`. **Append-only**: every run adds its rows. |
| `silver` | same three | Every submission, the Postgres column names and values, all STRING, plus `root_uuid` and `_run_id` |
| `silver` | `mortality_validation_issues` | One row per issue found by a run; identifier values masked |
| `gold` | same three | Approved submissions only, typed, **no identifiers** |
| `restricted` | `mortality_*_identifiers` | Names, phone numbers (STRING), GPS and the interview audio of the gold rows, same key |

**Keys:** household `root_uuid`; woman `root_uuid + mother_code` (form `mother_id`); pregnancy `root_uuid + pregnancy_code` (form `preg_id`), pointing at its woman on `root_uuid + mother_code`. `root_uuid` is Kobo's `meta/rootUuid`; the female sheet has none of its own, so it takes its household's.

**Values match Postgres.** Each column is filled the way `stager_auditor_mortality.py` fills it: the `transform` of its row in `map/mortality/<sheet>_map.csv` (yes/no, label recodes, month names, `99` = "Don't know", …, copied in `pipeline/recodes.py`), LGA / ward / community from the first non-blank of their form fields, and location copied from the household onto women and pregnancies. Two differences, on purpose:
- `state`: when the export leaves it blank (the current form has no state question), it is the round's `state` from `config/kobo_assets.yml` instead of a constant in the code.
- `start_time`, `end_time`: the time Kobo recorded, stored as a timestamp. The Postgres stager writes the same time with a `+00` suffix although it is local time, not UTC.

Column list and gold types: `map/mortality/gold_types.csv` (Postgres order).

## Running in Databricks

1. **Form:** the round is an entry under `mortality:` in [../config/kobo_assets.yml](../config/kobo_assets.yml): `yobe_potiskum` (Yobe State, Potiskum LGA). Its saved export (`export_settings_id`) must use XML values and headers. The Kobo token comes from the `sarmaan` secret scope.
2. Open `mortality/notebooks/run_mortality_pipeline`, set **round**, **dry_run** and **catalog**, and **Run all**. Start with `dry_run = true`.
3. Each run keeps the raw Kobo file, `run.log` and `issues.csv` in `/Volumes/<catalog>/bronze/landing/mortality/<round>/<time>/`.

**What stops a run** (nothing is loaded): an empty or repeated key, a woman without her household, or a pregnancy without its woman. **Warnings** (the run continues): a mapped column missing from the export, or a value that does not fit its gold type; both load as NULL and are listed in `issues.csv`.

An existing table is never altered. If a run needs a column a table lacks, it stops before writing anything.

## Tests

```
python -m unittest discover -s mortality/tests -v
```

They build a made-up export from the real Mortality column list and check approval filtering, keys, identifiers, the Postgres value rules, the state fallback and the blocking checks. No Kobo or Databricks needed.
