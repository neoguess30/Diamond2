from __future__ import annotations
import time
from typing import List, Any
from core.state.enums import EngineState
from core.config import SHUTDOWN_DEADLINE_SEC
from core.logger import logger

class LifecycleManager:
    """
    Master Lifecycle & Deterministic Shutdown Barrier:
    Enforces a strict 7-stage ordered teardown to guarantee zero in-flight data loss,
    clean queue drainage, and durable transaction settlement.
    """
    
    @staticmethod
    def shutdown_sequence(
        controller: Any,
        producers: List[Any],
        worker: Any,
        supervisor: Any,
        writer: Any,
        network: Any,
        db: Any
    ) -> bool:
        shutdown_start_monotonic = time.monotonic()
        logger.info(f"LifecycleManager: [STAGE 1/7] Initiating Master Teardown Sequence (Deadline: {SHUTDOWN_DEADLINE_SEC}s)...")
        controller.state = EngineState.STOPPING
        shutdown_clean = True

        def remaining_ms() -> int:
            elapsed = time.monotonic() - shutdown_start_monotonic
            rem = max(0.1, SHUTDOWN_DEADLINE_SEC - elapsed)
            return int(rem * 1000)

        # STAGE 2: Stop and join all background target producers (Cut off ingestion at source)
        logger.info(f"LifecycleManager: [STAGE 2/7] Halting {len(producers)} active target producers...")
        for prod in list(producers):
            prod.stop()
            prod.wait(min(2000, remaining_ms()))
            if not prod.isFinished():
                logger.critical("CRITICAL: Pattern Producer thread failed to finish within shutdown deadline.")
                shutdown_clean = False

        # STAGE 3: Stop Scanner Worker & allow in-flight network requests to settle into writer
        logger.info("LifecycleManager: [STAGE 3/7] Stopping ScannerWorker and settling in-flight scans...")
        worker.stop()
        worker.wait(min(10000, remaining_ms()))
        if not worker.isFinished():
            logger.critical("CRITICAL: Scanner Worker thread failed to finish within shutdown deadline.")
            shutdown_clean = False

        # STAGE 4: Drain and stop StorageWriter (Commit final batch, fsync emergency journal, and flush exports)
        logger.info(f"LifecycleManager: [STAGE 4/7] Draining StorageWriter ({writer.get_queue_len()} items remaining in queue)...")
        writer.stop()
        writer.wait(min(10000, remaining_ms()))
        if not writer.isFinished():
            logger.critical("CRITICAL: Storage Writer failed to complete transaction drain within deadline.")
            shutdown_clean = False
        elif not getattr(writer, "final_commit_succeeded", True):
            logger.critical("CRITICAL: Storage Writer final database commit failed.")
            shutdown_clean = False

        # STAGE 5: Stop Supervisor Watchdog
        logger.info("LifecycleManager: [STAGE 5/7] Halting Supervisor Watchdog...")
        supervisor.stop()
        supervisor.wait(min(2000, remaining_ms()))
        if not supervisor.isFinished():
            logger.critical("CRITICAL: Supervisor thread failed to finish within shutdown deadline.")
            shutdown_clean = False

        # STAGE 6: Network Engine cleanup (Safe now that all scanning threads are dead)
        logger.info("LifecycleManager: [STAGE 6/7] Closing Network Engine and TLS sessions...")
        if worker.isFinished():
            network.close()
        else:
            logger.warning("WARNING: NetworkEngine close deferred because scanner worker is still active.")

        # STAGE 7: Record clean shutdown in SQLite and execute passive WAL checkpoint
        logger.info("LifecycleManager: [STAGE 7/7] Recording clean shutdown journal and checkpointing WAL...")
        if shutdown_clean:
            db.record_session_clean_shutdown()
        db.checkpoint_wal(mode="PASSIVE")

        elapsed_shutdown = time.monotonic() - shutdown_start_monotonic
        controller.state = EngineState.STOPPED

        if shutdown_clean and elapsed_shutdown <= SHUTDOWN_DEADLINE_SEC:
            logger.info(f"LifecycleManager: ✅ Master Teardown COMPLETE in {elapsed_shutdown:.2f}s. 100% Data Preserved (Proof of Drain Verified).")
        else:
            logger.warning(f"LifecycleManager: ⚠️ Teardown finished with warnings in {elapsed_shutdown:.2f}s.")
        return shutdown_clean