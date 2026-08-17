from __future__ import annotations
import time
from typing import Tuple
from core.config import (
    CONNECT_TIMEOUT_SEC,
    READ_TIMEOUT_SEC,
    MAX_JOB_RUNTIME_SEC,
    MAX_QUEUE_WAIT_SEC,
    MAX_JOB_LIFECYCLE_SEC,
    MAX_RETRY_AGE_SEC
)

class DeadlineManager:
    """Calculates adjusted network timeouts and deadline constraints."""
    
    @staticmethod
    def calculate_network_timeouts(remaining_deadline_sec: float) -> Tuple[float, float]:
        """Deadline Propagation: Computes connection and read timeouts within the remaining job deadline."""
        connect_t = min(CONNECT_TIMEOUT_SEC, max(0.5, remaining_deadline_sec / 2.0))
        read_t = min(READ_TIMEOUT_SEC, max(0.5, remaining_deadline_sec - connect_t))
        return connect_t, read_t

    @staticmethod
    def is_queue_wait_expired(created_monotonic: float, started_monotonic: float | None) -> bool:
        if started_monotonic is not None:
            return False
        return (time.monotonic() - created_monotonic) > MAX_QUEUE_WAIT_SEC

    @staticmethod
    def is_execution_expired(started_monotonic: float | None) -> bool:
        if started_monotonic is None:
            return False
        return (time.monotonic() - started_monotonic) > MAX_JOB_RUNTIME_SEC

    @staticmethod
    def is_lifecycle_expired(created_monotonic: float) -> bool:
        return (time.monotonic() - created_monotonic) > MAX_JOB_LIFECYCLE_SEC

    @staticmethod
    def is_retry_age_expired(first_failure_monotonic: float | None) -> bool:
        if first_failure_monotonic is None:
            return False
        return (time.monotonic() - first_failure_monotonic) > MAX_RETRY_AGE_SEC