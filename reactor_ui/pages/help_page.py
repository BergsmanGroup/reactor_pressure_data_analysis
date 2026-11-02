"""Local documentation links and runtime information."""

from __future__ import annotations

import platform
from pathlib import Path

import PySide6
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from reactor_ui import APPLICATION_VERSION
from reactor_ui.widgets.card import Card
from reactor_ui.widgets.page_header import PageHeader


class HelpPage(QWidget):
    def __init__(self, root: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.root = root or Path(__file__).resolve().parents[2]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 24)
        layout.setSpacing(14)
        layout.addWidget(PageHeader("Help", "Open the project's maintained documentation.", self))
        docs = Card("Documentation", self)
        self.documentation_buttons: dict[str, QPushButton] = {}
        for label, path in (
            ("Technical Whitepaper", self.root / "WHITEPAPER.md"),
            ("Processing Workflow Review", self.root / "PROCESSING_WORKFLOW_REVIEW.md"),
            ("Documentation Folder", self.root / "docs"),
        ):
            button = QPushButton(label, docs)
            button.clicked.connect(lambda _checked=False, target=path: self._open(target))
            self.documentation_buttons[label] = button
            docs.add_widget(button)
        layout.addWidget(docs)
        versions = Card("Application and Runtime", self)
        version = APPLICATION_VERSION or "Not specified in this checkout"
        self.version_label = QLabel(
            f"Application version: {version}\nPython: {platform.python_version()}\nPySide6: {PySide6.__version__}",
            versions,
        )
        self.version_label.setWordWrap(True)
        self.version_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        versions.add_widget(self.version_label)
        layout.addWidget(versions)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.status)
        layout.addStretch(1)

    def _open(self, path: Path) -> None:
        if not path.exists():
            self.status.setText(f"ERROR: documentation path does not exist: {path}")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.status.setText(f"ERROR: could not open documentation: {path}")
        else:
            self.status.setText(f"Opened: {path}")
