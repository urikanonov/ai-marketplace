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

    def test_passed_canonical_forms_pass(self):
        self.assertTrue(gate.evaluate("- [x] multi-duck passed")[0])
        self.assertTrue(gate.evaluate("- [X] Multi-Duck passed (2 rounds of multi-duck review)")[0])

    def test_passed_with_negating_trailing_prose_fails(self):
        # A checked box whose text negates the stamp must NOT count as a pass.
        ok, _ = gate.evaluate("- [x] Multi-Duck passed? No, this has not passed")
        self.assertFalse(ok)

    def test_stamp_hidden_in_html_comment_fails(self):
        body = "<!--\n- [x] Multi-Duck passed (2 rounds)\n-->\n\n" + UNCHECKED_BODY
        ok, _ = gate.evaluate(body)
        self.assertFalse(ok)

    def test_stamp_quoted_in_code_fence_fails(self):
        body = "Here is the template:\n\n```\n- [x] Multi-Duck passed (2 rounds)\n```\n\n" + UNCHECKED_BODY
        ok, _ = gate.evaluate(body)
        self.assertFalse(ok)

    def test_both_boxes_checked_fails(self):
        body = ("- [x] Multi-Duck passed (2 rounds of multi-duck review)\n"
                "- [x] Multi-Duck opted out - reason: also skipped\n")
        ok, msg = gate.evaluate(body)
        self.assertFalse(ok)
        self.assertIn("exactly one", msg.lower())

    def test_reason_with_comparison_operators_passes(self):
        # A real reason that merely contains "<" and ">" must not be mistaken for the placeholder.
        ok, msg = gate.evaluate("- [x] Multi-Duck opted out - reason: keep p95 < 200ms and rps > 1k")
        self.assertTrue(ok, msg)

    def test_fully_bracketed_placeholder_reason_fails(self):
        ok, _ = gate.evaluate("- [x] Multi-Duck opted out - reason: <why 2 rounds were skipped>")
        self.assertFalse(ok)

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


    def test_main_reads_event_path(self):
        # The CI path: body/author come from the GitHub Actions event payload (GITHUB_EVENT_PATH).
        import json
        import os
        import tempfile
        saved = {k: os.environ.get(k) for k in ("PR_BODY", "PR_AUTHOR", "GITHUB_EVENT_PATH")}
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        try:
            json.dump({"pull_request": {"body": PASSED_BODY, "user": {"login": "urikanonov"}}}, tmp)
            tmp.close()
            os.environ.pop("PR_BODY", None)
            os.environ.pop("PR_AUTHOR", None)
            os.environ["GITHUB_EVENT_PATH"] = tmp.name
            self.assertEqual(gate.main([]), 0)
            # A missing stamp in the payload fails.
            with open(tmp.name, "w", encoding="utf-8") as fh:
                json.dump({"pull_request": {"body": UNCHECKED_BODY, "user": {"login": "urikanonov"}}}, fh)
            self.assertEqual(gate.main([]), 1)
            # A dependabot author in the payload auto-passes even with no stamp.
            with open(tmp.name, "w", encoding="utf-8") as fh:
                json.dump({"pull_request": {"body": "", "user": {"login": "dependabot[bot]"}}}, fh)
            self.assertEqual(gate.main([]), 0)
        finally:
            os.unlink(tmp.name)
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
