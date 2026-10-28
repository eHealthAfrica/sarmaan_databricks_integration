"""
Offline tests for the Mortality pipeline: a made-up export with the real
Mortality column list (map/mortality/export_columns.txt), no Kobo and no
Databricks.

Run from the repo root:  python -m unittest discover -s mortality/tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

MORTALITY_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MORTALITY_DIR))

import architecture as arch  # noqa: E402
from pipeline.run import ValidationFailed, run  # noqa: E402
from pipeline.settings import APPROVED, MAP_DIR, Settings  # noqa: E402
from pipeline.transform import RunInfo, build  # noqa: E402

RUN = RunInfo("20261028T000000Z_test", "2026-10-28 00:00:00", "aMaahuu5VANkY6o4QyQ8uC", "git-test")


def export_columns() -> dict[str, list[str]]:
    sheets, cur = {}, None
    for line in (MAP_DIR / "export_columns.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            cur = line[1:-1]
            sheets[cur] = []
        else:
            sheets[cur].append(line)
    # The real female sheet has no rootUuid column: the pipeline fills it
    sheets["female"].remove("_submission_meta/rootUuid")
    return sheets


def fake_export(preg_mother="B-1_01", second_woman_code="B-2_01") -> dict[str, pd.DataFrame]:
    """Two households (A approved, B not), one woman each, one pregnancy each."""
    cols = export_columns()

    def frame(sheet, rows):
        df = pd.DataFrame([{c: "" for c in cols[sheet]} for _ in rows])
        for i, values in enumerate(rows):
            for k, v in values.items():
                df.at[i, k] = v
        return df

    hh = frame("household", [
        {"_uuid": "ua", "meta/rootUuid": "uuid:ra", "_index": "1", "_id": "101",
         "_validation_status": APPROVED, "states": "", "lgas": "potiskum", "ward": "Bolewa_A",
         "community_confirm": "Adaya_Pri_Sch", "hh_category": "1100", "cycle": "cycle_1",
         "unique_code": "B-1", "username": "enum one", "phonenumber": "08031234567",
         "phone_no": "08039999999", "household_headname": "Head A", "latitude": "11.7", "longitude": "11.0",
         "starttime": "2026-03-01T09:15:00.000+01:00", "_submission_time": "2026-03-01 08:40:00",
         "household_head_consent": "yes", "water_source": "borehole", "q_western/quranic": "1.0"},
        {"_uuid": "ub", "meta/rootUuid": "", "_index": "2", "_id": "102",
         "_validation_status": "validation_status_not_approved", "lgas": "", "lga_confirm": "fika",
         "unique_code": "B-2"},
    ])
    fe = frame("female", [
        {"_submission__uuid": "ua", "_index": "1", "_parent_index": "1", "_submission__id": "101",
         "household_id": "B-1", "mother_id": "B-1_01", "female_position": "1.0", "female_name": "Amina",
         "q_women_western/quranic": "1.0", "q_women_western/western": "0.0", "birth_month": "3"},
        {"_submission__uuid": "ub", "_index": "2", "_parent_index": "2", "_submission__id": "102",
         "household_id": "B-2", "mother_id": second_woman_code, "female_position": "1"},
    ])
    pr = frame("pregnancy", [
        {"_submission__uuid": "ua", "_submission_meta/rootUuid": "uuid:ra", "_index": "1", "_parent_index": "1",
         "_submission__id": "101", "householdid": "B-1", "motherid": preg_mother, "preg_id": "B-1_01_01",
         "c_id": "1.0", "q114_pregnancy_outcome": "alive", "q113_pregnancy_type": "2.0",
         "q116_child_name": "Child A", "q120iii_pregnancy_end_day": "99"},
        {"_submission__uuid": "ub", "_submission_meta/rootUuid": "", "_index": "2", "_parent_index": "2",
         "_submission__id": "102", "householdid": "B-2", "motherid": "B-2_01", "preg_id": "B-2_01_01"},
    ])
    return {"SARMAAN II MORTALITY YOBE": hh, "female": fe, "pregnancy_history": pr}


def tables(built):
    return {f"{t.schema}.{t.name}": t for t in built.tables}


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.built = build(fake_export(), RUN, default_state="Yobe")
        self.t = tables(self.built)

    def test_no_blocking_issues(self):
        self.assertTrue(self.built.blocking.empty, self.built.blocking.to_string())

    def test_bronze_keeps_every_row_with_lineage_and_fills_root(self):
        b = self.t["bronze.mortality_household"]
        self.assertTrue(b.append)
        self.assertEqual(len(b.df), 2)
        for col, _ in arch.BRONZE_METADATA:
            self.assertIn(col, b.df.columns)
        self.assertEqual(b.df["meta_rootuuid"].tolist(), ["uuid:ra", "uuid:ub"])
        # the female sheet has no rootUuid of its own: taken from the household
        self.assertEqual(self.t["bronze.mortality_female"].df["_submission_meta_rootuuid"].tolist(),
                         ["uuid:ra", "uuid:ub"])

    def test_silver_has_every_submission_in_postgres_order(self):
        for s, n in (("household", 83), ("female", 51), ("pregnancy", 70)):
            df = self.t[f"silver.mortality_{s}"].df
            self.assertEqual(len(df), 2)
            self.assertEqual(len(df.columns), n + 2)          # + root_uuid, _run_id
            self.assertEqual(df.columns[0], arch.ROOT_UUID)

    def test_gold_is_approved_only(self):
        for s in ("household", "female", "pregnancy"):
            self.assertEqual(self.t[f"gold.mortality_{s}"].df[arch.ROOT_UUID].tolist(), ["uuid:ra"])

    def test_identifiers_only_in_restricted(self):
        for s, ids in arch.IDENTIFIERS.items():
            gold = self.t[f"gold.mortality_{s}"].df.columns
            restricted = self.t[f"restricted.{arch.restricted_table(s)}"]
            self.assertFalse(set(ids) & set(gold), s)
            self.assertTrue(set(ids) <= set(restricted.df.columns), s)
        r = self.t["restricted.mortality_household_identifiers"].df.iloc[0]
        self.assertEqual(r["respondent_phone_number"], "8039999999")   # strip_leading_zero, as in Postgres

    def test_keys_match_the_architecture(self):
        for s in ("household", "female", "pregnancy"):
            for layer in ("silver", "gold"):
                t = self.t[f"{layer}.mortality_{s}"]
                self.assertEqual((t.pk, t.fk), arch.KEYS[s])

    def test_postgres_value_rules(self):
        h = self.t["gold.mortality_household"].df.iloc[0]
        self.assertEqual(h["state"], "Yobe")                      # blank -> round config
        self.assertEqual(h["lga"], "Potiskum")                    # simple_capitalize
        self.assertEqual(h["ward"], "Bolewa A")                   # underscore_to_space
        self.assertEqual(h["community"], "Adaya Pri Sch")
        self.assertEqual(h["household_no_category"], "001 - 100")
        self.assertEqual(h["household_head_consent"], "Yes")
        self.assertEqual(h["drinking_water_source"], "Borehole")
        self.assertEqual(h["education_type_quranic"], "Yes")
        self.assertEqual(h["start_time"], "2026-03-01 09:15:00.000")   # time Kobo recorded
        self.assertEqual(h["concatenated_id"], "ua_1")
        f = self.t["gold.mortality_female"].df.iloc[0]
        self.assertEqual((f["mother_code"], f["female_id"], f["birth_month"]), ("B-1_01", "1", "March"))
        self.assertEqual((f["school_level_quranic"], f["school_level_western"]), ("Yes", "No"))
        self.assertEqual((f["state"], f["lga"]), ("Yobe", "Potiskum"))   # from the household
        p = self.t["gold.mortality_pregnancy"].df.iloc[0]
        self.assertEqual((p["birth_form"], p["pregnancy_form"]), ("Born Alive", "Twins"))
        self.assertEqual(p["day_pregnancy_ended"], "Don't know")
        self.assertEqual(p["pregnancy_code"], "B-1_01_01")

    def test_lga_falls_back_to_confirm_field(self):
        s = self.t["silver.mortality_household"].df
        self.assertEqual(s.loc[s[arch.ROOT_UUID] == "uuid:ub", "lga"].iloc[0], "Fika")

    def test_columns_without_a_question_are_kept_as_null(self):
        g = self.t["gold.mortality_pregnancy"].df
        self.assertIn("pregnancy_report", g.columns)
        self.assertTrue(g["pregnancy_report"].isna().all())


class BlockingTests(unittest.TestCase):
    def test_pregnancy_without_its_woman_blocks(self):
        built = build(fake_export(preg_mother="B-1_09"), RUN, "Yobe")
        self.assertIn("no_parent", set(built.blocking["check_type"]))

    def test_repeated_woman_code_blocks(self):
        export = fake_export()
        fe = export["female"]
        export["female"] = pd.concat([fe, fe.iloc[[0]]], ignore_index=True)
        built = build(export, RUN, "Yobe")
        self.assertIn("duplicate_key", set(built.blocking["check_type"]))


class RunTests(unittest.TestCase):
    def _export_file(self, folder, export):
        path = Path(folder) / "export.xlsx"
        with pd.ExcelWriter(path) as xl:
            for name, df in export.items():
                df.to_excel(xl, sheet_name=name[:31], index=False)
        return path

    def _settings(self):
        return Settings(round="yobe_potiskum", catalog="eha_ghi_sarmaan_dev", dry_run=True,
                        kobo_base_url="https://kf.kobotoolbox.org", kobo_asset_uid="aMaahuu5VANkY6o4QyQ8uC",
                        kobo_export_settings_id="esVRqDjSZ6UdHozvskTbBga", kobo_token="token",
                        state="Yobe", export_wait_minutes=1, pipeline_version="git-test")

    def test_dry_run_lands_the_export_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = run(self._settings(), landing_dir=tmp,
                          export_file=str(self._export_file(tmp, fake_export())))
            self.assertEqual(summary["gold.mortality_household"], 1)
            self.assertEqual(summary["bronze.mortality_pregnancy"], 2)
            [folder] = [p for p in Path(tmp).iterdir() if p.is_dir()]
            self.assertTrue(folder.name.endswith("_dryrun"))
            self.assertTrue((folder / "kobo_export.xlsx").exists())

    def test_blocking_issue_stops_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValidationFailed):
                run(self._settings(), landing_dir=tmp,
                    export_file=str(self._export_file(tmp, fake_export(preg_mother="B-1_09"))))


if __name__ == "__main__":
    unittest.main()
