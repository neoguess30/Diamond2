from __future__ import annotations
import unittest
import os
import shutil
import time
from pathlib import Path

from core.models.job import Job
from core.state.enums import DeadLetterReason
from persistence.database import ConsolidatedDatabaseManager
from persistence.writer.storage_writer import StorageWriterWorker

class TestDLQAccountingConservation(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("./test_dlq_env")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.test_dir / "dlq_conservation.db")
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

    def test_dlq_transition_strictly_deletes_from_pending_jobs(self):
        """
        P0 Conservation Test: Proves that moving a job to dead_jobs
        ATOMICALLY deletes it from pending_jobs, maintaining exact conservation count.
        """
        # 1. Create and persist 10 pending jobs
        jobs = [Job.create_new(f"target_{i:02d}") for i in range(10)]
        self.assertTrue(self.db_mgr.save_pending_jobs_batch(jobs, wait_for_commit=True))

        time.sleep(0.5)
        # Verify initial pending count = 10
        conn = self.db_mgr._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(1) FROM pending_jobs;")
        self.assertEqual(cur.fetchone()[0], 10)
        conn.close()

        # 2. Escalate 3 jobs to DLQ
        for i in range(3):
            j = jobs[i]
            self.assertTrue(self.db_mgr.save_dead_letter(
                job_id=j.job_id,
                username=j.username,
                error_msg="Test Fatal Error",
                attempts=j.attempt,
                reason=DeadLetterReason.MAX_RETRIES_EXCEEDED,
                category="NETWORK_FATAL",
                correlation_id=j.correlation_id,
                wait_for_commit=True
            ))

        time.sleep(0.5)

        # 3. Verify Conservation Law: Pending (7) + DLQ (3) == Total Submitted (10)
        conn = self.db_mgr._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(1) FROM pending_jobs;")
        pending_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(1) FROM dead_jobs;")
        dlq_count = cur.fetchone()[0]
        conn.close()

        self.assertEqual(pending_count, 7)
        self.assertEqual(dlq_count, 3)
        self.assertEqual(pending_count + dlq_count, 10)

if __name__ == "__main__":
    unittest.main()