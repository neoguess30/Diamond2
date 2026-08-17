from __future__ import annotations
import unittest
import time

from resilience.circuit_breaker import NetworkCircuitBreaker
from core.state.enums import CircuitState

class TestCircuitBreakerResilience(unittest.TestCase):

    def test_state_transitions(self):
        cb = NetworkCircuitBreaker(failure_threshold=3, recovery_timeout=0.2)
        
        # Initial State: CLOSED
        self.assertEqual(cb.get_state(), CircuitState.CLOSED)
        self.assertTrue(cb.can_execute())

        # Record 2 failures -> Still CLOSED
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.get_state(), CircuitState.CLOSED)

        # 3rd failure -> Transition to OPEN
        cb.record_failure()
        self.assertEqual(cb.get_state(), CircuitState.OPEN)
        self.assertFalse(cb.can_execute())

        # Wait recovery timeout (0.2s) -> Transition to HALF_OPEN (Single Probe)
        time.sleep(0.25)
        self.assertTrue(cb.can_execute())
        self.assertEqual(cb.get_state(), CircuitState.HALF_OPEN)

        # Second request blocked while single probe is in-flight
        self.assertFalse(cb.can_execute())

        # Probe success -> Transition back to CLOSED
        cb.record_success()
        self.assertEqual(cb.get_state(), CircuitState.CLOSED)
        self.assertTrue(cb.can_execute())

    def test_rate_limit_429_rapid_trip(self):
        # Two consecutive 429s should trip the circuit immediately
        cb = NetworkCircuitBreaker(failure_threshold=10, recovery_timeout=1.0)
        cb.record_failure(is_429=True)
        cb.record_failure(is_429=True)
        self.assertEqual(cb.get_state(), CircuitState.OPEN)

if __name__ == "__main__":
    unittest.main()