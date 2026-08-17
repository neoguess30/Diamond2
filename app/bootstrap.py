from __future__ import annotations
import time
import threading
import queue
from collections import deque
from typing import List, Callable, Optional, Any

from core.state.enums import EngineState, JobSource, JobStatus, ScanCheckResult, DatabaseHealthState
from core.models.job import Job
from core.queues.inflight import InFlightRegistry
from core.config import MAX_PATTERN_QUEUE
from core.logger import logger
from network.controller import CentralizedNetworkController
from network.client import NetworkEngine
from resilience.circuit_breaker import NetworkCircuitBreaker
from persistence.database import ConsolidatedDatabaseManager
from persistence.writer.storage_writer import StorageWriterWorker
from scanner.worker import ScannerWorker
from watchdog.supervisor import SupervisorWorker
from producers.pattern_producer import PatternProducerWorker
from app.lifecycle import LifecycleManager

class ApplicationController:
    """Decoupled Engine Controller with Dual-Queue Smart Recovery, Emergency Journal Auto-Replay & Fencing Tokens."""
    def __init__(self, db_path: str = "falcon_master.db", initial_delay: float = 1.2):
        self.circuit_breaker = NetworkCircuitBreaker()
        self.network_controller = CentralizedNetworkController(initial_delay=initial_delay)
        self.db = ConsolidatedDatabaseManager(db_path=db_path)
        self.network = NetworkEngine(controller=self.network_controller, circuit_breaker=self.circuit_breaker)
        self.inflight = InFlightRegistry()
        
        self.current_worker_generation = 1
        self.current_writer_generation = 1

        self.writer = StorageWriterWorker(db_path=self.db.db_path, db_manager=self.db)
        self.db.set_writer(self.writer)
        self.worker = ScannerWorker(self.db, self.network, self.inflight, self.writer, generation_id=self.current_worker_generation, controller=self)
        self.supervisor = SupervisorWorker(self.worker, self.network, self.writer, self.db, controller=self)
        
        self.state = EngineState.STOPPED
        self.worker.pause()
        
        self.active_producers: List[PatternProducerWorker] = []
        self.writer_replacement_callbacks: List[Callable[[StorageWriterWorker], None]] = []
        self.worker_replacement_callbacks: List[Callable[[ScannerWorker], None]] = []
        self.lock = threading.RLock()
        
        preflight_ok, preflight_msg = self.db.verify_preflight_health()
        if not preflight_ok:
            logger.critical(f"PREFLIGHT CHECK FAILED: {preflight_msg}")
            self.state = EngineState.STARTUP_BLOCKED
        else:
            logger.info("Pre-flight health check PASSED: All subsystems operational.")
            self.writer.start()
            self.worker.start()
            self.supervisor.start()

            writer_ready = self.writer.wait_ready(timeout=5.0)
            worker_ready = self.worker.wait_ready(timeout=5.0)
            supervisor_ready = self.supervisor.wait_ready(timeout=5.0)

            if not (writer_ready and worker_ready and supervisor_ready):
                logger.critical("CRITICAL: Subsystem readiness handshake timed out during bootstrap.")
                self.state = EngineState.FAILED
            else:
                # P0: Execute 6-Stage Master Recovery (Emergency Journals Replay + SQLite Pending Jobs)
                self._perform_startup_recovery()
                logger.info(f"ApplicationController: Engine initialized with Verified Readiness (Worker Gen #{self.current_worker_generation}).")

    def register_writer_replacement_callback(self, callback: Callable[[StorageWriterWorker], None]):
        self.writer_replacement_callbacks.append(callback)

    def register_worker_replacement_callback(self, callback: Callable[[ScannerWorker], None]):
        self.worker_replacement_callbacks.append(callback)

    def _route_recovered_jobs(self, target_worker: ScannerWorker, jobs: List[Job]):
        now_epoch = time.time()
        now_monotonic = time.monotonic()
        queue_count = 0
        retry_count = 0

        for job in jobs:
            if job.status == JobStatus.RETRYABLE and job.retry_at_epoch > now_epoch:
                delay_remaining = max(0.1, job.retry_at_epoch - now_epoch)
                retry_at_monotonic = now_monotonic + delay_remaining
                pushed = target_worker.retry_manager.push(retry_at_monotonic, job)
                if pushed:
                    retry_count += 1
                else:
                    target_worker.add_job_direct(job)
                    queue_count += 1
            else:
                target_worker.add_job_direct(job)
                queue_count += 1

        logger.info(f"⚡ Recovery Distribution: {queue_count} jobs -> Active Queue | {retry_count} jobs -> Retry Heap")

    def replace_dead_worker(self) -> bool:
        with self.lock:
            if self.state in (EngineState.STOPPING, EngineState.DRAINING, EngineState.STOPPED, EngineState.STARTUP_BLOCKED):
                logger.warning(f"ApplicationController: Refusing worker replacement because engine state is {self.state.value}.")
                return False
            
            old_worker = self.worker
            self.current_worker_generation += 1
            new_gen = self.current_worker_generation
            logger.critical(f"🚨 SUPERVISOR HEALING: Advancing Worker Fencing Epoch to Gen #{new_gen}. Fencing old worker...")
            
            try:
                new_worker = ScannerWorker(
                    self.db, self.network, self.inflight, self.writer,
                    generation_id=new_gen, controller=self
                )
                
                try:
                    transferred_count = 0
                    while not old_worker.queue.empty():
                        try:
                            job = old_worker.queue.get_nowait()
                            new_worker.queue.put_nowait(job)
                            old_worker.queue.task_done()
                            transferred_count += 1
                        except queue.Empty:
                            break
                        except Exception as item_err:
                            logger.warning(f"Error transferring item between worker queues: {item_err}")
                            break
                    if transferred_count > 0:
                        logger.info(f"⚡ SUPERVISOR HEALING: Transferred {transferred_count:,} queued jobs to Gen #{new_gen}.")
                except Exception as qe:
                    logger.warning(f"Worker replacement queue transfer warning: {qe}")

                with old_worker.paused_lock:
                    new_worker.paused_patterns = set(old_worker.paused_patterns)
                    new_worker.cancelled_patterns = set(old_worker.cancelled_patterns)
                    for pat_id, q in old_worker.paused_pattern_queues.items():
                        new_worker.paused_pattern_queues[pat_id] = deque(q, maxlen=MAX_PATTERN_QUEUE)

                with old_worker.retry_lock:
                    new_worker.retry_manager.restore_from_list(old_worker.retry_manager.get_snapshot_list())

                new_worker.worker_jobs_completed = old_worker.worker_jobs_completed
                new_worker.worker_busy_time_sec = old_worker.worker_busy_time_sec
                new_worker.worker_idle_time_sec = old_worker.worker_idle_time_sec
                new_worker.last_completed_job_monotonic = old_worker.last_completed_job_monotonic

                orphaned_inflight = self.inflight.drain_and_clear()
                if orphaned_inflight:
                    logger.warning(f"⚡ SUPERVISOR HEALING: Re-queueing {len(orphaned_inflight)} in-flight job(s)...")
                    for ifj in orphaned_inflight:
                        if self.db.is_scanned(ifj.username) != ScanCheckResult.FOUND:
                            requeued_job = Job(
                                job_id=ifj.job_id,
                                username=ifj.username,
                                pattern_id=ifj.pattern_id,
                                source=JobSource.RECOVERY,
                                attempt=ifj.attempt,
                                correlation_id=ifj.correlation_id,
                                status=JobStatus.QUEUED,
                                generation_id=new_gen,
                                created_monotonic=ifj.created_monotonic
                            )
                            new_worker.add_job_direct(requeued_job)

                uncompleted_db_jobs = self.db.recover_abandoned_jobs_on_startup()
                if uncompleted_db_jobs:
                    existing_queued_ids = set()
                    try:
                        with new_worker.queue.mutex:
                            existing_queued_ids.update(j.job_id for j in new_worker.queue.queue if hasattr(j, 'job_id'))
                        with new_worker.retry_lock:
                            existing_queued_ids.update(j.job_id for _, j in new_worker.retry_manager.heap if hasattr(j, 'job_id'))
                    except Exception:
                        pass
                    
                    jobs_to_route = [j for j in uncompleted_db_jobs if j.job_id not in existing_queued_ids]
                    if jobs_to_route:
                        self._route_recovered_jobs(new_worker, jobs_to_route)

                self.worker = new_worker
                self.supervisor.scanner = new_worker

                for cb in self.worker_replacement_callbacks:
                    try:
                        cb(new_worker)
                    except Exception as cb_err:
                        logger.error(f"Error invoking worker replacement callback: {cb_err}")

                if self.state == EngineState.RUNNING:
                    new_worker.resume()
                else:
                    new_worker.pause()

                new_worker.start()

                if not new_worker.wait_ready(timeout=5.0):
                    logger.critical("❌ Replacement ScannerWorker failed readiness handshake.")
                    return False

                logger.info(f"✅ SUPERVISOR HEALING: Replacement ScannerWorker Gen #{new_gen} verified and active.")
                return True
            except Exception as e:
                logger.critical(f"❌ Worker Replacement Failed: {e}")
                return False

    def replace_dead_writer(self) -> bool:
        with self.lock:
            if self.state in (EngineState.STOPPING, EngineState.DRAINING, EngineState.STOPPED, EngineState.STARTUP_BLOCKED):
                logger.warning(f"ApplicationController: Refusing writer replacement because engine state is {self.state.value}.")
                return False
            
            old_writer = self.writer
            self.current_writer_generation += 1
            new_writer_gen = self.current_writer_generation
            logger.critical(f"🚨 SUPERVISOR HEALING: Advancing Writer Epoch to Gen #{new_writer_gen}. Initiating replacement...")
            
            try:
                new_writer = StorageWriterWorker(db_path=self.db.db_path, db_manager=self.db)
                
                in_flight_recovered = old_writer.drain_in_flight_uncommitted()
                for rec in in_flight_recovered:
                    new_writer.result_queue.put_nowait(rec)
                if in_flight_recovered:
                    logger.info(f"⚡ SUPERVISOR HEALING: Salvaged {len(in_flight_recovered)} in-flight uncommitted records.")

                transferred_count = 0
                try:
                    while not old_writer.result_queue.empty():
                        try:
                            item = old_writer.result_queue.get_nowait()
                            new_writer.result_queue.put_nowait(item)
                            old_writer.result_queue.task_done()
                            transferred_count += 1
                        except queue.Empty:
                            break
                        except Exception as q_err:
                            logger.warning(f"Error transferring item between writer queues: {q_err}")
                            break
                    if transferred_count > 0:
                        logger.info(f"⚡ SUPERVISOR HEALING: Transferred {transferred_count:,} queued items.")
                except Exception as qe:
                    logger.warning(f"StorageWriter replacement queue transfer warning: {qe}")

                if hasattr(old_writer, 'file_buffers') and old_writer.file_buffers:
                    for k, v in old_writer.file_buffers.items():
                        new_writer.file_buffers[k].extend(v)

                if hasattr(old_writer, 'sequence_counter') and old_writer.sequence_counter > 0:
                    new_writer.sequence_counter = old_writer.sequence_counter

                self.writer = new_writer
                self.db.set_writer(new_writer)
                self.worker.writer = new_writer
                self.supervisor.writer = new_writer

                for cb in self.writer_replacement_callbacks:
                    try:
                        cb(new_writer)
                    except Exception as cb_err:
                        logger.error(f"Error invoking writer replacement callback: {cb_err}")

                new_writer.start()

                if not new_writer.wait_ready(timeout=5.0):
                    logger.critical("❌ Replacement StorageWriter failed readiness handshake.")
                    return False

                self.db.report_write_success()
                logger.info(f"✅ SUPERVISOR HEALING: Replacement StorageWriter Gen #{new_writer_gen} verified and active.")
                return True
            except Exception as e:
                logger.critical(f"❌ StorageWriter Replacement Failed: {e}")
                return False

    def _perform_startup_recovery(self):
        """
        P0 6-Stage Master Startup Recovery:
        1. Pre-flight & DB Health Verified.
        2. Replay & Ingest Emergency Journal Chunks from previous session crashes.
        3. Restore all Pending Jobs from SQLite Checkpoint.
        4. Reconstruct in-memory queues with Dual-Queue Smart Dispatcher.
        """
        # 1. P0: Replay Emergency Journal files from previous crashes into SQLite FIRST
        if hasattr(self.writer, 'emergency_mgr') and self.writer.emergency_mgr:
            try:
                restored, quarantined = self.writer.emergency_mgr.replay_and_restore_journals(self.db)
                if restored > 0 or quarantined > 0:
                    logger.info(f"⚡ Emergency Journal Replay on Startup: {restored} records restored to DB | {quarantined} quarantined.")
            except Exception as e:
                logger.error(f"Emergency Journal Replay Exception on startup: {e}")

        # 2. Recover all pending jobs and route to Active Queue or Retry Heap
        abandoned_jobs = self.db.recover_abandoned_jobs_on_startup()
        if abandoned_jobs:
            self._route_recovered_jobs(self.worker, abandoned_jobs)

    def start_engine(self) -> bool:
        with self.lock:
            if self.state == EngineState.STARTUP_BLOCKED:
                logger.error("Cannot start engine: Pre-flight check was blocked.")
                return False
            if self.state == EngineState.RUNNING:
                return True

            self.state = EngineState.STARTING
            logger.info("ApplicationController: Engine transitioning to STARTING... Verifying subsystem readiness.")

            if not self.writer.isRunning() or not self.worker.isRunning() or not self.supervisor.isRunning():
                logger.error("Cannot start engine: One or more core pipeline threads are not running.")
                self.state = EngineState.DEGRADED
                return False

            if self.db.get_health_state() != DatabaseHealthState.HEALTHY:
                logger.error(f"Cannot start engine: Database health state is {self.db.get_health_state().value}.")
                self.state = EngineState.DEGRADED
                return False

            self.worker.resume()
            self.state = EngineState.RUNNING
            logger.info("ApplicationController: All subsystem verifications PASSED. Engine is now RUNNING.")
            return True

    def pause_engine(self):
        with self.lock:
            self.state = EngineState.PAUSING
            self.worker.pause()
            self.active_producers = [p for p in self.active_producers if not p.isFinished()]
            for prod in self.active_producers:
                if hasattr(prod, 'pause'):
                    prod.pause()
            self.state = EngineState.PAUSED
            logger.info("ApplicationController: Engine paused (State: PAUSED).")

    def resume_engine(self):
        with self.lock:
            if self.state == EngineState.STARTUP_BLOCKED:
                return
            self.worker.resume()
            self.active_producers = [p for p in self.active_producers if not p.isFinished()]
            for prod in self.active_producers:
                if hasattr(prod, 'resume'):
                    prod.resume()
            self.state = EngineState.RUNNING
            logger.info("ApplicationController: Engine resumed (State: RUNNING).")

    def shutdown_engine(self) -> bool:
        with self.lock:
            return LifecycleManager.shutdown_sequence(
                controller=self,
                producers=self.active_producers,
                worker=self.worker,
                supervisor=self.supervisor,
                writer=self.writer,
                network=self.network,
                db=self.db
            )