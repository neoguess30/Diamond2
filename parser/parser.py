from __future__ import annotations
import time
from typing import Tuple

from core.state.enums import FragmentStatus
from core.errors.categories import ErrorCategory
from core.metrics import METRICS
from core.logger import logger
from parser.engine import create_soup
from parser.context import ContextExtractor
from parser.metadata import MetadataExtractor
from parser.evidence import EvidenceCollector
from parser.resolver import ConflictResolver

class FragmentParser:
    """Correctness-First Fragment Parser with Strict Target Context Isolation & Unified Matcher."""

    @classmethod
    def parse_html(
        cls,
        html_bytes: bytes,
        username: str,
        correlation_id: str = ""
    ) -> Tuple[FragmentStatus, float, str, str, str, ErrorCategory]:
        parse_start_t = time.monotonic()
        payload_size = len(html_bytes) if html_bytes else 0

        if not html_bytes:
            METRICS.lifetime_unknowns += 1
            METRICS.record_parser_latency((time.monotonic() - parse_start_t) * 1000, payload_size_bytes=0)
            return FragmentStatus.ERROR, 0.0, "", "Empty HTTP Content", "NO DATA", ErrorCategory.NETWORK_TRANSIENT

        html_text = html_bytes.decode('utf-8', errors='replace')
        html_lower = html_text.lower()

        # 1. Fast-Path: Cloudflare / Bot Challenge Guard
        if "just a moment" in html_lower or "cf-challenge" in html_lower or "turnstile" in html_lower:
            parse_dur = (time.monotonic() - parse_start_t) * 1000
            METRICS.record_parser_latency(parse_dur, payload_size_bytes=payload_size)
            return FragmentStatus.ERROR, 0.0, "", "Cloudflare Challenge Intercepted", "CHALLENGE", ErrorCategory.HTTP_429

        soup = create_soup(html_bytes)
        try:
            # 2. Extract Strict Target Context
            is_verified, context_node, full_context_text, status_element_str, btn_texts = ContextExtractor.extract_context(soup)
            
            # P0 Gate: If no legitimate target container was verified, reject full-page fallback
            if not is_verified:
                parse_dur = (time.monotonic() - parse_start_t) * 1000
                METRICS.lifetime_unknowns += 1
                METRICS.record_parser_latency(parse_dur, payload_size_bytes=payload_size)
                return FragmentStatus.UNKNOWN, 0.0, "", "Target Context Container Not Verified (Structure Mismatch)", "NO CONTEXT", ErrorCategory.PARSER_ERROR

            price = MetadataExtractor.detect_price(full_context_text, soup=soup, context_node=context_node)
            owner = MetadataExtractor.detect_owner(full_context_text)

            # 3. Collect Evidence via Unified Matcher
            evidence, reasons = EvidenceCollector.collect(
                status_element_str=status_element_str,
                btn_texts=btn_texts,
                context_lower=full_context_text.lower(),
                price=price
            )

            # 4. Resolve Conflict Gate
            status, conf, price, reason, detail, err_cat = ConflictResolver.resolve(
                evidence=evidence,
                reasons=reasons,
                full_context_text=full_context_text,
                username=username,
                price=price,
                owner=owner,
                correlation_id=correlation_id
            )

            parse_dur = (time.monotonic() - parse_start_t) * 1000
            METRICS.record_parser_latency(parse_dur, payload_size_bytes=payload_size)

            if status == FragmentStatus.UNKNOWN:
                METRICS.lifetime_unknowns += 1

            return status, conf, price, reason, detail, err_cat

        except Exception as e:
            parse_dur = (time.monotonic() - parse_start_t) * 1000
            METRICS.lifetime_parse_errors += 1
            METRICS.record_parser_latency(parse_dur, payload_size_bytes=payload_size)
            logger.exception(f"[{correlation_id}] Parsing Exception for @{username}: {e}")
            return FragmentStatus.ERROR, 0.0, "", f"Parser Exception: {e}", "ERROR", ErrorCategory.PARSER_ERROR
        finally:
            if hasattr(soup, "decompose"):
                soup.decompose()