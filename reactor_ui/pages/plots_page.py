"""Interactive cycle previews and existing pipeline output actions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget

from reactor_ui.models.analysis_state import AnalysisState
from reactor_ui.widgets.card import Card
from reactor_ui.widgets.page_header import PageHeader

if TYPE_CHECKING:
    from reactor_ui.pages.analyze_page import AnalyzePage


class PlotsPage(QWidget):
    def __init__(self, state: AnalysisState, analyze: AnalyzePage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.analyze = analyze
        self.canvas: FigureCanvasQTAgg | None = None
        self.toolbar: NavigationToolbar2QT | None = None
        self._preview_source: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 24)
        layout.setSpacing(12)
        layout.addWidget(PageHeader("Plots & Animation", "Preview a cycle and generate analysis outputs.", self))

        preview = Card("Single-Cycle Preview", self)
        controls = QWidget(preview)
        self.control_layout = QGridLayout(controls)
        self.control_layout.setContentsMargins(0, 0, 0, 0)
        self.cycle_label = QLabel("Cycle", controls)
        self.cycle = QSpinBox(controls)
        self.cycle.setRange(0, 2_147_483_647)
        self.cycle.setValue(1)
        self.cycle.setAccessibleName("Preview cycle number")
        self.cycle.valueChanged.connect(self._update_controls)
        self.previous_button = QPushButton("Previous", controls)
        self.previous_button.clicked.connect(lambda: self._step_cycle(-1))
        self.next_button = QPushButton("Next", controls)
        self.next_button.clicked.connect(lambda: self._step_cycle(1))
        self.preview_button = QPushButton("Preview Cycle", controls)
        self.preview_button.setObjectName("primaryButton")
        self.preview_button.clicked.connect(self._request_preview)
        self.preview_label = QLabel("No cycle previewed.", controls)
        self.preview_label.setObjectName("mutedText")
        self.preview_label.setWordWrap(True)
        preview.add_widget(controls)

        self.preview_container = QWidget(preview)
        self.preview_layout = QVBoxLayout(self.preview_container)
        self.preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_layout.setSpacing(0)
        self.placeholder = QLabel("Load a header on Analyze, select a cycle, and choose Preview Cycle.", self.preview_container)
        self.placeholder.setObjectName("mutedText")
        self.placeholder.setWordWrap(True)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setMinimumHeight(220)
        self.preview_layout.addWidget(self.placeholder, 1)
        preview.add_widget(self.preview_container, 1)
        layout.addWidget(preview, 1)

        output = Card("Generated Outputs", self)
        self.output_label = QLabel(output)
        self.output_label.setWordWrap(True)
        self.output_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.output_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        output.add_widget(self.output_label)
        output_buttons = QWidget(output)
        self.output_layout = QGridLayout(output_buttons)
        self.output_layout.setContentsMargins(0, 0, 0, 0)
        self.generate_button = QPushButton("Generate Plots && Animation", output_buttons)
        self.generate_button.clicked.connect(self.analyze.generate_outputs)
        self.open_directory_button = QPushButton("Open Output Directory", output_buttons)
        self.open_directory_button.clicked.connect(self._open_directory)
        self.open_animation_button = QPushButton("Open Animation", output_buttons)
        self.open_animation_button.clicked.connect(self._open_animation)
        self.set_compact(False)
        output.add_widget(output_buttons)
        self.status = QLabel("Load a header on Analyze to begin.", output)
        self.status.setObjectName("mutedText")
        self.status.setWordWrap(True)
        output.add_widget(self.status)
        layout.addWidget(output)

        self.state.changed.connect(self._state_changed)
        self.state.busy_changed.connect(self._busy_changed)
        self.state.log_message.connect(self.status.setText)
        self._state_changed()

    def set_compact(self, compact: bool) -> None:
        control_widgets = (
            self.cycle_label,
            self.cycle,
            self.previous_button,
            self.next_button,
            self.preview_button,
            self.preview_label,
        )
        for widget in control_widgets:
            self.control_layout.removeWidget(widget)
        if compact:
            for column, widget in enumerate(control_widgets[:4]):
                self.control_layout.addWidget(widget, 0, column)
            self.control_layout.addWidget(self.preview_button, 1, 0, 1, 2)
            self.control_layout.addWidget(self.preview_label, 1, 2, 1, 2)
        else:
            for column, widget in enumerate(control_widgets):
                self.control_layout.addWidget(widget, 0, column)
        for column in range(7):
            self.control_layout.setColumnStretch(column, int(column == (4 if compact else 6)))

        output_widgets = (self.generate_button, self.open_directory_button, self.open_animation_button)
        for widget in output_widgets:
            self.output_layout.removeWidget(widget)
        if compact:
            self.output_layout.addWidget(self.generate_button, 0, 0, 1, 2)
            self.output_layout.addWidget(self.open_directory_button, 1, 0)
            self.output_layout.addWidget(self.open_animation_button, 1, 1)
        else:
            for column, widget in enumerate(output_widgets):
                self.output_layout.addWidget(widget, 0, column)
        for column in range(4):
            self.output_layout.setColumnStretch(column, int(column == (2 if compact else 3)))

    def _request_preview(self) -> None:
        self.analyze.start_preview(self.cycle.value(), self._show_preview)

    def _step_cycle(self, step: int) -> None:
        self.cycle.setValue(self.cycle.value() + step)
        self._request_preview()

    def _show_preview(self, result: object) -> None:
        if not isinstance(result, Figure):
            raise TypeError("Preview did not return a Matplotlib figure.")
        self._clear_preview()
        self._preview_source = self.state.source_path
        self.canvas = FigureCanvasQTAgg(result)
        self.canvas.setAccessibleName(f"Pressure plot for cycle {self.cycle.value()}")
        self.toolbar = NavigationToolbar2QT(self.canvas, self.preview_container)
        self.preview_layout.insertWidget(0, self.toolbar)
        self.preview_layout.addWidget(self.canvas, 1)
        self.placeholder.hide()
        self.preview_label.setText(f"Showing cycle {self.cycle.value()}")
        self.canvas.draw()

    def _clear_preview(self) -> None:
        if self.toolbar is not None:
            self.preview_layout.removeWidget(self.toolbar)
            self.toolbar.deleteLater()
            self.toolbar = None
        if self.canvas is not None:
            self.preview_layout.removeWidget(self.canvas)
            self.canvas.figure.clear()
            self.canvas.deleteLater()
            self.canvas = None
        self._preview_source = None
        self.preview_label.setText("No cycle previewed.")
        self.placeholder.show()

    def _state_changed(self) -> None:
        if self._preview_source is not None and self._preview_source != self.state.source_path:
            self._clear_preview()
        output = self.state.output_dir
        self.output_label.setText(f"Output directory: {output or '(not selected)'}")
        self._update_controls()

    def _busy_changed(self, busy: bool) -> None:
        if self.canvas is not None:
            self.canvas.setUpdatesEnabled(not busy)
        if self.toolbar is not None:
            self.toolbar.setEnabled(not busy)
        self._update_controls()

    def _update_controls(self, *_args) -> None:
        ready = self.state.source_path is not None and bool(self.state.sequences) and not self.state.busy
        self.cycle.setEnabled(ready)
        self.previous_button.setEnabled(ready and self.cycle.value() > self.cycle.minimum())
        self.next_button.setEnabled(ready and self.cycle.value() < self.cycle.maximum())
        self.preview_button.setEnabled(ready)
        pipeline = self.state.pipeline
        self.generate_button.setEnabled(ready and pipeline is not None and pipeline.stage != "none")
        self.open_directory_button.setEnabled(
            not self.state.busy and self.state.output_dir is not None and self.state.output_dir.is_dir()
        )
        result = self.state.last_result
        animation = result.get("animation") if result else None
        self.open_animation_button.setEnabled(not self.state.busy and bool(animation) and Path(animation).is_file())

    def _open_path(self, path: Path | None, label: str) -> None:
        if path is None or not path.exists():
            self.status.setText(f"ERROR: {label} does not exist: {path or '(not selected)'}")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.status.setText(f"ERROR: could not open {label}: {path}")

    def _open_directory(self) -> None:
        self._open_path(self.state.output_dir, "output directory")

    def _open_animation(self) -> None:
        result = self.state.last_result or {}
        animation = result.get("animation")
        self._open_path(Path(animation) if animation else None, "animation")
