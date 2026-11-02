"""In-memory recipe editor and controller-payload export."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDateTime, QEvent, QItemSelection, QItemSelectionModel, QModelIndex, QObject, QSignalBlocker, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from reactor_ui.adapters.recipe_conversion import export_payload
from reactor_ui.models.recipe_document import RecipeDocument
from reactor_ui.models.recipe_table_model import RecipeTableModel
from reactor_ui.theme import COLORS
from reactor_ui.widgets.card import Card
from reactor_ui.widgets.page_header import PageHeader
from reactor_ui.widgets.phase_summary import PhaseSummaryWidget
from reactor_ui.widgets.recipe_table import RecipeTableView
from reactor_ui.widgets.run_timeline import RunTimeline


class RecipeEditorPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.document = RecipeDocument(self)
        self.table_model = RecipeTableModel(self.document)
        self._syncing_table = False
        self._updating_timing = False
        self._draft_playhead = 0.0
        self._valve_edits: list[list[QLineEdit]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 24)
        layout.setSpacing(14)

        self.header = PageHeader("Recipe Editor", "Review a recipe sheet and export a controller payload.", self)
        self.new_button = QPushButton("New", self.header)
        self.open_button = QPushButton("Open...", self.header)
        self.export_button = QPushButton("Export Payload...", self.header)
        self.export_button.setObjectName("primaryButton")
        for button in (self.new_button, self.open_button, self.export_button):
            self.header.actions_layout.addWidget(button)
        layout.addWidget(self.header)

        self.vertical_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.vertical_splitter.setChildrenCollapsible(False)
        self.metadata_splitter = QSplitter(Qt.Orientation.Horizontal, self.vertical_splitter)
        self.metadata_splitter.setChildrenCollapsible(False)
        self.metadata_card = self._build_metadata_card()
        self.valve_card = self._build_valve_card()
        self.metadata_splitter.addWidget(self.metadata_card)
        self.metadata_splitter.addWidget(self.valve_card)
        self.metadata_splitter.setStretchFactor(0, 1)
        self.metadata_splitter.setStretchFactor(1, 1)
        self.metadata_splitter.setSizes([580, 580])
        self.vertical_splitter.addWidget(self.metadata_splitter)

        self.lower_splitter = QSplitter(Qt.Orientation.Horizontal, self.vertical_splitter)
        self.lower_splitter.setChildrenCollapsible(False)
        self.timeline_card = self._build_timeline_card()
        self.table_card = self._build_table_card()
        self.lower_splitter.addWidget(self.timeline_card)
        self.lower_splitter.addWidget(self.table_card)
        self.lower_splitter.setStretchFactor(0, 1)
        self.lower_splitter.setStretchFactor(1, 1)
        self.lower_splitter.setSizes([580, 580])
        self.vertical_splitter.addWidget(self.lower_splitter)
        self.vertical_splitter.setStretchFactor(0, 2)
        self.vertical_splitter.setStretchFactor(1, 3)
        self.vertical_splitter.setSizes([265, 525])
        layout.addWidget(self.vertical_splitter, 1)

        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        self.source_label = QLabel(self)
        self.source_label.setWordWrap(True)
        self.source_label.setObjectName("mutedText")
        self.export_path_label = QLabel(self)
        self.export_path_label.setWordWrap(True)
        self.export_path_label.setObjectName("mutedText")
        for label in (self.status_label, self.source_label, self.export_path_label):
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.status_label)
        layout.addWidget(self.source_label)
        layout.addWidget(self.export_path_label)

        self.new_button.clicked.connect(self._new_clicked)
        self.open_button.clicked.connect(self._open_clicked)
        self.export_button.clicked.connect(self._export_clicked)
        self.username_input.textChanged.connect(lambda text: self.document.set_metadata("username", text))
        self.description_input.textChanged.connect(
            lambda: self.document.set_metadata("info", self.description_input.toPlainText())
        )
        self.did_input.textChanged.connect(lambda text: self.document.set_metadata("did", text))
        self.edr_input.textChanged.connect(lambda text: self.document.set_metadata("edr", text))
        self.wait_input.textChanged.connect(self.document.set_wait_text)
        self.start_input.dateTimeChanged.connect(self._start_changed)
        self.timeline.playheadChanged.connect(self._playhead_changed)
        self.timeline.sequenceSelected.connect(self._sequence_selected)
        self.time_control.valueChanged.connect(self.timeline.set_playhead)
        self.timing_table.selectionModel().currentRowChanged.connect(self._table_row_changed)
        self.document.reset.connect(self._refresh_document)
        self.document.changed.connect(self._refresh_document)
        self._refresh_document()

    def set_compact(self, compact: bool) -> None:
        self.header.set_compact(compact)
        orientation = Qt.Orientation.Vertical if compact else Qt.Orientation.Horizontal
        self.metadata_splitter.setOrientation(orientation)
        self.lower_splitter.setOrientation(orientation)
        for card in (self.metadata_card, self.valve_card, self.timeline_card, self.table_card):
            card.setMinimumHeight(200 if compact else 0)
        self._layout_timing_actions(compact)

    def _build_metadata_card(self) -> Card:
        card = Card("Recipe Metadata", self)
        contents = QWidget(card)
        grid = QGridLayout(contents)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self.username_input = QLineEdit(contents)
        self.username_input.setAccessibleName("Recipe username")
        self.description_input = QPlainTextEdit(contents)
        self.description_input.setAccessibleName("Recipe description")
        self.description_input.setTabChangesFocus(True)
        self.description_input.setUndoRedoEnabled(False)
        self.description_input.setMinimumHeight(54)
        self.description_input.setMaximumHeight(72)
        self.did_input = QLineEdit(contents)
        self.did_input.setAccessibleName("Recipe DID")
        self.edr_input = QLineEdit(contents)
        self.edr_input.setAccessibleName("Recipe EDR")
        self.wait_input = QLineEdit(contents)
        self.wait_input.setAccessibleName("Wait time in seconds")
        self.start_input = QDateTimeEdit(contents)
        self.start_input.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.start_input.setCalendarPopup(True)
        self.start_input.setAccessibleName("Planned start time")
        self.run_duration_label = QLabel("-", contents)
        self.predicted_end_label = QLabel("-", contents)
        for editor in (
            self.username_input,
            self.description_input,
            self.did_input,
            self.edr_input,
            self.wait_input,
            self.start_input,
            self.start_input.findChild(QLineEdit),
        ):
            if editor is not None:
                editor.installEventFilter(self)

        for row, label, widget, column, span in (
            (0, "Username", self.username_input, 0, 3),
            (1, "Description", self.description_input, 0, 3),
            (2, "DID", self.did_input, 0, 1),
            (2, "EDR", self.edr_input, 2, 1),
            (3, "Wait time (s)", self.wait_input, 0, 1),
            (3, "Start time", self.start_input, 2, 1),
            (4, "Estimated run", self.run_duration_label, 0, 1),
            (4, "Predicted end", self.predicted_end_label, 2, 1),
        ):
            grid.addWidget(QLabel(label, contents), row, column)
            grid.addWidget(widget, row, column + 1, 1, span)
        self.metadata_scroll = QScrollArea(card)
        self.metadata_scroll.setWidgetResizable(True)
        self.metadata_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.metadata_scroll.setWidget(contents)
        card.add_widget(self.metadata_scroll)
        return card

    def _build_valve_card(self) -> Card:
        card = Card("Valve Metadata", self)
        self.valve_scroll = QScrollArea(card)
        self.valve_scroll.setWidgetResizable(True)
        self.valve_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        card.add_widget(self.valve_scroll)
        self.add_valve_button = QPushButton("Add valve", card)
        self.add_valve_button.clicked.connect(self._add_valve)
        card.add_widget(self.add_valve_button)
        return card

    def _build_timeline_card(self) -> Card:
        card = Card("Run Timeline & Sequence Details", self)
        self.timeline_scroll = QScrollArea(card)
        self.timeline_scroll.setWidgetResizable(True)
        self.timeline_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        contents = QWidget(self.timeline_scroll)
        layout = QVBoxLayout(contents)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.timeline_note = QLabel("Provisional timing: current serial estimate.", contents)
        self.timeline_note.setObjectName("mutedText")
        self.timeline_note.setToolTip("Controller timing order and overlap have not been independently confirmed.")
        layout.addWidget(self.timeline_note)
        self.timeline = RunTimeline(contents)
        layout.addWidget(self.timeline)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Elapsed time (s)", contents))
        self.time_control = QDoubleSpinBox(contents)
        self.time_control.setDecimals(6)
        self.time_control.setRange(0, 0)
        self.time_control.setAccessibleName("Timeline elapsed time in seconds")
        time_row.addWidget(self.time_control)
        time_row.addStretch(1)
        layout.addLayout(time_row)

        self.sequence_details = QLabel("No sequence selected.", contents)
        self.sequence_details.setWordWrap(True)
        layout.addWidget(self.sequence_details)
        self.phase_summary = PhaseSummaryWidget(contents)
        layout.addWidget(self.phase_summary)
        layout.addStretch(1)
        self.timeline_scroll.setWidget(contents)
        card.add_widget(self.timeline_scroll)
        return card

    def _build_table_card(self) -> Card:
        card = Card("Timing Table", self)
        self.timing_table = RecipeTableView(self.document, card)
        self.timing_table.setObjectName("recipeTimingTable")
        self.timing_table.setAccessibleName("Recipe timing table")
        self.timing_table.setModel(self.table_model)
        self.timing_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.timing_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.timing_table.setAlternatingRowColors(True)
        self.timing_table.verticalHeader().setVisible(False)
        self.timing_table.horizontalHeader().setStretchLastSection(True)
        card.add_widget(self.timing_table)

        actions = QWidget(card)
        self.timing_actions_layout = QGridLayout(actions)
        self.timing_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.insert_above_button = QPushButton("Insert above", actions)
        self.insert_below_button = QPushButton("Insert below", actions)
        self.delete_rows_button = QPushButton("Delete rows", actions)
        self.undo_button = QPushButton("Undo", actions)
        self.redo_button = QPushButton("Redo", actions)
        self.timing_action_buttons = (
            self.insert_above_button,
            self.insert_below_button,
            self.delete_rows_button,
            self.undo_button,
            self.redo_button,
        )
        self._layout_timing_actions(False)
        card.add_widget(actions)
        self.insert_above_button.clicked.connect(lambda: self._insert_row(False))
        self.insert_below_button.clicked.connect(lambda: self._insert_row(True))
        self.delete_rows_button.clicked.connect(self._delete_rows)

        self.undo_action = self.document.undo_stack.createUndoAction(self, "Undo")
        self.undo_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Undo))
        self.undo_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.addAction(self.undo_action)
        self.redo_action = self.document.undo_stack.createRedoAction(self, "Redo")
        self.redo_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Redo))
        self.redo_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.addAction(self.redo_action)
        self.undo_button.clicked.connect(self.undo_action.trigger)
        self.redo_button.clicked.connect(self.redo_action.trigger)
        self.document.undo_stack.canUndoChanged.connect(self.undo_button.setEnabled)
        self.document.undo_stack.canRedoChanged.connect(self.redo_button.setEnabled)
        self.undo_button.setEnabled(False)
        self.redo_button.setEnabled(False)
        return card

    def _layout_timing_actions(self, compact: bool) -> None:
        for button in self.timing_action_buttons:
            self.timing_actions_layout.removeWidget(button)
        for index, button in enumerate(self.timing_action_buttons):
            self.timing_actions_layout.addWidget(button, index // 3 if compact else 0, index % 3 if compact else index)
        for column in range(6):
            self.timing_actions_layout.setColumnStretch(column, int(column == (3 if compact else 5)))

    def _refresh_document(self) -> None:
        doc = self.document
        active = doc.frame is not None
        for widget, value in (
            (self.username_input, doc.metadata_text("username")),
            (self.did_input, doc.metadata_text("did")),
            (self.edr_input, doc.metadata_text("edr")),
        ):
            widget.setEnabled(active)
            if widget.text() != value:
                with QSignalBlocker(widget):
                    widget.setText(value)
        self.description_input.setEnabled(active)
        description = doc.metadata_text("info")
        if self.description_input.toPlainText() != description:
            with QSignalBlocker(self.description_input):
                self.description_input.setPlainText(description)
        self.wait_input.setEnabled(active)
        self.start_input.setEnabled(active)
        self.add_valve_button.setEnabled(active)
        self.insert_above_button.setEnabled(active)
        self.insert_below_button.setEnabled(active)
        self.delete_rows_button.setEnabled(active and bool(doc.rows))
        with QSignalBlocker(self.wait_input), QSignalBlocker(self.start_input):
            self.wait_input.setText(doc.wait_text)
            self.start_input.setDateTime(QDateTime(doc.start_time))
        self._refresh_valves()
        with QSignalBlocker(self.time_control):
            self.time_control.setRange(0.0, doc.timing.run_duration_s if doc.timing is not None else 0.0)
            self.time_control.setEnabled(doc.timing is not None and bool(doc.timing.sequences))
        old_syncing = self._syncing_table
        self._syncing_table = True
        self._updating_timing = True
        try:
            self.timeline.set_run(doc.timing)
            if doc.timing is None:
                self.phase_summary.set_sequence(None)
                self.sequence_details.setText("Preview is stale; correct the timing errors." if active else "No sequence selected.")
                self.timeline_note.setText("Preview is stale until timing errors are corrected." if active else "Provisional timing: current serial estimate.")
            else:
                self.timeline_note.setText("Provisional timing: current serial estimate.")
                self.timeline.set_playhead(self._draft_playhead)
                self._draft_playhead = self.timeline.playhead_seconds
        finally:
            self._updating_timing = False
            self._syncing_table = old_syncing
        selected = self.timeline.selected_sequence
        current = self.timing_table.currentIndex()
        if (
            not self._syncing_table
            and selected is not None
            and (not current.isValid() or current.row() not in selected.row_indices)
        ):
            self._sequence_selected(selected.index)
        self._refresh_status()

    def _refresh_valves(self) -> None:
        rows = self.document.valve_rows
        if len(self._valve_edits) != len(rows) or self.valve_scroll.widget() is None:
            contents = QWidget(self.valve_scroll)
            grid = QGridLayout(contents)
            grid.setContentsMargins(0, 0, 0, 0)
            self._valve_edits = []
            titles = ("Valve #", "Name", "Temperature (C)")
            for column, title in enumerate(titles):
                grid.addWidget(QLabel(title, contents), 0, column)
            for row, values in enumerate(rows):
                editors: list[QLineEdit] = []
                for column, value in enumerate(values):
                    editor = QLineEdit(value, contents)
                    editor.setAccessibleName(f"Valve metadata row {row + 1}, {titles[column]}")
                    if row == 0 and column < 2:
                        editor.setReadOnly(True)
                    editor.installEventFilter(self)
                    editor.textEdited.connect(lambda text, r=row, c=column: self._valve_edited(r, c, text))
                    grid.addWidget(editor, row + 1, column)
                    editors.append(editor)
                if row:
                    remove = QPushButton("Remove", contents)
                    remove.clicked.connect(lambda _=False, r=row: self._remove_valve(r))
                    grid.addWidget(remove, row + 1, 3)
                self._valve_edits.append(editors)
            grid.setRowStretch(grid.rowCount(), 1)
            grid.setColumnStretch(1, 1)
            self.valve_scroll.setWidget(contents)
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                editor = self._valve_edits[row][column]
                if editor.text() != value:
                    with QSignalBlocker(editor):
                        editor.setText(value)
                error = self.document.valve_errors.get((row, column), "")
                editor.setToolTip(error)
                editor.setStyleSheet(f"border: 1px solid {COLORS['error']};" if error else "")

    def _valve_edited(self, row: int, column: int, text: str) -> None:
        rows = [values[:] for values in self.document.valve_rows]
        if row < len(rows) and rows[row][column] != text:
            rows[row][column] = text
            self.document.set_valve_rows(rows)

    def _add_valve(self) -> None:
        rows = [values[:] for values in self.document.valve_rows]
        if not rows:
            rows = [["nan", "Chamber", ""]]
        try:
            self.document.set_valve_rows([*rows, ["", "", ""]])
        except ValueError as exc:
            QMessageBox.warning(self, "Valve metadata", str(exc))

    def _remove_valve(self, row: int) -> None:
        rows = [values[:] for index, values in enumerate(self.document.valve_rows) if index != row]
        self.document.set_valve_rows(rows)

    def _insert_row(self, below: bool) -> None:
        current = self.timing_table.currentIndex()
        index = current.row() + int(below) if current.isValid() else len(self.document.rows)
        self.document.insert_row(index)
        self.timing_table.setCurrentIndex(self.table_model.index(index, 2))

    def _delete_rows(self) -> None:
        rows = sorted({index.row() for index in self.timing_table.selectionModel().selectedIndexes()})
        if not rows and self.timing_table.currentIndex().isValid():
            rows = [self.timing_table.currentIndex().row()]
        try:
            self.document.delete_rows(rows)
        except ValueError as exc:
            QMessageBox.warning(self, "Delete rows", str(exc))

    def _refresh_status(self) -> None:
        doc = self.document
        errors = doc.validation_errors
        self.export_button.setEnabled(doc.can_export)
        message = " | ".join(errors[:3]) if errors else "Recipe valid"
        if len(errors) > 3:
            message += f" | {len(errors) - 3} more error(s)"
        if doc.dirty:
            message += " - modified"
        self.status_label.setText(message)
        self.status_label.setToolTip("\n".join(errors))
        color = COLORS["error"] if errors else COLORS["success"]
        self.status_label.setStyleSheet(f"color: {color};")
        source = str(doc.source_path) if doc.source_path else ("new in-memory draft" if doc.frame is not None else "none")
        self.source_label.setText(f"Source: {source}")
        self.export_path_label.setText(f"Last export: {doc.last_export_path}" if doc.last_export_path else "Last export: none")
        if doc.run_seconds is None:
            self.run_duration_label.setText("-")
        else:
            duration = f"{doc.run_seconds:,.2f} s ({doc.run_seconds / 3600:,.2f} h)"
            self.run_duration_label.setText(duration)
        self.predicted_end_label.setText(
            doc.predicted_end.strftime("%Y-%m-%d %H:%M:%S") if doc.predicted_end else "-"
        )

    def _playhead_changed(self, seconds: float) -> None:
        if not self._updating_timing and self.document.timing is not None:
            self._draft_playhead = seconds
        with QSignalBlocker(self.time_control):
            self.time_control.setValue(seconds)

    def _sequence_selected(self, index: int) -> None:
        sequence = self.timeline.selected_sequence
        if sequence is None or sequence.index != index:
            return
        self.phase_summary.set_sequence(sequence)
        self.sequence_details.setText(
            f"Sequence {index}: {sequence.cycle_count} cycles, "
            f"{sequence.cycle_duration_s:g} s per cycle, "
            f"{sequence.end_s - sequence.start_s:g} s total."
        )
        if self._syncing_table:
            return
        selection_model = self.timing_table.selectionModel()
        first = self.table_model.index(sequence.first_row, 0)
        last = self.table_model.index(sequence.row_indices[-1], self.table_model.columnCount() - 1)
        with QSignalBlocker(selection_model):
            selection_model.select(
                QItemSelection(first, last),
                QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
            )
            selection_model.setCurrentIndex(first, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.timing_table.scrollTo(first)

    def _table_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        del previous
        if self._syncing_table or not current.isValid() or self.document.timing is None:
            return
        sequence = next(
            (seq for seq in self.document.timing.sequences if current.row() in seq.row_indices),
            None,
        )
        if sequence is not None:
            self._syncing_table = True
            try:
                self.timeline.select_sequence(sequence.index)
            finally:
                self._syncing_table = False

    def _start_changed(self, value: QDateTime) -> None:
        self.document.set_start_time(value.toPython())

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(event, QKeyEvent) and event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            undo = event.matches(QKeySequence.StandardKey.Undo)
            redo = event.matches(QKeySequence.StandardKey.Redo)
            if undo or redo:
                if event.type() == QEvent.Type.KeyPress:
                    if undo:
                        self.document.undo_stack.undo()
                    else:
                        self.document.undo_stack.redo()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def open_recipe(self, path: str | Path) -> None:
        previous_playhead = self._draft_playhead
        self._draft_playhead = 0.0
        try:
            self.document.load(path)
        except Exception:
            self._draft_playhead = previous_playhead
            raise
        self.timing_table.resizeColumnsToContents()
        if self.timeline.selected_sequence is not None:
            self._sequence_selected(self.timeline.selected_sequence.index)

    def confirm_discard(self) -> bool:
        self._finish_pending_edit()
        if not self.document.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Discard recipe changes?",
            "The in-memory recipe changes have not been exported. Discard them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _finish_pending_edit(self) -> None:
        focused = QApplication.focusWidget()
        if focused is not None and self.timing_table.isAncestorOf(focused):
            focused.clearFocus()

    def _new_clicked(self) -> None:
        if self.confirm_discard():
            self._draft_playhead = 0.0
            self.document.new_draft()
            self.timing_table.resizeColumnsToContents()

    def _open_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Recipe Sheet", "", "Recipe sheets (*.xlsx *.xls *.csv);;All files (*)"
        )
        if not path or not self.confirm_discard():
            return
        try:
            self.open_recipe(path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not open recipe", str(exc))

    def _export_clicked(self) -> None:
        self._finish_pending_edit()
        if not self.document.can_export:
            QMessageBox.warning(self, "Cannot export", "\n".join(self.document.validation_errors))
            return
        source = self.document.source_path
        suggested = source.with_name(f"{source.stem}_payload.json") if source else Path.home() / "recipe_payload.json"
        path, _ = QFileDialog.getSaveFileName(self, "Export Payload", str(suggested), "JSON files (*.json)")
        if not path:
            return
        try:
            saved = export_payload(self.document, path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not export payload", str(exc))
            return
        QMessageBox.information(self, "Payload exported", f"Payload written to:\n{saved}\n\nSource unchanged:\n{source}")
