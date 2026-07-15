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


if __name__ == "__main__":
    unittest.main()
