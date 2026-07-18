#!/usr/bin/env python3
"""Thorough covering tests for the multi-duck-review PR gate (scripts/check_multi_duck_review.py).

Run by the validate CI job via `python -m unittest discover -s scripts -p "test_*.py"` (and by the
cross-platform matrix), so the required multi-duck-review gate's logic is itself gated by a required
status check. Standard library only.

Coverage map (every behavior the multi-duck panel raised has a case):
  - passed stamp: canonical / parenthetical / [X] / bullet variants / CRLF / leading spaces.
  - passed negation, 4-space-indented code block, HTML comment (closed + unclosed), fenced code
    (``` and ~~~, closed + unterminated) all FAIL (no silent/hidden pass).
  - opt-out: canonical dash/colon separators, spelling variants, (reason required) hint; negation,
    missing/empty/placeholder/too-short reason FAIL; a reason containing < and > operators PASSES.
  - exactly-one enforcement: two passed, two opt-out, passed+opt-out all FAIL.
  - a real visible stamp near stray inline backticks still PASSES (no fence false-fail).
  - dependabot auto-pass; a huge/backtick-heavy body does not hang (ReDoS sanity).
  - main(): --body-file, PR_BODY env, GITHUB_EVENT_PATH payload (pass/fail/dependabot) precedence.
"""
import json
import os
import tempfile
import time
import unittest

import check_multi_duck_review as gate


UNCHECKED_BODY = (
    "## Multi-duck review (required)\n\n"
    "- [ ] Multi-Duck passed (2 rounds of multi-duck review)\n"
    "- [ ] Multi-Duck opted out - reason: <a real, specific reason>\n"
)
PASSED_BODY = "## Summary\n\nAdds a thing.\n\n- [x] Multi-Duck passed (2 rounds of multi-duck review)\n"


def ok(body, author=None):
    return gate.evaluate(body, author)[0]


class PassedStampTests(unittest.TestCase):
    def test_canonical_and_parenthetical(self):
        self.assertTrue(ok("- [x] multi-duck passed"))
        self.assertTrue(ok("- [x] Multi-Duck passed (2 rounds of multi-duck review)"))

    def test_capital_x_and_asterisk_bullet(self):
        self.assertTrue(ok("- [X] Multi-Duck passed"))
        self.assertTrue(ok("* [x] multi-duck passed (2 rounds)"))

    def test_up_to_three_leading_spaces_ok(self):
        self.assertTrue(ok("   - [x] Multi-Duck passed"))

    def test_crlf_line_endings(self):
        self.assertTrue(ok("intro\r\n\r\n- [x] Multi-Duck passed (2 rounds)\r\n"))

    def test_embedded_in_a_larger_body(self):
        self.assertTrue(ok(PASSED_BODY))


class PassedFalsePassTests(unittest.TestCase):
    """A stamp that is invisible or negated in the rendered PR must NOT pass."""

    def test_negating_trailing_prose_fails(self):
        self.assertFalse(ok("- [x] Multi-Duck passed? No, this has not passed"))
        self.assertFalse(ok("- [x] Multi-Duck passed - actually not, skipping"))

    def test_four_space_indented_code_block_fails(self):
        self.assertFalse(ok("prose\n\n    - [x] Multi-Duck passed (2 rounds)\n\n" + UNCHECKED_BODY))

    def test_tab_indented_code_block_fails(self):
        self.assertFalse(ok("prose\n\n\t- [x] Multi-Duck passed\n"))

    def test_hidden_in_closed_html_comment_fails(self):
        self.assertFalse(ok("<!-- - [x] Multi-Duck passed (2 rounds) -->\n" + UNCHECKED_BODY))

    def test_hidden_in_unclosed_html_comment_fails(self):
        # GitHub hides everything after an unclosed <!-- to EOF, so a stamp there is invisible.
        self.assertFalse(ok(UNCHECKED_BODY + "\n<!--\n- [x] Multi-Duck passed (2 rounds)\n"))

    def test_quoted_in_backtick_fence_fails(self):
        self.assertFalse(ok("Example:\n\n```\n- [x] Multi-Duck passed (2 rounds)\n```\n\n" + UNCHECKED_BODY))

    def test_quoted_in_tilde_fence_fails(self):
        self.assertFalse(ok("Example:\n\n~~~\n- [x] Multi-Duck passed (2 rounds)\n~~~\n\n" + UNCHECKED_BODY))

    def test_in_unterminated_fence_fails(self):
        self.assertFalse(ok(UNCHECKED_BODY + "\n```\n- [x] Multi-Duck passed (2 rounds)\n"))

    def test_visible_stamp_after_a_closing_comment_on_prior_line_passes(self):
        # A real closing --> then a stamp on its own line renders as a visible checkbox: accept it.
        self.assertTrue(ok("<!-- note -->\n\n- [x] Multi-Duck passed (2 rounds)\n"))


class OptOutTests(unittest.TestCase):
    def test_dash_and_colon_separators_pass(self):
        self.assertTrue(ok("- [x] Multi-Duck opted out - reason: docs-only typo fix"))
        self.assertTrue(ok("- [x] Multi-Duck opted out: trivial config-only change"))

    def test_spelling_variants_pass(self):
        for line in (
            "- [x] Multi-Duck opt out - reason: trivial config change",
            "- [x] Multi-Duck opted-out - reason: trivial config change",
            "* [x] multi-duck opted out: trivial config change",
        ):
            self.assertTrue(ok(line), line)

    def test_reason_required_hint_prefix_pass(self):
        self.assertTrue(ok("- [x] Multi-Duck opted out (reason required): trivial config change"))

    def test_reason_with_comparison_operators_passes(self):
        self.assertTrue(ok("- [x] Multi-Duck opted out - reason: keep p95 < 200ms and rps > 1k"))

    def test_negating_optout_suffix_fails(self):
        # A checked opt-out box whose text negates it (no canonical separator) must not pass.
        self.assertFalse(ok("- [x] Multi-Duck opted out? No, review is still pending"))

    def test_missing_separator_and_reason_fails(self):
        self.assertFalse(ok("- [x] Multi-Duck opted out"))

    def test_empty_reason_fails(self):
        self.assertFalse(ok("- [x] Multi-Duck opted out - reason:"))

    def test_too_short_reason_fails(self):
        self.assertFalse(ok("- [x] Multi-Duck opted out - reason: x"))

    def test_placeholder_reason_fails(self):
        self.assertFalse(ok("- [x] Multi-Duck opted out - reason: <a real, specific reason>"))
        self.assertFalse(ok("- [x] Multi-Duck opted out - reason: TODO"))
        self.assertFalse(ok("- [x] Multi-Duck opted out - reason: fill in why"))


class ExactlyOneTests(unittest.TestCase):
    def test_both_boxes_checked_fails(self):
        body = ("- [x] Multi-Duck passed (2 rounds)\n"
                "- [x] Multi-Duck opted out - reason: also skipped\n")
        okk, msg = gate.evaluate(body)
        self.assertFalse(okk)
        self.assertIn("exactly one", msg.lower())

    def test_two_passed_boxes_fail(self):
        self.assertFalse(ok("- [x] Multi-Duck passed\n- [x] Multi-Duck passed (2 rounds)\n"))

    def test_two_optout_boxes_fail(self):
        body = ("- [x] Multi-Duck opted out - reason: one good reason here\n"
                "- [x] Multi-Duck opted out - reason: another good reason here\n")
        self.assertFalse(ok(body))

    def test_unchecked_template_fails(self):
        okk, msg = gate.evaluate(UNCHECKED_BODY)
        self.assertFalse(okk)
        self.assertIn("no multi-duck stamp", msg.lower())


class FalseFailRegressionTests(unittest.TestCase):
    def test_stray_inline_backticks_do_not_swallow_a_real_stamp(self):
        # A real, checked, VISIBLE stamp must survive stray inline ``` earlier in prose.
        body = ("See the docs: use ``` to start a fence.\n\n"
                "- [x] Multi-Duck passed (2 rounds of multi-duck review)\n\n"
                "Example later:\n```\nsome unrelated code\n```\n")
        self.assertTrue(ok(body), "a real visible stamp must not be eaten by fence pairing")

    def test_stamp_between_prose_and_a_later_fence_passes(self):
        body = ("- [x] Multi-Duck passed (2 rounds)\n\nhere is a fence:\n```\ncode\n```\n")
        self.assertTrue(ok(body))


class AuthorTests(unittest.TestCase):
    def test_dependabot_auto_passes_without_stamp(self):
        self.assertTrue(ok("", author="dependabot[bot]"))
        self.assertTrue(ok("", author="dependabot-preview[bot]"))
        self.assertTrue(ok("", author="Dependabot[bot]"))  # case-insensitive

    def test_non_dependabot_author_still_needs_stamp(self):
        self.assertFalse(ok("", author="urikanonov"))
        self.assertFalse(ok(UNCHECKED_BODY, author="some-contributor"))


class RobustnessTests(unittest.TestCase):
    def test_empty_and_none_body_fail(self):
        self.assertFalse(ok(""))
        self.assertFalse(ok(None))

    def test_backtick_heavy_body_does_not_hang(self):
        # ReDoS sanity: many stray fence markers must evaluate quickly and deterministically.
        body = ("```\n" * 500) + "- [x] Multi-Duck passed\n"
        start = time.time()
        gate.evaluate(body)
        self.assertLess(time.time() - start, 2.0)

    def test_large_body_with_stamp_passes(self):
        body = ("lorem ipsum " * 5000) + "\n- [x] Multi-Duck passed (2 rounds)\n"
        self.assertTrue(ok(body))


class HelperUnitTests(unittest.TestCase):
    def test_strip_noise_removes_closed_and_unclosed_constructs(self):
        self.assertNotIn("SECRET", gate._strip_noise("<!-- SECRET -->"))
        self.assertNotIn("SECRET", gate._strip_noise("<!-- SECRET to eof"))
        self.assertNotIn("SECRET", gate._strip_noise("```\nSECRET\n```"))
        self.assertNotIn("SECRET", gate._strip_noise("```\nSECRET to eof"))

    def test_clean_reason_strips_label(self):
        self.assertEqual(gate._clean_reason("reason: because things"), "because things")
        self.assertEqual(gate._clean_reason("  because things  "), "because things")

    def test_reason_is_valid(self):
        self.assertTrue(gate._reason_is_valid("a genuine reason"))
        self.assertTrue(gate._reason_is_valid("keep p95 < 1s and n > 2"))
        self.assertFalse(gate._reason_is_valid("<placeholder here>"))
        self.assertFalse(gate._reason_is_valid("ab"))
        self.assertFalse(gate._reason_is_valid("tbd"))


class MainTests(unittest.TestCase):
    def _clear_env(self):
        for k in ("PR_BODY", "PR_AUTHOR", "GITHUB_EVENT_PATH"):
            os.environ.pop(k, None)

    @staticmethod
    def _restore(saved):
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_body_file_takes_precedence(self):
        saved = {k: os.environ.get(k) for k in ("PR_BODY", "GITHUB_EVENT_PATH")}
        tf = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
        try:
            tf.write(PASSED_BODY)
            tf.close()
            os.environ["PR_BODY"] = UNCHECKED_BODY  # ignored in favor of --body-file
            self.assertEqual(gate.main(["--body-file", tf.name]), 0)
        finally:
            os.unlink(tf.name)
            self._restore(saved)

    def test_pr_body_env_used_over_event_path(self):
        saved = {k: os.environ.get(k) for k in ("PR_BODY", "PR_AUTHOR", "GITHUB_EVENT_PATH")}
        try:
            self._clear_env()
            os.environ["PR_BODY"] = PASSED_BODY
            self.assertEqual(gate.main([]), 0)
            os.environ["PR_BODY"] = UNCHECKED_BODY
            self.assertEqual(gate.main([]), 1)
        finally:
            self._restore(saved)

    def test_event_path_payload_pass_fail_and_dependabot(self):
        saved = {k: os.environ.get(k) for k in ("PR_BODY", "PR_AUTHOR", "GITHUB_EVENT_PATH")}
        tf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        tf.close()

        def write_event(body, login):
            with open(tf.name, "w", encoding="utf-8") as fh:
                json.dump({"pull_request": {"body": body, "user": {"login": login}}}, fh)

        try:
            self._clear_env()
            os.environ["GITHUB_EVENT_PATH"] = tf.name
            write_event(PASSED_BODY, "urikanonov")
            self.assertEqual(gate.main([]), 0)
            write_event(UNCHECKED_BODY, "urikanonov")
            self.assertEqual(gate.main([]), 1)
            write_event("", "dependabot[bot]")  # auto-pass from payload author
            self.assertEqual(gate.main([]), 0)
        finally:
            os.unlink(tf.name)
            self._restore(saved)


if __name__ == "__main__":
    unittest.main()
