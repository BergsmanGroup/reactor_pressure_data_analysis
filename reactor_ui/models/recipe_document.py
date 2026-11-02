"""Editable in-memory recipe state, validation, and undo commands."""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QUndoCommand, QUndoStack

from convert_to_json import (
    RECIPE_COLS,
    extract_header_details,
    extract_sequence_notes,
    load_table,
    validate_recipe_sheet,
)
from reactor_ui.models.recipe_timing import RecipeTimingError, RunTiming, _integer, compute_run_timing
from recipe_timing_core import TIMING_COLUMNS


_HEADER_LABELS = {
    "username": ("User/File Name Info", "Username"),
    "info": ("Info",),
    "did": ("DID",),
    "edr": ("EDR",),
    "wait": ("Wait time",),
    "valve": ("Valve/precursor", "valve number", "Valve number"),
    "name": ("Name", "valve name", "Valve name"),
    "temperature": ("Temperature (C)", "valve temperature", "Valve temperature"),
}


def _header_and_rows(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[list[str]], int]:
    table = frame.fillna("").astype(str).reindex(
        columns=range(max(RECIPE_COLS, frame.shape[1])), fill_value=""
    )
    headers = table.index[table.iloc[:, 0].str.strip() == "Cycles"]
    if not len(headers):
        raise ValueError("Could not find the timing table header row starting with 'Cycles'.")
    header_index = int(headers[0])
    rows = table.iloc[header_index + 1 :, :RECIPE_COLS].values.tolist()
    return (
        table.iloc[: header_index + 1].copy(),
        [row for row in rows if any(value.strip() for value in row)],
        min(frame.shape[1], RECIPE_COLS),
    )


def _find_header(header: pd.DataFrame, labels: Sequence[str]) -> int | None:
    for index in range(len(header) - 1):
        if str(header.iat[index, 0]).strip() in labels:
            return index
    return None


def _write_header(header: pd.DataFrame, key: str, values: Sequence[str]) -> pd.DataFrame:
    labels = _HEADER_LABELS[key]
    result = header.copy(deep=True)
    index = _find_header(result, labels)
    if index is None:
        row = pd.DataFrame([[""] * result.shape[1]], columns=result.columns)
        row.iat[0, 0] = labels[0]
        result = pd.concat([result.iloc[:-1], row, result.iloc[-1:]], ignore_index=True)
        index = len(result) - 2
    for column in range(1, RECIPE_COLS):
        result.iat[index, column] = values[column - 1] if column - 1 < len(values) else ""
    return result


def _blank_like(value: str) -> bool:
    return not value.strip() or value.strip().lower() == "nan"


def _validation_frame(frame: pd.DataFrame, header: pd.DataFrame, rows: list[list[str]]) -> pd.DataFrame:
    result = frame.copy(deep=True)
    valve_row = _find_header(header, _HEADER_LABELS["valve"])
    if valve_row is not None:
        for column in range(2, RECIPE_COLS):
            number = _integer(result.iat[valve_row, column], blank_is_zero=False)
            if number is not None and number > 0:
                result.iat[valve_row, column] = str(number)
    for row, values in enumerate(rows):
        number = _integer(values[1], blank_is_zero=False)
        if number is not None and number > 0:
            result.iat[len(header) + row, 1] = str(number)
    return result


class _ChangeCommand(QUndoCommand):
    def __init__(
        self,
        document: RecipeDocument,
        text: str,
        redo: Callable[[], None],
        undo: Callable[[], None],
        *,
        reset_rows: bool = False,
    ) -> None:
        super().__init__(text)
        self._document = document
        self._redo = redo
        self._undo = undo
        self._reset_rows = reset_rows

    def redo(self) -> None:
        self._document._apply_change(self._redo, reset_rows=self._reset_rows)

    def undo(self) -> None:
        self._document._apply_change(self._undo, reset_rows=self._reset_rows)


class RecipeDocument(QObject):
    """Keep the workbook read-only and own the editable draft."""

    aboutToReset = Signal()
    reset = Signal()
    cellsChanged = Signal()
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.indexChanged.connect(self._stack_index_changed)
        self._header: pd.DataFrame | None = None
        self.clear()

    def clear(self) -> None:
        self.aboutToReset.emit()
        self.source_path: Path | None = None
        self._header = None
        self._metadata_width = RECIPE_COLS
        self.frame: pd.DataFrame | None = None
        self.username = ""
        self.details: dict = {}
        self.rows: list[list[str]] = []
        self.valve_rows: list[list[str]] = []
        self._valve_count = 0
        self.sequence_numbers: list[int | str] = []
        self.sequence_notes: list[dict] = []
        self.sheet_errors: list[str] = []
        self.timing_errors: list[str] = []
        self.metadata_errors: list[str] = []
        self.cell_errors: dict[tuple[int, int], str] = {}
        self.valve_errors: dict[tuple[int, int], str] = {}
        self.timing: RunTiming | None = None
        self.wait_text = "0"
        self.start_time = datetime.now().replace(microsecond=0)
        self.run_seconds: float | None = None
        self.last_export_path: Path | None = None
        self.reset.emit()
        self.undo_stack.clear()
        self.changed.emit()

    @Slot(int)
    def _stack_index_changed(self, _: int) -> None:
        self.changed.emit()

    def _open_draft(
        self, header: pd.DataFrame, rows: list[list[str]], source: Path | None, metadata_width: int
    ) -> None:
        _, details = extract_header_details(header)
        self.aboutToReset.emit()
        self.source_path = source
        self._header = header
        self._metadata_width = metadata_width
        self._valve_count = 0
        self.rows = rows
        self.wait_text = str(details.get("WaitTime", 0))
        self.start_time = datetime.now().replace(microsecond=0)
        self.last_export_path = None
        self._recompute()
        self.reset.emit()
        self.undo_stack.clear()
        self.changed.emit()

    def load(self, path: str | Path) -> None:
        source = Path(path).resolve()
        header, rows, metadata_width = _header_and_rows(load_table(source))
        self._open_draft(header, rows, source, metadata_width)

    def new_draft(self) -> None:
        lines = [
            ["User/File Name Info", ""],
            ["Info", ""],
            ["Wait time", "0"],
            ["EDR", ""],
            ["DID", ""],
            ["Valve/precursor", "nan"],
            ["Name", "Chamber"],
            ["Temperature (C)", ""],
            ["Cycles", *TIMING_COLUMNS[1:]],
        ]
        header = pd.DataFrame([line + [""] * (RECIPE_COLS - len(line)) for line in lines])
        self._open_draft(header, [[""] * RECIPE_COLS], None, RECIPE_COLS)

    def _read_valve_rows(self) -> list[list[str]]:
        if self._header is None:
            return []
        columns: list[list[str]] = []
        for key in ("valve", "name", "temperature"):
            index = _find_header(self._header, _HEADER_LABELS[key])
            values = (
                [str(self._header.iat[index, column]) for column in range(1, RECIPE_COLS)]
                if index is not None
                else [""] * (RECIPE_COLS - 1)
            )
            columns.append(values)
        rows = [list(values) for values in zip(*columns)]
        while rows and all(_blank_like(value) for value in rows[-1]):
            rows.pop()
        return rows

    def _recompute(self) -> None:
        if self._header is None:
            return
        width = self._header.shape[1]
        timing_rows = [row + [""] * (width - RECIPE_COLS) for row in self.rows]
        body = pd.DataFrame(timing_rows, columns=self._header.columns)
        self.frame = pd.concat([self._header, body], ignore_index=True)
        metadata_width = self._metadata_width
        for column in range(metadata_width, RECIPE_COLS):
            if any(str(value).strip() for value in self._header.iloc[:-1, column]):
                metadata_width = column + 1
        username, self.details = extract_header_details(self._header.iloc[:, :metadata_width])
        self.username = str(username)
        self.valve_rows = self._read_valve_rows()
        while len(self.valve_rows) < self._valve_count:
            self.valve_rows.append(["", "", ""])
        self._valve_count = len(self.valve_rows)
        self.sheet_errors = validate_recipe_sheet(_validation_frame(self.frame, self._header, self.rows))
        self.timing_errors = []
        self.metadata_errors = []
        self.cell_errors = {}
        self.valve_errors = {}
        self.timing = None
        self.run_seconds = None
        self.sequence_notes = []

        sequence = 0
        self.sequence_numbers = []
        for row in self.rows:
            cycles = _integer(row[0], blank_is_zero=True)
            if cycles is not None and cycles > 0:
                sequence += 1
            self.sequence_numbers.append(sequence or "")

        if not self.rows:
            self.timing_errors.append("The recipe has no timing rows.")
        else:
            try:
                self.timing = compute_run_timing(self.rows)
            except RecipeTimingError as exc:
                for issue in exc.issues:
                    self.cell_errors[(issue.row, issue.column)] = issue.message
                    self.timing_errors.append(f"Timing row {issue.row + 1}, {issue.message}")
            else:
                self.run_seconds = self.timing.run_duration_s
                self.sequence_notes = extract_sequence_notes(self.frame)

        declared: set[int] = set()
        for index, (valve, name, temperature) in enumerate(self.valve_rows[1:], start=2):
            number = _integer(valve, blank_is_zero=False)
            if number is None or number <= 0:
                message = f"Valve metadata row {index} needs a positive integer valve number."
                self.metadata_errors.append(message)
                self.valve_errors[(index - 1, 0)] = message
            elif number in declared:
                message = f"Valve {number} is declared more than once."
                self.metadata_errors.append(message)
                self.valve_errors[(index - 1, 0)] = message
            else:
                declared.add(number)
            if _blank_like(name):
                message = f"Valve metadata row {index} needs a name."
                self.metadata_errors.append(message)
                self.valve_errors[(index - 1, 1)] = message
            if not _blank_like(temperature):
                try:
                    valid_temperature = math.isfinite(float(temperature))
                except ValueError:
                    valid_temperature = False
                if not valid_temperature:
                    message = f"Valve metadata row {index} needs a finite temperature."
                    self.metadata_errors.append(message)
                    self.valve_errors[(index - 1, 2)] = message

        for index, row in enumerate(self.rows):
            number = _integer(row[1], blank_is_zero=False)
            if number is not None and number > 0 and number not in declared:
                message = f"Valve {number} is not declared in Valve Metadata."
                self.cell_errors[(index, 1)] = message
                self.metadata_errors.append(f"Timing row {index + 1}: {message}")

    def _apply_change(self, operation: Callable[[], None], *, reset_rows: bool) -> None:
        if reset_rows:
            self.aboutToReset.emit()
        operation()
        self._recompute()
        if reset_rows:
            self.reset.emit()
        else:
            self.cellsChanged.emit()

    def _push(self, text: str, redo: Callable[[], None], undo: Callable[[], None], *, reset_rows: bool = False) -> None:
        self.undo_stack.push(_ChangeCommand(self, text, redo, undo, reset_rows=reset_rows))

    def set_cells(self, changes: Sequence[tuple[int, int, str]], description: str = "Edit cell") -> None:
        if self._header is None:
            raise ValueError("Open or create a recipe first.")
        old: list[tuple[int, int, str]] = []
        new: list[tuple[int, int, str]] = []
        for row, column, value in changes:
            if not (0 <= row < len(self.rows) and 0 <= column < RECIPE_COLS):
                raise ValueError("The edit extends outside the timing table.")
            text = str(value)
            if text != self.rows[row][column]:
                old.append((row, column, self.rows[row][column]))
                new.append((row, column, text))
        if not new:
            return

        def apply(values: list[tuple[int, int, str]]) -> None:
            for row, column, value in values:
                self.rows[row][column] = value

        self._push(description, lambda: apply(new), lambda: apply(old))

    def paste_rectangle(self, row: int, column: int, text: str) -> None:
        try:
            values = list(csv.reader(io.StringIO(text, newline=""), delimiter="\t", strict=True))
        except csv.Error as exc:
            raise ValueError(f"Invalid clipboard text: {exc}") from exc
        if not values or not values[0]:
            raise ValueError("The clipboard does not contain a rectangle.")
        width = len(values[0])
        if any(len(line) != width for line in values):
            raise ValueError("The clipboard rows do not all have the same number of columns.")
        if row < 0 or column < 0 or row + len(values) > len(self.rows) or column + width > RECIPE_COLS:
            raise ValueError("The pasted rectangle extends outside the editable timing table.")
        changes: list[tuple[int, int, str]] = []
        for row_offset, line in enumerate(values):
            for column_offset, value in enumerate(line):
                target_column = column + column_offset
                stripped = value.strip()
                if target_column in (0, 1) and stripped:
                    number = _integer(stripped, blank_is_zero=False)
                    if number is None or number < 0 or (target_column == 1 and number == 0):
                        raise ValueError(f"Row {row_offset + 1}, column {column_offset + 1} needs an integer.")
                elif 2 <= target_column <= 8 and stripped:
                    try:
                        number_float = float(stripped)
                    except ValueError:
                        number_float = math.nan
                    if not math.isfinite(number_float) or number_float < 0:
                        raise ValueError(
                            f"Row {row_offset + 1}, column {column_offset + 1} needs non-negative seconds."
                        )
                changes.append((row + row_offset, target_column, value))
        self.set_cells(changes, "Paste cells")

    def _replace_rows(self, rows: list[list[str]], description: str) -> None:
        old = [row[:] for row in self.rows]
        new = [row[:] for row in rows]
        if old == new:
            return

        def apply(values: list[list[str]]) -> None:
            self.rows = [row[:] for row in values]

        self._push(description, lambda: apply(new), lambda: apply(old), reset_rows=True)

    def insert_row(self, index: int) -> None:
        if self._header is None or not 0 <= index <= len(self.rows):
            raise ValueError("Choose a valid insertion point in an open recipe.")
        rows = [row[:] for row in self.rows]
        rows.insert(index, [""] * RECIPE_COLS)
        self._replace_rows(rows, "Insert row")

    def delete_rows(self, indices: Sequence[int]) -> None:
        selected = set(indices)
        if not selected or any(index < 0 or index >= len(self.rows) for index in selected):
            raise ValueError("Select one or more timing rows to delete.")
        self._replace_rows([row[:] for index, row in enumerate(self.rows) if index not in selected], "Delete rows")

    def _set_header(self, key: str, values: Sequence[str], description: str, *, wait: str | None = None) -> None:
        if self._header is None:
            raise ValueError("Open or create a recipe first.")
        before = self._header.copy(deep=True)
        after = _write_header(before, key, values)
        old_wait = self.wait_text
        new_wait = old_wait if wait is None else wait
        if before.equals(after) and old_wait == new_wait:
            return

        def apply(header: pd.DataFrame, wait_text: str) -> None:
            self._header = header.copy(deep=True)
            self.wait_text = wait_text

        self._push(description, lambda: apply(after, new_wait), lambda: apply(before, old_wait))

    def set_metadata(self, key: str, text: str) -> None:
        if key not in {"username", "info", "did", "edr"}:
            raise ValueError(f"Unknown editable metadata field: {key}")
        self._set_header(key, [text], f"Edit {key}")

    def metadata_text(self, key: str) -> str:
        if self._header is None or key not in _HEADER_LABELS:
            return ""
        index = _find_header(self._header, _HEADER_LABELS[key])
        if index is None:
            return ""
        values = [str(value) for value in self._header.iloc[index, 1:RECIPE_COLS]]
        if key == "did":
            return ", ".join(value for value in values if not _blank_like(value))
        return values[0] if values else ""

    def set_wait_text(self, text: str) -> None:
        if text != self.wait_text and self._header is not None:
            self._set_header("wait", [text], "Edit wait time", wait=text)

    def set_start_time(self, value: datetime) -> None:
        value = value.replace(microsecond=0)
        if self._header is None or value == self.start_time:
            return
        old = self.start_time
        self._push("Edit start time", lambda: setattr(self, "start_time", value), lambda: setattr(self, "start_time", old))

    def set_valve_rows(self, rows: Sequence[Sequence[str]]) -> None:
        if self._header is None:
            raise ValueError("Open or create a recipe first.")
        if not rows or len(rows) > RECIPE_COLS - 1 or any(len(row) != 3 for row in rows):
            raise ValueError("Valve metadata requires a chamber and at most eight valve rows.")
        before = self._header.copy(deep=True)
        old_count = self._valve_count
        after = before
        for column, key in enumerate(("valve", "name", "temperature")):
            after = _write_header(after, key, [str(row[column]) for row in rows])
        if before.equals(after) and old_count == len(rows):
            return

        def apply(header: pd.DataFrame, count: int) -> None:
            self._header = header.copy(deep=True)
            self._valve_count = count

        self._push(
            "Edit valve metadata",
            lambda: apply(after, len(rows)),
            lambda: apply(before, old_count),
        )

    @property
    def dirty(self) -> bool:
        return not self.undo_stack.isClean()

    @property
    def wait_seconds(self) -> float | None:
        try:
            value = float(self.wait_text.strip())
        except ValueError:
            return None
        return value if math.isfinite(value) and value >= 0 else None

    @property
    def predicted_end(self) -> datetime | None:
        wait = self.wait_seconds
        if self.run_seconds is None or wait is None:
            return None
        try:
            return pd.Timestamp(self.start_time) + pd.to_timedelta(wait + self.run_seconds, unit="s")
        except (OverflowError, ValueError):
            return None

    @property
    def validation_errors(self) -> list[str]:
        if self.frame is None:
            return ["Open or create a recipe sheet to begin."]
        errors = [*self.sheet_errors, *self.timing_errors, *self.metadata_errors]
        if self.wait_seconds is None:
            errors.append("Wait time must be a finite non-negative number of seconds.")
        elif self.run_seconds is not None and self.predicted_end is None:
            errors.append("The predicted end time is outside the supported date range.")
        return errors

    @property
    def sequence_count(self) -> int:
        return len(self.timing.sequences) if self.timing is not None else 0

    @property
    def can_export(self) -> bool:
        return self.frame is not None and not self.validation_errors

    def mark_exported(self, path: Path) -> None:
        self.last_export_path = path
        self.undo_stack.setClean()
        self.changed.emit()
