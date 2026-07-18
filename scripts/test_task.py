"""Unit tests for scripts/task.py.

Run by the validate CI job via `python -m unittest discover -s scripts -p "test_*.py"`,
so the issue-first task wrapper's body assembly, ASCII guard, argument construction,
checkbox ticking, and the heartbeat / branch-stamp helpers are covered by a required
status check. The `gh` boundary is not exercised here; only the pure helpers are.
"""
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


class ParserTests(unittest.TestCase):
    def test_new_parses_repeatable_ac(self):
        args = task.build_parser().parse_args(
            ["new", "T", "-d", "why", "--ac", "a", "--ac", "b"])
        self.assertEqual(args.ac, ["a", "b"])

    def test_search_all_flag(self):
        args = task.build_parser().parse_args(["search", "topic", "--all"])
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


class BranchDerivationTests(unittest.TestCase):
    def test_slug_lowercases_and_dashes(self):
        self.assertEqual(task.branch_slug("Fix the Thing!"), "fix-the-thing")

    def test_slug_trims_and_bounds_length(self):
        self.assertEqual(task.branch_slug("  --Hello--  "), "hello")
        self.assertLessEqual(len(task.branch_slug("word " * 40)), 40)

    def test_derive_branch_with_and_without_slug(self):
        self.assertEqual(task.derive_branch(414, "Heartbeat work"), "issue-414-heartbeat-work")
        self.assertEqual(task.derive_branch(414, ""), "issue-414")


if __name__ == "__main__":
    unittest.main()
