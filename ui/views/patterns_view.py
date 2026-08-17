from __future__ import annotations
from typing import Dict, Any

try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QLineEdit, QPushButton, QScrollArea, QFileDialog
    )
    from PyQt6.QtGui import QFont
except ImportError:
    class QWidget:
        def __init__(self, parent=None): pass
        def setFixedWidth(self, w): pass
        def setStyleSheet(self, s): pass
        def hide(self): pass
        def show(self): pass
    class QVBoxLayout:
        def __init__(self, p=None): pass
        def setContentsMargins(self, *args): pass
        def setSpacing(self, s): pass
        def addWidget(self, w): pass
        def addLayout(self, l): pass
        def addStretch(self): pass
        def count(self): return 0
        def insertWidget(self, idx, w): pass
    class QHBoxLayout(QVBoxLayout): pass
    class QLabel:
        def __init__(self, t=""): pass
        def setFont(self, f): pass
    class QLineEdit:
        def __init__(self): pass
        def setFixedHeight(self, h): pass
        def setPlaceholderText(self, t): pass
        def text(self): return ""
        def clear(self): pass
        class returnPressed:
            @staticmethod
            def connect(s): pass
    class QPushButton:
        def __init__(self, t=""): pass
        def setFixedSize(self, w, h): pass
        def setFixedHeight(self, h): pass
        def setStyleSheet(self, s): pass
        class clicked:
            @staticmethod
            def connect(s): pass
    class QScrollArea:
        def __init__(self): pass
        def setWidgetResizable(self, r): pass
        def setWidget(self, w): pass
    class QFileDialog:
        @staticmethod
        def getOpenFileName(*args): return "", ""
    class QFont:
        class Weight:
            Bold = 700
        def __init__(self, *args, **kwargs): pass

from core.config import MAX_ACTIVE_PRODUCERS
from parser.pattern_generator import LazyPatternGenerator
from producers.pattern_producer import PatternProducerWorker
from producers.file_producer import FileImporterWorker
from ui.widgets.task_card import PatternTaskCard
from ui.themes.colors import (
    DARK_PRIMARY,
    DARK_PANEL,
    DARK_BORDER
)

class PatternsView(QWidget):
    """View managing pattern tasks creation, queue parking, and streaming file target imports."""
    def __init__(self, parent_gui: Any):
        super().__init__()
        self.parent_gui = parent_gui
        self.setFixedWidth(300)
        self.pattern_cards: Dict[str, PatternTaskCard] = {}
        self.active_importers = []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(6)
        
        lbl_head = QLabel("PATTERNS & TARGETS")
        lbl_head.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        layout.addWidget(lbl_head)
        
        inp_lay = QHBoxLayout()
        self.txt_pattern = QLineEdit()
        self.txt_pattern.setFixedHeight(32)
        self.txt_pattern.setPlaceholderText("pattern (e.g. L_L_N)")
        self.txt_pattern.returnPressed.connect(self.add_pattern_task)
        
        btn_add = QPushButton("ADD")
        btn_add.setFixedSize(70, 32)
        btn_add.clicked.connect(self.add_pattern_task)
        btn_add.setStyleSheet(f"background-color: {DARK_PRIMARY}; color: black; font-weight: bold; border-radius: 3px;")
        inp_lay.addWidget(self.txt_pattern)
        inp_lay.addWidget(btn_add)
        layout.addLayout(inp_lay)
        
        btn_import = QPushButton("📂 IMPORT (TXT / CSV / JSON)")
        btn_import.setFixedHeight(34)
        btn_import.clicked.connect(self.import_files)
        btn_import.setStyleSheet(f"background-color: {DARK_PANEL}; color: white; border: 1px dashed {DARK_BORDER}; border-radius: 3px; font-weight: bold;")
        layout.addWidget(btn_import)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        self.pattern_container = QWidget()
        self.pattern_layout = QVBoxLayout(self.pattern_container)
        self.pattern_layout.addStretch()
        scroll.setWidget(self.pattern_container)
        layout.addWidget(scroll)

    def add_pattern_task(self):
        pat = self.txt_pattern.text().strip()
        if not pat:
            return

        if pat in self.pattern_cards:
            self.parent_gui.queue_ui_log(f"⚠️ Pattern '{pat}' is already actively running or registered.")
            return

        controller = self.parent_gui.controller
        if any(p.pattern == pat for p in controller.active_producers):
            self.parent_gui.queue_ui_log(f"⚠️ A producer is already generating tasks for pattern '{pat}'.")
            return
        
        if len(controller.active_producers) >= MAX_ACTIVE_PRODUCERS:
            self.parent_gui.queue_ui_log(f"⚠️ Producer Budget Limit: Max {MAX_ACTIVE_PRODUCERS} concurrent producers allowed.")
            return

        with controller.worker.paused_lock:
            controller.worker.cancelled_patterns.discard(pat)

        count = LazyPatternGenerator.calculate_possibilities(pat)
        card = PatternTaskCard(pat, count, parent_gui=self.parent_gui)
        self.pattern_cards[pat] = card
        self.pattern_layout.insertWidget(self.pattern_layout.count() - 1, card)
        
        producer = PatternProducerWorker(pat, pat, controller.worker, controller.db)
        producer.sig_log.connect(self.parent_gui.queue_ui_log)
        producer.finished.connect(lambda: self.cleanup_producer(producer))
        controller.active_producers.append(producer)
        producer.start()
            
        self.txt_pattern.clear()

    def cleanup_producer(self, producer: PatternProducerWorker):
        controller = self.parent_gui.controller
        if producer in controller.active_producers:
            controller.active_producers.remove(producer)
            producer.deleteLater()

    def import_files(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Import Target List", "", "Supported Files (*.txt *.csv *.json)")
        if file_path:
            controller = self.parent_gui.controller
            importer = FileImporterWorker(file_path, controller.worker, controller.db)
            importer.sig_log.connect(self.parent_gui.queue_ui_log)
            importer.finished.connect(lambda: self.active_importers.remove(importer) if importer in self.active_importers else None)
            self.active_importers.append(importer)
            importer.start()

    def update_theme(self):
        for card in self.pattern_cards.values():
            card.update_card_style()