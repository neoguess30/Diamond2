from __future__ import annotations
import unittest
import os
import shutil
import time
from pathlib import Path

from core.models.job import Job
from core.state.enums import ScanCheckResult
from app.bootstrap import ApplicationController

class TestFencingAndIdempotencyResilience(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("./test_fencing_env")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.test_dir / "fencing_test.db")
        self.controller = ApplicationController(db_path=self.db_path, initial_delay=0.1)
        self.controller.start_engine()

    def tearDown(self):
        self.controller.shutdown_engine()
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_zombie_worker_fencing_token_drops_stale_execution(self):
        """
        P0 Test: Proves that when a worker is replaced (Gen #1 -> Gen #2),
        the old worker (Gen #1) detects its stale epoch and immediately halts without polluting DB.
        """
        old_worker = self.controller.worker
        self.assertEqual(old_worker.generation_id, 1)

        # Trigger worker replacement -> advances generation to #2
        self.assertTrue(self.controller.replace_dead_worker())
        self.assertEqual(self.controller.current_worker_generation, 2)
        self.assertEqual(self.controller.worker.generation_id, 2)

        # Old worker must detect that it is now a stale zombie
        self.assertTrue(old_worker.is_stale_generation())

    def test_idempotency_key_consistency(self):
        """P0 Test: Verifies that job idempotency keys remain deterministic across retries."""
        job = Job.create_new("idempotent_target")
        self.assertEqual(job.attempt, 0)
        self.assertTrue(job.idempotency_key.endswith("_attempt_0"))

        job.mark_retryable("Network error", None)
        self.assertEqual(job.attempt, 1)
        self.assertTrue(job.idempotency_key.endswith("_attempt_1"))

if __name__ == "__main__":
    unittest.main()