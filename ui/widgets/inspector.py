from __future__ import annotations
from typing import Any

try:
    from PyQt6.QtWidgets import (
        QFrame, QVBoxLayout, QHBoxLayout, QLabel,
        QProgressBar, QTextEdit, QPushButton
    )
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QFont, QDesktopServices
except ImportError:
    class QFrame:
        def __init__(self, *args): pass
        def setFixedWidth(self, w): pass
        def setStyleSheet(self, s): pass
    class QVBoxLayout:
        def __init__(self, p=None): pass
        def setContentsMargins(self, *args): pass
        def setSpacing(self, s): pass
        def addWidget(self, w): pass
        def addLayout(self, l): pass
    class QHBoxLayout(QVBoxLayout): pass
    class QLabel:
        def __init__(self, t=""): pass
        def setFont(self, f): pass
        def setText(self, t): pass
        def text(self): return ""
        def setStyleSheet(self, s): pass
    class QProgressBar:
        def setValue(self, v): pass
        def setFixedHeight(self, h): pass
        def setStyleSheet(self, s): pass
    class QTextEdit:
        def setReadOnly(self, r): pass
        def setText(self, t): pass
        def setStyleSheet(self, s): pass
    class QPushButton:
        def __init__(self, t=""): pass
        def setFixedHeight(self, h): pass
        def setFont(self, f): pass
        def setStyleSheet(self, s): pass
        class clicked:
            @staticmethod
            def connect(slot): pass
    class QFont:
        class Weight:
            Bold = 700
        def __init__(self, *args, **kwargs): pass
    class QDesktopServices:
        @staticmethod
        def openUrl(u): pass
    class QUrl:
        def __init__(self, u): pass

from ui.themes.colors import (
    DARK_PANEL, LIGHT_PANEL,
    DARK_BORDER, LIGHT_BORDER,
    DARK_TEXT, LIGHT_TEXT,
    DARK_PRIMARY, LIGHT_PRIMARY,
    DARK_PURPLE, LIGHT_PURPLE,
    DARK_MUTED, LIGHT_MUTED,
    DARK_STAT_AVAILABLE, LIGHT_STAT_AVAILABLE,
    DARK_STAT_UNAVAILABLE, LIGHT_STAT_UNAVAILABLE,
    DARK_STAT_AUCTION, LIGHT_STAT_AUCTION,
    DARK_STAT_SOLD, LIGHT_STAT_SOLD,
    DARK_STAT_TAKEN, LIGHT_STAT_TAKEN
)

class TargetInspectorPanel(QFrame):
    """
    FALCON VISION // TARGET INTELLIGENCE
    Displays deep target profile, forensic metadata, confidence rating,
    and single-click Telegram routing.
    """
    def __init__(self, parent_gui: Any = None):
        super().__init__()
        self.parent_gui = parent_gui
        self.setFixedWidth(380)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        
        # Header Badge with Purple Intelligence Accent
        self.lbl_head = QLabel("FALCON VISION // INTELLIGENCE")
        self.lbl_head.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        layout.addWidget(self.lbl_head)
        
        self.lbl_uname = QLabel("@select_target")
        self.lbl_uname.setFont(QFont("JetBrains Mono", 17, QFont.Weight.Bold))
        
        self.lbl_status_badge = QLabel("STATUS:  ● NONE")
        self.lbl_status_badge.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        
        layout.addWidget(self.lbl_uname)
        layout.addWidget(self.lbl_status_badge)
        
        self.lbl_meta_details = QLabel("PATTERN    : --\nRESPONSE   : --ms\nFIRST SEEN : --:--:--\nATTEMPTS   : 0\nCORRELATION: --")
        self.lbl_meta_details.setFont(QFont("JetBrains Mono", 9))
        layout.addWidget(self.lbl_meta_details)
        
        # Confidence Gauge
        lbl_conf = QLabel("CONFIDENCE RATING")
        lbl_conf.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.conf_bar = QProgressBar()
        self.conf_bar.setValue(100)
        self.conf_bar.setFixedHeight(5)
        
        layout.addWidget(lbl_conf)
        layout.addWidget(self.conf_bar)
        
        # Evidence Checklist
        lbl_ev = QLabel("EVIDENCE CHECKLIST")
        lbl_ev.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        layout.addWidget(lbl_ev)
        
        self.ev_box = QLabel("✓ Target Context\n✓ Status Element\n✓ Exact Phrase\n✓ Structural Match")
        self.ev_box.setFont(QFont("Segoe UI", 9))
        layout.addWidget(self.ev_box)
        
        # Status History
        lbl_time = QLabel("STATUS HISTORY")
        lbl_time.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        layout.addWidget(lbl_time)
        
        self.txt_history = QTextEdit()
        self.txt_history.setReadOnly(True)
        self.txt_history.setText("● --:--:--  INITIAL QUEUE")
        layout.addWidget(self.txt_history)
        
        # Action Buttons
        btn_grid = QHBoxLayout()
        self.btn_inspect = QPushButton("INSPECT")
        self.btn_inspect.setFixedHeight(30)
        self.btn_inspect.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        
        self.btn_history = QPushButton("HISTORY")
        self.btn_history.setFixedHeight(30)
        self.btn_history.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        btn_grid.addWidget(self.btn_inspect)
        btn_grid.addWidget(self.btn_history)
        layout.addLayout(btn_grid)

        self.btn_telegram = QPushButton("✈ OPEN IN TELEGRAM")
        self.btn_telegram.setFixedHeight(34)
        self.btn_telegram.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.btn_telegram.clicked.connect(self.open_telegram)
        layout.addWidget(self.btn_telegram)

        self.update_style()

    def update_style(self):
        is_dark = self.parent_gui.is_dark if self.parent_gui else True
        bg = DARK_PANEL if is_dark else LIGHT_PANEL
        border = DARK_BORDER if is_dark else LIGHT_BORDER
        txt_col = DARK_TEXT if is_dark else LIGHT_TEXT
        purple_col = DARK_PURPLE if is_dark else LIGHT_PURPLE
        primary_col = DARK_PRIMARY if is_dark else LIGHT_PRIMARY
        box_bg = "#080B10" if is_dark else "#F3F6F9"
        
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border: 1px solid {border};
                border-top: 2px solid {purple_col};
                border-radius: 4px;
            }}
            QLabel {{
                border: none;
                color: {txt_col};
            }}
            QPushButton {{
                background-color: {'#111821' if is_dark else '#FFFFFF'};
                color: {txt_col};
                border: 1px solid {border};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                border-color: {purple_col};
            }}
        """)
        if hasattr(self, 'lbl_head'):
            self.lbl_head.setStyleSheet(f"color: {purple_col}; font-weight: bold; letter-spacing: 1px;")
            self.lbl_meta_details.setStyleSheet(f"color: {DARK_MUTED if is_dark else LIGHT_MUTED}; background-color: {box_bg}; padding: 8px; border-radius: 3px;")
            self.ev_box.setStyleSheet(f"color: {DARK_STAT_AVAILABLE if is_dark else LIGHT_STAT_AVAILABLE}; background-color: {box_bg}; padding: 6px; border-radius: 3px;")
            self.txt_history.setStyleSheet(f"background-color: {box_bg}; color: {txt_col}; font-family: 'JetBrains Mono'; font-size: 10px; border: 1px solid {border};")
            self.btn_telegram.setStyleSheet(f"background-color: {primary_col}; color: {'#080B10' if is_dark else '#FFFFFF'}; border-radius: 3px; font-weight: bold;")
            self.conf_bar.setStyleSheet(f"QProgressBar {{ background-color: {box_bg}; border: none; }} QProgressBar::chunk {{ background-color: {DARK_STAT_AVAILABLE if is_dark else LIGHT_STAT_AVAILABLE}; }}")

    def inspect_target(self, uname: str, status: str, detail: str, latency: str, time_str: str, corr_id: str = "N/A", pattern_id: str = "N/A", attempts: int = 1):
        self.lbl_uname.setText(uname)
        is_dark = self.parent_gui.is_dark if self.parent_gui else True
        
        color_map = {
            "UNAVAILABLE": DARK_STAT_UNAVAILABLE if is_dark else LIGHT_STAT_UNAVAILABLE,
            "AVAILABLE": DARK_STAT_AVAILABLE if is_dark else LIGHT_STAT_AVAILABLE,
            "AUCTION": DARK_STAT_AUCTION if is_dark else LIGHT_STAT_AUCTION,
            "SOLD": DARK_STAT_SOLD if is_dark else LIGHT_STAT_SOLD,
            "TAKEN": DARK_STAT_TAKEN if is_dark else LIGHT_STAT_TAKEN
        }
        col = color_map.get(status, DARK_MUTED if is_dark else LIGHT_MUTED)
        self.lbl_uname.setStyleSheet(f"color: {col};")
        self.lbl_status_badge.setText(f"STATUS:  ● {status}")
        self.lbl_status_badge.setStyleSheet(f"color: {col}; background-color: rgba(0, 0, 0, 18%); padding: 6px; border-radius: 3px; font-weight: bold;")
        
        self.lbl_meta_details.setText(f"PATTERN    : {pattern_id}\nRESPONSE   : {latency}\nFIRST SEEN : {time_str}\nATTEMPTS   : {attempts}\nCORRELATION: {corr_id}")
        self.txt_history.setText(f"● {time_str}   {status} ({detail})\n│\n● 10:00:00   INITIAL QUEUE")

    def open_telegram(self):
        raw_uname = self.lbl_uname.text().replace("@", "").strip()
        if raw_uname and raw_uname != "select_target":
            QDesktopServices.openUrl(QUrl(f"https://t.me/{raw_uname}"))