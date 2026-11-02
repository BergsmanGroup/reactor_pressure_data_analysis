"""Recipe conversion regression tests (pre-Qt-migration baseline)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import _helpers
from _helpers import (
    EXAMPLE_CSV,
    EXAMPLE_PAYLOAD,
    OWNER_EXAMPLE_CSV,
    OWNER_EXAMPLE_TOTAL_SECONDS,
    WORKBOOK_CURRENT,
    WORKBOOK_OLD,
    load_golden,
    sha256_file,
)
from _baseline import PAYLOAD_FIXTURES, build_normalized_payload

import convert_to_json


def _details(payload: dict) -> dict:
    return json.loads(payload["experimentalDetails"])


class GoldenPayloadTests(unittest.TestCase):
    def test_payloads_match_golden_baselines(self):
        for golden_name, source in PAYLOAD_FIXTURES.items():
            with self.subTest(source=source.name):
                self.assertTrue(source.exists(), f"missing fixture {source}")
                self.assertEqual(build_normalized_payload(source), load_golden(golden_name))

    def test_example_csv_matches_stored_payload_for_stable_fields(self):
        # The stored example payload predates the current username and legacy
        # SID/EID/PID handling, so only fields that did not change are compared.
        payload = convert_to_json.build_payload(convert_to_json.load_table(EXAMPLE_CSV))
        with open(EXAMPLE_PAYLOAD, "r", encoding="utf-8") as fh:
            stored = json.load(fh)
        self.assertEqual(payload["recipe"], stored["recipe"])
        current, expected = _details(payload), _details(stored)
        for key in ("Info", "WaitTime", "EDR", "DID", "ValvePrecursor", "Name", "TempC", "ProcessTimeHr"):
            self.assertEqual(current[key], expected[key], key)

    def test_workbooks_validate_and_produce_nine_column_rows(self):
        for path in (WORKBOOK_CURRENT, WORKBOOK_OLD):
            with self.subTest(workbook=path.name):
                df = convert_to_json.load_table(path)
                self.assertEqual(convert_to_json.validate_recipe_sheet(df), [])
                payload = convert_to_json.build_payload(df)
                self.assertTrue(payload["recipe"])
                self.assertEqual({len(row) for row in payload["recipe"]}, {convert_to_json.RECIPE_SEQUENCE_COLS})


class OwnerExampleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="recipe_test_"))
        self.csv_path = self._tmp / "owner_example.csv"
        self.csv_path.write_text(OWNER_EXAMPLE_CSV, encoding="utf-8")
        self.df = convert_to_json.load_table(self.csv_path)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_process_time_is_per_sequence_sum(self):
        payload = convert_to_json.build_payload(self.df)
        expected_hr = round(OWNER_EXAMPLE_TOTAL_SECONDS / 3600.0, 6)
        self.assertAlmostEqual(_details(payload)["ProcessTimeHr"], expected_hr, places=6)

    def test_cycle_column_marks_sequence_starts(self):
        rows = convert_to_json.extract_timing_table(self.df)
        self.assertEqual([row[0] for row in rows], ["1", "1", "40", "", "", "", "", "", "1"])
        self.assertEqual([row[1] for row in rows], ["12", "7", "5", "5", "7", "8", "8", "7", "12"])


class SourceImmutabilityTests(unittest.TestCase):
    def test_conversion_never_modifies_source(self):
        tmp = Path(tempfile.mkdtemp(prefix="recipe_hash_"))
        try:
            for source in (EXAMPLE_CSV, WORKBOOK_CURRENT, WORKBOOK_OLD):
                with self.subTest(source=source.name):
                    copy = tmp / source.name
                    shutil.copy2(source, copy)
                    before = sha256_file(copy)
                    _, out_path = convert_to_json.convert_recipe_sheet(copy, out_path=tmp / f"{copy.stem}_out.json")
                    self.assertTrue(out_path.exists())
                    self.assertNotEqual(out_path.resolve(), copy.resolve())
                    self.assertEqual(sha256_file(copy), before)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
