from __future__ import annotations
import unittest
import time
import threading

from network.rate_limiter import TokenBucketRateLimiter

class TestTokenBucketRateLimiter(unittest.TestCase):

    def test_rate_limiter_burst_acquire(self):
        limiter = TokenBucketRateLimiter(rate_per_sec=10.0, burst_capacity=5.0)
        
        # Acquire 5 tokens immediately (Burst)
        for _ in range(5):
            self.assertTrue(limiter.acquire(timeout=0.01))

        # 6th acquire with zero timeout should fail immediately
        self.assertFalse(limiter.acquire(timeout=0.01))

    def test_rate_limiter_refill(self):
        limiter = TokenBucketRateLimiter(rate_per_sec=10.0, burst_capacity=2.0)
        
        # Exhaust capacity
        limiter.acquire(timeout=0.01)
        limiter.acquire(timeout=0.01)

        # Wait 0.25s -> should refill at least 2 tokens (10 * 0.25 = 2.5)
        time.sleep(0.25)
        self.assertTrue(limiter.acquire(timeout=0.01))

    def test_rate_limiter_instant_cancel_event(self):
        # Set rate very low so tokens take 10 seconds to generate
        limiter = TokenBucketRateLimiter(rate_per_sec=0.1, burst_capacity=0.0)
        limiter.tokens = 0.0
        
        cancel_evt = threading.Event()
        
        # Trigger cancel after 50ms while timeout is set to 2.0s
        def _cancel():
            time.sleep(0.05)
            cancel_evt.set()

        t = threading.Thread(target=_cancel)
        t.start()

        start_t = time.monotonic()
        acquired = limiter.acquire(timeout=2.0, cancel_event=cancel_evt)
        elapsed = time.monotonic() - start_t
        t.join()

        self.assertFalse(acquired)
        self.assertLess(elapsed, 0.5)  # Woke up in <500ms instead of blocking for 2.0s!

if __name__ == "__main__":
    unittest.main()