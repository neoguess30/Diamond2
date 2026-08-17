from __future__ import annotations
import unittest

from parser.parser import FragmentParser
from parser.matcher import StatusMatcher
from core.state.enums import FragmentStatus
from tests.fixtures.html_fixtures import REAL_FRAGMENT_FIXTURES

class TestFragmentParserUnit(unittest.TestCase):

    def test_status_matcher_single_source_of_truth(self):
        """P0 Test: Verifies StatusMatcher pattern matching and scoring rules."""
        # Status element matching
        res = StatusMatcher.match_status_element("tm-status-available Available")
        self.assertTrue(any(r[0] == FragmentStatus.AVAILABLE for r in res))

        # Action button matching
        btn_res = StatusMatcher.match_buttons("btn-primary place bid")
        self.assertTrue(any(r[0] == FragmentStatus.AUCTION for r in btn_res))

        # Exact phrase matching
        phrase_res = StatusMatcher.match_phrases("this username is unavailable on fragment")
        self.assertTrue(any(r[0] == FragmentStatus.UNAVAILABLE for r in phrase_res))

    def test_real_production_fixtures_parsing(self):
        """P0 Test: Validates all real Fragment.com production HTML fixtures."""
        for fix_name, (raw_html, expected_st, min_conf) in REAL_FRAGMENT_FIXTURES.items():
            st, conf, price, reason, detail, err_cat = FragmentParser.parse_html(raw_html, "testtarget")
            self.assertEqual(st.value, expected_st, f"Failed on fixture {fix_name}")
            self.assertGreaterEqual(conf, min_conf, f"Low confidence on {fix_name}")

    def test_unverified_target_context_strictly_returns_unknown(self):
        """P0 Test: Proves that arbitrary non-Fragment HTML without target container returns UNKNOWN (0.0% conf)."""
        arbitrary_html = b"""
        <html>
        <body>
            <div class="unrelated-promo-footer">
                <h1>Special Sale Event</h1>
                <p>Everything is available for purchase at 50% discount!</p>
            </div>
        </body>
        </html>
        """
        st, conf, price, reason, detail, err_cat = FragmentParser.parse_html(arbitrary_html, "someuser")
        self.assertEqual(st, FragmentStatus.UNKNOWN)
        self.assertEqual(conf, 0.0)
        self.assertEqual(detail, "NO CONTEXT")

if __name__ == "__main__":
    unittest.main()