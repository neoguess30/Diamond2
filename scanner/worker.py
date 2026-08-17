from __future__ import annotations
import time
import queue
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict, Set, Optional, Tuple, Any

try:
    from PyQt6.QtCore import QThread, pyqtSignal
except ImportError:
    class QThread(threading.Thread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.daemon = True
        def wait(self, timeout_ms=None):
            timeout_sec = (timeout_ms / 1000.0) if timeout_ms is not None else None
            self.join(timeout=timeout_sec)
        def isRunning(self): return self.is_alive()
        def isFinished(self): return not self.is_alive()

    class _DummySignal:
        def connect(self, slot): pass
        def emit(self, *args, **kwargs): pass

    def pyqtSignal(*args, **kwargs):
        return _DummySignal()

from core.config import (
    MAX_GLOBAL_QUEUE,
    MAX_PATTERN_QUEUE,
    MAX_RETRY_QUEUE,
    MAX_WRITER_QUEUE,
    MAX_QUEUE_WAIT_SEC,
    MAX_JOB_RUNTIME_SEC,
    MAX_JOB_LIFECYCLE_SEC,
    MAX_RETRY_AGE_SEC
)
from core.models.job import Job
from core.state.enums import (
    JobStatus,
    JobSource,
    FragmentStatus,
    ScanCheckResult,
    VerificationMode,
    DeadLetterReason
)
from core.errors.categories import ErrorCategory
from core.metrics import METRICS
from core.logger import logger
from core.queues.inflight import InFlightRegistry
from network.client import NetworkEngine
from parser.parser import FragmentParser
from persistence.database import ConsolidatedDatabaseManager
from persistence.writer.storage_writer import StorageWriterWorker
from resilience.retry_manager import RetryHeapManager
from resilience.retry_policy import RetryPolicy
from resilience.backoff import calculate_retry_delay
from scanner.policies import ScannerPolicy

class ScannerWorker(QThread):
    sig_log = pyqtSignal(str)

    def __init__(
        self,
        db: ConsolidatedDatabaseManager,
        network: NetworkEngine,
        inflight: InFlightRegistry,
        writer: StorageWriterWorker,
        generation_id: int = 1,
        controller: Any = None
    ):
        super().__init__()
        self.db = db
        self.network = network
        self.inflight = inflight
        self.writer = writer
        self.generation_id = generation_id
        self.controller = controller
        
        self.is_running = True
        self.pause_event = threading.Event()
        self.pause_event.set()
        
        # P0 Interruptible Event
        self._interrupt_sleep_event = threading.Event()
        
        # P0 Readiness Handshake
        self.is_ready_event = threading.Event()

        self.queue: queue.Queue = queue.Queue(maxsize=MAX_GLOBAL_QUEUE)
        self.paused_pattern_queues: Dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_PATTERN_QUEUE))
        self.paused_patterns: Set[str] = set()
        self.cancelled_patterns: Set[str] = set()
        self.paused_lock = threading.RLock()
        
        self.retry_manager = RetryHeapManager(max_capacity=MAX_RETRY_QUEUE)
        self.retry_lock = self.retry_manager.lock
        self.retry_queue = self.retry_manager.heap
        
        self.verification_mode = VerificationMode.SMART
        self.start_time = time.time()
        self.last_heartbeat_monotonic = time.monotonic()
        self.last_scan_monotonic = time.monotonic()
        self.last_success_monotonic = time.monotonic()
        self.last_completed_job_monotonic = time.monotonic()
        
        self.worker_jobs_completed = 0
        self.worker_busy_time_sec = 0.0
        self.worker_idle_time_sec = 0.0
        self.worker_last_activity_monotonic = time.monotonic()

    def is_stale_generation(self) -> bool:
        """P0 Fencing Token Guard: Detects if this worker was superseded by a newer generation."""
        if self.controller is not None and hasattr(self.controller, 'current_worker_generation'):
            return self.generation_id != self.controller.current_worker_generation
        return False

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self.is_ready_event.wait(timeout=timeout)

    def add_to_queue(self, username: str, pattern_id: str = "", source: JobSource = JobSource.PATTERN, timeout: float = 2.0) -> bool:
        job = Job.create_new(username=username, pattern_id=pattern_id, source=source, generation_id=self.generation_id)
        if self.db:
            persisted = self.db.save_pending_job(job, wait_for_commit=True)
            if not persisted:
                return False
        return self.add_job_direct(job, timeout=timeout)

    def add_job_direct(self, job: Job, timeout: float = 2.0, persist_if_new: bool = False) -> bool:
        job.generation_id = self.generation_id
        if persist_if_new and self.db:
            persisted = self.db.save_pending_job(job, wait_for_commit=True)
            if not persisted:
                return False

        with self.paused_lock:
            if job.pattern_id in self.paused_patterns:
                if len(self.paused_pattern_queues[job.pattern_id]) >= MAX_PATTERN_QUEUE:
                    return False
                self.paused_pattern_queues[job.pattern_id].append(job)
                self._update_paused_metrics()
                return True

        try:
            self.queue.put(job, block=True, timeout=timeout)
            return True
        except queue.Full:
            return False

    def _update_paused_metrics(self):
        total_depth = 0
        oldest_age = 0.0
        now = time.monotonic()
        for q in self.paused_pattern_queues.values():
            total_depth += len(q)
            if q:
                age = now - q[0].created_monotonic
                if age > oldest_age:
                    oldest_age = age
        METRICS.record_paused_patterns_state(total_depth, oldest_age)

    def _drain_unpaused_patterns(self):
        with self.paused_lock:
            if not self.paused_pattern_queues:
                return

            unpaused_ids = [pid for pid in self.paused_pattern_queues.keys() if pid not in self.paused_patterns]
            for pid in unpaused_ids:
                parked = self.paused_pattern_queues[pid]
                while parked and not self.queue.full():
                    job = parked.popleft()
                    try:
                        self.queue.put_nowait(job)
                    except queue.Full:
                        parked.appendleft(job)
                        break
                if not parked:
                    del self.paused_pattern_queues[pid]

            self._update_paused_metrics()

    def get_oldest_queue_age_sec(self) -> float:
        try:
            with self.queue.mutex:
                if self.queue.queue:
                    oldest_job: Job = self.queue.queue[0]
                    return time.monotonic() - oldest_job.created_monotonic
            return 0.0
        except Exception:
            return 0.0

    def pause_pattern(self, pattern_id: str):
        with self.paused_lock:
            self.paused_patterns.add(pattern_id)
            self._update_paused_metrics()

    def resume_pattern(self, pattern_id: str):
        with self.paused_lock:
            self.paused_patterns.discard(pattern_id)
            self._drain_unpaused_patterns()

    def remove_pattern(self, pattern_id: str) -> int:
        cancelled_count = 0
        with self.paused_lock:
            self.paused_patterns.discard(pattern_id)
            self.cancelled_patterns.add(pattern_id)
            
            if pattern_id in self.paused_pattern_queues:
                parked = self.paused_pattern_queues.pop(pattern_id)
                while parked:
                    job = parked.popleft()
                    job.mark_cancelled("PATTERN_REMOVED")
                    cancelled_count += 1
            self._update_paused_metrics()

        if self.db:
            db_cleaned = self.db.delete_pending_jobs_by_pattern(pattern_id)
            cancelled_count = max(cancelled_count, db_cleaned)

        self.sig_log.emit(f"🗑️ Pattern '{pattern_id}' removed: Cancelled {cancelled_count:,} associated jobs.")
        return cancelled_count

    def get_queue_len(self) -> int:
        return self.queue.qsize()

    def run(self):
        self.start_time = time.time()
        self.is_ready_event.set()
        
        while self.is_running:
            # P0 Fencing Token Gate: Zombie workers terminate immediately
            if self.is_stale_generation():
                logger.warning(f"🛑 Fencing Token Triggered: ScannerWorker Gen #{self.generation_id} is STALE. Terminating zombie loop.")
                break

            loop_start_t = time.monotonic()
            active_job: Optional[Job] = None
            from_main_queue = False
            username = ""

            try:
                self.pause_event.wait()
                if not self.is_running or self.is_stale_generation():
                    break

                self.last_heartbeat_monotonic = time.monotonic()
                now = time.monotonic()

                # P0 Background Anti-Starvation Drain
                self._drain_unpaused_patterns()

                # DB Failure & Writer Backpressure Yield
                if self.writer.get_queue_len() >= (MAX_WRITER_QUEUE - 1000) or self.writer.db_degraded:
                    self._interrupt_sleep_event.wait(timeout=0.05)
                    self._interrupt_sleep_event.clear()
                    self.worker_idle_time_sec += time.monotonic() - loop_start_t
                    continue

                # 1. Pop from Retry Heap
                ready_retry = self.retry_manager.pop_ready(now)
                if ready_retry:
                    active_job = ready_retry
                    from_main_queue = False

                # 2. Pop from Main Scanner Queue
                if not active_job:
                    try:
                        active_job = self.queue.get(block=True, timeout=0.1)
                        from_main_queue = True
                    except queue.Empty:
                        pass

                if not active_job:
                    self.worker_idle_time_sec += time.monotonic() - loop_start_t
                    self._interrupt_sleep_event.wait(timeout=0.02)
                    self._interrupt_sleep_event.clear()
                    continue

                self.worker_last_activity_monotonic = time.monotonic()
                username = active_job.username

                # P0 Guard: Queue Wait Deadline
                if from_main_queue and active_job.is_queue_expired():
                    active_job.mark_permanent_failure(
                        error_msg=f"Job exceeded max queue wait deadline ({MAX_QUEUE_WAIT_SEC}s)",
                        category=ErrorCategory.TIMEOUT,
                        reason=DeadLetterReason.QUEUE_DEADLINE_EXCEEDED
                    )
                    self.db.save_dead_letter(
                        job_id=active_job.job_id,
                        username=active_job.username,
                        error_msg=active_job.last_error,
                        attempts=active_job.attempt,
                        reason=DeadLetterReason.QUEUE_DEADLINE_EXCEEDED,
                        category=ErrorCategory.TIMEOUT.value,
                        correlation_id=active_job.correlation_id,
                        wait_for_commit=True
                    )
                    self.sig_log.emit(f"[{active_job.correlation_id}] ❌ @{active_job.username} Exceeded Queue Wait Deadline → DLQ")
                    continue

                # P0 Guard: Absolute Lifecycle Deadline
                if active_job.is_lifecycle_expired():
                    active_job.mark_permanent_failure(
                        error_msg=f"Job exceeded absolute lifecycle deadline ({MAX_JOB_LIFECYCLE_SEC}s)",
                        category=ErrorCategory.TIMEOUT,
                        reason=DeadLetterReason.ABSOLUTE_LIFECYCLE_EXCEEDED
                    )
                    self.db.save_dead_letter(
                        job_id=active_job.job_id,
                        username=active_job.username,
                        error_msg=active_job.last_error,
                        attempts=active_job.attempt,
                        reason=DeadLetterReason.ABSOLUTE_LIFECYCLE_EXCEEDED,
                        category=ErrorCategory.TIMEOUT.value,
                        correlation_id=active_job.correlation_id,
                        wait_for_commit=True
                    )
                    self.sig_log.emit(f"[{active_job.correlation_id}] ❌ @{active_job.username} Exceeded Absolute Lifecycle Deadline → DLQ")
                    continue

                # P0 Guard: Retry Age and Runtime Deadlines
                if not from_main_queue:
                    if active_job.first_failure_monotonic and (time.monotonic() - active_job.first_failure_monotonic) > MAX_RETRY_AGE_SEC:
                        active_job.mark_permanent_failure(
                            error_msg=f"Job exceeded max retry age ({MAX_RETRY_AGE_SEC}s)",
                            category=ErrorCategory.TIMEOUT,
                            reason=DeadLetterReason.RETRY_AGE_EXCEEDED
                        )
                        self.db.save_dead_letter(
                            job_id=active_job.job_id,
                            username=active_job.username,
                            error_msg=active_job.last_error,
                            attempts=active_job.attempt,
                            reason=DeadLetterReason.RETRY_AGE_EXCEEDED,
                            category=ErrorCategory.TIMEOUT.value,
                            correlation_id=active_job.correlation_id,
                            wait_for_commit=True
                        )
                        self.sig_log.emit(f"[{active_job.correlation_id}] ❌ @{active_job.username} Exceeded Max Retry Age → DLQ")
                        continue

                    if active_job.is_execution_expired():
                        active_job.mark_permanent_failure(
                            error_msg=f"Job exceeded active execution deadline ({MAX_JOB_RUNTIME_SEC}s)",
                            category=ErrorCategory.TIMEOUT,
                            reason=DeadLetterReason.JOB_DEADLINE_EXCEEDED
                        )
                        self.db.save_dead_letter(
                            job_id=active_job.job_id,
                            username=active_job.username,
                            error_msg=active_job.last_error,
                            attempts=active_job.attempt,
                            reason=DeadLetterReason.JOB_DEADLINE_EXCEEDED,
                            category=ErrorCategory.TIMEOUT.value,
                            correlation_id=active_job.correlation_id,
                            wait_for_commit=True
                        )
                        self.sig_log.emit(f"[{active_job.correlation_id}] ❌ @{active_job.username} Exceeded Active Execution Deadline → DLQ")
                        continue

                # P0 Guard: Cancelled Patterns
                with self.paused_lock:
                    if active_job.pattern_id in self.cancelled_patterns:
                        active_job.mark_cancelled("PATTERN_REMOVED")
                        if self.db and active_job.job_id:
                            self.db.delete_pending_job(active_job.job_id)
                        continue

                # P0 Guard: Paused Patterns
                with self.paused_lock:
                    if active_job.pattern_id in self.paused_patterns:
                        if len(self.paused_pattern_queues[active_job.pattern_id]) < MAX_PATTERN_QUEUE:
                            self.paused_pattern_queues[active_job.pattern_id].append(active_job)
                            self._update_paused_metrics()
                        else:
                            active_job.mark_permanent_failure(
                                error_msg="Pattern paused queue overflow",
                                category=ErrorCategory.PROGRAMMING_ERROR,
                                reason=DeadLetterReason.QUEUE_FULL
                            )
                            self.db.save_dead_letter(
                                job_id=active_job.job_id,
                                username=active_job.username,
                                error_msg=active_job.last_error,
                                attempts=active_job.attempt,
                                reason=DeadLetterReason.QUEUE_FULL,
                                category="QUEUE_OVERFLOW",
                                correlation_id=active_job.correlation_id,
                                wait_for_commit=True
                            )
                        continue

                active_job.mark_in_flight()

                # Deduplication Check
                scan_check = self.db.is_scanned(username)
                if scan_check == ScanCheckResult.DB_UNAVAILABLE:
                    active_job.mark_retryable(error_msg="Database unavailable during scan check", category=ErrorCategory.DB_ERROR)
                    retry_at_m = time.monotonic() + 1.0
                    retry_at_epoch = time.time() + 1.0
                    
                    persisted = self.db.update_pending_job_retry_state(active_job, retry_at_epoch, wait_for_commit=True)
                    if persisted:
                        pushed = self.retry_manager.push(retry_at_m, active_job)
                        if pushed:
                            METRICS.retry_enqueued += 1
                        else:
                            active_job.mark_permanent_failure(
                                error_msg="Retry Queue overflow during DB unavailable retry",
                                category=ErrorCategory.DB_ERROR,
                                reason=DeadLetterReason.RETRY_QUEUE_OVERFLOW
                            )
                            self.db.save_dead_letter(
                                job_id=active_job.job_id,
                                username=username,
                                error_msg=active_job.last_error,
                                attempts=active_job.attempt,
                                reason=DeadLetterReason.RETRY_QUEUE_OVERFLOW,
                                category="DB_ERROR",
                                correlation_id=active_job.correlation_id,
                                wait_for_commit=True
                            )
                    continue
                elif scan_check == ScanCheckResult.FOUND:
                    active_job.mark_completed()
                    if self.db and active_job.job_id:
                        self.db.delete_pending_job(active_job.job_id)
                    self.worker_jobs_completed += 1
                    continue

                registered_job_id = self.inflight.register(
                    username, job_id=active_job.job_id, correlation_id=active_job.correlation_id, pattern_id=active_job.pattern_id, attempt=active_job.attempt
                )
                if not registered_job_id:
                    continue

                queue_wait_ms = (time.monotonic() - active_job.created_monotonic) * 1000
                METRICS.record_queue_wait(queue_wait_ms)

                self.last_scan_monotonic = time.monotonic()
                remaining_deadline = active_job.get_remaining_deadline_sec()
                
                # Check Fencing token before network call
                if self.is_stale_generation():
                    break

                status_code, content, headers, latency, err_category = self.network.fetch(
                    username,
                    correlation_id=active_job.correlation_id,
                    remaining_deadline_sec=remaining_deadline,
                    cancel_event=self._interrupt_sleep_event
                )

                if err_category == ErrorCategory.CIRCUIT_OPEN:
                    self.sig_log.emit(f"[{active_job.correlation_id}] ⚡ Circuit Breaker OPEN → Parking @{username} into retry queue...")
                    retry_at_m = time.monotonic() + 3.0
                    retry_at_epoch = time.time() + 3.0
                    
                    persisted = self.db.update_pending_job_retry_state(active_job, retry_at_epoch, wait_for_commit=True)
                    if persisted:
                        pushed = self.retry_manager.push(retry_at_m, active_job)
                        if not pushed:
                            active_job.mark_permanent_failure(
                                error_msg="Retry Queue overflow during Circuit Breaker cooldown",
                                category=ErrorCategory.CIRCUIT_OPEN,
                                reason=DeadLetterReason.RETRY_QUEUE_OVERFLOW
                            )
                            self.db.save_dead_letter(
                                job_id=active_job.job_id,
                                username=username,
                                error_msg=active_job.last_error,
                                attempts=active_job.attempt,
                                reason=DeadLetterReason.RETRY_QUEUE_OVERFLOW,
                                category="CIRCUIT_OPEN",
                                correlation_id=active_job.correlation_id,
                                wait_for_commit=True
                            )
                    continue

                if status_code == 0 or err_category in [ErrorCategory.TIMEOUT, ErrorCategory.HTTP_5XX, ErrorCategory.HTTP_429, ErrorCategory.RESPONSE_TOO_LARGE]:
                    error_sig = f"{err_category.value}_{status_code}"
                    can_retry, dlq_reason = RetryPolicy.evaluate(active_job, err_category, error_sig)

                    if can_retry:
                        active_job.mark_retryable(error_msg=f"Error: {err_category.value}", category=err_category, error_sig=error_sig)
                        delay_sec = calculate_retry_delay(active_job.attempt)
                        retry_at_m = time.monotonic() + delay_sec
                        retry_at_epoch = time.time() + delay_sec
                        
                        persisted = self.db.update_pending_job_retry_state(active_job, retry_at_epoch, wait_for_commit=True)
                        
                        if persisted:
                            pushed = self.retry_manager.push(retry_at_m, active_job)
                            if pushed:
                                METRICS.retry_enqueued += 1
                                self.sig_log.emit(f"[{active_job.correlation_id}] ⚠ Transient Failure @{username} [{err_category.value}] → Retry {active_job.attempt}/3 (Delay: {delay_sec:.1f}s, Budget: {active_job.retry_budget})")
                            else:
                                active_job.mark_permanent_failure(
                                    error_msg="Retry Queue capacity overflow",
                                    category=err_category,
                                    reason=DeadLetterReason.RETRY_QUEUE_OVERFLOW
                                )
                                self.db.save_dead_letter(
                                    job_id=active_job.job_id,
                                    username=username,
                                    error_msg=active_job.last_error,
                                    attempts=active_job.attempt,
                                    reason=DeadLetterReason.RETRY_QUEUE_OVERFLOW,
                                    category=err_category.value,
                                    correlation_id=active_job.correlation_id,
                                    wait_for_commit=True
                                )
                        else:
                            active_job.mark_permanent_failure(
                                error_msg="Failed to persist retry state to DB",
                                category=ErrorCategory.DB_ERROR,
                                reason=DeadLetterReason.DB_FAILURE
                            )
                            self.db.save_dead_letter(
                                job_id=active_job.job_id,
                                username=username,
                                error_msg=active_job.last_error,
                                attempts=active_job.attempt,
                                reason=DeadLetterReason.DB_FAILURE,
                                category="DB_ERROR",
                                correlation_id=active_job.correlation_id,
                                wait_for_commit=True
                            )
                    else:
                        active_job.mark_permanent_failure(
                            error_msg=f"Exhausted retry allowance. Last error: {err_category.value}",
                            category=err_category,
                            reason=dlq_reason or DeadLetterReason.MAX_RETRIES_EXCEEDED
                        )
                        if dlq_reason == DeadLetterReason.POISON_JOB:
                            METRICS.poison_jobs_count += 1
                            self.sig_log.emit(f"[{active_job.correlation_id}] ☠️ Poison Job Detected @{username} (Signature: {error_sig}) → Escalated to DLQ")
                        else:
                            METRICS.retry_exhausted += 1
                            self.sig_log.emit(f"[{active_job.correlation_id}] ❌ @{username} Retries Exhausted ({dlq_reason.value if dlq_reason else 'EXHAUSTED'}) → DLQ")

                        self.db.save_dead_letter(
                            job_id=active_job.job_id,
                            username=username,
                            error_msg=active_job.last_error,
                            attempts=active_job.attempt,
                            reason=dlq_reason or DeadLetterReason.MAX_RETRIES_EXCEEDED,
                            category=err_category.value,
                            correlation_id=active_job.correlation_id,
                            wait_for_commit=True
                        )
                    continue

                if active_job.attempt > 0:
                    METRICS.retry_success += 1

                status, conf, price, reason, detail, parse_category = FragmentParser.parse_html(content, username, correlation_id=active_job.correlation_id)
                self.last_success_monotonic = time.monotonic()
                active_job.mark_result_ready()
                METRICS.record_target_scanned(status.value)

                # SMART Verification Strategy
                if ScannerPolicy.should_verify_smart(self.verification_mode, status):
                    self._interrupt_sleep_event.wait(timeout=0.15)
                    self._interrupt_sleep_event.clear()
                    if not self.is_running or self.is_stale_generation():
                        active_job.mark_cancelled("ENGINE_STOPPING")
                        break

                    _, c2, _, _, _ = self.network.fetch(
                        username,
                        correlation_id=active_job.correlation_id,
                        remaining_deadline_sec=active_job.get_remaining_deadline_sec(),
                        cancel_event=self._interrupt_sleep_event
                    )
                    status2, _, price2, _, detail2, _ = FragmentParser.parse_html(c2, username, correlation_id=active_job.correlation_id)
                    if status2 == FragmentStatus.AVAILABLE:
                        status = status2
                        price = price2 or price
                        detail = detail2 or detail

                # P0 Fencing Stamp: Attach worker generation ID to payload
                record = {
                    "raw_username": username,
                    "username": f"@{username}",
                    "status": status.value,
                    "confidence": conf,
                    "price": price,
                    "detail": detail,
                    "latency": f"{int(latency)}ms",
                    "time": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
                    "pat_id": active_job.pattern_id,
                    "job_id": active_job.job_id,
                    "correlation_id": active_job.correlation_id,
                    "worker_generation": self.generation_id,
                    "idempotency_key": active_job.idempotency_key,
                    "_job_obj": active_job
                }

                # Discard if worker became stale while parsing
                if self.is_stale_generation():
                    logger.warning(f"🛑 Fencing Token: Discarding result for @{username} from Stale Gen #{self.generation_id}.")
                    break

                active_job.mark_persist_pending()
                enqueued = self.writer.enqueue_result(record, timeout=2.0)
                while not enqueued and self.is_running and not self.is_stale_generation():
                    self._interrupt_sleep_event.wait(timeout=0.05)
                    self._interrupt_sleep_event.clear()
                    enqueued = self.writer.enqueue_result(record, timeout=2.0)

                if enqueued:
                    self.last_completed_job_monotonic = time.monotonic()
                    self.worker_jobs_completed += 1
                else:
                    active_job.mark_cancelled("WRITER_UNAVAILABLE_ON_SHUTDOWN")
                    self.sig_log.emit(f"[{active_job.correlation_id}] ⚠️ Result for @{username} preserved in DB checkpoint; writer stopped.")

            except Exception as e:
                logger.exception(f"Unhandled Exception in ScannerWorker loop: {e}")
                self.sig_log.emit(f"⚠️ Scanner Loop Recovered from Exception: {e}")
                self._interrupt_sleep_event.wait(timeout=0.5)
                self._interrupt_sleep_event.clear()

            finally:
                if username:
                    self.inflight.unregister(username)
                
                if from_main_queue:
                    try:
                        self.queue.task_done()
                    except Exception:
                        pass
                
                self.worker_busy_time_sec += time.monotonic() - loop_start_t

                delay = self.network.get_jittered_delay()
                self._interrupt_sleep_event.wait(timeout=delay)
                self._interrupt_sleep_event.clear()
                if not self.is_running or self.is_stale_generation():
                    break

    def pause(self):
        self.pause_event.clear()
        self._interrupt_sleep_event.set()

    def resume(self):
        self.pause_event.set()

    def stop(self):
        self.is_running = False
        self.pause_event.set()
        self._interrupt_sleep_event.set()