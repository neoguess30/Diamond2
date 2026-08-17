from __future__ import annotations
import time
from typing import Optional
from core.models.job import Job
from resilience.retry_manager import RetryHeapManager
from resilience.backoff import calculate_retry_delay

class RetryScheduler:
    """Handles time-based delayed retry scheduling and priority queue management."""
    def __init__(self, retry_manager: RetryHeapManager):
        self.retry_manager = retry_manager

    def schedule_retry(self, job: Job, base_delay: float = 2.0) -> bool:
        delay_sec = calculate_retry_delay(job.attempt, base=base_delay)
        retry_at = time.monotonic() + delay_sec
        return self.retry_manager.push(retry_at, job)

    def schedule_immediate(self, job: Job) -> bool:
        return self.retry_manager.push(time.monotonic(), job)

    def schedule_delayed(self, job: Job, delay_sec: float) -> bool:
        return self.retry_manager.push(time.monotonic() + delay_sec, job)

    def fetch_next_ready(self) -> Optional[Job]:
        return self.retry_manager.pop_ready()

    def get_pending_count(self) -> int:
        return self.retry_manager.get_queue_len()