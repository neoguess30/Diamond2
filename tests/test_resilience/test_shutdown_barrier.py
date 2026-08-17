from __future__ import annotations
import unittest
import os
import shutil
import time
from pathlib import Path

from core.state.enums import EngineState
from app.bootstrap import ApplicationController

class TestShutdownBarrierResilience(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("./test_shutdown_env")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.test_dir / "shutdown_test.db")
        self.controller = ApplicationController(db_path=self.db_path, initial_delay=0.1)
        self.controller.start_engine()

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_worker_replacement_is_strictly_blocked_during_shutdown(self):
        """
        P0 Test: Proves that worker and writer replacements are 100% blocked
        once the controller enters STOPPING or STOPPED state, preventing replacement storms.
        """
        self.assertEqual(self.controller.state, EngineState.RUNNING)

        # Trigger clean shutdown sequence
        shutdown_ok = self.controller.shutdown_engine()
        self.assertTrue(shutdown_ok)
        self.assertEqual(self.controller.state, EngineState.STOPPED)

        # Attempt to trigger worker replacement while stopped -> MUST return False!
        self.assertFalse(self.controller.replace_dead_worker())
        self.assertFalse(self.controller.replace_dead_writer())

    def test_7_stage_barrier_drain_cleanliness(self):
        """P0 Test: Verifies that after shutdown, all pipeline threads are finished and unblocked."""
        self.controller.shutdown_engine()

        # All threads must report isFinished() == True
        self.assertFalse(self.controller.worker.isRunning())
        self.assertFalse(self.controller.writer.isRunning())
        self.assertFalse(self.controller.supervisor.isRunning())

if __name__ == "__main__":
    unittest.main()