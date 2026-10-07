# Databricks notebook source
# MAGIC %md
# MAGIC # Run the Coverage pipeline
# MAGIC
# MAGIC Downloads one state/round from Kobo and loads it into the SARMAAN catalog
# MAGIC (`bronze`, `silver`, `gold`, `restricted`).
# MAGIC
# MAGIC 1. Set the widgets at the top: **round** (e.g. `zamfara_c1`, as listed in `config/kobo_assets.yml`),
# MAGIC    **dry_run** and **catalog**.
# MAGIC 2. **Run all.** Start with `dry_run = true`: it runs every step and checks the tables, but writes nothing to the catalog.
# MAGIC 3. Read the log at the bottom. When it is clean, set `dry_run = false` and run again to load.
# MAGIC
# MAGIC If Kobo is slow to build the export, the run stops after **export_wait_minutes** and leaves the export
# MAGIC on Kobo; run again later and it is picked up. You can also start the export on the Kobo website
# MAGIC (same saved export) and run this once it shows complete: the finished file is reused.
# MAGIC
# MAGIC The Kobo token is read from the `sarmaan` secret scope. The step outputs (Excel) and the log are
# MAGIC saved to `/Volumes/<catalog>/bronze/landing/coverage/<round>/<time>/`, never into this Git folder.

# COMMAND ----------

# MAGIC %pip install -q -r requirements-databricks.txt

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("round", "zamfara_c1", "Round (state_cycle)")
dbutils.widgets.dropdown("dry_run", "true", ["true", "false"], "Dry run (write nothing)")
dbutils.widgets.text("catalog", "eha_ghi_sarmaan_dev", "Catalog")
dbutils.widgets.text("export_wait_minutes", "60", "Wait for Kobo export (minutes)")

ROUND = dbutils.widgets.get("round").strip().lower()
DRY_RUN = dbutils.widgets.get("dry_run") == "true"
CATALOG = dbutils.widgets.get("catalog").strip()
EXPORT_WAIT = dbutils.widgets.get("export_wait_minutes").strip() or "60"
print(f"round={ROUND}  dry_run={DRY_RUN}  catalog={CATALOG}  export_wait_minutes={EXPORT_WAIT}")

# COMMAND ----------

import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

COVERAGE_DIR = os.path.dirname(os.getcwd())          # this notebook lives in coverage/notebooks
WORK_DIR = tempfile.mkdtemp(prefix=f"coverage_{ROUND}_")

os.environ.update({
    "KOBO_ROUND": ROUND,
    "DATABRICKS_CATALOG": CATALOG,
    "LOAD_TARGET": "databricks",
    "COVERAGE_WORK_DIR": WORK_DIR,
    "KOBO_EXPORT_TIMEOUT_MINUTES": EXPORT_WAIT,
})

# Forget pipeline modules from an earlier run, so a new round's settings are read
for name in [n for n, m in sys.modules.items()
             if (getattr(m, "__file__", None) or "").startswith(COVERAGE_DIR)]:
    del sys.modules[name]
if COVERAGE_DIR not in sys.path:
    sys.path.insert(0, COVERAGE_DIR)

import config  # noqa: E402  (reads kobo_assets.yml and the secret scope)
print(f"Kobo form {config.KOBO_ASSET_UID} on {config.KOBO_BASE_URL}")
print(f"Sampling frame {config.DAT_FILE.relative_to(config.BASE_DIR)}")

# COMMAND ----------

import main  # noqa: E402

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
archive = f"/Volumes/{CATALOG}/bronze/landing/coverage/{ROUND}/{stamp}{'_dryrun' if DRY_RUN else ''}"
try:
    main.run(dry_run=DRY_RUN)
except SystemExit:
    # main.py exits when step 4 validation finds issues
    raise RuntimeError(
        f"Stopped at step 4: validation found issues, so nothing was loaded. "
        f"Open {archive}/outputs/04_validation_report.xlsx to see them."
    ) from None
finally:
    # Keep the step outputs and the log for this run, then clear the temp folder
    spark.sql(f"CREATE VOLUME IF NOT EXISTS `{CATALOG}`.`bronze`.`landing`")
    shutil.copytree(WORK_DIR, archive)
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    print(f"Step outputs and log saved to {archive}")
