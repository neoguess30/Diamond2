from __future__ import annotations
import re

try:
    from PyQt6.QtCore import QSortFilterProxyModel, QModelIndex, Qt
except ImportError:
    class QSortFilterProxyModel:
        def __init__(self, parent=None): pass
        def setSourceModel(self, m): pass
        def invalidateFilter(self): pass
        def setDynamicSortFilter(self, b): pass
        def sort(self, col, order): pass
    class QModelIndex:
        def isValid(self): return False
        def row(self): return 0
    class Qt:
        class SortOrder:
            AscendingOrder = 0
            DescendingOrder = 1

class StatusFilterProxyModel(QSortFilterProxyModel):
    """
    High-Performance Filter & Multi-Column Sorting Proxy:
    Filters live stream by Status, Username Search Query, and sorts by Sequence/Latency/Status.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter_status = "ALL"
        self.search_query = ""
        self.setDynamicSortFilter(True)

    def set_filter_status(self, status: str):
        self.filter_status = status.upper()
        self.invalidateFilter()

    def set_search_query(self, query: str):
        self.search_query = query.strip().lower().replace("@", "")
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if not hasattr(model, 'rows') or source_row >= len(model.rows):
            return True

        record = model.rows[source_row]
        record_status = record.get("status", "")
        record_username = record.get("username", "").lower().replace("@", "")

        # 1. Status Filter
        if self.filter_status != "ALL" and record_status != self.filter_status:
            return False

        # 2. Search Query Filter
        if self.search_query and self.search_query not in record_username:
            return False

        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        model = self.sourceModel()
        if not hasattr(model, 'rows'):
            return False

        left_row, right_row = left.row(), right.row()
        col = left.column()

        if left_row >= len(model.rows) or right_row >= len(model.rows):
            return False

        r1 = model.rows[left_row]
        r2 = model.rows[right_row]

        if col == 0:  # Sequence Number
            return int(r1.get("result_sequence", 0)) < int(r2.get("result_sequence", 0))
        elif col == 1:  # Username
            return r1.get("username", "") < r2.get("username", "")
        elif col == 2:  # Status
            return r1.get("status", "") < r2.get("status", "")
        elif col == 4:  # Latency
            l1 = int(re.sub(r'\D', '', str(r1.get("latency", "0")) or "0"))
            l2 = int(re.sub(r'\D', '', str(r2.get("latency", "0")) or "0"))
            return l1 < l2

        return super().lessThan(left, right)