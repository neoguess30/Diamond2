from __future__ import annotations
import unittest

from parser.pattern_generator import LazyPatternGenerator

class TestPatternGenerator(unittest.TestCase):

    def test_exact_pattern_possibilities(self):
        total = LazyPatternGenerator.calculate_possibilities("crypto")
        self.assertEqual(total, 1)

    def test_wildcard_possibilities(self):
        # 'L' = 26, 'N' = 10 -> 'L_N' = 26 * 1 * 10 = 260
        total = LazyPatternGenerator.calculate_possibilities("L_N")
        self.assertEqual(total, 260)

        # 'L_L_N' = 26 * 1 * 26 * 1 * 10 = 6760
        total_wild = LazyPatternGenerator.calculate_possibilities("L_L_N")
        self.assertEqual(total_wild, 6760)

    def test_stream_output(self):
        # Small space (pre-shuffled memory test)
        stream_results = list(LazyPatternGenerator.generate_stream("L_0"))
        self.assertEqual(len(stream_results), 26)
        for item in stream_results:
            self.assertTrue(item.endswith("_0"))
            self.assertEqual(len(item), 3)

if __name__ == "__main__":
    unittest.main()