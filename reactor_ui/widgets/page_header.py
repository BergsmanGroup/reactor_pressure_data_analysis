"""Page title, subtitle, and action area."""

from __future__ import annotations

from PySide6.QtWidgets import QBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


class PageHeader(QWidget):
    """Consistent page heading with an optional right-aligned action area."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("pageHeader")

        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(16)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(3)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("pageTitle")
        text_column.addWidget(self.title_label)

        self.subtitle_label = QLabel(subtitle, self)
        self.subtitle_label.setObjectName("pageSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        text_column.addWidget(self.subtitle_label)

        text_container = QWidget(self)
        text_container.setLayout(text_column)
        text_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.row.addWidget(text_container, 1)

        self.actions_widget = QWidget(self)
        self.actions_widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.actions_layout = QHBoxLayout(self.actions_widget)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(8)
        self.row.addWidget(self.actions_widget)

    def set_compact(self, compact: bool) -> None:
        self.row.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
        self.row.setSpacing(8 if compact else 16)
