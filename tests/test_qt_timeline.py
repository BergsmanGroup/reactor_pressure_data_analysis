"""Interaction and proportional-layout tests for the recipe timeline."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTableView

from _helpers import OWNER_EXAMPLE_CSV, sha256_file
from reactor_ui.models.recipe_timing import compute_run_timing
from reactor_ui.pages.recipe_editor_page import RecipeEditorPage
from reactor_ui.widgets.run_timeline import RunTimeline, _tick_labels


class TimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = RunTimeline()
        self.widget.resize(600, 190)
        self.widget.show()
        self.app.processEvents()

    def tearDown(self):
        self.widget.close()

    def test_widths_boundaries_mouse_and_keyboard(self):
        run = compute_run_timing(
            [
                ["1", "5", "10", "0", "0", "0", "0", "0", "0"],
                ["3", "7", "10", "0", "0", "0", "0", "0", "0"],
            ]
        )
        self.widget.set_run(run)
        rects = self.widget.sequence_rects()
        self.assertAlmostEqual(rects[1][1].width(), 3 * rects[0][1].width())
        self.assertAlmostEqual(sum(rect.width() for _, rect in rects), self.widget.overview_rect().width())
        self.widget.set_playhead(10)
        self.assertEqual(self.widget.selected_sequence.index, 2)
        self.widget.set_playhead(40)
        self.assertEqual(self.widget.selected_sequence.index, 2)

        overview = self.widget.overview_rect()
        y = int(overview.center().y())
        QTest.mousePress(self.widget, Qt.MouseButton.LeftButton, pos=QPoint(int(overview.left()), y))
        QTest.mouseMove(self.widget, QPoint(int(overview.left() + overview.width() * 0.75), y))
        QTest.mouseRelease(
            self.widget, Qt.MouseButton.LeftButton, pos=QPoint(int(overview.left() + overview.width() * 0.75), y)
        )
        self.assertAlmostEqual(self.widget.playhead_seconds, 30, delta=0.1)
        self.assertEqual(self.widget.selected_sequence.index, 2)
        QTest.keyClick(self.widget, Qt.Key.Key_Home)
        self.assertEqual(self.widget.selected_sequence.index, 1)
        QTest.keyClick(self.widget, Qt.Key.Key_Right)
        self.assertEqual(self.widget.selected_sequence.index, 2)
        QTest.keyClick(self.widget, Qt.Key.Key_Left)
        self.assertEqual(self.widget.selected_sequence.index, 1)
        self.assertFalse(self.widget.grab().isNull())

    def test_zero_duration_sequences_remain_selectable(self):
        run = compute_run_timing(
            [
                ["1", "5", "0", "0", "0", "0", "0", "0", "0"],
                ["1", "7", "0", "0", "0", "0", "0", "0", "0"],
            ]
        )
        self.widget.set_run(run)
        self.assertEqual(self.widget.sequence_rects(), [])
        self.widget.select_sequence(2)
        self.assertEqual(self.widget.selected_sequence.index, 2)
        self.assertEqual(self.widget.playhead_seconds, 0)

    def test_playhead_is_clamped_when_run_shrinks(self):
        long_run = compute_run_timing([["1", "5", "100", "0", "0", "0", "0", "0", "0"]])
        short_run = compute_run_timing([["1", "5", "20", "0", "0", "0", "0", "0", "0"]])
        self.widget.set_run(long_run)
        self.widget.set_playhead(80)
        self.widget.set_run(short_run)
        self.assertEqual(self.widget.playhead_seconds, 20)

    def test_time_tick_labels_do_not_overlap_on_narrow_timelines(self):
        labels = _tick_labels(QRectF(0, 0, 220, 26), 80425, self.widget.fontMetrics())
        self.assertEqual(labels[0][0], "0 h")
        self.assertEqual(labels[-1][0], "22.3 h")
        for (_, left), (_, right) in zip(labels, labels[1:]):
            self.assertLessEqual(left.right() + 4, right.left())

    def test_table_and_timeline_synchronize_without_modifying_recipe(self):
        with tempfile.TemporaryDirectory(prefix="qt_timeline_") as folder:
            source = Path(folder) / "recipe.csv"
            source.write_text(OWNER_EXAMPLE_CSV, encoding="utf-8")
            before = sha256_file(source)
            page = RecipeEditorPage()
            try:
                page.resize(1400, 900)
                page.open_recipe(source)
                page.show()
                self.app.processEvents()
                original_rows = [row[:] for row in page.document.rows]
                page.timeline.select_sequence(3)
                self.assertEqual(page.timing_table.currentIndex().row(), 2)
                self.assertEqual(
                    [index.row() for index in page.timing_table.selectionModel().selectedRows()],
                    [2, 3, 4, 5, 6, 7],
                )
                page.timing_table.setCurrentIndex(page.table_model.index(8, 2))
                self.assertEqual(page.timeline.selected_sequence.index, 4)
                self.assertEqual(page.timeline.playhead_seconds, 81365)
                page.timing_table.setCurrentIndex(page.table_model.index(4, 2))
                self.assertEqual(page.timeline.selected_sequence.index, 3)
                self.assertEqual(page.timing_table.currentIndex().row(), 4)
                page.time_control.setValue(100)
                self.assertEqual(page.timeline.selected_sequence.index, 1)
                self.assertEqual(page.document.rows, original_rows)
                self.assertEqual(sha256_file(source), before)
                self.assertEqual(len(page.findChildren(QTableView)), 1)
            finally:
                page.close()

    def test_long_recipe_keeps_cycles_compact_and_remains_interactive(self):
        prefix = OWNER_EXAMPLE_CSV[:OWNER_EXAMPLE_CSV.index("Cycles,Valve,")]
        header = "Cycles,Valve,PrePump,N2Dose,PumpDose,Dose,Hold,PrePurge,Purge,Notes\n"
        rows = "".join(
            f'{1000000 if index % 10 == 0 else ""},7,1,0,0,0,0,0,0,\n'
            for index in range(600)
        )
        with tempfile.TemporaryDirectory(prefix="qt_long_recipe_") as folder:
            source = Path(folder) / "large.csv"
            source.write_text(prefix + header + rows, encoding="utf-8")
            before = sha256_file(source)
            page = RecipeEditorPage()
            try:
                page.resize(1400, 900)
                page.show()
                started = time.perf_counter()
                page.open_recipe(source)
                self.app.processEvents()
                self.assertEqual(page.table_model.rowCount(), 600)
                self.assertEqual(page.document.sequence_count, 60)
                self.assertEqual(page.document.run_seconds, 600_000_000)
                self.assertEqual(sum(sequence.cycle_count for sequence in page.document.timing.sequences), 60_000_000)
                self.assertEqual(sum(len(sequence.events) for sequence in page.document.timing.sequences), 600)
                page.table_model.setData(page.table_model.index(0, 4), "2")
                page.timeline.select_sequence(60)
                self.app.processEvents()
                self.assertEqual(page.document.run_seconds, 601_000_000)
                self.assertEqual(page.timeline.selected_sequence.index, 60)
                self.assertFalse(page.timeline.grab().isNull())
                self.assertLess(time.perf_counter() - started, 10.0)
                self.assertEqual(sha256_file(source), before)
            finally:
                page.close()


if __name__ == "__main__":
    unittest.main()
