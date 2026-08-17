from __future__ import annotations
import queue
from typing import Optional, Tuple, Any
from core.models.job import Job
from core.state.enums import DeadLetterReason
from core.errors.categories import ErrorCategory
from resilience.deadlines import DeadlineManager

class TaskDispatcher:
    """Dispatches next executable job while enforcing wait and lifecycle deadlines."""
    
    @staticmethod
    def dispatch_next_job(
        main_queue: queue.Queue,
        scheduler: Any,
        timeout: float = 0.1
    ) -> Tuple[Optional[Job], bool]:
        # 1. Priority to Retry Heap
        ready_retry = scheduler.fetch_next_ready()
        if ready_retry:
            return ready_retry, True

        # 2. Main Queue
        try:
            job = main_queue.get(block=True, timeout=timeout)
            return job, False
        except queue.Empty:
            return None, False

    @staticmethod
    def validate_job_deadlines(job: Job, from_retry_heap: bool) -> Tuple[bool, Optional[DeadLetterReason]]:
        # 1. Queue wait deadline
        if not from_retry_heap and DeadlineManager.is_queue_wait_expired(job.created_monotonic, job.started_monotonic):
            return False, DeadLetterReason.QUEUE_DEADLINE_EXCEEDED

        # 2. Total absolute lifecycle deadline
        if DeadlineManager.is_lifecycle_expired(job.created_monotonic):
            return False, DeadLetterReason.ABSOLUTE_LIFECYCLE_EXCEEDED

        # 3. Retry age deadline
        if from_retry_heap and DeadlineManager.is_retry_age_expired(job.first_failure_monotonic):
            return False, DeadLetterReason.RETRY_AGE_EXCEEDED

        # 4. Active runtime deadline
        if from_retry_heap and DeadlineManager.is_execution_expired(job.started_monotonic):
            return False, DeadLetterReason.JOB_DEADLINE_EXCEEDED

        return True, None