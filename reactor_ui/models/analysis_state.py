"""Shared state for Analyze and Plots without global variables."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from pipeline import ReactorPipeline


class AnalysisState(QObject):
    changed = Signal()
    busy_changed = Signal(bool)
    log_message = Signal(str)
    settings_changed = Signal(object, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.source_path: Path | None = None
        self.output_dir: Path | None = None
        self.header: dict = {}
        self.sequences: dict = {}
        self.pipeline: ReactorPipeline | None = None
        self.input_is_condensed = False
        self.last_result: dict | None = None
        self.busy = False

    def set_busy(self, busy: bool) -> None:
        if self.busy != busy:
            self.busy = busy
            self.busy_changed.emit(busy)

    def clear(self) -> None:
        if self.pipeline is not None:
            self.pipeline.cleanup()
        self.source_path = None
        self.output_dir = None
        self.header = {}
        self.sequences = {}
        self.pipeline = None
        self.input_is_condensed = False
        self.last_result = None
        self.changed.emit()
