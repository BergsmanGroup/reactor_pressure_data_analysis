"""Editable timing table with rectangular TSV clipboard operations."""

from __future__ import annotations

import csv
import io

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QStyledItemDelegate, QTableView, QWidget

from reactor_ui.models.recipe_document import RecipeDocument


class RecipeCellDelegate(QStyledItemDelegate):
    def createEditor(self, parent: QWidget, option, index: QModelIndex) -> QWidget:
        del option
        editor = QLineEdit(parent)
        column = index.column()
        if column == 2:
            editor.setPlaceholderText("Blank or 0 continues a sequence")
        elif column == 3:
            editor.setPlaceholderText("Declared valve number")
        elif 4 <= column <= 10:
            editor.setPlaceholderText("Non-negative seconds")
        return editor


class RecipeTableView(QTableView):
    def __init__(self, document: RecipeDocument, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.document = document
        self.setItemDelegate(RecipeCellDelegate(self))

    def copy_selection(self) -> None:
        indexes = self.selectionModel().selectedIndexes()
        if not indexes and self.currentIndex().isValid():
            indexes = [self.currentIndex()]
        if not indexes:
            raise ValueError("Select cells to copy.")
        cells = {(index.row(), index.column()): index for index in indexes}
        first_row = min(row for row, _ in cells)
        last_row = max(row for row, _ in cells)
        first_column = min(column for _, column in cells)
        last_column = max(column for _, column in cells)
        if len(cells) != (last_row - first_row + 1) * (last_column - first_column + 1):
            raise ValueError("Select a single rectangular range to copy.")
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        for row in range(first_row, last_row + 1):
            writer.writerow(
                [
                    str(cells[(row, column)].data(Qt.ItemDataRole.DisplayRole) or "")
                    for column in range(first_column, last_column + 1)
                ]
            )
        QApplication.clipboard().setText(output.getvalue().removesuffix("\n"))

    def paste_selection(self) -> None:
        current = self.currentIndex()
        if not current.isValid() or current.column() < 2:
            raise ValueError("Choose an editable timing cell as the paste destination.")
        self.document.paste_rectangle(current.row(), current.column() - 2, QApplication.clipboard().text())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            operation = self.copy_selection
        elif event.matches(QKeySequence.StandardKey.Paste):
            operation = self.paste_selection
        else:
            super().keyPressEvent(event)
            return
        try:
            operation()
        except ValueError as exc:
            QMessageBox.warning(self, "Clipboard operation", str(exc))
        event.accept()
