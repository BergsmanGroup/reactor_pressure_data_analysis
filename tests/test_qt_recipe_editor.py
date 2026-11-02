"""Recipe loading, validation and export through the Qt editor."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import QApplication

from _helpers import (
    EXAMPLE_CSV,
    OWNER_EXAMPLE_CSV,
    OWNER_EXAMPLE_TOTAL_SECONDS,
    WORKBOOK_CURRENT,
    WORKBOOK_OLD,
    normalize_payload,
    sha256_file,
)
from convert_to_json import build_output_filename, build_payload, extract_timing_table, load_table
from reactor_ui.adapters.recipe_conversion import create_payload, export_payload
from reactor_ui.models.recipe_document import TIMING_COLUMNS, RecipeDocument
from reactor_ui.pages.recipe_editor_page import RecipeEditorPage


class RecipeEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_examples_load_into_one_source_row_table(self):
        page = RecipeEditorPage()
        try:
            for source in (EXAMPLE_CSV, WORKBOOK_CURRENT, WORKBOOK_OLD):
                with self.subTest(source=source.name):
                    page.open_recipe(source)
                    frame = load_table(source)
                    self.assertEqual(page.table_model.rowCount(), len(extract_timing_table(frame)))
                    self.assertEqual(page.table_model.columnCount(), 12)
                    self.assertEqual(
                        [page.table_model.headerData(i, Qt.Orientation.Horizontal) for i in range(12)],
                        ["#", "Seq", *TIMING_COLUMNS],
                    )
                    self.assertTrue(page.document.can_export, page.document.validation_errors)
                    self.assertEqual(page.timing_table.model(), page.table_model)
                    self.assertGreater(page.document.sequence_count, 0)
                    self.assertTrue(page.username_input.text())
        finally:
            page.close()

    def test_export_matches_existing_gui_conversion_without_changing_source(self):
        with tempfile.TemporaryDirectory(prefix="qt_recipe_") as folder:
            work = Path(folder)
            for source in (EXAMPLE_CSV, WORKBOOK_CURRENT, WORKBOOK_OLD):
                with self.subTest(source=source.name):
                    copy = work / source.name
                    shutil.copy2(source, copy)
                    before = sha256_file(copy)
                    doc = RecipeDocument()
                    doc.load(copy)
                    doc.set_start_time(datetime(2026, 1, 2, 12, 0, 0))
                    target = work / f"{copy.stem}_payload.json"
                    export_payload(doc, target)
                    with target.open(encoding="utf-8") as handle:
                        actual = json.load(handle)
                    frame = load_table(copy)
                    expected = build_payload(frame, username=build_output_filename(frame))
                    self.assertEqual(normalize_payload(actual), normalize_payload(expected))
                    self.assertEqual(sha256_file(copy), before)
                    self.assertEqual(doc.last_export_path, target)
                    self.assertFalse(doc.dirty)

    def test_wait_and_start_update_predicted_end_and_payload(self):
        with tempfile.TemporaryDirectory(prefix="qt_recipe_") as folder:
            source = Path(folder) / "owner.csv"
            source.write_text(OWNER_EXAMPLE_CSV, encoding="utf-8")
            page = RecipeEditorPage()
            try:
                page.open_recipe(source)
                start = datetime(2026, 1, 2, 12, 0, 0)
                page.start_input.setDateTime(QDateTime(start))
                page.wait_input.setText("75")
                self.assertEqual(page.document.run_seconds, OWNER_EXAMPLE_TOTAL_SECONDS)
                expected = start + timedelta(seconds=75 + OWNER_EXAMPLE_TOTAL_SECONDS)
                self.assertEqual(page.document.predicted_end, expected)
                self.assertEqual(page.predicted_end_label.text(), expected.strftime("%Y-%m-%d %H:%M:%S"))
                payload = create_payload(page.document)
                details = json.loads(payload["experimentalDetails"])
                self.assertEqual(details["WaitTime"], 75)
                self.assertEqual(details["EndTime"], expected.strftime("%Y-%m-%d %H:%M:%S"))
                page.wait_input.setText("-1")
                self.assertFalse(page.export_button.isEnabled())
                self.assertIn("Wait time", " ".join(page.document.validation_errors))
            finally:
                page.close()

    def test_invalid_timing_is_visible_and_blocks_export(self):
        with tempfile.TemporaryDirectory(prefix="qt_recipe_") as folder:
            source = Path(folder) / "invalid.csv"
            source.write_text(
                OWNER_EXAMPLE_CSV.replace("40,5,10,0,0,300,0,0,600,", "40.5,5,10,0,0,-1,0,0,600,"),
                encoding="utf-8",
            )
            doc = RecipeDocument()
            doc.load(source)
            self.assertEqual(doc.rows[2][0], "40.5")
            self.assertEqual(doc.rows[2][5], "-1")
            self.assertFalse(doc.can_export)
            self.assertIn("Cycle", " ".join(doc.validation_errors))
            self.assertIn("Dose", " ".join(doc.validation_errors))
            with self.assertRaises(ValueError):
                create_payload(doc)

    def test_export_refuses_to_overwrite_source_or_hardlink(self):
        with tempfile.TemporaryDirectory(prefix="qt_recipe_") as folder:
            work = Path(folder)
            source = work / "recipe.csv"
            source.write_text(OWNER_EXAMPLE_CSV, encoding="utf-8")
            before = sha256_file(source)
            doc = RecipeDocument()
            doc.load(source)
            with self.assertRaises(ValueError):
                export_payload(doc, source)
            alias = work / "source_alias.json"
            try:
                os.link(source, alias)
            except OSError as exc:
                self.skipTest(f"Hard links unavailable: {exc}")
            with self.assertRaisesRegex(ValueError, "source recipe"):
                export_payload(doc, alias)
            self.assertEqual(sha256_file(source), before)


if __name__ == "__main__":
    unittest.main()
