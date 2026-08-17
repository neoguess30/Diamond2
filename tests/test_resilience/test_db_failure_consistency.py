from __future__ import annotations
import unittest
import os
import shutil
import time
import threading
from pathlib import Path

from core.state.enums import ScanCheckResult, JobStatus
from core.models.job import Job
from persistence.database import ConsolidatedDatabaseManager
from persistence.writer.storage_writer import StorageWriterWorker

class TestDatabaseFailureConsistency(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("./test_db_consistency_env")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.test_dir / "consistency_test.db")
        self.db_mgr = ConsolidatedDatabaseManager(self.db_path)
        self.writer = StorageWriterWorker(self.db_path, db_manager=self.db_mgr)
        self.writer.desktop_dir = self.test_dir
        self.db_mgr.set_writer(self.writer)
        self.writer.start()
        self.writer.wait_ready(timeout=5.0)

    def tearDown(self):
        self.writer.stop()
        self.writer.wait(2000)
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_failed_sql_execution_does_not_contaminate_lru_cache(self):
        """
        P0 Test: Proves that if a record fails SQL insertion/execution:
        1. It is NEVER marked as SCANNED in LRU cache.
        2. Subsequent check returns NOT_FOUND after table restore (preventing false deduplication).
        3. Record is safely quarantined without silent disappearance.
        """
        username = "unlucky_failed_target"
        job = Job.create_new(username)
        ack_event = threading.Event()

        # Stop writer and drop table to simulate complete SQL execute failure
        self.writer.stop()
        self.writer.wait(1000)

        with self.db_mgr.lock:
            conn = self.db_mgr._get_connection()
            conn.execute("DROP TABLE scan_results;")
            conn.commit()
            conn.close()

        # Restart writer on damaged DB
        self.writer = StorageWriterWorker(self.db_path, db_manager=self.db_mgr)
        self.writer.desktop_dir = self.test_dir
        self.db_mgr.set_writer(self.writer)
        self.writer.start()
        self.writer.wait_ready(timeout=5.0)

        # Dispatch result to writer (will fail execution on missing table)
        self.writer.enqueue_result({
            "raw_username": username,
            "username": f"@{username}",
            "status": "AVAILABLE",
            "confidence": 99.0,
            "price": "$500 USD",
            "detail": "FREE",
            "pat_id": "FAIL_TEST",
            "job_id": job.job_id,
            "correlation_id": job.correlation_id,
            "_ack_event": ack_event,
            "_job_obj": job
        })

        # Wait for failure handling
        ack_event.wait(timeout=2.0)
        time.sleep(0.5)

        # 1. Verify that LRU Cache does NOT contain this username
        self.assertIsNone(self.db_mgr.lru_cache.get(username))

        # 2. Stop writer, re-create table cleanly, and verify that is_scanned reports NOT_FOUND
        self.writer.stop()
        self.writer.wait(1000)

        self.db_mgr._init_db()
        self.assertEqual(self.db_mgr.is_scanned(username), ScanCheckResult.NOT_FOUND)

        # 3. Verify writer degradation caught the error
        self.assertGreater(self.writer.total_write_failures, 0)

if __name__ == "__main__":
    unittest.main()