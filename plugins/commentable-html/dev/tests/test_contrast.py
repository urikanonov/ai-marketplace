#!/usr/bin/env python3
"""Tests for tools/validate/cmhval/contrast.py (CMH-DECK-08)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402

sys.path.insert(0, os.path.join(_paths.TOOLS, "validate"))
from cmhval import contrast  # noqa: E402


class ContrastUtilityTests(unittest.TestCase):
    def test_cmh_deck_08_black_white_ratio_is_21_to_1(self):
        self.assertAlmostEqual(contrast.contrast_ratio("#000", "#fff"), 21.0, places=2)
        self.assertAlmostEqual(contrast.contrast_ratio("white", "black"), 21.0, places=2)

    def test_cmh_deck_08_parser_supports_hex_rgb_rgba_and_vars(self):
        variables = {"--fg": "#abc", "--bg": "rgb(0, 0, 0)"}
        self.assertEqual(contrast.parse_css_color("var(--fg)", variables), (170, 187, 204, 1.0))
        self.assertEqual(contrast.parse_css_color("rgba(255, 255, 255, 0.5)", variables),
                         (255, 255, 255, 0.5))
        self.assertGreater(contrast.contrast_ratio("var(--fg)", "var(--bg)", variables), 9.0)

    def test_cmh_deck_08_finds_low_and_good_pairs(self):
        html = """
        <style>
        :root { --same: #777; --dark: #000; --light: #fff; }
        .low { color: var(--same); background-color: #777; }
        .good { color: var(--light); background: var(--dark); }
        </style>
        <p style="color: #ffffff; background-color: #000000">Readable</p>
        """
        issues = contrast.find_low_contrast_pairs(html)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].source, "selector .low")
        self.assertLess(issues[0].ratio, contrast.DEFAULT_MIN_CONTRAST_RATIO)

    def test_cmh_deck_08_finds_configured_variable_pairs(self):
        html = "<style>:root { --fg: #777; --bg: #777; }</style>"
        issues = contrast.find_low_contrast_pairs(
            html, variable_pairs=(("--fg", "--bg", "theme variables --fg/--bg"),))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].source, "theme variables --fg/--bg")


if __name__ == "__main__":
    unittest.main()
