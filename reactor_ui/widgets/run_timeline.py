"""Proportional run timeline and representative-cycle display."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QHelpEvent, QKeyEvent, QMouseEvent, QPaintEvent, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QToolTip, QWidget

from reactor_ui.models.recipe_timing import RunTiming, SequenceTiming, cycle_index, sequence_at
from reactor_ui.theme import COLORS
from recipe_timing_core import SLOT_LABELS


_SEQUENCE_COLORS = ("#8D72E8", "#5EA9C4", "#CE8FAE", "#72BEA0", "#D7A563", "#8A95D4")
_PHASE_COLORS = ("#628FBF", "#7DBBCE", "#B78ACF", "#D58B99", "#D9AE69", "#86B88A", "#7E9FC7")


def _time_label(seconds: float, span: float) -> str:
    if span >= 3600:
        return f"{seconds / 3600:.3g} h"
    if span >= 60:
        return f"{seconds / 60:.3g} min"
    return f"{seconds:.3g} s"


def _tick_labels(overview: QRectF, total: float, metrics: QFontMetrics) -> list[tuple[str, QRectF]]:
    candidates = []
    for step in range(5):
        x = overview.left() + overview.width() * step / 4
        text = _time_label(total * step / 4, total)
        width = float(metrics.horizontalAdvance(text) + 2)
        left = max(overview.left(), min(x - width / 2, overview.right() - width))
        candidates.append((text, QRectF(left, overview.bottom() + 8, width, 18)))
    first, last = candidates[0], candidates[-1]
    if first[1].right() + 4 > last[1].left():
        return [last]
    visible = [first]
    for candidate in candidates[1:-1]:
        if candidate[1].left() >= visible[-1][1].right() + 4 and candidate[1].right() + 4 <= last[1].left():
            visible.append(candidate)
    visible.append(last)
    return visible


class RunTimeline(QWidget):
    """Draw one run overview and one representative cycle without expansion."""

    playheadChanged = Signal(float)
    sequenceSelected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(174)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Run timeline")
        self.setAccessibleDescription(
            "Provisional serial timing. Use the left and right arrows, Home, or End to select a sequence."
        )
        self.setToolTip("Click or drag to select time; use arrow keys to select a sequence.")
        self.setMouseTracking(True)
        self._run: RunTiming | None = None
        self._time_s = 0.0
        self._selected: int | None = None
        self._dragging = False

    @property
    def run(self) -> RunTiming | None:
        return self._run

    @property
    def playhead_seconds(self) -> float:
        return self._time_s

    @property
    def selected_sequence(self) -> SequenceTiming | None:
        if self._run is None or self._selected is None:
            return None
        return next((seq for seq in self._run.sequences if seq.index == self._selected), None)

    def set_run(self, run: RunTiming | None) -> None:
        self._run = run
        if run is None or not run.sequences:
            self._time_s = 0.0
            self._selected = None
        else:
            self._time_s = min(max(self._time_s, 0.0), run.run_duration_s)
            selected = sequence_at(run, self._time_s)
            if run.run_duration_s == 0:
                selected = run.sequences[0]
            self._selected = selected.index if selected else None
        self.update()
        self.playheadChanged.emit(self._time_s)
        if self._selected is not None:
            self.sequenceSelected.emit(self._selected)

    def set_playhead(self, seconds: float) -> None:
        if not math.isfinite(seconds):
            raise ValueError("Elapsed time must be finite.")
        if self._run is None or not self._run.sequences:
            return
        seconds = min(max(0.0, seconds), self._run.run_duration_s)
        sequence = sequence_at(self._run, seconds)
        changed_time = seconds != self._time_s
        changed_sequence = sequence is not None and sequence.index != self._selected
        self._time_s = seconds
        if sequence is not None:
            self._selected = sequence.index
        self.update()
        if changed_sequence and self._selected is not None:
            self.sequenceSelected.emit(self._selected)
        if changed_time:
            self.playheadChanged.emit(seconds)

    def select_sequence(self, index: int) -> None:
        if self._run is None:
            raise ValueError("There is no run to select.")
        sequence = next((seq for seq in self._run.sequences if seq.index == index), None)
        if sequence is None:
            raise ValueError(f"Unknown sequence: {index}")
        changed_time = self._time_s != sequence.start_s
        changed_sequence = self._selected != index
        self._time_s = sequence.start_s
        self._selected = index
        self.update()
        if changed_sequence:
            self.sequenceSelected.emit(index)
        if changed_time:
            self.playheadChanged.emit(self._time_s)

    def overview_rect(self) -> QRectF:
        return QRectF(14.0, 40.0, max(0.0, self.width() - 28.0), 26.0)

    def sequence_rects(self) -> list[tuple[int, QRectF]]:
        if self._run is None or self._run.run_duration_s <= 0:
            return []
        rect = self.overview_rect()
        total = self._run.run_duration_s
        return [
            (
                seq.index,
                QRectF(
                    rect.left() + rect.width() * (seq.start_s / total),
                    rect.top(),
                    rect.width() * ((seq.end_s - seq.start_s) / total),
                    rect.height(),
                ),
            )
            for seq in self._run.sequences
        ]

    def _time_from_x(self, x: float) -> float:
        if self._run is None or self._run.run_duration_s <= 0:
            return 0.0
        rect = self.overview_rect()
        if rect.width() <= 0:
            return 0.0
        fraction = min(1.0, max(0.0, (x - rect.left()) / rect.width()))
        return fraction * self._run.run_duration_s

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(COLORS["text"]))
        painter.drawText(QRectF(14, 8, self.width() - 28, 22), Qt.AlignmentFlag.AlignLeft, "Full run")

        if self._run is None or not self._run.sequences:
            painter.setPen(QColor(COLORS["muted_text"]))
            painter.drawText(QRectF(14, 40, self.width() - 28, 60), Qt.AlignmentFlag.AlignLeft, "No recipe loaded.")
            return

        overview = self.overview_rect()
        painter.fillRect(overview, QColor(COLORS["surface_raised"]))
        for index, rect in self.sequence_rects():
            painter.fillRect(rect, QColor(_SEQUENCE_COLORS[(index - 1) % len(_SEQUENCE_COLORS)]))
            if rect.width() >= 32:
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(index))
            if index == self._selected and rect.width() > 0:
                painter.setPen(QPen(QColor(COLORS["focus"]), 2))
                painter.drawRect(rect)

        total = self._run.run_duration_s
        painter.setPen(QColor(COLORS["muted_text"]))
        for step in range(5):
            x = overview.left() + overview.width() * step / 4
            painter.drawLine(QPointF(x, overview.bottom() + 2), QPointF(x, overview.bottom() + 7))
        for label, text_rect in _tick_labels(overview, total, painter.fontMetrics()):
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)

        if total > 0:
            x = overview.left() + overview.width() * (self._time_s / total)
            painter.setPen(QPen(QColor("#FFFFFF"), 2))
            painter.drawLine(QPointF(x, overview.top() - 5), QPointF(x, overview.bottom() + 5))
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawPolygon(QPolygonF([QPointF(x - 5, overview.top() - 8), QPointF(x + 5, overview.top() - 8), QPointF(x, overview.top() - 2)]))

        sequence = self.selected_sequence
        painter.setPen(QColor(COLORS["text"]))
        if sequence is None:
            return
        current_cycle = cycle_index(sequence, self._time_s)
        cycle_text = str(current_cycle) if current_cycle is not None else "-"
        painter.drawText(
            QRectF(14, 112, self.width() - 28, 20),
            Qt.AlignmentFlag.AlignLeft,
            f"Sequence {sequence.index}  |  Cycle {cycle_text} / {sequence.cycle_count}",
        )
        cycle_rect = QRectF(14, 139, max(0, self.width() - 28), 25)
        painter.fillRect(cycle_rect, QColor(COLORS["surface_raised"]))
        if sequence.cycle_duration_s <= 0:
            painter.setPen(QColor(COLORS["muted_text"]))
            painter.drawText(cycle_rect, Qt.AlignmentFlag.AlignCenter, "Zero-duration cycle")
            return
        for event in sequence.events:
            event_rect = QRectF(
                cycle_rect.left() + cycle_rect.width() * event.start_s / sequence.cycle_duration_s,
                cycle_rect.top(),
                cycle_rect.width() * event.duration_s / sequence.cycle_duration_s,
                cycle_rect.height(),
            )
            painter.fillRect(event_rect, QColor(_PHASE_COLORS[SLOT_LABELS.index(event.slot)]))
            if event_rect.width() >= 52:
                painter.setPen(QColor("#11101B"))
                painter.drawText(event_rect, Qt.AlignmentFlag.AlignCenter, event.slot)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.overview_rect().contains(event.position()):
            self._dragging = True
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.set_playhead(self._time_from_x(event.position().x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            self.set_playhead(self._time_from_x(event.position().x()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self.set_playhead(self._time_from_x(event.position().x()))
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._run is None or not self._run.sequences:
            super().keyPressEvent(event)
            return
        sequences = self._run.sequences
        current = next((i for i, seq in enumerate(sequences) if seq.index == self._selected), 0)
        if event.key() == Qt.Key.Key_Left:
            current = max(0, current - 1)
        elif event.key() == Qt.Key.Key_Right:
            current = min(len(sequences) - 1, current + 1)
        elif event.key() == Qt.Key.Key_Home:
            current = 0
        elif event.key() == Qt.Key.Key_End:
            current = len(sequences) - 1
        else:
            super().keyPressEvent(event)
            return
        self.select_sequence(sequences[current].index)
        event.accept()

    def event(self, event: QEvent) -> bool:
        if isinstance(event, QHelpEvent) and event.type() == QEvent.Type.ToolTip:
            if self._run is not None and self.overview_rect().contains(event.pos()):
                sequence = sequence_at(self._run, self._time_from_x(event.pos().x()))
                if sequence is not None:
                    QToolTip.showText(
                        event.globalPos(),
                        f"Sequence {sequence.index}: {sequence.cycle_count} cycles\n"
                        f"Start {sequence.start_s:g} s; end {sequence.end_s:g} s\n"
                        f"Duration {sequence.end_s - sequence.start_s:g} s",
                        self,
                    )
                    return True
        return super().event(event)
