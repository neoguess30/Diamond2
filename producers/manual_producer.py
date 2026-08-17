from __future__ import annotations
from typing import Any
from core.models.job import Job
from core.state.enums import JobSource

class ManualTargetProducer:
    """Handles manual/interactive single target ingestion into the scanner engine."""
    def __init__(self, scanner_worker: Any, db: Any):
        self.scanner = scanner_worker
        self.db = db

    def submit_target(self, username: str, priority: bool = False, timeout: float = 2.0) -> bool:
        clean_user = username.strip().replace("@", "")
        if not clean_user:
            return False

        job = Job.create_new(username=clean_user, pattern_id="MANUAL_INPUT", source=JobSource.MANUAL)
        if self.db:
            self.db.save_pending_job(job)
            
        return self.scanner.add_job_direct(job, timeout=timeout)