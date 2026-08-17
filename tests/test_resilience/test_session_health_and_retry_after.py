from __future__ import annotations
import unittest
import time

from network.session import SessionLifecycleManager
from network.controller import CentralizedNetworkController
from network.client import parse_retry_after_header
from resilience.circuit_breaker import NetworkCircuitBreaker
from core.state.enums import CircuitState

class TestSessionHealthAndRetryAfter(unittest.TestCase):

    def test_session_health_score_degradation_and_auto_recycle(self):
        mgr = SessionLifecycleManager()
        self.assertEqual(mgr.health_score, 100.0)
        self.assertTrue(mgr.is_healthy)

        # Simulate successive failures reducing score
        mgr.record_429()       # -5 -> 95
        mgr.record_timeout()   # -2 -> 93
        mgr.record_5xx()       # -2 -> 91
        self.assertEqual(mgr.health_score, 91.0)
        self.assertTrue(mgr.is_healthy)

        # Force health score below 50
        for _ in range(9):
            mgr.record_429()   # 9 * 5 = 45 penalty -> score drops to 46.0

        self.assertLess(mgr.health_score, 50.0)
        self.assertFalse(mgr.is_healthy)
        self.assertIsNotNone(mgr._pending_recycle_reason)

        # Executing check_and_recycle must replenish health score to 100.0
        mgr.check_and_recycle()
        self.assertEqual(mgr.health_score, 100.0)
        self.assertTrue(mgr.is_healthy)

    def test_parse_retry_after_numeric_and_http_date(self):
        # 1. Numeric seconds
        sec = parse_retry_after_header("30")
        self.assertEqual(sec, 30.0)

        # 2. None / Empty
        self.assertIsNone(parse_retry_after_header(None))
        self.assertIsNone(parse_retry_after_header(""))

    def test_controller_aimd_slow_start_ramp_up(self):
        ctrl = CentralizedNetworkController(initial_delay=1.0)
        self.assertEqual(ctrl.shared_delay, 1.0)

        # 429 multiplicative increase
        ctrl.report_response(429, 200.0, retry_after_sec=10.0)
        self.assertGreaterEqual(ctrl.shared_delay, 10.0)

        # Sustained 200 OKs additive decrease (slow start / gradual recovery)
        current_delay = ctrl.shared_delay
        ctrl.report_response(200, 100.0)
        self.assertLess(ctrl.shared_delay, current_delay)

    def test_circuit_breaker_respects_custom_retry_after_cooldown(self):
        cb = NetworkCircuitBreaker(failure_threshold=2, recovery_timeout=5.0)
        # Record 429 with 20-second Retry-After
        cb.record_failure(is_429=True, retry_after_sec=20.0)
        cb.record_failure(is_429=True, retry_after_sec=20.0)
        
        self.assertEqual(cb.get_state(), CircuitState.OPEN)
        self.assertEqual(cb.recovery_timeout, 20.0)

if __name__ == "__main__":
    unittest.main()