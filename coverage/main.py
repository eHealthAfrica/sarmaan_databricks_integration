"""
main.py — Pipeline orchestrator.

Run:
    python main.py             # full pipeline (all steps)
    python main.py --step 1    # run only step 1
    python main.py --step 4 5  # run steps 4 and 5

Steps:
    1 — Raw XML export          -> outputs/01_raw_xml_export.xlsx
    2 — Rename columns          -> outputs/SARMAAN_II_COVERAGE_{STATE}_{CYCLE}_RAW.xlsx
    3 — Merge + partner output  -> outputs/SARMAAN_II_COVERAGE_{STATE}_{CYCLE}_CLEANED.xlsx
    4 — Validation              -> outputs/04_validation_report.xlsx (stops on failure)
    5 — DB schema mapping       -> outputs/05_db_ready.xlsx
    6 — Sync to PostgreSQL      -> raw_data.coverage_* and sarmaan2data.coverage_*
"""

import argparse
import logging
import sys
import time
from datetime import datetime

import pandas as pd

from config import LOG_DIR, OUTPUT_DIR, STEP1_FILENAME, STEP5_FILENAME

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
log_filename = LOG_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_filename, encoding="utf-8"),
    ],
)
import io
for handler in logging.root.handlers:
    if isinstance(handler, logging.StreamHandler) and \
       not isinstance(handler, logging.FileHandler):
        handler.stream = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8",
            errors="replace", line_buffering=True
        )

logger = logging.getLogger("main")


def run(steps: list[int] | None = None):
    run_all = not steps
    def should_run(n): return run_all or n in steps

    start = time.time()
    logger.info("=" * 60)
    logger.info(f"Pipeline started | steps={steps or 'all'}")
    logger.info("=" * 60)

    # ── Load all mappings once ────────────────────────────────────────────────
    from mappings import (
        load_step1_maps, load_step2_maps, load_step3_maps, load_step5_maps,
        load_completeness_rules, load_standardization_cols,
    )
    logger.info("Loading mapping files...")
    step1_maps         = load_step1_maps()
    step2_maps         = load_step2_maps()
    step3_maps         = load_step3_maps()
    step5_maps         = load_step5_maps()
    completeness_rules = load_completeness_rules()
    std_cols           = load_standardization_cols()
    logger.info("All mappings loaded")

    # Shared state
    raw_sheets   = None   # preprocessed raw Kobo data
    step1_sheets = None   # Step 1 output (for raw DB sync)
    step2_sheets = None   # Step 2 output
    step3_sheets = None   # Step 3 output
    step4_sheets = None   # Step 4 output (validated)
    step5_sheets = None   # Step 5 output (for clean DB sync)

    # ── Fetch + preprocess ────────────────────────────────────────────────────
    if should_run(1) or should_run(2) or should_run(3) or should_run(5):
        from extractor import fetch_kobo_data
        from preprocessor import apply_all

        logger.info("Fetching data from KoboToolbox...")
        kobo_sheets, main_sheet_name = fetch_kobo_data()

        known_repeats = ["child_info", "net_repeat", "child_infoo"]
        normalised = {"main": kobo_sheets[main_sheet_name]}
        for key in known_repeats:
            if key in kobo_sheets:
                normalised[key] = kobo_sheets[key]
            else:
                logger.warning(f"Expected sheet '{key}' not found in Kobo data")

        logger.info("Applying preprocessor...")
        raw_sheets = apply_all(normalised)
        logger.info("Preprocessing complete")

    # ── Step 1: Raw XML export ────────────────────────────────────────────────
    if should_run(1):
        from step1_raw_export import run_step1
        step1_sheets = run_step1(raw_sheets)

    # ── Step 2: Rename columns ────────────────────────────────────────────────
    if should_run(2):
        from step2_rename_columns import run_step2
        step2_sheets = run_step2(raw_sheets, step2_maps)

    # ── Step 3: Merge + partner output ───────────────────────────────────────
    if should_run(3):
        from step3_partner_output import run_step3
        step3_sheets = run_step3(raw_sheets, step3_maps)

    # ── Step 4: Validation ────────────────────────────────────────────────────
    if should_run(4):
        from step4_validation import run_step4, ValidationError
        if step3_sheets is None:
            step3_sheets = _load_local(3)
        try:
            step4_sheets = run_step4(step3_sheets, completeness_rules, std_cols)
        except ValidationError as e:
            logger.error(f"Pipeline stopped at Step 4: {e}")
            sys.exit(1)

    # ── Step 5: DB schema mapping ─────────────────────────────────────────────
    if should_run(5):
        from step5_db_schema import run_step5
        if step2_sheets is None:
            step2_sheets = _load_local(
                2, sheets=["Household Code", "Child_Info", "Net_repeat", "Child_Infoo"]
            )
        step5_sheets = run_step5(step2_sheets, step5_maps, std_cols)

    # ── Step 6: Sync to PostgreSQL ────────────────────────────────────────────
    if should_run(6):
        from step6_db_loader import run_step6

        # Load from memory if available, otherwise from local files
        if step1_sheets is None:
            step1_sheets = _load_local(
                1, sheets=["main_sheet", "child_info", "net_repeat", "child_infoo"]
            )
        if step5_sheets is None:
            step5_sheets = _load_local(
                5, sheets=["Household Code", "Child_Info", "Net_repeat", "Child_Infoo"]
            )

        # Build map dicts keyed by sheet name (as they appear in the output files)
        raw_maps = {
            "main_sheet":  step1_maps.get("main", {}),
            "child_info":  step1_maps.get("child_info", {}),
            "net_repeat":  step1_maps.get("net_repeat", {}),
            "child_infoo": step1_maps.get("child_infoo", {}),
        }
        clean_maps = {
            "Household Code": step5_maps.get("household_info", {}),
            "Child_Info":     step5_maps.get("child_info", {}),
            "Net_repeat":     step5_maps.get("net_repeat", {}),
            "Child_Infoo":    step5_maps.get("child_infoo", {}),
        }

        run_step6(
            raw_sheets=step1_sheets,
            clean_sheets=step5_sheets,
            raw_maps=raw_maps,
            clean_maps=clean_maps,
        )

    elapsed = time.time() - start
    logger.info("=" * 60)
    logger.info(f"Pipeline finished in {elapsed:.1f}s")
    logger.info("=" * 60)


def _load_local(
    step_num: int,
    sheets: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Load a previously saved local Excel output for a given step."""
    filenames = {
        1: STEP1_FILENAME,
        5: STEP5_FILENAME,
    }
    # For steps 2 and 3 use dynamic naming — find most recent file
    if step_num in (2, 3):
        suffix = "RAW" if step_num == 2 else "CLEANED"
        matches = list(OUTPUT_DIR.glob(f"SARMAAN_II_COVERAGE_*_{suffix}.xlsx"))
        if not matches:
            raise FileNotFoundError(
                f"No Step {step_num} output found in {OUTPUT_DIR}. Run step {step_num} first."
            )
        # most recently written file - sorting by name would pick the
        # alphabetically last state (e.g. KANO over a newer BAUCHI run)
        path = max(matches, key=lambda p: p.stat().st_mtime)
    elif step_num in filenames:
        path = OUTPUT_DIR / filenames[step_num]
    else:
        raise ValueError(f"Cannot load local output for step {step_num}")

    if not path.exists():
        raise FileNotFoundError(
            f"Step {step_num} output not found at {path}. Run step {step_num} first."
        )
    logger.info(f"Loading local step {step_num} output: {path.name}")
    return pd.read_excel(path, sheet_name=sheets, dtype=str)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KoboToolbox data pipeline")
    parser.add_argument(
        "--step", nargs="+", type=int,
        help="Run specific steps only, e.g. --step 1 or --step 5 6",
    )
    args = parser.parse_args()
    run(steps=args.step)
