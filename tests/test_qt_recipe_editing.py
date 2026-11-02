"""Editable draft, validation, clipboard and undo regression tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from _helpers import OWNER_EXAMPLE_CSV, OWNER_EXAMPLE_TOTAL_SECONDS, normalize_payload, sha256_file
from convert_to_json import build_output_filename, build_payload, load_table
from reactor_ui.adapters.recipe_conversion import create_payload, export_payload
from reactor_ui.models.recipe_document import RecipeDocument
from reactor_ui.pages.recipe_editor_page import RecipeEditorPage


class RecipeEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="qt_editing_")
        self.source = Path(self.folder.name) / "recipe.csv"
        self.source.write_text(OWNER_EXAMPLE_CSV, encoding="utf-8")
        self.before = sha256_file(self.source)
        self.page = RecipeEditorPage()
        self.page.resize(1400, 900)
        self.page.open_recipe(self.source)
        self.page.show()
        self.app.processEvents()

    def tearDown(self):
        self.page.close()
        self.folder.cleanup()

    def test_edit_recomputes_and_undo_restores_exact_state(self):
        doc = self.page.document
        model = self.page.table_model
        self.page.timeline.set_playhead(10000)
        original_rows = [row[:] for row in doc.rows]
        index = model.index(0, 4)
        self.assertTrue(model.flags(index) & Qt.ItemFlag.ItemIsEditable)
        self.assertFalse(model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEditable)
        self.assertFalse(model.flags(model.index(0, 1)) & Qt.ItemFlag.ItemIsEditable)
        self.assertTrue(model.setData(index, "20"))
        self.assertEqual(doc.run_seconds, OWNER_EXAMPLE_TOTAL_SECONDS + 10)
        self.assertEqual(self.page.timeline.playhead_seconds, 10000)
        self.assertTrue(doc.dirty)
        doc.undo_stack.undo()
        self.assertEqual(doc.rows, original_rows)
        self.assertEqual(doc.run_seconds, OWNER_EXAMPLE_TOTAL_SECONDS)
        self.assertFalse(doc.dirty)
        doc.undo_stack.redo()
        self.assertEqual(doc.rows[0][2], "20")
        self.assertEqual(doc.run_seconds, OWNER_EXAMPLE_TOTAL_SECONDS + 10)
        self.assertEqual(sha256_file(self.source), self.before)

    def test_table_delegate_commits_a_user_edit(self):
        table = self.page.timing_table
        index = self.page.table_model.index(0, 4)
        table.setCurrentIndex(index)
        table.edit(index)
        self.app.processEvents()
        editor = table.findChild(QLineEdit)
        assert editor is not None
        editor.selectAll()
        QTest.keyClicks(editor, "25")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.page.document.rows[0][2], "25")
        self.assertEqual(self.page.document.run_seconds, OWNER_EXAMPLE_TOTAL_SECONDS + 15)

    def test_invalid_cell_stays_visible_and_preserves_playhead_when_fixed(self):
        self.page.timeline.set_playhead(10000)
        model = self.page.table_model
        index = model.index(0, 4)
        model.setData(index, "-1")
        self.assertEqual(model.data(index), "-1")
        self.assertIn("non-negative", model.data(index, Qt.ItemDataRole.ToolTipRole))
        self.assertIsNotNone(model.data(index, Qt.ItemDataRole.BackgroundRole))
        self.assertFalse(self.page.export_button.isEnabled())
        self.assertIn("stale", self.page.timeline_note.text().lower())
        model.setData(index, "15")
        self.assertTrue(self.page.export_button.isEnabled())
        self.assertEqual(self.page.timeline.playhead_seconds, 10000)

        valve = model.index(0, 3)
        model.setData(valve, "999")
        self.assertIn("not declared", model.data(valve, Qt.ItemDataRole.ToolTipRole))
        self.assertFalse(self.page.document.can_export)
        model.setData(valve, "12")
        self.assertTrue(self.page.document.can_export)

    def test_playhead_and_table_resynchronize_when_a_boundary_moves(self):
        self.page.timeline.select_sequence(3)
        self.assertEqual(self.page.timeline.playhead_seconds, 165)
        self.page.table_model.setData(self.page.table_model.index(0, 4), "20")
        self.assertEqual(self.page.timeline.playhead_seconds, 165)
        self.assertEqual(self.page.timeline.selected_sequence.index, 2)
        self.assertEqual(self.page.timing_table.currentIndex().row(), 1)

    def test_rectangular_clipboard_paste_is_one_undo_step(self):
        doc = self.page.document
        table = self.page.timing_table
        model = self.page.table_model
        original = [row[:] for row in doc.rows]
        selection = QItemSelection(model.index(2, 4), model.index(3, 5))
        table.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        table.setFocus()
        QTest.keyClick(table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.app.clipboard().text(), "10\t0\n10\t0")
        table.setCurrentIndex(model.index(4, 4))
        QTest.keyClick(table, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(doc.rows[4][2:4], ["10", "0"])
        self.assertEqual(doc.rows[5][2:4], ["10", "0"])
        self.assertEqual(doc.undo_stack.count(), 1)
        doc.undo_stack.undo()
        self.assertEqual(doc.rows, original)
        doc.undo_stack.redo()
        self.assertEqual(doc.rows[4][2:4], ["10", "0"])

    def test_paste_rejects_bad_shape_type_and_bounds_without_partial_edit(self):
        doc = self.page.document
        original = [row[:] for row in doc.rows]
        for row, column, text in (
            (0, 2, "1\t2\n3"),
            (0, 2, "1\tbad\n3\t4"),
            (8, 2, "1\n2"),
            (0, 0, "2.5"),
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                doc.paste_rectangle(row, column, text)
            self.assertEqual(doc.rows, original)
            self.assertEqual(doc.undo_stack.count(), 0)

    def test_row_insert_delete_and_undo_preserve_rows(self):
        doc = self.page.document
        original = [row[:] for row in doc.rows]
        self.page.timeline.set_playhead(10000)
        doc.insert_row(3)
        self.assertEqual(doc.rows[3], [""] * 10)
        self.assertFalse(doc.can_export)
        doc.undo_stack.undo()
        self.assertEqual(doc.rows, original)
        self.assertEqual(self.page.timeline.playhead_seconds, 10000)
        doc.undo_stack.redo()
        self.assertEqual(doc.rows[3], [""] * 10)
        doc.undo_stack.undo()
        doc.delete_rows([3, 4])
        self.assertEqual(doc.rows, [row for index, row in enumerate(original) if index not in (3, 4)])
        doc.undo_stack.undo()
        self.assertEqual(doc.rows, original)

    def test_metadata_edits_and_clean_index_are_undoable(self):
        doc = self.page.document
        self.page.description_input.setPlainText("Changed description")
        self.assertEqual(doc.metadata_text("info"), "Changed description")
        doc.undo_stack.undo()
        self.assertEqual(self.page.description_input.toPlainText(), "Owner example with four sequences")
        self.assertFalse(doc.dirty)
        doc.undo_stack.redo()
        self.assertEqual(self.page.description_input.toPlainText(), "Changed description")
        self.page.wait_input.setText("75")
        self.assertEqual(doc.wait_seconds, 75)
        doc.undo_stack.undo()
        self.assertEqual(self.page.wait_input.text(), "0")
        editor = self.page._valve_edits[1][1]
        old_name = editor.text()
        editor.setFocus()
        editor.selectAll()
        QTest.keyClicks(editor, "Updated valve")
        self.assertEqual(doc.valve_rows[1][1], "Updated valve")
        for _ in "Updated valve":
            doc.undo_stack.undo()
        self.assertEqual(doc.valve_rows[1][1], old_name)
        self.page._add_valve()
        self.assertEqual(len(doc.valve_rows), 7)
        self.assertFalse(doc.can_export)
        doc.undo_stack.undo()
        self.assertEqual(len(doc.valve_rows), 6)
        self.assertTrue(doc.can_export)

        output = Path(self.folder.name) / "payload.json"
        export_payload(doc, output)
        self.assertFalse(doc.dirty)
        doc.undo_stack.undo()
        self.assertTrue(doc.dirty)
        doc.undo_stack.redo()
        self.assertFalse(doc.dirty)

    def test_live_field_shortcuts_undo_and_reopen_clears_actions(self):
        doc = self.page.document
        field = self.page.username_input
        field.setFocus()
        QTest.keyClick(field, Qt.Key.Key_End)
        QTest.keyClicks(field, "X")
        self.assertEqual(doc.metadata_text("username"), "JayX")
        self.assertEqual(doc.undo_stack.index(), 1)
        QTest.keyClick(field, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(field.text(), "Jay")
        self.assertEqual(doc.undo_stack.index(), 0)
        self.assertEqual(doc.undo_stack.count(), 1)
        doc.undo_stack.redo()
        self.assertTrue(self.page.undo_action.isEnabled())
        self.page.open_recipe(self.source)
        self.assertFalse(self.page.undo_action.isEnabled())
        self.assertFalse(self.page.undo_button.isEnabled())
        self.assertEqual(doc.undo_stack.count(), 0)

    def test_start_time_and_unsaved_new_confirmation(self):
        doc = self.page.document
        original_start = doc.start_time
        doc.set_start_time(datetime(2026, 1, 2, 12, 0, 0))
        self.assertTrue(doc.dirty)
        doc.undo_stack.undo()
        self.assertEqual(doc.start_time, original_start)
        doc.undo_stack.redo()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.page._new_clicked()
        self.assertEqual(doc.source_path, self.source.resolve())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.page._new_clicked()
        self.assertIsNone(doc.source_path)
        self.assertIsNotNone(doc.frame)
        self.assertFalse(doc.dirty)

    def test_pending_cell_edit_is_committed_before_discard_confirmation(self):
        table = self.page.timing_table
        index = self.page.table_model.index(0, 4)
        table.setCurrentIndex(index)
        table.edit(index)
        self.app.processEvents()
        editor = table.findChild(QLineEdit)
        assert editor is not None
        editor.selectAll()
        QTest.keyClicks(editor, "25")
        self.assertFalse(self.page.document.dirty)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as question:
            self.assertFalse(self.page.confirm_discard())
        question.assert_called_once()
        self.assertEqual(self.page.document.rows[0][2], "25")
        self.assertTrue(self.page.document.dirty)

    def test_exported_draft_matches_equivalent_sheet_and_does_not_change_source(self):
        doc = self.page.document
        start = datetime(2026, 1, 2, 12, 0, 0)
        doc.set_cells([(2, 5, "333"), (3, 9, "Continuation note")])
        doc.set_metadata("info", "Edited description")
        doc.set_wait_text("75")
        doc.set_start_time(start)
        equivalent = (
            OWNER_EXAMPLE_CSV.replace("Info,Owner example with four sequences", "Info,Edited description")
            .replace("Wait time,0", "Wait time,75")
            .replace("40,5,10,0,0,300,0,0,600,", "40,5,10,0,0,333,0,0,600,")
            .replace(",5,10,0,0,0,60,0,10,", ",5,10,0,0,0,60,0,10,Continuation note", 1)
        )
        sheet = Path(self.folder.name) / "equivalent.csv"
        sheet.write_text(equivalent, encoding="utf-8")
        frame = load_table(sheet)
        expected = build_payload(frame, username=build_output_filename(frame), start_time=start)
        self.assertEqual(normalize_payload(create_payload(doc)), normalize_payload(expected))
        output = Path(self.folder.name) / "edited_payload.json"
        export_payload(doc, output)
        self.assertEqual(normalize_payload(json.loads(output.read_text(encoding="utf-8"))), normalize_payload(expected))
        self.assertEqual(sha256_file(self.source), self.before)

    def test_new_draft_can_be_built_and_exported_without_a_workbook(self):
        doc = RecipeDocument()
        doc.new_draft()
        doc.set_metadata("username", "New run")
        doc.set_valve_rows([["nan", "Chamber", "25"], ["5", "Precursor", "20"]])
        doc.set_cells([(0, 0, "1"), (0, 1, "5"), (0, 2, "10")])
        self.assertTrue(doc.can_export, doc.validation_errors)
        self.assertIsNone(doc.source_path)
        target = Path(self.folder.name) / "new_payload.json"
        export_payload(doc, target)
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(payload["recipe"][0][:3], ["1", "5", "10"])
        self.assertFalse(doc.dirty)

    def test_integer_equivalent_valve_text_validates_and_exports_exactly(self):
        doc = self.page.document
        doc.set_cells([(0, 1, "12.0")])
        self.assertTrue(doc.can_export, doc.validation_errors)
        self.assertEqual(create_payload(doc)["recipe"][0][1], "12")

        doc.new_draft()
        valve = "9007199254740993"
        doc.set_valve_rows([["nan", "Chamber", "25"], [valve, "Large valve", "20"]])
        doc.set_cells([(0, 0, "1"), (0, 1, valve), (0, 2, "10")])
        self.assertTrue(doc.can_export, doc.validation_errors)
        self.assertEqual(create_payload(doc)["recipe"][0][1], valve)


if __name__ == "__main__":
    unittest.main()
