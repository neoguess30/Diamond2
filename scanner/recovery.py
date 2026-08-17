from __future__ import annotations
import queue
from collections import deque
from typing import List, Any
from core.models.job import Job
from core.state.enums import JobSource, JobStatus, ScanCheckResult
from core.logger import logger

class WorkerStateRecovery:
    """Transfers queued, inflight, and pending jobs seamlessly to replacement workers."""
    
    @staticmethod
    def transfer_queue_items(source_queue: queue.Queue, target_queue: queue.Queue) -> int:
        transferred = 0
        try:
            while not source_queue.empty():
                try:
                    job = source_queue.get_nowait()
                    target_queue.put_nowait(job)
                    source_queue.task_done()
                    transferred += 1
                except queue.Empty:
                    break
        except Exception as e:
            logger.warning(f"WorkerStateRecovery: Queue transfer warning: {e}")
        return transferred

    @staticmethod
    def restore_inflight_jobs(inflight_jobs: List[Any], target_scanner: Any, db: Any) -> int:
        restored = 0
        for ifj in inflight_jobs:
            if db.is_scanned(ifj.username) != ScanCheckResult.FOUND:
                requeued_job = Job(
                    job_id=ifj.job_id,
                    username=ifj.username,
                    pattern_id=ifj.pattern_id,
                    source=JobSource.RECOVERY,
                    attempt=ifj.attempt,
                    correlation_id=ifj.correlation_id,
                    status=JobStatus.QUEUED,
                    created_monotonic=ifj.created_monotonic
                )
                target_scanner.add_job_direct(requeued_job)
                restored += 1
        return restored