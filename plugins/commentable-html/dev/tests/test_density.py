#!/usr/bin/env python3
"""Tests for the information-density authoring advisory (CMH-VAL-15): a non-fatal validator
warning when a report/plan section is a wall of consecutive long paragraphs with no layout-bearing
block (table, list, figure, diff, chart, or diagram) to break it up."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402

sys.path.insert(0, os.path.join(_paths.TOOLS, "validate"))
from checks import density  # noqa: E402

# A paragraph comfortably past the default "long" threshold (~240 chars).
LONG = "This sentence is deliberately padded out with plenty of filler words " * 4
SHORT = "A short line."


def _p(text):
    return "<p>%s</p>" % text


def _doc(inner, kind="report"):
    return (
        '<!doctype html><html><head>'
        '<meta name="commentable-html-kind" content="%s" />'
        '</head><body><main id="commentRoot" data-cmh-content-root>'
        "<h1>Title</h1><section><h2>Section</h2>%s</section>"
        "</main></body></html>" % (kind, inner)
    )


class DensityAdvisoryTests(unittest.TestCase):
    def test_cmh_val_15_prose_wall_warns(self):
        errors, warnings = density.check_density(_doc(_p(LONG) * 4))
        self.assertEqual(errors, [])
        self.assertTrue(warnings, "expected a density advisory for a 4-paragraph prose wall")

    def test_cmh_val_15_layout_bearing_section_is_clean(self):
        # A table breaks the run so no sub-run reaches the threshold.
        inner = _p(LONG) * 2 + "<table><tr><td>x</td></tr></table>" + _p(LONG) * 2
        errors, warnings = density.check_density(_doc(inner))
        self.assertEqual(warnings, [])

    def test_cmh_val_15_short_paragraphs_are_clean(self):
        errors, warnings = density.check_density(_doc(_p(SHORT) * 8))
        self.assertEqual(warnings, [])

    def test_cmh_val_15_heading_breaks_the_run(self):
        inner = _p(LONG) * 3 + "<h3>Sub</h3>" + _p(LONG) * 3
        errors, warnings = density.check_density(_doc(inner))
        self.assertEqual(warnings, [])

    def test_cmh_val_15_slides_and_board_are_exempt(self):
        for kind in ("slides", "board"):
            errors, warnings = density.check_density(_doc(_p(LONG) * 6, kind=kind))
            self.assertEqual(warnings, [], msg="kind %s should be exempt" % kind)

    def test_cmh_val_15_cm_skip_is_ignored(self):
        inner = '<div class="cm-skip">%s</div>' % (_p(LONG) * 6)
        errors, warnings = density.check_density(_doc(inner))
        self.assertEqual(warnings, [])

    def test_cmh_val_15_content_outside_root_is_ignored(self):
        # A prose wall in host chrome outside #commentRoot must not be flagged.
        html = (
            '<!doctype html><html><head>'
            '<meta name="commentable-html-kind" content="report" /></head><body>'
            "<header>%s</header>"
            '<main id="commentRoot" data-cmh-content-root><h1>t</h1><section><h2>s</h2>%s</section></main>'
            "</body></html>" % (_p(LONG) * 6, _p(SHORT))
        )
        errors, warnings = density.check_density(html)
        self.assertEqual(warnings, [])

    def test_cmh_val_15_threshold_is_tunable(self):
        # A 3-paragraph section is clean at the default max but warns at a stricter max_run.
        doc = _doc(_p(LONG) * 3)
        self.assertEqual(density.check_density(doc)[1], [])
        self.assertTrue(density.check_density(doc, max_run=3)[1])

    def test_cmh_val_15_paragraphs_inside_layout_do_not_count(self):
        # Long <p> nested inside a figure/list are layout content, not a prose wall.
        inner = "<ul>%s</ul>" % ("<li>%s</li>" % _p(LONG)) * 6
        errors, warnings = density.check_density(_doc(inner))
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
