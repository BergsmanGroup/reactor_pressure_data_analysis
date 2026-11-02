"""In-memory editor for an existing reactor data header."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QScrollArea,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QAbstractItemView,
    QSplitter,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from convert_to_json import _is_truthy_detail, build_output_filename, build_payload, load_table, validate_recipe_sheet
from reactor_ui.models.header_table_model import HeaderTableModel, HeaderTimingModel, display_cell, parse_list, parse_token
from reactor_ui.widgets.card import Card
from reactor_ui.widgets.window_geometry import fit_to_available_screen


@dataclass(frozen=True)
class HeaderEdit:
    payload: dict
    save_header_text: bool
    align_names: bool
    header_path: Path | None = None


class TimingDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        del option
        editor = QLineEdit(parent)
        if index.column() == 0:
            editor.setPlaceholderText("Blank or 0 continues a sequence")
        elif index.column() == 1:
            editor.setPlaceholderText("Valve number")
        else:
            editor.setPlaceholderText("Non-negative seconds")
        return editor


def _details(value: object) -> tuple[dict, bool, bool]:
    if isinstance(value, dict):
        return copy.deepcopy(value), True, False
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed, True, True
        return {"Info": value}, False, False
    return {}, False, False


def _username(base: str, details: dict, rows: list[list[str]]) -> str:
    def filename_token(value: object) -> str:
        text = display_cell(value).strip()
        if text.casefold() in {"nan", "none"}:
            return "NaN"
        parsed = parse_token(text)
        return str(parsed) if isinstance(parsed, (int, float)) and not isinstance(parsed, bool) else text

    match = re.search(r"(?:&|_)(?:EDR|DID|SID|EID|PID)", base, flags=re.IGNORECASE)
    base = base[: match.start()] if match else base
    parts = [base, "EDRTrue" if _is_truthy_detail(details.get("EDR")) else "EDRNaN"]
    did = details.get("DID", [])
    did = did if isinstance(did, list) else [did]
    tokens = [filename_token(value) for value in did]
    tokens = [token for token in tokens if token.casefold() not in {"", "0", "nan", "none"}]
    if tokens:
        parts.append("DID" + "-".join(tokens))
    active = {str(parse_token(row[1])) for row in rows if len(row) > 1 and row[1].strip()}
    valves = details.get("ValvePrecursor", [])
    names = details.get("Name", [])
    temperatures = details.get("TempC", [])
    if isinstance(valves, list) and isinstance(names, list):
        for index, name in enumerate(names):
            valve = valves[index] if index < len(valves) else ""
            token = display_cell(valve).strip()
            if token.casefold() not in {"", "nan", "none"} and str(parse_token(token)) not in active:
                continue
            temp = temperatures[index] if isinstance(temperatures, list) and index < len(temperatures) else "NaN"
            parts.append(f"{filename_token(name)}{filename_token(temp)}")
    return re.sub(r'[<>:"/\\|?*]', "_", "_".join(part for part in parts if part)).strip()


class HeaderEditorDialog(QDialog):
    def __init__(self, payload: dict, source: Path, header_path: Path | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Data Header")
        self.resize(1250, 850)
        self.setMinimumSize(700, 400)
        self.source = source
        self.header_path = header_path
        self.result_edit: HeaderEdit | None = None
        self._payload = copy.deepcopy(payload)
        self._editing = False
        self._was_maximized = False

        layout = QVBoxLayout(self)
        warning = QLabel(
            "Changes are only a draft here. Saving will show a complete file-change plan and require confirmation.",
            self,
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.path_label = QLabel(f"Selected data: {source}\nHeader text: {header_path or '(not selected)'}", self)
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.path_label)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        metadata_card = Card("Header Information and Valve Metadata", splitter)
        metadata = metadata_card.content
        metadata_layout = metadata_card.content_layout
        form = QFormLayout()
        self.username = QLineEdit(metadata)
        self.username.setAccessibleName("Header username")
        self.auto_username = QCheckBox("Generate username from header fields", metadata)
        username_row = QWidget(metadata)
        username_layout = QHBoxLayout(username_row)
        username_layout.setContentsMargins(0, 0, 0, 0)
        username_layout.addWidget(self.username, 1)
        username_layout.addWidget(self.auto_username)
        form.addRow("Username", username_row)
        self.info = QPlainTextEdit(metadata)
        self.info.setAccessibleName("Experimental information")
        self.info.setTabChangesFocus(True)
        self.info.setMaximumHeight(90)
        form.addRow("Info", self.info)
        metadata_layout.addLayout(form)

        columns = QHBoxLayout()
        columns.setSpacing(16)
        left_column = QVBoxLayout()
        right_column = QVBoxLayout()
        columns.addLayout(left_column, 1)
        columns.addLayout(right_column, 1)
        metadata_layout.addLayout(columns)

        details_form = QFormLayout()
        self.wait = QLineEdit(metadata)
        self.wait.setAccessibleName("Header wait time in seconds")
        self.edr = QCheckBox("EDR", metadata)
        wait_row = QWidget(metadata)
        wait_layout = QHBoxLayout(wait_row)
        wait_layout.setContentsMargins(0, 0, 0, 0)
        wait_layout.addWidget(self.wait, 1)
        wait_layout.addWidget(self.edr)
        details_form.addRow("Wait time (s)", wait_row)
        self.list_fields: dict[str, QLineEdit] = {}
        for key in ("DID", "SID", "EID", "PID"):
            field = QLineEdit(metadata)
            field.setAccessibleName(f"{key} values")
            field.setPlaceholderText("comma-separated")
            details_form.addRow(key, field)
            self.list_fields[key] = field
        left_column.addLayout(details_form)
        self.structured = QCheckBox("Save experimental details as structured JSON", metadata)
        self.format_warning = QLabel(metadata)
        self.format_warning.setWordWrap(True)
        left_column.addWidget(self.structured)
        left_column.addWidget(self.format_warning)
        left_column.addStretch(1)

        right_column.addWidget(QLabel("Valve Metadata", metadata))
        self.valve_table = QTableView(metadata)
        self.valve_table.setAccessibleName("Header valve metadata")
        self.valve_table.setMinimumHeight(130)
        self.valve_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.valve_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_column.addWidget(self.valve_table)
        valve_buttons = QHBoxLayout()
        add_valve = QPushButton("Add Valve Row", metadata)
        add_valve.setProperty("actionTone", "info")
        remove_valve = QPushButton("Delete Valve Row", metadata)
        remove_valve.setProperty("actionTone", "danger")
        self._valve_add_button = add_valve
        self._valve_remove_button = remove_valve
        add_valve.clicked.connect(self._add_valve)
        remove_valve.clicked.connect(self._remove_valve)
        valve_buttons.addWidget(add_valve)
        valve_buttons.addWidget(remove_valve)
        valve_buttons.addStretch(1)
        right_column.addLayout(valve_buttons)
        right_column.addStretch(1)
        self.save_text = QCheckBox("Also update or create the selected header text file", self)
        self.align_names = QCheckBox("Rename existing associated files to match the username", self)
        metadata_scroll = QScrollArea(splitter)
        metadata_scroll.setWidgetResizable(True)
        metadata_scroll.setFrameShape(QFrame.Shape.NoFrame)
        metadata_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        metadata_scroll.setWidget(metadata_card)
        self.metadata_scroll = metadata_scroll
        splitter.addWidget(metadata_scroll)

        timing_card = Card("Timing Table (seconds)", splitter, accent="info")
        timing = timing_card.content
        timing_layout = timing_card.content_layout
        self.timing_table = QTableView(timing)
        self.timing_table.setAccessibleName("Header timing rows")
        self.timing_table.setItemDelegate(TimingDelegate(self.timing_table))
        self.timing_table.setMinimumHeight(150)
        timing_layout.addWidget(self.timing_table, 1)
        timing_buttons = QHBoxLayout()
        add_timing = QPushButton("Insert Row", timing)
        add_timing.setProperty("actionTone", "info")
        delete_timing = QPushButton("Delete Row", timing)
        delete_timing.setProperty("actionTone", "danger")
        reset_timing = QPushButton("Reset Timing Table", timing)
        reset_timing.setProperty("actionTone", "warning")
        self._timing_add_button = add_timing
        self._timing_delete_button = delete_timing
        self._timing_reset_button = reset_timing
        add_timing.clicked.connect(self._add_timing)
        delete_timing.clicked.connect(self._delete_timing)
        reset_timing.clicked.connect(self._reset_timing)
        timing_buttons.addWidget(add_timing)
        timing_buttons.addWidget(delete_timing)
        timing_buttons.addWidget(reset_timing)
        timing_buttons.addStretch(1)
        timing_layout.addLayout(timing_buttons)
        splitter.addWidget(timing_card)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        self.splitter = splitter
        self._default_split_applied = False
        layout.addWidget(splitter, 1)

        file_options = QHBoxLayout()
        file_options.addWidget(self.save_text)
        file_options.addWidget(self.align_names)
        file_options.addStretch(1)
        layout.addLayout(file_options)

        actions = QHBoxLayout()
        regenerate = QPushButton("Regenerate Draft from Recipe...", self)
        regenerate.setProperty("actionTone", "primary")
        self.regenerate_button = regenerate
        regenerate.clicked.connect(self._regenerate)
        actions.addWidget(regenerate)
        self.edit_button = QPushButton("Edit Header", self)
        self.edit_button.setProperty("actionTone", "info")
        self.edit_button.clicked.connect(self._enable_editing)
        actions.addWidget(self.edit_button)
        actions.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, self)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.save_button.setProperty("actionTone", "success")
        self.cancel_button.setProperty("actionTone", "danger")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        actions.addWidget(buttons)
        layout.addLayout(actions)

        self.auto_username.toggled.connect(self._auto_changed)
        self.structured.toggled.connect(self._format_changed)
        self.info.textChanged.connect(self._refresh_username)
        self.wait.textChanged.connect(self._refresh_username)
        self.edr.toggled.connect(self._refresh_username)
        for field in self.list_fields.values():
            field.textChanged.connect(self._refresh_username)
        self._populate(self._payload)
        self.auto_username.setChecked(True)
        self.save_text.setChecked(True)
        self.align_names.setChecked(True)
        self._set_editing_enabled(False)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.full_screen_button = QPushButton("Full Screen (F11)", self)
        self.full_screen_button.setProperty("actionTone", "info")
        self.full_screen_button.setCheckable(True)
        self.full_screen_button.clicked.connect(self.toggle_full_screen)
        actions.insertWidget(actions.count() - 1, self.full_screen_button)
        full_screen_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F11), self)
        full_screen_shortcut.activated.connect(self.toggle_full_screen)
        fit_to_available_screen(self)

    def toggle_full_screen(self) -> None:
        if self.isFullScreen():
            self.showMaximized() if self._was_maximized else self.showNormal()
        else:
            self._was_maximized = self.isMaximized()
            self.showFullScreen()
        self.full_screen_button.setChecked(self.isFullScreen())
        self.full_screen_button.setText("Exit Full Screen (F11)" if self.isFullScreen() else "Full Screen (F11)")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._default_split_applied:
            self._default_split_applied = True
            QTimer.singleShot(0, self._apply_default_split)

    def _apply_default_split(self) -> None:
        total = sum(self.splitter.sizes())
        if total <= 0:
            return
        timing = min(total, round(self.height() * 0.5))
        self.splitter.setSizes([total - timing, timing])

    def _populate(self, payload: dict) -> None:
        self._payload = copy.deepcopy(payload)
        self._original_username = str(payload.get("username", ""))
        self._details_value, structured, self._details_was_string = _details(payload.get("experimentalDetails", ""))
        self.username.setText(self._original_username)
        self.auto_username.setChecked(False)
        self.structured.setChecked(structured)
        self.info.setPlainText(display_cell(self._details_value.get("Info", "")))
        self.wait.setText(display_cell(self._details_value.get("WaitTime", "")))
        self.edr.setChecked(_is_truthy_detail(self._details_value.get("EDR", False)))
        for key, field in self.list_fields.items():
            value = self._details_value.get(key, [])
            field.setText(", ".join(display_cell(item) for item in value) if isinstance(value, list) else display_cell(value))
        values = []
        for key in ("ValvePrecursor", "Name", "TempC"):
            value = self._details_value.get(key, [])
            values.append(value if isinstance(value, list) else ([] if value in ("", None) else [value]))
        count = max(3, *(len(value) for value in values))
        valve_rows = [
            [display_cell(column[index]) if index < len(column) else "" for column in values]
            for index in range(count)
        ]
        self.valve_model = HeaderTableModel(("Valve #", "Name", "Temperature (C)"), valve_rows, self)
        self.valve_table.setModel(self.valve_model)
        self.valve_table.horizontalHeader().setStretchLastSection(True)
        self._fit_valve_table()
        self.valve_model.dataChanged.connect(self._refresh_username)
        self.valve_model.rowsInserted.connect(self._refresh_username)
        self.valve_model.rowsRemoved.connect(self._refresh_username)
        self.timing_model = HeaderTimingModel(payload.get("valveSequence", []), self)
        self.timing_table.setModel(self.timing_model)
        self.timing_table.horizontalHeader().setStretchLastSection(True)
        self.timing_model.dataChanged.connect(self._refresh_username)
        self.timing_model.rowsInserted.connect(self._refresh_username)
        self.timing_model.rowsRemoved.connect(self._refresh_username)
        self._initial = {
            "Info": self.info.toPlainText(),
            "WaitTime": self.wait.text(),
            "EDR": self.edr.isChecked(),
            **{key: field.text() for key, field in self.list_fields.items()},
            "valves": copy.deepcopy(self.valve_model.rows),
        }
        self._original_structured = structured
        self._format_changed()

    def _current_details(self) -> dict:
        details = copy.deepcopy(self._details_value)
        current = {
            "Info": self.info.toPlainText().strip(),
            "WaitTime": self.wait.text().strip(),
            "EDR": self.edr.isChecked(),
            **{key: field.text().strip() for key, field in self.list_fields.items()},
        }
        for key, value in current.items():
            if value != self._initial.get(key) or not self._original_structured:
                if key in self.list_fields:
                    details[key] = parse_list(value)
                elif key == "WaitTime":
                    details[key] = parse_token(value)
                else:
                    details[key] = value
        if self.valve_model.rows != self._initial["valves"] or not self._original_structured:
            rows = copy.deepcopy(self.valve_model.rows)
            while rows and all(not value.strip() for value in rows[-1]):
                rows.pop()
            for index, key in enumerate(("ValvePrecursor", "Name", "TempC")):
                details[key] = [parse_token(row[index]) for row in rows]
        return details

    def _refresh_username(self, *_args) -> None:
        if self.auto_username.isChecked() and hasattr(self, "_initial"):
            self.username.setText(_username(self._original_username, self._current_details(), self.timing_model.rows))

    def _auto_changed(self, checked: bool) -> None:
        self.username.setReadOnly(checked)
        self._refresh_username()

    def _enable_editing(self) -> None:
        self._set_editing_enabled(True)

    def _set_editing_enabled(self, enabled: bool) -> None:
        self._editing = enabled
        for field in (self.username, self.wait, *self.list_fields.values()):
            field.setReadOnly(not enabled or (field is self.username and self.auto_username.isChecked()))
        self.info.setReadOnly(not enabled)
        for checkbox in (self.auto_username, self.structured, self.edr, self.save_text, self.align_names):
            checkbox.setEnabled(enabled)
        self.valve_table.setEditTriggers(
            QAbstractItemView.EditTrigger.AllEditTriggers if enabled
            else QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.timing_table.setEditTriggers(
            QAbstractItemView.EditTrigger.AllEditTriggers if enabled
            else QAbstractItemView.EditTrigger.NoEditTriggers
        )
        for button in (self.regenerate_button,):
            button.setEnabled(enabled)
        self.edit_button.setVisible(not enabled)
        self.save_button.setEnabled(enabled)
        self.cancel_button.setText("Cancel" if enabled else "Close")
        for button in (self._valve_add_button, self._valve_remove_button,
                       self._timing_add_button, self._timing_delete_button,
                       self._timing_reset_button):
            button.setEnabled(enabled)

    def _format_changed(self, *_args) -> None:
        self.format_warning.setText(
            "WARNING: saving as plain text discards structured experimental details other than Info."
            if getattr(self, "_original_structured", False) and not self.structured.isChecked() else ""
        )

    def _add_valve(self) -> None:
        self.valve_model.insert_row(self.valve_model.rowCount())
        self._fit_valve_table()
        self._refresh_username()

    def _remove_valve(self) -> None:
        row = self.valve_table.currentIndex().row()
        self.valve_model.remove_row(row)
        self._fit_valve_table()
        self._refresh_username()

    def _fit_valve_table(self) -> None:
        self.valve_table.resizeRowsToContents()
        self.valve_table.setFixedHeight(
            self.valve_table.horizontalHeader().height()
            + self.valve_table.verticalHeader().length()
            + self.valve_table.frameWidth() * 2
        )

    def _add_timing(self) -> None:
        row = self.timing_table.currentIndex().row()
        self.timing_model.insert_row(row + 1 if row >= 0 else self.timing_model.rowCount())
        self._refresh_username()

    def _delete_timing(self) -> None:
        self.timing_model.remove_row(self.timing_table.currentIndex().row())
        self._refresh_username()

    def _reset_timing(self) -> None:
        self.timing_model.reset_original()
        self._refresh_username()

    def _regenerate(self) -> None:
        answer = QMessageBox.question(
            self, "Replace Header Draft",
            "Replace the current header draft with data from a recipe sheet? No files will be written.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select Recipe Sheet", "", "Recipe sheets (*.xlsx *.xls *.csv);;All files (*)")
        if not path:
            return
        try:
            frame = load_table(Path(path))
            errors = validate_recipe_sheet(frame)
            if errors:
                raise ValueError("\n".join(errors))
            recipe = build_payload(frame, username=build_output_filename(frame))
            regenerated = copy.deepcopy(self._payload)
            regenerated.update(
                username=recipe["username"],
                experimentalDetails=recipe["experimentalDetails"],
                valveSequence=recipe["recipe"],
            )
            self._populate(regenerated)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Regenerate Header", f"Could not load the recipe sheet:\n\n{exc}")

    def _save(self) -> None:
        try:
            sequence = self.timing_model.sequence()
            details = self._current_details()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Header", str(exc))
            return
        payload = copy.deepcopy(self._payload)
        payload["username"] = self.username.text().strip()
        payload["valveSequence"] = sequence
        if self.structured.isChecked():
            payload["experimentalDetails"] = (
                json.dumps(details, ensure_ascii=False, separators=(",", ":"), allow_nan=True)
                if self._details_was_string else details
            )
        else:
            payload["experimentalDetails"] = details.get("Info", "")
        header_path = self.header_path
        if self.save_text.isChecked() and header_path is None:
            default_name = f"{payload['username'] or self.source.stem}_Header.txt"
            chosen, _ = QFileDialog.getSaveFileName(
                self, "Header Text File", str(self.source.with_name(default_name)), "Text files (*.txt);;All files (*)"
            )
            if not chosen:
                return
            header_path = Path(chosen).absolute()
        self.result_edit = HeaderEdit(
            payload, self.save_text.isChecked(), self.align_names.isChecked(),
            header_path if self.save_text.isChecked() else self.header_path,
        )
        self.accept()
