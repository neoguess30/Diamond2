from __future__ import annotations
from ui.themes.colors import (
    LIGHT_BG, LIGHT_TEXT, LIGHT_PANEL, LIGHT_BORDER,
    LIGHT_STAT_AVAILABLE, LIGHT_PRIMARY, LIGHT_TABLE, LIGHT_ROW_SEL
)

LIGHT_STYLESHEET = f"""
QMainWindow {{
    background-color: {LIGHT_BG};
}}
QWidget {{
    color: {LIGHT_TEXT};
    font-family: 'Segoe UI', sans-serif;
}}
QLabel {{
    color: {LIGHT_TEXT};
}}
QPushButton {{
    background-color: {LIGHT_PANEL};
    color: {LIGHT_TEXT};
    border: 1px solid {LIGHT_BORDER};
    border-radius: 3px;
    padding: 4px 8px;
}}
QPushButton:hover {{
    border-color: {LIGHT_PRIMARY};
}}
QTextEdit {{
    background-color: #FFFFFF;
    color: {LIGHT_STAT_AVAILABLE};
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    border: 1px solid {LIGHT_BORDER};
    border-radius: 3px;
}}
QTableView {{
    background-color: {LIGHT_TABLE};
    gridline-color: {LIGHT_BORDER};
    border: 1px solid {LIGHT_BORDER};
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: {LIGHT_TEXT};
}}
QTableView::item:selected {{
    background-color: {LIGHT_ROW_SEL};
    color: {LIGHT_TEXT};
    border-left: 3px solid {LIGHT_PRIMARY};
}}
"""