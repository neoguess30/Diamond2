from __future__ import annotations
from typing import Any
from pathlib import Path

try:
    from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
    from PyQt6.QtGui import QFont, QDesktopServices
    from PyQt6.QtCore import QUrl
except ImportError:
    class QFrame:
        def __init__(self): pass
        def setFixedHeight(self, h): pass
        def setStyleSheet(self, s): pass
    class QHBoxLayout:
        def __init__(self, p=None): pass
        def setContentsMargins(self, *args): pass
        def addWidget(self, w): pass
        def addStretch(self): pass
    class QLabel:
        def __init__(self, t=""): pass
        def setFont(self, f): pass
    class QPushButton:
        def __init__(self, t=""): pass
        def setFixedSize(self, w, h): pass
        class clicked:
            @staticmethod
            def connect(s): pass
    class QFont:
        class Weight:
            Bold = 700
        def __init__(self, *args, **kwargs): pass
    class QDesktopServices:
        @staticmethod
        def openUrl(u): pass
    class QUrl:
        @staticmethod
        def fromLocalFile(f): pass

from core.utils import get_real_desktop_path
from ui.themes.colors import DARK_CARD, DARK_BORDER, DARK_TEXT, DARK_PRIMARY

class FolderExportCard(QFrame):
    """Card displaying active rotated output folders with one-click opening."""
    def __init__(self, category: str = "AVAILABLE", count: int = 0):
        super().__init__()
        self.category = category.lower()
        self.count = count
        self.setFixedHeight(45)
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet(f"QFrame {{ background-color: {DARK_CARD}; border: 1px solid {DARK_BORDER}; border-radius: 4px; }} QLabel {{ color: {DARK_TEXT}; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        lbl_icon = QLabel("📁")
        lbl_name = QLabel(f"/{self.category.upper()}")
        lbl_name.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        
        self.lbl_count = QLabel(f"{self.count} saved")
        self.lbl_count.setFont(QFont("JetBrains Mono", 8))

        btn_open = QPushButton("OPEN")
        btn_open.setFixedSize(60, 24)
        btn_open.setStyleSheet(f"background-color: {DARK_PRIMARY}; color: black; font-weight: bold; border-radius: 2px;")
        btn_open.clicked.connect(self.open_folder)

        layout.addWidget(lbl_icon)
        layout.addWidget(lbl_name)
        layout.addStretch()
        layout.addWidget(self.lbl_count)
        layout.addWidget(btn_open)

    def open_folder(self):
        folder_path = get_real_desktop_path() / self.category
        folder_path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder_path)))