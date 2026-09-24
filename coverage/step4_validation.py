"""
step4_validation.py — Completeness & standardization checks.

Rule engine handles all rule patterns found in the template:
  1.  X must not be blank
  2.  X must not be blank and must not have integer entries
  3.  If X = val then Y[, Z...] must not be blank
  4.  If X = val then Y[, Z...] should/must be blank
  5.  If X = val then Y[, Z...] must not be blank else X = val2 then Y must not be blank
  6.  Y must not be blank if X = val [or X = val2 ...]
  7.  X > 0 then Y[, Z...] must not be blank
  8.  X = 0 then Y[, Z...] must not be blank
  9.  X = 1 then Y[, Z...] must not be blank
  10. Y must be blank if X = val
  11. Y must be blank except if X = val
  12. X must not be blank if Y is not blank / has a response / has an entry

Standardization:
  Columns listed in Standardization sheet: 0 -> 'no', 1 -> 'yes'
  Any other value is flagged.
"""

import logging
import re
import pandas as pd
from config import OUTPUT_DIR, STEP4_FILENAME

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_blank(val) -> bool:
    return str(val).strip().lower() in ("", "nan", "none", "na")

def _is_not_blank(val) -> bool:
    return not _is_blank(val)

def _val_eq(actual, expected) -> bool:
    return str(actual).strip().strip('"').lower() == str(expected).strip().strip('"').lower()

def _val_gt(actual, threshold) -> bool:
    try:
        return float(str(actual).strip()) > threshold
    except (ValueError, TypeError):
        return False

def _val_eq_num(actual, num) -> bool:
    try:
        return float(str(actual).strip()) == num
    except (ValueError, TypeError):
        return False

def _parse_cols(raw: str) -> list[str]:
    """Parse a comma-separated list of column names, stripping spaces and quotes."""
    return [c.strip().strip('"').strip("'") for c in re.split(r",\s*", raw) if c.strip()]

def _is_integer_only(val) -> bool:
    return bool(re.fullmatch(r"\d+", str(val).strip()))

def _parse_or_conditions(cond_str: str) -> list[tuple[str, str]]:
    """
    Parse 'X = val or X = val2 or Y = val3' into [(col, val), ...]
    Handles both 'or' and 'and' as separators for multi-value conditions.
    """
    parts = re.split(r"\s+or\s+|\s+and\s+", cond_str, flags=re.I)
    result = []
    for part in parts:
        m = re.search(r"([\w/]+)\s*=\s*['\"]?([\w_]+)['\"]?", part)
        if m:
            result.append((m.group(1).strip(), m.group(2).strip()))
    return result


# ── Rule parser ───────────────────────────────────────────────────────────────

def _parse_rule(rule_text: str):
    """
    Returns a callable(row) -> list[str of issues]
    """
    r = rule_text.strip()

    # ── Pattern: else clause (split into two separate rules) ─────────────────
    # "If X=val then Y must not be blank else X=val2 then Z must not be blank"
    else_match = re.split(r"\s+else\s+", r, flags=re.I)
    if len(else_match) > 1:
        sub_rules = [_parse_rule(part) for part in else_match]
        def check_else(row, sub_rules=sub_rules):
            issues = []
            for fn in sub_rules:
                issues.extend(fn(row))
            return issues
        return check_else

    # ── Pattern: multiple sentences — split on '. If' ────────────────────────
    sentences = re.split(r"\.\s+(?=If\s)", r, flags=re.I)
    if len(sentences) > 1:
        sub_rules = [_parse_rule(s) for s in sentences]
        def check_multi(row, sub_rules=sub_rules):
            issues = []
            for fn in sub_rules:
                issues.extend(fn(row))
            return issues
        return check_multi

    # ── Pattern 1: simple must not be blank (+ optional integer check) ────────
    # "X, Y, Z must not be blank [and must not have integer entries]"
    m = re.match(
        r"^([\w,\s/]+?)\s+must not be blank"
        r"(\s+and must not have integer entries.*)?$", r, re.I
    )
    if m and not re.search(r"\bif\b", r, re.I):
        cols = _parse_cols(m.group(1))
        check_int = bool(m.group(2))
        def check_not_blank(row, cols=cols, check_int=check_int, rule=r):
            issues = []
            for col in cols:
                if col not in row:
                    continue
                if _is_blank(row[col]):
                    issues.append(f"[{col}] must not be blank")
                elif check_int and _is_integer_only(row[col]):
                    issues.append(f"[{col}] must be text, not integer (got: '{row[col]}')")
            return issues
        return check_not_blank

    # ── Pattern 2: If X = val then Y[,Z] must not be blank ───────────────────
    m = re.match(
        r'^[Ii]f\s+([\w/]+)\s*=\s*["\']?([\w_]+)["\']?\s+then\s+'
        r'([\w,\s/]+?)\s+must not be blank', r, re.I
    )
    if m:
        cond_col, cond_val, targets_raw = m.group(1), m.group(2), m.group(3)
        target_cols = _parse_cols(targets_raw)
        def check_if_then_not_blank(row, cond_col=cond_col, cond_val=cond_val,
                                    target_cols=target_cols, rule=r):
            if not _val_eq(row.get(cond_col, ""), cond_val):
                return []
            return [
                f"[{col}] must not be blank when {cond_col}='{cond_val}'"
                for col in target_cols
                if col in row and _is_blank(row[col])
            ]
        return check_if_then_not_blank

    # ── Pattern 3: If X = val then Y[,Z] should/must be blank ────────────────
    m = re.match(
        r'^[Ii]f\s+([\w/]+)\s*=\s*["\']?([\w_]+)["\']?\s+then\s+'
        r'([\w,\s/]+?)\s+(?:should|must) be blank', r, re.I
    )
    if m:
        cond_col, cond_val, targets_raw = m.group(1), m.group(2), m.group(3)
        target_cols = _parse_cols(targets_raw)
        def check_if_then_blank(row, cond_col=cond_col, cond_val=cond_val,
                                target_cols=target_cols, rule=r):
            if not _val_eq(row.get(cond_col, ""), cond_val):
                return []
            return [
                f"[{col}] must be blank when {cond_col}='{cond_val}'"
                for col in target_cols
                if col in row and _is_not_blank(row[col])
            ]
        return check_if_then_blank

    # ── Pattern 4: Y must not be blank if X = val [or X = val2] ─────────────
    m = re.match(
        r'^([\w,\s/]+?)\s+must not be blank\s+if\s+(.+)$', r, re.I
    )
    if m:
        targets_raw, cond_str = m.group(1), m.group(2)
        target_cols = _parse_cols(targets_raw)
        conditions = _parse_or_conditions(cond_str)
        def check_must_not_blank_if(row, target_cols=target_cols,
                                    conditions=conditions, rule=r):
            triggered = any(_val_eq(row.get(col, ""), val) for col, val in conditions)
            if not triggered:
                return []
            return [
                f"[{col}] must not be blank"
                for col in target_cols
                if col in row and _is_blank(row[col])
            ]
        return check_must_not_blank_if

    # ── Pattern 5: X > 0 then Y[,Z] must not be blank ────────────────────────
    m = re.match(
        r'^([\w/]+)\s*>\s*0\s+then\s+([\w,\s/]+?)\s+must not be blank', r, re.I
    )
    if m:
        cond_col, targets_raw = m.group(1), m.group(2)
        target_cols = _parse_cols(targets_raw)
        def check_gt_zero(row, cond_col=cond_col, target_cols=target_cols, rule=r):
            if not _val_gt(row.get(cond_col, ""), 0):
                return []
            return [
                f"[{col}] must not be blank when {cond_col}>0"
                for col in target_cols
                if col in row and _is_blank(row[col])
            ]
        return check_gt_zero

    # ── Pattern 6: X = 0 then Y[,Z] must not be blank ────────────────────────
    m = re.match(
        r'^([\w/]+)\s*=\s*0\s+then\s+([\w,\s/]+?)\s+must not be blank', r, re.I
    )
    if m:
        cond_col, targets_raw = m.group(1), m.group(2)
        target_cols = _parse_cols(targets_raw)
        def check_eq_zero(row, cond_col=cond_col, target_cols=target_cols, rule=r):
            if not _val_eq_num(row.get(cond_col, ""), 0):
                return []
            return [
                f"[{col}] must not be blank when {cond_col}=0"
                for col in target_cols
                if col in row and _is_blank(row[col])
            ]
        return check_eq_zero

    # ── Pattern 7: X = 1 then Y must not be blank ────────────────────────────
    m = re.match(
        r'^([\w/]+)\s*=\s*1\s+then\s+([\w,\s/]+?)\s+must not be blank', r, re.I
    )
    if m:
        cond_col, targets_raw = m.group(1), m.group(2)
        target_cols = _parse_cols(targets_raw)
        def check_eq_one(row, cond_col=cond_col, target_cols=target_cols, rule=r):
            if not _val_eq_num(row.get(cond_col, ""), 1):
                return []
            return [
                f"[{col}] must not be blank when {cond_col}=1"
                for col in target_cols
                if col in row and _is_blank(row[col])
            ]
        return check_eq_one

    # ── Pattern 8: Y must be blank if X = val ────────────────────────────────
    m = re.match(
        r'^([\w,\s/]+?)\s+(?:should|must) be blank\s+if\s+([\w/]+)\s*=\s*["\']?([\w_]+)["\']?',
        r, re.I
    )
    if m:
        targets_raw, cond_col, cond_val = m.group(1), m.group(2), m.group(3)
        target_cols = _parse_cols(targets_raw)
        def check_must_blank_if(row, target_cols=target_cols,
                                cond_col=cond_col, cond_val=cond_val, rule=r):
            if not _val_eq(row.get(cond_col, ""), cond_val):
                return []
            return [
                f"[{col}] must be blank when {cond_col}='{cond_val}'"
                for col in target_cols
                if col in row and _is_not_blank(row[col])
            ]
        return check_must_blank_if

    # ── Pattern 9: Y must be blank except if X = val ─────────────────────────
    m = re.match(
        r'^([\w,\s/]+?)\s+must be blank\s+except\s+if\s+([\w/]+)\s*=\s*["\']?([\w_]+)["\']?',
        r, re.I
    )
    if m:
        targets_raw, cond_col, cond_val = m.group(1), m.group(2), m.group(3)
        target_cols = _parse_cols(targets_raw)
        def check_blank_except(row, target_cols=target_cols,
                               cond_col=cond_col, cond_val=cond_val, rule=r):
            # Only flag if condition is NOT met AND field is not blank
            if _val_eq(row.get(cond_col, ""), cond_val):
                return []
            return [
                f"[{col}] must be blank (only allowed when {cond_col}='{cond_val}')"
                for col in target_cols
                if col in row and _is_not_blank(row[col])
            ]
        return check_blank_except

    # ── Pattern 10: X must not be blank if Y is not blank / has a response ───
    m = re.match(
        r'^([\w,\s/]+?)\s+must not be blank\s+if\s+([\w/]+)\s+'
        r'(?:is not blank|has a response|has an entry)', r, re.I
    )
    if m:
        targets_raw, cond_col = m.group(1), m.group(2)
        target_cols = _parse_cols(targets_raw)
        def check_not_blank_if_other_not_blank(row, target_cols=target_cols,
                                               cond_col=cond_col, rule=r):
            if _is_blank(row.get(cond_col, "")):
                return []
            return [
                f"[{col}] must not be blank when {cond_col} has a value"
                for col in target_cols
                if col in row and _is_blank(row[col])
            ]
        return check_not_blank_if_other_not_blank

    # ── Fallback: log and skip ────────────────────────────────────────────────
    logger.debug(f"  Rule not parsed (skipped): {r[:100]}")
    return lambda row: []


# ── Standardization ───────────────────────────────────────────────────────────

def apply_standardization(df: pd.DataFrame, std_cols: list[str],
                          sheet_label: str) -> tuple[pd.DataFrame, list[dict]]:
    df = df.copy()
    issues = []
    valid_values = {"yes", "no", "0", "1", "0.0", "1.0", "", "nan", "none"}

    for col in std_cols:
        if col not in df.columns:
            continue
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace({"0": "no", "1": "yes", "0.0": "no", "1.0": "yes"})

        for idx, val in df[col].items():
            if val.lower() not in valid_values and val.lower() not in {"yes", "no"}:
                issues.append({
                    "sheet":      sheet_label,
                    "row_index":  idx,
                    "check_type": "standardization",
                    "column":     col,
                    "value":      val,
                    "issue":      f"[{col}] unexpected value '{val}' (expected 0/1/yes/no)",
                })

    return df, issues


# ── Main validation function ──────────────────────────────────────────────────

def run_step4(
    sheets: dict[str, pd.DataFrame],
    completeness_rules: dict[str, list[str]],
    std_cols: dict[str, list[str]],
) -> dict[str, pd.DataFrame]:
    logger.info("=" * 50)
    logger.info("STEP 4 — Completeness & standardization validation")

    all_issues   = {}
    clean_sheets = {}

    for sheet_name, df in sheets.items():
        logger.info(f"  Validating '{sheet_name}' ({len(df)} rows)...")
        issues = []

        # Standardization first
        std_list = std_cols.get(sheet_name, [])
        df, std_issues = apply_standardization(df, std_list, sheet_name)
        issues.extend(std_issues)

        # Compile completeness rules
        rules_raw = completeness_rules.get(sheet_name, [])
        compiled  = [_parse_rule(r) for r in rules_raw]
        logger.info(f"  Applying {len(compiled)} completeness rules to {len(df)} rows")

        for row_idx, row in df.iterrows():
            for rule_fn, rule_text in zip(compiled, rules_raw):
                try:
                    row_issues = rule_fn(row)
                except Exception as e:
                    logger.debug(f"  Rule error on row {row_idx}: {e} | rule: {rule_text[:60]}")
                    row_issues = []

                for msg in row_issues:
                    uid = (
                        row.get("uuid") or row.get("_uuid") or
                        row.get("concatenated_id") or str(row_idx)
                    )
                    issues.append({
                        "sheet":      sheet_name,
                        "row_index":  row_idx,
                        "row_id":     uid,
                        "check_type": "completeness",
                        "rule":       rule_text,
                        "issue":      msg,
                    })

        all_issues[sheet_name] = issues
        clean_sheets[sheet_name] = df

        if issues:
            logger.warning(f"  '{sheet_name}': {len(issues)} issues found")
        else:
            logger.info(f"  '{sheet_name}': all checks passed")

    # Build report
    total_issues = sum(len(v) for v in all_issues.values())
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / STEP4_FILENAME

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, issues in all_issues.items():
            if issues:
                pd.DataFrame(issues).to_excel(writer, sheet_name=sheet_name, index=False)
            else:
                pd.DataFrame([{"result": f"All checks passed for {sheet_name}"}]).to_excel(
                    writer, sheet_name=sheet_name, index=False
                )

    logger.info(f"Validation report saved: {output_path}")

    if total_issues > 0:
        logger.error(
            f"Validation FAILED — {total_issues} issues across "
            f"{sum(1 for v in all_issues.values() if v)} sheet(s). "
            f"See report: '{STEP4_FILENAME}'"
        )
        raise ValidationError(
            f"{total_issues} validation issues found. "
            f"Review '{STEP4_FILENAME}' before re-running."
        )

    logger.info("Step 4 complete — all checks passed")
    return clean_sheets
