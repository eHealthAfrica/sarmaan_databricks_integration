"""
run.py — Run the Pharmacy pipeline for one round.

  1. Download the round's Kobo export (kobo.py).
  2. Land it unchanged in the Volume:
       /Volumes/<catalog>/bronze/landing/pharmacy/<round>/<time>/kobo_export.xlsx
     and read bronze from that file, so what was loaded can always be traced
     back to the exact file Kobo gave us.
  3. Build and check every table in memory (transform.py).
  4. A blocking issue stops the run: nothing is loaded, the issues go to
     silver.pharmacy_validation_issues and to issues.csv next to the export.
  5. Otherwise load bronze, silver, gold and restricted (load.py).

dry_run = True does steps 1-4 and writes nothing to the catalog (the export,
issues.csv and the log are still kept in the Volume, in a *_dryrun folder).
"""

import logging
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .kobo import Kobo, read_export
from .settings import PHARMACY_DIR, Settings
from .transform import RunInfo, build

logger = logging.getLogger("pharmacy")
LOG_PER_CHECK = 20


class ValidationFailed(RuntimeError):
    pass


def git_version() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PHARMACY_DIR,
                             capture_output=True, text=True, check=True, timeout=10)
        return f"git-{out.stdout.strip()}"
    except Exception:
        return "unknown"


def _log_to(path: Path) -> logging.Handler:
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return handler


def run(settings: Settings, spark=None, landing_dir: str | None = None,
        export_file: str | None = None) -> dict:
    """Run one round. Returns a summary {table: rows}.

    landing_dir  where this run's files go (default: the round's Volume folder)
    export_file  load this already-downloaded export instead of calling Kobo
                 (for re-running a landed file, and for tests)
    """
    now = datetime.now(timezone.utc)
    info = RunInfo(
        run_id=now.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6],
        ingested_at=now.strftime("%Y-%m-%d %H:%M:%S"),
        source_asset=settings.kobo_asset_uid,
        pipeline_version=settings.pipeline_version,
    )
    out_dir = Path(landing_dir or settings.landing_dir) / (
        now.strftime("%Y%m%dT%H%M%SZ") + ("_dryrun" if settings.dry_run else ""))
    out_dir.mkdir(parents=True, exist_ok=True)
    handler = _log_to(out_dir / "run.log")
    try:
        logger.info("=" * 60)
        logger.info(f"Pharmacy {settings.round} | run {info.run_id} | catalog {settings.catalog} | "
                    f"dry_run={settings.dry_run} | {info.pipeline_version}")

        # 1-2. Download and land the export unchanged; bronze reads the landed file
        landed = out_dir / "kobo_export.xlsx"
        if export_file:
            landed.write_bytes(Path(export_file).read_bytes())
            logger.info(f"Using export file {export_file}")
        else:
            landed.write_bytes(Kobo(settings).download())
        logger.info(f"Export landed at {landed}")
        sheets = read_export(landed.read_bytes())

        # 3. Build and check
        built = build(sheets, info, settings.cycle, settings.blank_status_is_approved)
        summary = {f"{t.schema}.{t.name}": len(t.df) for t in built.tables}
        for name, rows in summary.items():
            logger.info(f"  {name:<45} {rows:>7} rows")
        if not built.issues.empty:
            built.issues.to_csv(out_dir / "issues.csv", index=False)
            # At most LOG_PER_CHECK lines per table and check; the rest are in issues.csv
            for (layer, table, check), group in built.issues.groupby(
                    ["layer", "table_name", "check_type"], sort=False):
                for _, i in group.head(LOG_PER_CHECK).iterrows():
                    level = logging.ERROR if i["blocking"] == "true" else logging.WARNING
                    logger.log(level, f"  [{layer}.{table}] {check}: {i['issue']}"
                                      + (f" (key {i['row_key']})" if i["row_key"] else ""))
                if len(group) > LOG_PER_CHECK:
                    logger.warning(f"  [{layer}.{table}] {check}: … and {len(group) - LOG_PER_CHECK} more "
                                   f"(all {len(group)} in issues.csv)")

        # 4. Blocking issues stop the run
        if not built.blocking.empty:
            if not settings.dry_run and spark is not None:
                from .load import Loader
                Loader(spark, settings.catalog).write_issues(built.issues)
            raise ValidationFailed(
                f"{len(built.blocking)} blocking issue(s); nothing was loaded. "
                f"See {out_dir / 'issues.csv'}")

        # 5. Load
        if settings.dry_run:
            logger.info("DRY RUN — every table built and checked; nothing written to the catalog")
        else:
            if spark is None:
                raise RuntimeError("Loading needs Databricks (a Spark session); use dry_run on a laptop")
            from .load import Loader
            loader = Loader(spark, settings.catalog)
            loader.load(built.tables)
            if not built.issues.empty:
                loader.write_issues(built.issues)
            logger.info(f"Loaded run {info.run_id}")
        return summary
    finally:
        logger.info(f"Run files: {out_dir}")
        logging.getLogger().removeHandler(handler)
        handler.close()
