"""Reusable bordered card container."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget


class Card(QFrame):
    """A titled card with a content widget and vertical content layout."""

    def __init__(self, title: str, parent: QWidget | None = None, *, accent: str = "primary") -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setProperty("accent", accent)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 12)
        self._layout.setSpacing(8)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("cardTitle")
        self._layout.addWidget(self.title_label)

        self.content = QWidget(self)
        self.content.setObjectName("cardContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(6)
        self._layout.addWidget(self.content, 1)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        alignment = Qt.AlignmentFlag.AlignLeft if isinstance(widget, QPushButton) else Qt.AlignmentFlag(0)
        self.content_layout.addWidget(widget, stretch, alignment)
