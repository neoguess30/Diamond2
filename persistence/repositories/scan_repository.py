from __future__ import annotations
import time
import sqlite3
from typing import List, Tuple, Optional

from core.config import (
    DB_BUSY_TIMEOUT_MS,
    DB_SYNCHRONOUS_MODE,
    DB_TEMP_STORE,
    DB_READER_CACHE_KIB
)
from core.state.enums import ScanCheckResult, JobSource, JobStatus
from core.models.job import Job
from core.logger import logger
from persistence.lru_cache import BoundedLRUCache

class ScanRepository:
    """Manages high-throughput lock-free read-only SQLite connections with WAL mode."""
    def __init__(self, db_path: str, lru_cache: BoundedLRUCache):
        self.db_path = db_path
        self.lru_cache = lru_cache

    def _get_read_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=DB_BUSY_TIMEOUT_MS / 1000.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(f"PRAGMA synchronous={DB_SYNCHRONOUS_MODE};")
        conn.execute(f"PRAGMA temp_store={DB_TEMP_STORE};")
        conn.execute(f"PRAGMA cache_size={DB_READER_CACHE_KIB};")
        conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
        conn.execute("PRAGMA query_only=ON;")
        return conn

    def is_scanned(self, username: str) -> ScanCheckResult:
        uname = username.lower().strip().replace("@", "")
        cached = self.lru_cache.get(uname)
        if cached is True:
            return ScanCheckResult.FOUND

        try:
            conn = self._get_read_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM scan_results WHERE username = ? LIMIT 1;", (uname,))
                exists = cur.fetchone() is not None
                if exists:
                    self.lru_cache.put(uname, True)
                    return ScanCheckResult.FOUND
                return ScanCheckResult.NOT_FOUND
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Database Query Error for @{uname}: {e}")
            return ScanCheckResult.DB_UNAVAILABLE

    def get_total_count(self) -> int:
        try:
            conn = self._get_read_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(1) FROM scan_results;")
                row = cur.fetchone()
                return row[0] if row else 0
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Database Count Error: {e}")
            return 0

    def get_dead_letter_count(self) -> int:
        try:
            conn = self._get_read_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(1) FROM dead_jobs;")
                row = cur.fetchone()
                return row[0] if row else 0
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Dead letter count error: {e}")
            return 0

    def load_dead_jobs(self, limit: int = 1000) -> List[Tuple[str, str, str, int, str, str]]:
        jobs = []
        try:
            conn = self._get_read_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT job_id, username, error, attempts, reason, correlation_id FROM dead_jobs ORDER BY last_attempt DESC LIMIT ?;", (limit,))
                jobs = cur.fetchall()
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Error loading dead jobs: {e}")
        return jobs

    def recover_abandoned_jobs_on_startup(self) -> List[Job]:
        """Restores uncompleted jobs preserving exact attempt counts, retry budgets, retry_at schedule, and error signatures."""
        recovered_jobs: List[Job] = []
        try:
            conn = self._get_read_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT job_id, username, pattern_id, source, attempt, retry_budget, error_signature, first_failure_epoch, last_error, correlation_id, status, retry_at_epoch
                    FROM pending_jobs 
                    WHERE status IN ('QUEUED', 'IN_PROGRESS', 'IN_FLIGHT', 'SCANNED', 'PERSIST_PENDING', 'RETRYABLE') 
                    LIMIT 10000;
                """)
                rows = cur.fetchall()
                now_monotonic = time.monotonic()
                now_epoch = time.time()

                for r in rows:
                    src_enum = JobSource.PATTERN
                    try:
                        src_enum = JobSource(r[3])
                    except Exception:
                        src_enum = JobSource.RECOVERY

                    st_enum = JobStatus.QUEUED
                    try:
                        st_enum = JobStatus(r[10])
                    except Exception:
                        st_enum = JobStatus.QUEUED

                    first_fail_epoch = r[7] if (r[7] is not None and r[7] > 0) else None
                    first_fail_monotonic = None
                    if first_fail_epoch:
                        elapsed_since_fail = max(0.0, now_epoch - first_fail_epoch)
                        first_fail_monotonic = now_monotonic - elapsed_since_fail

                    retry_at_epoch = r[11] if (r[11] is not None) else 0.0

                    job = Job(
                        job_id=r[0],
                        username=r[1],
                        pattern_id=r[2] or "",
                        source=src_enum,
                        attempt=r[4] if r[4] is not None else 0,
                        retry_budget=r[5] if r[5] is not None else 6,
                        error_signature=r[6] or "",
                        first_failure_monotonic=first_fail_monotonic,
                        last_error=r[8] or "",
                        correlation_id=r[9] or "",
                        status=st_enum,
                        retry_at_epoch=retry_at_epoch,
                        created_monotonic=now_monotonic
                    )
                    recovered_jobs.append(job)
                if recovered_jobs:
                    logger.info(f"⚡ Startup Recovery: Restored {len(recovered_jobs):,} jobs with durable retry states.")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Error recovering abandoned jobs on startup: {e}")
        return recovered_jobs