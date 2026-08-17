from __future__ import annotations
import random

def calculate_jittered_backoff(base_delay: float, attempt: int, factor: float = 1.5, max_delay: float = 8.0) -> float:
    """Calculates exponential backoff with full randomized jitter."""
    backoff = base_delay * (factor ** min(attempt, 3))
    jitter = random.uniform(0.1, 0.3 * backoff)
    total_delay = backoff + jitter
    return max(1.0, min(total_delay, max_delay))

def calculate_retry_delay(attempt: int, base: float = 2.0, factor: float = 1.5, max_delay: float = 60.0) -> float:
    """
    P0 Full Decorrelated Jitter:
    Spreads retry timestamps uniformly across time windows to eliminate Thundering Herd spikes.
    """
    calculated_backoff = min(max_delay, base * (factor ** attempt))
    # Full randomized jitter: uniform distribution between 0.5x and 1.5x of backoff
    jittered_delay = random.uniform(0.5 * calculated_backoff, 1.5 * calculated_backoff)
    return max(1.0, min(jittered_delay, max_delay))