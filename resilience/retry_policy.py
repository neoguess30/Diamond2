from __future__ import annotations
from typing import Tuple
from core.models.job import Job
from core.errors.categories import ErrorCategory, DeadLetterReason
from core.config import MAX_TOTAL_RETRY_BUDGET
from resilience.deadlines import DeadlineManager

class RetryPolicy:
    """Evaluates whether a failed job should be retried or escalated to DLQ."""
    
    @classmethod
    def evaluate(cls, job: Job, err_category: ErrorCategory, error_sig: str = "") -> Tuple[bool, DeadLetterReason | None]:
        # 1. Absolute Lifecycle Deadline check
        if DeadlineManager.is_lifecycle_expired(job.created_monotonic):
            return False, DeadLetterReason.ABSOLUTE_LIFECYCLE_EXCEEDED

        # 2. Execution Deadline check
        if DeadlineManager.is_execution_expired(job.started_monotonic):
            return False, DeadLetterReason.JOB_DEADLINE_EXCEEDED

        # 3. Retry Age check
        if DeadlineManager.is_retry_age_expired(job.first_failure_monotonic):
            return False, DeadLetterReason.RETRY_AGE_EXCEEDED

        # 4. Poison Job Detection
        if job.is_poison(error_sig):
            return False, DeadLetterReason.POISON_JOB

        # 5. Retry Budget & Max Attempts (Up to 3 active network retries and budget > 0)
        if job.attempt < 3 and job.retry_budget > 0:
            return True, None

        # 6. Retry Budget or Max Retries Exhausted
        if job.retry_budget <= 0:
            return False, DeadLetterReason.RETRY_BUDGET_EXHAUSTED
        
        return False, DeadLetterReason.MAX_RETRIES_EXCEEDED