from __future__ import annotations
import itertools
import random
from typing import List, Generator

class LazyPatternGenerator:
    """Generates permutation streams using bounded-memory randomized generation."""
    WILDCARDS = {
        'L': 'abcdefghijklmnopqrstuvwxyz',
        'N': '0123456789',
        'V': 'aeiou',
        'C': 'bcdfghjklmnpqrstvwxyz',
        '?': 'abcdefghijklmnopqrstuvwxyz0123456789_'
    }

    @classmethod
    def parse_pattern(cls, pattern: str) -> List[List[str]]:
        pools = []
        for char in pattern:
            if char in cls.WILDCARDS:
                pools.append(list(cls.WILDCARDS[char]))
            else:
                pools.append([char])
        return pools

    @classmethod
    def calculate_possibilities(cls, pattern: str) -> int:
        pools = cls.parse_pattern(pattern)
        total = 1
        for pool in pools:
            total *= len(pool)
        return total

    @classmethod
    def generate_stream(cls, pattern: str) -> Generator[str, None, None]:
        pools = cls.parse_pattern(pattern)
        total = cls.calculate_possibilities(pattern)

        if total <= 50000:
            results = ["".join(comb) for comb in itertools.product(*pools)]
            random.shuffle(results)
            for r in results:
                yield r
        else:
            for comb in itertools.product(*pools):
                yield "".join(comb)