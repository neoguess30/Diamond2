from __future__ import annotations
from ui.themes.colors import (
    DARK_BG, DARK_TEXT, DARK_PANEL, DARK_BORDER,
    DARK_STAT_AVAILABLE, DARK_PRIMARY, DARK_TABLE, DARK_ROW_SEL
)

DARK_STYLESHEET = f"""
QMainWindow {{
    background-color: {DARK_BG};
}}
QWidget {{
    color: {DARK_TEXT};
    font-family: 'Segoe UI', sans-serif;
}}
QLabel {{
    color: {DARK_TEXT};
}}
QPushButton {{
    background-color: {DARK_PANEL};
    color: {DARK_TEXT};
    border: 1px solid {DARK_BORDER};
    border-radius: 3px;
    padding: 4px 8px;
}}
QPushButton:hover {{
    border-color: {DARK_PRIMARY};
}}
QTextEdit {{
    background-color: #05070A;
    color: {DARK_STAT_AVAILABLE};
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    border: 1px solid {DARK_BORDER};
    border-radius: 3px;
}}
QTableView {{
    background-color: {DARK_TABLE};
    gridline-color: {DARK_BORDER};
    border: 1px solid {DARK_BORDER};
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: {DARK_TEXT};
}}
QTableView::item:selected {{
    background-color: {DARK_ROW_SEL};
    color: {DARK_TEXT};
    border-left: 3px solid {DARK_PRIMARY};
}}
"""