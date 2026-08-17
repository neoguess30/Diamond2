from __future__ import annotations

try:
    from PyQt6.QtGui import QFont
except ImportError:
    class QFont:
        class Weight:
            Bold = 700
            DemiBold = 600
        def __init__(self, *args, **kwargs): pass
        def setWeight(self, w): pass

def get_header_font(size: int = 12) -> QFont:
    f = QFont("Segoe UI", size)
    f.setWeight(QFont.Weight.Bold)
    return f

def get_code_font(size: int = 11) -> QFont:
    f = QFont("JetBrains Mono", size)
    f.setWeight(QFont.Weight.DemiBold)
    return f

def get_body_font(size: int = 10) -> QFont:
    return QFont("Segoe UI", size)

def get_caption_font(size: int = 8) -> QFont:
    return QFont("Segoe UI", size)