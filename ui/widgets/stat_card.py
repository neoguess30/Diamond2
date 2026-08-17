from __future__ import annotations
from typing import Any

try:
    from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont
except ImportError:
    class QFrame:
        def __init__(self, *args): pass
        def setFixedHeight(self, h): pass
        def setCursor(self, c): pass
        def setStyleSheet(self, s): pass
    class QVBoxLayout:
        def __init__(self, p=None): pass
        def setContentsMargins(self, *args): pass
        def setSpacing(self, s): pass
        def addLayout(self, l): pass
        def addWidget(self, w): pass
    class QHBoxLayout(QVBoxLayout):
        def addStretch(self): pass
    class QLabel:
        def __init__(self, t=""): pass
        def setFont(self, f): pass
        def setStyleSheet(self, s): pass
        def setText(self, t): pass
    class Qt:
        class CursorShape:
            PointingHandCursor = 0
    class QFont:
        class Weight:
            Bold = 700
            DemiBold = 600
        def __init__(self, *args, **kwargs): pass

from ui.themes.colors import (
    DARK_CARD, LIGHT_CARD,
    DARK_BORDER, LIGHT_BORDER,
    DARK_ROW_HOVER, LIGHT_ROW_HOVER,
    DARK_STAT_AVAILABLE, LIGHT_TEXT
)

class StatCard(QFrame):
    """
    Tactical Stat Card with Visual Hierarchy (Primary vs Secondary metrics)
    and live minute rate deltas (e.g. ▲ +4.2%/m).
    """
    def __init__(self, title: str, value: str, color: str, is_primary: bool = False, parent_gui: Any = None):
        super().__init__()
        self.title = title
        self.color = color
        self.is_primary = is_primary
        self.parent_gui = parent_gui
        self.current_value = value
        
        # Primary metrics (TOTAL, AVAILABLE, ERRORS) have a taller, more elevated stature
        self.setFixedHeight(76 if is_primary else 64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(1)
        
        top_h = QHBoxLayout()
        self.lbl_title = QLabel(f"// {title}")
        self.lbl_title.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        
        self.lbl_delta = QLabel("")
        self.lbl_delta.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        self.lbl_delta.setStyleSheet(f"color: {DARK_STAT_AVAILABLE};")
        
        top_h.addWidget(self.lbl_title)
        top_h.addStretch()
        top_h.addWidget(self.lbl_delta)
        
        self.lbl_value = QLabel(value)
        self.lbl_value.setFont(QFont("Segoe UI", 20 if is_primary else 15, QFont.Weight.Bold))
        
        layout.addLayout(top_h)
        layout.addWidget(self.lbl_value)
        self.update_style()

    def update_style(self):
        is_dark = self.parent_gui.is_dark if self.parent_gui else True
        bg = DARK_CARD if is_dark else LIGHT_CARD
        border = DARK_BORDER if is_dark else LIGHT_BORDER
        txt_val = "#FFFFFF" if is_dark else LIGHT_TEXT
        
        border_top_width = "3px" if self.is_primary else "2px"
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border: 1px solid {border};
                border-top: {border_top_width} solid {self.color};
                border-radius: 4px;
            }}
            QFrame:hover {{
                background-color: {DARK_ROW_HOVER if is_dark else LIGHT_ROW_HOVER};
                border-color: {self.color};
            }}
            QLabel {{
                border: none;
            }}
        """)
        if hasattr(self, 'lbl_title'):
            self.lbl_title.setStyleSheet(f"color: {self.color}; border: none;")
            self.lbl_value.setStyleSheet(f"color: {txt_val}; border: none;")

    def set_value_debounced(self, val: str, delta_str: str = ""):
        if self.current_value != val:
            self.current_value = val
            self.lbl_value.setText(val)
        if delta_str:
            self.lbl_delta.setText(delta_str)
        else:
            self.lbl_delta.setText("")