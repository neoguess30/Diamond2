from __future__ import annotations
from typing import Any

try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
        QPushButton, QTableView, QHeaderView, QAbstractItemView, QMenu, QApplication
    )
    from PyQt6.QtCore import Qt, QUrl, QModelIndex
    from PyQt6.QtGui import QFont, QDesktopServices, QAction
except ImportError:
    class QWidget:
        def __init__(self, parent=None): pass
    class QVBoxLayout:
        def __init__(self, p=None): pass
        def setContentsMargins(self, *args): pass
        def setSpacing(self, s): pass
        def addWidget(self, w): pass
        def addLayout(self, l): pass
    class QHBoxLayout(QVBoxLayout):
        def addStretch(self): pass
    class QLabel:
        def __init__(self, t=""): pass
        def setFont(self, f): pass
        def setStyleSheet(self, s): pass
        def setText(self, t): pass
    class QLineEdit:
        def __init__(self): pass
        def setPlaceholderText(self, t): pass
        def setFixedHeight(self, h): pass
        def setStyleSheet(self, s): pass
        def text(self): return ""
        class textChanged:
            @staticmethod
            def connect(s): pass
    class QPushButton:
        def __init__(self, t=""): pass
        def setFixedSize(self, w, h): pass
        def setCheckable(self, c): pass
        def setChecked(self, c): pass
        def setStyleSheet(self, s): pass
        class clicked:
            @staticmethod
            def connect(s): pass
    class QTableView:
        def __init__(self): pass
        def setModel(self, m): pass
        def setEditTriggers(self, t): pass
        def setSelectionBehavior(self, b): pass
        def setSelectionMode(self, m): pass
        def setSortingEnabled(self, e): pass
        def setContextMenuPolicy(self, p): pass
        def setColumnWidth(self, c, w): pass
        def horizontalHeader(self):
            class _H:
                def setSectionResizeMode(self, *args): pass
            return _H()
        def verticalHeader(self):
            class _V:
                def setDefaultSectionSize(self, s): pass
            return _V()
        def verticalScrollBar(self):
            class _SB:
                def value(self): return 0
                def maximum(self): return 0
            return _SB()
        def scrollToBottom(self): pass
        def currentIndex(self): pass
        def viewport(self):
            class _VP:
                def mapToGlobal(self, p): pass
            return _VP()
        def setStyleSheet(self, s): pass
        class clicked:
            @staticmethod
            def connect(s): pass
        class customContextMenuRequested:
            @staticmethod
            def connect(s): pass
    class QHeaderView:
        class ResizeMode:
            Stretch = 1
    class QAbstractItemView:
        class EditTrigger:
            NoEditTriggers = 0
        class SelectionBehavior:
            SelectRows = 1
        class SelectionMode:
            SingleSelection = 1
    class QMenu:
        def __init__(self, p=None): pass
        def addAction(self, a): pass
        def addSeparator(self): pass
        def exec(self, p): pass
    class QAction:
        def __init__(self, t, p=None): pass
        class triggered:
            @staticmethod
            def connect(s): pass
    class QApplication:
        @staticmethod
        def clipboard():
            class _C:
                def setText(self, t): pass
            return _C()
    class Qt:
        class ContextMenuPolicy:
            CustomContextMenu = 0
    class QUrl:
        def __init__(self, u): pass
    class QFont:
        class Weight:
            Bold = 700
        def __init__(self, *args, **kwargs): pass
    class QDesktopServices:
        @staticmethod
        def openUrl(u): pass

from ui.themes.colors import (
    DARK_TABLE, LIGHT_TABLE,
    DARK_TEXT, LIGHT_TEXT,
    DARK_BORDER, LIGHT_BORDER,
    DARK_ROW_SEL, LIGHT_ROW_SEL,
    DARK_PRIMARY, LIGHT_PRIMARY,
    DARK_BG, LIGHT_BG,
    DARK_CARD, LIGHT_CARD,
    DARK_MUTED, LIGHT_MUTED,
    DARK_STAT_AVAILABLE, LIGHT_STAT_AVAILABLE,
    DARK_STAT_AUCTION, LIGHT_STAT_AUCTION,
    DARK_STAT_SOLD, LIGHT_STAT_SOLD,
    DARK_STAT_ERROR, LIGHT_STAT_ERROR
)

class LiveScannerView(QWidget):
    """
    LIVE SCANNER (HERO VIEW)
    The central operational stage featuring live search query filtering,
    quick status filter pills, multi-column sorting, and high-framerate rendering.
    """
    def __init__(self, parent_gui: Any):
        super().__init__()
        self.parent_gui = parent_gui
        self.filter_buttons: dict[str, QPushButton] = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(8)
        
        # Header Controls: Search + Filter Pills
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.txt_search = QLineEdit()
        self.txt_search.setFixedHeight(30)
        self.txt_search.setPlaceholderText("🔎 Search live usernames...")
        self.txt_search.textChanged.connect(self.on_search_changed)
        top_bar.addWidget(self.txt_search, 3)

        # Quick Status Filter Pills
        pill_statuses = ["ALL", "AVAILABLE", "AUCTION", "SOLD", "ERROR"]
        for st in pill_statuses:
            btn = QPushButton(st)
            btn.setFixedHeight(28)
            btn.setCheckable(True)
            if st == "ALL":
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, s=st: self.on_filter_pill_clicked(s))
            self.filter_buttons[st] = btn
            top_bar.addWidget(btn, 1)

        layout.addLayout(top_bar)
        
        # Hero Table
        self.table = QTableView()
        self.table.setModel(self.parent_gui.proxy_model)
        
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 230)
        self.table.setColumnWidth(2, 140)
        self.table.setColumnWidth(3, 220)
        self.table.setColumnWidth(4, 95)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.clicked.connect(self.handle_table_click)
        
        layout.addWidget(self.table)
        self.apply_table_style()

    def on_search_changed(self, text: str):
        self.parent_gui.proxy_model.set_search_query(text)

    def on_filter_pill_clicked(self, status: str):
        for s, btn in self.filter_buttons.items():
            btn.setChecked(s == status)
        self.parent_gui.filter_stream(status)

    def apply_table_style(self):
        is_dark = self.parent_gui.is_dark
        bg = DARK_TABLE if is_dark else LIGHT_TABLE
        fg = DARK_TEXT if is_dark else LIGHT_TEXT
        border = DARK_BORDER if is_dark else LIGHT_BORDER
        sel = DARK_ROW_SEL if is_dark else LIGHT_ROW_SEL
        primary = DARK_PRIMARY if is_dark else LIGHT_PRIMARY
        card_bg = DARK_CARD if is_dark else LIGHT_CARD
        
        self.txt_search.setStyleSheet(f"""
            QLineEdit {{
                background-color: {card_bg};
                color: {fg};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 4px 8px;
                font-family: 'Segoe UI';
                font-size: 11px;
            }}
            QLineEdit:focus {{
                border-color: {primary};
            }}
        """)

        for s, btn in self.filter_buttons.items():
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {card_bg};
                    color: {fg};
                    border: 1px solid {border};
                    border-radius: 4px;
                    font-family: 'Segoe UI';
                    font-size: 9px;
                    font-weight: bold;
                }}
                QPushButton:checked {{
                    background-color: {primary};
                    color: {'#080B10' if is_dark else '#FFFFFF'};
                    border-color: {primary};
                }}
            """)

        self.table.setStyleSheet(f"""
            QTableView {{
                background-color: {bg};
                gridline-color: {border};
                border: 1px solid {border};
                border-radius: 4px;
                font-family: 'JetBrains Mono', 'Consolas', monospace;
                font-size: 12px;
                color: {fg};
            }}
            QTableView::item:selected {{
                background-color: {sel};
                color: {fg};
                border-left: 3px solid {primary};
            }}
            QHeaderView::section {{
                background-color: {DARK_BG if is_dark else LIGHT_BG};
                color: {DARK_MUTED if is_dark else LIGHT_MUTED};
                font-family: 'Segoe UI', sans-serif;
                font-size: 10px;
                font-weight: bold;
                padding: 5px;
                border: none;
                border-bottom: 2px solid {border};
            }}
        """)

    def handle_table_click(self, proxy_index: Any):
        if not proxy_index.isValid():
            return
        source_index = self.parent_gui.proxy_model.mapToSource(proxy_index)
        row = source_index.row()
    
        with self.parent_gui.table_model.lock:
            if row >= len(self.parent_gui.table_model.rows):
                return
            record = dict(self.parent_gui.table_model.rows[row])
    
        uname = record["username"]
        status = record["status"]
        detail = record.get("detail", "NO DATA")
        latency = record.get("latency", "0ms")
        time_str = record.get("time", "--:--:--")
        corr_id = record.get("correlation_id", "N/A")
        pat_id = record.get("pat_id", "N/A")
    
        self.parent_gui.right_panel.inspect_target(
            uname=uname,
            status=status,
            detail=detail,
            latency=latency,
            time_str=time_str,
            corr_id=corr_id,
            pattern_id=pat_id
        )

    def show_context_menu(self, pos):
        proxy_index = self.table.currentIndex()
        if not proxy_index.isValid():
            return
        
        source_index = self.parent_gui.proxy_model.mapToSource(proxy_index)
        row = source_index.row()
        
        with self.parent_gui.table_model.lock:
            if row >= len(self.parent_gui.table_model.rows):
                return
            record = dict(self.parent_gui.table_model.rows[row])
            
        uname = record["username"]
        corr_id = record.get("correlation_id", "N/A")
        
        menu = QMenu(self)
        act_copy_user = QAction(f"📋 Copy Username ({uname})", self)
        act_copy_row  = QAction("📄 Copy Row Data", self)
        act_copy_corr = QAction(f"🔑 Copy Correlation ID ({corr_id})", self)
        act_open_tg   = QAction("✈ Open in Telegram", self)
        act_inspect   = QAction("🔍 Inspect in Falcon Vision", self)
        
        act_copy_user.triggered.connect(lambda: QApplication.clipboard().setText(uname))
        act_copy_row.triggered.connect(lambda: QApplication.clipboard().setText(f"{uname}\t{record['status']}\t{record['detail']}"))
        act_copy_corr.triggered.connect(lambda: QApplication.clipboard().setText(corr_id))
        act_open_tg.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(f"https://t.me/{uname.replace('@', '')}")))
        act_inspect.triggered.connect(lambda: self.handle_table_click(proxy_index))
        
        menu.addAction(act_copy_user)
        menu.addAction(act_copy_row)
        menu.addAction(act_copy_corr)
        menu.addSeparator()
        menu.addAction(act_open_tg)
        menu.addAction(act_inspect)
        menu.exec(self.table.viewport().mapToGlobal(pos))