from __future__ import annotations
import threading
import uuid
import time
from typing import Dict, List, Optional
from core.models.job import InFlightJob

class InFlightRegistry:
    def __init__(self):
        self.lock = threading.RLock()
        self.in_flight_jobs: Dict[str, InFlightJob] = {}

    def register(self, username: str, job_id: str = "", correlation_id: str = "", pattern_id: str = "", attempt: int = 0) -> Optional[str]:
        uname = username.lower().strip().replace("@", "")
        with self.lock:
            if uname in self.in_flight_jobs:
                return None
            final_job_id = job_id or f"job_{uname}_{uuid.uuid4().hex[:8]}"
            final_corr_id = correlation_id or f"corr_{uuid.uuid4().hex[:8]}"
            self.in_flight_jobs[uname] = InFlightJob(
                job_id=final_job_id,
                username=uname,
                correlation_id=final_corr_id,
                pattern_id=pattern_id,
                attempt=attempt,
                created_monotonic=time.monotonic()
            )
            return final_job_id

    def unregister(self, username: str):
        uname = username.lower().strip().replace("@", "")
        with self.lock:
            self.in_flight_jobs.pop(uname, None)

    def is_in_flight(self, username: str) -> bool:
        uname = username.lower().strip().replace("@", "")
        with self.lock:
            return uname in self.in_flight_jobs

    def drain_and_clear(self) -> List[InFlightJob]:
        with self.lock:
            jobs = list(self.in_flight_jobs.values())
            self.in_flight_jobs.clear()
            return jobs

    def get_in_flight_count(self) -> int:
        with self.lock:
            return len(self.in_flight_jobs)
