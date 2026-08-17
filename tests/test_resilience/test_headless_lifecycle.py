from __future__ import annotations
import unittest
import os
import shutil
from pathlib import Path

from app.application import Application
from core.state.enums import EngineState

class TestHeadlessLifecycle(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("./test_headless_env")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.test_dir / "headless_test.db")

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_headless_starts_engine_before_ingestion(self):
        """P0 Test: Proves that Headless mode starts the engine and verifies worker readiness before feeding."""
        app = Application(db_path=self.db_path)
        
        # Verify initial state is STOPPED
        self.assertEqual(app.controller.state, EngineState.STOPPED)
        
        # Starting engine must transition to RUNNING with verified readiness
        self.assertTrue(app.controller.start_engine())
        self.assertEqual(app.controller.state, EngineState.RUNNING)
        self.assertTrue(app.controller.worker.isRunning())
        self.assertTrue(app.controller.writer.isRunning())

        app.controller.shutdown_engine()
        self.assertEqual(app.controller.state, EngineState.STOPPED)

if __name__ == "__main__":
    unittest.main()