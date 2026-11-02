"""Application palette and stylesheet tokens."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication


COLORS = {
    "background": "#111522",
    "surface": "#1C2334",
    "surface_raised": "#273249",
    "card_border": "#4D5C78",
    "text": "#F4F7FF",
    "muted_text": "#BCC8DB",
    "primary": "#7350CE",
    "primary_hover": "#7954D0",
    "primary_text": "#C7B5FF",
    "button": "#3B5078",
    "button_hover": "#4A6391",
    "info": "#265F93",
    "info_hover": "#3175AE",
    "info_text": "#83D5FF",
    "success_button": "#196B56",
    "success_hover": "#20775F",
    "warning_button": "#795321",
    "warning_hover": "#91672D",
    "danger_button": "#873E57",
    "danger_hover": "#A14B69",
    "focus": "#C2ADFF",
    "selection": "#493B72",
    "error": "#F16D83",
    "warning": "#E9B75A",
    "success": "#64CEA1",
}


def create_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["background"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["surface_raised"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLORS["surface_raised"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["button"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(COLORS["error"]))
    palette.setColor(QPalette.ColorRole.Link, QColor(COLORS["primary_hover"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["selection"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(COLORS["muted_text"]))
    return palette


def create_stylesheet() -> str:
    return f"""
        QWidget {{
            color: {COLORS["text"]};
            font-size: 10pt;
        }}
        QMainWindow, QStackedWidget, QDialog {{
            background-color: {COLORS["background"]};
        }}
        QScrollArea, QWidget#pageHeader {{
            background-color: transparent;
        }}
        QFrame#navigationRail {{
            background-color: {COLORS["surface"]};
            border-right: 1px solid {COLORS["card_border"]};
        }}
        QFrame#card {{
            background-color: {COLORS["surface"]};
            border: 1px solid {COLORS["card_border"]};
            border-left: 3px solid {COLORS["primary_text"]};
            border-radius: 5px;
        }}
        QWidget#cardContent, QFrame#card QLabel {{
            background-color: transparent;
        }}
        QLabel#brandMark {{
            color: {COLORS["primary_text"]};
            font-size: 15pt;
            font-weight: 700;
        }}
        QLabel#brandTitle {{
            color: {COLORS["text"]};
            font-size: 10pt;
            font-weight: 600;
        }}
        QLabel#pageTitle {{
            font-size: 19pt;
            font-weight: 700;
        }}
        QLabel#pageSubtitle, QLabel#mutedText {{
            color: {COLORS["muted_text"]};
        }}
        QLabel#cardTitle {{
            font-size: 11pt;
            font-weight: 600;
        }}
        QToolButton#navButton {{
            color: {COLORS["muted_text"]};
            background-color: transparent;
            border: 1px solid transparent;
            border-radius: 7px;
            padding: 10px 12px;
            text-align: left;
        }}
        QToolButton#navButton:hover {{
            color: {COLORS["text"]};
            background-color: {COLORS["surface_raised"]};
        }}
        QToolButton#navButton:checked {{
            color: {COLORS["text"]};
            background-color: {COLORS["primary"]};
            border-color: {COLORS["primary"]};
            font-weight: 600;
        }}
        QToolButton#navButton:focus {{
            border: 2px solid {COLORS["focus"]};
        }}
        QPushButton {{
            background-color: {COLORS["button"]};
            border: 1px solid {COLORS["button_hover"]};
            border-radius: 3px;
            padding: 5px 11px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: {COLORS["button_hover"]};
            border-color: {COLORS["info_text"]};
        }}
        QPushButton:pressed {{
            background-color: {COLORS["selection"]};
        }}
        QPushButton:disabled, QPushButton#primaryButton:disabled {{
            color: {COLORS["muted_text"]};
            background-color: {COLORS["surface"]};
            border-color: {COLORS["card_border"]};
        }}
        QPushButton:focus {{
            border: 2px solid {COLORS["focus"]};
        }}
        QPushButton#primaryButton {{
            color: #FFFFFF;
            background-color: {COLORS["primary"]};
            border-color: {COLORS["primary"]};
            font-weight: 600;
        }}
        QPushButton#primaryButton:hover {{
            background-color: {COLORS["primary_hover"]};
        }}
        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox,
        QDoubleSpinBox, QDateTimeEdit, QTableView {{
            background-color: {COLORS["surface_raised"]};
            border: 1px solid {COLORS["card_border"]};
            border-radius: 3px;
            padding: 3px 5px;
            selection-background-color: {COLORS["selection"]};
        }}
        QLineEdit:read-only {{
            color: {COLORS["muted_text"]};
            background-color: {COLORS["surface"]};
        }}
        QHeaderView::section {{
            color: {COLORS["info_text"]};
            background-color: {COLORS["surface_raised"]};
            border: 0;
            border-right: 1px solid {COLORS["card_border"]};
            border-bottom: 1px solid {COLORS["card_border"]};
            padding: 5px;
            font-weight: 600;
        }}
        QTableView {{
            gridline-color: {COLORS["card_border"]};
            alternate-background-color: {COLORS["surface"]};
        }}
        QTableView::item:selected {{
            color: {COLORS["text"]};
            background-color: {COLORS["selection"]};
        }}
        QProgressBar {{
            background-color: {COLORS["surface_raised"]};
            border: 1px solid {COLORS["card_border"]};
            border-radius: 3px;
            text-align: center;
            min-height: 18px;
        }}
        QProgressBar::chunk {{
            background-color: {COLORS["success_button"]};
        }}
        QCheckBox {{
            spacing: 7px;
        }}
        QCheckBox::indicator:unchecked {{
            width: 14px;
            height: 14px;
            border: 2px solid {COLORS["muted_text"]};
            border-radius: 3px;
            background-color: {COLORS["surface_raised"]};
        }}
        QCheckBox::indicator:unchecked:hover {{
            border-color: {COLORS["focus"]};
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
        QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
        QDateTimeEdit:focus, QTableView:focus {{
            border: 1px solid {COLORS["focus"]};
        }}
        QScrollBar:vertical {{
            width: 10px;
            background: {COLORS["surface"]};
        }}
        QScrollBar::handle:vertical {{
            background: #71819F;
            min-height: 24px;
            border-radius: 4px;
        }}
        QScrollBar:horizontal {{
            height: 10px;
            background: {COLORS["surface"]};
        }}
        QScrollBar::handle:horizontal {{
            background: #71819F;
            min-width: 24px;
            border-radius: 4px;
        }}
        QScrollBar::add-line, QScrollBar::sub-line {{
            width: 0px;
            height: 0px;
        }}
        QScrollBar::add-page, QScrollBar::sub-page {{
            background: transparent;
        }}
        QSplitter::handle {{
            background-color: {COLORS["background"]};
        }}
        QSplitter::handle:horizontal {{
            width: 6px;
        }}
        QSplitter::handle:vertical {{
            height: 6px;
        }}
        QToolTip {{
            color: {COLORS["text"]};
            background-color: {COLORS["surface_raised"]};
            border: 1px solid {COLORS["card_border"]};
            padding: 4px;
        }}
    """ + "".join(
        f"""
        QFrame#card[accent="{tone}"] {{
            border-left-color: {text};
        }}
        QFrame#card[accent="{tone}"] QLabel#cardTitle {{
            color: {text};
        }}
        QPushButton[actionTone="{tone}"] {{
            background-color: {background};
            border-color: {hover};
        }}
        QPushButton[actionTone="{tone}"]:hover {{
            background-color: {hover};
        }}
        QPushButton[actionTone="{tone}"]:disabled {{
            color: {COLORS["muted_text"]};
            background-color: {COLORS["surface_raised"]};
            border-color: {COLORS["card_border"]};
        }}
        """
        for tone, text, background, hover in (
            ("primary", COLORS["primary_text"], COLORS["primary"], COLORS["primary_hover"]),
            ("info", COLORS["info_text"], COLORS["info"], COLORS["info_hover"]),
            ("success", COLORS["success"], COLORS["success_button"], COLORS["success_hover"]),
            ("warning", COLORS["warning"], COLORS["warning_button"], COLORS["warning_hover"]),
            ("danger", COLORS["error"], COLORS["danger_button"], COLORS["danger_hover"]),
        )
    )


def apply_theme(app: QApplication) -> None:
    installed_families = {family.casefold() for family in QFontDatabase.families()}
    font_family = "Segoe UI" if "segoe ui" in installed_families else app.font().family()
    app.setFont(QFont(font_family, 10))
    app.setPalette(create_palette())
    app.setStyleSheet(create_stylesheet())
