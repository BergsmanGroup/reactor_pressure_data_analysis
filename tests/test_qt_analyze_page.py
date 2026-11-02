"""Qt Analyze page integration, file paths, and safety checks."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import matplotlib

matplotlib.use("Agg")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from _helpers import sha256_file
from _synthetic_run import write_synthetic_run
from analysis_metadata import parse_experimental_details, sequence_note_text
from data_parser import condense_log, condensed_path
from pipeline import ReactorPipeline
from reactor_ui.adapters.analysis_controller import build_processing_snapshot
from reactor_ui.models.analysis_state import AnalysisState
from reactor_ui.pages.analyze_page import AnalyzePage


class AnalyzePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="qt_analyze_")
        self.root = Path(self.folder.name)
        self.local = self.root / "config_local.json"
        self.default = self.root / "config_default.json"
        self.default.write_text(
            json.dumps(
                {
                    "last_processing_settings": {"write_condensed_json": False, "add_temperature": False},
                    "last_valve_names": {"InSituReactor": {}},
                    "reactors": ["InSituReactor"],
                }
            ),
            encoding="utf-8",
        )
        self.log = self.root / "valve_name_log.jsonl"
        self.source = write_synthetic_run(
            self.root / "260101_12h00m__InSituReactor_Test_Reactor1_Data.json"
        )
        self.output = self.root / "out"
        self.state = AnalysisState()
        self.page = AnalyzePage(
            self.state,
            settings_path=self.local,
            default_settings_path=self.default,
            valve_log_path=self.log,
        )
        self.page.source_input.setText(str(self.source))
        self.page.output_input.setText(str(self.output))
        self.page.show()
        self.app.processEvents()

    def tearDown(self):
        if self.page.is_busy():
            self.wait_for_worker()
        self.page.cleanup()
        self.page.close()
        self.folder.cleanup()

    def wait_for_worker(self):
        thread = self.page._thread
        if thread is None:
            return
        loop = QEventLoop()
        thread.finished.connect(loop.quit)
        QTimer.singleShot(30000, loop.quit)
        loop.exec()
        self.app.processEvents()
        self.assertFalse(self.page.is_busy(), "Analyze worker did not finish")

    def load_header(self):
        self.page._load_header()
        self.wait_for_worker()
        self.assertEqual(self.state.source_path, self.source.resolve(), self.page.log_box.toPlainText())

    def test_run_analysis_from_form_matches_pipeline_and_preserves_raw_source(self):
        before = sha256_file(self.source)
        self.load_header()
        self.assertFalse(self.page.write_condensed.isChecked())
        self.assertTrue(self.page.run_all_button.isEnabled())
        self.assertEqual(self.page._valve_fields[7].text(), "TestValve")
        self.assertTrue(self.page._valve_fields[7].isReadOnly())
        self.page._run_action("run_all")
        self.wait_for_worker()
        self.assertIsNotNone(self.state.last_result, self.page.log_box.toPlainText())
        self.assertEqual(self.state.last_result["plots"], 2)
        self.assertTrue((self.output / "cycle_0001.png").is_file())
        self.assertTrue(self.local.is_file())
        self.assertTrue(self.log.is_file())
        self.assertEqual(sha256_file(self.source), before)
        self.assertIn(str(self.state.pipeline.working_path), self.page.path_summary.text())
        self.assertIn(str(self.output), self.page.path_summary.text())

    def test_condensed_input_is_explicit_and_cancel_does_not_write(self):
        condensed = condensed_path(self.source)
        condense_log(self.source, condensed)
        self.source = condensed
        self.page.source_input.setText(str(condensed))
        self.page.write_condensed.setChecked(True)
        self.load_header()
        before = sha256_file(condensed)
        self.assertIn("updated in place", self.page.overwrite_warning.text())
        self.assertIn(str(condensed), self.page.path_summary.text())
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.No) as warning:
            self.page._run_action("condense")
        warning.assert_called_once()
        self.assertEqual(sha256_file(condensed), before)
        self.assertFalse(self.local.exists())
        self.assertFalse(self.log.exists())
        self.assertFalse(self.page.is_busy())

    def test_output_collision_confirmation_can_cancel_without_writes(self):
        self.load_header()
        self.output.mkdir()
        existing = self.output / "cycle_0001.png"
        existing.write_bytes(b"existing")
        before = sha256_file(existing)
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.No) as warning:
            self.page._run_action("run_all")
        self.assertIn(str(existing), warning.call_args.args[2])
        self.assertEqual(sha256_file(existing), before)
        self.assertFalse(self.local.exists())

    def test_output_alias_of_raw_source_is_rejected(self):
        self.load_header()
        self.output.mkdir()
        os.link(self.source, self.output / f"{self.source.stem}_exposure.csv")
        before = sha256_file(self.source)
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes):
            self.page._run_action("run_all")
        self.wait_for_worker()
        self.assertEqual(sha256_file(self.source), before)
        self.assertIn("alias", self.page.log_box.toPlainText().lower())

    def test_existing_condensed_hardlink_is_replaced_without_changing_raw_input(self):
        destination = condensed_path(self.source)
        os.link(self.source, destination)
        before = sha256_file(self.source)
        self.page.write_condensed.setChecked(True)
        self.load_header()
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes) as warning:
            self.page._run_action("condense")
        self.wait_for_worker()
        self.assertIn(str(destination), warning.call_args.args[2])
        self.assertEqual(sha256_file(self.source), before)
        self.assertFalse(self.source.samefile(destination))
        self.assertEqual(self.state.pipeline.stage, "condensed")

    def test_separate_stages_are_available_after_condensation(self):
        self.load_header()
        for action, expected in (
            ("condense", "condensed"),
            ("label_phases", "labeled"),
            ("generate_outputs", "generated"),
        ):
            with self.subTest(action=action):
                self.page._run_action(action)
                self.wait_for_worker()
                self.assertEqual(self.state.pipeline.stage, expected, self.page.log_box.toPlainText())

    def test_explicit_ise_stage_remains_enabled_for_output_generation(self):
        self.load_header()
        self.page.ise_file.setText(str(Path(__file__).resolve().parents[1] / "Example_iSE_data.csv"))
        self.assertFalse(self.page.add_ise.isChecked())
        for action in ("condense", "label_phases", "attach_ise"):
            self.page._run_action(action)
            self.wait_for_worker()
        self.assertTrue(self.state.pipeline.ise_thickness_by_cycle, self.page.log_box.toPlainText())
        self.assertTrue(self.page.add_ise.isChecked())
        self.page._run_action("generate_outputs")
        self.wait_for_worker()
        self.assertTrue(self.state.last_result["thickness_csv"])
        self.assertTrue(Path(self.state.last_result["thickness_csv"]).is_file())

    def test_run_all_temperature_and_ise_match_direct_pipeline(self):
        self.load_header()
        telemetry = self.root / "temperature.jsonl"
        telemetry.write_text(
            "\n".join(
                json.dumps(
                    {
                        "ts": f"2026-01-01T12:00:{index:02d}",
                        "telemetry": {"zones": {"1": {"pv_c": 25 + index, "sp_abs": 30}}},
                    }
                )
                for index in range(14)
            ) + "\n",
            encoding="utf-8",
        )
        self.page.write_condensed.setChecked(True)
        self.page.add_temperature.setChecked(True)
        self.page.run_all_temperature.setChecked(True)
        self.page.temperature_mode.setCurrentIndex(1)
        self.page.temperature_files.setText(str(telemetry))
        self.page._detect_zones()
        self.wait_for_worker()
        self.page.add_ise.setChecked(True)
        self.page.ise_file.setText(str(Path(__file__).resolve().parents[1] / "Example_iSE_data.csv"))
        self.page.blank_rows.setText("1")

        direct_root = self.root / "direct"
        direct_root.mkdir()
        direct_source = write_synthetic_run(direct_root / self.source.name)
        snapshot = build_processing_snapshot(self.page._inputs(), self.state.header["experimentalDetails"])
        details = parse_experimental_details(self.state.header["experimentalDetails"])
        direct = ReactorPipeline(
            direct_source,
            str(direct_root / "output"),
            self.state.sequences,
            snapshot.to_options(),
            sequence_note_fn=lambda key, phased: sequence_note_text(key, phased, details),
        )
        before = sha256_file(self.source)
        try:
            expected = direct.run_all(attach_temperature=True, attach_ise=True)
            self.page._run_action("run_all")
            self.wait_for_worker()
            actual = self.state.last_result
            self.assertIsNotNone(actual, self.page.log_box.toPlainText())
            self.assertEqual((actual["plots"], actual["cycle_summaries"]), (expected["plots"], expected["cycle_summaries"]))
            for name in ("exposure_csv", "thickness_csv"):
                self.assertIsNotNone(actual[name], self.page.log_box.toPlainText())
                self.assertEqual(Path(actual[name]).read_bytes(), Path(expected[name]).read_bytes())
            with condensed_path(self.source).open(encoding="utf-8") as actual_file:
                actual_records = [json.loads(line) for line in actual_file]
            with condensed_path(direct_source).open(encoding="utf-8") as expected_file:
                expected_records = [json.loads(line) for line in expected_file]
            self.assertEqual(actual_records, expected_records)
            self.assertTrue(any("TemperatureZones" in record.get("payload", {}) for record in actual_records))
            self.assertTrue(self.state.pipeline.ise_thickness_by_cycle)
            self.assertEqual(sha256_file(self.source), before)
        finally:
            direct.cleanup()

    def test_temperature_zone_discovery_is_background_and_selectable(self):
        self.load_header()
        telemetry = self.root / "temperature.jsonl"
        telemetry.write_text(
            "\n".join(
                json.dumps({"ts": f"2026-01-01T12:00:0{index}", "telemetry": {"zones": {"1": {"pv_c": 25}}}})
                for index in (0, 1)
            ) + "\n",
            encoding="utf-8",
        )
        self.page.temperature_mode.setCurrentIndex(1)
        self.page.temperature_files.setText(str(telemetry))
        self.page._detect_zones()
        self.wait_for_worker()
        self.assertEqual(list(self.page._temperature_checks), ["1"])
        self.assertTrue(self.page._temperature_checks["1"].isChecked())
        self.assertTrue(self.page._plot_checks["1"].isChecked())
        self.assertIn("1 s", self.page.interval_label.text())


if __name__ == "__main__":
    unittest.main()
