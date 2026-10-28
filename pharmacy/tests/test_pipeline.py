"""
Offline tests for the Pharmacy pipeline: a made-up export with the real
Pharmacy column list (map/pharmacy/export_columns.txt), no Kobo and no
Databricks.

Run from the repo root:  python -m unittest discover -s pharmacy/tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PHARMACY_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PHARMACY_DIR))

import architecture as arch  # noqa: E402
from pipeline.run import ValidationFailed, run  # noqa: E402
from pipeline.settings import APPROVED, MAP_DIR, Settings  # noqa: E402
from pipeline.transform import RunInfo, build  # noqa: E402

RUN = RunInfo("20261028T000000Z_test", "2026-10-28 00:00:00", "aLcuF4wGExja3LrSZxEEnB", "git-test")


def export_columns() -> list[str]:
    return [l.strip() for l in (MAP_DIR / "export_columns.txt").read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#") and not l.startswith("[")]


def fake_export(second_root="") -> dict[str, pd.DataFrame]:
    """Two pharmacies: A approved (new form version), B not approved (old version, numeric LGA code)."""
    cols = export_columns()
    rows = [
        {"_uuid": "ua", "meta/rootUuid": "uuid:ra", "_index": "1", "_id": "201", "_validation_status": APPROVED,
         "starttime": "2025-06-02T09:15:00.000+01:00", "endtime": "2025-06-02T09:55:00.000+01:00",
         "username": "enum one", "phonenumber": "08031234567", "name_pharmacist": "Pharm A",
         "photo_001_URL": "https://kc.kobotoolbox.org/media/photo.jpg", "_gps_latitude": "12.17",
         "_gps_longitude": "6.66", "signed_consent": "yes", "states": "Zamfara", "lgas": "Gusau",
         "unique": "ZM-01-001", "settlement_type": "urban", "gender": "female", "age": "34",
         "antibiotics": "Yes", "antibiotic_meaning/medicines_that_can_kill_germs_in_the_body": "1",
         "antibiotic_meaning/medicines_used_to_treat_malaria": "0", "stock/azithromycin": "1.0",
         "other_stock": "Cefixime", "training_year": "2019-01-01", "no_people": "12"},
        {"_uuid": "ub", "meta/rootUuid": second_root, "_index": "2", "_id": "202",
         "_validation_status": "validation_status_not_approved", "lgas": "02", "unique": "ZM-01-002",
         "age": "forty"},
    ]
    df = pd.DataFrame([{c: "" for c in cols} for _ in rows])
    for i, values in enumerate(rows):
        for k, v in values.items():
            df.at[i, k] = v
    return {"SARMAAN II BASELINE ZAMFARA ...": df}


def tables(built):
    return {f"{t.schema}.{t.name}": t for t in built.tables}


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.built = build(fake_export(), RUN, cycle="Year 1")
        self.t = tables(self.built)

    def test_no_blocking_issues(self):
        self.assertTrue(self.built.blocking.empty, self.built.blocking.to_string())

    def test_bronze_keeps_every_row_with_lineage(self):
        b = self.t["bronze.pharmacy"]
        self.assertTrue(b.append)
        self.assertEqual(len(b.df), 2)
        for col, _ in arch.BRONZE_METADATA:
            self.assertIn(col, b.df.columns)
        self.assertEqual(b.df["meta_rootuuid"].tolist(), ["uuid:ra", "uuid:ub"])   # blank filled like Kobo

    def test_silver_has_every_submission_in_postgres_order(self):
        s = self.t["silver.pharmacy"].df
        self.assertEqual(len(s), 2)
        self.assertEqual(len(s.columns), 107 + 2)           # + root_uuid, _run_id
        self.assertEqual(s.columns[0], arch.ROOT_UUID)

    def test_gold_is_approved_only_and_identifiers_restricted(self):
        g, r = self.t["gold.pharmacy"], self.t["restricted.pharmacy_identifiers"]
        self.assertEqual(g.df[arch.ROOT_UUID].tolist(), ["uuid:ra"])
        self.assertFalse(set(arch.IDENTIFIERS["pharmacy"]) & set(g.df.columns))
        self.assertTrue(set(arch.IDENTIFIERS["pharmacy"]) <= set(r.df.columns))
        self.assertEqual(r.df.iloc[0]["enumerator_phone_number"], "08031234567")   # STRING keeps the 0
        self.assertEqual(r.df.iloc[0]["pharmacy_photo_url"], "https://kc.kobotoolbox.org/media/photo.jpg")

    def test_postgres_value_rules(self):
        g = self.t["gold.pharmacy"].df.iloc[0]
        self.assertEqual((g["consent"], g["know_antibiotics"]), ("Yes", "Yes"))
        self.assertEqual((g["settlement_type"], g["pharmacist_gender"]), ("Urban", "Female"))
        self.assertEqual(g["define_antibiotics_kill_germs"], "Yes")
        self.assertEqual(g["define_antibiotics_treat_malaria"], "No")
        self.assertEqual(g["antibiotics_in_shop_azith"], "Yes")
        self.assertEqual(g["antibiotics_in_shop_other_specified"], "Cefixime")   # _specified not recoded
        self.assertEqual((g["start_time"], g["end_time"], g["training_year"]),
                         ("2025-06-02", "2025-06-02", "2019-01-01"))           # dates only
        self.assertEqual((g["cycle"], g["concatenated_id"]), ("Year 1", "ua_1"))
        self.assertEqual((g["pharmacist_age"], g["people_count_ask_antibitoics"]), ("34", "12"))

    def test_lga_code_becomes_name(self):
        s = self.t["silver.pharmacy"].df
        self.assertEqual(s.loc[s[arch.ROOT_UUID] == "uuid:ub", "lga"].iloc[0], "Bakura")


class ApprovalTests(unittest.TestCase):
    """Pharmacy marks only rejected submissions: with blank_status_is_approved,
    a blank status goes to gold; 'not approved' and 'on hold' never do."""

    def _gold_roots(self, statuses, blank_is_approved):
        export = fake_export()
        df = next(iter(export.values()))
        df = pd.concat([df] * 2, ignore_index=True)          # four pharmacies
        df["_uuid"] = ["u1", "u2", "u3", "u4"]
        df["meta/rootUuid"] = ""
        df["_validation_status"] = statuses
        built = build({"sheet": df}, RUN, "Year 1", blank_is_approved)
        self.assertTrue(built.blocking.empty, built.blocking.to_string())
        return tables(built)["gold.pharmacy"].df[arch.ROOT_UUID].tolist()

    STATUSES = ["", APPROVED, "validation_status_not_approved", "validation_status_on_hold"]

    def test_blank_counts_as_approved_when_configured(self):
        self.assertEqual(self._gold_roots(self.STATUSES, True), ["uuid:u1", "uuid:u2"])

    def test_blank_stays_out_by_default(self):
        self.assertEqual(self._gold_roots(self.STATUSES, False), ["uuid:u2"])


class BlockingTests(unittest.TestCase):
    def test_repeated_root_uuid_blocks(self):
        built = build(fake_export(second_root="uuid:ra"), RUN, "Year 1")
        self.assertIn("duplicate_key", set(built.blocking["check_type"]))


class RunTests(unittest.TestCase):
    def _export_file(self, folder, export):
        path = Path(folder) / "export.xlsx"
        with pd.ExcelWriter(path) as xl:
            for name, df in export.items():
                df.to_excel(xl, sheet_name=name[:31], index=False)
        return path

    def _settings(self):
        return Settings(round="zamfara_c1", catalog="eha_ghi_sarmaan_dev", dry_run=True,
                        kobo_base_url="https://kf.kobotoolbox.org", kobo_asset_uid="aLcuF4wGExja3LrSZxEEnB",
                        kobo_export_settings_id="esoXu2auPC68oteb2G3UuGA", kobo_token="token",
                        cycle="Year 1", export_wait_minutes=1, pipeline_version="git-test")

    def test_dry_run_lands_the_export_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = run(self._settings(), landing_dir=tmp,
                          export_file=str(self._export_file(tmp, fake_export())))
            self.assertEqual((summary["bronze.pharmacy"], summary["gold.pharmacy"]), (2, 1))
            [folder] = [p for p in Path(tmp).iterdir() if p.is_dir()]
            self.assertTrue(folder.name.endswith("_dryrun"))
            self.assertTrue((folder / "kobo_export.xlsx").exists())

    def test_blocking_issue_stops_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValidationFailed):
                run(self._settings(), landing_dir=tmp,
                    export_file=str(self._export_file(tmp, fake_export(second_root="uuid:ra"))))


if __name__ == "__main__":
    unittest.main()
