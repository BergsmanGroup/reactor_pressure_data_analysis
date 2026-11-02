"""Settings persistence, conflict handling, and local Help actions."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox

from _synthetic_run import write_synthetic_run
from reactor_ui.models.analysis_state import AnalysisState
from reactor_ui.pages.analyze_page import AnalyzePage
from reactor_ui.pages.help_page import HelpPage
from reactor_ui.pages.settings_page import SettingsPage
from settings_store import load_settings_state, save_settings_state


class SettingsHelpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="qt_preferences_")
        self.root = Path(self.folder.name)
        self.default = self.root / "config_default.json"
        self.local = self.root / "config_local.json"
        self.defaults = {
            "last_processing_settings": {
                "xlim": "auto",
                "ylim": "auto",
                "shift": "2",
                "wait_time": "0",
                "fps": "5",
                "leakrate_phase_reduction": "0",
                "thickness_blank_rows": "0",
                "write_condensed_json": True,
            },
            "last_valve_names": {"InSituReactor": {}, "HTReactor": {}},
            "reactors": ["InSituReactor", "HTReactor"],
        }
        self.default.write_text(json.dumps(self.defaults), encoding="utf-8")
        self.state = AnalysisState()
        self.analyze = AnalyzePage(
            self.state,
            settings_path=self.local,
            default_settings_path=self.default,
            valve_log_path=self.root / "valves.jsonl",
        )
        self.settings = SettingsPage(self.state, self.local, self.default)

    def tearDown(self):
        self.analyze.cleanup()
        self.settings.close()
        self.analyze.close()
        self.folder.cleanup()

    def test_round_trip_updates_analyze_and_retains_existing_options(self):
        self.settings.text_fields["fps"].setText("8")
        self.settings.text_fields["grid_x_spacing"].setText("2.5")
        self.settings.boolean_fields["write_condensed_json"].setChecked(False)
        self.settings.reactors.setPlainText("InSituReactor\nHTReactor\nNewReactor")
        model = self.settings.valve_model
        for column, value in enumerate(("NewReactor", "7", "Precursor")):
            model.setData(model.index(0, column), value)
        self.settings._save()
        self.assertIn("saved", self.settings.status.text().lower())
        saved = load_settings_state(self.local, self.default, create_local=False)
        self.assertEqual(saved["last_processing_settings"]["fps"], "8")
        self.assertEqual(saved["last_processing_settings"]["grid_x_spacing"], "2.5")
        self.assertFalse(saved["last_processing_settings"]["write_condensed_json"])
        self.assertEqual(saved["last_valve_names"]["NewReactor"]["7"], "Precursor")
        self.assertIn("NewReactor", saved["reactors"])
        self.assertEqual(self.analyze.fps.text(), "8")
        self.assertFalse(self.analyze.write_condensed.isChecked())
        self.assertIn("NewReactor", self.analyze.settings["reactors"])

    def test_loaded_header_takes_precedence_after_settings_are_saved(self):
        source = write_synthetic_run(self.root / "260101_12h00m__InSituReactor_Test_Reactor1_Data.json")
        self.analyze.source_input.setText(str(source))
        self.analyze._load_header()
        thread = self.analyze._thread
        self.assertIsNotNone(thread)
        loop = QEventLoop()
        thread.finished.connect(loop.quit)
        QTimer.singleShot(10000, loop.quit)
        loop.exec()
        self.app.processEvents()
        self.assertFalse(self.analyze.is_busy())
        self.assertEqual(self.state.source_path, source.resolve())
        self.settings.text_fields["wait_time"].setText("99")
        for column, value in enumerate(("InSituReactor", "7", "Saved name")):
            self.settings.valve_model.setData(self.settings.valve_model.index(0, column), value)
        self.settings._save()
        self.assertIn("saved", self.settings.status.text().lower())
        self.assertEqual(self.analyze.wait.text(), "0")
        self.assertTrue(self.analyze.wait.isReadOnly())
        self.assertEqual(self.analyze._valve_fields[7].text(), "TestValve")
        self.assertTrue(self.analyze._valve_fields[7].isReadOnly())

    def test_invalid_values_and_external_conflict_do_not_overwrite(self):
        self.settings.text_fields["fps"].setText("0")
        self.settings._save()
        self.assertFalse(self.local.exists())
        self.assertIn("FPS", self.settings.status.text())
        self.settings.text_fields["fps"].setText("7")
        external = copy.deepcopy(self.defaults)
        external["last_processing_settings"]["shift"] = "9"
        save_settings_state(self.local, external)
        before = self.local.read_bytes()
        self.settings._save()
        self.assertEqual(self.local.read_bytes(), before)
        self.assertIn("changed on disk", self.settings.status.text())

    def test_reset_requires_confirmation_and_copies_exact_defaults(self):
        changed = copy.deepcopy(self.defaults)
        changed["last_processing_settings"]["fps"] = "20"
        save_settings_state(self.local, changed)
        self.settings._load()
        before = self.local.read_bytes()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as question:
            self.settings._reset()
        self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.No)
        self.assertEqual(self.local.read_bytes(), before)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.settings._reset()
        self.assertEqual(json.loads(self.local.read_text(encoding="utf-8")), self.defaults)
        self.assertEqual(self.analyze.fps.text(), "5")

    def test_bad_defaults_are_not_written_during_reset(self):
        self.local.write_text(json.dumps(self.defaults), encoding="utf-8")
        self.settings._load()
        before = self.local.read_bytes()
        bad = copy.deepcopy(self.defaults)
        bad["last_processing_settings"]["write_condensed_json"] = "not a boolean"
        self.default.write_text(json.dumps(bad), encoding="utf-8")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.settings._reset()
        self.assertEqual(self.local.read_bytes(), before)
        self.assertIn("ERROR", self.settings.status.text())

    def test_malformed_local_settings_can_be_reset(self):
        self.local.write_text("{", encoding="utf-8")
        self.settings._load()
        self.assertIn("ERROR", self.settings.status.text())
        self.assertFalse(self.settings.save_button.isEnabled())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.settings._reset()
        self.assertEqual(json.loads(self.local.read_text(encoding="utf-8")), self.defaults)
        self.assertTrue(self.settings.save_button.isEnabled())
        self.assertEqual(self.analyze.fps.text(), "5")

    def test_external_analysis_update_preserves_unsaved_draft(self):
        self.settings.text_fields["fps"].setText("7")
        external = copy.deepcopy(self.defaults)
        external["last_processing_settings"]["shift"] = "4"
        save_settings_state(self.local, external)
        self.state.settings_changed.emit(external, "analyze")
        self.assertEqual(self.settings.text_fields["fps"].text(), "7")
        self.assertIn("Reload", self.settings.status.text())
        self.settings._save()
        self.assertEqual(load_settings_state(self.local, self.default)["last_processing_settings"]["shift"], "4")
        self.assertIn("changed on disk", self.settings.status.text())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.settings._reload_clicked()
        self.assertEqual(self.analyze.shift.text(), "4")

    def test_legacy_flat_valve_names_survive_conversion(self):
        legacy = copy.deepcopy(self.defaults)
        legacy["last_valve_names"] = {"7": "Legacy"}
        save_settings_state(self.local, legacy)
        self.settings._load()
        self.settings._save()
        names = load_settings_state(self.local, self.default)["last_valve_names"]
        self.assertEqual(names["InSituReactor"]["7"], "Legacy")
        self.assertEqual(names["HTReactor"]["7"], "Legacy")

    def test_settings_are_disabled_during_processing(self):
        self.state.set_busy(True)
        self.assertFalse(self.settings.isEnabled())
        self.assertFalse(self.settings.save_button.isEnabled())
        self.state.set_busy(False)
        self.assertTrue(self.settings.isEnabled())
        self.assertTrue(self.settings.save_button.isEnabled())

    def test_help_opens_existing_docs_and_reports_missing_or_failed_paths(self):
        (self.root / "WHITEPAPER.md").write_text("documentation", encoding="utf-8")
        (self.root / "PROCESSING_WORKFLOW_REVIEW.md").write_text("workflow", encoding="utf-8")
        (self.root / "docs").mkdir()
        help_page = HelpPage(self.root)
        self.assertIn("Python:", help_page.version_label.text())
        self.assertIn("PySide6:", help_page.version_label.text())
        self.assertIn("Application version: Not specified in this checkout", help_page.version_label.text())
        with patch.object(QDesktopServices, "openUrl", return_value=True) as open_url:
            for button in help_page.documentation_buttons.values():
                button.click()
        self.assertEqual(open_url.call_count, 3)
        self.assertEqual(Path(open_url.call_args_list[0].args[0].toLocalFile()), self.root / "WHITEPAPER.md")
        with patch.object(QDesktopServices, "openUrl", return_value=False):
            help_page.documentation_buttons["Technical Whitepaper"].click()
        self.assertIn("could not open", help_page.status.text())
        help_page._open(self.root / "missing.md")
        self.assertIn("does not exist", help_page.status.text())
        help_page.close()
        with patch("reactor_ui.pages.help_page.APPLICATION_VERSION", "1.2.3"):
            versioned_page = HelpPage(self.root)
        self.assertIn("Application version: 1.2.3", versioned_page.version_label.text())
        versioned_page.close()


if __name__ == "__main__":
    unittest.main()
