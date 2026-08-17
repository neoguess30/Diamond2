from __future__ import annotations
import time
import threading
from typing import Optional, Dict, Any

from core.state.enums import RecycleReason
from core.logger import logger

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    curl_requests = None

class SessionLifecycleManager:
    """
    Resilience-Driven Session Health & Lifecycle Engine:
    Maintains a deterministic Session Health Score (0-100), tracking degradation,
    and executing cooperative deferred recycling to guarantee connection stability.
    """
    def __init__(self, browser_profile: str = "chrome131"):
        self.browser_profile = browser_profile
        self.session = None
        self.lock = threading.RLock()
        
        self.total_recycles = 0
        self.request_count = 0
        self.consecutive_errors = 0
        self.bytes_transferred = 0
        self.session_created_monotonic = time.monotonic()
        self.last_success_monotonic = time.monotonic()
        self.last_recycle_reason: RecycleReason = RecycleReason.RECYCLE_MANUAL
        self._pending_recycle_reason: Optional[RecycleReason] = None
        
        # P0 Session Health Score Engine (0.0 to 100.0)
        self.health_score: float = 100.0
        
        self._perform_actual_recycle(reason=RecycleReason.RECYCLE_MANUAL)

    @property
    def is_healthy(self) -> bool:
        return self.health_score >= 80.0

    @property
    def is_degraded(self) -> bool:
        return 50.0 <= self.health_score < 80.0

    def record_success(self, bytes_count: int):
        with self.lock:
            self.consecutive_errors = 0
            self.bytes_transferred += bytes_count
            self.last_success_monotonic = time.monotonic()
            # Reward successful transmission up to 100.0 cap
            self.health_score = min(100.0, self.health_score + 1.0)

    def record_timeout(self):
        with self.lock:
            self.consecutive_errors += 1
            self.health_score = max(0.0, self.health_score - 2.0)
            self._evaluate_health_threshold()

    def record_5xx(self):
        with self.lock:
            self.consecutive_errors += 1
            self.health_score = max(0.0, self.health_score - 2.0)
            self._evaluate_health_threshold()

    def record_429(self):
        with self.lock:
            self.consecutive_errors += 1
            # Rate limit penalty
            self.health_score = max(0.0, self.health_score - 5.0)
            self._evaluate_health_threshold()

    def record_connection_error(self):
        with self.lock:
            self.consecutive_errors += 1
            self.health_score = max(0.0, self.health_score - 2.0)
            self._evaluate_health_threshold()

    def _evaluate_health_threshold(self):
        """Triggers cooperative recycle if health score drops below critical threshold."""
        if self.health_score < 50.0 and self._pending_recycle_reason is None:
            logger.warning(f"⚠️ Session Health Score degraded to {self.health_score:.1f}/100. Scheduling health-driven recycle.")
            self._pending_recycle_reason = RecycleReason.RECYCLE_ERRORS

    def request_recycle(self, reason: RecycleReason = RecycleReason.RECYCLE_ERRORS):
        with self.lock:
            self._pending_recycle_reason = reason
            logger.info(f"🔄 SessionLifecycleManager: Cooperative recycle requested ({reason.value}). Scheduled for next boundary.")

    def _perform_actual_recycle(self, reason: RecycleReason = RecycleReason.RECYCLE_AGE):
        with self.lock:
            self.total_recycles += 1
            if self.session:
                try:
                    self.session.close()
                except Exception:
                    pass
            if HAS_CURL_CFFI and curl_requests is not None:
                self.session = curl_requests.Session(
                    impersonate=self.browser_profile,
                    max_redirects=0,
                    trust_env=False
                )
            else:
                self.session = None
            self.last_recycle_reason = reason
            self._pending_recycle_reason = None
            self.request_count = 0
            self.consecutive_errors = 0
            self.bytes_transferred = 0
            self.health_score = 100.0  # Reset health score on fresh connection pool
            self.session_created_monotonic = time.monotonic()
            self.last_success_monotonic = time.monotonic()

    def check_and_recycle(self):
        with self.lock:
            pending = self._pending_recycle_reason
            now = time.monotonic()
            session_age = now - self.session_created_monotonic
            
            if pending is not None:
                self._perform_actual_recycle(reason=pending)
            elif self.request_count >= 500:
                self._perform_actual_recycle(reason=RecycleReason.RECYCLE_BYTES)
            elif self.consecutive_errors >= 5 or self.health_score < 50.0:
                self._perform_actual_recycle(reason=RecycleReason.RECYCLE_ERRORS)
            elif session_age >= 900.0 or not self.session:
                self._perform_actual_recycle(reason=RecycleReason.RECYCLE_AGE)

    def get_session(self):
        with self.lock:
            self.request_count += 1
            return self.session

    def get_telemetry(self) -> Dict[str, Any]:
        with self.lock:
            now = time.monotonic()
            return {
                "session_age_sec": now - self.session_created_monotonic,
                "requests_on_session": self.request_count,
                "errors_on_session": self.consecutive_errors,
                "bytes_transferred": self.bytes_transferred,
                "health_score": self.health_score,
                "is_healthy": self.is_healthy,
                "last_recycle_reason": self.last_recycle_reason.value,
                "last_success_age_sec": now - self.last_success_monotonic,
                "total_recycles": self.total_recycles
            }

    def close(self):
        with self.lock:
            if self.session:
                try:
                    self.session.close()
                except Exception:
                    pass
                self.session = None