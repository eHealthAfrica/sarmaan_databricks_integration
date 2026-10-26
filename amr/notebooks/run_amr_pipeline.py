# Databricks notebook source
# MAGIC %md
# MAGIC # Run the AMR pipeline
# MAGIC
# MAGIC Downloads one AMR round (household, mother, child) from Kobo and loads it into the SARMAAN catalog
# MAGIC (`bronze`, `silver`, `gold`, `restricted`), following the AMR ERD (`amr/docs/erd/`).
# MAGIC
# MAGIC 1. Set the widgets at the top: **round** (e.g. `zamfara_c1`, as listed under `amr:` in `config/kobo_assets.yml`),
# MAGIC    **dry_run** and **catalog**.
# MAGIC 2. **Run all.** Start with `dry_run = true`: it downloads, builds and checks every table, but writes nothing to the catalog.
# MAGIC 3. Read the log at the bottom. When it is clean, set `dry_run = false` and run again to load.
# MAGIC
# MAGIC The raw Kobo file, the run log and any issues are kept in
# MAGIC `/Volumes/<catalog>/bronze/landing/amr/<round>/<time>/`, never in this Git folder.
# MAGIC A blocking issue (empty or repeated key, child without its mother) stops the run before anything is loaded.

# COMMAND ----------

# MAGIC %pip install -q "openpyxl>=3.1.2" "pyyaml>=6.0"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("round", "zamfara_c1", "Round (state_cycle)")
dbutils.widgets.dropdown("dry_run", "true", ["true", "false"], "Dry run (write nothing)")
dbutils.widgets.text("catalog", "eha_ghi_sarmaan_dev", "Catalog")
dbutils.widgets.text("export_wait_minutes", "60", "Wait for Kobo export (minutes)")
dbutils.widgets.text("pipeline_version", "", "Pipeline version (set by the job)")

ROUND = dbutils.widgets.get("round").strip().lower()
DRY_RUN = dbutils.widgets.get("dry_run") == "true"
CATALOG = dbutils.widgets.get("catalog").strip()
EXPORT_WAIT = float(dbutils.widgets.get("export_wait_minutes").strip() or "60")
PIPELINE_VERSION = dbutils.widgets.get("pipeline_version").strip()
print(f"round={ROUND}  dry_run={DRY_RUN}  catalog={CATALOG}  export_wait_minutes={EXPORT_WAIT:g}")

# COMMAND ----------

import logging
import os
import sys

# amr/ is two levels up from this notebook (amr/notebooks/<this>). Derived from
# the notebook's own path, not the working directory, which is not the
# notebook's folder when this runs as a job task.
try:
    AMR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    _nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
    AMR_DIR = os.path.dirname(os.path.dirname("/Workspace" + _nb))

# Forget pipeline modules from an earlier run in this session
for name in [n for n, m in sys.modules.items() if (getattr(m, "__file__", None) or "").startswith(AMR_DIR)]:
    del sys.modules[name]
if AMR_DIR not in sys.path:
    sys.path.insert(0, AMR_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    stream=sys.stdout, force=True)

from pipeline.run import git_version, run  # noqa: E402
from pipeline.settings import Settings  # noqa: E402

settings = Settings.load(ROUND, CATALOG, DRY_RUN, EXPORT_WAIT,
                         PIPELINE_VERSION or git_version(), dbutils=dbutils)
print(f"Kobo form {settings.kobo_asset_uid} on {settings.kobo_base_url}")

# COMMAND ----------

spark.sql(f"CREATE VOLUME IF NOT EXISTS `{CATALOG}`.`bronze`.`landing`")
summary = run(settings, spark=spark)
display(spark.createDataFrame([(k, v) for k, v in summary.items()], "table STRING, rows INT"))
