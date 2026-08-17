from __future__ import annotations
import time
from typing import Tuple, Any

from core.config import (
    MAX_GLOBAL_QUEUE,
    MAX_WRITER_QUEUE,
    MAX_RETRY_QUEUE,
    MAX_PATTERN_QUEUE,
    MAX_LRU_CACHE_SIZE
)

class SystemInvariantChecker:
    """Verifies that all internal queues, heaps, and caches strictly obey hard bounds."""
    
    @staticmethod
    def audit_invariants(scanner: Any, writer: Any, db: Any) -> Tuple[bool, str]:
        scanner_len = scanner.get_queue_len()
        writer_len = writer.get_queue_len()
        
        with scanner.retry_lock:
            retry_len = len(scanner.retry_queue)
            
        with scanner.paused_lock:
            max_paused = max([len(q) for q in scanner.paused_pattern_queues.values()]) if scanner.paused_pattern_queues else 0
            
        lru_len = len(db.lru_cache)
        
        if scanner_len > MAX_GLOBAL_QUEUE:
            return False, f"Scanner queue exceeded bound: {scanner_len} > {MAX_GLOBAL_QUEUE}"
        if writer_len > MAX_WRITER_QUEUE:
            return False, f"Writer queue exceeded bound: {writer_len} > {MAX_WRITER_QUEUE}"
        if retry_len > MAX_RETRY_QUEUE:
            return False, f"Retry heap exceeded bound: {retry_len} > {MAX_RETRY_QUEUE}"
        if max_paused > MAX_PATTERN_QUEUE:
            return False, f"Paused pattern queue exceeded bound: {max_paused} > {MAX_PATTERN_QUEUE}"
        if lru_len > MAX_LRU_CACHE_SIZE:
            return False, f"LRU Cache exceeded bound: {lru_len} > {MAX_LRU_CACHE_SIZE}"
            
        return True, "ALL_INVARIANTS_SATISFIED"

    @staticmethod
    def audit_worker_starvation(scanner: Any) -> Tuple[bool, str]:
        now = time.monotonic()
        idle_time = now - scanner.worker_last_activity_monotonic
        if scanner.pause_event.is_set() and scanner.get_queue_len() > 0 and idle_time > 60.0:
            return True, f"Worker starvation detected: Queue has {scanner.get_queue_len()} items but worker idle for {idle_time:.1f}s"
        return False, "WORKER_HEALTHY"