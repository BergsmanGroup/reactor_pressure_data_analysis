"""Editable models for header timing rows and valve metadata."""

from __future__ import annotations

import copy
from decimal import Decimal

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from reactor_ui.models.recipe_timing import RecipeTimingError, _integer, compute_run_timing
from recipe_timing_core import TIMING_COLUMNS


def display_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(display_cell(item) for item in value)
    return str(value)


def parse_token(text: str):
    value = text.strip()
    if not value:
        return ""
    if value.upper() in {"TRUE", "FALSE"}:
        return value.upper() == "TRUE"
    try:
        number = Decimal(value)
        if number.is_finite():
            return int(number) if number == number.to_integral_value() else float(number)
    except ArithmeticError:
        pass
    return value


def parse_list(text: str) -> list:
    return [parse_token(part) for part in text.split(",") if part.strip()]


class HeaderTableModel(QAbstractTableModel):
    def __init__(self, headers: tuple[str, ...], rows: list[list[str]], parent=None) -> None:
        super().__init__(parent)
        self.headers = headers
        self.rows = [list(row[: len(headers)]) + [""] * max(0, len(headers) - len(row)) for row in rows]
        if not self.rows:
            self.rows = [[""] * len(headers)]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self.rows[index.row()][index.column()]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        return flags | Qt.ItemFlag.ItemIsEditable if index.isValid() else flags

    def setData(self, index: QModelIndex, value: object, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        text = str(value)
        if self.rows[index.row()][index.column()] != text:
            self.rows[index.row()][index.column()] = text
            self.dataChanged.emit(index, index, [role, Qt.ItemDataRole.DisplayRole])
        return True

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.headers[section] if 0 <= section < len(self.headers) else None
        return section + 1

    def insert_row(self, row: int) -> None:
        row = max(0, min(row, len(self.rows)))
        self.beginInsertRows(QModelIndex(), row, row)
        self.rows.insert(row, [""] * len(self.headers))
        self.endInsertRows()

    def remove_row(self, row: int) -> None:
        if not 0 <= row < len(self.rows):
            return
        if len(self.rows) == 1:
            self.reset_rows([[""] * len(self.headers)])
        else:
            self.beginRemoveRows(QModelIndex(), row, row)
            del self.rows[row]
            self.endRemoveRows()

    def reset_rows(self, rows: list[list[str]]) -> None:
        self.beginResetModel()
        self.rows = copy.deepcopy(rows) or [[""] * len(self.headers)]
        self.endResetModel()


class HeaderTimingModel(HeaderTableModel):
    def __init__(self, sequence: object, parent=None) -> None:
        if not isinstance(sequence, list):
            raise ValueError("The header valveSequence must be a list of rows.")
        rows: list[list[str]] = []
        self.extras: list[list] = []
        for index, row in enumerate(sequence, start=1):
            if not isinstance(row, (list, tuple)):
                raise ValueError(f"Header timing row {index} is not a list.")
            rows.append([display_cell(value) for value in row[:9]])
            self.extras.append(copy.deepcopy(list(row[9:])))
        super().__init__(tuple(TIMING_COLUMNS[:9]), rows, parent)
        if not self.extras:
            self.extras = [[]]
        self.original_rows = copy.deepcopy(self.rows)
        self.original_extras = copy.deepcopy(self.extras)

    def insert_row(self, row: int) -> None:
        row = max(0, min(row, len(self.rows)))
        self.extras.insert(row, [])
        super().insert_row(row)

    def remove_row(self, row: int) -> None:
        if not 0 <= row < len(self.rows):
            return
        if len(self.rows) == 1:
            self.extras = [[]]
        else:
            del self.extras[row]
        super().remove_row(row)

    def reset_original(self) -> None:
        self.extras = copy.deepcopy(self.original_extras)
        self.reset_rows(self.original_rows)

    def sequence(self) -> list[list]:
        retained = [
            (row, extra) for row, extra in zip(self.rows, self.extras)
            if any(cell.strip() for cell in row) or extra
        ]
        if not retained:
            raise ValueError("The header must contain at least one timing row.")
        try:
            compute_run_timing([row for row, _ in retained])
        except RecipeTimingError as exc:
            first = exc.issues[0]
            raise ValueError(f"Timing row {first.row + 1}, {TIMING_COLUMNS[first.column]}: {first.message}") from exc
        result = []
        for row, extra in retained:
            values = []
            for column, value in enumerate(row):
                text = value.strip()
                if not text:
                    values.append("")
                elif column < 2:
                    number = _integer(text, blank_is_zero=False)
                    assert number is not None
                    values.append(number)
                else:
                    values.append(parse_token(text))
            result.append(values + copy.deepcopy(extra))
        return result
