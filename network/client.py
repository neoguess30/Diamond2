from __future__ import annotations
import time
import threading
import email.utils
from urllib.parse import urljoin
from datetime import datetime, timezone
from typing import Tuple, Dict, Optional, Any

from core.errors.categories import ErrorCategory
from core.metrics import METRICS
from core.logger import logger
from core.config import (
    MAX_RESPONSE_BYTES,
    MAX_HTTP_REDIRECTS
)
from resilience.circuit_breaker import NetworkCircuitBreaker
from resilience.deadlines import DeadlineManager
from resilience.failure_classifier import FailureClassifier
from network.rate_limiter import TokenBucketRateLimiter
from network.headers import get_standard_headers
from network.validator import is_safe_fragment_url
from network.controller import CentralizedNetworkController
from network.session import SessionLifecycleManager, HAS_CURL_CFFI, curl_requests

def parse_retry_after_header(header_value: Optional[str]) -> Optional[float]:
    if not header_value:
        return None
    val = header_value.strip()
    if val.isdigit():
        return max(1.0, float(val))
    try:
        parsed_tuple = email.utils.parsedate_tz(val)
        if parsed_tuple:
            target_ts = email.utils.mktime_tz(parsed_tuple)
            diff = target_ts - time.time()
            return max(1.0, diff)
    except Exception:
        pass
    return None

class NetworkEngine:
    """
    Production Network Engine:
    1. Deadlock-Free Circuit Breaker Probe Management.
    2. Strict RFC 7231 Retry-After Parsing and Cooldown Alignment.
    3. Dynamic Per-Hop Deadline Propagation across redirects.
    4. Rate Limiting with Instant Wakeup Cancellation.
    5. Bounded Streaming Reception & Response Size Cap.
    """
    def __init__(
        self,
        controller: Optional[CentralizedNetworkController] = None,
        circuit_breaker: Optional[NetworkCircuitBreaker] = None
    ):
        self.controller = controller or CentralizedNetworkController()
        self.circuit_breaker = circuit_breaker or NetworkCircuitBreaker()
        self.rate_limiter = TokenBucketRateLimiter()
        self.session_mgr = SessionLifecycleManager(browser_profile="chrome131")

    def request_recycle(self, reason=None):
        if reason:
            self.session_mgr.request_recycle(reason)
        else:
            self.session_mgr.request_recycle()

    def fetch(
        self,
        username: str,
        correlation_id: str = "",
        remaining_deadline_sec: float = 60.0,
        cancel_event: Optional[threading.Event] = None
    ) -> Tuple[int, bytes, Dict[str, str], float, ErrorCategory]:
        if not HAS_CURL_CFFI or curl_requests is None:
            return 0, b"", {}, 0.0, ErrorCategory.NETWORK_FATAL

        if not self.circuit_breaker.can_execute():
            return 0, b"", {}, 0.0, ErrorCategory.CIRCUIT_OPEN

        # P0 Probe Guard: Rate limiter acquire
        acquired = self.rate_limiter.acquire(
            timeout=min(2.0, remaining_deadline_sec),
            cancel_event=cancel_event
        )
        if not acquired:
            self.circuit_breaker.abort_probe(reopen=False, reason="RATE_LIMIT_ACQUIRE_TIMEOUT")
            return 0, b"", {}, 0.0, ErrorCategory.NETWORK_TRANSIENT

        if cancel_event is not None and cancel_event.is_set():
            self.circuit_breaker.abort_probe(reopen=False, reason="CANCEL_EVENT_SET")
            return 0, b"", {}, 0.0, ErrorCategory.NETWORK_TRANSIENT

        self.session_mgr.check_and_recycle()

        initial_url = f"https://fragment.com/username/{username}"
        current_url = initial_url
        redirect_hops = 0
        max_hops = MAX_HTTP_REDIRECTS

        start_t = time.monotonic()
        deadline_horizon = start_t + remaining_deadline_sec
        headers = get_standard_headers()

        while True:
            now_m = time.monotonic()

            if cancel_event is not None and cancel_event.is_set():
                self.circuit_breaker.abort_probe(reopen=False, reason="CANCEL_DURING_HOPS")
                return 0, b"", {}, 0.0, ErrorCategory.NETWORK_TRANSIENT

            hop_remaining_deadline = deadline_horizon - now_m
            if hop_remaining_deadline <= 0.2:
                latency = (now_m - start_t) * 1000
                logger.warning(
                    f"[{correlation_id}] Request deadline exhausted ({remaining_deadline_sec:.1f}s budget) across redirect hops for @{username}"
                )
                METRICS.record_network_request(latency, 0)
                self.circuit_breaker.record_failure()
                self.session_mgr.record_timeout()
                return 0, b"", {}, latency, ErrorCategory.TIMEOUT

            hop_timeouts = DeadlineManager.calculate_network_timeouts(hop_remaining_deadline)

            is_safe, reason_msg = is_safe_fragment_url(current_url)
            if not is_safe:
                latency = (time.monotonic() - start_t) * 1000
                logger.error(f"[{correlation_id}] 🛑 Insecure redirect rejected for @{username}: {current_url} ({reason_msg})")
                METRICS.record_network_request(latency, 403)
                self.circuit_breaker.abort_probe(reopen=True, reason="INSECURE_REDIRECT")
                return 403, b"", {}, latency, ErrorCategory.NETWORK_FATAL

            active_session = self.session_mgr.get_session()
            if not active_session:
                self.circuit_breaker.abort_probe(reopen=False, reason="SESSION_NONE")
                return 0, b"", {}, 0.0, ErrorCategory.NETWORK_FATAL

            try:
                resp = active_session.get(
                    current_url, headers=headers, timeout=hop_timeouts, allow_redirects=False, stream=True
                )

                # Check for HTTP Redirects
                if resp.status_code in (301, 302, 303, 307, 308):
                    resp.close()
                    location = resp.headers.get("Location")
                    if not location:
                        latency = (time.monotonic() - start_t) * 1000
                        logger.warning(f"[{correlation_id}] Redirect status {resp.status_code} missing Location header for @{username}")
                        self.circuit_breaker.abort_probe(reopen=False, reason="MISSING_LOCATION")
                        return resp.status_code, b"", dict(resp.headers), latency, ErrorCategory.HTTP_4XX

                    next_url = urljoin(current_url, location.strip())
                    redirect_hops += 1
                    if redirect_hops > max_hops:
                        latency = (time.monotonic() - start_t) * 1000
                        logger.warning(f"[{correlation_id}] Maximum redirect hops ({max_hops}) exceeded for @{username}")
                        self.circuit_breaker.abort_probe(reopen=False, reason="MAX_REDIRECTS")
                        return 310, b"", dict(resp.headers), latency, ErrorCategory.NETWORK_FATAL

                    logger.info(f"[{correlation_id}] ↪️ Safe Redirect #{redirect_hops} for @{username} -> {next_url}")
                    current_url = next_url
                    continue

                # Content-Length Guard
                cl_header = resp.headers.get("Content-Length")
                if cl_header and cl_header.isdigit() and int(cl_header) > MAX_RESPONSE_BYTES:
                    resp.close()
                    latency = (time.monotonic() - start_t) * 1000
                    logger.warning(f"[{correlation_id}] Response Content-Length ({cl_header} bytes) exceeded {MAX_RESPONSE_BYTES} bytes cap for @{username}.")
                    METRICS.record_network_request(latency, 413)
                    self.circuit_breaker.abort_probe(reopen=False, reason="CONTENT_LENGTH_EXCEEDED")
                    return 413, b"", dict(resp.headers), latency, ErrorCategory.RESPONSE_TOO_LARGE

                # Bounded Streaming Reception
                body_chunks = []
                received_bytes = 0
                payload_exceeded = False

                try:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if cancel_event is not None and cancel_event.is_set():
                            payload_exceeded = True
                            break
                        if not chunk:
                            continue
                        received_bytes += len(chunk)
                        if received_bytes > MAX_RESPONSE_BYTES:
                            payload_exceeded = True
                            break
                        body_chunks.append(chunk)
                finally:
                    resp.close()

                latency = (time.monotonic() - start_t) * 1000
                
                if payload_exceeded:
                    if cancel_event is not None and cancel_event.is_set():
                        self.circuit_breaker.abort_probe(reopen=False, reason="STREAM_CANCELLED")
                        return 0, b"", {}, latency, ErrorCategory.NETWORK_TRANSIENT
                    logger.warning(f"[{correlation_id}] Streamed response payload exceeded {MAX_RESPONSE_BYTES} bytes cap for @{username}.")
                    METRICS.record_network_request(latency, 413)
                    self.circuit_breaker.abort_probe(reopen=False, reason="STREAM_PAYLOAD_EXCEEDED")
                    return 413, b"", dict(resp.headers), latency, ErrorCategory.RESPONSE_TOO_LARGE

                content = b"".join(body_chunks)
                METRICS.record_network_request(latency, resp.status_code)
                
                # Parse Retry-After header on 429
                retry_after_sec = parse_retry_after_header(resp.headers.get("Retry-After"))
                self.controller.report_response(resp.status_code, latency, retry_after_sec=retry_after_sec)

                # Settle Probe & Circuit States Deterministically
                if resp.status_code in (200, 404):
                    self.session_mgr.record_success(received_bytes)
                    self.circuit_breaker.record_success()
                    return resp.status_code, content, dict(resp.headers), latency, ErrorCategory.NETWORK_TRANSIENT
                elif resp.status_code == 429:
                    self.session_mgr.record_429()
                    self.circuit_breaker.record_failure(is_429=True, retry_after_sec=retry_after_sec)
                    return resp.status_code, content, dict(resp.headers), latency, ErrorCategory.HTTP_429
                elif 500 <= resp.status_code <= 599:
                    self.session_mgr.record_5xx()
                    self.circuit_breaker.record_failure()
                    return resp.status_code, content, dict(resp.headers), latency, ErrorCategory.HTTP_5XX
                else:
                    # Client errors (e.g. 400, 403)
                    self.session_mgr.record_connection_error()
                    self.circuit_breaker.abort_probe(reopen=False, reason=f"HTTP_{resp.status_code}")
                    return resp.status_code, content, dict(resp.headers), latency, ErrorCategory.HTTP_4XX

            except Exception as e:
                latency = (time.monotonic() - start_t) * 1000
                METRICS.record_network_request(latency, 0)
                self.controller.report_response(0, latency)
                
                category = FailureClassifier.classify_exception(e)
                if category == ErrorCategory.TIMEOUT:
                    self.session_mgr.record_timeout()
                else:
                    self.session_mgr.record_connection_error()
                    
                self.circuit_breaker.record_failure()

                logger.debug(f"[{correlation_id}] Network Request Error for @{username} [{category.value}]: {e}")
                self.session_mgr.check_and_recycle()
                return 0, b"", {}, latency, category

    def get_session_telemetry(self) -> Dict[str, Any]:
        return self.session_mgr.get_telemetry()

    def get_jittered_delay(self, attempt: int = 0) -> float:
        return self.controller.get_delay_with_jitter(attempt)

    def close(self):
        self.rate_limiter.shutdown()
        self.session_mgr.close()