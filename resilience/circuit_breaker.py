from __future__ import annotations
import time
import threading
from typing import Dict, Any, Optional

from core.state.enums import CircuitState
from core.logger import logger

class NetworkCircuitBreaker:
    """
    Single-Probe Circuit Breaker with Dynamic Retry-After & Deadlock-Free Probe Leases:
    1. Prevents probe storms by allowing exactly 1 probe in HALF_OPEN.
    2. Auto-expiring Probe Lease (15.0s) prevents permanent deadlocks if a thread drops early.
    3. Explicit abort_probe() API releases/reopens probe on early cancellations.
    """
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 12.0, probe_lease_timeout: float = 15.0):
        self.lock = threading.RLock()
        self.state = CircuitState.CLOSED
        self.failure_threshold = failure_threshold
        self.default_recovery_timeout = recovery_timeout
        self.recovery_timeout = recovery_timeout
        self.probe_lease_timeout = probe_lease_timeout
        
        self.consecutive_failures = 0
        self.consecutive_429s = 0
        self.last_failure_monotonic = 0.0
        self.probe_in_flight = False
        self.probe_start_monotonic = 0.0

        self.circuit_open_event = threading.Event()

    def can_execute(self) -> bool:
        with self.lock:
            now = time.monotonic()
            if self.state == CircuitState.CLOSED:
                return True
            elif self.state == CircuitState.OPEN:
                if now - self.last_failure_monotonic >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.probe_in_flight = True
                    self.probe_start_monotonic = now
                    self.circuit_open_event.clear()
                    logger.info("⚡ Single-Probe Circuit Breaker: Transitioned to HALF-OPEN. Permitting 1 probe request only.")
                    return True
                return False
            elif self.state == CircuitState.HALF_OPEN:
                # P0 Deadlock Guard: Auto-expire hung/orphaned probe lease if in-flight for > 15s
                if self.probe_in_flight and (now - self.probe_start_monotonic > self.probe_lease_timeout):
                    logger.warning("⚠️ Circuit Breaker: Stale probe lease expired in HALF-OPEN. Permitting new probe.")
                    self.probe_in_flight = True
                    self.probe_start_monotonic = now
                    return True

                if not self.probe_in_flight:
                    self.probe_in_flight = True
                    self.probe_start_monotonic = now
                    return True
                return False

    def record_success(self):
        """Called when server connection and response are verified successfully."""
        with self.lock:
            if self.state == CircuitState.HALF_OPEN:
                logger.info("🟢 Single-Probe Circuit Breaker: Probe verified success. Circuit CLOSED.")
            self.state = CircuitState.CLOSED
            self.consecutive_failures = 0
            self.consecutive_429s = 0
            self.recovery_timeout = self.default_recovery_timeout
            self.probe_in_flight = False
            self.probe_start_monotonic = 0.0
            self.circuit_open_event.clear()

    def record_failure(self, is_429: bool = False, retry_after_sec: Optional[float] = None):
        """Trips circuit to OPEN upon verified network/server failure."""
        with self.lock:
            self.consecutive_failures += 1
            if is_429:
                self.consecutive_429s += 1
            self.last_failure_monotonic = time.monotonic()

            if retry_after_sec is not None and retry_after_sec > 0:
                self.recovery_timeout = max(self.default_recovery_timeout, retry_after_sec)
            else:
                self.recovery_timeout = self.default_recovery_timeout

            if self.consecutive_failures >= self.failure_threshold or self.consecutive_429s >= 2 or self.state == CircuitState.HALF_OPEN:
                if self.state != CircuitState.OPEN:
                    logger.warning(
                        f"🔴 Circuit Breaker: OPENED ({self.consecutive_failures} failures, {self.consecutive_429s} rate-limits). "
                        f"Cooldown set to {self.recovery_timeout:.1f}s."
                    )
                self.state = CircuitState.OPEN
                self.probe_in_flight = False
                self.probe_start_monotonic = 0.0
                self.circuit_open_event.set()

    def abort_probe(self, reopen: bool = False, reason: str = "CANCELLED"):
        """
        P0 Probe Settling API:
        - If reopen is True: Trips state back to OPEN.
        - If reopen is False (e.g. cancelled/rate-limited before network): Releases probe slot immediately for next request.
        """
        with self.lock:
            if self.state == CircuitState.HALF_OPEN:
                if reopen:
                    self.record_failure()
                else:
                    self.probe_in_flight = False
                    self.probe_start_monotonic = 0.0
                    logger.debug(f"Circuit Breaker: Probe released ({reason}) in HALF-OPEN state.")

    def get_state(self) -> CircuitState:
        with self.lock:
            return self.state

    def get_telemetry(self) -> Dict[str, Any]:
        with self.lock:
            now = time.monotonic()
            remaining_recovery = max(0.0, self.recovery_timeout - (now - self.last_failure_monotonic)) if self.state == CircuitState.OPEN else 0.0
            return {
                "state": self.state.value,
                "consecutive_failures": self.consecutive_failures,
                "consecutive_429s": self.consecutive_429s,
                "recovery_remaining_sec": remaining_recovery,
                "configured_cooldown_sec": self.recovery_timeout,
                "probe_in_flight": self.probe_in_flight,
                "last_failure_age_sec": (now - self.last_failure_monotonic) if self.last_failure_monotonic > 0 else 0.0
            }