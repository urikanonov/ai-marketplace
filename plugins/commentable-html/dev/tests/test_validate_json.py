#!/usr/bin/env python3
"""Tests for the embedded application/json block validity check (cmhval/jsonblocks.py).

Standard library only (unittest).

    python -m unittest discover -s tests -p test_validate_json.py   # from dev
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)

import validate  # noqa: E402
from cmhval import jsonblocks as J  # noqa: E402


def _errs(html, chart_checks_run=True):
    parser, ok = validate._parse(html)
    assert ok, "parse failed"
    e, _w = J.check_json_blocks(parser, chart_checks_run=chart_checks_run)
    return e


class JsonBlockValidity(unittest.TestCase):
    """CMH-SYN-06: an embedded application/json block that is not valid JSON is an error."""

    def test_invalid_json_no_canvas_is_flagged(self):
        html = '<script type="application/json" id="data">{"a": 1,}</script>'
        e = _errs(html)
        self.assertTrue(e)
        self.assertIn('id="data"', e[0])

    def test_valid_json_not_flagged(self):
        self.assertEqual(_errs('<script type="application/json" id="data">{"a": 1}</script>'), [])

    def test_empty_block_flagged(self):
        e = _errs('<script type="application/json" id="data">   </script>')
        self.assertTrue(e)
        self.assertIn("empty", e[0])

    def test_layer_blocks_ignored(self):
        for lid in ("handledCommentIds", "embeddedComments", "commentableHtmlLayer"):
            html = '<script type="application/json" id="%s">not json</script>' % lid
            self.assertEqual(_errs(html), [], lid)

    def test_canvas_present_defers_to_chart_checks(self):
        # When a <canvas> exists, the chart path owns JSON validity, so this module
        # stays silent to avoid double-reporting.
        html = ('<span class="cm-skip"><canvas id="c"></canvas></span>'
                '<script type="application/json" id="data">{bad</script>')
        self.assertEqual(_errs(html), [])

    def test_non_json_script_ignored(self):
        self.assertEqual(_errs('<script>var x = {bad json;;;</script>'), [])

    def test_wired_into_validate_module(self):
        self.assertTrue(hasattr(validate, "check_json_blocks"))

    def test_nan_infinity_flagged(self):
        # Python's json.loads accepts these by default, but browser JSON.parse
        # rejects them, so they must fail here too.
        for lit in ("NaN", "Infinity", "-Infinity"):
            html = '<script type="application/json" id="data">{"x": %s}</script>' % lit
            with self.subTest(lit=lit):
                self.assertTrue(_errs(html), lit)

    def test_script_breakout_is_caught_via_json_validity(self):
        # A raw </script> truncates the block in the browser; the captured body is
        # then invalid JSON, so JSON-validity already catches a real breakout. A
        # lone "<!--" inside a valid JSON string is NOT a breakout and is not flagged.
        self.assertEqual(_errs('<script type="application/json" id="d">"<!-- ok -->"</script>'), [])

    def test_layer_only_still_checks_json_when_canvas_present(self):
        # In --layer-only mode the chart checks do not run, so this module must not
        # defer just because a canvas exists.
        html = ('<span class="cm-skip"><canvas id="c"></canvas></span>'
                '<script type="application/json" id="data">{bad</script>')
        self.assertEqual(_errs(html, chart_checks_run=True), [])   # default: charts own it
        self.assertTrue(_errs(html, chart_checks_run=False))       # layer-only: we own it


if __name__ == "__main__":
    unittest.main()
