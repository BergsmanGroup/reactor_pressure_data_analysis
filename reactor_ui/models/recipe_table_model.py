"""Editable view of the recipe's source timing rows."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from reactor_ui.models.recipe_document import TIMING_COLUMNS, RecipeDocument
from reactor_ui.theme import COLORS


class RecipeTableModel(QAbstractTableModel):
    def __init__(self, document: RecipeDocument) -> None:
        super().__init__(document)
        self.document = document
        document.aboutToReset.connect(self.beginResetModel)
        document.reset.connect(self.endResetModel)
        document.cellsChanged.connect(self._refresh_cells)

    def _refresh_cells(self) -> None:
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.document.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(TIMING_COLUMNS) + 2

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.document.rows)):
            return None
        column = index.column()
        error = self.document.cell_errors.get((index.row(), column - 2))
        if role == Qt.ItemDataRole.ToolTipRole and error:
            return error
        if role == Qt.ItemDataRole.BackgroundRole and error:
            return QColor("#633344")
        if role == Qt.ItemDataRole.ForegroundRole and error:
            return QColor(COLORS["error"])
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        if column == 0:
            return index.row() + 1
        if column == 1:
            return self.document.sequence_numbers[index.row()]
        if 2 <= column < self.columnCount():
            return self.document.rows[index.row()][column - 2]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if index.isValid() and index.column() >= 2 and self.document.frame is not None:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value: object, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or index.column() < 2:
            return False
        self.document.set_cells([(index.row(), index.column() - 2, str(value))])
        return True

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            headers = ("#", "Seq", *TIMING_COLUMNS)
            return headers[section] if 0 <= section < len(headers) else None
        return section + 1
