"""Offscreen tests for the PySide6 application shell."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QRect, QTimer, Qt, qInstallMessageHandler
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QLineEdit, QMessageBox, QPushButton, QStackedWidget

from reactor_ui.main_window import MainWindow
from reactor_ui.theme import COLORS, apply_theme, create_palette
from reactor_ui.widgets.card import Card
from reactor_ui.widgets.window_geometry import fit_to_available_screen
from reactor_ui.workers.pipeline_worker import OperationWorker


_QT_MESSAGES: list[str] = []


def _capture_qt_message(message_type, context, message):
    del message_type, context
    _QT_MESSAGES.append(str(message))


class QtShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self):
        _QT_MESSAGES.clear()
        self._previous_message_handler = qInstallMessageHandler(_capture_qt_message)
        self.window = MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        qInstallMessageHandler(self._previous_message_handler)

    def test_window_layout_and_pages_construct(self):
        self.assertEqual(self.window.windowTitle(), "Reactor Pressure Data Analyzer")
        self.assertEqual(self.window.size().width(), 1440)
        self.assertEqual(self.window.minimumSize().width(), 760)
        self.assertIsInstance(self.window.navigation_rail, QFrame)
        self.assertIsInstance(self.window.page_stack, QStackedWidget)
        self.assertEqual(self.window.page_stack.count(), 5)
        self.assertEqual(self.window.page_button("analyze").text(), "Analyze")
        self.assertEqual(self.window.page_button("recipe_editor").text(), "Recipe Editor")
        self.assertEqual(self.window.page_button("plots").text(), "Plots && Animation")
        self.assertEqual(self.window.page_button("settings").text(), "Settings")
        self.assertEqual(self.window.page_button("help").text(), "Help")
        self.assertTrue(self.window.page_button("analyze").isChecked())

    def test_navigation_switches_pages_and_marks_active_button(self):
        for page_id in ("recipe_editor", "plots", "settings", "help", "analyze"):
            with self.subTest(page=page_id):
                button = self.window.page_button(page_id)
                button.click()
                self.app.processEvents()
                self.assertIs(self.window.page_stack.currentWidget(), self.window.page_widget(page_id))
                self.assertTrue(button.isChecked())

    def test_keyboard_navigation_and_accessible_names(self):
        for page_id in ("recipe_editor", "plots", "settings", "help", "analyze"):
            button = self.window.page_button(page_id)
            self.assertTrue(button.accessibleName())
            button.setFocus()
            QTest.keyClick(button, Qt.Key.Key_Space)
            self.assertIs(self.window.page_stack.currentWidget(), self.window.page_widget(page_id))
        recipe = self.window.recipe_editor
        self.assertEqual(recipe.timing_table.accessibleName(), "Recipe timing table")
        self.assertTrue(recipe.timeline.accessibleName())
        self.assertIn("arrows", recipe.timeline.accessibleDescription())
        for field in (recipe.username_input, recipe.description_input, recipe.did_input, recipe.edr_input):
            self.assertTrue(field.accessibleName())

    def test_tab_navigation_reaches_compact_recipe_table(self):
        recipe = self.window.recipe_editor
        recipe.open_recipe(Path(__file__).resolve().parents[1] / "Example recipe sheet.csv")
        self.window.resize(835, 470)
        self.window.show_page("recipe_editor")
        self.app.processEvents()
        recipe.new_button.setFocus()
        for _ in range(150):
            focused = self.app.focusWidget()
            self.assertIsNotNone(focused)
            if focused is recipe.timing_table:
                break
            QTest.keyClick(focused, Qt.Key.Key_Tab)
            self.app.processEvents()
        else:
            self.fail("Keyboard focus did not reach the recipe timing table")
        self.assertGreater(self.window.page_scroll.verticalScrollBar().value(), 0)

    def test_small_window_scrolls_and_fits_available_screen(self):
        self.window.resize(800, 500)
        self.window.show_page("recipe_editor")
        self.app.processEvents()
        self.assertEqual(self.window.size().toTuple(), (800, 500))
        self.assertGreater(self.window.page_scroll.verticalScrollBar().maximum(), 0)
        self.window.resize(1440, 900)
        fit_to_available_screen(self.window)
        available = self.window.screen().availableGeometry()
        self.assertLessEqual(self.window.width(), available.width())
        self.assertLessEqual(self.window.height(), available.height())

    def test_fit_reduces_minimum_size_on_a_very_small_screen(self):
        screen = type("Screen", (), {"availableGeometry": lambda self: QRect(0, 0, 650, 400)})()
        with patch.object(self.window, "screen", return_value=screen):
            fit_to_available_screen(self.window)
        self.assertEqual(self.window.minimumSize().toTuple(), (618, 336))
        self.assertLessEqual(self.window.width(), 650)
        self.assertLessEqual(self.window.height(), 400)

    def test_splitters_can_shrink_before_the_outer_page_scrolls(self):
        self.window.show_page("recipe_editor")
        minimum = self.window.page_stack.minimumSizeHint()
        self.window.resize(max(1050, minimum.width() + self.window.navigation_rail.width() + 20), minimum.height() + 20)
        self.app.processEvents()
        self.assertEqual(self.window.page_scroll.verticalScrollBar().maximum(), 0)
        self.assertEqual(self.window.page_scroll.horizontalScrollBar().maximum(), 0)

    def test_compact_layout_stacks_panels_without_horizontal_clipping(self):
        self.window.resize(835, 470)
        self.window.show_page("recipe_editor")
        self.app.processEvents()
        self.assertEqual(self.window.navigation_rail.width(), 160)
        self.assertEqual(self.window.page_button("plots").text(), "Plots")
        self.assertEqual(self.window.recipe_editor.metadata_splitter.orientation(), Qt.Orientation.Vertical)
        self.assertEqual(self.window.recipe_editor.lower_splitter.orientation(), Qt.Orientation.Vertical)
        self.assertEqual(self.window.analyze_page.content_splitter.orientation(), Qt.Orientation.Vertical)
        self.assertEqual(self.window.settings_page.content_splitter.orientation(), Qt.Orientation.Vertical)
        for page_id in ("analyze", "recipe_editor", "plots", "settings", "help"):
            self.window.show_page(page_id)
            self.app.processEvents()
            with self.subTest(page=page_id):
                self.assertEqual(self.window.page_scroll.horizontalScrollBar().maximum(), 0)
        self.window.show_page("recipe_editor")
        self.app.processEvents()
        self.window.page_scroll.verticalScrollBar().setValue(self.window.page_scroll.verticalScrollBar().maximum())
        self.window.show_page("settings")
        self.app.processEvents()
        self.assertEqual(self.window.page_scroll.verticalScrollBar().value(), 0)
        self.window.resize(1300, 800)
        self.app.processEvents()
        self.assertEqual(self.window.navigation_rail.width(), 204)
        self.assertEqual(self.window.page_button("plots").text(), "Plots && Animation")
        self.assertEqual(self.window.recipe_editor.metadata_splitter.orientation(), Qt.Orientation.Horizontal)

    def test_theme_palette_and_stylesheet_apply_without_parse_warnings(self):
        self.assertEqual(
            self.app.palette().color(QPalette.ColorRole.Window).name(),
            COLORS["background"].lower(),
        )
        self.assertEqual(
            create_palette().color(QPalette.ColorRole.Highlight).name(),
            COLORS["selection"].lower(),
        )
        self.assertIn("QFrame#card", self.app.styleSheet())
        self.assertFalse(
            any("Could not parse stylesheet" in message for message in _QT_MESSAGES),
            "\n".join(_QT_MESSAGES),
        )

    def test_card_controls_have_solid_distinct_backgrounds(self):
        card = Card("Solid controls", accent="info")
        try:
            for name, tone, expected in (
                ("", "", "button"),
                ("primaryButton", "", "primary"),
                ("", "success", "success_button"),
                ("", "warning", "warning_button"),
            ):
                button = QPushButton("Action", card)
                button.setObjectName(name)
                button.setProperty("actionTone", tone)
                card.add_widget(button)
                card.show()
                self.app.processEvents()
                image = button.grab().toImage()
                self.assertEqual(image.pixelColor(5, 5).name(), COLORS[expected].lower())
                button.setEnabled(False)
                self.app.processEvents()
                self.assertNotEqual(button.grab().toImage().pixelColor(5, 5).name(), COLORS[expected].lower())
            field = QLineEdit("Value", card)
            card.add_widget(field)
            self.app.processEvents()
            self.assertEqual(field.grab().toImage().pixelColor(5, 5).name(), COLORS["surface_raised"].lower())
        finally:
            card.close()

    def test_action_colors_meet_normal_text_contrast(self):
        def luminance(color):
            channels = (color.redF(), color.greenF(), color.blueF())
            linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
            return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

        foreground = luminance(QColor(COLORS["text"]))
        for token in ("button", "button_hover", "primary", "primary_hover", "info", "info_hover",
                      "success_button", "success_hover", "warning_button", "warning_hover",
                      "danger_button", "danger_hover"):
            with self.subTest(color=token):
                self.assertGreaterEqual((foreground + 0.05) / (luminance(QColor(COLORS[token])) + 0.05), 4.5)

    def test_numeric_fields_and_actions_do_not_expand_across_cards(self):
        self.window.resize(1670, 940)
        self.app.processEvents()
        page = self.window.analyze_page
        self.assertLessEqual(page.options_column.width(), 420)
        for field in (page.xlim, page.ylim, page.shift, page.wait, page.fps, page.leakrate_reduction,
                      page.blank_rows, page.grid_x_spacing, page.grid_y_spacing, page.temperature_interval):
            self.assertLessEqual(field.width(), 128)
        self.window.show_page("recipe_editor")
        self.app.processEvents()
        recipe = self.window.recipe_editor
        self.assertLess(recipe.add_valve_button.width(), recipe.valve_card.width() // 2)
        self.assertLessEqual(recipe.wait_input.width(), 128)
        self.assertLessEqual(recipe.edr_input.width(), 100)

    def test_offscreen_screenshot_captures_rail_and_page(self):
        self.window.resize(1440, 900)
        self.app.processEvents()
        pixmap = self.window.grab()
        self.assertEqual(pixmap.size().width(), 1440)
        self.assertEqual(pixmap.size().height(), 900)
        with tempfile.TemporaryDirectory(prefix="reactor_qt_shell_") as temp_dir:
            screenshot = Path(temp_dir) / "qt_shell.png"
            self.assertTrue(pixmap.save(str(screenshot), "PNG"))
            self.assertGreater(screenshot.stat().st_size, 5_000)

    def test_pages_use_real_workflows(self):
        self.assertIs(self.window.page_widget("analyze"), self.window.analyze_page)
        self.assertIs(self.window.page_widget("plots"), self.window.plots_page)
        self.assertIs(self.window.page_widget("settings"), self.window.settings_page)
        self.assertIs(self.window.page_widget("help"), self.window.help_page)

    def test_unsaved_settings_prevent_closing_without_confirmation(self):
        self.window.settings_page.text_fields["fps"].setText("12")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as question:
            self.assertFalse(self.window.close())
        self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.No)
        self.assertTrue(self.window.isVisible())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(self.window.close())

    def test_close_waits_for_active_worker_and_controls_are_restored(self):
        gate = threading.Event()
        page = self.window.analyze_page
        worker = OperationWorker("Wait", lambda _progress, _log: gate.wait(10))
        page._start_worker(worker, lambda _result: None)
        thread = page._thread
        try:
            self.assertFalse(page.source_input.isEnabled())
            with patch.object(QMessageBox, "warning") as warning:
                self.assertFalse(self.window.close())
            warning.assert_called_once()
            self.assertTrue(self.window.isVisible())
        finally:
            gate.set()
            loop = QEventLoop()
            thread.finished.connect(loop.quit)
            QTimer.singleShot(10000, loop.quit)
            loop.exec()
            self.app.processEvents()
        self.assertFalse(page.is_busy())
        self.assertTrue(page.source_input.isEnabled())


if __name__ == "__main__":
    unittest.main()
