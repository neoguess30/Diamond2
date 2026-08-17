from __future__ import annotations
import time
import heapq
import threading
from typing import List, Tuple, Optional
from core.models.job import Job
from core.config import MAX_RETRY_QUEUE

class RetryHeapManager:
    """Thread-safe Priority Queue for delayed retry scheduling."""
    def __init__(self, max_capacity: int = MAX_RETRY_QUEUE):
        self.heap: List[Tuple[float, Job]] = []
        self.lock = threading.RLock()
        self.max_capacity = max_capacity

    def push(self, retry_at_monotonic: float, job: Job) -> bool:
        """Pushes a job into the retry heap if capacity permits."""
        with self.lock:
            if len(self.heap) >= self.max_capacity:
                return False
            heapq.heappush(self.heap, (retry_at_monotonic, job))
            return True

    def pop_ready(self, current_monotonic: Optional[float] = None) -> Optional[Job]:
        """Pops the oldest ready job whose schedule timestamp has arrived."""
        now = current_monotonic if current_monotonic is not None else time.monotonic()
        with self.lock:
            if self.heap and self.heap[0][0] <= now:
                _, job = heapq.heappop(self.heap)
                return job
            return None

    def get_queue_len(self) -> int:
        with self.lock:
            return len(self.heap)

    def get_snapshot_list(self) -> List[Tuple[float, Job]]:
        with self.lock:
            return list(self.heap)

    def restore_from_list(self, items: List[Tuple[float, Job]]):
        with self.lock:
            self.heap = list(items)
            heapq.heapify(self.heap)

    def clear(self):
        with self.lock:
            self.heap.clear()