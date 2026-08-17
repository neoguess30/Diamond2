from __future__ import annotations
from typing import Any

try:
    from PyQt6.QtWidgets import QLabel
    from PyQt6.QtGui import QFont
except ImportError:
    class QLabel:
        def __init__(self, t=""): pass
        def setFont(self, f): pass
        def setStyleSheet(self, s): pass
        def setText(self, t): pass
    class QFont:
        class Weight:
            Bold = 700
        def __init__(self, *args, **kwargs): pass

from ui.themes.colors import (
    DARK_STAT_AVAILABLE, LIGHT_STAT_AVAILABLE,
    DARK_STAT_UNAVAILABLE, LIGHT_STAT_UNAVAILABLE,
    DARK_STAT_AUCTION, LIGHT_STAT_AUCTION,
    DARK_STAT_SOLD, LIGHT_STAT_SOLD,
    DARK_STAT_TAKEN, LIGHT_STAT_TAKEN,
    DARK_STAT_UNKNOWN, LIGHT_STAT_UNKNOWN,
    DARK_STAT_ERROR
)

class StatusBadge(QLabel):
    """Tactical status badge with high-contrast color mapping."""
    def __init__(self, status: str = "NONE", is_dark: bool = True):
        super().__init__()
        self.is_dark = is_dark
        self.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.set_status(status)

    def set_status(self, status: str):
        color_map = {
            "AVAILABLE": DARK_STAT_AVAILABLE if self.is_dark else LIGHT_STAT_AVAILABLE,
            "UNAVAILABLE": DARK_STAT_UNAVAILABLE if self.is_dark else LIGHT_STAT_UNAVAILABLE,
            "AUCTION": DARK_STAT_AUCTION if self.is_dark else LIGHT_STAT_AUCTION,
            "SOLD": DARK_STAT_SOLD if self.is_dark else LIGHT_STAT_SOLD,
            "TAKEN": DARK_STAT_TAKEN if self.is_dark else LIGHT_STAT_TAKEN,
            "ERROR": DARK_STAT_ERROR
        }
        col = color_map.get(status.upper(), DARK_STAT_UNKNOWN if self.is_dark else LIGHT_STAT_UNKNOWN)
        self.setText(f"STATUS:  [ {status.upper()} ]")
        self.setStyleSheet(f"color: {col}; background-color: rgba(0, 0, 0, 20%); padding: 6px; border-radius: 3px; font-weight: bold;")