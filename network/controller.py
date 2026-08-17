from __future__ import annotations
import threading
from typing import Optional
from resilience.backoff import calculate_jittered_backoff

class CentralizedNetworkController:
    """
    Adaptive Delay Coordinator with AIMD (Additive Increase / Multiplicative Decrease):
    Expands backoff instantly on 429/errors and ramps up throughput gradually on sustained success.
    """
    def __init__(self, initial_delay: float = 1.2, min_delay: float = 1.0, max_delay: float = 60.0):
        self.lock = threading.RLock()
        self.shared_delay = initial_delay
        self.min_delay = min_delay
        self.max_delay = max_delay

    def report_response(self, status_code: int, latency_ms: float, retry_after_sec: Optional[float] = None):
        with self.lock:
            if status_code == 429:
                if retry_after_sec is not None and retry_after_sec > 0:
                    # Respect exact Retry-After recommendation
                    self.shared_delay = max(self.shared_delay * 1.5, min(retry_after_sec, self.max_delay))
                else:
                    self.shared_delay = min(self.shared_delay * 1.8, 15.0)
            elif status_code == 200:
                # P0 Gradual Resume (Additive Decrease / Slow Start)
                if latency_ms < 500:
                    self.shared_delay = max(self.min_delay, self.shared_delay - 0.05)
            elif status_code == 0 or (500 <= status_code <= 599):
                self.shared_delay = min(self.shared_delay * 1.4, self.max_delay)

    def get_delay_with_jitter(self, attempt: int = 0) -> float:
        with self.lock:
            return calculate_jittered_backoff(
                base_delay=self.shared_delay,
                attempt=attempt,
                factor=1.5,
                max_delay=self.max_delay
            )