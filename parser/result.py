from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
from core.state.enums import FragmentStatus
from core.errors.categories import ErrorCategory

@dataclass
class ParserResult:
    """Strongly typed structure representing the parsed target status and extracted evidence."""
    username: str
    status: FragmentStatus
    confidence: float
    price: str = ""
    reason: str = ""
    detail: str = ""
    error_category: ErrorCategory = ErrorCategory.NETWORK_TRANSIENT
    evidence_reasons: List[str] = field(default_factory=list)

    @classmethod
    def create_unknown(cls, username: str, reason: str = "No Structural Evidence Found") -> ParserResult:
        return cls(
            username=username,
            status=FragmentStatus.UNKNOWN,
            confidence=0.0,
            price="",
            reason=reason,
            detail="NO EVIDENCE",
            error_category=ErrorCategory.PARSER_ERROR
        )

    @classmethod
    def create_error(cls, username: str, error_msg: str, category: ErrorCategory = ErrorCategory.PARSER_ERROR) -> ParserResult:
        return cls(
            username=username,
            status=FragmentStatus.ERROR,
            confidence=0.0,
            price="",
            reason=error_msg,
            detail="ERROR",
            error_category=category
        )