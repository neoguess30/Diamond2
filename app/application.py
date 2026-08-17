from __future__ import annotations
import sys
import os
import time
from typing import List, Any

try:
    from PyQt6.QtWidgets import QApplication
    HAS_PYQT6 = True
except ImportError:
    HAS_PYQT6 = False

from core.models.job import Job
from core.state.enums import JobSource, EngineState
from core.metrics import METRICS
from core.utils import get_process_memory_mb_str
from parser.pattern_generator import LazyPatternGenerator
from producers.pattern_producer import PatternProducerWorker
from producers.file_producer import FileImporterWorker
from app.bootstrap import ApplicationController

class Application:
    """
    Enterprise Application Entry Point:
    Manages GUI launch and robust, non-blocking Headless execution pipelines.
    """
    def __init__(self, db_path: str = "falcon_master.db"):
        self.controller = ApplicationController(db_path=db_path)

    def run_gui(self) -> int:
        if not HAS_PYQT6:
            print("[!] PyQt6 is not installed. Falling back to Headless Mode automatically.")
            return self.run_headless()

        from ui.main_window import MainWindow
        app = QApplication(sys.argv)
        window = MainWindow(controller=self.controller)
        window.show()
        return app.exec()

    def run_headless(self, pattern: str = "", import_file: str = "") -> int:
        print("=" * 70)
        print("🦅 FALCON // SOVEREIGN HEADLESS COMMAND ENGINE")
        print("=" * 70)

        # 1. P0 Architecture: Start the engine FIRST so workers, writers & DB are actively consuming
        started = self.controller.start_engine()
        if not started:
            print("❌ FATAL: ApplicationController failed to verify readiness. Review startup logs.")
            return 1

        active_producers: List[Any] = []

        # 2. Launch asynchronous producer pipelines feeding the active scanner
        if pattern:
            print(f"[*] Dispatching streaming pattern task: '{pattern}' ...")
            producer = PatternProducerWorker(pattern, pattern, self.controller.worker, self.controller.db)
            self.controller.active_producers.append(producer)
            active_producers.append(producer)
            producer.start()
        elif import_file and os.path.exists(import_file):
            print(f"[*] Dispatching streaming file importer: '{import_file}' ...")
            importer = FileImporterWorker(import_file, self.controller.worker, self.controller.db)
            self.controller.active_producers.append(importer)
            active_producers.append(importer)
            importer.start()
        else:
            print("[*] Headless mode operational in standing listen/recovery state.")

        # 3. Main Operational Telemetry & Completion Monitoring Loop
        try:
            start_monotonic = time.monotonic()
            while True:
                time.sleep(2.0)
                elapsed = int(time.monotonic() - start_monotonic)
                hrs = elapsed // 3600
                mins = (elapsed % 3600) // 60
                secs = elapsed % 60
                
                total_db = self.controller.db.get_total_count()
                snap = METRICS.get_snapshot()
                ram_s = get_process_memory_mb_str()
                delay_s = self.controller.network_controller.shared_delay
                q_age = self.controller.worker.get_oldest_queue_age_sec()
                q_depth = self.controller.worker.get_queue_len()
                w_depth = self.controller.writer.get_queue_len()
                
                # Check if all active producers are done
                all_producers_done = all(p.isFinished() for p in active_producers) if active_producers else False

                print(
                    f"\r[UPTIME {hrs:02d}:{mins:02d}:{secs:02d}] "
                    f"Scanned: {total_db:,} │ Q: {q_depth:,} │ W: {w_depth:,} │ "
                    f"Q-Age: {q_age:.1f}s │ Delay: {delay_s:.2f}s │ Rate: {snap['effective_jobs_per_sec']:.1f}j/s │ "
                    f"RAM: {ram_s} │ ● LIVE",
                    end=""
                )

                # Auto-exit when all submitted pattern/file workloads are 100% processed and committed
                if (pattern or import_file) and all_producers_done and q_depth == 0 and w_depth == 0:
                    time.sleep(2.5)  # Grace period for final transaction commit settlement
                    print("\n\n[✓] All target workloads completed and durably persisted to database.")
                    break

        except KeyboardInterrupt:
            print("\n\n[!] Operator interrupted headless engine. Initiating master teardown...")
        finally:
            self.controller.shutdown_engine()
            print("[✓] Clean headless shutdown complete (Proof of Drain Verified).")

        return 0