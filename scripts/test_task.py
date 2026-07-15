"""Unit tests for scripts/task.py.

Run by the validate CI job via `python -m unittest discover -s scripts -p "test_*.py"`,
so the issue-first task wrapper's body assembly, ASCII guard, argument construction,
and checkbox ticking are covered by a required status check. The `gh` boundary is not
exercised here; only the pure helpers are.
"""
import unittest

import task


class AsciiGuardTests(unittest.TestCase):
    def test_rejects_smart_punctuation(self):
        with self.assertRaises(ValueError):
            task.assert_ascii("uses an em\u2014dash", "description")

    def test_allows_plain_ascii(self):
        task.assert_ascii("plain - ascii ... only", "description")  # must not raise


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

    def test_already_checked_items_are_skipped(self):
        body = "- [x] done\n- [ ] pending\n"
        out = task.tick_checkbox(body, 1)
        self.assertEqual(out, "- [x] done\n- [x] pending")


class ParserTests(unittest.TestCase):
    def test_new_parses_repeatable_ac(self):
        args = task.build_parser().parse_args(
            ["new", "T", "-d", "why", "--ac", "a", "--ac", "b"])
        self.assertEqual(args.ac, ["a", "b"])

    def test_search_all_flag(self):
        args = task.build_parser().parse_args(["search", "topic", "--all"])
        self.assertTrue(args.all)


if __name__ == "__main__":
    unittest.main()
