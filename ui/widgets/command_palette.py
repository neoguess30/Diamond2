from __future__ import annotations
from typing import List, Tuple, Callable, Any

try:
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QLabel, QPushButton
    )
    from PyQt6.QtCore import Qt, QEvent
    from PyQt6.QtGui import QFont, QKeyEvent
except ImportError:
    class QDialog:
        def __init__(self, parent=None): pass
        def setWindowTitle(self, t): pass
        def resize(self, w, h): pass
        def setStyleSheet(self, s): pass
        def exec(self): pass
        def accept(self): pass
        def reject(self): pass
    class QVBoxLayout:
        def __init__(self, p=None): pass
        def setContentsMargins(self, *args): pass
        def setSpacing(self, s): pass
        def addWidget(self, w): pass
        def addLayout(self, l): pass
    class QHBoxLayout(QVBoxLayout):
        def addStretch(self): pass
    class QLineEdit:
        def __init__(self): pass
        def setPlaceholderText(self, t): pass
        def setFixedHeight(self, h): pass
        def text(self): return ""
        def setFocus(self): pass
        class textChanged:
            @staticmethod
            def connect(s): pass
        class returnPressed:
            @staticmethod
            def connect(s): pass
    class QListWidget:
        def __init__(self): pass
        def addItem(self, item): pass
        def clear(self): pass
        def currentRow(self): return 0
        def setCurrentRow(self, r): pass
        def count(self): return 0
        class itemActivated:
            @staticmethod
            def connect(s): pass
    class QListWidgetItem:
        def __init__(self, t=""): pass
    class QLabel:
        def __init__(self, t=""): pass
        def setFont(self, f): pass
        def setStyleSheet(self, s): pass
    class QPushButton:
        def __init__(self, t=""): pass
        def setFixedSize(self, w, h): pass
        def setStyleSheet(self, s): pass
        class clicked:
            @staticmethod
            def connect(s): pass
    class Qt:
        class WindowType:
            FramelessWindowHint = 1
            Popup = 2
        class Key:
            Key_Down = 1
            Key_Up = 2
            Key_Escape = 3
    class QFont:
        class Weight:
            Bold = 700
        def __init__(self, *args, **kwargs): pass

from ui.themes.colors import (
    DARK_PANEL, DARK_BORDER, DARK_TEXT, DARK_PRIMARY, DARK_ROW_SEL, DARK_MUTED
)

class CommandPaletteDialog(QDialog):
    """
    Tactical Command Palette (Ctrl + K / Cmd + K):
    Allows instant keyboard or mouse-driven execution of actions.
    Dismissible via [Esc], Close button [×], or clicking outside.
    """
    def __init__(self, commands: List[Tuple[str, str, Callable[[], None]]], parent=None):
        super().__init__(parent)
        self.commands = commands
        self.filtered_commands = list(commands)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.resize(540, 370)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_PANEL};
                border: 1px solid {DARK_PRIMARY};
                border-radius: 6px;
            }}
            QLineEdit {{
                background-color: #080B10;
                color: {DARK_TEXT};
                border: 1px solid {DARK_BORDER};
                border-radius: 4px;
                padding: 6px 10px;
                font-family: 'Segoe UI';
                font-size: 13px;
            }}
            QListWidget {{
                background-color: #080B10;
                color: {DARK_TEXT};
                border: 1px solid {DARK_BORDER};
                border-radius: 4px;
                font-family: 'Segoe UI';
                font-size: 11px;
            }}
            QListWidget::item {{
                padding: 8px 10px;
                border-bottom: 1px solid {DARK_BORDER};
            }}
            QListWidget::item:selected {{
                background-color: {DARK_ROW_SEL};
                color: {DARK_PRIMARY};
                border-left: 3px solid {DARK_PRIMARY};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)

        # Header Bar with Close Button
        head_lay = QHBoxLayout()
        lbl_head = QLabel("⚡ FALCON COMMAND PALETTE  [ Press ESC to close ]")
        lbl_head.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_head.setStyleSheet(f"color: {DARK_MUTED};")
        head_lay.addWidget(lbl_head)
        head_lay.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(24, 24)
        btn_close.setStyleSheet("border: none; color: #8493A5; font-size: 12px; font-weight: bold;")
        btn_close.clicked.connect(self.reject)
        head_lay.addWidget(btn_close)
        layout.addLayout(head_lay)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Type a command or search action...")
        self.txt_search.textChanged.connect(self.filter_commands)
        self.txt_search.returnPressed.connect(self.execute_selected)
        layout.addWidget(self.txt_search)

        self.list_commands = QListWidget()
        self.list_commands.itemActivated.connect(self.execute_selected)
        layout.addWidget(self.list_commands)

        self.populate_list()
        self.txt_search.setFocus()

    def populate_list(self):
        self.list_commands.clear()
        for title, category, _ in self.filtered_commands:
            item_text = f"[{category.upper()}]  {title}"
            self.list_commands.addItem(QListWidgetItem(item_text))
        if self.list_commands.count() > 0:
            self.list_commands.setCurrentRow(0)

    def filter_commands(self, query: str):
        q = query.strip().lower()
        if not q:
            self.filtered_commands = list(self.commands)
        else:
            self.filtered_commands = [
                c for c in self.commands if q in c[0].lower() or q in c[1].lower()
            ]
        self.populate_list()

    def execute_selected(self):
        row = self.list_commands.currentRow()
        if 0 <= row < len(self.filtered_commands):
            _, _, callback = self.filtered_commands[row]
            self.accept()
            if callback:
                callback()

    def keyPressEvent(self, event: Any):
        if event.key() == Qt.Key.Key_Down:
            curr = self.list_commands.currentRow()
            if curr < self.list_commands.count() - 1:
                self.list_commands.setCurrentRow(curr + 1)
        elif event.key() == Qt.Key.Key_Up:
            curr = self.list_commands.currentRow()
            if curr > 0:
                self.list_commands.setCurrentRow(curr - 1)
        elif event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)