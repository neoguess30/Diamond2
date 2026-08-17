from __future__ import annotations
import time
import threading
from datetime import datetime, timezone
from typing import List, Any

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

from core.models.job import Job
from core.state.enums import JobSource
from core.config import PRODUCER_MAX_BLOCK_SEC
from parser.pattern_generator import LazyPatternGenerator
from persistence.database import ConsolidatedDatabaseManager

class PatternProducerWorker(QThread):
    sig_log = pyqtSignal(str)

    def __init__(self, pattern: str, pattern_id: str, scanner_worker: Any, db: ConsolidatedDatabaseManager):
        super().__init__()
        self.pattern = pattern
        self.pattern_id = pattern_id
        self.scanner = scanner_worker
        self.db = db
        self.is_stopped = False
        self.pause_event = threading.Event()
        self.pause_event.set()

    def pause(self):
        self.pause_event.clear()

    def resume(self):
        self.pause_event.set()

    def stop(self):
        self.is_stopped = True
        self.pause_event.set()

    def _persist_batch_with_backpressure(self, batch_jobs: List[Job]) -> bool:
        """
        Durability Barrier (P0): Retries saving the batch to DB with backoff.
        Guarantees that jobs NEVER enter memory queue unless persisted to DB first.
        """
        retry_count = 0
        blocked_start_monotonic = time.monotonic()

        while not self.is_stopped:
            self.pause_event.wait()
            if self.is_stopped:
                return False

            persisted = self.db.save_pending_jobs_batch(batch_jobs, wait_for_commit=True)
            if persisted:
                return True

            retry_count += 1
            elapsed_blocked = time.monotonic() - blocked_start_monotonic
            if elapsed_blocked >= PRODUCER_MAX_BLOCK_SEC:
                self.sig_log.emit(
                    f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  🚨 DB Persistence Timeout ({PRODUCER_MAX_BLOCK_SEC}s) → Pausing Producer '{self.pattern}'"
                )
                self.pause()
                blocked_start_monotonic = time.monotonic()
                continue

            if retry_count % 5 == 0:
                self.sig_log.emit(
                    f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  ⚠️ DB Persistence Backpressure: Retrying batch save for '{self.pattern}' (Attempt {retry_count})..."
                )

            # Exponential backoff capped at 2.0s
            backoff = min(2.0, 0.05 * (1.5 ** min(retry_count, 6)))
            time.sleep(backoff)

        return False

    def run(self):
        count = LazyPatternGenerator.calculate_possibilities(self.pattern)
        self.sig_log.emit(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  ✓ Registered task '{self.pattern}' ({count:,} candidates)")
        
        batch_jobs: List[Job] = []
        for uname in LazyPatternGenerator.generate_stream(self.pattern):
            if self.is_stopped:
                break

            self.pause_event.wait()
            if self.is_stopped:
                break
                
            job = Job.create_new(username=uname, pattern_id=self.pattern_id, source=JobSource.PATTERN)
            batch_jobs.append(job)
            
            if len(batch_jobs) >= 50:
                # P0 Durability Gate: Persist batch FIRST. Only proceed if 100% saved in DB.
                persisted = self._persist_batch_with_backpressure(batch_jobs)
                if not persisted:
                    break

                for j in batch_jobs:
                    self.pause_event.wait()
                    if self.is_stopped:
                        break
                    enqueued = self.scanner.add_job_direct(j, timeout=1.0)
                    blocked_start_monotonic = time.monotonic()
                    while not enqueued and not self.is_stopped:
                        self.pause_event.wait()
                        if self.is_stopped:
                            break
                        if time.monotonic() - blocked_start_monotonic >= PRODUCER_MAX_BLOCK_SEC:
                            self.sig_log.emit(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  🚨 Producer Block Deadline Exceeded → Pausing Producer '{self.pattern}'")
                            self.pause()
                            break
                        enqueued = self.scanner.add_job_direct(j, timeout=1.0)
                batch_jobs.clear()

        # Flush remaining jobs with strict persistence guarantee
        if batch_jobs and not self.is_stopped:
            persisted = self._persist_batch_with_backpressure(batch_jobs)
            if persisted:
                for j in batch_jobs:
                    self.scanner.add_job_direct(j, timeout=1.0)
            batch_jobs.clear()