"""Application palette and stylesheet tokens."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication


COLORS = {
    "background": "#11101B",
    "surface": "#1B1928",
    "surface_raised": "#232034",
    "card_border": "#39344F",
    "text": "#F4F1FA",
    "muted_text": "#AAA5BA",
    "primary": "#9474F5",
    "primary_hover": "#A88EFF",
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
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["surface_raised"]))
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
            background-color: {COLORS["background"]};
            font-size: 10pt;
        }}
        QMainWindow, QStackedWidget {{
            background-color: {COLORS["background"]};
        }}
        QFrame#navigationRail {{
            background-color: {COLORS["surface"]};
            border-right: 1px solid {COLORS["card_border"]};
        }}
        QFrame#card {{
            background-color: {COLORS["surface"]};
            border: 1px solid {COLORS["card_border"]};
            border-radius: 10px;
        }}
        QFrame#card QWidget, QFrame#card QLabel {{
            background-color: transparent;
        }}
        QLabel#brandMark {{
            color: {COLORS["primary_hover"]};
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
            background-color: {COLORS["selection"]};
            border-color: {COLORS["primary"]};
            font-weight: 600;
        }}
        QToolButton#navButton:focus {{
            border: 2px solid {COLORS["focus"]};
        }}
        QPushButton {{
            background-color: {COLORS["surface_raised"]};
            border: 1px solid {COLORS["card_border"]};
            border-radius: 6px;
            padding: 7px 12px;
        }}
        QPushButton:hover {{
            border-color: {COLORS["primary"]};
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
            border-radius: 5px;
            selection-background-color: {COLORS["selection"]};
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
            background: {COLORS["card_border"]};
            min-height: 24px;
            border-radius: 4px;
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
    """


def apply_theme(app: QApplication) -> None:
    installed_families = {family.casefold() for family in QFontDatabase.families()}
    font_family = "Segoe UI" if "segoe ui" in installed_families else app.font().family()
    app.setFont(QFont(font_family, 10))
    app.setPalette(create_palette())
    app.setStyleSheet(create_stylesheet())
