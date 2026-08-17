from __future__ import annotations
from typing import Dict, Any, Optional

from core.models.job import Job
from core.state.enums import JobSource
from core.metrics import METRICS
from scanner.worker import ScannerWorker
from persistence.database import ConsolidatedDatabaseManager
from network.client import NetworkEngine
from core.queues.inflight import InFlightRegistry
from persistence.writer.storage_writer import StorageWriterWorker

class LiveScannerEngine:
    """Facade providing a clean high-level interface over the underlying ScannerWorker pipeline."""
    def __init__(
        self,
        db: ConsolidatedDatabaseManager,
        network: NetworkEngine,
        inflight: InFlightRegistry,
        writer: StorageWriterWorker
    ):
        self.db = db
        self.network = network
        self.inflight = inflight
        self.writer = writer
        self.worker = ScannerWorker(db, network, inflight, writer)

    def start(self):
        if not self.worker.isRunning():
            self.worker.start()
        self.worker.resume()

    def pause(self):
        self.worker.pause()

    def resume(self):
        self.worker.resume()

    def stop(self):
        self.worker.stop()

    def submit(self, username: str, pattern_id: str = "", source: JobSource = JobSource.PATTERN, timeout: float = 2.0) -> bool:
        return self.worker.add_to_queue(username, pattern_id=pattern_id, source=source, timeout=timeout)

    def submit_job(self, job: Job, timeout: float = 2.0) -> bool:
        return self.worker.add_job_direct(job, timeout=timeout)

    def pause_pattern(self, pattern_id: str):
        self.worker.pause_pattern(pattern_id)

    def resume_pattern(self, pattern_id: str):
        self.worker.resume_pattern(pattern_id)

    def remove_pattern(self, pattern_id: str) -> int:
        return self.worker.remove_pattern(pattern_id)

    def get_queue_depth(self) -> int:
        return self.worker.get_queue_len()

    def stats(self) -> Dict[str, Any]:
        snap = METRICS.get_snapshot()
        snap["queue_depth"] = self.get_queue_depth()
        snap["writer_queue_depth"] = self.writer.get_queue_len()
        snap["in_flight_count"] = self.inflight.get_in_flight_count()
        return snap