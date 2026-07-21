"""Unit tests for scripts/task.py.

Run by the validate CI job via `python -m unittest discover -s scripts -p "test_*.py"`,
so the issue-first task wrapper's body assembly, ASCII guard, argument construction,
checkbox ticking, and the heartbeat / branch-stamp helpers are covered by a required
status check. The `gh` boundary is not exercised here; only the pure helpers and the
_beat_once routing (with the gh/git calls stubbed) are.
"""
import json
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

    def test_no_acceptance_heading_does_not_tick_unrelated_boxes(self):
        # Without a "## Acceptance criteria" heading, --all must NOT fall back to the whole body
        # and tick unrelated checkboxes (e.g. an implementation plan or "before starting" list).
        body = "## Implementation plan\n\n- [ ] step one\n- [ ] step two\n"
        with self.assertRaises(IndexError):
            task.tick_all_checkboxes(body)

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

    def test_index_and_all_together_raises(self):
        # --all with an explicit index is contradictory; fail loudly instead of silently
        # discarding the index and ticking everything.
        with self.assertRaises(ValueError):
            task.apply_ac_check(self.BODY, 1, True)


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

    def test_heartbeat_accepts_session_id(self):
        args = task.build_parser().parse_args(["heartbeat", "5", "--session-id", "sess-9"])
        self.assertEqual(args.session_id, "sess-9")

    def test_claim_accepts_session_id(self):
        args = task.build_parser().parse_args(["claim", "5", "--session-id", "sess-9"])
        self.assertEqual(args.session_id, "sess-9")

    def test_board_parses_defaults_and_flags(self):
        args = task.build_parser().parse_args(["board"])
        self.assertFalse(args.json)
        self.assertFalse(args.all_labels)
        self.assertEqual(args.minutes, task.HEARTBEAT_STALE_MINUTES)
        args = task.build_parser().parse_args(["board", "--json", "--all-labels", "--minutes", "30"])
        self.assertTrue(args.json)
        self.assertTrue(args.all_labels)
        self.assertEqual(args.minutes, 30)

    def test_start_parses_slug_and_name(self):
        args = task.build_parser().parse_args(["start", "5", "--slug", "Fix Thing", "--name", "wt"])
        self.assertEqual(args.slug, "Fix Thing")
        self.assertEqual(args.name, "wt")

    def test_project_sync_parses_defaults_and_flags(self):
        args = task.build_parser().parse_args(["project-sync"])
        self.assertIsNone(args.issue)
        self.assertIsNone(args.project_number)
        self.assertFalse(args.dry_run)
        args = task.build_parser().parse_args(
            ["project-sync", "--issue", "5", "--project-number", "3", "--dry-run"])
        self.assertEqual(args.issue, 5)
        self.assertEqual(args.project_number, 3)
        self.assertTrue(args.dry_run)

    def test_heartbeat_accepts_project_sync_flag(self):
        args = task.build_parser().parse_args(["heartbeat", "5", "--project-sync"])
        self.assertTrue(args.project_sync)
        args = task.build_parser().parse_args(["heartbeat", "5"])
        self.assertFalse(args.project_sync)


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

    def test_includes_handling_session_when_given(self):
        body = task.status_body("issue-5-foo", "2026-07-18T13:55:00Z", "sess-abc123")
        self.assertIn("- Handling session: `sess-abc123`", body)
        self.assertEqual(task.parse_session(body), "sess-abc123")
        task.assert_ascii(body, "status body")  # still plain ASCII

    def test_omits_handling_session_when_absent(self):
        body = task.status_body("issue-5-foo", "2026-07-18T13:55:00Z")
        self.assertNotIn("Handling session", body)
        self.assertIsNone(task.parse_session(body))

    def test_rejects_bad_session(self):
        for bad in ["has`tick", "has space"]:
            with self.assertRaises(ValueError):
                task.status_body("issue-5-foo", "2026-07-18T13:55:00Z", bad)


class ParseSessionTests(unittest.TestCase):
    def test_reads_session_back(self):
        body = task.status_body("issue-5-foo", "2026-07-18T13:55:00Z", "061a371f-d345")
        self.assertEqual(task.parse_session(body), "061a371f-d345")

    def test_returns_none_when_absent(self):
        self.assertIsNone(task.parse_session("no session line"))


class SetSessionTests(unittest.TestCase):
    def test_inserts_after_branch_when_absent(self):
        body = task.status_body("issue-5-foo", "2026-07-18T13:55:00Z")
        out = task.set_session(body, "sess-1")
        self.assertEqual(task.parse_session(out), "sess-1")
        # inserted after Branch, before Last active
        self.assertLess(out.index("Handling session"), out.index("Last active"))
        self.assertGreater(out.index("Handling session"), out.index("Branch"))

    def test_replaces_existing_session(self):
        body = task.status_body("issue-5-foo", "2026-07-18T13:55:00Z", "old-sess")
        out = task.set_session(body, "new-sess")
        self.assertEqual(task.parse_session(out), "new-sess")
        self.assertNotIn("old-sess", out)
        self.assertEqual(out.count("Handling session"), 1)

    def test_empty_session_preserves_existing(self):
        body = task.status_body("issue-5-foo", "2026-07-18T13:55:00Z", "keep-me")
        self.assertEqual(task.set_session(body, ""), body)

    def test_empty_session_on_body_without_one_is_unchanged(self):
        body = task.status_body("issue-5-foo", "2026-07-18T13:55:00Z")
        self.assertEqual(task.set_session(body, ""), body)

    def test_falls_back_to_before_last_active_when_no_branch_line(self):
        body = task.STATUS_MARKER + "\n- Last active (UTC): 2026-07-18T13:55:00Z\n"
        out = task.set_session(body, "sess-1")
        self.assertEqual(task.parse_session(out), "sess-1")
        self.assertLess(out.index("Handling session"), out.index("Last active"))

    def test_rejects_bad_session(self):
        body = task.status_body("issue-5-foo", "2026-07-18T13:55:00Z")
        with self.assertRaises(ValueError):
            task.set_session(body, "has space")

    def test_replaces_a_malformed_existing_session_line(self):
        # A malformed session line (no code span) must be REPLACED, not left beside a new one.
        body = (task.STATUS_MARKER + "\n- Branch: `issue-5-foo`\n"
                "- Handling session: broken-no-backticks\n- Last active (UTC): 2026-07-18T13:55:00Z\n")
        out = task.set_session(body, "good-sess")
        self.assertEqual(out.count("Handling session"), 1)
        self.assertEqual(task.parse_session(out), "good-sess")
        self.assertNotIn("broken-no-backticks", out)

    def test_dedupes_multiple_existing_session_lines(self):
        body = (task.STATUS_MARKER + "\n- Branch: `issue-5-foo`\n"
                "- Handling session: `a`\n- Handling session: `b`\n"
                "- Last active (UTC): 2026-07-18T13:55:00Z\n")
        out = task.set_session(body, "c")
        self.assertEqual(out.count("Handling session"), 1)
        self.assertEqual(task.parse_session(out), "c")


class SessionArgTests(unittest.TestCase):
    class _Args:
        def __init__(self, session_id=None):
            self.session_id = session_id

    def setUp(self):
        self._env = os.environ.pop("COPILOT_AGENT_SESSION_ID", None)

    def tearDown(self):
        if self._env is not None:
            os.environ["COPILOT_AGENT_SESSION_ID"] = self._env
        else:
            os.environ.pop("COPILOT_AGENT_SESSION_ID", None)

    def test_explicit_valid_session_returned(self):
        self.assertEqual(task._session_arg(self._Args("sess-9")), "sess-9")

    def test_env_fallback(self):
        os.environ["COPILOT_AGENT_SESSION_ID"] = "env-sess"
        self.assertEqual(task._session_arg(self._Args(None)), "env-sess")

    def test_empty_when_unset(self):
        self.assertEqual(task._session_arg(self._Args(None)), "")

    def test_invalid_session_fails_fast_with_systemexit(self):
        with self.assertRaises(SystemExit):
            task._session_arg(self._Args("bad session with space"))


class BoardRowTests(unittest.TestCase):
    NOW = datetime(2026, 7, 18, 14, 0, 0, tzinfo=timezone.utc)

    def test_active_row_from_fresh_status(self):
        body = task.status_body("issue-5-foo", "2026-07-18T13:58:00Z", "sess-1")
        row = task.board_row({"number": 5, "title": "Do a thing"}, body, self.NOW)
        self.assertEqual(row["number"], 5)
        self.assertEqual(row["session"], "sess-1")
        self.assertEqual(row["branch"], "issue-5-foo")
        self.assertEqual(row["last_active"], "2026-07-18T13:58:00Z")
        self.assertEqual(row["state"], "active")

    def test_stale_row_from_old_status(self):
        body = task.status_body("issue-5-foo", "2026-07-18T10:00:00Z", "sess-1")
        row = task.board_row({"number": 5, "title": "Old"}, body, self.NOW)
        self.assertEqual(row["state"], "stale")

    def test_none_row_when_no_status_comment(self):
        row = task.board_row({"number": 9, "title": "Untouched"}, "", self.NOW)
        self.assertEqual(row["state"], "none")
        self.assertEqual(row["session"], "")
        self.assertEqual(row["branch"], "")
        self.assertEqual(row["last_active"], "")


class FormatBoardTests(unittest.TestCase):
    def test_table_has_headers_and_row_data(self):
        rows = [{"number": 5, "title": "Do a thing", "session": "sess-1",
                 "branch": "issue-5-foo", "last_active": "2026-07-18T13:58:00Z", "state": "active"}]
        out = task.format_board(rows)
        for token in ("Issue", "State", "Session", "Branch", "Last active", "Title",
                      "5", "sess-1", "issue-5-foo", "2026-07-18T13:58:00Z", "active", "Do a thing"):
            self.assertIn(token, out)

    def test_empty_rows_is_a_message_not_a_crash(self):
        self.assertIn("No open", task.format_board([]))


class ResolveProjectNumberTests(unittest.TestCase):
    def test_explicit_wins(self):
        self.assertEqual(task.resolve_project_number(explicit=5, env="9"), 5)

    def test_env_fallback_when_no_explicit(self):
        self.assertEqual(task.resolve_project_number(explicit=None, env="7"), 7)

    def test_default_when_neither(self):
        self.assertEqual(task.resolve_project_number(explicit=None, env=None),
                         task.DEFAULT_PROJECT_NUMBER)

    def test_empty_env_falls_back_to_default(self):
        self.assertEqual(task.resolve_project_number(explicit=None, env=""),
                         task.DEFAULT_PROJECT_NUMBER)

    def test_zero_disables(self):
        self.assertIsNone(task.resolve_project_number(explicit=0))
        self.assertIsNone(task.resolve_project_number(env="0"))

    def test_negative_disables(self):
        self.assertIsNone(task.resolve_project_number(explicit=-1))

    def test_unparseable_env_disables(self):
        self.assertIsNone(task.resolve_project_number(env="abc"))


class SelectTextFieldIdTests(unittest.TestCase):
    FIELDS = [
        {"id": "PVTF_status", "name": "Status", "dataType": "SINGLE_SELECT"},
        {"id": "PVTF_session", "name": "Session", "dataType": "TEXT"},
        {"id": "PVTF_active", "name": "Last active", "dataType": "TEXT"},
    ]

    def test_finds_text_field_by_name(self):
        self.assertEqual(task.select_text_field_id(self.FIELDS, "Session"), "PVTF_session")
        self.assertEqual(task.select_text_field_id(self.FIELDS, "Last active"), "PVTF_active")

    def test_none_when_absent(self):
        self.assertIsNone(task.select_text_field_id(self.FIELDS, "Nope"))

    def test_ignores_non_text_field_with_matching_name(self):
        fields = [{"id": "PVTF_x", "name": "Session", "dataType": "SINGLE_SELECT"}]
        self.assertIsNone(task.select_text_field_id(fields, "Session"))

    def test_empty_fields_is_none(self):
        self.assertIsNone(task.select_text_field_id([], "Session"))

    def test_accepts_lowercase_text_datatype(self):
        fields = [{"id": "PVTF_s", "name": "Session", "dataType": "text"}]
        self.assertEqual(task.select_text_field_id(fields, "Session"), "PVTF_s")

    def test_missing_datatype_key_is_none(self):
        fields = [{"id": "PVTF_s", "name": "Session"}]
        self.assertIsNone(task.select_text_field_id(fields, "Session"))


class SelectItemIdForProjectTests(unittest.TestCase):
    NODES = [
        {"id": "PVTI_other", "project": {"id": "PVT_other"}},
        {"id": "PVTI_mine", "project": {"id": "PVT_mine"}},
    ]

    def test_picks_item_on_matching_project(self):
        self.assertEqual(task.select_item_id_for_project(self.NODES, "PVT_mine"), "PVTI_mine")
        self.assertEqual(task.select_item_id_for_project(self.NODES, "PVT_other"), "PVTI_other")

    def test_none_when_no_project_matches(self):
        self.assertIsNone(task.select_item_id_for_project(self.NODES, "PVT_absent"))

    def test_skips_null_node_and_missing_id(self):
        nodes = [None, {"project": {"id": "PVT_mine"}}, {"id": "PVTI_ok", "project": {"id": "PVT_mine"}}]
        self.assertEqual(task.select_item_id_for_project(nodes, "PVT_mine"), "PVTI_ok")

    def test_empty_nodes(self):
        self.assertIsNone(task.select_item_id_for_project([], "PVT_mine"))


class BuildFieldUpdateVariablesTests(unittest.TestCase):
    def test_builds_string_variable_map(self):
        got = task.build_field_update_variables("PVT_p", "PVTI_i", "PVTF_f", "sess-1")
        self.assertEqual(got, {
            "projectId": "PVT_p",
            "itemId": "PVTI_i",
            "fieldId": "PVTF_f",
            "value": "sess-1",
        })


class ParseActiveScopesTests(unittest.TestCase):
    def test_single_github_account(self):
        text = (
            "github.com\n"
            "  x Logged in to github.com account urikanonov (keyring)\n"
            "  - Active account: true\n"
            "  - Token scopes: 'gist', 'project', 'read:org', 'repo', 'workflow'\n")
        self.assertEqual(task.parse_active_scopes(text),
                         {"gist", "project", "read:org", "repo", "workflow"})

    def test_active_account_not_first_on_same_host(self):
        text = (
            "github.com\n"
            "  x Logged in to github.com account bot (keyring)\n"
            "  - Active account: false\n"
            "  - Token scopes: 'repo'\n"
            "  x Logged in to github.com account urikanonov (keyring)\n"
            "  - Active account: true\n"
            "  - Token scopes: 'gist', 'project'\n")
        self.assertEqual(task.parse_active_scopes(text), {"gist", "project"})

    def test_ignores_other_host_active_account(self):
        text = (
            "ghe.example.com\n"
            "  x Logged in to ghe.example.com account alice (keyring)\n"
            "  - Active account: true\n"
            "  - Token scopes: 'repo'\n"
            "\n"
            "github.com\n"
            "  x Logged in to github.com account urikanonov (keyring)\n"
            "  - Active account: true\n"
            "  - Token scopes: 'gist', 'project', 'repo'\n")
        self.assertEqual(task.parse_active_scopes(text), {"gist", "project", "repo"})

    def test_none_when_only_other_host(self):
        text = (
            "ghe.example.com\n"
            "  x Logged in to ghe.example.com account alice (keyring)\n"
            "  - Active account: true\n"
            "  - Token scopes: 'repo', 'project'\n")
        self.assertIsNone(task.parse_active_scopes(text))

    def test_none_when_scopes_line_unparseable(self):
        text = (
            "github.com\n"
            "  x Logged in to github.com account urikanonov (keyring)\n"
            "  - Active account: true\n"
            "  - Token scopes: none listed\n")
        self.assertIsNone(task.parse_active_scopes(text))

    def test_none_when_no_scopes_line(self):
        text = (
            "github.com\n"
            "  x Logged in to github.com account urikanonov (keyring)\n"
            "  - Active account: true\n")
        self.assertIsNone(task.parse_active_scopes(text))

    def test_none_on_empty_text(self):
        self.assertIsNone(task.parse_active_scopes(""))


class ProjectSyncBestEffortTests(unittest.TestCase):
    """The heartbeat MUST never be broken by a project-sync problem: _project_sync_best_effort must
    swallow both Exception AND SystemExit (the latter is a BaseException, not an Exception, and is
    what _capture/_graphql raise on a nonzero gh exit)."""

    def setUp(self):
        self._orig = task.cmd_project_sync

    def tearDown(self):
        task.cmd_project_sync = self._orig

    def test_swallows_systemexit_and_returns_false(self):
        def boom(_a):
            raise SystemExit(1)
        task.cmd_project_sync = boom
        self.assertFalse(task._project_sync_best_effort(5))

    def test_swallows_exception_and_returns_false(self):
        def boom(_a):
            raise RuntimeError("network down")
        task.cmd_project_sync = boom
        self.assertFalse(task._project_sync_best_effort(5))

    def test_returns_true_on_clean_run(self):
        task.cmd_project_sync = lambda _a: None
        self.assertTrue(task._project_sync_best_effort(5))


class ItemFieldTextTests(unittest.TestCase):
    NODES = [
        {"text": "sess-1", "field": {"name": "Session"}},
        {"text": "2026-07-18T13:58:00Z", "field": {"name": "Last active"}},
    ]

    def test_returns_matching_field_text(self):
        self.assertEqual(task.item_field_text(self.NODES, "Session"), "sess-1")
        self.assertEqual(task.item_field_text(self.NODES, "Last active"), "2026-07-18T13:58:00Z")

    def test_empty_when_field_absent(self):
        self.assertEqual(task.item_field_text(self.NODES, "Nope"), "")

    def test_empty_on_none_or_empty_nodes(self):
        self.assertEqual(task.item_field_text(None, "Session"), "")
        self.assertEqual(task.item_field_text([], "Session"), "")
        self.assertEqual(task.item_field_text([None], "Session"), "")


class FieldUpdatesTests(unittest.TestCase):
    def _values(self, session="sess-1", last="2026-07-18T13:58:00Z"):
        return {task.PROJECT_SESSION_FIELD: session, task.PROJECT_LAST_ACTIVE_FIELD: last}

    def test_writes_both_when_board_empty(self):
        got = task.field_updates(self._values(), "")
        self.assertEqual(got, {task.PROJECT_SESSION_FIELD: "sess-1",
                               task.PROJECT_LAST_ACTIVE_FIELD: "2026-07-18T13:58:00Z"})

    def test_writes_both_when_desired_is_newer(self):
        got = task.field_updates(self._values(last="2026-07-18T14:00:00Z"), "2026-07-18T13:58:00Z")
        self.assertEqual(got[task.PROJECT_LAST_ACTIVE_FIELD], "2026-07-18T14:00:00Z")

    def test_skips_all_when_board_is_newer(self):
        # Stale writer: a slow sweep must not regress a newer heartbeat already on the board.
        got = task.field_updates(self._values(last="2026-07-18T13:58:00Z"), "2026-07-18T14:05:00Z")
        self.assertEqual(got, {})

    def test_skips_all_when_equal_idempotent(self):
        got = task.field_updates(self._values(last="2026-07-18T13:58:00Z"), "2026-07-18T13:58:00Z")
        self.assertEqual(got, {})

    def test_drops_empty_values(self):
        got = task.field_updates(self._values(session="", last="2026-07-18T14:00:00Z"), "")
        self.assertEqual(got, {task.PROJECT_LAST_ACTIVE_FIELD: "2026-07-18T14:00:00Z"})

    def test_empty_last_active_still_writes_session(self):
        got = task.field_updates(self._values(session="sess-1", last=""), "2026-07-18T14:05:00Z")
        self.assertEqual(got, {task.PROJECT_SESSION_FIELD: "sess-1"})


class FieldActionTests(unittest.TestCase):
    NOW = datetime(2026, 7, 21, 14, 0, 0, tzinfo=timezone.utc)

    def test_open_and_fresh_is_set(self):
        self.assertEqual(task.field_action("OPEN", "2026-07-21T13:58:00Z", self.NOW), "set")

    def test_open_but_stale_is_clear(self):
        self.assertEqual(task.field_action("OPEN", "2026-07-21T10:00:00Z", self.NOW), "clear")

    def test_open_with_missing_last_active_is_clear(self):
        self.assertEqual(task.field_action("OPEN", "", self.NOW), "clear")

    def test_closed_is_clear_even_if_fresh(self):
        self.assertEqual(task.field_action("CLOSED", "2026-07-21T13:59:00Z", self.NOW), "clear")

    def test_state_is_case_insensitive(self):
        self.assertEqual(task.field_action("open", "2026-07-21T13:58:00Z", self.NOW), "set")
        self.assertEqual(task.field_action("closed", "2026-07-21T13:58:00Z", self.NOW), "clear")

    def test_unknown_state_is_clear(self):
        self.assertEqual(task.field_action(None, "2026-07-21T13:58:00Z", self.NOW), "clear")


class _StubProjectSync:
    """Monkeypatch the gh/GraphQL boundary so project-sync ORCHESTRATION is testable end to end:
    _graphql dispatches on the (identity-compared) query constant and records update/clear
    mutations; _token_scopes / _viewer_login / _list_comments return canned data; _utc_now is
    pinned so the field_action (set/clear) decision is deterministic."""
    NOW = datetime(2026, 7, 21, 14, 0, 0, tzinfo=timezone.utc)

    def __init__(self, scopes=frozenset({"project"}), fields=None, issue_state="OPEN",
                 issue_nodes=None, sweep_nodes=None, comments_by_issue=None, now=None):
        self.scopes = None if scopes is None else set(scopes)
        self.fields = fields if fields is not None else [
            {"id": "F_sess", "name": "Session", "dataType": "TEXT"},
            {"id": "F_last", "name": "Last active", "dataType": "TEXT"}]
        self.issue_state = issue_state
        self.issue_nodes = issue_nodes or []
        self.sweep_nodes = sweep_nodes or []
        self.comments_by_issue = comments_by_issue or {}
        self.now = now or self.NOW
        self.mutations = []   # update (set) mutations
        self.clears = []      # clear mutations
        self.graphql_calls = 0

    def _graphql(self, query, str_vars=None, int_vars=None):
        self.graphql_calls += 1
        if query == task._PROJECT_FIELDS_QUERY:
            return {"data": {"user": {"projectV2": {"id": "PVT_1",
                    "fields": {"nodes": self.fields}}}}}
        if query == task._ISSUE_ITEMS_QUERY:
            return {"data": {"repository": {"issue": {"state": self.issue_state,
                    "projectItems": {"nodes": self.issue_nodes}}}}}
        if query == task._PROJECT_ITEMS_QUERY:
            return {"data": {"user": {"projectV2": {"items": {
                    "pageInfo": {"hasNextPage": False}, "nodes": self.sweep_nodes}}}}}
        if query == task._FIELD_UPDATE_MUTATION:
            self.mutations.append(str_vars)
            return {"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": str_vars["itemId"]}}}}
        if query == task._FIELD_CLEAR_MUTATION:
            self.clears.append(str_vars)
            return {"data": {"clearProjectV2ItemFieldValue": {"projectV2Item": {"id": str_vars["itemId"]}}}}
        raise AssertionError(f"unexpected query: {query[:40]}")

    def __enter__(self):
        self._orig = (task._graphql, task._token_scopes, task._viewer_login,
                      task._list_comments, task._utc_now)
        task._graphql = self._graphql
        task._token_scopes = lambda: self.scopes
        task._viewer_login = lambda timeout=None: "me"
        task._list_comments = lambda number, timeout=None: self.comments_by_issue.get(number, [])
        task._utc_now = lambda: self.now
        return self

    def __exit__(self, *exc):
        (task._graphql, task._token_scopes, task._viewer_login,
         task._list_comments, task._utc_now) = self._orig


class _PSArgs:
    def __init__(self, issue=None, project_number=1, dry_run=False):
        self.issue = issue
        self.project_number = project_number
        self.dry_run = dry_run


class ProjectSyncRoutingTests(unittest.TestCase):
    """Orchestration tests for cmd_project_sync with the gh/GraphQL boundary stubbed (the pure-helper
    tests do not exercise target selection, item resolution, or the set/clear mutations). Timestamps
    are relative to _StubProjectSync.NOW (2026-07-21T14:00Z)."""

    FRESH = "2026-07-21T13:58:00Z"   # within the 15-min stale window of NOW
    STALE = "2026-07-21T10:00:00Z"   # older than the stale window

    def setUp(self):
        self._env = {k: os.environ.pop(k, None) for k in ("TASK_PROJECT_NUMBER", "TASK_PROJECT_OWNER")}

    def tearDown(self):
        for k, v in self._env.items():
            if v is not None:
                os.environ[k] = v

    def _status(self, session="sess-abc", last=None):
        return [{"id": 1, "body": task.status_body("issue-5-foo", last or self.FRESH, session),
                 "assoc": "OWNER"}]

    def _fv(self, session="", last=""):
        nodes = []
        if session:
            nodes.append({"text": session, "field": {"name": "Session"}})
        if last:
            nodes.append({"text": last, "field": {"name": "Last active"}})
        return {"nodes": nodes}

    def test_no_op_when_scope_missing(self):
        with _StubProjectSync(scopes={"repo"}) as stub:
            task.cmd_project_sync(_PSArgs(issue=5))
        self.assertEqual(stub.mutations, [])
        self.assertEqual(stub.graphql_calls, 0)  # skipped before any GraphQL

    def test_no_op_when_project_unconfigured(self):
        with _StubProjectSync() as stub:
            task.cmd_project_sync(_PSArgs(issue=5, project_number=0))
        self.assertEqual(stub.graphql_calls, 0)

    def test_fast_path_writes_both_fields_for_fresh_open_issue(self):
        nodes = [{"id": "IT_5", "project": {"id": "PVT_1"}, "fieldValues": self._fv()}]
        with _StubProjectSync(issue_state="OPEN", issue_nodes=nodes,
                              comments_by_issue={5: self._status()}) as stub:
            task.cmd_project_sync(_PSArgs(issue=5))
        self.assertEqual(len(stub.mutations), 2)
        self.assertEqual(stub.clears, [])
        self.assertTrue(all(m["itemId"] == "IT_5" for m in stub.mutations))
        self.assertEqual({m["value"] for m in stub.mutations}, {"sess-abc", self.FRESH})

    def test_fast_path_stale_writer_skips_when_board_newer(self):
        # Fresh heartbeat, but the board already shows an even newer stamp: monotonic guard -> no-op.
        nodes = [{"id": "IT_5", "project": {"id": "PVT_1"},
                  "fieldValues": self._fv(session="sess-abc", last="2026-07-21T13:59:30Z")}]
        with _StubProjectSync(issue_state="OPEN", issue_nodes=nodes,
                              comments_by_issue={5: self._status(last="2026-07-21T13:58:00Z")}) as stub:
            task.cmd_project_sync(_PSArgs(issue=5))
        self.assertEqual(stub.mutations, [])
        self.assertEqual(stub.clears, [])

    def test_fast_path_clears_a_closed_issue(self):
        nodes = [{"id": "IT_5", "project": {"id": "PVT_1"},
                  "fieldValues": self._fv(session="old-sess", last=self.STALE)}]
        with _StubProjectSync(issue_state="CLOSED", issue_nodes=nodes) as stub:
            task.cmd_project_sync(_PSArgs(issue=5))
        self.assertEqual(stub.mutations, [])
        self.assertEqual(len(stub.clears), 2)  # both set fields cleared
        self.assertTrue(all(c["itemId"] == "IT_5" for c in stub.clears))

    def test_fast_path_closed_but_already_blank_is_a_no_op(self):
        nodes = [{"id": "IT_5", "project": {"id": "PVT_1"}, "fieldValues": self._fv()}]
        with _StubProjectSync(issue_state="CLOSED", issue_nodes=nodes) as stub:
            task.cmd_project_sync(_PSArgs(issue=5))
        self.assertEqual(stub.clears, [])
        self.assertEqual(stub.mutations, [])

    def test_fast_path_clears_a_stale_open_issue(self):
        nodes = [{"id": "IT_5", "project": {"id": "PVT_1"},
                  "fieldValues": self._fv(session="old-sess", last=self.STALE)}]
        with _StubProjectSync(issue_state="OPEN", issue_nodes=nodes,
                              comments_by_issue={5: self._status(last=self.STALE)}) as stub:
            task.cmd_project_sync(_PSArgs(issue=5))
        self.assertEqual(stub.mutations, [])
        self.assertEqual(len(stub.clears), 2)  # abandoned in-progress issue: clear the dead session

    def test_fast_path_off_board_issue_writes_nothing(self):
        nodes = [{"id": "IT_X", "project": {"id": "PVT_OTHER"}, "fieldValues": self._fv()}]
        with _StubProjectSync(issue_state="OPEN", issue_nodes=nodes,
                              comments_by_issue={5: self._status()}) as stub:
            task.cmd_project_sync(_PSArgs(issue=5))
        self.assertEqual(stub.mutations, [])
        self.assertEqual(stub.clears, [])

    def test_fast_path_dry_run_writes_nothing(self):
        nodes = [{"id": "IT_5", "project": {"id": "PVT_1"}, "fieldValues": self._fv()}]
        with _StubProjectSync(issue_state="OPEN", issue_nodes=nodes,
                              comments_by_issue={5: self._status()}) as stub:
            task.cmd_project_sync(_PSArgs(issue=5, dry_run=True))
        self.assertEqual(stub.mutations, [])
        self.assertEqual(stub.clears, [])

    def test_dry_run_clear_issues_no_mutation(self):
        nodes = [{"id": "IT_5", "project": {"id": "PVT_1"},
                  "fieldValues": self._fv(session="old", last=self.STALE)}]
        with _StubProjectSync(issue_state="CLOSED", issue_nodes=nodes) as stub:
            task.cmd_project_sync(_PSArgs(issue=5, dry_run=True))
        self.assertEqual(stub.clears, [])
        self.assertEqual(stub.mutations, [])

    def test_missing_fields_is_a_no_op(self):
        with _StubProjectSync(fields=[{"id": "F_s", "name": "Status", "dataType": "SINGLE_SELECT"}]) as stub:
            task.cmd_project_sync(_PSArgs(issue=5))
        self.assertEqual(stub.mutations, [])
        self.assertEqual(stub.clears, [])

    def _sweep_node(self, number, state, repo="urikanonov/ai-marketplace", fv=None):
        return {"id": f"IT_{number}", "content": {"number": number, "state": state,
                "repository": {"nameWithOwner": repo}}, "fieldValues": fv or self._fv()}

    def test_sweep_sets_open_and_clears_closed(self):
        sweep = [
            self._sweep_node(5, "OPEN"),
            self._sweep_node(6, "CLOSED", fv=self._fv(session="old", last=self.STALE)),
        ]
        with _StubProjectSync(sweep_nodes=sweep, comments_by_issue={5: self._status()}) as stub:
            task.cmd_project_sync(_PSArgs(issue=None))
        self.assertTrue(all(m["itemId"] == "IT_5" for m in stub.mutations))
        self.assertEqual(len(stub.mutations), 2)   # #5 set
        self.assertTrue(all(c["itemId"] == "IT_6" for c in stub.clears))
        self.assertEqual(len(stub.clears), 2)      # #6 cleared

    def test_sweep_ignores_other_repo_items(self):
        sweep = [self._sweep_node(5, "CLOSED", repo="someone/else",
                                  fv=self._fv(session="x", last=self.STALE))]
        with _StubProjectSync(sweep_nodes=sweep) as stub:
            task.cmd_project_sync(_PSArgs(issue=None))
        self.assertEqual(stub.clears, [])   # not our repo; never touched
        self.assertEqual(stub.mutations, [])

    def test_sweep_skips_draft_and_non_issue_nodes(self):
        sweep = [
            {"id": "IT_draft", "content": None, "fieldValues": self._fv()},   # a draft card
            {"id": "IT_pr", "content": {}, "fieldValues": self._fv()},        # non-issue (no number)
            None,                                                             # a null node
            self._sweep_node(5, "OPEN"),
        ]
        with _StubProjectSync(sweep_nodes=sweep, comments_by_issue={5: self._status()}) as stub:
            task.cmd_project_sync(_PSArgs(issue=None))
        # Only the real issue #5 is touched; drafts/PRs/nulls neither crash nor mutate.
        self.assertTrue(all(m["itemId"] == "IT_5" for m in stub.mutations))
        self.assertEqual(len(stub.mutations), 2)
        self.assertEqual(stub.clears, [])

    def test_sweep_uses_newest_duplicate_status_comment(self):
        # An older survivor (stale) plus a newer duplicate (fresh): the sweep must SET from the
        # newest, not clear based on the stale survivor.
        old = {"id": 1, "body": task.status_body("issue-5-foo", self.STALE, "old-sess"),
               "assoc": "OWNER"}
        new = {"id": 2, "body": task.status_body("issue-5-foo", self.FRESH, "new-sess"),
               "assoc": "OWNER"}
        with _StubProjectSync(sweep_nodes=[self._sweep_node(5, "OPEN")],
                              comments_by_issue={5: [old, new]}) as stub:
            task.cmd_project_sync(_PSArgs(issue=None))
        self.assertEqual(stub.clears, [])
        self.assertEqual({m["value"] for m in stub.mutations}, {"new-sess", self.FRESH})


class HeartbeatProjectSyncRoutingTests(unittest.TestCase):
    """cmd_heartbeat --project-sync must invoke the best-effort sync after a one-shot beat."""

    def setUp(self):
        self._orig = (task._beat_once, task._project_sync_best_effort)

    def tearDown(self):
        task._beat_once, task._project_sync_best_effort = self._orig

    def test_one_shot_beat_calls_project_sync_when_flag_set(self):
        calls = []
        task._beat_once = lambda number, branch, session="": "2026-07-18T13:58:00Z"
        task._project_sync_best_effort = lambda number: calls.append(number)
        args = task.build_parser().parse_args(["heartbeat", "5", "--branch", "issue-5-foo",
                                               "--project-sync"])
        task.cmd_heartbeat(args)
        self.assertEqual(calls, [5])

    def test_one_shot_beat_skips_project_sync_without_flag(self):
        calls = []
        task._beat_once = lambda number, branch, session="": "2026-07-18T13:58:00Z"
        task._project_sync_best_effort = lambda number: calls.append(number)
        args = task.build_parser().parse_args(["heartbeat", "5", "--branch", "issue-5-foo"])
        task.cmd_heartbeat(args)
        self.assertEqual(calls, [])


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

    def test_session_is_stamped_on_a_body_without_one(self):
        body = task.status_body("issue-7-foo", "2026-07-18T10:00:00Z")
        with _StubComments(self._trusted(body)) as stub:
            task._beat_once(7, None, "sess-abc")
        self.assertEqual(len(stub.edited), 1)
        self.assertEqual(task.parse_session(stub.edited[0][1]), "sess-abc")

    def test_session_is_re_stamped_over_a_different_one(self):
        body = task.status_body("issue-7-foo", "2026-07-18T10:00:00Z", "old-sess")
        with _StubComments(self._trusted(body)) as stub:
            task._beat_once(7, None, "new-sess")
        self.assertEqual(task.parse_session(stub.edited[0][1]), "new-sess")

    def test_empty_session_preserves_existing_session_on_beat(self):
        body = task.status_body("issue-7-foo", "2026-07-18T10:00:00Z", "keep-me")
        with _StubComments(self._trusted(body)) as stub:
            task._beat_once(7, None, "")
        # timestamp refreshed, session preserved (no session provided this beat)
        self.assertEqual(task.parse_session(stub.edited[0][1]), "keep-me")

    def test_malformed_recovery_carries_existing_session(self):
        malformed = (task.STATUS_MARKER + "\n- Branch: `issue-7-foo` (note)\n"
                     "- Handling session: `keep-me`\n(no timestamp line)")
        with _StubComments(self._trusted(malformed)) as stub:
            task._beat_once(7, None, "")
        healed = stub.edited[0][1]
        self.assertIn("- Last active (UTC):", healed)
        self.assertEqual(task.parse_session(healed), "keep-me")

    def test_new_post_carries_session(self):
        with _StubComments([]) as stub:
            task._beat_once(7, "issue-7-foo", "sess-abc")
        self.assertEqual(task.parse_session(stub.posted[0][1]), "sess-abc")

    def test_convergence_inherits_newest_duplicate_session(self):
        # Survivor is older (session A); a duplicate carries the newest stamp AND a different session
        # (B). A beat with no session of our own must attribute ownership to the newest heartbeat (B),
        # not keep the survivor's stale A, before pruning the duplicate.
        older = task.status_body("issue-7-foo", "2098-01-01T00:00:00Z", "sess-A")
        newer = task.status_body("issue-7-foo", "2099-01-01T00:00:00Z", "sess-B")
        comments = [{"id": 1, "body": older, "assoc": "OWNER"},
                    {"id": 2, "body": newer, "assoc": "OWNER"}]
        with _StubComments(comments) as stub:
            task._beat_once(7, None, "")
        edited = stub.edited[0][1]
        self.assertIn("2099-01-01T00:00:00Z", edited)          # newest timestamp
        self.assertEqual(task.parse_session(edited), "sess-B")  # newest heartbeat's session
        self.assertEqual(stub.deleted, [2])                     # duplicate pruned after commit

    def test_malformed_stored_session_does_not_crash_the_beat(self):
        # A crafted/legacy comment whose session code span contains a space would raise if fed back
        # into set_session; the beat must sanitize it to '' and simply refresh the timestamp.
        body = (task.STATUS_MARKER + "\n- Branch: `issue-7-foo`\n"
                "- Handling session: `bad session`\n- Last active (UTC): 2026-07-18T10:00:00Z\n")
        with _StubComments(self._trusted(body)) as stub:
            task._beat_once(7, None, "")  # must not raise
        self.assertEqual(len(stub.edited), 1)
        self.assertIn("- Last active (UTC):", stub.edited[0][1])

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
        task._upsert_status = lambda number, branch, stamp=None, session="": self.upserts.append((number, branch, session))
        return self

    def __exit__(self, *exc):
        task._run, task._capture, task._upsert_status = self._orig


def _start_args(number=7, slug="foo", branch=None, name=None, session_id=None):
    return task.build_parser().parse_args(
        ["start", str(number)]
        + (["--slug", slug] if slug is not None else [])
        + (["--branch", branch] if branch else [])
        + (["--name", name] if name else [])
        + (["--session-id", session_id] if session_id else []))


class CmdStartTests(unittest.TestCase):
    def setUp(self):
        # Hermetic: the local dev box sets COPILOT_AGENT_SESSION_ID, which would leak into the
        # forwarded session. Pop it so the default is a known empty string.
        self._env = os.environ.pop("COPILOT_AGENT_SESSION_ID", None)

    def tearDown(self):
        if self._env is not None:
            os.environ["COPILOT_AGENT_SESSION_ID"] = self._env

    def test_success_creates_worktree_and_stamps(self):
        with _StubStartBoundary(claim_rc=0) as stub:
            task.cmd_start(_start_args(7, "Heartbeat work"))
        self.assertTrue(any("worktree" in r for r in stub.runs))
        self.assertEqual(stub.upserts, [(7, "issue-7-heartbeat-work", "")])

    def test_forwards_the_session_id_to_the_stamp(self):
        with _StubStartBoundary(claim_rc=0) as stub:
            task.cmd_start(_start_args(7, "Heartbeat work", session_id="sess-xyz"))
        self.assertEqual(stub.upserts, [(7, "issue-7-heartbeat-work", "sess-xyz")])

    def test_invalid_session_fails_before_any_mutation(self):
        with _StubStartBoundary(claim_rc=0) as stub:
            with self.assertRaises(SystemExit):
                task.cmd_start(_start_args(7, "Heartbeat work", session_id="bad session"))
        # Fail-fast: no worktree/claim runs and no stamp happened.
        self.assertEqual(stub.runs, [])
        self.assertEqual(stub.upserts, [])

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
