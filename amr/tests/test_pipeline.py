"""
Offline tests for the AMR pipeline: a made-up export with the real AMR column
list (map/amr/zamfara_export_columns.txt), no Kobo and no Databricks.

Run from the repo root:  python -m unittest discover -s amr/tests -v
"""

import io
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

AMR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AMR_DIR))

import architecture as arch  # noqa: E402
from pipeline.run import ValidationFailed, run  # noqa: E402
from pipeline.settings import APPROVED, MAP_DIR, Settings  # noqa: E402
from pipeline.transform import RunInfo, build  # noqa: E402

RUN = RunInfo("20261026T000000Z_test", "2026-10-26 00:00:00", "aks5TQaYbfgGvhCigjGAvp", "git-test")


def export_columns() -> dict[str, list[str]]:
    sheets, cur = {}, None
    for line in (MAP_DIR / "zamfara_export_columns.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            cur = line[1:-1]
            sheets[cur] = []
        else:
            sheets[cur].append(line)
    return sheets


def fake_export(child_mother="M1") -> dict[str, pd.DataFrame]:
    """Two households (A approved, B not), one mother each, one child each."""
    cols = export_columns()

    def frame(sheet, rows):
        df = pd.DataFrame([{c: "" for c in cols[sheet]} for _ in rows])
        for i, values in enumerate(rows):
            for k, v in values.items():
                df.at[i, k] = v
        return df

    hh = frame("household", [
        {"_uuid": "ua", "meta/rootUuid": "uuid:ra", "_index": "1", "_id": "101",
         "_validation_status": APPROVED, "state_name": "Zamfara", "lga_name": "Gusau",
         "ward_name": "W1", "community_label": "C1", "cycle": "1", "username": "enum one",
         "phonenumber": "08031234567", "_gps_capture_latitude": "12.1", "_gps_capture_longitude": "6.6",
         "q_western/quranic": "1", "q_western/western": "0", "start": "2026-03-01T09:15:00.000+01:00"},
        {"_uuid": "ub", "meta/rootUuid": "", "_index": "2", "_id": "102",
         "_validation_status": "validation_status_not_approved", "state_name": "Zamfara"},
    ])
    mo = frame("mother", [
        {"_submission__uuid": "ua", "_submission_meta/rootUuid": "uuid:ra", "unique_code1": "M1",
         "_index": "1", "_parent_index": "1", "_submission__id": "101", "mother_name_proper": "Amina"},
        {"_submission__uuid": "ub", "_submission_meta/rootUuid": "", "unique_code1": "M2",
         "_index": "2", "_parent_index": "2", "_submission__id": "102"},
    ])
    ch = frame("child", [
        {"_submission__uuid": "ua", "_submission_meta/rootUuid": "uuid:ra", "child_id": "C1",
         "motherid": child_mother, "_index": "1", "_parent_index": "1", "_submission__id": "101",
         "current_feeding_mode/breastfeeding": "1", "current_feeding_mode/formula": "0"},
        {"_submission__uuid": "ub", "_submission_meta/rootUuid": "", "child_id": "C2",
         "motherid": "M2", "_index": "2", "_parent_index": "2", "_submission__id": "102"},
    ])
    return {"SARMAAN II BASELINE ZAMFARA AMR": hh, "mother_information": mo, "child_info": ch}


def tables(built):
    return {f"{t.schema}.{t.name}": t for t in built.tables}


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.built = build(fake_export(), RUN)
        self.t = tables(self.built)

    def test_no_blocking_issues(self):
        self.assertTrue(self.built.blocking.empty, self.built.blocking.to_string())

    def test_bronze_keeps_every_row_and_column_with_lineage(self):
        b = self.t["bronze.amr_household"]
        self.assertEqual(len(b.df), 2)
        self.assertTrue(b.append)
        self.assertIn("_gps_capture_latitude", b.df.columns)
        for col, _ in arch.BRONZE_METADATA:
            self.assertIn(col, b.df.columns)
        self.assertEqual(b.df["_run_id"].unique().tolist(), [RUN.run_id])
        # blank rootUuid filled the way Kobo does on first submission
        self.assertEqual(b.df["meta_rootuuid"].tolist(), ["uuid:ra", "uuid:ub"])
        self.assertEqual(self.t["bronze.amr_mother"].df["_submission_meta_rootuuid"].tolist(),
                         ["uuid:ra", "uuid:ub"])

    def test_silver_has_every_submission(self):
        for s in ("household", "mother", "child"):
            self.assertEqual(len(self.t[f"silver.amr_{s}"].df), 2)

    def test_gold_is_approved_only(self):
        for s in ("household", "mother", "child"):
            self.assertEqual(self.t[f"gold.amr_{s}"].df[arch.ROOT_UUID].tolist(), ["uuid:ra"])

    def test_identifiers_only_in_restricted(self):
        for s, ids in arch.IDENTIFIERS.items():
            gold = self.t[f"gold.amr_{s}"].df.columns
            restricted = self.t[f"restricted.{arch.restricted_table(s)}"]
            self.assertFalse(set(ids) & set(gold), s)
            self.assertTrue(set(ids) <= set(restricted.df.columns), s)
            self.assertEqual(restricted.pk, arch.KEYS[s][0])
        r = self.t["restricted.amr_household_identifiers"]
        self.assertEqual(r.types["phone_number"], "STRING")
        self.assertEqual(r.df.loc[r.df.index[0], "enumerator_phone_number"], "08031234567")

    def test_keys_match_the_architecture(self):
        for s in ("household", "mother", "child"):
            for layer in ("silver", "gold"):
                t = self.t[f"{layer}.amr_{s}"]
                self.assertEqual((t.pk, t.fk), arch.KEYS[s])

    def test_values(self):
        g = self.t["gold.amr_household"].df.iloc[0]
        self.assertEqual(g["education_type_quranic"], "Yes")
        self.assertEqual(g["education_type_western"], "No")
        self.assertEqual(g["concatenated_id"], "ua_1")
        self.assertEqual(g["start_time"], "2026-03-01 09:15:00.000")   # local time kept
        c = self.t["gold.amr_child"].df.iloc[0]
        self.assertEqual(c["current_feeding_breastfeeding"], "Yes")
        self.assertEqual((c["state"], c["lga"], c["cycle"]), ("Zamfara", "Gusau", "1"))
        self.assertEqual(c["mother_code"], "M1")
        self.assertEqual(self.t["gold.amr_mother"].df.iloc[0]["lga"], "Gusau")

    def test_columns_without_a_question_are_kept_as_null(self):
        g = self.t["gold.amr_mother"].df
        self.assertIn("adverse_events", g.columns)
        self.assertTrue(g["adverse_events"].isna().all())


class BlockingTests(unittest.TestCase):
    def test_child_without_its_mother_blocks(self):
        built = build(fake_export(child_mother="M9"), RUN)
        checks = set(built.blocking["check_type"])
        self.assertIn("no_parent", checks)

    def test_repeated_mother_code_blocks(self):
        export = fake_export()
        mo = export["mother_information"]
        export["mother_information"] = pd.concat([mo, mo.iloc[[0]]], ignore_index=True)
        built = build(export, RUN)
        self.assertIn("duplicate_key", set(built.blocking["check_type"]))


class RunTests(unittest.TestCase):
    def _export_file(self, folder, export):
        path = Path(folder) / "export.xlsx"
        with pd.ExcelWriter(path) as xl:
            for name, df in export.items():
                df.to_excel(xl, sheet_name=name[:31], index=False)
        return path

    def _settings(self):
        return Settings("zamfara_c1", "eha_ghi_sarmaan_dev", True, "https://kf.kobotoolbox.org",
                        "aks5TQaYbfgGvhCigjGAvp", "", "token", 1, "git-test")

    def test_dry_run_lands_the_export_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = run(self._settings(), landing_dir=tmp,
                          export_file=str(self._export_file(tmp, fake_export())))
            self.assertEqual(summary["gold.amr_household"], 1)
            self.assertEqual(summary["bronze.amr_child"], 2)
            [folder] = [p for p in Path(tmp).iterdir() if p.is_dir()]
            self.assertTrue(folder.name.endswith("_dryrun"))
            self.assertTrue((folder / "kobo_export.xlsx").exists())
            self.assertTrue((folder / "run.log").exists())

    def test_blocking_issue_stops_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValidationFailed):
                run(self._settings(), landing_dir=tmp,
                    export_file=str(self._export_file(tmp, fake_export(child_mother="M9"))))
            [folder] = [p for p in Path(tmp).iterdir() if p.is_dir()]
            issues = pd.read_csv(folder / "issues.csv", dtype=str)
            self.assertIn("no_parent", set(issues["check_type"]))


if __name__ == "__main__":
    unittest.main()
