"""Offscreen tests for the PySide6 application shell."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QStackedWidget

from reactor_ui.main_window import MainWindow
from reactor_ui.theme import COLORS, apply_theme, create_palette


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
        self.assertEqual(self.window.minimumSize().width(), 1180)
        self.assertIsInstance(self.window.navigation_rail, QFrame)
        self.assertIsInstance(self.window.page_stack, QStackedWidget)
        self.assertEqual(self.window.page_stack.count(), 5)
        self.assertEqual(self.window.page_button("analyze").text(), "Analyze")
        self.assertEqual(self.window.page_button("recipe_editor").text(), "Recipe Editor")
        self.assertEqual(self.window.page_button("plots").text(), "Plots & Animation")
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

    def test_unimplemented_pages_are_explicit_not_fake(self):
        self.window.show_page("recipe_editor")
        self.app.processEvents()
        labels = self.window.page_widget("recipe_editor").findChildren(QLabel)
        self.assertTrue(any("has not been migrated yet" in label.text() for label in labels))


if __name__ == "__main__":
    unittest.main()
