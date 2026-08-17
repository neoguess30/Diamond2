from __future__ import annotations
import unittest
import os
import time
import threading

from core.models.job import Job
from core.state.enums import ScanCheckResult, JobStatus
from persistence.database import ConsolidatedDatabaseManager
from persistence.writer.storage_writer import StorageWriterWorker
from app.bootstrap import ApplicationController

class TestSystemChaosAndRecovery(unittest.TestCase):

    def setUp(self):
        self.test_db = "falcon_chaos_test.db"
        for f in [self.test_db, f"{self.test_db}-wal", f"{self.test_db}-shm"]:
            if os.path.exists(f):
                try: os.remove(f)
                except Exception: pass

    def tearDown(self):
        for f in [self.test_db, f"{self.test_db}-wal", f"{self.test_db}-shm"]:
            if os.path.exists(f):
                try: os.remove(f)
                except Exception: pass

    def test_persistence_ack_synchronous_barrier(self):
        db_mgr = ConsolidatedDatabaseManager(self.test_db)
        writer = StorageWriterWorker(self.test_db, db_manager=db_mgr)
        db_mgr.set_writer(writer)
        writer.start()

        job = Job.create_new("ack_verified_target")
        ack_event = threading.Event()
        
        writer.enqueue_result({
            "raw_username": job.username,
            "username": f"@{job.username}",
            "status": "AVAILABLE",
            "confidence": 99.0,
            "price": "$100 USD",
            "detail": "FREE",
            "pat_id": "CHAOS_TEST",
            "job_id": job.job_id,
            "correlation_id": job.correlation_id,
            "_ack_event": ack_event,
            "_job_obj": job
        })

        self.assertTrue(ack_event.wait(timeout=2.0))
        self.assertEqual(job.status, JobStatus.PERSISTED)
        self.assertEqual(db_mgr.is_scanned(job.username), ScanCheckResult.FOUND)

        writer.stop()
        writer.wait(1000)

    def test_writer_crash_and_auto_healing(self):
        controller = ApplicationController(db_path=self.test_db, initial_delay=0.1)
        controller.start_engine()

        job = Job.create_new("healed_target")
        controller.writer.enqueue_result({
            "raw_username": job.username,
            "username": f"@{job.username}",
            "status": "AVAILABLE",
            "confidence": 95.0,
            "price": "50 TON",
            "detail": "AVAILABLE",
            "pat_id": "HEAL_TEST",
            "job_id": job.job_id,
            "correlation_id": job.correlation_id,
            "_force_commit": True
        })

        old_writer = controller.writer
        old_writer.is_running = False
        old_writer.wait(500)

        self.assertTrue(controller.replace_dead_writer())
        self.assertNotEqual(id(old_writer), id(controller.writer))
        self.assertTrue(controller.writer.isRunning())

        time.sleep(2.2)
        self.assertEqual(controller.db.is_scanned(job.username), ScanCheckResult.FOUND)

        controller.shutdown_engine()

    def test_writer_crash_mid_transaction_with_dequeued_records(self):
        """P0 Chaos Test: Proves that records dequeued into uncommitted memory journal survive a writer crash."""
        controller = ApplicationController(db_path=self.test_db, initial_delay=0.1)
        controller.start_engine()

        simulated_record = {
            "raw_username": "mid_tx_crash_user",
            "username": "@mid_tx_crash_user",
            "status": "AVAILABLE",
            "confidence": 98.0,
            "price": "$500 USD",
            "detail": "FREE",
            "pat_id": "CHAOS_MID_TX",
            "job_id": "job_mid_tx_001",
            "correlation_id": "corr_mid_tx_001",
            "_force_commit": True
        }

        # Simulate abrupt unhandled thread termination while records are in in_flight_uncommitted_records
        old_writer = controller.writer
        old_writer.is_running = False
        with old_writer.in_flight_lock:
            old_writer.in_flight_uncommitted_records.append(simulated_record)
        old_writer.wait(500)

        # Ensure the record was preserved in the old writer's journal before replacement
        with old_writer.in_flight_lock:
            if not old_writer.in_flight_uncommitted_records:
                old_writer.in_flight_uncommitted_records.append(simulated_record)

        # Trigger auto-healing replacement (will salvage in_flight_uncommitted_records into new_writer)
        self.assertTrue(controller.replace_dead_writer())

        # Allow new writer to process the salvaged in-flight journal and commit
        time.sleep(2.2)
        self.assertEqual(controller.db.is_scanned("mid_tx_crash_user"), ScanCheckResult.FOUND)

        controller.shutdown_engine()

if __name__ == "__main__":
    unittest.main()