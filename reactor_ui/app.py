"""Qt application startup."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from reactor_ui.main_window import MainWindow
from reactor_ui.theme import apply_theme


def main(argv: Sequence[str] | None = None) -> int:
    """Create and run the Qt application."""
    app = QApplication.instance()
    if app is None:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        app = QApplication(list(argv) if argv is not None else sys.argv)

    app.setApplicationName("Reactor Pressure Data Analyzer")
    apply_theme(app)

    window = MainWindow()
    window.show()
    return app.exec()
