from __future__ import annotations
from collections import defaultdict
from typing import Dict, List, Tuple
from core.state.enums import FragmentStatus
from parser.matcher import StatusMatcher

class EvidenceCollector:
    """
    Collects weighted evidence by delegating all semantic matching
    directly to StatusMatcher (Single Source of Truth).
    """
    
    @classmethod
    def collect(
        cls,
        status_element_str: str,
        btn_texts: str,
        context_lower: str,
        price: str
    ) -> Tuple[Dict[FragmentStatus, int], Dict[FragmentStatus, List[str]]]:
        evidence: Dict[FragmentStatus, int] = defaultdict(int)
        reasons: Dict[FragmentStatus, List[str]] = defaultdict(list)

        # 1. Match Status Elements (Weight: 50)
        for status, score, reason in StatusMatcher.match_status_element(status_element_str):
            evidence[status] += score
            reasons[status].append(reason)

        # 2. Match Action Buttons (Weight: 30)
        for status, score, reason in StatusMatcher.match_buttons(btn_texts):
            evidence[status] += score
            reasons[status].append(reason)

        # 3. Match Exact Phrases and Keywords (Weight: 15 to 35)
        for status, score, reason in StatusMatcher.match_phrases(context_lower):
            evidence[status] += score
            reasons[status].append(reason)

        # 4. Price Confirmation Evidence
        if price:
            if evidence[FragmentStatus.SOLD] > 0:
                evidence[FragmentStatus.SOLD] += 20
            if evidence[FragmentStatus.AVAILABLE] > 0:
                evidence[FragmentStatus.AVAILABLE] += 20
            if evidence[FragmentStatus.AUCTION] > 0:
                evidence[FragmentStatus.AUCTION] += 20

        return evidence, reasons