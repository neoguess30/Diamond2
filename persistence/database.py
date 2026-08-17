from __future__ import annotations
import os
import sqlite3
import threading
import uuid
import time
from datetime import datetime, timezone
from typing import Tuple, List, Optional, Any

from core.config import (
    DB_BUSY_TIMEOUT_MS,
    DB_SYNCHRONOUS_MODE,
    DB_TEMP_STORE,
    DB_READER_CACHE_KIB,
    DISK_CRITICAL_GB,
    WAL_CRITICAL_MB,
    WAL_WARNING_MB,
    HEALTH_SNAPSHOT_RETENTION_DAYS,
    DEAD_LETTER_RETENTION_DAYS
)
from core.state.enums import (
    DatabaseHealthState,
    DiskHealthState,
    ScanCheckResult,
    JobStatus
)
from core.errors.categories import DeadLetterReason, ErrorCategory
from core.metrics import METRICS
from core.models.job import Job
from core.utils import (
    get_free_disk_space_gb,
    get_file_size_mb,
    get_disk_health_state,
    get_process_memory_mb,
    get_real_desktop_path
)
from core.logger import logger
from persistence.lru_cache import BoundedLRUCache
from persistence.repositories.scan_repository import ScanRepository

class ConsolidatedDatabaseManager:
    """Consolidated Database Engine with Automated Telemetry Retention, Pruning & WAL Checkpointing."""
    def __init__(self, db_path: str = "falcon_master.db"):
        self.db_path = db_path
        self.lock = threading.RLock()
        self.writer: Any = None
        self.lru_cache = BoundedLRUCache()
        self.repo = ScanRepository(db_path, self.lru_cache)
        self.session_id = f"session_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self._health_state: DatabaseHealthState = DatabaseHealthState.HEALTHY
        self._consecutive_read_errors: int = 0
        self._consecutive_write_errors: int = 0
        self._last_error: str = ""
        
        self._cached_disk_health: DiskHealthState = DiskHealthState.HEALTHY
        self._last_disk_check_monotonic: float = 0.0
        self._disk_check_ttl_sec: float = 3.0

        self._init_db()
        self._record_session_startup()

    @property
    def health_state(self) -> DatabaseHealthState:
        return self._health_state

    @property
    def db_degraded(self) -> bool:
        return self._health_state != DatabaseHealthState.HEALTHY

    def get_health_state(self) -> DatabaseHealthState:
        return self._health_state

    def is_degraded(self) -> bool:
        return self._health_state != DatabaseHealthState.HEALTHY

    def set_health_state(self, state: DatabaseHealthState, reason: str = ""):
        with self.lock:
            old_state = self._health_state
            self._health_state = state
            if reason:
                self._last_error = reason
            if old_state != state:
                logger.warning(f"Database Health State transition: {old_state.value} -> {state.value} (Reason: {reason})")

    def report_read_success(self):
        with self.lock:
            self._consecutive_read_errors = 0
            if self._health_state != DatabaseHealthState.HEALTHY and self._consecutive_write_errors == 0:
                self.set_health_state(DatabaseHealthState.HEALTHY, "Read operation succeeded")

    def report_read_failure(self, error: str):
        with self.lock:
            self._consecutive_read_errors += 1
            new_st = DatabaseHealthState.UNAVAILABLE if self._consecutive_read_errors >= 3 else DatabaseHealthState.DEGRADED
            self.set_health_state(new_st, f"Read failure #{self._consecutive_read_errors}: {error}")

    def report_write_success(self):
        with self.lock:
            self._consecutive_write_errors = 0
            if self._health_state != DatabaseHealthState.HEALTHY and self._consecutive_read_errors == 0:
                self.set_health_state(DatabaseHealthState.HEALTHY, "Write commit succeeded")

    def report_write_failure(self, error: str, fatal: bool = False):
        with self.lock:
            self._consecutive_write_errors += 1
            new_st = DatabaseHealthState.UNAVAILABLE if (fatal or self._consecutive_write_errors >= 3) else DatabaseHealthState.DEGRADED
            self.set_health_state(new_st, f"Write failure #{self._consecutive_write_errors} (fatal={fatal}): {error}")

    def set_writer(self, writer: Any):
        self.writer = writer

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=DB_BUSY_TIMEOUT_MS / 1000.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(f"PRAGMA synchronous={DB_SYNCHRONOUS_MODE};")
        conn.execute(f"PRAGMA temp_store={DB_TEMP_STORE};")
        conn.execute(f"PRAGMA cache_size={DB_READER_CACHE_KIB};")
        conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
        return conn

    def _init_db(self):
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS scan_results (
                            username TEXT PRIMARY KEY,
                            status TEXT NOT NULL,
                            confidence REAL,
                            price TEXT,
                            detail TEXT,
                            pattern_id TEXT,
                            result_sequence INTEGER,
                            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_scan_results_username ON scan_results(username);")
                    
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS dead_jobs (
                            job_id TEXT PRIMARY KEY,
                            username TEXT NOT NULL,
                            correlation_id TEXT,
                            error TEXT,
                            attempts INTEGER,
                            reason TEXT,
                            failure_category TEXT,
                            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            last_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_dead_jobs_lookup ON dead_jobs(username, last_attempt);")

                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS pending_jobs (
                            job_id TEXT PRIMARY KEY,
                            username TEXT NOT NULL,
                            correlation_id TEXT,
                            pattern_id TEXT,
                            source TEXT DEFAULT 'PATTERN',
                            status TEXT DEFAULT 'QUEUED',
                            attempt INTEGER DEFAULT 0,
                            retry_budget INTEGER DEFAULT 6,
                            error_signature TEXT DEFAULT '',
                            first_failure_epoch REAL DEFAULT 0.0,
                            last_error TEXT DEFAULT '',
                            retry_at_epoch REAL DEFAULT 0.0,
                            enqueued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_recovery ON pending_jobs(status, retry_at_epoch);")
                    
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS runtime_state (
                            session_id TEXT PRIMARY KEY,
                            started_at TIMESTAMP,
                            stopped_at TIMESTAMP,
                            status TEXT,
                            last_username TEXT,
                            last_error TEXT
                        );
                    """)

                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS health_snapshots (
                            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                            session_id TEXT NOT NULL,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            requests INTEGER,
                            successful_requests INTEGER,
                            http_429 INTEGER,
                            http_5xx INTEGER,
                            timeouts INTEGER,
                            dead_letters INTEGER,
                            poison_jobs INTEGER,
                            jobs_persisted INTEGER,
                            queue_depth INTEGER,
                            oldest_queue_age_sec REAL,
                            ram_mb REAL,
                            ram_slope_mb_hr REAL,
                            threads_count INTEGER,
                            handles_count INTEGER,
                            db_size_mb REAL,
                            wal_size_mb REAL
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_health_snapshots_timestamp ON health_snapshots(timestamp);")
                    conn.commit()

                    cur = conn.cursor()
                    cur.execute("PRAGMA table_info(scan_results);")
                    scan_cols = {row[1] for row in cur.fetchall()}
                    if "pattern_id" not in scan_cols:
                        conn.execute("ALTER TABLE scan_results ADD COLUMN pattern_id TEXT;")
                    if "result_sequence" not in scan_cols:
                        conn.execute("ALTER TABLE scan_results ADD COLUMN result_sequence INTEGER;")

                    cur.execute("PRAGMA table_info(pending_jobs);")
                    pending_cols = {row[1] for row in cur.fetchall()}
                    if "source" not in pending_cols:
                        conn.execute("ALTER TABLE pending_jobs ADD COLUMN source TEXT DEFAULT 'PATTERN';")
                    if "status" not in pending_cols:
                        conn.execute("ALTER TABLE pending_jobs ADD COLUMN status TEXT DEFAULT 'QUEUED';")
                    if "attempt" not in pending_cols:
                        conn.execute("ALTER TABLE pending_jobs ADD COLUMN attempt INTEGER DEFAULT 0;")
                    if "retry_budget" not in pending_cols:
                        conn.execute("ALTER TABLE pending_jobs ADD COLUMN retry_budget INTEGER DEFAULT 6;")
                    if "error_signature" not in pending_cols:
                        conn.execute("ALTER TABLE pending_jobs ADD COLUMN error_signature TEXT DEFAULT '';")
                    if "first_failure_epoch" not in pending_cols:
                        conn.execute("ALTER TABLE pending_jobs ADD COLUMN first_failure_epoch REAL DEFAULT 0.0;")
                    if "last_error" not in pending_cols:
                        conn.execute("ALTER TABLE pending_jobs ADD COLUMN last_error TEXT DEFAULT '';")
                    if "retry_at_epoch" not in pending_cols:
                        conn.execute("ALTER TABLE pending_jobs ADD COLUMN retry_at_epoch REAL DEFAULT 0.0;")
                    if "correlation_id" not in pending_cols:
                        conn.execute("ALTER TABLE pending_jobs ADD COLUMN correlation_id TEXT;")

                    cur.execute("PRAGMA table_info(dead_jobs);")
                    dead_cols = {row[1] for row in cur.fetchall()}
                    if "correlation_id" not in dead_cols:
                        conn.execute("ALTER TABLE dead_jobs ADD COLUMN correlation_id TEXT;")

                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            logger.exception(f"Database Initialization/Migration Exception: {e}")
            self.report_write_failure(f"Init exception: {e}", fatal=True)

    def prune_old_dead_letters(self, retention_days: int = DEAD_LETTER_RETENTION_DAYS) -> int:
        """P0 Single Writer Architecture: Routes DLQ pruning through StorageWriter worker."""
        if self.writer and getattr(self.writer, 'is_running', False):
            self.writer.enqueue_action({
                "_type": "PRUNE_DEAD_LETTERS",
                "retention_days": retention_days
            })
            return 0
        pruned_count = 0
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM dead_jobs WHERE last_attempt < datetime('now', ?);", (f'-{retention_days} days',))
                    pruned_count = cur.rowcount
                    conn.commit()
                    if pruned_count > 0:
                        logger.info(f"DatabaseRetention: Pruned {pruned_count} dead letters older than {retention_days} days.")
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"DatabaseRetention: Dead letter pruning error: {e}")
        return pruned_count

    def prune_old_health_snapshots(self, retention_days: int = HEALTH_SNAPSHOT_RETENTION_DAYS) -> int:
        """P0 Single Writer Architecture: Routes health snapshot pruning through StorageWriter worker."""
        if self.writer and getattr(self.writer, 'is_running', False):
            self.writer.enqueue_action({
                "_type": "PRUNE_HEALTH_SNAPSHOTS",
                "retention_days": retention_days
            })
            return 0
        pruned_count = 0
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM health_snapshots WHERE timestamp < datetime('now', ?);", (f'-{retention_days} days',))
                    pruned_count = cur.rowcount
                    conn.commit()
                    if pruned_count > 0:
                        logger.info(f"DatabaseRetention: Pruned {pruned_count} health snapshots older than {retention_days} days.")
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"DatabaseRetention: Health snapshot pruning error: {e}")
        return pruned_count

    def verify_preflight_health(self) -> Tuple[bool, str]:
        free_gb = get_free_disk_space_gb()
        if free_gb < DISK_CRITICAL_GB:
            return False, f"Startup Blocked: Insufficient disk space ({free_gb:.2f} GB free < {DISK_CRITICAL_GB} GB)"

        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.execute("CREATE TABLE IF NOT EXISTS _preflight_test (id INTEGER PRIMARY KEY);")
                    conn.execute("""
                        INSERT INTO _preflight_test (id) VALUES (1)
                        ON CONFLICT(id) DO NOTHING;
                    """)
                    conn.commit()
                    conn.execute("DROP TABLE _preflight_test;")
                    conn.commit()
                finally:
                    conn.close()
        except Exception as dbe:
            return False, f"Startup Blocked: Database read/write verification failed: {dbe}"

        try:
            test_file = get_real_desktop_path() / ".preflight_test.tmp"
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("OK")
            if os.path.exists(test_file):
                os.remove(test_file)
        except Exception as fe:
            return False, f"Startup Blocked: Desktop export directory is not writable: {fe}"

        return True, "PREFLIGHT_ALL_SYSTEMS_OPERATIONAL"

    def run_integrity_check(self) -> Tuple[bool, str]:
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("PRAGMA integrity_check;")
                    rows = cur.fetchall()
                    if rows and rows[0][0] == "ok":
                        logger.info("SQLite integrity check passed: 'ok'")
                        return True, "ok"
                    report = "; ".join([str(r[0]) for r in rows])
                    logger.critical(f"SQLite integrity check failed: {report}")
                    return False, report
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"Error running database integrity check: {e}")
            return False, str(e)

    def backup_database_safe(self, target_backup_path: Optional[str] = None) -> bool:
        if not target_backup_path:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            target_backup_path = f"backup_falcon_master_{timestamp}.db"
        try:
            with self.lock:
                source_conn = self._get_connection()
                try:
                    target_conn = sqlite3.connect(target_backup_path)
                    try:
                        source_conn.backup(target_conn, pages=100, sleep=0.01)
                        logger.info(f"Live online backup completed to '{target_backup_path}'.")
                        return True
                    finally:
                        target_conn.close()
                finally:
                    source_conn.close()
        except Exception as e:
            logger.exception(f"Database Online Backup Exception: {e}")
            return False

    def save_health_snapshot(self, snap: dict, db_mb: float, wal_mb: float):
        if self.writer and getattr(self.writer, 'is_running', False):
            self.writer.enqueue_action({
                "_type": "HEALTH_SNAPSHOT",
                "session_id": self.session_id,
                "snap": snap,
                "db_mb": db_mb,
                "wal_mb": wal_mb,
                "ram_mb": get_process_memory_mb() or 0.0
            })
            return
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.execute("""
                        INSERT INTO health_snapshots (
                            session_id, requests, successful_requests, http_429, http_5xx,
                            timeouts, dead_letters, poison_jobs, jobs_persisted,
                            queue_depth, oldest_queue_age_sec, ram_mb, ram_slope_mb_hr,
                            threads_count, handles_count, db_size_mb, wal_size_mb
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        self.session_id, snap.get("requests", 0), snap.get("success", 0),
                        snap.get("429", 0), snap.get("5xx", 0), snap.get("timeouts", 0),
                        snap.get("dead_letters", 0), snap.get("poison_jobs", 0), snap.get("jobs_persisted", 0),
                        snap.get("q_scanner_peak", 0), snap.get("oldest_age_sec", 0.0), get_process_memory_mb() or 0.0,
                        snap.get("ram_long_slope", 0.0), snap.get("threads_current", 0), snap.get("handles_current", 0),
                        db_mb, wal_mb
                    ))
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            logger.warning(f"Failed to record health snapshot: {e}")

    def _record_session_startup(self):
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT session_id, started_at, last_username, last_error FROM runtime_state WHERE status = 'RUNNING' ORDER BY started_at DESC LIMIT 1;")
                    crashed = cur.fetchone()
                    if crashed:
                        logger.warning(f"⚠️ Crash Recovery Journal: Detected abnormal termination of session '{crashed[0]}'")
                        conn.execute("UPDATE runtime_state SET status = 'ABNORMAL_TERMINATION' WHERE session_id = ?;", (crashed[0],))

                    conn.execute("""
                        INSERT INTO runtime_state (session_id, started_at, status, last_username, last_error)
                        VALUES (?, CURRENT_TIMESTAMP, 'RUNNING', '', '')
                        ON CONFLICT(session_id) DO UPDATE SET
                            started_at = CURRENT_TIMESTAMP,
                            status = 'RUNNING';
                    """, (self.session_id,))
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"Error recording session startup: {e}")

    def record_session_clean_shutdown(self):
        if self.writer and getattr(self.writer, 'is_running', False):
            self.writer.enqueue_action({
                "_type": "CLEAN_SHUTDOWN",
                "session_id": self.session_id
            })
            return
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.execute("UPDATE runtime_state SET stopped_at = CURRENT_TIMESTAMP, status = 'CLEAN_SHUTDOWN' WHERE session_id = ?;", (self.session_id,))
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"Error recording clean shutdown: {e}")

    def update_session_journal(self, last_username: str, last_error: str = ""):
        if self.writer and getattr(self.writer, 'is_running', False):
            self.writer.enqueue_action({
                "_type": "SESSION_JOURNAL",
                "session_id": self.session_id,
                "last_username": last_username,
                "last_error": last_error
            })
            return
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.execute("UPDATE runtime_state SET last_username = ?, last_error = ? WHERE session_id = ?;", (last_username, last_error, self.session_id))
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            logger.warning(f"Failed to update runtime journal: {e}")

    def check_disk_health(self, force: bool = False) -> DiskHealthState:
        now = time.monotonic()
        if force or (now - self._last_disk_check_monotonic >= self._disk_check_ttl_sec):
            self._cached_disk_health = get_disk_health_state()
            self._last_disk_check_monotonic = now
        return self._cached_disk_health

    def get_db_file_sizes_mb(self) -> Tuple[float, float]:
        db_mb = get_file_size_mb(self.db_path)
        wal_mb = get_file_size_mb(f"{self.db_path}-wal")
        if wal_mb >= WAL_CRITICAL_MB:
            logger.critical(f"WAL Size Critical: {wal_mb:.1f} MB")
        elif wal_mb >= WAL_WARNING_MB:
            logger.warning(f"WAL Size Warning: {wal_mb:.1f} MB")
        return db_mb, wal_mb

    def is_scanned(self, username: str) -> ScanCheckResult:
        res = self.repo.is_scanned(username)
        if res == ScanCheckResult.DB_UNAVAILABLE:
            self.report_read_failure("Query error")
        else:
            self.report_read_success()
        return res

    def mark_scanned(self, username: str):
        self.lru_cache.put(username.lower().strip().replace("@", ""), True)

    def save_dead_letter(self, job_id: str, username: str, error_msg: str, attempts: int, reason: DeadLetterReason, category: str, correlation_id: str = "", wait_for_commit: bool = True):
        METRICS.dead_letter_count += 1
        reason_val = reason.value if hasattr(reason, 'value') else str(reason)
        clean_uname = username.lower().strip().replace("@", "")
        clean_error = (error_msg or "")[:255]
        
        action = {
            "_type": "DEAD_LETTER",
            "job_id": job_id,
            "username": clean_uname,
            "correlation_id": correlation_id,
            "error": clean_error,
            "attempts": attempts,
            "reason": reason_val,
            "category": category
        }
        
        if self.writer and getattr(self.writer, 'is_running', False):
            return self.writer.enqueue_action(action, timeout=5.0, wait_for_commit=wait_for_commit)
            
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.execute("""
                        INSERT INTO dead_jobs (job_id, username, correlation_id, error, attempts, reason, failure_category, first_seen, last_attempt)
                        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        ON CONFLICT(job_id) DO UPDATE SET
                            username = excluded.username,
                            correlation_id = excluded.correlation_id,
                            error = excluded.error,
                            attempts = excluded.attempts,
                            reason = excluded.reason,
                            failure_category = excluded.failure_category,
                            last_attempt = CURRENT_TIMESTAMP;
                    """, (job_id, clean_uname, correlation_id, clean_error, attempts, reason_val, category))
                    
                    if job_id:
                        conn.execute("DELETE FROM pending_jobs WHERE job_id = ?;", (job_id,))

                    conn.commit()
                    return True
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"[{correlation_id}] Dead Letter save error for @{username}: {e}")
            return False

    def load_dead_jobs(self, limit: int = 1000) -> List[Tuple[str, str, str, int, str, str]]:
        res = self.repo.load_dead_jobs(limit=limit)
        self.report_read_success()
        return res

    def clear_dead_jobs(self):
        if self.writer and getattr(self.writer, 'is_running', False):
            self.writer.enqueue_action({"_type": "CLEAR_DEAD_JOBS"})
            return
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.execute("DELETE FROM dead_jobs;")
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"Error clearing dead jobs: {e}")

    def recover_abandoned_jobs_on_startup(self) -> List[Job]:
        res = self.repo.recover_abandoned_jobs_on_startup()
        self.report_read_success()
        return res

    def save_pending_job(self, job: Job, wait_for_commit: bool = True) -> bool:
        first_fail_epoch = (time.time() - (time.monotonic() - job.first_failure_monotonic)) if job.first_failure_monotonic else 0.0
        clean_error = (job.last_error or "")[:255]
        action = {
            "_type": "PENDING_JOB",
            "job_id": job.job_id,
            "username": job.username,
            "correlation_id": job.correlation_id,
            "pattern_id": job.pattern_id,
            "source": job.source.value,
            "status": job.status.value,
            "attempt": job.attempt,
            "retry_budget": job.retry_budget,
            "error_signature": job.error_signature,
            "first_failure_epoch": first_fail_epoch,
            "last_error": clean_error,
            "retry_at_epoch": 0.0
        }
        if self.writer and getattr(self.writer, 'is_running', False):
            return self.writer.enqueue_action(action, timeout=5.0, wait_for_commit=wait_for_commit)
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.execute("""
                        INSERT INTO pending_jobs (job_id, username, correlation_id, pattern_id, source, status, attempt, retry_budget, error_signature, first_failure_epoch, last_error, retry_at_epoch, enqueued_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(job_id) DO UPDATE SET
                            username = excluded.username,
                            correlation_id = excluded.correlation_id,
                            pattern_id = excluded.pattern_id,
                            source = excluded.source,
                            status = excluded.status,
                            attempt = excluded.attempt,
                            retry_budget = excluded.retry_budget,
                            error_signature = excluded.error_signature,
                            first_failure_epoch = excluded.first_failure_epoch,
                            last_error = excluded.last_error,
                            retry_at_epoch = excluded.retry_at_epoch,
                            enqueued_at = CURRENT_TIMESTAMP;
                    """, (
                        job.job_id, job.username, job.correlation_id, job.pattern_id,
                        job.source.value, job.status.value, job.attempt,
                        job.retry_budget, job.error_signature, first_fail_epoch,
                        clean_error, 0.0
                    ))
                    conn.commit()
                    return True
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"[{job.correlation_id}] Error saving pending job @{job.username}: {e}")
            return False

    def update_pending_job_retry_state(self, job: Job, retry_at_epoch: float, wait_for_commit: bool = True) -> bool:
        first_fail_epoch = (time.time() - (time.monotonic() - job.first_failure_monotonic)) if job.first_failure_monotonic else time.time()
        clean_error = (job.last_error or "")[:255]
        action = {
            "_type": "UPDATE_PENDING_RETRY",
            "job_id": job.job_id,
            "status": "RETRYABLE",
            "attempt": job.attempt,
            "retry_budget": job.retry_budget,
            "error_signature": job.error_signature,
            "first_failure_epoch": first_fail_epoch,
            "last_error": clean_error,
            "retry_at_epoch": retry_at_epoch
        }
        if self.writer and getattr(self.writer, 'is_running', False):
            return self.writer.enqueue_action(action, timeout=5.0, wait_for_commit=wait_for_commit)
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.execute("""
                        UPDATE pending_jobs 
                        SET status = ?, attempt = ?, retry_budget = ?, error_signature = ?, first_failure_epoch = ?, last_error = ?, retry_at_epoch = ?
                        WHERE job_id = ?;
                    """, (
                        "RETRYABLE", job.attempt, job.retry_budget,
                        job.error_signature, first_fail_epoch,
                        clean_error, retry_at_epoch, job.job_id
                    ))
                    conn.commit()
                    return True
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"[{job.correlation_id}] Error updating pending retry state for @{job.username}: {e}")
            return False

    def save_pending_jobs_batch(self, jobs: List[Job], wait_for_commit: bool = True) -> bool:
        if not jobs:
            return True
        now_time = time.time()
        now_mono = time.monotonic()
        data = []
        for j in jobs:
            first_fail_epoch = (now_time - (now_mono - j.first_failure_monotonic)) if j.first_failure_monotonic else 0.0
            clean_error = (j.last_error or "")[:255]
            data.append((
                j.job_id, j.username, j.correlation_id, j.pattern_id,
                j.source.value, j.status.value, j.attempt,
                j.retry_budget, j.error_signature, first_fail_epoch,
                clean_error, 0.0
            ))
        action = {"_type": "PENDING_JOBS_BATCH", "data": data}
        if self.writer and getattr(self.writer, 'is_running', False):
            return self.writer.enqueue_action(action, timeout=10.0, wait_for_commit=wait_for_commit)
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.executemany("""
                        INSERT INTO pending_jobs (job_id, username, correlation_id, pattern_id, source, status, attempt, retry_budget, error_signature, first_failure_epoch, last_error, retry_at_epoch, enqueued_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(job_id) DO UPDATE SET
                            username = excluded.username,
                            correlation_id = excluded.correlation_id,
                            pattern_id = excluded.pattern_id,
                            source = excluded.source,
                            status = excluded.status,
                            attempt = excluded.attempt,
                            retry_budget = excluded.retry_budget,
                            error_signature = excluded.error_signature,
                            first_failure_epoch = excluded.first_failure_epoch,
                            last_error = excluded.last_error,
                            retry_at_epoch = excluded.retry_at_epoch,
                            enqueued_at = CURRENT_TIMESTAMP;
                    """, data)
                    conn.commit()
                    return True
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"Error saving pending jobs batch: {e}")
            return False

    def update_pending_job_status(self, job_id: str, status: JobStatus):
        if self.writer and getattr(self.writer, 'is_running', False):
            self.writer.enqueue_action({"_type": "UPDATE_PENDING_STATUS", "job_id": job_id, "status": status.value})
            return
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    if status in [JobStatus.COMPLETED, JobStatus.DEAD_LETTER]:
                        conn.execute("DELETE FROM pending_jobs WHERE job_id = ?;", (job_id,))
                    else:
                        conn.execute("UPDATE pending_jobs SET status = ? WHERE job_id = ?;", (status.value, job_id))
                    conn.commit()
                finally:
                    conn.close()
        except Exception:
            pass

    def delete_pending_job(self, job_id: str):
        if self.writer and getattr(self.writer, 'is_running', False):
            self.writer.enqueue_action({"_type": "DELETE_PENDING_JOB", "job_id": job_id})
            return
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.execute("DELETE FROM pending_jobs WHERE job_id = ?;", (job_id,))
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"Error deleting pending job {job_id}: {e}")

    def delete_pending_jobs_by_pattern(self, pattern_id: str) -> int:
        if not pattern_id:
            return 0
        if self.writer and getattr(self.writer, 'is_running', False):
            self.writer.enqueue_action({"_type": "DELETE_PENDING_BY_PATTERN", "pattern_id": pattern_id})
            return 0
        deleted_count = 0
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM pending_jobs WHERE pattern_id = ?;", (pattern_id,))
                    deleted_count = cur.rowcount
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"Error deleting pending jobs for pattern '{pattern_id}': {e}")
        return deleted_count

    def clear_pending_jobs(self):
        if self.writer and getattr(self.writer, 'is_running', False):
            self.writer.enqueue_action({"_type": "CLEAR_PENDING_JOBS"})
            return
        with self.lock:
            conn = self._get_connection()
            try:
                conn.execute("DELETE FROM pending_jobs;")
                conn.commit()
            except Exception as e:
                logger.error(f"Error clearing pending jobs: {e}")
            finally:
                conn.close()

    def get_total_count(self) -> int:
        return self.repo.get_total_count()

    def get_dead_letter_count(self) -> int:
        return self.repo.get_dead_letter_count()

    def checkpoint_wal(self, mode: str = "PASSIVE") -> Tuple[int, int]:
        ckpt_start = time.monotonic()
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    cur = conn.cursor()
                    cur.execute(f"PRAGMA wal_checkpoint({mode});")
                    row = cur.fetchone()
                    pnLog = row[1] if row and len(row) > 1 else 0
                    pnCkpt = row[2] if row and len(row) > 2 else 0
                    ckpt_dur = (time.monotonic() - ckpt_start) * 1000
                    METRICS.record_checkpoint_latency(ckpt_dur)
                    logger.info(f"Controlled WAL Checkpoint ({mode}): Frames Total={pnLog}, Checkpointed={pnCkpt} in {ckpt_dur:.2f}ms")
                    return pnLog, pnCkpt
                finally:
                    conn.close()
        except Exception as e:
            logger.exception(f"WAL Checkpoint Exception: {e}")
            return 0, 0