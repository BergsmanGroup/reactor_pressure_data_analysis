"""PySide6 / QtAgg feasibility spike for the GUI migration (prompt 01).

Runs on Qt's offscreen platform so no window is shown.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import _helpers  # noqa: F401  (adds the repository root to sys.path)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Signal, Slot
    from PySide6.QtWidgets import QApplication, QMainWindow
except ImportError:  # pragma: no cover - environment without PySide6
    QApplication = None


def _app():
    return QApplication.instance() or QApplication([])


if QApplication is not None:

    class _Worker(QObject):
        progress = Signal(int)
        failed = Signal(str)
        finished = Signal()

        def __init__(self, fail: bool):
            super().__init__()
            self._fail = fail

        @Slot()
        def run(self):
            try:
                for pct in (0, 50, 100):
                    self.progress.emit(pct)
                if self._fail:
                    raise RuntimeError("simulated pipeline failure")
            except Exception as exc:  # noqa: BLE001 - worker boundary
                self.failed.emit(str(exc))
            finally:
                self.finished.emit()

    class _Receiver(QObject):
        def __init__(self):
            super().__init__()
            self.progress: list[int] = []
            self.errors: list[str] = []
            self.on_gui_thread: list[bool] = []

        @Slot(int)
        def on_progress(self, pct):
            self.on_gui_thread.append(QThread.currentThread() == QApplication.instance().thread())
            self.progress.append(pct)

        @Slot(str)
        def on_failed(self, message):
            self.on_gui_thread.append(QThread.currentThread() == QApplication.instance().thread())
            self.errors.append(message)


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class QtSpikeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _run_worker(self, fail: bool):
        receiver = _Receiver()
        thread = QThread()
        worker = _Worker(fail)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(receiver.on_progress)
        worker.failed.connect(receiver.on_failed)
        worker.finished.connect(thread.quit)

        loop = QEventLoop()
        thread.finished.connect(loop.quit)
        QTimer.singleShot(5000, loop.quit)
        thread.start()
        loop.exec()
        thread.wait(2000)
        self.app.processEvents()
        self.assertTrue(thread.isFinished(), "worker thread did not finish")
        return receiver

    def test_worker_progress_arrives_on_gui_thread(self):
        receiver = self._run_worker(fail=False)
        self.assertEqual(receiver.progress, [0, 50, 100])
        self.assertEqual(receiver.errors, [])
        self.assertTrue(receiver.on_gui_thread and all(receiver.on_gui_thread))

    def test_worker_errors_are_reported_through_signals(self):
        receiver = self._run_worker(fail=True)
        self.assertEqual(receiver.errors, ["simulated pipeline failure"])
        self.assertTrue(all(receiver.on_gui_thread))

    def test_qtagg_canvas_embeds_and_batch_saving_still_works(self):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        window = QMainWindow()
        fig = Figure(figsize=(4, 3))
        fig.add_subplot(111).plot([0, 1, 2], [0, 1, 4])
        canvas = FigureCanvasQTAgg(fig)
        window.setCentralWidget(canvas)
        window.resize(640, 480)
        window.show()
        canvas.draw()
        self.app.processEvents()
        self.assertGreater(canvas.width(), 0)

        # Non-interactive output path used by plot_utils must be unaffected.
        import matplotlib.pyplot as plt

        tmp = Path(tempfile.mkdtemp(prefix="qt_spike_"))
        try:
            batch_fig = Figure(figsize=(2, 2))
            batch_fig.add_subplot(111).plot([0, 1], [1, 0])
            out = tmp / "batch.png"
            batch_fig.savefig(out)
            self.assertGreater(out.stat().st_size, 0)
            plt.close("all")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            window.close()


class LegacyTkImportTests(unittest.TestCase):
    def test_tk_gui_module_still_imports(self):
        import gui

        self.assertTrue(hasattr(gui, "ReactorApp"))


if __name__ == "__main__":
    unittest.main()
