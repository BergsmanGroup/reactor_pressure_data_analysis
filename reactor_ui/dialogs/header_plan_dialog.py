"""Explicit confirmation for a planned header correction."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from reactor_ui.adapters.header_changes import HeaderChangePlan, describe_header_change_plan
from reactor_ui.widgets.window_geometry import fit_to_available_screen


class HeaderPlanDialog(QDialog):
    def __init__(self, plan: HeaderChangePlan, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm Header File Changes")
        self.resize(1050, 650)
        layout = QVBoxLayout(self)
        warning = QLabel(
            "This will overwrite the following files and may rename related files. "
            "Backups will be created before any original is changed.",
            self,
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.plan_text = QPlainTextEdit(self)
        self.plan_text.setReadOnly(True)
        self.plan_text.setTabChangesFocus(True)
        self.plan_text.setPlainText(describe_header_change_plan(plan))
        self.plan_text.setAccessibleName("Complete list of planned file changes")
        layout.addWidget(self.plan_text, 1)
        self.confirmation = QCheckBox("I reviewed these paths and authorize the listed file changes.", self)
        layout.addWidget(self.confirmation)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.apply_button.setEnabled(False)
        self.apply_button.setAutoDefault(False)
        self.cancel_button.setDefault(True)
        self.confirmation.toggled.connect(self.apply_button.setEnabled)
        self.apply_button.clicked.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        fit_to_available_screen(self)
