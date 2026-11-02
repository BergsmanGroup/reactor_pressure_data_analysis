"""Main application shell and navigation."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from reactor_ui.widgets.card import Card
from reactor_ui.widgets.page_header import PageHeader


PAGES: Sequence[tuple[str, str, str, str]] = (
    ("analyze", "Analyze", "Analyze", "Process reactor pressure data and review run outputs."),
    ("recipe_editor", "Recipe Editor", "Recipe Editor", "Review and prepare controller recipe payloads."),
    ("plots", "Plots & Animation", "Plots & Animation", "Review cycle plots and generated animations."),
    ("settings", "Settings", "Settings", "Application preferences."),
    ("help", "Help", "Help", "Project documentation and application information."),
)


class MainWindow(QMainWindow):
    """Dark-themed shell with a persistent navigation rail."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reactor Pressure Data Analyzer")
        self.resize(1440, 900)
        self.setMinimumSize(1180, 720)

        self._buttons: dict[str, QToolButton] = {}
        self._pages: dict[str, QWidget] = {}

        root = QWidget(self)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.navigation_rail = self._build_navigation()
        root_layout.addWidget(self.navigation_rail)

        self.page_stack = QStackedWidget(root)
        self.page_stack.setObjectName("pageStack")
        root_layout.addWidget(self.page_stack, 1)
        self.setCentralWidget(root)

        for page_id, label, title, subtitle in PAGES:
            page = self._build_placeholder_page(title, subtitle)
            self._pages[page_id] = page
            self.page_stack.addWidget(page)
            self._add_navigation_button(page_id, label)

        self._buttons["analyze"].setChecked(True)
        self.page_stack.setCurrentWidget(self._pages["analyze"])

    def _build_navigation(self) -> QFrame:
        rail = QFrame(self)
        rail.setObjectName("navigationRail")
        rail.setFixedWidth(204)

        layout = QVBoxLayout(rail)
        layout.setContentsMargins(14, 18, 14, 16)
        layout.setSpacing(7)

        brand_mark = QLabel("RPA", rail)
        brand_mark.setObjectName("brandMark")
        layout.addWidget(brand_mark)

        brand_title = QLabel("Reactor Pressure\nData Analyzer", rail)
        brand_title.setObjectName("brandTitle")
        brand_title.setWordWrap(True)
        layout.addWidget(brand_title)
        layout.addSpacing(20)

        self._navigation_layout = layout
        layout.addStretch(1)
        return rail

    def _add_navigation_button(self, page_id: str, label: str) -> None:
        button = QToolButton(self.navigation_rail)
        button.setObjectName("navButton")
        button.setText(label)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.setMinimumHeight(44)
        button.setAccessibleName(f"{label} page")
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._navigation_layout.insertWidget(self._navigation_layout.count() - 1, button)
        self._buttons[page_id] = button
        button.clicked.connect(lambda checked=False, key=page_id: self._on_navigation_clicked(key, checked))

    def _build_placeholder_page(self, title: str, subtitle: str) -> QWidget:
        page = QWidget(self.page_stack)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(32, 26, 32, 30)
        page_layout.setSpacing(26)

        header = PageHeader(title, subtitle, page)
        page_layout.addWidget(header)

        card = Card("Migration status", page)
        notice = QLabel(
            "This page has not been migrated yet. Use the existing application "
            "(reactor_plotter.py) for this workflow.",
            card.content,
        )
        notice.setObjectName("mutedText")
        notice.setWordWrap(True)
        notice.setMinimumHeight(58)
        card.add_widget(notice)
        page_layout.addWidget(card)
        page_layout.addStretch(1)
        return page

    def _on_navigation_clicked(self, page_id: str, checked: bool) -> None:
        if checked:
            self.show_page(page_id)

    def show_page(self, page_id: str) -> None:
        if page_id not in self._pages:
            raise KeyError(f"Unknown application page: {page_id}")
        self.page_stack.setCurrentWidget(self._pages[page_id])
        self._buttons[page_id].setChecked(True)

    def page_button(self, page_id: str) -> QToolButton:
        return self._buttons[page_id]

    def page_widget(self, page_id: str) -> QWidget:
        return self._pages[page_id]
