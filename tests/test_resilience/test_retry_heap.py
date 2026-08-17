from __future__ import annotations
import unittest
import time

from resilience.retry_manager import RetryHeapManager
from core.models.job import Job

class TestRetryHeapResilience(unittest.TestCase):

    def test_heap_priority_ordering(self):
        manager = RetryHeapManager(max_capacity=10)
        now = time.monotonic()

        job_later = Job.create_new("later_user")
        job_sooner = Job.create_new("sooner_user")

        # Push later job first, then sooner job
        manager.push(now + 0.3, job_later)
        manager.push(now + 0.1, job_sooner)

        # At t=0, none ready
        self.assertIsNone(manager.pop_ready(now))

        # At t=0.15, sooner job must pop first despite being inserted second
        ready_1 = manager.pop_ready(now + 0.15)
        self.assertIsNotNone(ready_1)
        self.assertEqual(ready_1.username, "sooner_user")

        # At t=0.35, later job pops
        ready_2 = manager.pop_ready(now + 0.35)
        self.assertIsNotNone(ready_2)
        self.assertEqual(ready_2.username, "later_user")

    def test_heap_capacity_bound(self):
        manager = RetryHeapManager(max_capacity=2)
        now = time.monotonic()

        self.assertTrue(manager.push(now + 1.0, Job.create_new("user1")))
        self.assertTrue(manager.push(now + 1.0, Job.create_new("user2")))
        # 3rd push must be rejected due to hard capacity limit
        self.assertFalse(manager.push(now + 1.0, Job.create_new("user3")))

if __name__ == "__main__":
    unittest.main()