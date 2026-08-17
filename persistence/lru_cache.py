from __future__ import annotations
import threading
from collections import OrderedDict
from typing import Optional

from core.config import MAX_LRU_CACHE_SIZE
from core.metrics import METRICS
from core.logger import logger

class BoundedLRUCache:
    def __init__(self, capacity: int = MAX_LRU_CACHE_SIZE):
        self.capacity = capacity
        self.cache: OrderedDict[str, bool] = OrderedDict()
        self.lock = threading.RLock()

    def get(self, key: str) -> Optional[bool]:
        with self.lock:
            if key not in self.cache:
                METRICS.record_cache_lookup(hit=False)
                return None
            self.cache.move_to_end(key)
            METRICS.record_cache_lookup(hit=True)
            return self.cache[key]

    def put(self, key: str, value: bool = True):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = value
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)

    def evict(self, key: str):
        with self.lock:
            self.cache.pop(key, None)

    def clear(self):
        with self.lock:
            self.cache.clear()

    def invalidate_cache(self):
        with self.lock:
            self.cache.clear()
            logger.info("In-memory LRU Cache invalidated completely.")

    def __len__(self) -> int:
        with self.lock:
            return len(self.cache)