from __future__ import annotations
import threading
from typing import List, Dict, Any, Optional

from core.config import MAX_ACTIVE_PRODUCERS
from core.logger import logger
from producers.pattern_producer import PatternProducerWorker
from producers.file_producer import FileImporterWorker
from producers.manual_producer import ManualTargetProducer

class ProducerManager:
    """Manages lifecycle, coordination, and bounded budgets across all target producers."""
    def __init__(self, scanner_worker: Any, db: Any):
        self.scanner = scanner_worker
        self.db = db
        self.active_producers: List[Any] = []
        self.manual_producer = ManualTargetProducer(scanner_worker, db)
        self.lock = threading.RLock()

    def register_pattern(self, pattern: str) -> Optional[PatternProducerWorker]:
        with self.lock:
            # Clean finished
            self.active_producers = [p for p in self.active_producers if p.isRunning()]
            
            if len(self.active_producers) >= MAX_ACTIVE_PRODUCERS:
                logger.warning(f"ProducerManager: Cannot start '{pattern}', active limit ({MAX_ACTIVE_PRODUCERS}) reached.")
                return None

            if any(getattr(p, 'pattern', None) == pattern for p in self.active_producers):
                logger.warning(f"ProducerManager: Producer for pattern '{pattern}' already running.")
                return None

            producer = PatternProducerWorker(pattern, pattern, self.scanner, self.db)
            self.active_producers.append(producer)
            producer.start()
            return producer

    def register_file_import(self, file_path: str) -> Optional[FileImporterWorker]:
        with self.lock:
            self.active_producers = [p for p in self.active_producers if p.isRunning()]
            
            if len(self.active_producers) >= MAX_ACTIVE_PRODUCERS:
                logger.warning(f"ProducerManager: Cannot import '{file_path}', active limit reached.")
                return None

            importer = FileImporterWorker(file_path, self.scanner, self.db)
            self.active_producers.append(importer)
            importer.start()
            return importer

    def submit_manual(self, username: str) -> bool:
        return self.manual_producer.submit_target(username)

    def pause_all(self):
        with self.lock:
            for p in self.active_producers:
                if hasattr(p, 'pause'):
                    p.pause()

    def resume_all(self):
        with self.lock:
            for p in self.active_producers:
                if hasattr(p, 'resume'):
                    p.resume()

    def stop_all(self, timeout_ms: int = 2000):
        with self.lock:
            for p in self.active_producers:
                p.stop()
                p.wait(timeout_ms)
            self.active_producers.clear()

    def get_active_count(self) -> int:
        with self.lock:
            self.active_producers = [p for p in self.active_producers if p.isRunning()]
            return len(self.active_producers)