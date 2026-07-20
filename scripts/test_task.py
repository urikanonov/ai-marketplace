"""Unit tests for scripts/task.py.

Run by the validate CI job via `python -m unittest discover -s scripts -p "test_*.py"`,
so the issue-first task wrapper's body assembly, ASCII guard, argument construction,
checkbox ticking, and the heartbeat / branch-stamp helpers are covered by a required
status check. The `gh` boundary is not exercised here; only the pure helpers and the
_beat_once routing (with the gh/git calls stubbed) are.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone

import task


class AsciiGuardTests(unittest.TestCase):
    def test_rejects_smart_punctuation(self):
        with self.assertRaises(ValueError):
            task.assert_ascii("uses an em\u2014dash", "description")

    def test_allows_plain_ascii(self):
        task.assert_ascii("plain - ascii ... only", "description")  # must not raise

    def test_rejects_any_non_ascii(self):
        for bad in ["caf\u00e9", "check \u2713", "emoji \U0001F600", "nbsp\u00a0here"]:
            with self.assertRaises(ValueError):
                task.assert_ascii(bad, "description")


class BuildBodyTests(unittest.TestCase):
    def test_sections_and_checkboxes(self):
        body = task.build_body("Why this matters.", ["First outcome", "Second outcome"], "1. step")
        self.assertIn("Why this matters.", body)
        self.assertIn("## Acceptance criteria", body)
        self.assertIn("- [ ] First outcome", body)
        self.assertIn("- [ ] Second outcome", body)
        self.assertIn("## Implementation plan", body)
        self.assertIn("1. step", body)

    def test_no_acceptance_or_plan_omits_sections(self):
        body = task.build_body("Just a description.", [])
        self.assertNotIn("## Acceptance criteria", body)
        self.assertNotIn("## Implementation plan", body)

    def test_smart_char_in_acceptance_raises(self):
        with self.assertRaises(ValueError):
            task.build_body("ok", ["bad \u2013 dash"])


class CreateArgsTests(unittest.TestCase):
    def test_includes_task_label_and_title(self):
        args = task.create_args("UI: title", "/tmp/b.md", [task.TASK_LABEL, "ui"])
        self.assertEqual(args[:3], ["gh", "issue", "create"])
        self.assertIn("--label", args)
        self.assertIn("task", args)
        self.assertIn("ui", args)
        self.assertEqual(args[args.index("--title") + 1], "UI: title")

    def test_smart_char_in_title_raises(self):
        with self.assertRaises(ValueError):
            task.create_args("bad \u2026 title", "/tmp/b.md", ["task"])


class TickCheckboxTests(unittest.TestCase):
    BODY = "Desc\n\n## Acceptance criteria\n\n- [ ] one\n- [ ] two\n- [ ] three\n"

    def test_ticks_requested_item_only(self):
        out = task.tick_checkbox(self.BODY, 2)
        self.assertIn("- [ ] one", out)
        self.assertIn("- [x] two", out)
        self.assertIn("- [ ] three", out)

    def test_preserves_indentation(self):
        out = task.tick_checkbox("  - [ ] nested", 1)
        self.assertEqual(out, "  - [x] nested")

    def test_index_out_of_range_raises(self):
        with self.assertRaises(IndexError):
            task.tick_checkbox(self.BODY, 4)

    def test_index_below_one_raises(self):
        with self.assertRaises(IndexError):
            task.tick_checkbox(self.BODY, 0)

    def test_already_checked_target_is_idempotent(self):
        # k is a stable ordinal, so item 1 being already checked makes ticking 1 a no-op.
        body = "- [x] done\n- [ ] pending\n"
        self.assertEqual(task.tick_checkbox(body, 1), "- [x] done\n- [ ] pending")
        # Ticking 2 checks the real second criterion, not a shifted one.
        self.assertEqual(task.tick_checkbox(body, 2), "- [x] done\n- [x] pending")

    def test_index_stable_as_items_are_checked(self):
        after1 = task.tick_checkbox(self.BODY, 1)
        after2 = task.tick_checkbox(after1, 2)
        self.assertIn("- [x] one", after2)
        self.assertIn("- [x] two", after2)
        self.assertIn("- [ ] three", after2)

    def test_scoped_to_acceptance_section(self):
        body = ("Desc\n\n## Implementation plan\n\n- [ ] plan step\n\n"
                "## Acceptance criteria\n\n- [ ] real one\n- [ ] real two\n")
        out = task.tick_checkbox(body, 1)
        self.assertIn("- [ ] plan step", out)
        self.assertIn("- [x] real one", out)

    def test_scoped_to_acceptance_section_h3_form(self):
        # GitHub issue forms render each field label as a level-3 heading.
        body = ("### Description\n\nwhy\n\n### Acceptance criteria\n\n"
                "- [ ] real one\n- [ ] real two\n\n### Before starting\n\n"
                "- [ ] I searched issues\n- [ ] I wrote a test\n")
        out = task.tick_checkbox(body, 2)
        self.assertIn("- [x] real two", out)
        self.assertIn("- [ ] I searched issues", out)
        with self.assertRaises(IndexError):
            task.tick_checkbox(body, 3)

    def test_ignores_checkboxes_after_next_heading(self):
        body = "## Acceptance criteria\n\n- [ ] a\n- [ ] b\n\n## Other\n\n- [ ] c\n"
        with self.assertRaises(IndexError):
            task.tick_checkbox(body, 3)


class TickAllCheckboxesTests(unittest.TestCase):
    BODY = "Desc\n\n## Acceptance criteria\n\n- [ ] one\n- [ ] two\n- [ ] three\n"

    def test_ticks_every_criterion(self):
        out = task.tick_all_checkboxes(self.BODY)
        self.assertIn("- [x] one", out)
        self.assertIn("- [x] two", out)
        self.assertIn("- [x] three", out)

    def test_preserves_text_outside_ac_section(self):
        body = ("Desc\n\n## Implementation plan\n\n- [ ] plan step\n\n"
                "## Acceptance criteria\n\n- [ ] real one\n- [ ] real two\n\n## Notes\n\nkeep me\n")
        out = task.tick_all_checkboxes(body)
        self.assertIn("- [ ] plan step", out)  # a checkbox outside the AC section is untouched
        self.assertIn("- [x] real one", out)
        self.assertIn("- [x] real two", out)
        self.assertIn("keep me", out)

    def test_idempotent_when_all_checked(self):
        body = "## Acceptance criteria\n\n- [x] a\n- [x] b\n"
        self.assertEqual(task.tick_all_checkboxes(body), "## Acceptance criteria\n\n- [x] a\n- [x] b")

    def test_preserves_indentation(self):
        out = task.tick_all_checkboxes("## Acceptance criteria\n\n  - [ ] nested\n")
        self.assertIn("  - [x] nested", out)

    def test_no_criteria_raises(self):
        with self.assertRaises(IndexError):
            task.tick_all_checkboxes("## Acceptance criteria\n\nno boxes here\n")

    def test_preserves_blank_lines_and_headings(self):
        # The whole Markdown structure (blank lines, headings, prose) must survive verbatim -
        # this is exactly what a naive PowerShell array round-trip destroyed on issue #478.
        body = ("## Description\n\nWhy.\n\n## Acceptance criteria\n\n- [ ] a\n- [ ] b\n\n"
                "## Notes\n\nEnd.\n")
        out = task.tick_all_checkboxes(body)
        self.assertEqual(out, ("## Description\n\nWhy.\n\n## Acceptance criteria\n\n"
                               "- [x] a\n- [x] b\n\n## Notes\n\nEnd."))


class ApplyAcCheckTests(unittest.TestCase):
    BODY = "## Acceptance criteria\n\n- [ ] one\n- [ ] two\n"

    def test_all_flag_ticks_every_criterion(self):
        out = task.apply_ac_check(self.BODY, None, True)
        self.assertIn("- [x] one", out)
        self.assertIn("- [x] two", out)

    def test_index_ticks_only_that_criterion(self):
        out = task.apply_ac_check(self.BODY, 2, False)
        self.assertIn("- [ ] one", out)
        self.assertIn("- [x] two", out)

    def test_neither_index_nor_all_raises(self):
        with self.assertRaises(ValueError):
            task.apply_ac_check(self.BODY, None, False)


class ParserTests(unittest.TestCase):
    def test_new_parses_repeatable_ac(self):
        args = task.build_parser().parse_args(
            ["new", "T", "-d", "why", "--ac", "a", "--ac", "b"])
        self.assertEqual(args.ac, ["a", "b"])

    def test_search_all_flag(self):
        args = task.build_parser().parse_args(["search", "topic", "--all"])
        self.assertTrue(args.all)

    def test_check_ac_parses_index(self):
        args = task.build_parser().parse_args(["check-ac", "188", "2"])
        self.assertEqual(args.index, 2)
        self.assertFalse(args.all)

    def test_check_ac_parses_all_flag_without_index(self):
        args = task.build_parser().parse_args(["check-ac", "188", "--all"])
        self.assertIsNone(args.index)
        self.assertTrue(args.all)

    def test_claim_accepts_branch(self):
        args = task.build_parser().parse_args(["claim", "5", "--branch", "issue-5-foo"])
        self.assertEqual(args.branch, "issue-5-foo")

    def test_heartbeat_watch_and_interval(self):
        args = task.build_parser().parse_args(["heartbeat", "5", "--watch", "--interval", "60"])
        self.assertTrue(args.watch)
        self.assertEqual(args.interval, 60)

    def test_heartbeat_default_interval_is_five_minutes(self):
        args = task.build_parser().parse_args(["heartbeat", "5"])
        self.assertFalse(args.watch)
        self.assertEqual(args.interval, task.HEARTBEAT_INTERVAL_SECONDS)

    def test_stale_default_minutes(self):
        args = task.build_parser().parse_args(["stale"])
        self.assertEqual(args.minutes, task.HEARTBEAT_STALE_MINUTES)

    def test_start_parses_slug_and_name(self):
        args = task.build_parser().parse_args(["start", "5", "--slug", "Fix Thing", "--name", "wt"])
        self.assertEqual(args.slug, "Fix Thing")
        self.assertEqual(args.name, "wt")


class UtcStampTests(unittest.TestCase):
    def test_formats_fixed_datetime_as_zulu(self):
        dt = datetime(2026, 7, 18, 13, 55, 0, tzinfo=timezone.utc)
        self.assertEqual(task.utc_stamp(dt), "2026-07-18T13:55:00Z")

    def test_converts_non_utc_to_utc(self):
        dt = datetime(2026, 7, 18, 16, 55, 0, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(task.utc_stamp(dt), "2026-07-18T13:55:00Z")


class StatusBodyTests(unittest.TestCase):
    def test_carries_marker_branch_and_timestamp(self):
        body = task.status_body("issue-5-foo", "2026-07-18T13:55:00Z")
        self.assertIn(task.STATUS_MARKER, body)
        self.assertIn("`issue-5-foo`", body)
        self.assertIn("- Last active (UTC): 2026-07-18T13:55:00Z", body)

    def test_is_plain_ascii(self):
        task.assert_ascii(task.status_body("issue-5-foo", "2026-07-18T13:55:00Z"), "status body")

    def test_rejects_non_ascii_branch(self):
        with self.assertRaises(ValueError):
            task.status_body("issue-5-caf\u00e9", "2026-07-18T13:55:00Z")

    def test_rejects_backtick_or_leading_dash_or_space_branch(self):
        for bad in ["--force", "has`tick", "has space", " ", ""]:
            with self.assertRaises(ValueError):
                task.status_body(bad, "2026-07-18T13:55:00Z")


class AssertValidBranchTests(unittest.TestCase):
    def test_accepts_normal_and_strips(self):
        self.assertEqual(task.assert_valid_branch("  issue-5-foo  "), "issue-5-foo")

    def test_rejects_leading_dash_backtick_space_and_empty(self):
        for bad in ["-x", "a`b", "a b", "", "   "]:
            with self.assertRaises(ValueError):
                task.assert_valid_branch(bad)


class BumpLastActiveTests(unittest.TestCase):
    def test_updates_only_timestamp_and_keeps_branch(self):
        body = task.status_body("issue-5-foo", "2026-07-18T13:55:00Z")
        out = task.bump_last_active(body, "2026-07-18T14:00:00Z")
        self.assertIn("- Last active (UTC): 2026-07-18T14:00:00Z", out)
        self.assertNotIn("13:55:00Z", out)
        self.assertIn("`issue-5-foo`", out)

    def test_raises_when_no_last_active_line(self):
        with self.assertRaises(ValueError):
            task.bump_last_active("no timestamp here", "2026-07-18T14:00:00Z")


class FindStatusCommentTests(unittest.TestCase):
    def test_returns_first_marker_comment(self):
        comments = [
            {"id": 1, "body": "unrelated"},
            {"id": 2, "body": task.STATUS_MARKER + "\nstuff"},
            {"id": 3, "body": task.STATUS_MARKER + "\nlater"},
        ]
        self.assertEqual(task.find_status_comment(comments)["id"], 2)

    def test_returns_none_when_absent(self):
        self.assertIsNone(task.find_status_comment([{"id": 1, "body": "nope"}]))

    def test_trusted_only_ignores_untrusted_author(self):
        comments = [
            {"id": 1, "body": task.STATUS_MARKER + "\nplanted", "assoc": "NONE"},
            {"id": 2, "body": task.STATUS_MARKER + "\nreal", "assoc": "OWNER"},
        ]
        # Without the filter the outsider comment wins; with it, only the trusted one is adopted.
        self.assertEqual(task.find_status_comment(comments)["id"], 1)
        self.assertEqual(task.find_status_comment(comments, trusted_only=True)["id"], 2)

    def test_trusted_only_returns_none_when_only_untrusted(self):
        comments = [{"id": 1, "body": task.STATUS_MARKER, "assoc": "CONTRIBUTOR"}]
        self.assertIsNone(task.find_status_comment(comments, trusted_only=True))

    def test_viewer_authored_comment_is_adopted_despite_untrusted_assoc(self):
        # A bot/self account whose author_association is NONE still owns its own comment.
        comments = [{"id": 9, "body": task.STATUS_MARKER, "assoc": "NONE", "author": "me-bot"}]
        self.assertIsNone(task.find_status_comment(comments, trusted_only=True))
        self.assertEqual(
            task.find_status_comment(comments, trusted_only=True, viewer="me-bot")["id"], 9)

    def test_outsider_not_matching_viewer_is_rejected(self):
        comments = [{"id": 1, "body": task.STATUS_MARKER, "assoc": "NONE", "author": "outsider"}]
        self.assertIsNone(task.find_status_comment(comments, trusted_only=True, viewer="me-bot"))


class StatusCommentsListTests(unittest.TestCase):
    def _c(self, cid, assoc="OWNER"):
        return {"id": cid, "body": task.STATUS_MARKER + f"\n#{cid}", "assoc": assoc}

    def test_status_comments_returns_all_matches_in_order(self):
        comments = [self._c(2), {"id": 3, "body": "unrelated"}, self._c(5)]
        got = task.status_comments(comments, trusted_only=True)
        self.assertEqual([c["id"] for c in got], [2, 5])

    def test_extra_status_comment_ids_are_all_but_first(self):
        comments = [self._c(2), self._c(5), self._c(8)]
        self.assertEqual(task.extra_status_comment_ids(comments, trusted_only=True), [5, 8])

    def test_extra_ids_empty_when_zero_or_one_match(self):
        self.assertEqual(task.extra_status_comment_ids([self._c(2)], trusted_only=True), [])
        self.assertEqual(task.extra_status_comment_ids([], trusted_only=True), [])


class PickSurvivorTests(unittest.TestCase):
    def test_prefers_globally_trusted_over_self_only(self):
        # A self-only (viewer-matched, assoc NONE) comment must not win over a maintainer's.
        matches = [
            {"id": 1, "assoc": "NONE"},   # older, self-only
            {"id": 2, "assoc": "OWNER"},  # maintainer
        ]
        self.assertEqual(task._pick_survivor(matches)["id"], 2)

    def test_oldest_trusted_when_multiple_trusted(self):
        matches = [{"id": 5, "assoc": "COLLABORATOR"}, {"id": 8, "assoc": "OWNER"}]
        self.assertEqual(task._pick_survivor(matches)["id"], 5)

    def test_oldest_when_all_self_only(self):
        matches = [{"id": 3, "assoc": "NONE"}, {"id": 4, "assoc": "NONE"}]
        self.assertEqual(task._pick_survivor(matches)["id"], 3)


class MaxStampTests(unittest.TestCase):
    def test_returns_newest_valid(self):
        self.assertEqual(
            task._max_stamp(["2026-07-18T10:00:00Z", "2026-07-18T12:00:00Z", "2026-07-18T09:00:00Z"]),
            "2026-07-18T12:00:00Z")

    def test_ignores_none_and_unparseable(self):
        self.assertEqual(task._max_stamp([None, "garbage", "2026-07-18T10:00:00Z"]),
                         "2026-07-18T10:00:00Z")

    def test_none_when_no_valid(self):
        self.assertIsNone(task._max_stamp([None, "nope", ""]))

    def test_orders_by_datetime_not_string(self):
        # A non-zero-padded month (accepted by strptime) must not misorder: October > July.
        self.assertEqual(
            task._max_stamp(["2026-7-18T00:00:00Z", "2026-10-18T00:00:00Z"]),
            "2026-10-18T00:00:00Z")


class IsNewerTests(unittest.TestCase):
    def test_newer_beats_older(self):
        self.assertTrue(task.is_newer("2026-07-18T10:05:00Z", "2026-07-18T10:00:00Z"))

    def test_older_does_not_beat_newer(self):
        self.assertFalse(task.is_newer("2026-07-18T10:00:00Z", "2026-07-18T10:05:00Z"))

    def test_equal_is_not_newer(self):
        self.assertFalse(task.is_newer("2026-07-18T10:00:00Z", "2026-07-18T10:00:00Z"))

    def test_missing_or_unparseable_existing_is_writable(self):
        self.assertTrue(task.is_newer("2026-07-18T10:00:00Z", None))
        self.assertTrue(task.is_newer("2026-07-18T10:00:00Z", "none"))


class ParseBranchTests(unittest.TestCase):
    def test_extracts_branch(self):
        body = task.status_body("issue-5-foo", "2026-07-18T13:55:00Z")
        self.assertEqual(task.parse_branch(body), "issue-5-foo")

    def test_returns_none_without_line(self):
        self.assertIsNone(task.parse_branch("no branch line"))


class ParseLastActiveTests(unittest.TestCase):
    def test_extracts_timestamp(self):
        body = task.status_body("issue-5-foo", "2026-07-18T13:55:00Z")
        self.assertEqual(task.parse_last_active(body), "2026-07-18T13:55:00Z")

    def test_returns_none_without_line(self):
        self.assertIsNone(task.parse_last_active("no timestamp"))


class IsStaleTests(unittest.TestCase):
    NOW = datetime(2026, 7, 18, 14, 0, 0, tzinfo=timezone.utc)

    def test_fresh_is_not_stale(self):
        self.assertFalse(task.is_stale("2026-07-18T13:55:00Z", self.NOW, minutes=15))

    def test_old_is_stale(self):
        self.assertTrue(task.is_stale("2026-07-18T13:40:00Z", self.NOW, minutes=15))

    def test_missing_is_stale(self):
        self.assertTrue(task.is_stale(None, self.NOW, minutes=15))

    def test_unparseable_is_stale(self):
        self.assertTrue(task.is_stale("not-a-timestamp", self.NOW, minutes=15))

    def test_zero_minutes_only_exact_now_is_fresh(self):
        self.assertFalse(task.is_stale("2026-07-18T14:00:00Z", self.NOW, minutes=0))
        self.assertTrue(task.is_stale("2026-07-18T13:59:59Z", self.NOW, minutes=0))

    def test_naive_now_is_treated_as_utc(self):
        naive = datetime(2026, 7, 18, 14, 0, 0)
        self.assertFalse(task.is_stale("2026-07-18T13:55:00Z", naive, minutes=15))
        self.assertTrue(task.is_stale("2026-07-18T13:40:00Z", naive, minutes=15))


class BranchDerivationTests(unittest.TestCase):
    def test_slug_lowercases_and_dashes(self):
        self.assertEqual(task.branch_slug("Fix the Thing!"), "fix-the-thing")

    def test_slug_trims_and_bounds_length(self):
        self.assertEqual(task.branch_slug("  --Hello--  "), "hello")
        self.assertLessEqual(len(task.branch_slug("word " * 40)), 40)

    def test_slug_has_no_trailing_dash_after_truncation(self):
        # A truncation that lands on a separator must not leave a dangling dash.
        s = task.branch_slug("ab " * 30, maxlen=5)
        self.assertFalse(s.endswith("-"))

    def test_slug_empty_or_all_symbols_is_empty(self):
        self.assertEqual(task.branch_slug(""), "")
        self.assertEqual(task.branch_slug("!!! @@@"), "")

    def test_derive_branch_with_and_without_slug(self):
        self.assertEqual(task.derive_branch(414, "Heartbeat work"), "issue-414-heartbeat-work")
        self.assertEqual(task.derive_branch(414, ""), "issue-414")


class ArgTypeValidatorTests(unittest.TestCase):
    def test_positive_int_accepts_and_rejects(self):
        self.assertEqual(task._positive_int("5"), 5)
        for bad in ["0", "-1"]:
            with self.assertRaises(task.argparse.ArgumentTypeError):
                task._positive_int(bad)

    def test_non_negative_int_accepts_and_rejects(self):
        self.assertEqual(task._non_negative_int("0"), 0)
        with self.assertRaises(task.argparse.ArgumentTypeError):
            task._non_negative_int("-1")

    def test_safe_worktree_name_rejects_separators_and_dotdot(self):
        for bad in ["a/b", "a\\b", "..", "../x", "."]:
            with self.assertRaises(SystemExit):
                task._assert_safe_worktree_name(bad)
        self.assertEqual(task._assert_safe_worktree_name("issue-5-foo"), "issue-5-foo")
        self.assertIsNone(task._assert_safe_worktree_name(None))

    @unittest.skipUnless(os.name == "nt", "drive-qualified names only escape on Windows")
    def test_safe_worktree_name_rejects_windows_drive(self):
        for bad in ["C:foo", "C:\\foo", "C:/foo"]:
            with self.assertRaises(SystemExit):
                task._assert_safe_worktree_name(bad)


class _StubComments:
    """Context-managed monkeypatch of the gh/git boundary so _beat_once routing is testable.

    _list_comments returns the provided comments; _edit_comment / _post_comment / _delete_comment
    record their calls instead of shelling out; _viewer_login returns a fixed login."""
    def __init__(self, comments, viewer="me"):
        self.comments = comments
        self.viewer = viewer
        self.edited = []
        self.posted = []
        self.deleted = []

    def __enter__(self):
        self._orig = (task._list_comments, task._edit_comment, task._post_comment,
                      task._delete_comment, task._viewer_login)
        task._list_comments = lambda number: self.comments
        task._edit_comment = lambda cid, body: self.edited.append((cid, body))
        task._post_comment = lambda number, body: self.posted.append((number, body))
        task._delete_comment = lambda cid: self.deleted.append(cid)
        task._viewer_login = lambda: self.viewer
        return self

    def __exit__(self, *exc):
        (task._list_comments, task._edit_comment, task._post_comment,
         task._delete_comment, task._viewer_login) = self._orig


class BeatOnceRoutingTests(unittest.TestCase):
    def _trusted(self, body):
        return [{"id": 7, "body": body, "assoc": "OWNER"}]

    def test_existing_valid_comment_bumps_timestamp_in_place(self):
        body = task.status_body("issue-7-foo", "2026-07-18T10:00:00Z")
        with _StubComments(self._trusted(body)) as stub:
            task._beat_once(7, None)
        self.assertEqual(len(stub.edited), 1)
        self.assertEqual(len(stub.posted), 0)
        edited_body = stub.edited[0][1]
        self.assertIn("`issue-7-foo`", edited_body)          # branch preserved
        self.assertNotIn("2026-07-18T10:00:00Z", edited_body)  # timestamp refreshed

    def test_malformed_comment_self_heals_from_recovered_branch(self):
        malformed = task.STATUS_MARKER + "\n- Branch: `issue-7-foo` (note)\n(no timestamp line)"
        with _StubComments(self._trusted(malformed)) as stub:
            task._beat_once(7, None)
        self.assertEqual(len(stub.edited), 1)
        healed = stub.edited[0][1]
        self.assertIn("- Last active (UTC):", healed)
        self.assertIn("`issue-7-foo`", healed)

    def test_malformed_comment_with_invalid_branch_stops(self):
        malformed = task.STATUS_MARKER + "\n- Branch: `bad branch`\n(no timestamp line)"
        with _StubComments(self._trusted(malformed)) as stub:
            with self.assertRaises(task.HeartbeatStop):
                task._beat_once(7, None)
        self.assertEqual(stub.edited, [])

    def test_no_comment_no_branch_stops(self):
        with _StubComments([]):
            with self.assertRaises(task.HeartbeatStop):
                task._beat_once(7, None)

    def test_no_comment_with_branch_posts_fresh(self):
        with _StubComments([]) as stub:
            task._beat_once(7, "issue-7-foo")
        self.assertEqual(len(stub.posted), 1)
        self.assertIn(task.STATUS_MARKER, stub.posted[0][1])

    def test_untrusted_marker_comment_is_not_adopted(self):
        planted = [{"id": 1, "body": task.status_body("evil", "2026-07-18T10:00:00Z"), "assoc": "NONE"}]
        with _StubComments(planted) as stub:
            task._beat_once(7, "issue-7-foo")
        # The outsider comment is ignored; a fresh trusted comment is posted instead of edited.
        self.assertEqual(len(stub.edited), 0)
        self.assertEqual(len(stub.posted), 1)

    def test_does_not_regress_a_newer_timestamp(self):
        # A concurrent worker already wrote a FUTURE timestamp; this beat must not move it back.
        future = task.status_body("issue-7-foo", "2099-01-01T00:00:00Z")
        with _StubComments(self._trusted(future)) as stub:
            task._beat_once(7, None)
        self.assertEqual(stub.edited, [])  # no write - the existing stamp is newer

    def test_converges_duplicate_status_comments(self):
        body = task.status_body("issue-7-foo", "2026-07-18T10:00:00Z")
        dupes = [
            {"id": 7, "body": body, "assoc": "OWNER"},
            {"id": 8, "body": body, "assoc": "OWNER"},
            {"id": 9, "body": body, "assoc": "OWNER"},
        ]
        with _StubComments(dupes) as stub:
            task._beat_once(7, None)
        self.assertEqual(stub.edited[0][0], 7)     # the oldest (first) is edited
        self.assertEqual(sorted(stub.deleted), [8, 9])  # the duplicates are pruned

    def test_adopts_viewer_authored_comment(self):
        # A comment authored by the invoking account (assoc NONE) is adopted, not duplicated.
        body = task.status_body("issue-7-foo", "2026-07-18T10:00:00Z")
        mine = [{"id": 3, "body": body, "assoc": "NONE", "author": "me"}]
        with _StubComments(mine, viewer="me") as stub:
            task._beat_once(7, None)
        self.assertEqual(len(stub.edited), 1)
        self.assertEqual(len(stub.posted), 0)

    def test_survivor_prefers_maintainer_over_self_only(self):
        # A self-authored older comment must not cause a maintainer's comment to be pruned.
        t = "2026-07-18T10:00:00Z"
        comments = [
            {"id": 1, "body": task.status_body("issue-7-foo", t), "assoc": "NONE", "author": "me"},
            {"id": 2, "body": task.status_body("issue-7-foo", t), "assoc": "OWNER", "author": "boss"},
        ]
        with _StubComments(comments, viewer="me") as stub:
            task._beat_once(7, None)
        self.assertEqual(stub.edited[0][0], 2)   # the maintainer's comment survives
        self.assertEqual(stub.deleted, [1])      # the self-only duplicate is pruned

    def test_does_not_delete_valid_duplicate_when_survivor_unrecoverable(self):
        # Oldest survivor is malformed and unrecoverable (no branch); a valid duplicate exists.
        comments = [
            {"id": 1, "body": task.STATUS_MARKER + "\n(no branch, no timestamp)", "assoc": "OWNER"},
            {"id": 2, "body": task.status_body("issue-7-foo", "2026-07-18T10:00:00Z"), "assoc": "OWNER"},
        ]
        with _StubComments(comments) as stub:
            with self.assertRaises(task.HeartbeatStop):
                task._beat_once(7, None)
        self.assertEqual(stub.deleted, [])   # the valid duplicate is NOT deleted
        self.assertEqual(stub.edited, [])

    def test_converges_to_newest_stamp_without_regression(self):
        # A duplicate carries a newer stamp than the oldest survivor; converging must not lose it.
        older = task.status_body("issue-7-foo", "2098-01-01T00:00:00Z")
        newer = task.status_body("issue-7-foo", "2099-01-01T00:00:00Z")
        comments = [
            {"id": 1, "body": older, "assoc": "OWNER"},  # oldest -> survivor
            {"id": 2, "body": newer, "assoc": "OWNER"},  # duplicate with the newest stamp
        ]
        with _StubComments(comments) as stub:
            result = task._beat_once(7, None)
        self.assertEqual(result, "2099-01-01T00:00:00Z")           # newest preserved
        self.assertIn("2099-01-01T00:00:00Z", stub.edited[0][1])   # survivor rewritten to newest
        self.assertEqual(stub.deleted, [2])                        # duplicate pruned

    def test_viewer_unresolved_skips_post_to_avoid_duplicate(self):
        # gh api user failed (viewer ""); an untrusted marker exists -> skip rather than duplicate.
        planted = [{"id": 1, "body": task.STATUS_MARKER + "\nx", "assoc": "NONE", "author": "someone"}]
        with _StubComments(planted, viewer="") as stub:
            task._beat_once(7, "issue-7-foo")
        self.assertEqual(stub.posted, [])
        self.assertEqual(stub.edited, [])


class _StubStartBoundary:
    """Monkeypatch the git/gh boundary of cmd_start so its orchestration is testable without
    touching the filesystem or the network. `claim_rc` sets the return code of the claim step."""
    def __init__(self, claim_rc=0):
        self.claim_rc = claim_rc
        self.runs = []
        self.upserts = []

    def _run(self, args):
        self.runs.append(args)
        if "worktree" in args:
            return 0
        if "issue" in args and "edit" in args:
            return self.claim_rc
        return 0

    def __enter__(self):
        self._orig = (task._run, task._capture, task._upsert_status)
        task._run = self._run
        task._capture = lambda args: ""
        task._upsert_status = lambda number, branch, stamp=None: self.upserts.append((number, branch))
        return self

    def __exit__(self, *exc):
        task._run, task._capture, task._upsert_status = self._orig


def _start_args(number=7, slug="foo", branch=None, name=None):
    return task.build_parser().parse_args(
        ["start", str(number)]
        + (["--slug", slug] if slug is not None else [])
        + (["--branch", branch] if branch else [])
        + (["--name", name] if name else []))


class CmdStartTests(unittest.TestCase):
    def test_success_creates_worktree_and_stamps(self):
        with _StubStartBoundary(claim_rc=0) as stub:
            task.cmd_start(_start_args(7, "Heartbeat work"))
        self.assertTrue(any("worktree" in r for r in stub.runs))
        self.assertEqual(stub.upserts, [(7, "issue-7-heartbeat-work")])

    def test_aborts_and_does_not_stamp_when_claim_fails(self):
        with _StubStartBoundary(claim_rc=1) as stub:
            with self.assertRaises(SystemExit):
                task.cmd_start(_start_args(7, "foo"))
        # The worktree was created, but the failed claim means the status was never stamped.
        self.assertTrue(any("worktree" in r for r in stub.runs))
        self.assertEqual(stub.upserts, [])

    def test_rejects_unsafe_name_before_any_git_call(self):
        with _StubStartBoundary() as stub:
            with self.assertRaises(SystemExit):
                task.cmd_start(_start_args(7, "foo", name="a/b"))
        self.assertEqual(stub.runs, [])

    def test_rejects_invalid_explicit_branch(self):
        with _StubStartBoundary() as stub:
            with self.assertRaises(SystemExit):
                task.cmd_start(_start_args(7, None, branch="bad branch"))
        self.assertEqual(stub.runs, [])


if __name__ == "__main__":
    unittest.main()
