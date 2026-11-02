"""QtAgg previews and shared-state output generation."""

from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import matplotlib

matplotlib.use("Agg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox

from _helpers import sha256_file
from _synthetic_run import write_synthetic_run
from analysis_metadata import parse_experimental_details, sequence_note_text
from data_parser import read_header
from pipeline import ReactorPipeline
from reactor_ui.adapters.analysis_controller import build_processing_snapshot
from reactor_ui.models.analysis_state import AnalysisState
from reactor_ui.pages.analyze_page import AnalyzePage
from reactor_ui.pages.plots_page import PlotsPage
from sequence_utils import convert_sequence


class PlotsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="qt_plots_")
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
        self.state = AnalysisState()
        self.analyze = AnalyzePage(
            self.state,
            settings_path=self.root / "local.json",
            default_settings_path=default,
            valve_log_path=self.root / "valves.jsonl",
        )
        self.plots = PlotsPage(self.state, self.analyze)
        self.analyze.source_input.setText(str(self.source))
        self.analyze.output_input.setText(str(self.root / "output"))
        self.plots.resize(1300, 850)
        self.plots.show()
        self.analyze._load_header()
        self.wait_for_worker()

    def tearDown(self):
        self.wait_for_worker()
        self.analyze.cleanup()
        self.plots.close()
        self.analyze.close()
        self.folder.cleanup()

    def wait_for_worker(self):
        thread = self.analyze._thread
        if thread is not None:
            loop = QEventLoop()
            thread.finished.connect(loop.quit)
            QTimer.singleShot(30000, loop.quit)
            loop.exec()
            self.app.processEvents()
            self.assertFalse(self.state.busy)

    def direct_pipeline(self, source: Path, output: Path) -> ReactorPipeline:
        header = read_header(source)
        details = parse_experimental_details(header["experimentalDetails"])
        snapshot = build_processing_snapshot(self.analyze._inputs(), header["experimentalDetails"])
        return ReactorPipeline(
            source,
            str(output),
            convert_sequence(header["valveSequence"]),
            snapshot.to_options(),
            sequence_note_fn=lambda key, phased: sequence_note_text(key, phased, details),
        )

    def test_preview_renders_same_cycle_as_backend_and_reports_errors(self):
        direct = self.direct_pipeline(self.source, self.root / "direct")
        expected = direct.preview_cycle(1)
        self.plots.preview_button.click()
        self.assertTrue(self.state.busy)
        self.assertFalse(self.plots.preview_button.isEnabled())
        self.wait_for_worker()
        canvas = self.plots.canvas
        self.assertIsInstance(canvas, FigureCanvasQTAgg)
        self.assertIsInstance(self.plots.toolbar, NavigationToolbar2QT)
        self.assertGreater(canvas.width(), 100)
        self.assertGreater(canvas.height(), 100)
        actual_axes = canvas.figure.axes[0]
        expected_axes = expected.axes[0]
        self.assertEqual(actual_axes.get_xlim(), expected_axes.get_xlim())
        self.assertEqual(actual_axes.get_ylim(), expected_axes.get_ylim())
        self.assertEqual(
            [(line.get_xdata().tolist(), line.get_ydata().tolist()) for line in actual_axes.lines],
            [(line.get_xdata().tolist(), line.get_ydata().tolist()) for line in expected_axes.lines],
        )
        self.plots.next_button.click()
        self.wait_for_worker()
        self.assertEqual(self.plots.preview_label.text(), "Showing cycle 2")
        canvas = self.plots.canvas
        self.plots.cycle.setValue(999)
        self.plots.preview_button.click()
        self.wait_for_worker()
        self.assertIn("Cycle 999 not found", self.plots.status.text())
        self.assertIs(self.plots.canvas, canvas)
        expected.clear()
        direct.cleanup()

    def test_generation_matches_direct_pipeline_and_open_actions(self):
        direct_dir = self.root / "direct"
        direct_dir.mkdir()
        direct_source = write_synthetic_run(direct_dir / self.source.name)
        direct = self.direct_pipeline(direct_source, direct_dir / "output")
        before = sha256_file(self.source)
        try:
            direct.condense()
            expected = direct.generate_outputs()
            self.analyze._run_action("condense")
            self.wait_for_worker()
            self.assertTrue(self.plots.generate_button.isEnabled())
            self.plots.generate_button.click()
            self.wait_for_worker()
            actual = self.state.last_result
            self.assertIsNotNone(actual, self.analyze.log_box.toPlainText())
            self.assertEqual(actual["plots"], expected["plots"])
            self.assertEqual(actual["cycle_summaries"], expected["cycle_summaries"])
            with open(expected["exposure_csv"], encoding="utf-8", newline="") as one, open(
                actual["exposure_csv"], encoding="utf-8", newline=""
            ) as two:
                self.assertEqual(list(csv.DictReader(one)), list(csv.DictReader(two)))
            for cycle in (1, 2):
                with Image.open(direct_dir / "output" / f"cycle_{cycle:04d}.png") as one, Image.open(
                    self.root / "output" / f"cycle_{cycle:04d}.png"
                ) as two:
                    self.assertEqual(one.size, two.size)
            with Image.open(expected["animation"]) as one, Image.open(actual["animation"]) as two:
                self.assertEqual((one.size, one.n_frames), (two.size, two.n_frames))
            self.assertEqual(sha256_file(self.source), before)
            with patch.object(QDesktopServices, "openUrl", return_value=True) as open_url:
                self.plots.open_directory_button.click()
                self.plots.open_animation_button.click()
            self.assertEqual(open_url.call_count, 2)
            self.assertEqual(Path(open_url.call_args_list[0].args[0].toLocalFile()), self.root / "output")
            self.assertEqual(Path(open_url.call_args_list[1].args[0].toLocalFile()), Path(actual["animation"]))
        finally:
            direct.cleanup()

    def test_generate_does_not_prompt_before_overwriting(self):
        self.analyze._run_action("condense")
        self.wait_for_worker()
        output = self.root / "output"
        output.mkdir()
        existing = output / "cycle_0001.png"
        existing.write_bytes(b"existing")
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.No) as warning:
            self.plots.generate_button.click()
        warning.assert_not_called()
        self.wait_for_worker()
        self.assertNotEqual(existing.read_bytes(), b"existing")
        self.assertFalse(self.state.busy)


if __name__ == "__main__":
    unittest.main()
