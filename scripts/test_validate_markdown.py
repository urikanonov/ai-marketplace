#!/usr/bin/env python3
"""Tests for scripts/validate_markdown.py.

Run from the repo root:
    python -m unittest discover -s scripts -p "test_*.py"
"""

import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_MODULE_PATH = Path(__file__).with_name("validate_markdown.py")
_spec = importlib.util.spec_from_file_location("validate_markdown", _MODULE_PATH)
vm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vm)


def codes(findings):
    return sorted(f.code for f in findings)


class TestAiCharacters(unittest.TestCase):
    def test_detects_each_smart_character(self):
        content = "em\u2014dash en\u2013dash ellipsis\u2026 \u201Cq\u201D \u2018s\u2019 nbsp\u00A0x\ufeff"
        found = vm.find_ai_characters(content)
        self.assertTrue(found)
        self.assertTrue(all(f.code == "ai-chars" and f.severity == vm.ERROR for f in found))

    def test_clean_ascii_has_no_findings(self):
        self.assertEqual(vm.find_ai_characters("plain - ascii ... 'ok' \"ok\""), [])

    def test_fix_replaces_with_ascii(self):
        new, count = vm.fix_ai_characters("a\u2014b \u201Cq\u201D \u2018s\u2019 dots\u2026 en\u2013d nbsp\u00A0x\ufeff")
        self.assertGreater(count, 0)
        self.assertEqual(vm.find_ai_characters(new), [])
        self.assertIn("a - b", new)
        self.assertIn("en-d", new)
        self.assertIn("dots...", new)
        self.assertIn('"q"', new)
        self.assertIn("'s'", new)
        self.assertNotIn("\ufeff", new)


class TestLocalPaths(unittest.TestCase):
    def test_flags_windows_and_unix_paths(self):
        found = vm.check_local_paths("See C:\\Projects\\foo and /Users/me/bar for details.")
        self.assertEqual(codes(found), ["local-path", "local-path"])

    def test_ignores_paths_inside_inline_code(self):
        self.assertEqual(vm.check_local_paths("Use `C:\\Projects\\foo` as an example."), [])

    def test_ignores_paths_inside_fenced_code(self):
        content = "text\n```\nC:\\Projects\\foo\n```\nmore"
        self.assertEqual(vm.check_local_paths(content), [])


class TestLinks(unittest.TestCase):
    def test_broken_link_flagged_valid_link_not(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "target.md").write_text("# Title\n", encoding="utf-8")
            src = root / "src.md"
            content = "[good](target.md) and [bad](missing.md)"
            src.write_text(content, encoding="utf-8")
            found = vm.check_links(src, content, root)
            self.assertEqual(codes(found), ["broken-link"])
            self.assertIn("missing.md", found[0].message)

    def test_external_links_ignored(self):
        content = "[a](https://example.com) [b](mailto:x@y.z) [c](tel:123)"
        with TemporaryDirectory() as d:
            root = Path(d)
            src = root / "s.md"
            src.write_text(content, encoding="utf-8")
            self.assertEqual(vm.check_links(src, content, root), [])

    def test_same_file_broken_anchor(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            src = root / "s.md"
            content = "# Real Heading\n\n[jump](#real-heading) [oops](#no-such)\n"
            src.write_text(content, encoding="utf-8")
            found = vm.check_links(src, content, root)
            self.assertEqual(codes(found), ["broken-anchor"])
            self.assertIn("#no-such", found[0].message)

    def test_cross_file_anchor(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "other.md").write_text("# Section One\n", encoding="utf-8")
            src = root / "s.md"
            content = "[ok](other.md#section-one) [bad](other.md#ghost)\n"
            src.write_text(content, encoding="utf-8")
            found = vm.check_links(src, content, root)
            self.assertEqual(codes(found), ["broken-anchor"])
            self.assertIn("ghost", found[0].message)

    def test_query_string_is_stripped_for_path_and_anchor_checks(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "other.md").write_text("# Section One\n", encoding="utf-8")
            src = root / "s.md"
            content = (
                "[ok](other.md?raw=1#section-one) "
                "[bad-anchor](other.md?raw=1#ghost) "
                "[missing](missing.md?raw=1)\n"
            )
            src.write_text(content, encoding="utf-8")
            found = vm.check_links(src, content, root)
            self.assertEqual(codes(found), ["broken-anchor", "broken-link"])

    def test_no_links_skipped_via_validate_content(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            src = root / "s.md"
            content = "[bad](missing.md)\n"
            src.write_text(content, encoding="utf-8")
            found = vm.validate_content(src, content, root, no_links=True)
            self.assertNotIn("broken-link", codes(found))


class TestPathCase(unittest.TestCase):
    def test_case_mismatch_detected_cross_platform(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "Target.md").write_text("x", encoding="utf-8")
            fix = vm._check_path_case(root / "target.md", root)
            self.assertEqual(fix, "Target.md")

    def test_exact_case_returns_none(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "Target.md").write_text("x", encoding="utf-8")
            self.assertIsNone(vm._check_path_case(root / "Target.md", root))


class TestPackagedSkillSkip(unittest.TestCase):
    """A .md beside a skill-resources.zip is skipped (its relative links resolve into the zip after
    first-run extraction); a .md without that sibling is still collected."""

    def test_skips_md_beside_skill_resources_zip(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            shipped = root / "pkg" / "skills" / "commentable-html"
            shipped.mkdir(parents=True)
            (shipped / "SKILL.md").write_text("[x](references/x.md)\n", encoding="utf-8")
            (shipped / "skill-resources.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
            stage = root / "dev" / "skill"
            stage.mkdir(parents=True)
            (stage / "SKILL.md").write_text("[x](references/x.md)\n", encoding="utf-8")
            found = {p.relative_to(root).as_posix() for p in vm.find_markdown_files(root)}
            self.assertNotIn("pkg/skills/commentable-html/SKILL.md", found)
            self.assertIn("dev/skill/SKILL.md", found)


class TestTables(unittest.TestCase):
    def test_unbalanced_row_flagged(self):
        content = "| a | b |\n| - | - |\n| 1 | 2 | 3 |\n"
        found = vm.check_unbalanced_tables(content)
        self.assertEqual(codes(found), ["table"])

    def test_balanced_table_clean(self):
        content = "| a | b |\n| - | - |\n| 1 | 2 |\n"
        self.assertEqual(vm.check_unbalanced_tables(content), [])


class TestOtherChecks(unittest.TestCase):
    def test_placeholder_markers(self):
        found = vm.check_placeholders("Intro\n\nTODO finish this\n")
        self.assertEqual(codes(found), ["placeholder"])

    def test_placeholder_ignored_in_code(self):
        self.assertEqual(vm.check_placeholders("Use `TODO` as a keyword."), [])

    def test_blank_after_heading(self):
        self.assertEqual(codes(vm.check_blank_after_heading("# Title\ntext\n")), ["blank-heading"])
        self.assertEqual(vm.check_blank_after_heading("# Title\n\ntext\n"), [])
        # A heading immediately followed by an HTML comment is a structural/region marker
        # (e.g. "## Section\n<!-- SECTION:...:BEGIN -->"), not prose - it must not be flagged.
        self.assertEqual(vm.check_blank_after_heading("## Acceptance Criteria\n<!-- AC:BEGIN -->\n"), [])
        self.assertEqual(vm.check_blank_after_heading("## Description\n\n<!-- SECTION:DESCRIPTION:BEGIN -->\n"), [])

    def test_double_bracket(self):
        self.assertEqual(codes(vm.check_double_brackets("see [[Page]] here")), ["double-bracket"])


class TestStyleChecks(unittest.TestCase):
    def test_filler_intro(self):
        self.assertEqual(codes(vm.check_filler_intros("This guide describes the setup.")), ["style"])

    def test_promotional_word(self):
        self.assertEqual(codes(vm.check_promotional_words("A powerful and robust tool.")), ["style", "style"])

    def test_line_number_reference(self):
        self.assertEqual(codes(vm.check_line_number_references("See lines 10-20 for detail.")), ["style"])

    def test_style_off_by_default_in_validate_content(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            src = root / "s.md"
            content = "# T\n\nThis guide describes a powerful tool.\n"
            src.write_text(content, encoding="utf-8")
            self.assertNotIn("style", codes(vm.validate_content(src, content, root)))
            self.assertIn("style", codes(vm.validate_content(src, content, root, style=True)))


class TestDiscovery(unittest.TestCase):
    def test_excludes_build_and_vcs_dirs(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "keep.md").write_text("x", encoding="utf-8")
            for sub in ("node_modules", "__pycache__", "dist"):
                (root / sub).mkdir()
                (root / sub / "skip.md").write_text("x", encoding="utf-8")
            files = [p.name for p in vm.find_markdown_files(root)]
            self.assertEqual(files, ["keep.md"])

    def test_excludes_nested_worktrees_dir(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "keep.md").write_text("x", encoding="utf-8")
            wt = root / ".worktrees" / "feature"
            wt.mkdir(parents=True)
            (wt / "other.md").write_text("x", encoding="utf-8")
            files = [p.name for p in vm.find_markdown_files(root)]
            self.assertEqual(files, ["keep.md"])

    def test_excludes_scratch_dirs(self):
        # .plans/ and tmp/ are gitignored local scratch: their .md files must not be scanned.
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "keep.md").write_text("x", encoding="utf-8")
            for sub in (".plans", "tmp"):
                (root / sub).mkdir()
                (root / sub / "scratch.md").write_text("x", encoding="utf-8")
            files = [p.name for p in vm.find_markdown_files(root)]
            self.assertEqual(files, ["keep.md"])

    def test_scans_when_root_is_under_an_excluded_name(self):
        # Running from inside a .worktrees/<name> checkout: the excluded name is an
        # ancestor of root, so it must not exclude the tree's own files.
        with TemporaryDirectory() as d:
            root = Path(d) / ".worktrees" / "feature"
            root.mkdir(parents=True)
            (root / "keep.md").write_text("x", encoding="utf-8")
            files = [p.name for p in vm.find_markdown_files(root)]
            self.assertEqual(files, ["keep.md"])


class TestMainExitCodes(unittest.TestCase):
    def _run_main(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = vm.main(argv)
        return rc, buf.getvalue()

    def test_error_fails_run(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "bad.md").write_text("has em\u2014dash\n", encoding="utf-8")
            rc, out = self._run_main([str(root)])
            self.assertEqual(rc, 1)
            self.assertIn("error(s)", out)

    def test_fix_repairs_and_passes(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            f = root / "bad.md"
            f.write_text("has em\u2014dash\n", encoding="utf-8")
            rc, _ = self._run_main([str(root), "--fix"])
            self.assertEqual(rc, 0)
            self.assertNotIn("\u2014", f.read_text(encoding="utf-8"))

    def test_fix_forces_lf_newlines(self):
        path = Path("example.md")
        with mock.patch.object(Path, "write_text") as write_text:
            vm.write_text_lf(path, "first\nsecond\n")
        write_text.assert_called_once_with("first\nsecond\n", encoding="utf-8", newline="\n")

    def test_warning_only_passes_unless_strict(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "warn.md").write_text("# T\ntext without blank line\n", encoding="utf-8")
            rc_default, _ = self._run_main([str(root)])
            self.assertEqual(rc_default, 0)
            rc_strict, _ = self._run_main([str(root), "--strict"])
            self.assertEqual(rc_strict, 1)

    def test_clean_file_passes(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "ok.md").write_text("# Title\n\nPlain ASCII body.\n", encoding="utf-8")
            rc, _ = self._run_main([str(root)])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
