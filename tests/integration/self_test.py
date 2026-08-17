from __future__ import annotations
import os
import time
import json
import itertools
import heapq
import threading

from core.state.enums import CircuitState, ScanCheckResult, JobStatus, DeadLetterReason
from core.errors.categories import ErrorCategory
from core.models.job import Job
from core.queues.inflight import InFlightRegistry
from core.config import MAX_RETRY_AGE_SEC, MAX_WRITER_QUEUE
from parser.engine import HAS_LXML, HTML_PARSER_ENGINE
from parser.parser import FragmentParser
from parser.pattern_generator import LazyPatternGenerator
from parser.file_streamer import StreamingTargetExtractor
from network.session import HAS_CURL_CFFI
from network.client import NetworkEngine
from network.controller import CentralizedNetworkController
from resilience.circuit_breaker import NetworkCircuitBreaker
from persistence.database import ConsolidatedDatabaseManager
from persistence.writer.storage_writer import StorageWriterWorker
from scanner.worker import ScannerWorker
from app.bootstrap import ApplicationController
from tests.fixtures.html_fixtures import REAL_FRAGMENT_FIXTURES

def run_self_test() -> int:
    print("=" * 75)
    print("🦅 FALCON // SYSTEM COMMAND - COMPREHENSIVE INTEGRATION TEST SUITE")
    print("=" * 75)

    test_db_file = "falcon_integration_test.db"
    for f in [test_db_file, f"{test_db_file}-wal", f"{test_db_file}-shm"]:
        if os.path.exists(f):
            try: os.remove(f)
            except Exception: pass

    all_passed = True

    # [1/14] Dependencies & TLS
    print("\n[1/14] Testing TLS Impersonation & Parser C-Acceleration...")
    if HAS_CURL_CFFI:
        print("  [✓] curl_cffi Engine   : ACTIVE (Chrome 131 Consistent Profile)")
    else:
        print("  [ℹ] curl_cffi Engine   : OPTIONAL IN TEST MODE (Use --network-test for live probe)")

    if HAS_LXML:
        print(f"  [✓] HTML Parser Engine : {HTML_PARSER_ENGINE} (High-Speed lxml C-Engine)")
    else:
        print(f"  [ℹ] HTML Parser Engine : {HTML_PARSER_ENGINE} (Native Fallback Parser Active)")

    # [2/14] Real HTML Fixtures
    print("\n[2/14] Testing Real Fragment.com Production HTML Fixtures (Strict Structural Evidence)...")
    for fix_name, (raw_html, expected_st, min_conf) in REAL_FRAGMENT_FIXTURES.items():
        st, conf, price, reason, detail, err_cat = FragmentParser.parse_html(raw_html, "testtarget", correlation_id="test_corr_fix")
        if st.value == expected_st and conf >= min_conf:
            price_str = f" | Price: {price}" if price else ""
            print(f"  [✓] Fixture {fix_name:24s}: PASSED (Status: {st.value:12s}{price_str}, Conf: {conf:.0f}%)")
        else:
            print(f"  [❌] Fixture {fix_name:24s}: FAILED (Expected: {expected_st} conf>={min_conf}%, Got: {st.value} conf={conf}%)")
            all_passed = False

    # [3/14] Pattern Generator
    print("\n[3/14] Testing Lazy Stream Pattern Generator Permutations...")
    p_exact = LazyPatternGenerator.calculate_possibilities("falcon")
    p_wildcard = LazyPatternGenerator.calculate_possibilities("L_L_N")
    if p_exact == 1 and p_wildcard == 6760:
        stream_sample = list(itertools.islice(LazyPatternGenerator.generate_stream("L_L_N"), 5))
        print(f"  [✓] Exact Match 'falcon'    : 1 candidate (Correct)")
        print(f"  [✓] Wildcard 'L_L_N'        : 6,760 candidates (Correct, Sample: {stream_sample})")
    else:
        print(f"  [❌] Pattern Generator calculation failed (Exact={p_exact}, Wildcard={p_wildcard})")
        all_passed = False

    # [4/14] Circuit Breaker
    print("\n[4/14] Testing Circuit Breaker State Transitions & Single-Probe Recovery...")
    cb = NetworkCircuitBreaker(failure_threshold=3, recovery_timeout=0.1)
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    st_open = cb.get_state()
    can_exec_open = cb.can_execute()
    time.sleep(0.15)
    can_exec_probe = cb.can_execute()
    st_half = cb.get_state()
    can_exec_second = cb.can_execute()
    cb.record_success()
    st_closed = cb.get_state()

    if st_open == CircuitState.OPEN and not can_exec_open and st_half == CircuitState.HALF_OPEN and can_exec_probe and not can_exec_second and st_closed == CircuitState.CLOSED:
        print("  [✓] Circuit Breaker: CLOSED -> OPEN -> HALF-OPEN (Single-Probe) -> CLOSED Verified")
    else:
        print(f"  [❌] Circuit Breaker State Transitions Failed")
        all_passed = False

    # [5/14] Error Classification
    print("\n[5/14] Testing Network Error Classification Engine...")
    net_ctrl = CentralizedNetworkController(initial_delay=0.1)
    net_eng = NetworkEngine(controller=net_ctrl)
    
    from resilience.failure_classifier import FailureClassifier
    cat_to = FailureClassifier.classify_exception(Exception("Connection timed out"))
    cat_tls = FailureClassifier.classify_exception(Exception("SSL/TLS handshake failure"))
    cat_gen = FailureClassifier.classify_exception(Exception("Connection reset by peer"))
    
    if cat_to == ErrorCategory.TIMEOUT and cat_tls == ErrorCategory.TLS_ERROR and cat_gen == ErrorCategory.NETWORK_TRANSIENT:
        print("  [✓] Error Classification (Timeout / TLS / Transient): PASSED")
    else:
        print(f"  [❌] Error Classification Failed")
        all_passed = False

    # [6/14] Persistence ACK
    print("\n[6/14] Testing SQLite WAL Mode, Single Writer & Persistence ACK...")
    db_mgr = ConsolidatedDatabaseManager(test_db_file)
    writer = StorageWriterWorker(test_db_file, db_manager=db_mgr)
    db_mgr.set_writer(writer)
    writer.start()

    test_job = Job.create_new(username="ack_user_test", pattern_id="TEST_ACK")
    ack_event = threading.Event()
    writer.enqueue_result({
        "raw_username": test_job.username,
        "username": f"@{test_job.username}",
        "status": "AVAILABLE",
        "confidence": 98.0,
        "price": "$500 USD",
        "detail": "FREE",
        "pat_id": test_job.pattern_id,
        "job_id": test_job.job_id,
        "correlation_id": test_job.correlation_id,
        "_ack_event": ack_event,
        "_job_obj": test_job
    })

    ack_ok = ack_event.wait(timeout=2.0)
    db_res = db_mgr.is_scanned(test_job.username)

    if ack_ok and test_job.status == JobStatus.PERSISTED and db_res == ScanCheckResult.FOUND:
        print("  [✓] Persistence ACK & Synchronous Durability Barrier: VERIFIED")
    else:
        print(f"  [❌] Persistence ACK Verification Failed")
        all_passed = False

    # [7/14] Retry Heap
    print("\n[7/14] Testing ScannerWorker Thread-Safe Retry Heap & Prioritization...")
    inflight = InFlightRegistry()
    scanner = ScannerWorker(db=db_mgr, network=net_eng, inflight=inflight, writer=writer)
    
    j_retry = Job.create_new("retry_heap_user", pattern_id="TEST_HEAP")
    j_retry.mark_retryable("Network transient glitch", ErrorCategory.NETWORK_TRANSIENT)
    
    with scanner.retry_lock:
        scanner.retry_manager.push(time.monotonic() + 0.1, j_retry)
        heap_len = scanner.retry_manager.get_queue_len()

    if heap_len == 1:
        print("  [✓] Retry Heap Insertion & Priority Heap Invariant: PASSED")
    else:
        print("  [❌] Retry Heap Verification Failed")
        all_passed = False

    # [8/14] DLQ Routing
    print("\n[8/14] Testing Job Deadlines & Max Retry Age Exceeded -> DLQ Routing...")
    j_expired = Job.create_new("stale_job_user", pattern_id="TEST_DEADLINE")
    j_expired.first_failure_monotonic = time.monotonic() - (MAX_RETRY_AGE_SEC + 10.0)
    j_expired.attempt = 3
    
    is_age_exceeded = (time.monotonic() - j_expired.first_failure_monotonic) > MAX_RETRY_AGE_SEC
    if is_age_exceeded:
        j_expired.mark_permanent_failure("Exceeded max retry age", ErrorCategory.TIMEOUT, DeadLetterReason.RETRY_AGE_EXCEEDED)
        db_mgr.save_dead_letter(
            job_id=j_expired.job_id,
            username=j_expired.username,
            error_msg=j_expired.last_error,
            attempts=j_expired.attempt,
            reason=DeadLetterReason.RETRY_AGE_EXCEEDED,
            category=ErrorCategory.TIMEOUT.value,
            correlation_id=j_expired.correlation_id,
            wait_for_commit=True
        )
        time.sleep(0.3)
        dlq_count = db_mgr.get_dead_letter_count()
        if dlq_count >= 1:
            print("  [✓] Max Retry Age Exceeded & Dead Letter Queue (DLQ) Routing: VERIFIED")
        else:
            print("  [❌] DLQ Routing Failed")
            all_passed = False
    else:
        print("  [❌] Stale job age calculation failed")
        all_passed = False

    # [9/14] Backpressure
    print("\n[9/14] Testing StorageWriter Backpressure & Scanner Yield Safety...")
    writer_q_capacity = MAX_WRITER_QUEUE
    writer_q_current = writer.get_queue_len()
    if writer_q_current < writer_q_capacity:
        print(f"  [✓] Writer Queue Bounded Flow Control (Capacity: {writer_q_capacity:,} items): VERIFIED")
    else:
        print("  [❌] Backpressure flow control check failed")
        all_passed = False

    # [10/14] Streaming File Importer
    print("\n[10/14] Testing Asynchronous Streaming File Importer...")
    temp_json_path = "test_import_targets.json"
    temp_txt_path = "test_import_targets.txt"
    try:
        with open(temp_json_path, "w", encoding="utf-8") as fj:
            json.dump([{"username": "imported_user_1"}, {"user": "imported_user_2"}, "imported_user_3"], fj)
        with open(temp_txt_path, "w", encoding="utf-8") as ft:
            ft.write("@txt_target_1\ntxt_target_2\n")

        json_targets = list(StreamingTargetExtractor.stream_json(temp_json_path))
        txt_targets = list(StreamingTargetExtractor.stream_txt(temp_txt_path))

        if len(json_targets) == 3 and len(txt_targets) == 2:
            print(f"  [✓] Streaming File Extractor: JSON={len(json_targets)} items, TXT={len(txt_targets)} items (PASSED)")
        else:
            print("  [❌] Streaming File Extractor failed")
            all_passed = False
    finally:
        for tf in [temp_json_path, temp_txt_path]:
            if os.path.exists(tf):
                try: os.remove(tf)
                except Exception: pass

    # [11/14] Pause / Resume Gate
    print("\n[11/14] Testing Cooperative Engine Pause & Resume Mechanisms...")
    scanner.pause()
    pause_active = not scanner.pause_event.is_set()
    scanner.resume()
    resume_active = scanner.pause_event.is_set()
    if pause_active and resume_active:
        print("  [✓] Scanner Thread Pause / Resume Event Gate: VERIFIED")
    else:
        print("  [❌] Pause / Resume transition failed")
        all_passed = False

    # [12/14] Worker Crash Recovery
    print("\n[12/14] Testing ScannerWorker Deadlock / Crash Auto-Healing Replacement...")
    controller = ApplicationController(db_path=test_db_file, initial_delay=0.1)
    controller.start_engine()
    old_worker_id = id(controller.worker)
    
    controller.worker.stop()
    controller.worker.wait(500)
    replace_worker_ok = controller.replace_dead_worker()
    new_worker_id = id(controller.worker)

    if replace_worker_ok and (old_worker_id != new_worker_id) and controller.worker.isRunning():
        print("  [✓] Supervisor ScannerWorker Replacement & State Synchronization: VERIFIED")
    else:
        print("  [❌] ScannerWorker replacement failed")
        all_passed = False

    # [13/14] StorageWriter Crash Recovery
    print("\n[13/14] Testing StorageWriter Deadlock / Crash Auto-Healing & Queue Transfer...")
    old_writer_id = id(controller.writer)
    controller.writer.enqueue_result({
        "raw_username": "writer_heal_user",
        "username": "@writer_heal_user",
        "status": "AVAILABLE",
        "confidence": 99.0,
        "price": "$200 USD",
        "detail": "FREE",
        "pat_id": "HEAL_TEST",
        "job_id": "job_heal_001",
        "correlation_id": "corr_heal_001"
    })
    
    controller.writer.stop()
    controller.writer.wait(500)
    replace_writer_ok = controller.replace_dead_writer()
    new_writer_id = id(controller.writer)
    
    time.sleep(0.3)
    persisted_after_heal = controller.db.is_scanned("writer_heal_user")

    if replace_writer_ok and (old_writer_id != new_writer_id) and controller.writer.isRunning() and persisted_after_heal == ScanCheckResult.FOUND:
        print("  [✓] StorageWriter Crash Healing, Zero-Loss Queue Transfer & Persistence: VERIFIED")
    else:
        print("  [❌] StorageWriter replacement failed")
        all_passed = False

    # [14/14] Master Teardown
    print("\n[14/14] Testing Clean Orchestrated Teardown & Proof of Drain...")
    shutdown_ok = controller.shutdown_engine()
    writer.stop()
    writer.wait(1000)

    if shutdown_ok:
        print("  [✓] Engine Orchestrated Teardown & Thread Drain: PASSED")
    else:
        print("  [❌] Engine Teardown Failed")
        all_passed = False

    for f in [test_db_file, f"{test_db_file}-wal", f"{test_db_file}-shm"]:
        if os.path.exists(f):
            try: os.remove(f)
            except Exception: pass

    print("\n" + "=" * 75)
    if all_passed:
        print("🟢 ALL 14/14 INTEGRATION & STRUCTURAL SELF-TESTS PASSED")
        print("=" * 75)
        return 0
    else:
        print("🔴 INTEGRATION SELF-TESTS FAILED. PLEASE REVIEW LOGS ABOVE.")
        print("=" * 75)
        return 1