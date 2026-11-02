"""Main application shell and navigation."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QCloseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from reactor_ui.pages.recipe_editor_page import RecipeEditorPage
from reactor_ui.pages.analyze_page import AnalyzePage
from reactor_ui.pages.plots_page import PlotsPage
from reactor_ui.pages.settings_page import SettingsPage
from reactor_ui.pages.help_page import HelpPage
from reactor_ui.models.analysis_state import AnalysisState


PAGES: Sequence[tuple[str, str]] = (
    ("analyze", "Analyze"),
    ("recipe_editor", "Recipe Editor"),
    ("plots", "Plots & Animation"),
    ("settings", "Settings"),
    ("help", "Help"),
)


class _PageStack(QStackedWidget):
    def hasHeightForWidth(self) -> bool:
        # Word-wrapped labels must not force resizable splitters to their full size hint.
        return False

    def heightForWidth(self, _width: int) -> int:
        return -1

    def minimumSizeHint(self) -> QSize:
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()


class MainWindow(QMainWindow):
    """Dark-themed shell with a persistent navigation rail."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reactor Pressure Data Analyzer")
        self.resize(1440, 900)
        self.setMinimumSize(760, 440)

        self._buttons: dict[str, QToolButton] = {}
        self._pages: dict[str, QWidget] = {}
        self._compact = False
        self.analysis_state = AnalysisState(self)

        root = QWidget(self)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.navigation_rail = self._build_navigation()
        root_layout.addWidget(self.navigation_rail)

        self.page_scroll = QScrollArea(root)
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.page_stack = _PageStack(self.page_scroll)
        self.page_stack.setObjectName("pageStack")
        self.page_scroll.setWidget(self.page_stack)
        root_layout.addWidget(self.page_scroll, 1)
        self.setCentralWidget(root)

        for page_id, label in PAGES:
            if page_id == "analyze":
                self.analyze_page = AnalyzePage(self.analysis_state, self.page_stack)
                page = self.analyze_page
            elif page_id == "recipe_editor":
                self.recipe_editor = RecipeEditorPage(self.page_stack)
                page = self.recipe_editor
            elif page_id == "plots":
                self.plots_page = PlotsPage(self.analysis_state, self.analyze_page, self.page_stack)
                page = self.plots_page
            elif page_id == "settings":
                self.settings_page = SettingsPage(
                    self.analysis_state, self.analyze_page.settings_path, self.analyze_page.default_settings_path, self.page_stack
                )
                page = self.settings_page
            elif page_id == "help":
                self.help_page = HelpPage(parent=self.page_stack)
                page = self.help_page
            else:
                raise RuntimeError(f"No implementation for page: {page_id}")
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
        button.setText(label.replace("&", "&&"))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.setMinimumHeight(44)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setAccessibleName(f"{label} page")
        button.setToolTip(label)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._navigation_layout.insertWidget(self._navigation_layout.count() - 1, button)
        self._buttons[page_id] = button
        button.clicked.connect(lambda checked=False, key=page_id: self._on_navigation_clicked(key, checked))

    def _on_navigation_clicked(self, page_id: str, checked: bool) -> None:
        if checked:
            self.show_page(page_id)

    def show_page(self, page_id: str) -> None:
        if page_id not in self._pages:
            raise KeyError(f"Unknown application page: {page_id}")
        page = self._pages[page_id]
        changed = self.page_stack.currentWidget() is not page
        self.page_stack.setCurrentWidget(page)
        self.page_stack.updateGeometry()
        if changed:
            self.page_scroll.horizontalScrollBar().setValue(0)
            self.page_scroll.verticalScrollBar().setValue(0)
        self._buttons[page_id].setChecked(True)

    def page_button(self, page_id: str) -> QToolButton:
        return self._buttons[page_id]

    def page_widget(self, page_id: str) -> QWidget:
        return self._pages[page_id]

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "settings_page"):
            return
        compact = event.size().width() < 1000
        if compact != self._compact:
            self._compact = compact
            self.navigation_rail.setFixedWidth(160 if compact else 204)
            self._buttons["plots"].setText("Plots" if compact else "Plots && Animation")
            self.analyze_page.set_compact(compact)
            self.recipe_editor.set_compact(compact)
            self.plots_page.set_compact(compact)
            self.settings_page.set_compact(compact)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.analyze_page.is_busy():
            QMessageBox.warning(self, "Processing in progress", "Wait for the current operation to finish before closing.")
            event.ignore()
        elif self.recipe_editor.confirm_discard() and self.settings_page.confirm_discard():
            self.analyze_page.cleanup()
            event.accept()
        else:
            event.ignore()
