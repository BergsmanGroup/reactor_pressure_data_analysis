"""Keep desktop windows within the available logical screen area."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget


def fit_to_available_screen(window: QWidget) -> None:
    screen = window.screen()
    if screen is None:
        return
    available = screen.availableGeometry()
    width = max(1, available.width() - 32)
    height = max(1, available.height() - 64)
    window.setMinimumSize(min(window.minimumWidth(), width), min(window.minimumHeight(), height))
    window.resize(
        min(window.width(), width),
        min(window.height(), height),
    )
