from __future__ import annotations
import threading
from collections import OrderedDict
from typing import List, Dict, Any, Optional

try:
    from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex
    from PyQt6.QtGui import QFont, QColor
except ImportError:
    class QModelIndex:
        def isValid(self): return False
        def row(self): return 0
        def column(self): return 0

    class QAbstractTableModel:
        def __init__(self, parent=None): pass
        def dataChanged(self, *args): pass
        def beginInsertRows(self, *args): pass
        def endInsertRows(self): pass
        def beginRemoveRows(self, *args): pass
        def endRemoveRows(self): pass
        def index(self, r, c, p=None): return QModelIndex()

    class Qt:
        class Orientation:
            Horizontal = 1
        class ItemDataRole:
            DisplayRole = 0
            ForegroundRole = 1
            FontRole = 2

    class QFont:
        class Weight:
            Bold = 700
            DemiBold = 600
        def __init__(self, *args, **kwargs): pass
        def setWeight(self, *args): pass

    class QColor:
        def __init__(self, *args, **kwargs): pass

from ui.themes.colors import (
    DARK_TEXT, LIGHT_TEXT,
    DARK_SECONDARY, LIGHT_SECONDARY,
    DARK_STAT_UNAVAILABLE, LIGHT_STAT_UNAVAILABLE,
    DARK_STAT_AVAILABLE, LIGHT_STAT_AVAILABLE,
    DARK_STAT_AUCTION, LIGHT_STAT_AUCTION,
    DARK_STAT_SOLD, LIGHT_STAT_SOLD,
    DARK_STAT_TAKEN, LIGHT_STAT_TAKEN,
    DARK_STAT_UNKNOWN, LIGHT_STAT_UNKNOWN
)

class LiveScannerTableModel(QAbstractTableModel):
    """
    High-Throughput Live Stream Table Model:
    Engineered with In-Batch Deduplication (Latest Wins), atomic batch evictions,
    and single-pass index reconstruction to maintain 60 FPS under massive ingestion.
    """
    def __init__(self, max_rows: int = 1000, is_dark: bool = True, parent=None):
        super().__init__(parent)
        self.max_rows = max_rows
        self.is_dark = is_dark
        self.rows: List[Dict[str, Any]] = []
        self.headers = ["No.", "USERNAME", "STATUS", "DETAIL", "LATENCY", "LAST CHECK"]
        self.lock = threading.RLock()
        self.username_row_map: Dict[str, int] = {}

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.headers)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if row >= len(self.rows):
            return None
        
        record = self.rows[row]
        status = record["status"]

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0: return str(record.get("result_sequence", row + 1))
            elif col == 1: return record["username"]
            elif col == 2:
                icon = "●" if status in ["AVAILABLE", "AUCTION", "SOLD", "TAKEN"] else "⚠" if status == "UNKNOWN" else "✕"
                return f"{icon} {status}"
            elif col == 3: return record.get("detail", "NO DATA")
            elif col == 4: return record.get("latency", "0ms")
            elif col == 5: return record.get("time", "--:--:--")

        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 1:
                return QColor(DARK_TEXT if self.is_dark else LIGHT_TEXT)
            elif col == 2:
                col_map = {
                    "UNAVAILABLE": DARK_STAT_UNAVAILABLE if self.is_dark else LIGHT_STAT_UNAVAILABLE,
                    "AVAILABLE": DARK_STAT_AVAILABLE if self.is_dark else LIGHT_STAT_AVAILABLE,
                    "AUCTION": DARK_STAT_AUCTION if self.is_dark else LIGHT_STAT_AUCTION,
                    "SOLD": DARK_STAT_SOLD if self.is_dark else LIGHT_STAT_SOLD,
                    "TAKEN": DARK_STAT_TAKEN if self.is_dark else LIGHT_STAT_TAKEN,
                    "FREE": DARK_STAT_AVAILABLE if self.is_dark else LIGHT_STAT_AVAILABLE
                }
                return QColor(col_map.get(status, DARK_STAT_UNKNOWN if self.is_dark else LIGHT_STAT_UNKNOWN))
            elif col == 3:
                return QColor(DARK_SECONDARY if self.is_dark else LIGHT_SECONDARY)

        elif role == Qt.ItemDataRole.FontRole:
            if col == 1:
                f = QFont("JetBrains Mono", 12)
                f.setWeight(QFont.Weight.DemiBold)
                return f
            elif col == 2:
                f = QFont("Segoe UI", 11)
                f.setWeight(QFont.Weight.Bold)
                return f
            else:
                return QFont("JetBrains Mono", 12)

        return None

    def add_records_batch(self, batch: List[Dict[str, Any]]):
        """
        P0 High-Performance In-Batch Deduplication & Atomic Ingestion:
        1. Folds incoming batch using OrderedDict (Latest record wins per username).
        2. In-place updates for existing rows.
        3. Single-pass atomic batch eviction of excess rows.
        4. Single-pass atomic insertion of new rows with zero duplicate rows.
        """
        if not batch:
            return
            
        with self.lock:
            # P0: Pre-batch In-Flight Folding (Guarantees zero duplicate usernames in same batch)
            unique_batch: Dict[str, Dict[str, Any]] = OrderedDict()
            for record in batch:
                uname = record.get("username", "")
                if uname:
                    unique_batch[uname] = record

            updates = []
            new_inserts = []

            for username, record in unique_batch.items():
                if username in self.username_row_map:
                    row_idx = self.username_row_map[username]
                    self.rows[row_idx] = record
                    updates.append(row_idx)
                else:
                    new_inserts.append(record)

            # 1. Notify UI of in-place row updates
            if updates:
                min_row = min(updates)
                max_row = max(updates)
                self.dataChanged.emit(self.index(min_row, 0), self.index(max_row, 5))

            # 2. Batch Eviction & Insertion for new rows
            if new_inserts:
                current_len = len(self.rows)
                to_insert_len = len(new_inserts)
                total_projected = current_len + to_insert_len
                excess = max(0, total_projected - self.max_rows)

                # Atomic Batch Eviction
                if excess > 0:
                    evict_count = min(excess, current_len)
                    self.beginRemoveRows(QModelIndex(), 0, evict_count - 1)
                    del self.rows[:evict_count]
                    self.endRemoveRows()

                # Atomic Batch Insertion
                start_insert_idx = len(self.rows)
                end_insert_idx = start_insert_idx + to_insert_len - 1
                self.beginInsertRows(QModelIndex(), start_insert_idx, end_insert_idx)
                self.rows.extend(new_inserts)
                self.endInsertRows()

                # Single-pass dictionary reconstruction for the whole batch
                self.username_row_map = {r["username"]: i for i, r in enumerate(self.rows)}