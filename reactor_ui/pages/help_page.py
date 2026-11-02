"""Local documentation links and runtime information."""

from __future__ import annotations

import platform
from pathlib import Path

import PySide6
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from reactor_ui import APPLICATION_VERSION
from reactor_ui.widgets.card import Card
from reactor_ui.widgets.page_header import PageHeader


class DocumentationWindow(QDialog):
    """Modeless Markdown reader for a local documentation file."""

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.setWindowTitle(path.stem.replace("_", " "))
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setModal(False)
        self.resize(900, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        self.reader = QTextBrowser(self)
        self.reader.setObjectName("documentationReader")
        self.reader.setOpenExternalLinks(True)
        self.reader.document().setDefaultStyleSheet(
            """
            body { color: #F4F7FF; font-family: "Segoe UI"; font-size: 11pt; }
            h1 { color: #C7B5FF; font-size: 23pt; margin-top: 0; }
            h2 { color: #83D5FF; font-size: 16pt; margin-top: 18px; }
            h3 { color: #64CEA1; font-size: 13pt; margin-top: 14px; }
            a { color: #83D5FF; }
            code, pre { background-color: #273249; }
            blockquote { color: #BCC8DB; border-left: 3px solid #7350CE; }
            """
        )
        self.reader.setMarkdown(path.read_text(encoding="utf-8"))
        layout.addWidget(self.reader)


class HelpPage(QWidget):
    def __init__(self, root: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.root = root or Path(__file__).resolve().parents[2]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)
        layout.addWidget(PageHeader("Help", "Open the project's maintained documentation.", self))
        docs = Card("Documentation", self)
        self.documentation_buttons: dict[str, QPushButton] = {}
        self._documentation_windows: dict[Path, DocumentationWindow] = {}
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
        elif path.is_file():
            try:
                window = self._documentation_windows.get(path)
                if window is None:
                    window = DocumentationWindow(path, self)
                    self._documentation_windows[path] = window
                window.show()
                window.raise_()
                window.activateWindow()
            except (OSError, UnicodeError) as error:
                self.status.setText(f"ERROR: could not read documentation {path}: {error}")
            else:
                self.status.setText(f"Opened in help window: {path}")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.status.setText(f"ERROR: could not open documentation: {path}")
        else:
            self.status.setText(f"Opened: {path}")
