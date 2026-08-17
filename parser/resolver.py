from __future__ import annotations
from typing import Dict, List, Tuple
from core.state.enums import FragmentStatus
from core.errors.categories import ErrorCategory
from core.logger import logger

class ConflictResolver:
    """Arbitrates conflicting structural evidence and calculates final confidence."""

    @classmethod
    def resolve(
        cls,
        evidence: Dict[FragmentStatus, int],
        reasons: Dict[FragmentStatus, List[str]],
        full_context_text: str,
        username: str,
        price: str,
        owner: str,
        correlation_id: str = ""
    ) -> Tuple[FragmentStatus, float, str, str, str, ErrorCategory]:
        if not evidence:
            return FragmentStatus.UNKNOWN, 0.0, "", "No Structural Evidence Found", "NO EVIDENCE", ErrorCategory.PARSER_ERROR

        sorted_candidates = sorted(evidence.items(), key=lambda item: item[1], reverse=True)
        top_status, top_score = sorted_candidates[0]

        if len(sorted_candidates) > 1:
            second_status, second_score = sorted_candidates[1]
            if top_score == second_score or (second_score >= 40 and (top_score - second_score) <= 10):
                if {top_status, second_status} == {FragmentStatus.AUCTION, FragmentStatus.AVAILABLE}:
                    if "bid" in full_context_text.lower() or "ends in" in full_context_text.lower():
                        top_status = FragmentStatus.AUCTION
                        top_score += 15
                    else:
                        top_status = FragmentStatus.AVAILABLE
                        top_score += 15
                elif {top_status, second_status} == {FragmentStatus.UNAVAILABLE, FragmentStatus.AVAILABLE}:
                    top_status = FragmentStatus.UNAVAILABLE
                    top_score += 20
                else:
                    logger.warning(f"[{correlation_id}] Conflict Gate: Ambiguous evidence for @{username} between {top_status.value}({top_score}) and {second_status.value}({second_score})")
                    return FragmentStatus.UNKNOWN, 50.0, "", f"Conflict: {top_status.value} vs {second_status.value}", "CONFLICT", ErrorCategory.PARSER_ERROR

        final_confidence = min(99.0, max(60.0, float(top_score)))
        primary_reason = "; ".join(reasons[top_status]) if reasons[top_status] else "Structural Heuristic"

        if top_status == FragmentStatus.AUCTION:
            detail = price if price else "AUCTION ACTIVE"
        elif top_status == FragmentStatus.AVAILABLE:
            detail = f"BUY: {price}" if price else "AVAILABLE"
        elif top_status == FragmentStatus.SOLD:
            detail = f"SOLD: {price}" if price else "WAS SOLD"
        elif top_status == FragmentStatus.TAKEN:
            detail = owner if owner else "TAKEN HANDLE"
        elif top_status == FragmentStatus.FREE:
            detail = "NOT REGISTERED"
        else:
            detail = "REGISTRATION CLOSED"

        return top_status, final_confidence, price, primary_reason, detail, ErrorCategory.NETWORK_TRANSIENT