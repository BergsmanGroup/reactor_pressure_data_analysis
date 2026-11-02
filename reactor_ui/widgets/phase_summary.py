"""Read-only phase summary for a selected sequence."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from reactor_ui.models.recipe_timing import SequenceTiming, phase_summary
from recipe_timing_core import SLOT_LABELS


class PhaseSummaryWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(0)
        for column, title in enumerate(("Phase", "Per cycle (s)", "Total (s)", "Share")):
            grid.addWidget(QLabel(title, self), 0, column)
        self._cells: list[tuple[QLabel, QLabel, QLabel, QLabel]] = []
        for row, name in enumerate(("Total", *SLOT_LABELS), start=1):
            cells = tuple(QLabel("", self) for _ in range(4))
            cells[0].setText(name)
            for column, cell in enumerate(cells):
                grid.addWidget(cell, row, column)
            self._cells.append(cells)
        grid.setColumnStretch(0, 1)
        self.set_sequence(None)

    def set_sequence(self, sequence: SequenceTiming | None) -> None:
        rows = phase_summary(sequence) if sequence is not None else ()
        for index, cells in enumerate(self._cells):
            if index < len(rows):
                row = rows[index]
                cells[1].setText(f"{row.per_cycle_s:g}")
                cells[2].setText(f"{row.total_s:g}")
                cells[3].setText(f"{100 * row.fraction:.1f}%" if row.fraction is not None else "\N{EM DASH}")
            else:
                for cell in cells[1:]:
                    cell.setText("\N{EM DASH}")
