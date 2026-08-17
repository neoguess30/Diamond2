from __future__ import annotations
from typing import Any

try:
    from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton, QLabel
    from PyQt6.QtGui import QFont
except ImportError:
    class QWidget:
        def __init__(self, parent=None): pass
    class QHBoxLayout:
        def __init__(self, p=None): pass
        def setContentsMargins(self, *args): pass
        def setSpacing(self, s): pass
        def addWidget(self, w): pass
    class QLineEdit:
        def __init__(self): pass
        def setFixedHeight(self, h): pass
        def setPlaceholderText(self, t): pass
        def text(self): return ""
        def clear(self): pass
        class textChanged:
            @staticmethod
            def connect(s): pass
        class returnPressed:
            @staticmethod
            def connect(s): pass
    class QPushButton:
        def __init__(self, t=""): pass
        def setFixedSize(self, w, h): pass
        def setStyleSheet(self, s): pass
        class clicked:
            @staticmethod
            def connect(s): pass
    class QLabel:
        def __init__(self, t=""): pass
        def setFont(self, f): pass
        def setText(self, t): pass
    class QFont:
        class Weight:
            Bold = 700
        def __init__(self, *args, **kwargs): pass

from parser.pattern_generator import LazyPatternGenerator
from ui.themes.colors import DARK_PRIMARY

class PatternEditorWidget(QWidget):
    """Input editor calculating live permutation estimates as user types."""
    def __init__(self, on_submit_callback: Any):
        super().__init__()
        self.on_submit_callback = on_submit_callback
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.txt_pattern = QLineEdit()
        self.txt_pattern.setFixedHeight(32)
        self.txt_pattern.setPlaceholderText("pattern (e.g. L_L_N)")
        self.txt_pattern.textChanged.connect(self.on_text_changed)
        self.txt_pattern.returnPressed.connect(self.submit)

        self.lbl_estimate = QLabel("0 candidates")
        self.lbl_estimate.setFont(QFont("Segoe UI", 8))

        self.btn_add = QPushButton("ADD")
        self.btn_add.setFixedSize(70, 32)
        self.btn_add.setStyleSheet(f"background-color: {DARK_PRIMARY}; color: black; font-weight: bold; border-radius: 3px;")
        self.btn_add.clicked.connect(self.submit)

        layout.addWidget(self.txt_pattern)
        layout.addWidget(self.btn_add)

    def on_text_changed(self, text: str):
        pat = text.strip()
        if pat:
            count = LazyPatternGenerator.calculate_possibilities(pat)
            self.lbl_estimate.setText(f"{count:,} candidates")
        else:
            self.lbl_estimate.setText("0 candidates")

    def submit(self):
        pat = self.txt_pattern.text().strip()
        if pat and self.on_submit_callback:
            self.on_submit_callback(pat)
            self.txt_pattern.clear()