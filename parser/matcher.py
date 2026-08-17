from __future__ import annotations
import re
from typing import Dict, List, Pattern, Tuple
from core.state.enums import FragmentStatus

class StatusMatcher:
    """
    P0 Single Source of Truth for Fragment Semantic Matching:
    Pre-compiled regular expressions and weighted evidence calculation.
    """
    
    # 1. Structural Status Element Regexes (Highest Weight: 50 points)
    STATUS_ELEMENT_PATTERNS: Dict[FragmentStatus, Pattern] = {
        FragmentStatus.UNAVAILABLE: re.compile(r'\b(unavailable|not for sale)\b', re.IGNORECASE),
        FragmentStatus.SOLD: re.compile(r'\b(sold)\b', re.IGNORECASE),
        FragmentStatus.TAKEN: re.compile(r'\b(taken)\b', re.IGNORECASE),
        FragmentStatus.RESERVED: re.compile(r'\b(reserved)\b', re.IGNORECASE),
        FragmentStatus.AUCTION: re.compile(r'\b(in auction|place bid|current bid|ends in|auction)\b', re.IGNORECASE),
        FragmentStatus.AVAILABLE: re.compile(r'\b(available|buy now|for sale)\b', re.IGNORECASE)
    }

    # 2. Action Button Regexes (Weight: 30 points)
    BUTTON_PATTERNS: Dict[FragmentStatus, Pattern] = {
        FragmentStatus.AUCTION: re.compile(r'\b(place bid|make bid|bid)\b', re.IGNORECASE),
        FragmentStatus.AVAILABLE: re.compile(r'\b(buy now|buy handle|purchase)\b', re.IGNORECASE),
        FragmentStatus.SOLD: re.compile(r'\b(subscribed|sold out)\b', re.IGNORECASE)
    }

    # 3. Additive Exact Phrases & Context Keywords
    PHRASE_PATTERNS: List[Tuple[FragmentStatus, Pattern, int, str]] = [
        # (Status, Regex, Score, Reason)
        (FragmentStatus.UNAVAILABLE, re.compile(r'\b(this username is unavailable|not for sale|registration closed|is not available)\b', re.IGNORECASE), 35, "Exact Phrase: Unavailable"),
        (FragmentStatus.UNAVAILABLE, re.compile(r'\b(unavailable|taken on telegram)\b', re.IGNORECASE), 25, "Keyword: Unavailable/Taken"),
        (FragmentStatus.AUCTION, re.compile(r'\b(minimum bid|current bid|time left|ends in \d|auction is live|placed a bid)\b', re.IGNORECASE), 25, "Exact Phrase: Auction Details"),
        (FragmentStatus.SOLD, re.compile(r'\b(was sold to|bought for|sold for|sale completed|auction ended|winning bid)\b', re.IGNORECASE), 25, "Exact Phrase: Sale Completed"),
        (FragmentStatus.UNAVAILABLE, re.compile(r'\b(assigned to|linked to|telegram handle is taken|owned by)\b', re.IGNORECASE), 30, "Exact Phrase: Assigned/Owned"),
        (FragmentStatus.TAKEN, re.compile(r'\b(assigned to|linked to|telegram handle is taken|owned by)\b', re.IGNORECASE), 25, "Exact Phrase: Taken/Owned"),
        (FragmentStatus.FREE, re.compile(r'\b(does not exist|not registered|query returned no result|user not found)\b', re.IGNORECASE), 30, "Exact Phrase: Free/Not Registered"),
        (FragmentStatus.AVAILABLE, re.compile(r'\b(is available for purchase|available for buy now|buy now for|for sale)\b', re.IGNORECASE), 25, "Exact Phrase: Available"),
        (FragmentStatus.AVAILABLE, re.compile(r'\b(available)\b', re.IGNORECASE), 15, "Keyword: Available")
    ]

    @classmethod
    def match_status_element(cls, text: str) -> List[Tuple[FragmentStatus, int, str]]:
        results = []
        if not text:
            return results
        for status, regex in cls.STATUS_ELEMENT_PATTERNS.items():
            if regex.search(text):
                # Ensure negative qualifiers don't trigger available
                if status == FragmentStatus.AVAILABLE and re.search(r'\b(not available|unavailable|not for sale)\b', text, re.IGNORECASE):
                    continue
                results.append((status, 50, f"Status Element: {status.value}"))
        return results

    @classmethod
    def match_buttons(cls, text: str) -> List[Tuple[FragmentStatus, int, str]]:
        results = []
        if not text:
            return results
        for status, regex in cls.BUTTON_PATTERNS.items():
            if regex.search(text):
                results.append((status, 30, f"Action Button: {status.value}"))
        return results

    @classmethod
    def match_phrases(cls, context_lower: str) -> List[Tuple[FragmentStatus, int, str]]:
        results = []
        if not context_lower:
            return results
        for status, regex, score, reason in cls.PHRASE_PATTERNS:
            if regex.search(context_lower):
                if status == FragmentStatus.AVAILABLE and re.search(r'\b(not available|is not available|unavailable|not for sale)\b', context_lower):
                    continue
                results.append((status, score, reason))
        return results