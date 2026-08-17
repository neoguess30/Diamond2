from __future__ import annotations
import time
import threading
from typing import Optional

from core.config import GLOBAL_MAX_REQ_PER_SEC

class TokenBucketRateLimiter:
    """
    Independent token-bucket rate limiter capping burst requests globally.
    Supports interruptible non-blocking acquire via shutdown and cancel events.
    """
    def __init__(self, rate_per_sec: float = GLOBAL_MAX_REQ_PER_SEC, burst_capacity: float = 20.0):
        self.rate = rate_per_sec
        self.capacity = burst_capacity
        self.tokens = burst_capacity
        self.last_update = time.monotonic()
        self.lock = threading.RLock()
        self.shutdown_event = threading.Event()

    def acquire(self, timeout: float = 2.0, cancel_event: Optional[threading.Event] = None) -> bool:
        start_t = time.monotonic()
        
        while True:
            # P0: Fast exit if shutdown or cancellation requested
            if self.shutdown_event.is_set() or (cancel_event is not None and cancel_event.is_set()):
                return False

            with self.lock:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_update = now
                
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True

                needed_fraction = 1.0 - self.tokens
                exact_wait_sec = needed_fraction / self.rate if self.rate > 0 else 0.02

            elapsed_total = time.monotonic() - start_t
            remaining_timeout = timeout - elapsed_total
            if remaining_timeout <= 0:
                return False

            sleep_duration = max(0.001, min(exact_wait_sec, remaining_timeout, 0.02))

            # Interruptible wait: Wakes up immediately if cancel_event or shutdown_event is triggered
            if cancel_event is not None:
                cancelled = cancel_event.wait(timeout=sleep_duration)
                if cancelled or cancel_event.is_set():
                    return False
            else:
                cancelled = self.shutdown_event.wait(timeout=sleep_duration)
                if cancelled or self.shutdown_event.is_set():
                    return False

    def shutdown(self):
        """Signals immediate wakeup for all threads blocked in acquire()."""
        self.shutdown_event.set()

    def reset_shutdown(self):
        self.shutdown_event.clear()