#!/usr/bin/env python3
"""Tests for the deck theme evaluation harness (dev/eval/theme_eval.py, CMH-DECK-THEME-05).

The harness must PASS on the real shipped corpus + presets (every cell scaffolds clean, zero validator
errors, zero content-overload advisories, and each theme adds only a bounded block), and its
`gate_failures` must actually CATCH each regression class: a scaffold failure, a validator error, a
content-overload (clipping) advisory, and a theme that bloats a deck past the size ceiling. The
overload case is exercised end to end against a real oversized slide so the gate is not tautological.
Written as unittest so CI's `unittest discover` gates it.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants

sys.path.insert(0, os.path.join(_paths.DEV, "eval"))
import theme_eval  # noqa: E402
sys.path.insert(0, _paths.DECK)
import _deck_theme  # noqa: E402


class RealCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = theme_eval.evaluate()

    def test_real_corpus_and_themes_pass_the_gate(self):
        self.assertTrue(self.rows, "the corpus produced no evaluation cells")
        self.assertEqual(theme_eval.gate_failures(self.rows), [])

    def test_every_shipped_theme_and_the_baseline_are_covered(self):
        covered = {r["theme"] for r in self.rows}
        self.assertIn(theme_eval.BASELINE, covered)
        for preset in _deck_theme.list_presets():
            self.assertIn(preset, covered, "preset %r was not evaluated" % preset)

    def test_each_theme_adds_a_bounded_nonzero_block(self):
        themed = [r for r in self.rows if r["theme"] != theme_eval.BASELINE]
        self.assertTrue(themed)
        for r in themed:
            self.assertGreater(r["delta"], 0, "%s added no bytes - theme not applied?" % r["theme"])
            self.assertLessEqual(r["delta"], theme_eval.SIZE_DELTA_CEILING)


class GateDetectionTests(unittest.TestCase):
    def test_gate_catches_a_real_content_overload_slide(self):
        # An oversized slide (far past the element budget) must produce an advisory and fail the gate -
        # this is the clipping-regression class the harness exists to catch, exercised end to end.
        with tempfile.TemporaryDirectory() as td:
            corpus = Path(td)
            paras = "\n".join("  <p>Overflowing line number %d on a single slide.</p>" % i for i in range(60))
            (corpus / "overload.html").write_text(
                '<section class="slide">\n  <h2 class="cmh-slide-title">Too much</h2>\n%s\n</section>\n' % paras,
                encoding="utf-8")
            rows = theme_eval.evaluate(corpus, themes=[])
            self.assertTrue(rows)
            self.assertTrue(any(r["advisories"] > 0 for r in rows), "expected a content-overload advisory")
            fails = theme_eval.gate_failures(rows)
            self.assertTrue(any("overload" in f for f in fails))

    def test_gate_catches_a_scaffold_failure(self):
        rows = [{"theme": "x", "corpus": "c", "rc": 2, "errors": 0, "advisories": 0,
                 "bytes": 0, "delta": 0, "error_list": [], "advisory_list": [], "log": "boom"}]
        self.assertTrue(any("scaffold failed" in f for f in theme_eval.gate_failures(rows)))

    def test_gate_catches_a_validator_error(self):
        rows = [{"theme": "x", "corpus": "c", "rc": 0, "errors": 1, "advisories": 0,
                 "bytes": 10, "delta": 10, "error_list": ["deck: bad"], "advisory_list": [], "log": ""}]
        self.assertTrue(any("validator error" in f for f in theme_eval.gate_failures(rows)))

    def test_gate_catches_theme_bloat(self):
        rows = [{"theme": "x", "corpus": "c", "rc": 0, "errors": 0, "advisories": 0,
                 "bytes": 999999, "delta": theme_eval.SIZE_DELTA_CEILING + 1,
                 "error_list": [], "advisory_list": [], "log": ""}]
        self.assertTrue(any("ceiling" in f for f in theme_eval.gate_failures(rows)))

    def test_clean_rows_have_no_failures(self):
        rows = [{"theme": "(none)", "corpus": "c", "rc": 0, "errors": 0, "advisories": 0,
                 "bytes": 10, "delta": 0, "error_list": [], "advisory_list": [], "log": ""}]
        self.assertEqual(theme_eval.gate_failures(rows), [])

    def test_cli_returns_zero_on_the_real_corpus(self):
        self.assertEqual(theme_eval.main([]), 0)

    def test_cli_fails_closed_on_an_empty_or_missing_corpus(self):
        # A mistyped/empty --corpus must FAIL, not report OK on zero cells.
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(theme_eval.evaluate(Path(td)), [])
            self.assertEqual(theme_eval.main(["--corpus", td]), 1)
            self.assertEqual(theme_eval.main(["--corpus", os.path.join(td, "nope")]), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
