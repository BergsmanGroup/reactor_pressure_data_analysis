"""Processing snapshots, shared settings, and Qt pipeline worker tests."""

from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import matplotlib

matplotlib.use("Agg")

from PIL import Image
from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Slot
from PySide6.QtWidgets import QApplication

from _helpers import sha256_file
from _synthetic_run import write_synthetic_run
from analysis_metadata import parse_experimental_details, sequence_note_text
from data_parser import read_header
from pipeline import ProcessingOptions, ReactorPipeline
from reactor_ui.adapters.analysis_controller import AnalysisInputs, build_processing_snapshot
from reactor_ui.workers.pipeline_worker import OperationWorker, PipelineWorker
from sequence_utils import convert_sequence
from settings_store import load_settings_state, save_settings_state


class _Receiver(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.progress: list[int] = []
        self.logs: list[str] = []
        self.results: list[object] = []
        self.errors: list[str] = []
        self.gui_thread: list[bool] = []

    @Slot(int, str)
    def on_progress(self, value: int, _label: str) -> None:
        self.gui_thread.append(QThread.currentThread() == QApplication.instance().thread())
        self.progress.append(value)

    @Slot(str)
    def on_log(self, text: str) -> None:
        self.gui_thread.append(QThread.currentThread() == QApplication.instance().thread())
        self.logs.append(text)

    @Slot(object)
    def on_finished(self, value: object) -> None:
        self.gui_thread.append(QThread.currentThread() == QApplication.instance().thread())
        self.results.append(value)

    @Slot(str)
    def on_failed(self, text: str) -> None:
        self.gui_thread.append(QThread.currentThread() == QApplication.instance().thread())
        self.errors.append(text)


class AnalysisWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def run_worker(self, worker: OperationWorker) -> _Receiver:
        receiver = _Receiver()
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(receiver.on_progress)
        worker.log.connect(receiver.on_log)
        worker.finished.connect(receiver.on_finished)
        worker.failed.connect(receiver.on_failed)
        worker.done.connect(thread.quit)
        loop = QEventLoop()
        thread.finished.connect(loop.quit)
        QTimer.singleShot(30000, loop.quit)
        thread.start()
        loop.exec()
        thread.wait(5000)
        self.app.processEvents()
        self.assertTrue(thread.isFinished())
        return receiver

    def test_snapshot_matches_tk_mapping_and_is_immutable(self):
        values = AnalysisInputs(
            valve_names=((7, "manual"), (12, "LeakRate")),
            xlim="auto",
            ylim="10",
            grid_x=True,
            grid_y=False,
            grid_x_spacing="2",
            shift="2",
            wait_time="15",
            leakrate_phase_reduction="0.5",
            temperature_source=("a.jsonl", "b.jsonl"),
            selected_temperature_zones=("1", "3"),
            plot_temperature_zones=("3",),
            temperature_sample_interval_s="5",
            add_temperature=True,
            add_ise=True,
            ise_file_path="sample.csv",
            ise_valve="Valve7",
            ise_first_cycle="1.5",
            thickness_blank_rows="2",
            fps="6",
        )
        details = {"ValvePrecursor": [None, 7], "Name": ["Chamber", "header name"]}
        snapshot = build_processing_snapshot(values, details)
        expected = ProcessingOptions(
            valve_names={7: "header name", 12: "LeakRate"},
            xlim=None,
            ylim=10,
            grid_x=True,
            grid_y=False,
            grid_x_spacing=2,
            grid_y_spacing=None,
            shift=2,
            wait_time=15,
            leakrate_phase_reduction=0.5,
            write_condensed_json=True,
            add_temperature=True,
            add_ise=True,
            temperature_source=["a.jsonl", "b.jsonl"],
            selected_temperature_zones=["1", "3"],
            temperature_sample_interval_s=5,
            plot_temperature_zones=["3"],
            ise_file_path="sample.csv",
            ise_valve="Valve7",
            ise_first_cycle=1.5,
            thickness_blank_rows=2,
            fps=6,
        )
        self.assertEqual(snapshot.to_options(), expected)
        with self.assertRaises(FrozenInstanceError):
            snapshot.fps = 10
        snapshot.to_options().valve_names[7] = "changed"
        self.assertEqual(dict(snapshot.valve_names)[7], "header name")
        for bad in (AnalysisInputs(fps="0"), AnalysisInputs(wait_time="nan"), AnalysisInputs(grid_x_spacing="-1")):
            with self.assertRaises(ValueError):
                build_processing_snapshot(bad, {})

    def test_settings_round_trip_without_touching_repository_config(self):
        with tempfile.TemporaryDirectory(prefix="qt_settings_") as folder:
            root = Path(folder)
            default = root / "config_default.json"
            local = root / "config_local.json"
            state = {"last_processing_settings": {"shift": "2"}, "last_valve_names": {}, "reactors": ["R1"]}
            default.write_text(json.dumps(state), encoding="utf-8")
            self.assertEqual(load_settings_state(local, default, create_local=False), state)
            self.assertFalse(local.exists())
            state["last_processing_settings"]["shift"] = "3"
            save_settings_state(local, state)
            self.assertEqual(load_settings_state(local, default), state)

    def test_worker_success_and_failure_signals_arrive_on_gui_thread(self):
        def good(progress, log):
            log("working")
            progress(50)
            return {"ok": True}

        receiver = self.run_worker(OperationWorker("Test", good))
        self.assertEqual(receiver.results, [{"ok": True}])
        self.assertEqual(receiver.progress, [50])
        self.assertEqual(receiver.logs, ["working"])
        self.assertFalse(receiver.errors)
        self.assertTrue(all(receiver.gui_thread))

        def bad(_progress, _log):
            raise RuntimeError("deliberate failure")

        receiver = self.run_worker(OperationWorker("Test", bad))
        self.assertEqual(receiver.results, [])
        self.assertIn("deliberate failure", receiver.errors[0])
        self.assertTrue(all(receiver.gui_thread))

    def test_worker_outputs_match_direct_pipeline_on_synthetic_raw_run(self):
        with tempfile.TemporaryDirectory(prefix="qt_pipeline_") as folder:
            root = Path(folder)
            direct_dir = root / "direct"
            worker_dir = root / "worker"
            direct_dir.mkdir()
            worker_dir.mkdir()
            filename = "260101_12h00m__InSituReactor_Test_Reactor1_Data.json"
            direct_source = write_synthetic_run(direct_dir / filename)
            worker_source = write_synthetic_run(worker_dir / filename)
            before = sha256_file(worker_source)
            header = read_header(direct_source)
            seq = convert_sequence(header["valveSequence"])
            details = parse_experimental_details(header["experimentalDetails"])
            note = lambda key, phased: sequence_note_text(key, phased, details)
            options = ProcessingOptions(valve_names={7: "TestValve"}, write_condensed_json=False, fps=2)
            direct = ReactorPipeline(direct_source, str(direct_dir / "out"), seq, options, sequence_note_fn=note)
            threaded = ReactorPipeline(
                worker_source,
                str(worker_dir / "out"),
                seq,
                ProcessingOptions(valve_names={7: "TestValve"}, write_condensed_json=False, fps=2),
                sequence_note_fn=note,
            )
            try:
                direct_result = direct.run_all()
                receiver = self.run_worker(PipelineWorker(threaded, "run_all"))
                self.assertFalse(receiver.errors, receiver.errors)
                self.assertEqual(len(receiver.results), 1)
                worker_result = receiver.results[0]
                self.assertEqual(worker_result["plots"], direct_result["plots"])
                self.assertEqual(worker_result["cycle_summaries"], direct_result["cycle_summaries"])
                for name in ("exposure_csv",):
                    with open(direct_result[name], encoding="utf-8", newline="") as source:
                        expected = list(csv.DictReader(source))
                    with open(worker_result[name], encoding="utf-8", newline="") as source:
                        self.assertEqual(list(csv.DictReader(source)), expected)
                for cycle in (1, 2):
                    with Image.open(direct_dir / "out" / f"cycle_{cycle:04d}.png") as a, Image.open(
                        worker_dir / "out" / f"cycle_{cycle:04d}.png"
                    ) as b:
                        self.assertEqual(a.size, b.size)
                with Image.open(direct_result["animation"]) as a, Image.open(worker_result["animation"]) as b:
                    self.assertEqual((a.size, a.n_frames), (b.size, b.n_frames))
                self.assertEqual(sha256_file(worker_source), before)
            finally:
                direct.cleanup()
                threaded.cleanup()


if __name__ == "__main__":
    unittest.main()
