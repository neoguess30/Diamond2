from __future__ import annotations
import unittest
import os
import json
import shutil
from pathlib import Path

from persistence.emergency_journal import EmergencyJournalManager
from persistence.database import ConsolidatedDatabaseManager
from app.bootstrap import ApplicationController
from core.state.enums import ScanCheckResult

class TestEmergencyJournalResilience(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("./test_emergency_env")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.manager = EmergencyJournalManager(self.test_dir)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_emergency_write_and_fault_tolerant_recovery(self):
        records = [
            {"raw_username": "valid_user_1", "status": "AVAILABLE", "detail": "100 TON"},
            {"raw_username": "valid_user_2", "status": "AUCTION", "detail": "200 TON"}
        ]
        target_file = self.manager.write_emergency_dump(records, "TEST_SIMULATED_DB_FAIL")
        self.assertTrue(target_file.exists())

        # Inject corrupted / torn JSON line at the end of the file
        with open(target_file, "a", encoding="utf-8") as f:
            f.write('{"raw_username": "torn_user_3", "status": "AVAIL\n')

        class DummyDB:
            def __init__(self):
                self.saved_batches = []
                self.lock = None
            def _get_connection(self):
                import sqlite3
                conn = sqlite3.connect(":memory:")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS scan_results (
                        username TEXT PRIMARY KEY, status TEXT, confidence REAL, price TEXT, detail TEXT, pattern_id TEXT, result_sequence INTEGER, scanned_at TIMESTAMP
                    );
                """)
                conn.execute("CREATE TABLE IF NOT EXISTS pending_jobs (job_id TEXT PRIMARY KEY);")
                return conn
            def save_pending_jobs_batch(self, jobs, wait_for_commit=True):
                self.saved_batches.extend(jobs)
                return True

        dummy_db = DummyDB()

        restored_count, quarantined_count = self.manager.replay_and_restore_journals(dummy_db)
        
        self.assertEqual(restored_count, 2)
        self.assertEqual(quarantined_count, 1)
        self.assertTrue(self.manager.quarantine_file.exists())

    def test_startup_recovery_automatically_replays_emergency_journals(self):
        """P0 Test: Proves that ApplicationController on startup automatically finds and replays emergency journals."""
        db_path = str(self.test_dir / "startup_replay.db")
        
        # 1. Create a dummy emergency journal file on disk BEFORE controller boots
        emergency_dir = self.test_dir / "emergency_journals"
        emergency_dir.mkdir(parents=True, exist_ok=True)
        chunk_file = emergency_dir / "emergency_2026-08-17_01.jsonl"
        
        with open(chunk_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "raw_username": "salvaged_startup_user",
                "username": "@salvaged_startup_user",
                "status": "AVAILABLE",
                "confidence": 99.0,
                "price": "$700 USD",
                "detail": "FREE",
                "pat_id": "REPLAY_STARTUP",
                "job_id": "job_salvaged_01"
            }) + "\n")

        # 2. Boot ApplicationController (must trigger _perform_startup_recovery which replays emergency journal)
        controller = ApplicationController(db_path=db_path, initial_delay=0.1)
        controller.writer.desktop_dir = self.test_dir
        controller.writer.emergency_mgr = EmergencyJournalManager(self.test_dir)
        
        # Trigger startup recovery explicitly with configured test directory
        controller._perform_startup_recovery()

        # 3. Verify that the salvaged user is now COMMITTED in SQLite scan_results!
        self.assertEqual(controller.db.is_scanned("salvaged_startup_user"), ScanCheckResult.FOUND)

        # 4. Verify chunk file was renamed to .replayed
        self.assertTrue((emergency_dir / "emergency_2026-08-17_01.replayed").exists())

        controller.shutdown_engine()

if __name__ == "__main__":
    unittest.main()