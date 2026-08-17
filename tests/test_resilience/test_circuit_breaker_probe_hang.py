from __future__ import annotations
import unittest
import time
import threading

from resilience.circuit_breaker import NetworkCircuitBreaker
from core.state.enums import CircuitState

class TestCircuitBreakerProbeHangResilience(unittest.TestCase):

    def test_aborted_probe_does_not_deadlock_half_open_state(self):
        """
        P0 Test: Proves that an early abort (rate-limit/cancel) in HALF_OPEN
        releases the probe slot immediately without hanging subsequent executions!
        """
        cb = NetworkCircuitBreaker(failure_threshold=2, recovery_timeout=0.2)
        
        # Trip to OPEN
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.get_state(), CircuitState.OPEN)

        # Wait recovery timeout -> Next can_execute transitions to HALF_OPEN and acquires probe
        time.sleep(0.25)
        self.assertTrue(cb.can_execute())
        self.assertEqual(cb.get_state(), CircuitState.HALF_OPEN)
        self.assertTrue(cb.probe_in_flight)

        # Simulate early return in NetworkEngine (e.g. rate limiter timed out before HTTP fetch)
        cb.abort_probe(reopen=False, reason="TEST_RATE_LIMIT_EARLY_RETURN")
        self.assertFalse(cb.probe_in_flight)

        # Next request MUST be granted probe immediately without waiting another 12 seconds!
        self.assertTrue(cb.can_execute())
        self.assertTrue(cb.probe_in_flight)

        # Probe succeeds -> CLOSED
        cb.record_success()
        self.assertEqual(cb.get_state(), CircuitState.CLOSED)

    def test_stale_probe_lease_auto_expires_preventing_deadlock(self):
        """
        P0 Test: Proves that if a thread crashes mid-request and leaves probe_in_flight=True,
        the 15-second lease timeout auto-expires it and allows new probes to proceed.
        """
        cb = NetworkCircuitBreaker(failure_threshold=2, recovery_timeout=0.1, probe_lease_timeout=0.2)
        cb.record_failure()
        cb.record_failure()

        time.sleep(0.15)
        self.assertTrue(cb.can_execute())
        self.assertTrue(cb.probe_in_flight)

        # Thread abandons without settling -> probe_in_flight remains True
        # Immediate next check is blocked
        self.assertFalse(cb.can_execute())

        # Wait past probe lease timeout (0.2s)
        time.sleep(0.25)

        # can_execute MUST break the deadlocked lease and permit a new probe!
        self.assertTrue(cb.can_execute())
        cb.record_success()
        self.assertEqual(cb.get_state(), CircuitState.CLOSED)

if __name__ == "__main__":
    unittest.main()