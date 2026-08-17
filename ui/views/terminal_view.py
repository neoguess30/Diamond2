from __future__ import annotations
import time
from typing import Any
from pathlib import Path
from datetime import datetime, timezone

try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QFileDialog, QMessageBox
    )
    from PyQt6.QtGui import QFont
except ImportError:
    class QWidget:
        def __init__(self, parent=None): pass
    class QVBoxLayout:
        def __init__(self, p=None): pass
        def setContentsMargins(self, *args): pass
        def setSpacing(self, s): pass
        def addWidget(self, w): pass
        def addLayout(self, l): pass
        def addStretch(self): pass
    class QHBoxLayout(QVBoxLayout): pass
    class QLabel:
        def __init__(self, t=""): pass
        def setFont(self, f): pass
        def setStyleSheet(self, s): pass
    class QPushButton:
        def __init__(self, t=""): pass
        def setFixedSize(self, w, h): pass
        def setCheckable(self, c): pass
        def setChecked(self, c): pass
        def isChecked(self): return True
        def setText(self, t): pass
        def setStyleSheet(self, s): pass
        class clicked:
            @staticmethod
            def connect(s): pass
    class QTextEdit:
        def __init__(self): pass
        def setFixedHeight(self, h): pass
        def setReadOnly(self, r): pass
        def toPlainText(self): return ""
        def document(self):
            class _D:
                def setMaximumBlockCount(self, c): pass
            return _D()
        def append(self, t): pass
        def clear(self): pass
        def hide(self): pass
        def show(self): pass
        def verticalScrollBar(self):
            class _SB:
                def setValue(self, v): pass
                def maximum(self): return 0
            return _SB()
    class QFont:
        class Weight:
            Bold = 700
        def __init__(self, *args, **kwargs): pass
    class QFileDialog:
        @staticmethod
        def getSaveFileName(*args): return "", ""
    class QMessageBox:
        @staticmethod
        def information(*args): pass

from ui.themes.colors import DARK_MUTED, DARK_PRIMARY, DARK_BORDER, DARK_CARD, DARK_TEXT

class TerminalView(QWidget):
    """
    OPERATOR CONSOLE
    Features category filtering [ALL] [SYSTEM] [NETWORK] [DB] [ERROR],
    auto-scroll latching, buffer clear, instant export, and 24-hour heap defragmentation.
    """
    def __init__(self, parent_gui: Any):
        super().__init__()
        self.parent_gui = parent_gui
        self.logs_collapsed = False
        self.auto_scroll_logs = True
        self.active_log_filter = "ALL"
        
        # P0 24-Hour Memory Health Purge
        self.last_purge_monotonic = time.monotonic()
        self.purge_interval_sec = 86400.0  # 24 Hours

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        head_lay = QHBoxLayout()
        lbl_head = QLabel("OPERATOR CONSOLE // LIVE TELEMETRY")
        lbl_head.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_head.setStyleSheet(f"color: {DARK_MUTED}; letter-spacing: 1px;")
        head_lay.addWidget(lbl_head)
        
        # Category Filter Buttons
        self.btn_log_all = QPushButton("ALL")
        self.btn_log_all.setFixedSize(45, 22)
        self.btn_log_all.clicked.connect(lambda: self.set_log_filter("ALL"))
        
        self.btn_log_sys = QPushButton("SYSTEM")
        self.btn_log_sys.setFixedSize(65, 22)
        self.btn_log_sys.clicked.connect(lambda: self.set_log_filter("SYSTEM"))
        
        self.btn_log_net = QPushButton("NETWORK")
        self.btn_log_net.setFixedSize(68, 22)
        self.btn_log_net.clicked.connect(lambda: self.set_log_filter("NETWORK"))
        
        self.btn_log_db = QPushButton("DB")
        self.btn_log_db.setFixedSize(40, 22)
        self.btn_log_db.clicked.connect(lambda: self.set_log_filter("DB"))

        self.btn_log_err = QPushButton("ERROR")
        self.btn_log_err.setFixedSize(55, 22)
        self.btn_log_err.clicked.connect(lambda: self.set_log_filter("ERROR"))
        
        self.btn_autoscroll = QPushButton("AUTO-SCROLL ●")
        self.btn_autoscroll.setCheckable(True)
        self.btn_autoscroll.setChecked(True)
        self.btn_autoscroll.setFixedSize(98, 22)
        self.btn_autoscroll.clicked.connect(self.toggle_autoscroll)
        
        btn_export_log = QPushButton("EXPORT")
        btn_export_log.setFixedSize(58, 22)
        btn_export_log.clicked.connect(self.export_console_log)

        btn_clear_log = QPushButton("CLEAR")
        btn_clear_log.setFixedSize(50, 22)
        btn_clear_log.clicked.connect(self.clear_terminal)
        
        self.btn_collapse = QPushButton("[−]")
        self.btn_collapse.setFixedSize(30, 22)
        self.btn_collapse.clicked.connect(self.toggle_terminal)
        self.btn_collapse.setStyleSheet("border: none; color: white; font-weight: bold;")
        
        head_lay.addWidget(self.btn_log_all)
        head_lay.addWidget(self.btn_log_sys)
        head_lay.addWidget(self.btn_log_net)
        head_lay.addWidget(self.btn_log_db)
        head_lay.addWidget(self.btn_log_err)
        head_lay.addWidget(self.btn_autoscroll)
        head_lay.addWidget(btn_export_log)
        head_lay.addWidget(btn_clear_log)
        head_lay.addStretch()
        head_lay.addWidget(self.btn_collapse)
        layout.addLayout(head_lay)
        
        self.txt_console = QTextEdit()
        self.txt_console.setFixedHeight(120)
        self.txt_console.setReadOnly(True)
        self.txt_console.document().setMaximumBlockCount(500)
        layout.addWidget(self.txt_console)

    def set_log_filter(self, flt: str):
        self.active_log_filter = flt
        self.parent_gui.queue_ui_log(f"[*] Console filter set to: [{flt}]")

    def toggle_autoscroll(self):
        self.auto_scroll_logs = self.btn_autoscroll.isChecked()

    def clear_terminal(self):
        self.txt_console.clear()

    def export_console_log(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Console Logs", f"console_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.log", "Log Files (*.log *.txt)"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(self.txt_console.toPlainText())
                QMessageBox.information(self, "Export Successful", f"Console logs exported safely to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export log file: {e}")

    def toggle_terminal(self):
        self.logs_collapsed = not self.logs_collapsed
        if self.logs_collapsed:
            self.txt_console.hide()
            self.btn_collapse.setText("[+]")
            self.parent_gui.v_splitter.setSizes([850, 32])
        else:
            self.txt_console.show()
            self.btn_collapse.setText("[−]")
            self.parent_gui.v_splitter.setSizes([720, 130])

    def append_log_batch(self, lines: list[str]):
        if not lines:
            return

        now = time.monotonic()
        # P0 24-Hour Memory Purge: Resets Qt document buffer to eliminate Heap Fragmentation
        if now - self.last_purge_monotonic >= self.purge_interval_sec:
            self.txt_console.clear()
            self.txt_console.append(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] --- 24-HOUR OPERATOR CONSOLE AUTO-MAINTENANCE PURGE ---")
            self.last_purge_monotonic = now

        self.txt_console.append("\n".join(lines))
        if self.auto_scroll_logs:
            self.txt_console.verticalScrollBar().setValue(self.txt_console.verticalScrollBar().maximum())