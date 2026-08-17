from __future__ import annotations
import os
import time
import json
import sqlite3
import queue
import threading
import uuid
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Tuple, Dict, Any, Optional

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
    MAX_WRITER_QUEUE,
    MAX_FILE_BUFFER_LINES,
    MAX_TX_AGE_SEC,
    MAX_TX_RECORD_COUNT,
    MAX_COMMIT_RETRIES,
    COMMIT_RETRY_BACKOFF_BASE_SEC,
    DB_BUSY_TIMEOUT_MS,
    DB_SYNCHRONOUS_MODE,
    DB_TEMP_STORE,
    DB_WRITER_CACHE_KIB,
    MAX_EXPORT_FILE_BYTES
)
from core.state.enums import DatabaseHealthState, DiskHealthState, DeadLetterReason, AckStatus
from core.errors.categories import ErrorCategory
from core.metrics import METRICS
from core.utils import get_real_desktop_path
from core.logger import logger
from persistence.emergency_journal import EmergencyJournalManager

class PersistenceAck:
    """
    P0 Strongly-Typed Durability Barrier:
    Guarantees that wait() returns True STRICTLY AND ONLY if SQLite COMMIT succeeded.
    Never returns True on failure, quarantine, or emergency journal fallback.
    """
    def __init__(self):
        self._event = threading.Event()
        self.status: AckStatus = AckStatus.FAILED
        self.error_message: str = ""

    def set_committed(self):
        self.status = AckStatus.COMMITTED
        self._event.set()

    def set_emergency_journaled(self, reason: str = ""):
        self.status = AckStatus.EMERGENCY_JOURNALED
        self.error_message = reason
        self._event.set()

    def set_failed(self, error: str = ""):
        self.status = AckStatus.FAILED
        self.error_message = error
        self._event.set()

    def wait(self, timeout: float = 5.0) -> bool:
        signaled = self._event.wait(timeout=timeout)
        if not signaled:
            self.status = AckStatus.TIMEOUT
            return False
        return self.status == AckStatus.COMMITTED

class StorageWriterWorker(QThread):
    sig_batch_processed = pyqtSignal(list)
    sig_log = pyqtSignal(str)

    def __init__(self, db_path: str = "falcon_master.db", db_manager: Any = None):
        super().__init__()
        self.db_path = db_path
        self.db_manager = db_manager
        
        self.result_queue: queue.Queue = queue.Queue(maxsize=MAX_WRITER_QUEUE)
        self.file_buffers = defaultdict(list)
        self.is_running = False
        self.desktop_dir = get_real_desktop_path()
        self.last_commit_monotonic = time.monotonic()
        self._db_degraded_local = False
        self.final_commit_succeeded = True
        self.sequence_counter = 0

        # P0 Persistence Invariant Metrics
        self.consecutive_write_failures = 0
        self.total_write_failures = 0
        self.last_write_error = ""

        # P0 Observable In-Flight Transaction Buffer
        self.in_flight_uncommitted_records: List[dict] = []
        self.in_flight_lock = threading.RLock()
        self.emergency_mgr = EmergencyJournalManager(self.desktop_dir)

        # P0 O(1) Active Export File Cache
        self.active_export_targets: Dict[str, Dict[str, Any]] = {}

        # P0 Readiness Handshake
        self.is_ready_event = threading.Event()

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self.is_ready_event.wait(timeout=timeout)

    @property
    def db_degraded(self) -> bool:
        if self.db_manager:
            return self.db_manager.is_degraded() or (self.consecutive_write_failures > 0)
        return self._db_degraded_local or (self.consecutive_write_failures > 0)

    @property
    def db_health_state(self) -> DatabaseHealthState:
        if self.db_manager:
            return self.db_manager.get_health_state()
        if self.consecutive_write_failures >= 3:
            return DatabaseHealthState.UNAVAILABLE
        elif self.consecutive_write_failures > 0 or self._db_degraded_local:
            return DatabaseHealthState.DEGRADED
        return DatabaseHealthState.HEALTHY

    def enqueue_result(self, record: dict, timeout: float = 2.0) -> bool:
        try:
            self.result_queue.put(record, block=True, timeout=timeout)
            return True
        except queue.Full:
            return False

    def enqueue_action(self, action: dict, timeout: float = 5.0, wait_for_commit: bool = False) -> bool:
        """P0 Durability Barrier: If wait_for_commit is True, returns True ONLY upon confirmed SQLite COMMIT."""
        ack_obj = PersistenceAck() if wait_for_commit else None
        if ack_obj:
            action["_ack_obj"] = ack_obj
            action["_force_commit"] = True
        try:
            self.result_queue.put(action, block=True, timeout=timeout)
            if ack_obj:
                return ack_obj.wait(timeout=timeout)
            return True
        except queue.Full:
            return False

    def get_queue_len(self) -> int:
        return self.result_queue.qsize()

    def drain_in_flight_uncommitted(self) -> List[dict]:
        with self.in_flight_lock:
            drained = list(self.in_flight_uncommitted_records)
            self.in_flight_uncommitted_records.clear()
            return drained

    def run(self):
        self.is_running = True
        try:
            conn = self._create_writer_connection()
        except Exception as e:
            logger.critical(f"StorageWriter: Failed to create SQLite connection: {e}")
            self.is_running = False
            return

        try:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(MAX(result_sequence), 0) FROM scan_results;")
            row = cur.fetchone()
            self.sequence_counter = row[0] if row else 0
        except Exception:
            self.sequence_counter = 0

        self.is_ready_event.set()

        uncommitted = 0
        force_commit_requested = False
        
        staged_ui_records: List[dict] = []
        verified_executed_records: List[dict] = []
        verified_usernames_for_lru: List[str] = []

        while self.is_running or not self.result_queue.empty():
            try:
                records_to_process = []
                try:
                    first_record = self.result_queue.get(block=True, timeout=0.1)
                    records_to_process.append(first_record)
                    while len(records_to_process) < 100:
                        rec = self.result_queue.get_nowait()
                        records_to_process.append(rec)
                except queue.Empty:
                    pass

                if records_to_process:
                    with self.in_flight_lock:
                        self.in_flight_uncommitted_records.extend(records_to_process)

                    for record in records_to_process:
                        if isinstance(record, dict) and (record.get("_force_commit") or record.get("_ack_obj") is not None or record.get("_ack_event") is not None):
                            force_commit_requested = True
                        action_type = record.get("_type") if isinstance(record, dict) else None

                        if action_type == "DEAD_LETTER":
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
                                """, (record["job_id"], record["username"], record.get("correlation_id", ""), record["error"], record["attempts"], record["reason"], record["category"]))
                                
                                if record.get("job_id"):
                                    conn.execute("DELETE FROM pending_jobs WHERE job_id = ?;", (record["job_id"],))

                                uncommitted += 1
                                verified_executed_records.append(record)
                            except Exception as dbe:
                                logger.error(f"Single Writer error inserting dead letter: {dbe}")
                                self._handle_individual_record_failure(record, str(dbe))
                            continue

                        elif action_type == "PRUNE_DEAD_LETTERS":
                            try:
                                retention_days = record.get("retention_days", 30)
                                conn.execute("DELETE FROM dead_jobs WHERE last_attempt < datetime('now', ?);", (f'-{retention_days} days',))
                                uncommitted += 1
                                verified_executed_records.append(record)
                            except Exception as dbe:
                                logger.error(f"Single Writer error pruning dead letters: {dbe}")
                                self._handle_individual_record_failure(record, str(dbe))
                            continue

                        elif action_type == "PRUNE_HEALTH_SNAPSHOTS":
                            try:
                                retention_days = record.get("retention_days", 7)
                                conn.execute("DELETE FROM health_snapshots WHERE timestamp < datetime('now', ?);", (f'-{retention_days} days',))
                                uncommitted += 1
                                verified_executed_records.append(record)
                            except Exception as dbe:
                                logger.error(f"Single Writer error pruning health snapshots: {dbe}")
                                self._handle_individual_record_failure(record, str(dbe))
                            continue

                        elif action_type == "PENDING_JOB":
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
                                    record["job_id"], record["username"], record.get("correlation_id", ""), record.get("pattern_id", ""),
                                    record.get("source", "PATTERN"), record.get("status", "QUEUED"), record.get("attempt", 0),
                                    record.get("retry_budget", 6), record.get("error_signature", ""), record.get("first_failure_epoch", 0.0),
                                    record.get("last_error", ""), record.get("retry_at_epoch", 0.0)
                                ))
                                uncommitted += 1
                                verified_executed_records.append(record)
                            except Exception as dbe:
                                logger.error(f"Single Writer error inserting pending job: {dbe}")
                                self._handle_individual_record_failure(record, str(dbe))
                            continue

                        elif action_type == "UPDATE_PENDING_RETRY":
                            try:
                                conn.execute("""
                                    UPDATE pending_jobs 
                                    SET status = ?, attempt = ?, retry_budget = ?, error_signature = ?, first_failure_epoch = ?, last_error = ?, retry_at_epoch = ?
                                    WHERE job_id = ?;
                                """, (
                                    record["status"], record["attempt"], record["retry_budget"],
                                    record.get("error_signature", ""), record.get("first_failure_epoch", 0.0),
                                    record.get("last_error", ""), record.get("retry_at_epoch", 0.0),
                                    record["job_id"]
                                ))
                                uncommitted += 1
                                verified_executed_records.append(record)
                            except Exception as dbe:
                                logger.error(f"Single Writer error updating pending retry: {dbe}")
                                self._handle_individual_record_failure(record, str(dbe))
                            continue

                        elif action_type == "PENDING_JOBS_BATCH":
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
                                """, record["data"])
                                uncommitted += len(record["data"])
                                verified_executed_records.append(record)
                            except Exception as dbe:
                                logger.error(f"Single Writer error inserting pending jobs batch: {dbe}")
                                self._handle_individual_record_failure(record, str(dbe))
                            continue

                        elif action_type == "UPDATE_PENDING_STATUS":
                            try:
                                status_str = record["status"]
                                if status_str in ["COMPLETED", "DEAD_LETTER"]:
                                    conn.execute("DELETE FROM pending_jobs WHERE job_id = ?;", (record["job_id"],))
                                else:
                                    conn.execute("UPDATE pending_jobs SET status = ? WHERE job_id = ?;", (status_str, record["job_id"]))
                                uncommitted += 1
                                verified_executed_records.append(record)
                            except Exception as dbe:
                                logger.error(f"Single Writer error updating pending status: {dbe}")
                                self._handle_individual_record_failure(record, str(dbe))
                            continue

                        elif action_type == "DELETE_PENDING_JOB":
                            try:
                                conn.execute("DELETE FROM pending_jobs WHERE job_id = ?;", (record["job_id"],))
                                uncommitted += 1
                                verified_executed_records.append(record)
                            except Exception as dbe:
                                logger.error(f"Single Writer error deleting pending job: {dbe}")
                                self._handle_individual_record_failure(record, str(dbe))
                            continue

                        elif action_type == "DELETE_PENDING_BY_PATTERN":
                            try:
                                conn.execute("DELETE FROM pending_jobs WHERE pattern_id = ?;", (record["pattern_id"],))
                                uncommitted += 1
                                verified_executed_records.append(record)
                            except Exception as dbe:
                                logger.error(f"Single Writer error deleting pending jobs by pattern: {dbe}")
                                self._handle_individual_record_failure(record, str(dbe))
                            continue

                        elif action_type == "HEALTH_SNAPSHOT":
                            try:
                                snap = record["snap"]
                                conn.execute("""
                                    INSERT INTO health_snapshots (
                                        session_id, requests, successful_requests, http_429, http_5xx,
                                        timeouts, dead_letters, poison_jobs, jobs_persisted,
                                        queue_depth, oldest_queue_age_sec, ram_mb, ram_slope_mb_hr,
                                        threads_count, handles_count, db_size_mb, wal_size_mb
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                                """, (
                                    record["session_id"], snap.get("requests", 0), snap.get("success", 0),
                                    snap.get("429", 0), snap.get("5xx", 0), snap.get("timeouts", 0),
                                    snap.get("dead_letters", 0), snap.get("poison_jobs", 0), snap.get("jobs_persisted", 0),
                                    snap.get("q_scanner_peak", 0), snap.get("oldest_age_sec", 0.0), record.get("ram_mb", 0.0),
                                    snap.get("ram_long_slope", 0.0), snap.get("threads_current", 0), snap.get("handles_current", 0),
                                    record["db_mb"], record["wal_mb"]
                                ))
                                uncommitted += 1
                                verified_executed_records.append(record)
                            except Exception as dbe:
                                logger.error(f"Single Writer error saving health snapshot: {dbe}")
                                self._handle_individual_record_failure(record, str(dbe))
                            continue

                        elif action_type == "SESSION_JOURNAL":
                            try:
                                conn.execute("""
                                    UPDATE runtime_state 
                                    SET last_username = ?, last_error = ?
                                    WHERE session_id = ?;
                                """, (record["last_username"], record.get("last_error", ""), record["session_id"]))
                                uncommitted += 1
                                verified_executed_records.append(record)
                            except Exception as dbe:
                                logger.error(f"Single Writer error updating session journal: {dbe}")
                                self._handle_individual_record_failure(record, str(dbe))
                            continue

                        elif action_type == "CLEAN_SHUTDOWN":
                            try:
                                conn.execute("""
                                    UPDATE runtime_state 
                                    SET stopped_at = CURRENT_TIMESTAMP, status = 'CLEAN_SHUTDOWN'
                                    WHERE session_id = ?;
                                """, (record["session_id"],))
                                uncommitted += 1
                                verified_executed_records.append(record)
                            except Exception as dbe:
                                logger.error(f"Single Writer error recording clean shutdown: {dbe}")
                                self._handle_individual_record_failure(record, str(dbe))
                            continue

                        elif action_type == "CLEAR_DEAD_JOBS":
                            try:
                                conn.execute("DELETE FROM dead_jobs;")
                                uncommitted += 1
                                verified_executed_records.append(record)
                            except Exception as dbe:
                                logger.error(f"Single Writer error clearing dead jobs: {dbe}")
                                self._handle_individual_record_failure(record, str(dbe))
                            continue

                        elif action_type == "CLEAR_PENDING_JOBS":
                            try:
                                conn.execute("DELETE FROM pending_jobs;")
                                uncommitted += 1
                                verified_executed_records.append(record)
                            except Exception as dbe:
                                logger.error(f"Single Writer error clearing pending jobs: {dbe}")
                                self._handle_individual_record_failure(record, str(dbe))
                            continue

                        # Regular Scan Result Processing
                        username = record["raw_username"]
                        status = record["status"]
                        conf = record["confidence"]
                        price = record["price"]
                        detail = record["detail"]
                        pat_id = record.get("pat_id", "")
                        job_id = record.get("job_id", "")
                        corr_id = record.get("correlation_id", "")
                        
                        self.sequence_counter += 1
                        seq_num = self.sequence_counter
                        record["result_sequence"] = seq_num

                        try:
                            conn.execute("""
                                INSERT INTO scan_results (username, status, confidence, price, detail, pattern_id, result_sequence, scanned_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                                ON CONFLICT(username) DO UPDATE SET
                                    status = excluded.status,
                                    confidence = excluded.confidence,
                                    price = excluded.price,
                                    detail = excluded.detail,
                                    pattern_id = excluded.pattern_id,
                                    result_sequence = excluded.result_sequence,
                                    scanned_at = CURRENT_TIMESTAMP;
                            """, (username.lower(), status, conf, price, detail, pat_id, seq_num))
                            
                            if job_id:
                                conn.execute("DELETE FROM pending_jobs WHERE job_id = ?;", (job_id,))
                                
                            uncommitted += 1
                            verified_executed_records.append(record)
                            verified_usernames_for_lru.append(username)
                            staged_ui_records.append(record)

                            disk_state = self.db_manager.check_disk_health() if self.db_manager else DiskHealthState.HEALTHY
                            if disk_state != DiskHealthState.HALTED and status in ["UNAVAILABLE", "AVAILABLE", "AUCTION", "SOLD"]:
                                line = f"#{seq_num} | @{username} | {status} | {detail} | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                                if len(self.file_buffers[status.lower()]) < MAX_FILE_BUFFER_LINES:
                                    self.file_buffers[status.lower()].append(line)

                        except Exception as dbe:
                            logger.error(f"[{corr_id}] Database execute failure for @{username}: {dbe}")
                            self.consecutive_write_failures += 1
                            self.total_write_failures += 1
                            self.last_write_error = str(dbe)
                            self._db_degraded_local = True
                            if self.db_manager:
                                self.db_manager.report_write_failure(str(dbe))
                            
                            self._handle_individual_record_failure(record, f"Database execute error: {dbe}")

                now = time.monotonic()
                tx_age_exceeded = (now - self.last_commit_monotonic >= MAX_TX_AGE_SEC) and (uncommitted > 0)
                record_limit_reached = uncommitted >= MAX_TX_RECORD_COUNT
                should_commit = (record_limit_reached or tx_age_exceeded or force_commit_requested) and (uncommitted > 0)

                if should_commit:
                    force_commit_requested = False
                    c_start = time.monotonic()
                    commit_succeeded = False
                    last_commit_error = ""

                    try:
                        conn.commit()
                        commit_succeeded = True
                    except Exception as ce:
                        last_commit_error = str(ce)
                        logger.warning(f"Database COMMIT initial failure: {ce}. Initiating explicit retry policy...")
                        try:
                            conn.rollback()
                        except Exception:
                            pass

                        self.consecutive_write_failures += 1
                        self.total_write_failures += 1
                        self.last_write_error = last_commit_error
                        self._db_degraded_local = True
                        if self.db_manager:
                            self.db_manager.report_write_failure(last_commit_error, fatal=False)

                        for attempt in range(1, MAX_COMMIT_RETRIES + 1):
                            backoff = COMMIT_RETRY_BACKOFF_BASE_SEC * (2 ** (attempt - 1))
                            time.sleep(backoff)
                            try:
                                reapplied_uncommitted, reapplied_usernames = self._reapply_records_to_connection(conn, verified_executed_records)
                                conn.commit()
                                commit_succeeded = True
                                uncommitted = reapplied_uncommitted
                                verified_usernames_for_lru = list(reapplied_usernames)
                                logger.info(f"✓ SQLite transaction retry #{attempt} succeeded.")
                                break
                            except Exception as retry_err:
                                last_commit_error = str(retry_err)
                                try:
                                    conn.rollback()
                                except Exception:
                                    pass
                                if attempt in (2, 4):
                                    try:
                                        conn.close()
                                    except Exception:
                                        pass
                                    try:
                                        conn = self._create_writer_connection()
                                    except Exception:
                                        pass

                    if commit_succeeded:
                        commit_dur = (time.monotonic() - c_start) * 1000
                        METRICS.record_db_commit(commit_dur, uncommitted)
                        METRICS.record_jobs_persisted_batch(uncommitted)
                        self.last_commit_monotonic = now
                        
                        self._db_degraded_local = False
                        self.consecutive_write_failures = 0
                        if self.db_manager:
                            self.db_manager.report_write_success()
                            
                            for u in verified_usernames_for_lru:
                                self.db_manager.mark_scanned(u)
                            if verified_usernames_for_lru:
                                self.db_manager.update_session_journal(last_username=verified_usernames_for_lru[-1])
                                
                        verified_usernames_for_lru.clear()
                        uncommitted = 0
                        self._flush_file_buffers_atomic()
                        
                        if staged_ui_records:
                            self.sig_batch_processed.emit(list(staged_ui_records))
                            staged_ui_records.clear()

                        with self.in_flight_lock:
                            for rec in verified_executed_records:
                                ack_obj: Optional[PersistenceAck] = rec.get("_ack_obj")
                                if ack_obj is not None:
                                    ack_obj.set_committed()
                                
                                ack_evt = rec.get("_ack_event")
                                if ack_evt is not None:
                                    try:
                                        ack_evt.set()
                                    except Exception:
                                        pass
                                
                                job_obj = rec.get("_job_obj") if isinstance(rec, dict) else None
                                if job_obj is not None:
                                    try:
                                        job_obj.mark_persisted()
                                    except Exception:
                                        pass
                                try:
                                    self.result_queue.task_done()
                                except Exception:
                                    pass
                            self.in_flight_uncommitted_records.clear()
                        verified_executed_records.clear()
                    else:
                        logger.critical(f"FATAL: Database COMMIT exhausted retries. Activating Rotated Emergency Journal.")
                        self._db_degraded_local = True
                        if self.db_manager:
                            self.db_manager.report_write_failure(last_commit_error, fatal=True)

                        verified_usernames_for_lru.clear()
                        staged_ui_records.clear()

                        with self.in_flight_lock:
                            self.emergency_mgr.write_emergency_dump(self.in_flight_uncommitted_records, last_commit_error)
                            for rec in self.in_flight_uncommitted_records:
                                ack_obj: Optional[PersistenceAck] = rec.get("_ack_obj")
                                if ack_obj is not None:
                                    ack_obj.set_emergency_journaled(last_commit_error)
                                
                                ack_evt = rec.get("_ack_event")
                                if ack_evt is not None:
                                    try:
                                        ack_evt.set()
                                    except Exception:
                                        pass

                                job_obj = rec.get("_job_obj") if isinstance(rec, dict) else None
                                if job_obj is not None:
                                    try:
                                        job_obj.mark_permanent_failure(
                                            error_msg=f"Emergency Journal: SQLite commit exhausted retries ({last_commit_error})",
                                            category=ErrorCategory.DB_ERROR,
                                            reason=DeadLetterReason.DB_FAILURE
                                        )
                                    except Exception:
                                        pass
                                try:
                                    self.result_queue.task_done()
                                except Exception:
                                    pass
                            self.in_flight_uncommitted_records.clear()
                        verified_executed_records.clear()
                        uncommitted = 0
                        self.last_commit_monotonic = now

                if not records_to_process:
                    time.sleep(0.02)

            except Exception as e:
                logger.exception(f"StorageWriter Loop Exception: {e}")
                time.sleep(0.5)

        # Final Drain on Shutdown
        with self.in_flight_lock:
            remaining_in_flight = list(self.in_flight_uncommitted_records)

        if uncommitted > 0 or remaining_in_flight:
            final_commit_succeeded = False
            final_error = ""
            try:
                conn.commit()
                final_commit_succeeded = True
            except Exception as e:
                final_error = str(e)
                try:
                    conn.rollback()
                except Exception:
                    pass
                for attempt in range(1, MAX_COMMIT_RETRIES + 1):
                    time.sleep(COMMIT_RETRY_BACKOFF_BASE_SEC * (2 ** (attempt - 1)))
                    try:
                        reapplied_uncommitted, reapplied_usernames = self._reapply_records_to_connection(conn, remaining_in_flight)
                        conn.commit()
                        final_commit_succeeded = True
                        uncommitted = reapplied_uncommitted
                        verified_usernames_for_lru = list(reapplied_usernames)
                        break
                    except Exception as retry_e:
                        final_error = str(retry_e)
                        try:
                            conn.rollback()
                        except Exception:
                            pass

            if final_commit_succeeded:
                METRICS.record_jobs_persisted_batch(uncommitted)
                if self.db_manager:
                    for u in verified_usernames_for_lru:
                        self.db_manager.mark_scanned(u)
                    if verified_usernames_for_lru:
                        self.db_manager.update_session_journal(last_username=verified_usernames_for_lru[-1])
                verified_usernames_for_lru.clear()
                
                if staged_ui_records:
                    self.sig_batch_processed.emit(list(staged_ui_records))
                    staged_ui_records.clear()

                with self.in_flight_lock:
                    for rec in self.in_flight_uncommitted_records:
                        ack_obj: Optional[PersistenceAck] = rec.get("_ack_obj")
                        if ack_obj is not None:
                            ack_obj.set_committed()

                        ack_evt = rec.get("_ack_event")
                        if ack_evt is not None:
                            try:
                                ack_evt.set()
                            except Exception:
                                pass

                        job_obj = rec.get("_job_obj") if isinstance(rec, dict) else None
                        if job_obj is not None:
                            try:
                                job_obj.mark_persisted()
                            except Exception:
                                pass
                        try:
                            self.result_queue.task_done()
                        except Exception:
                            pass
                    self.in_flight_uncommitted_records.clear()
                self.final_commit_succeeded = True
            else:
                logger.critical(f"Final StorageWriter Commit Error: {final_error}. Dumping to Rotated Emergency Journal.")
                self.final_commit_succeeded = False
                with self.in_flight_lock:
                    self.emergency_mgr.write_emergency_dump(self.in_flight_uncommitted_records, final_error)
                    for rec in self.in_flight_uncommitted_records:
                        ack_obj: Optional[PersistenceAck] = rec.get("_ack_obj")
                        if ack_obj is not None:
                            ack_obj.set_emergency_journaled(final_error)

                        ack_evt = rec.get("_ack_event")
                        if ack_evt is not None:
                            try:
                                ack_evt.set()
                            except Exception:
                                pass

                        try:
                            self.result_queue.task_done()
                        except Exception:
                            pass
                    self.in_flight_uncommitted_records.clear()
                verified_usernames_for_lru.clear()
                staged_ui_records.clear()

        self._flush_file_buffers_atomic()
        conn.close()

    def _handle_individual_record_failure(self, record: dict, error_msg: str):
        username = record.get("raw_username") or record.get("username", "").replace("@", "")
        job_id = record.get("job_id") or f"db_err_{uuid.uuid4().hex[:8]}"
        corr_id = record.get("correlation_id", "N/A")

        logger.error(f"[{corr_id}] Quarantining failed record for @{username}: {error_msg}")

        if self.db_manager and hasattr(self.db_manager, 'lru_cache'):
            self.db_manager.lru_cache.evict(username)

        job_obj = record.get("_job_obj") if isinstance(record, dict) else None
        if job_obj is not None:
            try:
                job_obj.mark_permanent_failure(
                    error_msg=error_msg,
                    category=ErrorCategory.DB_ERROR,
                    reason=DeadLetterReason.DB_FAILURE
                )
            except Exception:
                pass

        ack_obj: Optional[PersistenceAck] = record.get("_ack_obj")
        if ack_obj is not None:
            ack_obj.set_failed(error_msg)

        ack_evt = record.get("_ack_event")
        if ack_evt is not None:
            try:
                ack_evt.set()
            except Exception:
                pass

        try:
            self.result_queue.task_done()
        except Exception:
            pass

    def _create_writer_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=DB_BUSY_TIMEOUT_MS / 1000.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(f"PRAGMA synchronous={DB_SYNCHRONOUS_MODE};")
        conn.execute(f"PRAGMA temp_store={DB_TEMP_STORE};")
        conn.execute(f"PRAGMA cache_size={DB_WRITER_CACHE_KIB};")
        conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
        return conn

    def _reapply_records_to_connection(self, conn: sqlite3.Connection, records: List[dict]) -> Tuple[int, List[str]]:
        reapplied_uncommitted = 0
        reapplied_usernames: List[str] = []

        for record in records:
            action_type = record.get("_type") if isinstance(record, dict) else None

            if action_type == "DEAD_LETTER":
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
                    """, (record["job_id"], record["username"], record.get("correlation_id", ""), record["error"], record["attempts"], record["reason"], record["category"]))
                    
                    if record.get("job_id"):
                        conn.execute("DELETE FROM pending_jobs WHERE job_id = ?;", (record["job_id"],))

                    reapplied_uncommitted += 1
                except Exception:
                    pass
                continue

            elif action_type == "PRUNE_DEAD_LETTERS":
                try:
                    retention_days = record.get("retention_days", 30)
                    conn.execute("DELETE FROM dead_jobs WHERE last_attempt < datetime('now', ?);", (f'-{retention_days} days',))
                    reapplied_uncommitted += 1
                except Exception:
                    pass
                continue

            elif action_type == "PRUNE_HEALTH_SNAPSHOTS":
                try:
                    retention_days = record.get("retention_days", 7)
                    conn.execute("DELETE FROM health_snapshots WHERE timestamp < datetime('now', ?);", (f'-{retention_days} days',))
                    reapplied_uncommitted += 1
                except Exception:
                    pass
                continue

            elif action_type == "PENDING_JOB":
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
                        record["job_id"], record["username"], record.get("correlation_id", ""), record.get("pattern_id", ""),
                        record.get("source", "PATTERN"), record.get("status", "QUEUED"), record.get("attempt", 0),
                        record.get("retry_budget", 6), record.get("error_signature", ""), record.get("first_failure_epoch", 0.0),
                        record.get("last_error", ""), record.get("retry_at_epoch", 0.0)
                    ))
                    reapplied_uncommitted += 1
                except Exception:
                    pass
                continue

            elif action_type == "UPDATE_PENDING_RETRY":
                try:
                    conn.execute("""
                        UPDATE pending_jobs 
                        SET status = ?, attempt = ?, retry_budget = ?, error_signature = ?, first_failure_epoch = ?, last_error = ?, retry_at_epoch = ?
                        WHERE job_id = ?;
                    """, (
                        record["status"], record["attempt"], record["retry_budget"],
                        record.get("error_signature", ""), record.get("first_failure_epoch", 0.0),
                        record.get("last_error", ""), record.get("retry_at_epoch", 0.0),
                        record["job_id"]
                    ))
                    reapplied_uncommitted += 1
                except Exception:
                    pass
                continue

            elif action_type == "PENDING_JOBS_BATCH":
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
                    """, record["data"])
                    reapplied_uncommitted += len(record["data"])
                except Exception:
                    pass
                continue

            elif action_type == "UPDATE_PENDING_STATUS":
                try:
                    status_str = record["status"]
                    if status_str in ["COMPLETED", "DEAD_LETTER"]:
                        conn.execute("DELETE FROM pending_jobs WHERE job_id = ?;", (record["job_id"],))
                    else:
                        conn.execute("UPDATE pending_jobs SET status = ? WHERE job_id = ?;", (status_str, record["job_id"]))
                    reapplied_uncommitted += 1
                except Exception:
                    pass
                continue

            elif action_type == "DELETE_PENDING_JOB":
                try:
                    conn.execute("DELETE FROM pending_jobs WHERE job_id = ?;", (record["job_id"],))
                    reapplied_uncommitted += 1
                except Exception:
                    pass
                continue

            elif action_type == "DELETE_PENDING_BY_PATTERN":
                try:
                    conn.execute("DELETE FROM pending_jobs WHERE pattern_id = ?;", (record["pattern_id"],))
                    reapplied_uncommitted += 1
                except Exception:
                    pass
                continue

            elif action_type == "HEALTH_SNAPSHOT":
                try:
                    snap = record["snap"]
                    conn.execute("""
                        INSERT INTO health_snapshots (
                            session_id, requests, successful_requests, http_429, http_5xx,
                            timeouts, dead_letters, poison_jobs, jobs_persisted,
                            queue_depth, oldest_queue_age_sec, ram_mb, ram_slope_mb_hr,
                            threads_count, handles_count, db_size_mb, wal_size_mb
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        record["session_id"], snap.get("requests", 0), snap.get("success", 0),
                        snap.get("429", 0), snap.get("5xx", 0), snap.get("timeouts", 0),
                        snap.get("dead_letters", 0), snap.get("poison_jobs", 0), snap.get("jobs_persisted", 0),
                        snap.get("q_scanner_peak", 0), snap.get("oldest_age_sec", 0.0), record.get("ram_mb", 0.0),
                        snap.get("ram_long_slope", 0.0), snap.get("threads_current", 0), snap.get("handles_current", 0),
                        record["db_mb"], record["wal_mb"]
                    ))
                    reapplied_uncommitted += 1
                except Exception:
                    pass
                continue

            elif action_type == "SESSION_JOURNAL":
                try:
                    conn.execute("""
                        UPDATE runtime_state 
                        SET last_username = ?, last_error = ?
                        WHERE session_id = ?;
                    """, (record["last_username"], record.get("last_error", ""), record["session_id"]))
                    reapplied_uncommitted += 1
                except Exception:
                    pass
                continue

            elif action_type == "CLEAN_SHUTDOWN":
                try:
                    conn.execute("""
                        UPDATE runtime_state 
                        SET stopped_at = CURRENT_TIMESTAMP, status = 'CLEAN_SHUTDOWN'
                        WHERE session_id = ?;
                    """, (record["session_id"],))
                    reapplied_uncommitted += 1
                except Exception:
                    pass
                continue

            elif action_type == "CLEAR_DEAD_JOBS":
                try:
                    conn.execute("DELETE FROM dead_jobs;")
                    reapplied_uncommitted += 1
                except Exception:
                    pass
                continue

            elif action_type == "CLEAR_PENDING_JOBS":
                try:
                    conn.execute("DELETE FROM pending_jobs;")
                    reapplied_uncommitted += 1
                except Exception:
                    pass
                continue

            username = record.get("raw_username", "")
            status = record.get("status", "")
            conf = record.get("confidence", 0.0)
            price = record.get("price", "")
            detail = record.get("detail", "")
            pat_id = record.get("pat_id", "")
            job_id = record.get("job_id", "")
            seq_num = record.get("result_sequence", 0)

            try:
                conn.execute("""
                    INSERT INTO scan_results (username, status, confidence, price, detail, pattern_id, result_sequence, scanned_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(username) DO UPDATE SET
                        status = excluded.status,
                        confidence = excluded.confidence,
                        price = excluded.price,
                        detail = excluded.detail,
                        pattern_id = excluded.pattern_id,
                        result_sequence = excluded.result_sequence,
                        scanned_at = CURRENT_TIMESTAMP;
                """, (username.lower(), status, conf, price, detail, pat_id, seq_num))

                if job_id:
                    conn.execute("DELETE FROM pending_jobs WHERE job_id = ?;", (job_id,))

                reapplied_uncommitted += 1
                reapplied_usernames.append(username)
            except Exception:
                pass

        return reapplied_uncommitted, reapplied_usernames

    def _get_active_export_file(self, status_key: str) -> Path:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        status_dir = self.desktop_dir / status_key
        cached = self.active_export_targets.get(status_key)

        if cached and cached.get("date") == today_str:
            active_path: Path = cached["path"]
            try:
                file_size = active_path.stat().st_size if active_path.exists() else 0
            except Exception:
                file_size = 0

            if file_size < MAX_EXPORT_FILE_BYTES:
                return active_path
            else:
                next_part = cached["part"] + 1
                new_path = status_dir / f"{today_str}_{next_part:04d}.txt"
                self.active_export_targets[status_key] = {
                    "date": today_str,
                    "part": next_part,
                    "path": new_path
                }
                return new_path
        else:
            status_dir.mkdir(parents=True, exist_ok=True)
            existing_parts = []
            for p in status_dir.glob(f"{today_str}_*.txt"):
                try:
                    part_num = int(p.stem.split("_")[-1])
                    existing_parts.append((part_num, p))
                except Exception:
                    pass

            if existing_parts:
                existing_parts.sort(key=lambda x: x[0])
                highest_part, highest_path = existing_parts[-1]
                try:
                    file_size = highest_path.stat().st_size
                except Exception:
                    file_size = 0

                if file_size < MAX_EXPORT_FILE_BYTES:
                    active_part = highest_part
                    active_path = highest_path
                else:
                    active_part = highest_part + 1
                    active_path = status_dir / f"{today_str}_{active_part:04d}.txt"
            else:
                active_part = 1
                active_path = status_dir / f"{today_str}_{active_part:04d}.txt"

            self.active_export_targets[status_key] = {
                "date": today_str,
                "part": active_part,
                "path": active_path
            }
            return active_path

    def _flush_file_buffers_atomic(self):
        for status_key, lines in list(self.file_buffers.items()):
            if lines:
                try:
                    target_file = self._get_active_export_file(status_key)
                    with open(target_file, "a", encoding="utf-8", errors="ignore") as f_out:
                        f_out.writelines(lines)
                        f_out.flush()
                    self.file_buffers[status_key].clear()
                except Exception as e:
                    logger.warning(f"File Export Append Error for {status_key}: {e}")
                    if len(self.file_buffers[status_key]) >= MAX_FILE_BUFFER_LINES:
                        self.file_buffers[status_key] = self.file_buffers[status_key][-2000:]

    def stop(self):
        self.is_running = False