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

    def test_cmh_deck_08_equal_colors_ratio_is_1_to_1(self):
        self.assertAlmostEqual(contrast.contrast_ratio("#123456", "#123456"), 1.0, places=2)

    def test_cmh_deck_08_parser_supports_hex_rgb_rgba_and_vars(self):
        variables = {"--fg": "#abc", "--bg": "rgb(0, 0, 0)"}
        self.assertEqual(contrast.parse_css_color("var(--fg)", variables), (170, 187, 204, 1.0))
        self.assertEqual(contrast.parse_css_color("rgba(255, 255, 255, 0.5)", variables),
                         (255, 255, 255, 0.5))
        self.assertGreater(contrast.contrast_ratio("var(--fg)", "var(--bg)", variables), 9.0)

    def test_cmh_deck_08_parser_rejects_non_finite_rgb_channels(self):
        self.assertIsNone(contrast.parse_css_color("rgb(inf 0 0)"))
        self.assertIsNone(contrast.parse_css_color("rgb(1e309 0 0)"))

    def test_cmh_deck_08_parser_rejects_malformed_rgb_arity(self):
        self.assertIsNone(contrast.parse_css_color("rgba(255,255,255,.5,.2)"))
        self.assertIsNone(contrast.parse_css_color("rgb(1 2 3 4)"))

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

    def test_cmh_deck_08_skips_semi_transparent_backgrounds(self):
        html = """
        <p style="color:#000; background:rgba(255,255,255,0.2)">Readable</p>
        <p style="color:#fff; background:rgba(255,255,255,0.2)">Unknown backdrop</p>
        """
        self.assertEqual(contrast.find_low_contrast_pairs(html), [])

    def test_cmh_deck_08_background_shorthand_uses_declaration_order(self):
        html = "<style>.ordered { color:#fff; background-color:#000; background:#eee; }</style>"
        issues = contrast.find_low_contrast_pairs(html)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].background, "#eee")

    def test_cmh_deck_08_background_url_text_is_not_a_color(self):
        html = """
        <style>
        .url-word { color:#fff; background:url(assets/white-banner.png); }
        .url-hex { color:#fff; background:url("assets/#ffffff/banner.png"); }
        </style>
        """
        self.assertEqual(contrast.find_low_contrast_pairs(html), [])

    def test_cmh_deck_08_background_url_fallback_color_is_detected(self):
        html = '<style>.fallback { color:#fff; background:url("assets/banner.png") #eee; }</style>'
        issues = contrast.find_low_contrast_pairs(html)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].background, "#eee")


if __name__ == "__main__":
    unittest.main()
