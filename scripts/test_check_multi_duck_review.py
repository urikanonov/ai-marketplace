#!/usr/bin/env python3
"""Covering tests for the multi-duck-review PR gate (scripts/check_multi_duck_review.py).

Run by the validate CI job via `python -m unittest discover -s scripts -p "test_*.py"` (and by
the cross-platform matrix), so the required multi-duck-review gate's logic is itself gated by a
required status check. Standard library only.
"""
import unittest

import check_multi_duck_review as gate


PASSED_BODY = """## Summary

Adds a thing.

## Multi-duck review (required)

- [x] Multi-Duck passed (2 rounds of multi-duck review)
- [ ] Multi-Duck opted out - reason: <a real, specific reason>
"""

OPTOUT_BODY = """## Multi-duck review (required)

- [ ] Multi-Duck passed (2 rounds of multi-duck review)
- [x] Multi-Duck opted out - reason: docs-only typo fix, no logic to review
"""

UNCHECKED_BODY = """## Multi-duck review (required)

- [ ] Multi-Duck passed (2 rounds of multi-duck review)
- [ ] Multi-Duck opted out - reason: <a real, specific reason>
"""

OPTOUT_PLACEHOLDER_BODY = """## Multi-duck review (required)

- [ ] Multi-Duck passed (2 rounds of multi-duck review)
- [x] Multi-Duck opted out - reason: <a real, specific reason>
"""

OPTOUT_EMPTY_BODY = """- [x] Multi-Duck opted out - reason:
"""


class EvaluateTests(unittest.TestCase):
    def test_passed_checkbox_passes(self):
        ok, msg = gate.evaluate(PASSED_BODY)
        self.assertTrue(ok, msg)
        self.assertIn("passed", msg.lower())

    def test_opted_out_with_reason_passes(self):
        ok, msg = gate.evaluate(OPTOUT_BODY)
        self.assertTrue(ok, msg)
        self.assertIn("docs-only typo fix", msg)

    def test_unchecked_template_fails(self):
        ok, msg = gate.evaluate(UNCHECKED_BODY)
        self.assertFalse(ok)
        self.assertIn("no multi-duck stamp", msg.lower())

    def test_opted_out_placeholder_reason_fails(self):
        ok, msg = gate.evaluate(OPTOUT_PLACEHOLDER_BODY)
        self.assertFalse(ok)
        self.assertIn("no real", msg.lower())

    def test_opted_out_empty_reason_fails(self):
        ok, _ = gate.evaluate(OPTOUT_EMPTY_BODY)
        self.assertFalse(ok)

    def test_missing_body_fails(self):
        ok, _ = gate.evaluate("")
        self.assertFalse(ok)
        ok2, _ = gate.evaluate(None)
        self.assertFalse(ok2)

    def test_dependabot_auto_passes_even_without_stamp(self):
        ok, msg = gate.evaluate("", author="dependabot[bot]")
        self.assertTrue(ok)
        self.assertIn("auto-passes", msg)

    def test_non_dependabot_author_still_needs_stamp(self):
        ok, _ = gate.evaluate("", author="urikanonov")
        self.assertFalse(ok)

    def test_passed_wording_is_flexible(self):
        ok, _ = gate.evaluate("- [X] multi-duck PASSED after two rounds")
        self.assertTrue(ok)

    def test_opt_out_hyphen_and_spelling_variants(self):
        for line in (
            "- [x] Multi-Duck opt out - reason: trivial config change",
            "- [x] Multi-Duck opted-out - reason: trivial config change",
            "* [x] multi-duck opted out: trivial config change",
        ):
            ok, msg = gate.evaluate(line)
            self.assertTrue(ok, "%s -> %s" % (line, msg))


class MainTests(unittest.TestCase):
    def test_main_reads_env_body(self):
        import os
        old = os.environ.get("PR_BODY")
        old_author = os.environ.get("PR_AUTHOR")
        try:
            os.environ["PR_BODY"] = PASSED_BODY
            os.environ.pop("PR_AUTHOR", None)
            self.assertEqual(gate.main([]), 0)
            os.environ["PR_BODY"] = UNCHECKED_BODY
            self.assertEqual(gate.main([]), 1)
        finally:
            if old is None:
                os.environ.pop("PR_BODY", None)
            else:
                os.environ["PR_BODY"] = old
            if old_author is not None:
                os.environ["PR_AUTHOR"] = old_author


if __name__ == "__main__":
    unittest.main()
