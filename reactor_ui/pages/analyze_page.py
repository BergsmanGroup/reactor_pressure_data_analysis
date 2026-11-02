"""Analysis controls and background execution of the existing pipeline."""

from __future__ import annotations

import copy
from dataclasses import replace
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from analysis_metadata import (
    append_valve_name_log,
    default_output_directory,
    details_valve_names,
    parse_experimental_details,
    predicted_header_text_path,
    reactor_type_from_filename,
    sequence_note_text,
)
from data_parser import (
    condensed_path,
    detect_sample_interval_s,
    is_condensed_file,
    load_temperature_data,
    read_header,
    temperature_zones,
)
from header_text import compare_header_payloads, format_human_json, parse_header_text
from pipeline import ReactorPipeline
from reactor_ui.adapters.analysis_controller import (
    AnalysisInputs,
    ProcessingSnapshot,
    build_processing_snapshot,
    settings_after_processing,
)
from reactor_ui.adapters.header_changes import (
    HeaderChangeResult,
    build_header_change_plan,
    execute_header_change,
    inspect_header_artifacts,
    inspect_path,
    validate_header_change_plan,
)
from reactor_ui.dialogs.header_editor_dialog import HeaderEditorDialog
from reactor_ui.dialogs.header_plan_dialog import HeaderPlanDialog
from reactor_ui.models.analysis_state import AnalysisState
from reactor_ui.models.recipe_timing import compute_run_timing
from reactor_ui.theme import COLORS
from reactor_ui.widgets.card import Card
from reactor_ui.widgets.page_header import PageHeader
from reactor_ui.workers.pipeline_worker import OperationWorker, PipelineWorker
from sequence_utils import convert_sequence
from settings_store import load_settings_state, save_settings_state


class AnalyzePage(QWidget):
    def __init__(
        self,
        state: AnalysisState,
        parent: QWidget | None = None,
        *,
        settings_path: Path | None = None,
        default_settings_path: Path | None = None,
        valve_log_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        root = Path(__file__).resolve().parents[2]
        self.state = state
        self.settings_path = settings_path or root / "config_local.json"
        self.default_settings_path = default_settings_path or root / "config_default.json"
        self.valve_log_path = valve_log_path or root / "valve_name_log.jsonl"
        self._settings_error = ""
        try:
            self.settings = load_settings_state(self.settings_path, self.default_settings_path, create_local=False)
        except (OSError, ValueError) as exc:
            self._settings_error = str(exc)
            self.settings = {"last_processing_settings": {}, "last_valve_names": {}, "reactors": []}
        self._thread: QThread | None = None
        self._worker: OperationWorker | None = None
        self._disabled_during_work: list[tuple[QWidget, bool]] = []
        self._result_handler: Callable[[object], None] | None = None
        self._failure_handler: Callable[[str], None] | None = None
        self._reload_after_work = False
        self._action = ""
        self._reactor: str | None = None
        self._condense_signature: tuple | None = None
        self._pending_signature: tuple | None = None
        self._valve_fields: dict[int, QLineEdit] = {}
        self._temperature_checks: dict[str, QCheckBox] = {}
        self._plot_checks: dict[str, QCheckBox] = {}
        self._detected_source: str | tuple[str, ...] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 24)
        layout.setSpacing(14)
        layout.addWidget(PageHeader("Analyze", "Process reactor data and inspect the resulting files.", self))
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(self._build_left())
        self.content_splitter.addWidget(self._build_right())
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 2)
        self.content_splitter.setSizes([850, 560])
        layout.addWidget(self.content_splitter, 1)

        self._restore_settings()
        self.state.settings_changed.connect(self._settings_changed)
        self.source_input.textChanged.connect(self._source_changed)
        self.output_input.textChanged.connect(self._output_changed)
        self.write_condensed.toggled.connect(self._refresh_paths)
        self.temperature_directory.textChanged.connect(self._temperature_source_changed)
        self.temperature_files.textChanged.connect(self._temperature_source_changed)
        self.temperature_mode.currentIndexChanged.connect(self._temperature_source_changed)
        if self._settings_error:
            self._log(f"ERROR loading settings ({self.settings_path}): {self._settings_error}")
        self._refresh_paths()
        self._refresh_buttons()

    def set_compact(self, compact: bool) -> None:
        self.content_splitter.setOrientation(Qt.Orientation.Vertical if compact else Qt.Orientation.Horizontal)

    @staticmethod
    def _scroll_column(parent: QWidget) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
        scroll = QScrollArea(parent)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        contents = QWidget(scroll)
        layout = QVBoxLayout(contents)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        scroll.setWidget(contents)
        return scroll, contents, layout

    @staticmethod
    def _path_row(parent: QWidget, button_text: str, action: Callable[[], None]) -> tuple[QWidget, QLineEdit]:
        row = QWidget(parent)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        entry = QLineEdit(row)
        button = QPushButton(button_text, row)
        button.clicked.connect(action)
        layout.addWidget(entry, 1)
        layout.addWidget(button)
        return row, entry

    def _build_left(self) -> QScrollArea:
        scroll, contents, layout = self._scroll_column(self)
        files = Card("Input and Header", contents)
        file_row, self.source_input = self._path_row(files, "Browse...", self._browse_source)
        self.source_input.setAccessibleName("Reactor data file")
        files.add_widget(QLabel("Raw or condensed NDJSON", files))
        files.add_widget(file_row)
        header_buttons = QWidget(files)
        header_layout = QHBoxLayout(header_buttons)
        header_layout.setContentsMargins(0, 0, 0, 0)
        self.load_header_button = QPushButton("Load Header", header_buttons)
        self.load_header_button.clicked.connect(self._load_header)
        self.header_status = QLabel("No header loaded.", header_buttons)
        self.header_status.setWordWrap(True)
        header_layout.addWidget(self.load_header_button)
        header_layout.addWidget(self.header_status, 1)
        files.add_widget(header_buttons)
        header_row, self.header_text_input = self._path_row(files, "Browse...", self._browse_header_text)
        self.header_text_input.setAccessibleName("Header text file")
        files.add_widget(QLabel("Header text file (optional)", files))
        files.add_widget(header_row)
        self.compare_button = QPushButton("Compare Headers", files)
        self.compare_button.clicked.connect(self._compare_headers)
        files.add_widget(self.compare_button)
        header_actions = QWidget(files)
        header_action_layout = QHBoxLayout(header_actions)
        header_action_layout.setContentsMargins(0, 0, 0, 0)
        self.edit_header_button = QPushButton("Edit Data Header...", header_actions)
        self.edit_header_button.clicked.connect(self._edit_header)
        self.use_header_text_button = QPushButton("Use Header Text as Data Header...", header_actions)
        self.use_header_text_button.clicked.connect(self._use_header_text)
        header_action_layout.addWidget(self.edit_header_button)
        header_action_layout.addWidget(self.use_header_text_button)
        files.add_widget(header_actions)
        header_warning = QLabel("Header changes require a file-by-file confirmation and backups.", files)
        header_warning.setWordWrap(True)
        header_warning.setObjectName("mutedText")
        files.add_widget(header_warning)
        layout.addWidget(files)

        temperature = Card("Temperature Data", contents)
        self.add_temperature = QCheckBox("Add temperature data to condensed output", temperature)
        temperature.add_widget(self.add_temperature)
        self.temperature_mode = QComboBox(temperature)
        self.temperature_mode.addItems(["Log directory", "Specific log files"])
        temperature.add_widget(self.temperature_mode)
        directory_row, self.temperature_directory = self._path_row(temperature, "Browse...", self._browse_temperature_directory)
        self.temperature_directory.setAccessibleName("Temperature log directory")
        temperature.add_widget(directory_row)
        files_row, self.temperature_files = self._path_row(temperature, "Choose files...", self._browse_temperature_files)
        self.temperature_files.setAccessibleName("Temperature log files separated by semicolons")
        temperature.add_widget(files_row)
        self.detect_zones_button = QPushButton("Detect Temperature Zones", temperature)
        self.detect_zones_button.clicked.connect(self._detect_zones)
        temperature.add_widget(self.detect_zones_button)
        self.temperature_zone_widget = QWidget(temperature)
        self.temperature_zone_layout = QGridLayout(self.temperature_zone_widget)
        self.temperature_zone_layout.setContentsMargins(0, 0, 0, 0)
        temperature.add_widget(self.temperature_zone_widget)
        self.interval_label = QLabel("Zones not detected.", temperature)
        self.interval_label.setObjectName("mutedText")
        temperature.add_widget(self.interval_label)
        interval_row = QWidget(temperature)
        interval_layout = QFormLayout(interval_row)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        self.temperature_interval = QLineEdit(interval_row)
        self.temperature_interval.setAccessibleName("Temperature sample interval in seconds")
        interval_layout.addRow("Sample interval (s; blank = all)", self.temperature_interval)
        temperature.add_widget(interval_row)
        layout.addWidget(temperature)

        ise = Card("iSE Thickness Data", contents)
        self.add_ise = QCheckBox("Attach iSE data during Run Analysis", ise)
        ise.add_widget(self.add_ise)
        ise_row, self.ise_file = self._path_row(ise, "Browse...", self._browse_ise)
        self.ise_file.setAccessibleName("iSE thickness CSV")
        ise.add_widget(ise_row)
        ise_form_widget = QWidget(ise)
        ise_form = QFormLayout(ise_form_widget)
        ise_form.setContentsMargins(0, 0, 0, 0)
        self.ise_valve = QLineEdit("Valve7", ise_form_widget)
        self.ise_valve.setAccessibleName("iSE valve")
        self.ise_first_cycle = QLineEdit("1.0", ise_form_widget)
        self.ise_first_cycle.setAccessibleName("iSE first cycle or half-cycle")
        ise_form.addRow("Valve", self.ise_valve)
        ise_form.addRow("First cycle / half-cycle", self.ise_first_cycle)
        ise.add_widget(ise_form_widget)
        layout.addWidget(ise)

        output = Card("Output and File Ownership", contents)
        output_row, self.output_input = self._path_row(output, "Browse...", self._browse_output)
        self.output_input.setAccessibleName("Output directory")
        output.add_widget(output_row)
        self.path_summary = QLabel(output)
        self.path_summary.setWordWrap(True)
        self.path_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        output.add_widget(self.path_summary)
        self.overwrite_warning = QLabel(output)
        self.overwrite_warning.setWordWrap(True)
        self.overwrite_warning.setStyleSheet(f"color: {COLORS['warning']};")
        output.add_widget(self.overwrite_warning)
        layout.addWidget(output)

        processing = Card("Processing", contents)
        self.run_all_button = QPushButton("Run Analysis", processing)
        self.run_all_button.setObjectName("primaryButton")
        self.run_all_button.clicked.connect(lambda: self._run_action("run_all"))
        processing.add_widget(self.run_all_button)
        self.run_all_temperature = QCheckBox("Attach temperature during Run Analysis", processing)
        processing.add_widget(self.run_all_temperature)
        self.progress = QProgressBar(processing)
        self.progress.setRange(0, 100)
        processing.add_widget(self.progress)
        self.progress_label = QLabel("Idle", processing)
        processing.add_widget(self.progress_label)
        buttons_widget = QWidget(processing)
        buttons = QGridLayout(buttons_widget)
        buttons.setContentsMargins(0, 0, 0, 0)
        self.stage_buttons: dict[str, QPushButton] = {}
        for index, (action, title) in enumerate(
            (
                ("condense", "1. Condense"),
                ("label_phases", "2. Label Phases"),
                ("attach_temperature", "3. Attach Temperature"),
                ("attach_ise", "4. Attach iSE"),
                ("generate_outputs", "6. Generate Outputs"),
            )
        ):
            button = QPushButton(title, buttons_widget)
            button.clicked.connect(lambda _=False, name=action: self._run_action(name))
            buttons.addWidget(button, index // 2, index % 2)
            self.stage_buttons[action] = button
        processing.add_widget(buttons_widget)
        layout.addWidget(processing)

        log_card = Card("Log", contents)
        self.log_box = QPlainTextEdit(log_card)
        self.log_box.setReadOnly(True)
        self.log_box.setTabChangesFocus(True)
        self.log_box.setMaximumBlockCount(1000)
        self.log_box.setMinimumHeight(140)
        log_card.add_widget(self.log_box)
        clear = QPushButton("Clear Log", log_card)
        clear.clicked.connect(self.log_box.clear)
        log_card.add_widget(clear)
        layout.addWidget(log_card)
        layout.addStretch(1)
        return scroll

    def _build_right(self) -> QScrollArea:
        scroll, contents, layout = self._scroll_column(self)
        options = Card("Analysis and Plot Options", contents)
        form_widget = QWidget(options)
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.xlim = QLineEdit("auto", form_widget)
        self.ylim = QLineEdit("auto", form_widget)
        self.shift = QLineEdit("0", form_widget)
        self.wait = QLineEdit("0", form_widget)
        self.fps = QLineEdit("5", form_widget)
        self.leakrate_reduction = QLineEdit("0", form_widget)
        self.blank_rows = QLineEdit("0", form_widget)
        self.grid_x_spacing = QLineEdit(form_widget)
        self.grid_y_spacing = QLineEdit(form_widget)
        for label, field in (
            ("X maximum (s; auto)", self.xlim),
            ("Y maximum (mTorr; auto)", self.ylim),
            ("Phase shift (s)", self.shift),
            ("Wait time (s)", self.wait),
            ("Animation FPS", self.fps),
            ("LeakRate phase reduction (s)", self.leakrate_reduction),
            ("Thickness blank rows", self.blank_rows),
            ("X grid spacing", self.grid_x_spacing),
            ("Y grid spacing", self.grid_y_spacing),
        ):
            field.setAccessibleName(label)
            form.addRow(label, field)
        self.grid_x = QCheckBox("X gridlines", form_widget)
        self.grid_y = QCheckBox("Y gridlines", form_widget)
        self.write_condensed = QCheckBox("Write condensed data JSON", form_widget)
        form.addRow(self.grid_x)
        form.addRow(self.grid_y)
        form.addRow(self.write_condensed)
        options.add_widget(form_widget)
        options.add_widget(QLabel("Summary box temperature zones", options))
        self.plot_zone_widget = QWidget(options)
        self.plot_zone_layout = QGridLayout(self.plot_zone_widget)
        self.plot_zone_layout.setContentsMargins(0, 0, 0, 0)
        options.add_widget(self.plot_zone_widget)
        layout.addWidget(options)

        valves = Card("Valve Metadata", contents)
        self.valve_widget = QWidget(valves)
        self.valve_layout = QFormLayout(self.valve_widget)
        self.valve_layout.setContentsMargins(0, 0, 0, 0)
        valves.add_widget(self.valve_widget)
        self.valve_hint = QLabel("Load a header to display valve names.", valves)
        self.valve_hint.setObjectName("mutedText")
        self.valve_hint.setWordWrap(True)
        valves.add_widget(self.valve_hint)
        layout.addWidget(valves)
        layout.addStretch(1)
        return scroll

    def _restore_settings(self) -> None:
        last = self.settings.get("last_processing_settings", {})
        values = (
            (self.xlim, "xlim", "auto"),
            (self.ylim, "ylim", "auto"),
            (self.shift, "shift", "0"),
            (self.wait, "wait_time", "0"),
            (self.fps, "fps", "5"),
            (self.leakrate_reduction, "leakrate_phase_reduction", "0"),
            (self.blank_rows, "thickness_blank_rows", "0"),
            (self.grid_x_spacing, "grid_x_spacing", last.get("grid_spacing", "")),
            (self.grid_y_spacing, "grid_y_spacing", last.get("grid_spacing", "")),
            (self.temperature_directory, "temperature_directory", ""),
            (self.ise_valve, "ise_valve", "Valve7"),
        )
        for field, key, default in values:
            field.setText(str(last.get(key, default)))
        files = last.get("temperature_file", "")
        self.temperature_files.setText("; ".join(str(item) for item in files) if isinstance(files, list) else str(files))
        self.temperature_mode.setCurrentIndex(1 if last.get("temperature_source_mode") == "file" else 0)
        self.grid_x.setChecked(bool(last.get("grid_x", True)))
        self.grid_y.setChecked(bool(last.get("grid_y", True)))
        self.write_condensed.setChecked(bool(last.get("write_condensed_json", True)))
        self.add_temperature.setChecked(bool(last.get("add_temperature", True)))
        self.run_all_temperature.setChecked(True)
        self._temperature_source_changed()

    def _settings_changed(self, settings: object, origin: str) -> None:
        if origin != "settings":
            return
        if not isinstance(settings, dict):
            self._log("ERROR: received invalid settings.")
            return
        self.settings = copy.deepcopy(settings)
        self._settings_error = ""
        self._restore_settings()
        if self.state.source_path is not None:
            self._reactor = reactor_type_from_filename(self.state.source_path, self.settings.get("reactors", []))
            if self._reactor is None:
                self.state.clear()
                self._condense_signature = None
                self.header_status.setText("The selected file's reactor type is no longer configured.")
                self._log("ERROR: update reactor types and reload the data header before processing.")
            else:
                details = parse_experimental_details(self.state.header.get("experimentalDetails", ""))
                self._populate_valves(details)
                if isinstance(details, dict) and "WaitTime" in details:
                    self.wait.setText(str(details["WaitTime"]))
                    self.wait.setReadOnly(True)
        self._refresh_paths()
        self._refresh_buttons()

    def is_busy(self) -> bool:
        return self._thread is not None

    def _log(self, message: str) -> None:
        self.log_box.appendPlainText(message)
        self.state.log_message.emit(message)

    def _source_changed(self) -> None:
        text = self.source_input.text().strip()
        if self.state.source_path is not None and Path(text).resolve() != self.state.source_path:
            self.state.clear()
            self._condense_signature = None
            self._reactor = None
            self.header_status.setText("Header not loaded for this file.")
            self.wait.setReadOnly(False)
            self._populate_valves({})
            self._output_changed()
        predicted = predicted_header_text_path(text) if text else None
        self.header_text_input.setText(str(predicted) if predicted is not None else "")
        self._refresh_paths()
        self._refresh_buttons()

    def _output_changed(self, *_args) -> None:
        text = self.output_input.text().strip()
        output = Path(text).resolve() if text else None
        if output != self.state.output_dir:
            self.state.output_dir = output
            self.state.last_result = None
            self.state.changed.emit()
        self._refresh_paths()

    def _refresh_paths(self, *_args) -> None:
        source_text = self.source_input.text().strip()
        source = Path(source_text).resolve() if source_text else None
        output_text = self.output_input.text().strip()
        output = str(Path(output_text).resolve()) if output_text else "(not selected)"
        pipeline = self.state.pipeline
        if pipeline is not None and pipeline.working_path is not None:
            working = str(pipeline.working_path.resolve())
        elif source is None:
            working = "(not selected)"
        elif not self.write_condensed.isChecked():
            working = "(temporary file assigned when condensation starts)"
        elif self.state.source_path == source and self.state.input_is_condensed:
            working = str(source)
        else:
            working = str(condensed_path(source))
        self.path_summary.setText(f"Source: {source or '(not selected)'}\nWorking: {working}\nOutput directory: {output}")
        if self.state.source_path == source and self.state.input_is_condensed and self.write_condensed.isChecked():
            self.overwrite_warning.setText("WARNING: the selected condensed input will be updated in place.")
        elif self.write_condensed.isChecked() and source is not None and Path(working).is_file():
            self.overwrite_warning.setText("WARNING: an existing condensed working file may be overwritten.")
        else:
            self.overwrite_warning.setText(
                "Generated output files may be overwritten; a stale thickness CSV may be removed."
            )

    def _refresh_buttons(self) -> None:
        busy = self.is_busy()
        loaded = self.state.source_path is not None
        usable = loaded and bool(self.state.sequences)
        pipeline = self.state.pipeline
        downstream = usable and pipeline is not None and pipeline.stage != "none"
        self.load_header_button.setEnabled(not busy)
        self.compare_button.setEnabled(not busy and loaded)
        self.edit_header_button.setEnabled(not busy and loaded)
        self.use_header_text_button.setEnabled(not busy and loaded)
        self.detect_zones_button.setEnabled(not busy)
        self.run_all_button.setEnabled(not busy and usable)
        for action, button in self.stage_buttons.items():
            button.setEnabled(not busy and (usable if action == "condense" else downstream))
        self.source_input.setEnabled(not busy)
        self.output_input.setEnabled(not busy)

    def _browse_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Reactor Data", "", "JSON files (*.json);;All files (*)")
        if path:
            self.source_input.setText(path)
            self.output_input.setText(str(default_output_directory(path)))
            self._load_header()

    def _browse_header_text(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Header Text", "", "Header files (*.txt *.json);;All files (*)")
        if path:
            self.header_text_input.setText(path)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if path:
            self.output_input.setText(path)

    def _browse_ise(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select iSE Data", "", "CSV files (*.csv);;All files (*)")
        if path:
            self.ise_file.setText(path)

    def _browse_temperature_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Temperature Log Directory")
        if path:
            self.temperature_directory.setText(path)
            self.temperature_mode.setCurrentIndex(0)
            self._detect_zones()

    def _browse_temperature_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Temperature Logs", "", "Log files (*.jsonl *.log *.json);;All files (*)")
        if paths:
            self.temperature_files.setText("; ".join(paths))
            self.temperature_mode.setCurrentIndex(1)
            self._detect_zones()

    def _load_header(self) -> None:
        text = self.source_input.text().strip()
        path = Path(text).resolve() if text else None
        if path is None or not path.is_file():
            self._log("ERROR: select an existing reactor data file.")
            return
        reactor = reactor_type_from_filename(path, self.settings.get("reactors", []))
        if reactor is None:
            self._log("ERROR: filename must contain a configured reactor type and match the reactor data naming format.")
            return

        def operation(_progress, log):
            log(f"Reading header: {path}")
            header = read_header(path)
            raw_sequence = header.get("valveSequence")
            if not isinstance(raw_sequence, list):
                log("WARNING: header has no valveSequence list; edit the header before processing.")
                sequences = {}
            else:
                try:
                    sequences = convert_sequence(raw_sequence)
                except (IndexError, KeyError, TypeError, ValueError) as exc:
                    log(f"WARNING: header sequence cannot be processed: {exc}")
                    sequences = {}
            if not sequences:
                log("WARNING: header has no usable sequence; processing is disabled until it is corrected.")
            return header, sequences, is_condensed_file(path)

        def loaded(result: object) -> None:
            header, sequences, condensed = result
            self.state.clear()
            self.state.source_path = path
            self.state.header = header
            self.state.sequences = sequences
            self.state.input_is_condensed = condensed
            self._reactor = reactor
            self._condense_signature = None
            self._output_changed()
            self.ise_file.clear()
            details = parse_experimental_details(header.get("experimentalDetails", ""))
            self._populate_valves(details)
            if isinstance(details, dict) and "WaitTime" in details:
                self.wait.setText(str(details["WaitTime"]))
                self.wait.setReadOnly(True)
            else:
                self.wait.setReadOnly(False)
            self.header_status.setText(f"Loaded: {header.get('username', '')} ({len(sequences)} sequences)")
            self._log(f"Header loaded; {'condensed' if condensed else 'raw'} input.")
            self.state.changed.emit()
            self._refresh_paths()

        self._start_worker(OperationWorker("Load header", operation), loaded)

    def _populate_valves(self, details: object) -> None:
        while self.valve_layout.count():
            item = self.valve_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._valve_fields.clear()
        numbers = sorted({number for seq in self.state.sequences.values() for number, _ in seq.get("valve_rows", [])})
        saved = self.settings.get("last_valve_names", {})
        if isinstance(saved, dict):
            by_reactor = saved.get(self._reactor, {})
            if not isinstance(by_reactor, dict):
                by_reactor = {}
            if all(not isinstance(value, dict) for value in saved.values()):
                by_reactor = saved
        else:
            by_reactor = {}
        from_header = details_valve_names(details)
        for number in numbers:
            value = from_header.get(number, str(by_reactor.get(str(number), number)))
            entry = QLineEdit(value, self.valve_widget)
            entry.setAccessibleName(f"Valve {number} name")
            entry.setReadOnly(number in from_header)
            self.valve_layout.addRow(f"Valve {number}", entry)
            self._valve_fields[number] = entry
        self.valve_hint.setText(
            "Names from the header are read-only; other names are saved per reactor."
            if numbers else "Load a header to display valve names."
        )

    def _temperature_source(self) -> str | tuple[str, ...] | None:
        if self.temperature_mode.currentIndex() == 1:
            files = tuple(part.strip() for part in self.temperature_files.text().split(";") if part.strip())
            return files or None
        return self.temperature_directory.text().strip() or None

    def _temperature_source_changed(self, *_args) -> None:
        file_mode = self.temperature_mode.currentIndex() == 1
        self.temperature_directory.setEnabled(not file_mode)
        self.temperature_files.setEnabled(file_mode)
        self._detected_source = None
        self._set_zones([], None)

    @staticmethod
    def _clear_layout(layout: QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _set_zones(self, zones: list[str], interval: float | None) -> None:
        self._clear_layout(self.temperature_zone_layout)
        self._clear_layout(self.plot_zone_layout)
        self._temperature_checks.clear()
        self._plot_checks.clear()
        for index, zone in enumerate(zones):
            attach = QCheckBox(f"Zone {zone}", self.temperature_zone_widget)
            plot = QCheckBox(f"Zone {zone}", self.plot_zone_widget)
            attach.setChecked(True)
            plot.setChecked(True)
            self.temperature_zone_layout.addWidget(attach, index // 3, index % 3)
            self.plot_zone_layout.addWidget(plot, index // 3, index % 3)
            self._temperature_checks[zone] = attach
            self._plot_checks[zone] = plot
        self.interval_label.setText(
            f"Detected sample interval: {interval:g} s" if interval is not None else
            ("No temperature zones found." if self._detected_source is not None else "Zones not detected.")
        )

    def _detect_zones(self) -> None:
        source = self._temperature_source()
        if source is None:
            self._log("ERROR: select a temperature directory or log files first.")
            return

        def operation(_progress, log):
            samples = load_temperature_data(list(source) if isinstance(source, tuple) else source)
            log(f"Read {len(samples)} temperature samples.")
            return temperature_zones(samples), detect_sample_interval_s(samples)

        def detected(result: object) -> None:
            zones, interval = result
            if source != self._temperature_source():
                self._log("Temperature source changed; discarded the earlier zone scan.")
                return
            self._detected_source = source
            self._set_zones(zones, interval)
            self._log("Detected temperature zones: " + (", ".join(zones) if zones else "none"))

        self._start_worker(OperationWorker("Detect temperature zones", operation), detected)

    def _compare_headers(self) -> None:
        source = self.state.source_path
        header_path = Path(self.header_text_input.text().strip())
        if source is None or not header_path.is_file():
            self._log("ERROR: select an existing header text file and load the data header.")
            return

        def operation(_progress, _log):
            raw = read_header(source)
            text = parse_header_text(header_path)
            return raw, text, compare_header_payloads(raw, text)

        def compared(result: object) -> None:
            raw, text, differences = result
            status = "valveSequence differs" if differences else "valveSequence matches"
            self._log(f"Header comparison: {status}. No files were written.")
            dialog = QDialog(self)
            dialog.setWindowTitle(status)
            dialog.resize(1100, 700)
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel(status, dialog))
            panes = QSplitter(Qt.Orientation.Horizontal, dialog)
            for value in (raw, text):
                view = QPlainTextEdit(panes)
                view.setReadOnly(True)
                view.setTabChangesFocus(True)
                view.setPlainText(format_human_json(value))
                panes.addWidget(view)
            layout.addWidget(panes)
            close = QPushButton("Close", dialog)
            close.clicked.connect(dialog.accept)
            layout.addWidget(close)
            dialog.exec()

        self._start_worker(OperationWorker("Compare headers", operation), compared)

    def _edit_header(self) -> None:
        source = self.state.source_path
        if self.is_busy() or source is None:
            self._log("ERROR: load a data header before editing.")
            return
        text = self.header_text_input.text().strip()
        header_path = Path(text).absolute() if text else None
        try:
            dialog = HeaderEditorDialog(self.state.header, source, header_path, self)
        except ValueError as exc:
            QMessageBox.warning(self, "Edit Data Header", str(exc))
            return
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_edit is not None:
            edit = dialog.result_edit
            self._prepare_header_change(edit.payload, edit.save_header_text, edit.align_names)

    def _use_header_text(self) -> None:
        source = self.state.source_path
        text = self.header_text_input.text().strip()
        if self.is_busy() or source is None or not text:
            self._log("ERROR: load a data header and select a header text file first.")
            return
        header_path = Path(text).absolute()
        try:
            before = inspect_path(header_path)
            if before.kind != "file":
                raise ValueError("The header text must be an existing regular, non-symlink file.")
            payload = parse_header_text(header_path)
            if inspect_path(header_path) != before:
                raise RuntimeError("The header text changed while it was read; try again.")
            sequence = payload.get("valveSequence")
            if not isinstance(sequence, list) or not sequence:
                raise ValueError("The header text must contain a nonempty valveSequence.")
            compute_run_timing(sequence)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self._log(f"ERROR: could not read header text: {exc}")
            QMessageBox.warning(self, "Use Header Text", str(exc))
            return
        self._prepare_header_change(payload, False, False, read_only_header=True, header_snapshot=before)

    def _prepare_header_change(
        self,
        payload: dict,
        save_text: bool,
        align_names: bool,
        *,
        read_only_header: bool = False,
        header_snapshot=None,
    ) -> None:
        source = self.state.source_path
        if source is None or self.is_busy():
            self._log("ERROR: load a data header and wait for processing to finish.")
            return
        header_text = self.header_text_input.text().strip()
        header_path = Path(header_text).absolute() if header_text else None
        try:
            inventory = inspect_header_artifacts(source, str(payload.get("username", "")), header_path)
            current = read_header(source)
            if inspect_path(source) != inventory[source]:
                raise RuntimeError("The data file changed while its header was read; reload it first.")
            if json.dumps(current, sort_keys=True) != json.dumps(self.state.header, sort_keys=True):
                raise RuntimeError("The data header changed since it was loaded; reload it before editing.")
            if header_snapshot is not None and (header_path is None or inventory[header_path] != header_snapshot):
                raise RuntimeError("The header text changed while preparing the plan; try again.")
            plan = build_header_change_plan(
                source, str(payload.get("username", "")), header_path,
                save_header_text=save_text,
                align_names=align_names,
                inventory=inventory,
                timestamp=datetime.now().strftime("%Y%m%d-%H%M%S"),
                token=uuid.uuid4().hex[:12],
                read_only_header=read_only_header,
            )
            validate_header_change_plan(plan)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self._log(f"ERROR preparing header change: {exc}")
            QMessageBox.warning(self, "Header Change Plan", str(exc))
            return
        if HeaderPlanDialog(plan, self).exec() != QDialog.DialogCode.Accepted:
            self._log("Header change cancelled; no files were changed.")
            return
        self._start_worker(
            OperationWorker(
                "Apply header changes",
                lambda progress, log: execute_header_change(plan, payload, progress=progress, log=log),
            ),
            self._header_change_finished,
            failure_handler=self._header_change_failed,
        )

    def _header_change_finished(self, result: object) -> None:
        if not isinstance(result, HeaderChangeResult):
            raise TypeError("Header operation returned an invalid result.")
        self.state.clear()
        self._reactor = None
        self._condense_signature = None
        self.source_input.setText(str(result.selected_path))
        if result.header_path is not None:
            self.header_text_input.setText(str(result.header_path))
        self._log("Header correction completed. Backups:\n" + "\n".join(str(path) for path in result.backups))
        self._reload_after_work = True

    def _header_change_failed(self, message: str) -> None:
        self.state.clear()
        self._reactor = None
        self._condense_signature = None
        self.header_status.setText("Header operation failed; review the report and reload the affected file.")
        QMessageBox.critical(self, "Header Change Failed", message)

    def _inputs(self) -> AnalysisInputs:
        source = self._temperature_source()
        return AnalysisInputs(
            valve_names=tuple((number, field.text()) for number, field in self._valve_fields.items()),
            xlim=self.xlim.text(),
            ylim=self.ylim.text(),
            grid_x=self.grid_x.isChecked(),
            grid_y=self.grid_y.isChecked(),
            grid_x_spacing=self.grid_x_spacing.text(),
            grid_y_spacing=self.grid_y_spacing.text(),
            shift=self.shift.text(),
            wait_time=self.wait.text(),
            leakrate_phase_reduction=self.leakrate_reduction.text(),
            write_condensed_json=self.write_condensed.isChecked(),
            add_temperature=self.add_temperature.isChecked(),
            add_ise=self.add_ise.isChecked(),
            temperature_source=source,
            temperature_directory=self.temperature_directory.text(),
            temperature_files=tuple(part.strip() for part in self.temperature_files.text().split(";") if part.strip()),
            temperature_source_mode="file" if self.temperature_mode.currentIndex() == 1 else "directory",
            selected_temperature_zones=tuple(zone for zone, check in self._temperature_checks.items() if check.isChecked()),
            temperature_sample_interval_s=self.temperature_interval.text(),
            plot_temperature_zones=(
                tuple(zone for zone, check in self._plot_checks.items() if check.isChecked())
                if self._plot_checks else None
            ),
            ise_file_path=self.ise_file.text(),
            ise_valve=self.ise_valve.text(),
            ise_first_cycle=self.ise_first_cycle.text(),
            thickness_blank_rows=self.blank_rows.text(),
            fps=self.fps.text(),
        )

    def _existing_output_paths(self, output: Path) -> list[Path]:
        source = self.state.source_path
        assert source is not None
        if not output.is_dir():
            return []
        stem = source.stem.removesuffix("_condensed")
        candidates = list(output.glob("cycle_*.png"))
        candidates.extend(output / f"{stem}{suffix}" for suffix in ("_exposure.csv", "_thickness.csv", "_animation.gif"))
        return sorted(path.absolute() for path in candidates if path.is_file() or path.is_symlink())

    def _affected_paths(self, action: str, snapshot: ProcessingSnapshot, output: Path) -> list[Path]:
        source = self.state.source_path
        assert source is not None
        affected: set[Path] = set()
        if snapshot.write_condensed_json:
            if action in {"condense", "run_all"}:
                working = source if self.state.input_is_condensed else condensed_path(source)
            else:
                working = self.state.pipeline.working_path if self.state.pipeline is not None else None
            if working is not None and (working.exists() or working.is_symlink()):
                affected.add(working.absolute())
        if action in {"generate_outputs", "run_all"}:
            affected.update(self._existing_output_paths(output))
        return sorted(affected)

    def _unsafe_output_aliases(self, action: str, snapshot: ProcessingSnapshot, output: Path) -> list[str]:
        if action not in {"generate_outputs", "run_all"}:
            return []
        source = self.state.source_path
        assert source is not None
        protected = [("selected input", source)]
        if self.state.pipeline is not None and self.state.pipeline.working_path is not None:
            protected.append(("working file", self.state.pipeline.working_path))
        if snapshot.write_condensed_json:
            protected.append(("condensed file", source if self.state.input_is_condensed else condensed_path(source)))
        for label, text in (
            ("header text", self.header_text_input.text()),
            ("iSE input", snapshot.ise_file_path),
        ):
            if text.strip():
                protected.append((label, Path(text.strip())))
        temperature = snapshot.temperature_source
        if isinstance(temperature, str):
            protected.append(("temperature input", Path(temperature)))
        elif temperature is not None:
            protected.extend(("temperature input", Path(path)) for path in temperature)

        aliases = []
        for candidate in self._existing_output_paths(output):
            if not candidate.is_file():
                continue
            for label, path in protected:
                if path.is_file() and candidate.samefile(path):
                    aliases.append(f"{candidate} aliases {label}: {path}")
        return aliases

    def _confirm_processing(self, action: str, snapshot: ProcessingSnapshot, output: Path) -> bool:
        affected = self._affected_paths(action, snapshot, output)
        if not affected:
            return True
        message = (
            "This operation may overwrite the following files. A stale thickness CSV may also be removed:\n\n"
            + "\n".join(
                f"{path} (symlink target: {path.resolve()})" if path.is_symlink() else str(path)
                for path in affected
            )
            + "\n\nContinue?"
        )
        return QMessageBox.warning(
            self, "Confirm file changes", message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    def _run_action(self, action: str) -> None:
        source = self.state.source_path
        if self.is_busy() or source is None or self._reactor is None or not self.state.sequences:
            self._log("ERROR: load a header before processing.")
            return
        output_text = self.output_input.text().strip()
        if not output_text:
            self._log("ERROR: choose an output directory.")
            return
        output = Path(output_text).resolve()
        inputs = self._inputs()
        if action == "attach_ise":
            inputs = replace(inputs, add_ise=True)
        try:
            snapshot = build_processing_snapshot(inputs, self.state.header.get("experimentalDetails", ""))
            will_attach_temperature = (
                action == "attach_temperature"
                or (action == "run_all" and self.run_all_temperature.isChecked())
            )
            if (
                will_attach_temperature
                and snapshot.add_temperature
                and snapshot.temperature_source
                and self._detected_source != snapshot.temperature_source
            ):
                raise ValueError("Detect temperature zones for the selected source before processing.")
        except ValueError as exc:
            self._log(f"ERROR: {exc}")
            return
        signature = (snapshot.wait_time, snapshot.write_condensed_json, snapshot.xlim, snapshot.ylim)
        pipeline = self.state.pipeline
        if action not in {"condense", "run_all"}:
            if pipeline is None or pipeline.stage == "none":
                self._log("ERROR: run Condense before this stage.")
                return
            if self._condense_signature != signature:
                self._log("ERROR: wait time, limits, or condensed-output setting changed; run Condense again.")
                return
        try:
            aliases = self._unsafe_output_aliases(action, snapshot, output)
        except OSError as exc:
            self._log(f"ERROR: could not check output file aliases: {exc}")
            return
        if aliases:
            self._log("ERROR: output files alias protected inputs; choose another output directory:\n" + "\n".join(aliases))
            return
        if not self._confirm_processing(action, snapshot, output):
            self._log("Processing cancelled; no files were changed.")
            return
        if self._settings_error:
            self._log("ERROR: settings could not be loaded; repair the configuration before processing.")
            return
        try:
            updated = settings_after_processing(self.settings, inputs, self._reactor, snapshot)
            save_settings_state(self.settings_path, updated)
        except (OSError, TypeError, ValueError) as exc:
            self._log(f"ERROR saving processing settings: {exc}")
            return
        self.settings = updated
        if action == "attach_ise":
            self.add_ise.setChecked(True)
        self.state.settings_changed.emit(copy.deepcopy(updated), "analyze")
        try:
            append_valve_name_log(
                self.valve_log_path, source, self.state.header.get("GUID", ""),
                self._reactor, dict(snapshot.valve_names),
            )
        except (OSError, TypeError, ValueError) as exc:
            self._log(f"WARNING: could not append valve-name log: {exc}")
        pipeline = self._pipeline_for_snapshot(snapshot, output)
        if action in {"condense", "run_all"}:
            pipeline.cleanup()
            pipeline.working_path = None
            pipeline.working_is_temp = False
            pipeline.cycle_points = {}
            pipeline.stage = "none"
            self._condense_signature = None
        self._pending_signature = signature
        self._action = action
        self.state.last_result = None
        self._log(f"Starting {action.replace('_', ' ')}: {source}")
        self._start_worker(
            PipelineWorker(
                pipeline, action,
                attach_temperature=self.run_all_temperature.isChecked(),
                attach_ise=self.add_ise.isChecked(),
            ),
            self._pipeline_finished,
        )

    def _pipeline_for_snapshot(self, snapshot: ProcessingSnapshot, output: Path) -> ReactorPipeline:
        source = self.state.source_path
        assert source is not None
        details = copy.deepcopy(parse_experimental_details(self.state.header.get("experimentalDetails", "")))

        def sequence_note(key: str, phased: dict) -> str | None:
            return sequence_note_text(key, phased, details)

        pipeline = self.state.pipeline
        if pipeline is None:
            pipeline = ReactorPipeline(
                source, str(output), self.state.sequences, snapshot.to_options(), sequence_note_fn=sequence_note
            )
            self.state.pipeline = pipeline
        else:
            pipeline.options = snapshot.to_options()
            pipeline.out_dir = str(output)
            pipeline.update_recipe(self.state.sequences)
            pipeline.update_sequence_note_fn(sequence_note)
        self.state.output_dir = output
        return pipeline

    def start_preview(self, cycle: int, handler: Callable[[object], None]) -> None:
        if self.is_busy() or self.state.source_path is None or not self.state.sequences:
            self._log("ERROR: load a header and wait for processing to finish before previewing.")
            return
        if self._settings_error:
            self._log("ERROR: settings could not be loaded; repair the configuration before previewing.")
            return
        output_text = self.output_input.text().strip()
        if not output_text:
            self._log("ERROR: choose an output directory before previewing.")
            return
        try:
            snapshot = build_processing_snapshot(self._inputs(), self.state.header.get("experimentalDetails", ""))
        except ValueError as exc:
            self._log(f"ERROR: {exc}")
            return
        signature = (snapshot.wait_time, snapshot.write_condensed_json, snapshot.xlim, snapshot.ylim)
        pipeline = self.state.pipeline
        if pipeline is not None and pipeline.stage != "none" and self._condense_signature != signature:
            self._log("ERROR: wait time, limits, or condensed-output setting changed; run Condense again.")
            return
        pipeline = self._pipeline_for_snapshot(snapshot, Path(output_text).resolve())

        def preview(progress, log):
            return pipeline.preview_cycle(cycle, progress_cb=progress, log_cb=log)

        self._start_worker(OperationWorker(f"Preview cycle {cycle}", preview), handler)

    def generate_outputs(self) -> None:
        self._run_action("generate_outputs")

    def _pipeline_finished(self, result: object) -> None:
        if self._action in {"condense", "run_all"}:
            self._condense_signature = self._pending_signature
        if isinstance(result, dict):
            self.state.last_result = result
        self._log(f"{self._action.replace('_', ' ').title()} completed.")
        self.state.changed.emit()
        self._refresh_paths()

    def _start_worker(
        self,
        worker: OperationWorker,
        handler: Callable[[object], None],
        *,
        failure_handler: Callable[[str], None] | None = None,
    ) -> None:
        if self.is_busy():
            self._log("ERROR: another operation is already running.")
            return
        thread = QThread(self)
        self._thread = thread
        self._worker = worker
        self._result_handler = handler
        self._failure_handler = failure_handler
        self.state.set_busy(True)
        self._disabled_during_work = []
        dynamic_containers = (self.valve_widget, self.temperature_zone_widget, self.plot_zone_widget)
        for widget_type in (QLineEdit, QComboBox, QCheckBox, QPushButton):
            for widget in self.findChildren(widget_type):
                if any(container.isAncestorOf(widget) for container in dynamic_containers):
                    continue
                self._disabled_during_work.append((widget, widget.isEnabled()))
                widget.setEnabled(False)
        for container in dynamic_containers:
            self._disabled_during_work.append((container, container.isEnabled()))
            container.setEnabled(False)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._progress_changed)
        worker.log.connect(self._log)
        worker.finished.connect(self._operation_finished)
        worker.failed.connect(self._operation_failed)
        worker.done.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        thread.finished.connect(thread.deleteLater)
        self.progress.setValue(0)
        self.progress_label.setText(worker.label)
        self._refresh_buttons()
        thread.start()

    @Slot(int, str)
    def _progress_changed(self, value: int, label: str) -> None:
        self.progress.setValue(value)
        self.progress_label.setText(f"{label}: {value}%")

    @Slot(object)
    def _operation_finished(self, result: object) -> None:
        try:
            if self._result_handler is not None:
                self._result_handler(result)
        except Exception as exc:
            self._operation_failed(f"Could not display operation result: {type(exc).__name__}: {exc}")

    @Slot(str)
    def _operation_failed(self, message: str) -> None:
        self.progress_label.setText("Failed")
        self._log(f"ERROR: {message}")
        if self._failure_handler is not None:
            self._failure_handler(message)

    @Slot()
    def _thread_finished(self) -> None:
        thread = self._thread
        if thread is not None:
            thread.wait()
        self._thread = None
        self._worker = None
        self._result_handler = None
        self._failure_handler = None
        for widget, was_enabled in self._disabled_during_work:
            widget.setEnabled(was_enabled)
        self._disabled_during_work = []
        self._refresh_buttons()
        self._refresh_paths()
        self.state.set_busy(False)
        if self._reload_after_work:
            self._reload_after_work = False
            self._load_header()

    def cleanup(self) -> None:
        self.state.clear()
