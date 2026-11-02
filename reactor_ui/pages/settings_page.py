"""Editable preferences using the existing configuration format."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from reactor_ui.adapters.analysis_controller import AnalysisInputs, build_processing_snapshot
from reactor_ui.models.analysis_state import AnalysisState
from reactor_ui.models.header_table_model import HeaderTableModel
from reactor_ui.models.recipe_timing import _integer
from reactor_ui.widgets.card import Card
from reactor_ui.widgets.page_header import PageHeader
from settings_store import load_settings_state, save_settings_state


_TEXT_SETTINGS = (
    ("xlim", "X maximum (s; auto)", "auto"),
    ("ylim", "Y maximum (mTorr; auto)", "auto"),
    ("shift", "Phase shift (s)", "0"),
    ("wait_time", "Wait time (s)", "0"),
    ("fps", "Animation FPS", "5"),
    ("leakrate_phase_reduction", "LeakRate phase reduction (s)", "0"),
    ("thickness_blank_rows", "Thickness blank rows", "0"),
    ("grid_x_spacing", "X grid spacing", ""),
    ("grid_y_spacing", "Y grid spacing", ""),
    ("temperature_directory", "Temperature log directory", ""),
    ("ise_valve", "iSE valve", "Valve7"),
)
_BOOLEAN_SETTINGS = (
    ("grid_x", "X gridlines", True),
    ("grid_y", "Y gridlines", True),
    ("write_condensed_json", "Write condensed data JSON", True),
    ("add_temperature", "Add temperature data", True),
)


def _validate_settings_shape(settings: dict) -> None:
    last = settings["last_processing_settings"]
    for key, _, default in _BOOLEAN_SETTINGS:
        if not isinstance(last.get(key, default), bool):
            raise ValueError(f"{key} must be a boolean in the settings file.")
    if last.get("temperature_source_mode", "directory") not in {"directory", "file"}:
        raise ValueError("Temperature source mode must be 'directory' or 'file'.")
    if not isinstance(last.get("temperature_file", []), (list, str)):
        raise ValueError("Temperature files must be text or a list of paths.")
    saved = settings["last_valve_names"]
    if saved and any(isinstance(value, dict) for value in saved.values()):
        for reactor, names in saved.items():
            if not isinstance(names, dict):
                raise ValueError(f"Valve names for {reactor} must be an object.")


class SettingsPage(QWidget):
    def __init__(
        self,
        state: AnalysisState,
        settings_path: Path,
        default_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.state = state
        self.settings_path = settings_path
        self.default_path = default_path
        self._baseline: dict = {}
        self._dirty = False
        self._applying = False
        self._load_error = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 24)
        layout.setSpacing(12)
        self.header = PageHeader("Settings", "Existing processing defaults, reactor types, and valve names.", self)
        self.save_button = QPushButton("Save Settings", self.header)
        self.save_button.setObjectName("primaryButton")
        self.reload_button = QPushButton("Reload", self.header)
        self.reset_button = QPushButton("Reset to Defaults", self.header)
        for button in (self.save_button, self.reload_button, self.reset_button):
            self.header.actions_layout.addWidget(button)
        layout.addWidget(self.header)
        notice = QLabel(
            "Saving applies these settings to Analyze. Values supplied by a loaded header take precedence.",
            self,
        )
        notice.setWordWrap(True)
        notice.setObjectName("mutedText")
        layout.addWidget(notice)
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.content_splitter.setChildrenCollapsible(False)
        self.processing_panel = self._build_processing()
        self.reactor_panel = self._build_reactors()
        self.content_splitter.addWidget(self.processing_panel)
        self.content_splitter.addWidget(self.reactor_panel)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 1)
        layout.addWidget(self.content_splitter, 1)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.status)

        self.save_button.clicked.connect(self._save)
        self.reload_button.clicked.connect(self._reload_clicked)
        self.reset_button.clicked.connect(self._reset)
        self.state.busy_changed.connect(self._busy_changed)
        self.state.settings_changed.connect(self._external_settings_changed)
        self._load()
        self._busy_changed(self.state.busy)

    def set_compact(self, compact: bool) -> None:
        self.header.set_compact(compact)
        self.content_splitter.setOrientation(Qt.Orientation.Vertical if compact else Qt.Orientation.Horizontal)
        self.processing_panel.setMinimumHeight(200 if compact else 0)
        self.reactor_panel.setMinimumHeight(200 if compact else 0)
        self.valve_action_layout.setDirection(
            QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight
        )

    def _build_processing(self) -> QScrollArea:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        card = Card("Processing Defaults", scroll)
        form_widget = QWidget(card)
        form = QFormLayout(form_widget)
        self.text_fields: dict[str, QLineEdit] = {}
        for key, label, _ in _TEXT_SETTINGS:
            field = QLineEdit(form_widget)
            field.setAccessibleName(label)
            field.textChanged.connect(self._mark_dirty)
            self.text_fields[key] = field
            form.addRow(label, field)
        self.boolean_fields: dict[str, QCheckBox] = {}
        for key, label, _ in _BOOLEAN_SETTINGS:
            field = QCheckBox(label, form_widget)
            field.toggled.connect(self._mark_dirty)
            self.boolean_fields[key] = field
            form.addRow(field)
        self.temperature_mode = QComboBox(form_widget)
        self.temperature_mode.addItem("Log directory", "directory")
        self.temperature_mode.addItem("Specific log files", "file")
        self.temperature_mode.currentIndexChanged.connect(self._mark_dirty)
        form.addRow("Temperature source", self.temperature_mode)
        self.temperature_files = QLineEdit(form_widget)
        self.temperature_files.setAccessibleName("Temperature log files separated by semicolons")
        self.temperature_files.textChanged.connect(self._mark_dirty)
        form.addRow("Temperature files (; separated)", self.temperature_files)
        card.add_widget(form_widget)
        scroll.setWidget(card)
        return scroll

    def _build_reactors(self) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        reactors = Card("Reactor Types", container)
        reactor_help = QLabel("One configured filename reactor type per line.", reactors)
        reactor_help.setWordWrap(True)
        reactors.add_widget(reactor_help)
        self.reactors = QPlainTextEdit(reactors)
        self.reactors.setAccessibleName("Configured reactor types")
        self.reactors.setTabChangesFocus(True)
        self.reactors.setMaximumHeight(150)
        self.reactors.textChanged.connect(self._mark_dirty)
        reactors.add_widget(self.reactors)
        layout.addWidget(reactors)
        valves = Card("Saved Valve Names", container)
        self.valve_model = HeaderTableModel(("Reactor type", "Valve #", "Name"), [], self)
        self.valve_model.dataChanged.connect(self._mark_dirty)
        self.valve_model.rowsInserted.connect(self._mark_dirty)
        self.valve_model.rowsRemoved.connect(self._mark_dirty)
        self.valve_table = QTableView(valves)
        self.valve_table.setAccessibleName("Saved valve names by reactor")
        self.valve_table.setModel(self.valve_model)
        self.valve_table.horizontalHeader().setStretchLastSection(True)
        valves.add_widget(self.valve_table, 1)
        actions = QWidget(valves)
        self.valve_action_layout = QHBoxLayout(actions)
        self.valve_action_layout.setContentsMargins(0, 0, 0, 0)
        add = QPushButton("Add Valve Name", actions)
        remove = QPushButton("Delete Selected", actions)
        add.clicked.connect(lambda: self.valve_model.insert_row(self.valve_model.rowCount()))
        remove.clicked.connect(lambda: self.valve_model.remove_row(self.valve_table.currentIndex().row()))
        self.valve_action_layout.addWidget(add)
        self.valve_action_layout.addWidget(remove)
        self.valve_action_layout.addStretch(1)
        valves.add_widget(actions)
        layout.addWidget(valves, 1)
        return container

    def _set_values(self, settings: dict) -> None:
        _validate_settings_shape(settings)
        self._applying = True
        try:
            last = settings["last_processing_settings"]
            for key, _, default in _TEXT_SETTINGS:
                fallback = last.get("grid_spacing", default) if key in {"grid_x_spacing", "grid_y_spacing"} else default
                self.text_fields[key].setText(str(last.get(key, fallback)))
            for key, _, default in _BOOLEAN_SETTINGS:
                value = last.get(key, default)
                if not isinstance(value, bool):
                    raise ValueError(f"{key} must be a boolean in the settings file.")
                self.boolean_fields[key].setChecked(value)
            mode = last.get("temperature_source_mode", "directory")
            index = self.temperature_mode.findData(mode)
            if index < 0:
                raise ValueError("Temperature source mode must be 'directory' or 'file'.")
            self.temperature_mode.setCurrentIndex(index)
            files = last.get("temperature_file", [])
            if isinstance(files, list):
                self.temperature_files.setText("; ".join(str(item) for item in files))
            elif isinstance(files, str):
                self.temperature_files.setText(files)
            else:
                raise ValueError("Temperature files must be text or a list of paths.")
            reactor_names = settings["reactors"]
            self.reactors.setPlainText("\n".join(reactor_names))
            saved = settings["last_valve_names"]
            rows: list[list[str]] = []
            if saved and all(not isinstance(value, dict) for value in saved.values()):
                for reactor in reactor_names:
                    rows.extend([reactor, str(number), str(name)] for number, name in saved.items())
            else:
                for reactor, names in saved.items():
                    if not isinstance(names, dict):
                        raise ValueError(f"Valve names for {reactor} must be an object.")
                    rows.extend([str(reactor), str(number), str(name)] for number, name in names.items())
            self.valve_model.reset_rows(rows)
            self._baseline = copy.deepcopy(settings)
            self._dirty = False
        finally:
            self._applying = False

    def _load(self) -> None:
        try:
            settings = load_settings_state(self.settings_path, self.default_path, create_local=False)
            self._set_values(settings)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self._load_error = str(exc)
            self.status.setText(f"ERROR loading settings: {exc}. Fix the file or reset to defaults.")
        else:
            self._load_error = ""
            self.status.setText(f"Loaded settings from {self.settings_path if self.settings_path.exists() else self.default_path}.")
        self._update_buttons()

    def _mark_dirty(self, *_args) -> None:
        if not self._applying:
            self._dirty = True
            self.status.setText("Unsaved settings. Saving applies them to Analyze.")

    def _candidate(self) -> dict:
        candidate = copy.deepcopy(self._baseline)
        last = candidate["last_processing_settings"]
        for key, field in self.text_fields.items():
            last[key] = field.text().strip()
        for key, field in self.boolean_fields.items():
            last[key] = field.isChecked()
        last["temperature_source_mode"] = self.temperature_mode.currentData()
        last["temperature_file"] = [part.strip() for part in self.temperature_files.text().split(";") if part.strip()]
        build_processing_snapshot(
            AnalysisInputs(
                xlim=last["xlim"], ylim=last["ylim"], shift=last["shift"], wait_time=last["wait_time"],
                fps=last["fps"], leakrate_phase_reduction=last["leakrate_phase_reduction"],
                thickness_blank_rows=last["thickness_blank_rows"],
                grid_x_spacing=last["grid_x_spacing"], grid_y_spacing=last["grid_y_spacing"],
            ),
            {},
        )
        reactors = [line.strip() for line in self.reactors.toPlainText().splitlines() if line.strip()]
        if not reactors:
            raise ValueError("At least one reactor type is required.")
        if len({name.casefold() for name in reactors}) != len(reactors):
            raise ValueError("Reactor types must be unique.")
        if any(any(char in name for char in '<>:"/\\|?*') for name in reactors):
            raise ValueError("Reactor types cannot contain filename separators or invalid filename characters.")
        candidate["reactors"] = reactors
        saved: dict[str, dict[str, str]] = {}
        for index, row in enumerate(self.valve_model.rows, start=1):
            reactor, number_text, name = (value.strip() for value in row)
            if not (reactor or number_text or name):
                continue
            number = _integer(number_text, blank_is_zero=False)
            if not reactor or number is None or number <= 0 or not name:
                raise ValueError(f"Valve-name row {index} needs a reactor, positive integer valve number, and name.")
            names = saved.setdefault(reactor, {})
            if str(number) in names:
                raise ValueError(f"Valve {number} is listed more than once for {reactor}.")
            names[str(number)] = name
        for reactor in reactors:
            saved.setdefault(reactor, {})
        candidate["last_valve_names"] = saved
        return candidate

    @staticmethod
    def _same_settings(one: dict, two: dict) -> bool:
        return json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)

    def _save(self) -> None:
        if self._load_error or self.state.busy:
            return
        try:
            current = load_settings_state(self.settings_path, self.default_path, create_local=False)
            if not self._same_settings(current, self._baseline):
                raise RuntimeError("Settings changed on disk; reload before saving to avoid overwriting those changes.")
            candidate = self._candidate()
            save_settings_state(self.settings_path, candidate)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            self.status.setText(f"ERROR saving settings: {exc}")
            return
        self._set_values(candidate)
        self.status.setText(f"Settings saved to {self.settings_path}.")
        self.state.settings_changed.emit(copy.deepcopy(candidate), "settings")

    def _reload_clicked(self) -> None:
        if not self.confirm_discard():
            return
        self._load()
        if not self._load_error:
            self.state.settings_changed.emit(copy.deepcopy(self._baseline), "settings")

    def confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        return QMessageBox.question(
            self, "Discard Settings Edits", "Discard unsaved settings edits?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    def _reset(self) -> None:
        if self.state.busy:
            return
        answer = QMessageBox.question(
            self, "Reset Settings",
            f"Replace {self.settings_path} with all values from {self.default_path}? "
            "This also resets reactor types and saved valve names.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            defaults = load_settings_state(self.default_path, self.default_path, create_local=False)
            _validate_settings_shape(defaults)
            save_settings_state(self.settings_path, defaults)
            self._set_values(defaults)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.status.setText(f"ERROR resetting settings: {exc}")
            return
        self._load_error = ""
        self._update_buttons()
        self.status.setText(f"Settings reset to {self.default_path}.")
        self.state.settings_changed.emit(copy.deepcopy(defaults), "settings")

    def _external_settings_changed(self, settings: object, origin: str) -> None:
        if origin != "analyze" or not isinstance(settings, dict):
            return
        if self._dirty:
            self.status.setText("Settings changed during analysis. Reload before saving this draft.")
            return
        try:
            self._set_values(settings)
        except (ValueError, TypeError, KeyError) as exc:
            self._load_error = str(exc)
            self.status.setText(f"ERROR updating settings: {exc}")
            self._update_buttons()
            return
        self.status.setText("Settings updated from the most recent analysis.")

    def _busy_changed(self, busy: bool) -> None:
        self.setEnabled(not busy)
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.save_button.setEnabled(not self.state.busy and not self._load_error)
