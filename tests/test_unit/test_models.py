from __future__ import annotations
import unittest
import time

from core.models.job import Job
from core.state.enums import JobStatus, JobSource
from core.errors.categories import ErrorCategory, DeadLetterReason
from core.config import MAX_TOTAL_RETRY_BUDGET, MAX_JOB_RUNTIME_SEC

class TestJobModel(unittest.TestCase):

    def test_job_creation(self):
        job = Job.create_new("FalconTarget", pattern_id="TEST_PAT", source=JobSource.PATTERN)
        self.assertEqual(job.username, "falcontarget")
        self.assertEqual(job.pattern_id, "TEST_PAT")
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertEqual(job.attempt, 0)
        self.assertEqual(job.retry_budget, MAX_TOTAL_RETRY_BUDGET)
        self.assertTrue(job.job_id.startswith("job_falcontarget_"))
        self.assertTrue(job.correlation_id.startswith("corr_"))

    def test_job_lifecycle_state_transitions(self):
        job = Job.create_new("tester")
        
        job.mark_in_flight()
        self.assertEqual(job.status, JobStatus.IN_FLIGHT)
        self.assertIsNotNone(job.started_monotonic)

        job.mark_result_ready()
        self.assertEqual(job.status, JobStatus.RESULT_READY)
        self.assertIsNotNone(job.scanned_monotonic)

        job.mark_persist_pending()
        self.assertEqual(job.status, JobStatus.PERSIST_PENDING)

        job.mark_persisted(seq_num=42)
        self.assertEqual(job.status, JobStatus.PERSISTED)
        self.assertEqual(job.result_sequence, 42)

        job.mark_completed()
        self.assertEqual(job.status, JobStatus.COMPLETED)
        self.assertIsNotNone(job.finished_monotonic)

    def test_job_poison_detection(self):
        job = Job.create_new("poison_target")
        error_sig = "TIMEOUT_0"

        # Attempt 1
        job.mark_retryable("Timeout 1", ErrorCategory.TIMEOUT, error_sig=error_sig)
        self.assertFalse(job.is_poison(error_sig))

        # Attempt 2 (Identical error signature in rapid succession)
        job.mark_retryable("Timeout 2", ErrorCategory.TIMEOUT, error_sig=error_sig)
        self.assertTrue(job.is_poison(error_sig))

    def test_job_execution_deadline(self):
        job = Job.create_new("deadline_target")
        job.mark_in_flight()
        # Simulate started 100s ago (exceeds MAX_JOB_RUNTIME_SEC = 60s)
        job.started_monotonic = time.monotonic() - (MAX_JOB_RUNTIME_SEC + 10.0)
        self.assertTrue(job.is_execution_expired())
        self.assertTrue(job.is_expired())

if __name__ == "__main__":
    unittest.main()