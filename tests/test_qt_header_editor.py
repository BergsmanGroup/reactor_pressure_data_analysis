"""Qt header editor, confirmation, and integrated correction workflows."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from _synthetic_run import write_synthetic_run
from data_parser import read_header
from header_text import associated_header_artifacts, save_header_text
from reactor_ui.adapters.header_changes import build_header_change_plan, inspect_header_artifacts
from reactor_ui.dialogs.header_editor_dialog import HeaderEditorDialog
from reactor_ui.dialogs.header_plan_dialog import HeaderPlanDialog
from reactor_ui.models.analysis_state import AnalysisState
from reactor_ui.pages.analyze_page import AnalyzePage
from reactor_ui.workers.pipeline_worker import OperationWorker
from recipe_timing_core import TIMING_COLUMNS


class HeaderEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="qt_header_")
        self.root = Path(self.folder.name)
        default = self.root / "default.json"
        default.write_text(
            json.dumps(
                {
                    "last_processing_settings": {"write_condensed_json": False, "add_temperature": False},
                    "last_valve_names": {},
                    "reactors": ["InSituReactor"],
                }
            ),
            encoding="utf-8",
        )
        self.source = write_synthetic_run(
            self.root / "260101_12h00m__InSituReactor_Test_Reactor1_Data.json"
        )
        self.header_path = self.root / "260101_12h00m__InSituReactor_Test_Reactor1_Header.txt"
        self.original = read_header(self.source)
        save_header_text(self.header_path, self.original)
        self.state = AnalysisState()
        self.page = AnalyzePage(
            self.state,
            settings_path=self.root / "local.json",
            default_settings_path=default,
            valve_log_path=self.root / "valves.jsonl",
        )
        self.page.source_input.setText(str(self.source))
        self.page.output_input.setText(str(self.root / "output"))
        self.page._load_header()
        self.wait_for_workers()
        self.page.header_text_input.setText(str(self.header_path))

    def tearDown(self):
        self.wait_for_workers()
        self.page.cleanup()
        self.page.close()
        self.folder.cleanup()

    def wait_for_workers(self):
        deadline = time.monotonic() + 30
        while self.page.is_busy():
            self.assertLess(time.monotonic(), deadline, "Header worker did not finish")
            thread = self.page._thread
            loop = QEventLoop()
            thread.finished.connect(loop.quit)
            QTimer.singleShot(1000, loop.quit)
            loop.exec()
            self.app.processEvents()

    def plan(self):
        inventory = inspect_header_artifacts(self.source, "Corrected", self.header_path)
        return build_header_change_plan(
            self.source,
            "Corrected",
            self.header_path,
            save_header_text=True,
            align_names=False,
            inventory=inventory,
            timestamp="20261101-123456",
            token="abc123",
        )

    def test_edit_rows_metadata_reset_and_preserve_other_fields(self):
        dialog = HeaderEditorDialog(self.original, self.source, self.header_path)
        model = dialog.timing_model
        self.assertEqual(model.headers, TIMING_COLUMNS[:9])
        dialog.timing_table.setCurrentIndex(model.index(0, 0))
        dialog._add_timing()
        self.assertEqual(model.rowCount(), 2)
        model.setData(model.index(1, 1), "8")
        model.setData(model.index(1, 5), "3")
        dialog._reset_timing()
        self.assertEqual(model.rowCount(), 1)
        dialog._add_timing()
        model.setData(model.index(1, 1), "8")
        model.setData(model.index(1, 5), "3")
        dialog.username.setText("Corrected")
        dialog.info.setPlainText("Updated information")
        dialog.save_text.setChecked(True)
        dialog.align_names.setChecked(True)
        dialog._save()
        result = dialog.result_edit
        self.assertIsNotNone(result)
        self.assertTrue(result.save_header_text)
        self.assertTrue(result.align_names)
        self.assertEqual(result.payload["GUID"], self.original["GUID"])
        self.assertEqual(result.payload["startTime"], self.original["startTime"])
        self.assertEqual(result.payload["valveSequence"][1][0:2], ["", 8])
        self.assertEqual(result.payload["valveSequence"][1][5], 3)
        details = json.loads(result.payload["experimentalDetails"])
        original_details = json.loads(self.original["experimentalDetails"])
        self.assertEqual(details["Info"], "Updated information")
        self.assertEqual(details["SequenceNotes"], original_details["SequenceNotes"])
        self.assertEqual(details["ValvePrecursor"], original_details["ValvePrecursor"])

    def test_invalid_timing_cannot_be_saved(self):
        dialog = HeaderEditorDialog(self.original, self.source, self.header_path)
        model = dialog.timing_model
        model.setData(model.index(0, 0), "")
        with patch.object(QMessageBox, "warning") as warning:
            dialog._save()
        warning.assert_called_once()
        self.assertIn("first row", warning.call_args.args[2].lower())
        self.assertIsNone(dialog.result_edit)

    def test_false_or_nan_edr_is_not_shown_as_true(self):
        for value in (float("nan"), "False", False, 0):
            with self.subTest(value=value):
                payload = copy.deepcopy(self.original)
                details = json.loads(payload["experimentalDetails"])
                details["EDR"] = value
                payload["experimentalDetails"] = json.dumps(details)
                dialog = HeaderEditorDialog(payload, self.source, self.header_path)
                self.assertFalse(dialog.edr.isChecked())
                dialog.auto_username.setChecked(True)
                self.assertIn("EDRNaN", dialog.username.text())

    def test_confirmation_requires_checkbox_and_defaults_to_cancel(self):
        dialog = HeaderPlanDialog(self.plan())
        self.assertTrue(dialog.cancel_button.isDefault())
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertIn(str(self.source), dialog.plan_text.toPlainText())
        dialog.confirmation.setChecked(True)
        self.assertTrue(dialog.apply_button.isEnabled())

    def test_cancelled_correction_creates_no_files(self):
        before = {path: path.read_bytes() for path in self.root.iterdir() if path.is_file()}
        with patch.object(HeaderPlanDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            self.page._prepare_header_change({**self.original, "username": "Corrected"}, True, False)
        after = {path: path.read_bytes() for path in self.root.iterdir() if path.is_file()}
        self.assertEqual(after, before)
        self.assertIn("cancelled", self.page.log_box.toPlainText().lower())

    def test_use_header_text_rewrites_only_after_confirmation_and_reloads(self):
        text_payload = copy.deepcopy(self.original)
        text_payload["username"] = "TextHeader"
        text_payload["valveSequence"][0][5] = 4
        save_header_text(self.header_path, text_payload)
        original_data = self.source.read_bytes()
        original_text = self.header_path.read_bytes()
        with patch.object(HeaderPlanDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            self.page._use_header_text()
        self.wait_for_workers()
        self.assertEqual(read_header(self.source)["username"], "TextHeader")
        self.assertEqual(self.state.header["username"], "TextHeader")
        self.assertEqual(self.source.read_bytes().splitlines()[1:], original_data.splitlines()[1:])
        self.assertEqual(self.header_path.read_bytes(), original_text)
        backups = list(self.root.glob(f"{self.source.name}.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original_data)
        self.assertEqual(self.state.source_path, self.source.resolve())

    def test_aligned_correction_updates_selected_paths_and_reloads(self):
        payload = {**self.original, "username": "Corrected"}
        expected = associated_header_artifacts(self.source, "Corrected", str(self.header_path))
        with patch.object(HeaderPlanDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            self.page._prepare_header_change(payload, True, True)
        self.wait_for_workers()
        self.assertEqual(self.state.source_path, expected["selected"]["expected"])
        self.assertEqual(Path(self.page.header_text_input.text()), expected["header_text"]["expected"])
        self.assertEqual(self.state.header["username"], "Corrected")
        self.assertFalse(self.source.exists())
        self.assertEqual(len(list(self.root.glob(f"{self.source.name}.bak-*"))), 1)

    def test_failed_write_reports_backup_and_invalidates_loaded_state(self):
        with patch.object(HeaderPlanDialog, "exec", return_value=QDialog.DialogCode.Accepted), patch(
            "reactor_ui.adapters.header_changes.os.replace", side_effect=OSError("test failure")
        ), patch.object(QMessageBox, "critical") as critical:
            self.page._prepare_header_change({**self.original, "username": "Changed"}, False, False)
            self.wait_for_workers()
        critical.assert_called_once()
        self.assertIn("test failure", critical.call_args.args[2])
        self.assertIn(".bak-", critical.call_args.args[2])
        self.assertIsNone(self.state.source_path)
        self.assertFalse(self.page.run_all_button.isEnabled())

    def test_header_without_sequence_remains_editable_but_not_processable(self):
        records = self.source.read_text(encoding="utf-8").splitlines()
        first = json.loads(records[0])
        first["payload"].pop("valveSequence")
        records[0] = json.dumps(first)
        self.source.write_text("\n".join(records) + "\n", encoding="utf-8")
        self.page._load_header()
        self.wait_for_workers()
        self.assertEqual(self.state.source_path, self.source.resolve())
        self.assertFalse(self.state.sequences)
        self.assertTrue(self.page.edit_header_button.isEnabled())
        self.assertFalse(self.page.run_all_button.isEnabled())
        dialog = HeaderEditorDialog(self.state.header, self.source, self.header_path)
        self.assertEqual(dialog.timing_model.rowCount(), 1)

    def test_worker_lifetime_with_immediate_header_reloads(self):
        for _ in range(30):
            worker = OperationWorker("Fast operation", lambda _progress, _log: None)
            self.page._start_worker(worker, lambda _result: setattr(self.page, "_reload_after_work", True))
            self.wait_for_workers()
            self.assertEqual(self.state.source_path, self.source.resolve())

    def test_worker_is_destroyed_only_after_its_thread_stops(self):
        gate = threading.Event()
        worker = OperationWorker("Lifetime probe", lambda _progress, _log: gate.wait(10))
        self.page._start_worker(worker, lambda _result: None)
        thread = self.page._thread
        self.assertIsNotNone(thread)
        thread_running_at_destruction = []
        worker.destroyed.connect(
            lambda _object=None: thread_running_at_destruction.append(thread.isRunning()),
            Qt.ConnectionType.DirectConnection,
        )
        gate.set()
        self.wait_for_workers()
        self.assertEqual(thread_running_at_destruction, [False])


if __name__ == "__main__":
    unittest.main()
