from __future__ import annotations
import unittest
import os
import shutil
import time
from pathlib import Path

from core.models.job import Job
from persistence.database import ConsolidatedDatabaseManager
from persistence.writer.storage_writer import StorageWriterWorker, PersistenceAck

class TestPersistenceAckAccuracy(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("./test_ack_env")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.test_dir / "ack_accuracy.db")
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

    def test_persistence_ack_returns_true_only_on_actual_commit(self):
        """P0 Test: Proves that save_pending_job returns True ONLY when committed durably."""
        job = Job.create_new("truthful_ack_user")
        
        # Valid database -> Must return True
        persisted = self.db_mgr.save_pending_job(job, wait_for_commit=True)
        self.assertTrue(persisted)

    def test_persistence_ack_strictly_returns_false_on_database_failure(self):
        """
        P0 Test: Proves that if SQL execute fails, wait_for_commit strictly returns FALSE
        and NEVER lies to caller with a false-positive True!
        """
        # Stop writer and drop table to simulate hard SQL execution failure
        self.writer.stop()
        self.writer.wait(1000)

        with self.db_mgr.lock:
            conn = self.db_mgr._get_connection()
            conn.execute("DROP TABLE pending_jobs;")
            conn.commit()
            conn.close()

        # Restart writer on damaged DB
        self.writer = StorageWriterWorker(self.db_path, db_manager=self.db_mgr)
        self.writer.desktop_dir = self.test_dir
        self.db_mgr.set_writer(self.writer)
        self.writer.start()
        self.writer.wait_ready(timeout=5.0)

        job = Job.create_new("should_fail_persisting")
        
        # P0 Guarantee: Must return False (NOT True!) because execute failed
        persisted = self.db_mgr.save_pending_job(job, wait_for_commit=True)
        self.assertFalse(persisted)

if __name__ == "__main__":
    unittest.main()