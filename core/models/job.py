from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Any
from core.state.enums import JobStatus, JobSource
from core.errors.categories import ErrorCategory, DeadLetterReason
from core.config import MAX_TOTAL_RETRY_BUDGET, MAX_QUEUE_WAIT_SEC, MAX_JOB_RUNTIME_SEC, MAX_JOB_LIFECYCLE_SEC

@dataclass
class Job:
    job_id: str
    username: str
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    pattern_id: str = ""
    source: JobSource = JobSource.PATTERN
    attempt: int = 0
    retry_budget: int = MAX_TOTAL_RETRY_BUDGET
    result_sequence: Optional[int] = None
    status: JobStatus = JobStatus.CREATED
    generation_id: int = 1
    created_monotonic: float = field(default_factory=time.monotonic)
    started_monotonic: Optional[float] = None
    scanned_monotonic: Optional[float] = None
    persist_pending_monotonic: Optional[float] = None
    persisted_monotonic: Optional[float] = None
    finished_monotonic: Optional[float] = None
    first_failure_monotonic: Optional[float] = None
    last_failure_monotonic: Optional[float] = None
    last_error: str = ""
    error_signature: str = ""
    retry_at_epoch: float = 0.0
    failure_category: Optional[ErrorCategory] = None
    dead_letter_reason: Optional[DeadLetterReason] = None

    @property
    def idempotency_key(self) -> str:
        """P0 Unique Deterministic Idempotency Key across distributed pipeline layers."""
        return f"{self.job_id}_attempt_{self.attempt}"

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Job):
            return NotImplemented
        return self.created_monotonic < other.created_monotonic

    @classmethod
    def create_new(cls, username: str, pattern_id: str = "", source: JobSource = JobSource.PATTERN, generation_id: int = 1) -> Job:
        uname_clean = username.lower().strip().replace("@", "")
        unique_token = uuid.uuid4().hex
        job_id = f"job_{uname_clean}_{unique_token}"
        corr_id = f"corr_{uuid.uuid4().hex[:12]}"
        return cls(
            job_id=job_id,
            username=uname_clean,
            correlation_id=corr_id,
            pattern_id=pattern_id,
            source=source,
            attempt=0,
            retry_budget=MAX_TOTAL_RETRY_BUDGET,
            status=JobStatus.QUEUED,
            generation_id=generation_id,
            created_monotonic=time.monotonic()
        )

    def is_queue_expired(self) -> bool:
        if self.started_monotonic is not None:
            return False
        return (time.monotonic() - self.created_monotonic) > MAX_QUEUE_WAIT_SEC

    def is_execution_expired(self) -> bool:
        if self.started_monotonic is None:
            return False
        return (time.monotonic() - self.started_monotonic) > MAX_JOB_RUNTIME_SEC

    def is_lifecycle_expired(self) -> bool:
        return (time.monotonic() - self.created_monotonic) > MAX_JOB_LIFECYCLE_SEC

    def is_expired(self) -> bool:
        return self.is_execution_expired() or self.is_lifecycle_expired()

    def get_remaining_deadline_sec(self) -> float:
        now = time.monotonic()
        remaining_execution = MAX_JOB_RUNTIME_SEC if self.started_monotonic is None else max(0.5, MAX_JOB_RUNTIME_SEC - (now - self.started_monotonic))
        remaining_lifecycle = max(0.5, MAX_JOB_LIFECYCLE_SEC - (now - self.created_monotonic))
        return min(remaining_execution, remaining_lifecycle)

    def is_poison(self, new_error_sig: str) -> bool:
        if self.attempt >= 2 and self.error_signature == new_error_sig and (time.monotonic() - (self.first_failure_monotonic or 0.0) < 10.0):
            return True
        return False

    def mark_queued(self): self.status = JobStatus.QUEUED
    def mark_in_flight(self):
        self.status = JobStatus.IN_FLIGHT
        if self.started_monotonic is None: self.started_monotonic = time.monotonic()
    def mark_result_ready(self):
        self.status = JobStatus.RESULT_READY
        self.scanned_monotonic = time.monotonic()
    def mark_persist_pending(self):
        self.status = JobStatus.PERSIST_PENDING
        self.persist_pending_monotonic = time.monotonic()
    def mark_persisted(self, seq_num: Optional[int] = None):
        self.status = JobStatus.PERSISTED
        self.result_sequence = seq_num
        self.persisted_monotonic = time.monotonic()
    def mark_completed(self):
        self.status = JobStatus.COMPLETED
        self.finished_monotonic = time.monotonic()
    def mark_retryable(self, error_msg: str, category: Optional[ErrorCategory] = None, error_sig: str = ""):
        now = time.monotonic()
        self.status = JobStatus.RETRYABLE
        self.last_error = error_msg
        # Safe attribute extraction handling None category
        self.error_signature = error_sig or (category.value if category is not None else "ERROR")
        self.failure_category = category
        self.last_failure_monotonic = now
        if self.first_failure_monotonic is None: self.first_failure_monotonic = now
        self.attempt += 1
        self.retry_budget = max(0, self.retry_budget - 1)
    def mark_poison_job(self, error_msg: str, category: ErrorCategory):
        self.status = JobStatus.POISON_JOB
        self.last_error = error_msg
        self.failure_category = category
        self.dead_letter_reason = DeadLetterReason.POISON_JOB
        self.finished_monotonic = time.monotonic()
    def mark_permanent_failure(self, error_msg: str, category: ErrorCategory, reason: DeadLetterReason):
        self.status = JobStatus.PERMANENT_FAIL
        self.last_error = error_msg
        self.failure_category = category
        self.dead_letter_reason = reason
        self.finished_monotonic = time.monotonic()
    def mark_cancelled(self, reason: str = "USER_CANCELLED"):
        self.status = JobStatus.CANCELLED
        self.last_error = reason
        self.finished_monotonic = time.monotonic()

@dataclass
class InFlightJob:
    job_id: str
    username: str
    correlation_id: str
    pattern_id: str
    attempt: int
    generation_id: int = 1
    created_monotonic: float = field(default_factory=time.monotonic)