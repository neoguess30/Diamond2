from __future__ import annotations
import time
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional

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

from core.state.enums import (
    SystemHealthState,
    EngineState,
    RecycleReason
)
from core.metrics import METRICS
from core.utils import get_process_memory_mb_str
from core.logger import logger
from watchdog.checks import SystemInvariantChecker
from watchdog.resource_monitor import ResourceMonitor
from watchdog.health import HealthEvaluator

class SupervisorWorker(QThread):
    """
    Observable Watchdog Health Engine & Worker Supervisor:
    1. Alive check (Detects dead/terminated workers & triggers verified replacement).
    2. Progress & Starvation check (Audits true completed progress).
    3. Heartbeat check (Audits loop activity).
    4. Queue movement & System Invariants check (Includes Paused Pattern Depth & Age).
    5. Self-healing network session recycling WITHOUT masking real job stalls.
    6. Instant Graceful Shutdown via stop_event (Zero 2-second sleep lag).
    7. Automated 6-Hour Database Telemetry & Dead Letter Pruning.
    """
    sig_telemetry = pyqtSignal(dict)
    sig_log = pyqtSignal(str)

    def __init__(self, scanner: Any, network: Any, writer: Any, db: Any, controller: Any = None):
        super().__init__()
        self.scanner = scanner
        self.network = network
        self.writer = writer
        self.db = db
        self.controller = controller
        self.is_running = False
        
        self.health_state = SystemHealthState.HEALTHY
        self.resource_monitor = ResourceMonitor()
        self.consecutive_stalls = 0
        self.last_snapshot_monotonic = time.monotonic()
        
        # P0 Storage Retention: Prune old snapshots and DLQs every 6 hours
        self.last_prune_monotonic = time.monotonic()
        self.prune_interval_sec = 21600.0  # 6 Hours

        self.is_ready_event = threading.Event()
        self.stop_event = threading.Event()

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self.is_ready_event.wait(timeout=timeout)

    def run(self):
        self.is_running = True
        self.is_ready_event.set()

        while self.is_running:
            try:
                stopped = self.stop_event.wait(timeout=2.0)
                if stopped or not self.is_running:
                    break

                now = time.monotonic()
                
                # 1. Sample System Resources (with Slope-Aware Adaptive GC)
                current_ram, current_handles, current_threads = self.resource_monitor.sample_and_record(
                    self.scanner.get_queue_len(),
                    self.writer.get_queue_len()
                )

                engine_in_shutdown = (
                    self.controller is not None and 
                    self.controller.state in (EngineState.STOPPING, EngineState.DRAINING, EngineState.STOPPED, EngineState.STARTUP_BLOCKED)
                )

                # 2. Scanner Worker Liveness Audit
                engine_should_run = (self.controller and self.controller.state == EngineState.RUNNING) if self.controller else False
                if engine_should_run and not self.scanner.isRunning() and not engine_in_shutdown:
                    logger.critical("🚨 SUPERVISOR ALERT: Scanner worker thread is dead while engine is RUNNING! Triggering verified replacement...")
                    self.sig_log.emit(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  🚨 Supervisor: Scanner worker died unexpectedly! Restoring queue & spawning replacement...")
                    self.health_state = SystemHealthState.RECOVERING
                    if self.controller:
                        replaced = self.controller.replace_dead_worker()
                        if replaced:
                            self.sig_log.emit(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  ✅ Supervisor: Replacement worker verified and active.")
                            continue

                # 3. StorageWriter Liveness Audit
                engine_active = (
                    self.controller is not None and 
                    self.controller.state not in (EngineState.STOPPING, EngineState.DRAINING, EngineState.STOPPED, EngineState.STARTUP_BLOCKED)
                )
                if engine_active and not self.writer.isRunning() and not engine_in_shutdown:
                    logger.critical("🚨 SUPERVISOR ALERT: StorageWriter thread is dead! Triggering verified writer replacement...")
                    self.sig_log.emit(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  🚨 Supervisor: StorageWriter thread died! Rebuilding writer, reconnecting DB & draining queue...")
                    self.health_state = SystemHealthState.RECOVERING
                    if self.controller:
                        replaced = self.controller.replace_dead_writer()
                        if replaced:
                            self.sig_log.emit(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  ✅ Supervisor: Replacement StorageWriter verified and active.")
                            continue

                # 4. Invariants & Starvation Audits
                invariants_ok, invariant_report = SystemInvariantChecker.audit_invariants(self.scanner, self.writer, self.db)
                if not invariants_ok:
                    logger.critical(f"CRITICAL INVARIANT VIOLATION: {invariant_report}")
                    self.health_state = SystemHealthState.DEGRADED

                is_starving, starvation_msg = SystemInvariantChecker.audit_worker_starvation(self.scanner)
                if is_starving:
                    logger.warning(f"STARVATION ALERT: {starvation_msg}")
                    self.health_state = SystemHealthState.DEGRADED

                # 5. Health State Evaluation
                short_slope, long_slope = METRICS.calculate_ram_slope_mb_per_hr()
                new_health, time_since_heartbeat, time_since_last_completed = HealthEvaluator.evaluate(
                    self.scanner,
                    self.network,
                    self.db,
                    invariants_ok,
                    is_starving,
                    long_slope
                )
                
                if new_health == SystemHealthState.STALLED:
                    self.consecutive_stalls += 1
                elif new_health == SystemHealthState.HEALTHY:
                    self.consecutive_stalls = 0
                    
                self.health_state = new_health

                # 6. Targeted Watchdog Self-Healing Action
                if self.health_state == SystemHealthState.STALLED and self.consecutive_stalls >= 2 and not engine_in_shutdown:
                    self.sig_log.emit(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  🚨 Watchdog: Scanner stall detected (No progress for {time_since_last_completed:.0f}s) → Requesting cooperative network session recycle...")
                    self.health_state = SystemHealthState.RECOVERING
                    self.network.request_recycle(reason=RecycleReason.RECYCLE_ERRORS)
                    self.scanner.last_heartbeat_monotonic = time.monotonic()
                    self.consecutive_stalls = 0

                # 7. Periodic Health Snapshot to Database (Every 60 seconds)
                oldest_queue_age = self.scanner.get_oldest_queue_age_sec()
                db_mb, wal_mb = self.db.get_db_file_sizes_mb()
                if now - self.last_snapshot_monotonic >= 60.0 and not engine_in_shutdown:
                    snap_data = METRICS.get_snapshot()
                    snap_data["oldest_age_sec"] = oldest_queue_age
                    self.db.save_health_snapshot(snap_data, db_mb, wal_mb)
                    self.last_snapshot_monotonic = now

                # 8. P0 Periodic Database Telemetry Retention Pruning (Every 6 Hours)
                if now - self.last_prune_monotonic >= self.prune_interval_sec and not engine_in_shutdown:
                    pruned_snaps = self.db.prune_old_health_snapshots(retention_days=7)
                    pruned_dlqs = self.db.prune_old_dead_letters(retention_days=30)
                    if pruned_snaps > 0 or pruned_dlqs > 0:
                        self.sig_log.emit(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}  🧹 Database Storage Retention: Pruned {pruned_snaps} telemetry snapshots (>7d) & {pruned_dlqs} dead letters (>30d).")
                    self.last_prune_monotonic = now

                # 9. Emit Real-Time Telemetry
                elapsed = int(time.time() - self.scanner.start_time) if self.scanner.is_running else 0
                hrs = elapsed // 3600
                mins = (elapsed % 3600) // 60
                secs = elapsed % 60
                
                snap = METRICS.get_snapshot()
                session_telemetry = self.network.get_session_telemetry()
                circuit_telemetry = self.network.circuit_breaker.get_telemetry()

                telemetry = {
                    "uptime": f"{hrs:02d}:{mins:02d}:{secs:02d}",
                    "delay": f"{self.network.controller.shared_delay:.2f}s",
                    "queue_depth": self.scanner.get_queue_len(),
                    "writer_queue": self.writer.get_queue_len(),
                    "paused_pattern_depth": snap["paused_pattern_depth"],
                    "oldest_paused_job_age_sec": snap["oldest_paused_job_age_sec"],
                    "health_state": self.health_state.value,
                    "db_health_state": self.db.get_health_state().value,
                    "db_degraded": self.db.is_degraded(),
                    "invariants_ok": invariants_ok,
                    "circuit_state": self.network.circuit_breaker.get_state().value,
                    "circuit_telemetry": circuit_telemetry,
                    "disk_state": self.db.check_disk_health().value,
                    "db_size_mb": db_mb,
                    "wal_size_mb": wal_mb,
                    "oldest_age_sec": oldest_queue_age,
                    "last_completed_age_sec": time_since_last_completed,
                    "ram_str": get_process_memory_mb_str(),
                    "ram_short_slope": short_slope,
                    "ram_long_slope": long_slope,
                    "threads_count": current_threads,
                    "handles_count": current_handles,
                    "p50_ms": snap["p50_ms"],
                    "p95_ms": snap["p95_ms"],
                    "p99_ms": snap["p99_ms"],
                    "breakdown": snap["breakdown"],
                    "deltas_60s": snap["deltas_60s"],
                    "req_per_sec": snap["req_per_sec"],
                    "effective_jobs_per_sec": snap["effective_jobs_per_sec"],
                    "hit_rate_str": snap["hit_rate_str"],
                    "429_count": snap["429"],
                    "dead_letters": snap["dead_letters"],
                    "poison_jobs": snap["poison_jobs"],
                    "db_writes": snap["db_writes"],
                    "session_age_sec": session_telemetry["session_age_sec"],
                    "session_requests": session_telemetry["requests_on_session"],
                    "session_errors": session_telemetry["errors_on_session"],
                    "last_recycle_reason": session_telemetry["last_recycle_reason"],
                    "last_net_success_sec": snap["last_net_success_sec"],
                    "last_scan_success_sec": snap["last_scan_success_sec"],
                    "last_persist_success_sec": snap["last_persist_success_sec"],
                    "worker_jobs_completed": self.scanner.worker_jobs_completed,
                    "worker_busy_sec": self.scanner.worker_busy_time_sec,
                    "worker_idle_sec": self.scanner.worker_idle_time_sec
                }
                self.sig_telemetry.emit(telemetry)

            except Exception as e:
                logger.exception(f"Supervisor Loop Exception: {e}")
                if self.stop_event.wait(timeout=1.0) or not self.is_running:
                    break

    def stop(self):
        self.is_running = False
        self.stop_event.set()