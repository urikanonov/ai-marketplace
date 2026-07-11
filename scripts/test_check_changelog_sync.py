#!/usr/bin/env python3
"""Tests for scripts/check_changelog_sync.py."""

import importlib.util
import os
import unittest
import unittest.mock

_MODULE_PATH = os.path.join(os.path.dirname(__file__), "check_changelog_sync.py")
_spec = importlib.util.spec_from_file_location("check_changelog_sync", _MODULE_PATH)
ccs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccs)


BASE_CHANGELOG = """# Changelog

## [Unreleased]

### Changed

- Draft item.

## [1.0.0] - 2026-01-01

### Added

- First release.
"""


class TestCurrentVersion(unittest.TestCase):
    def test_version_present(self):
        self.assertEqual(
            ccs.check_current_version("sample", "plugins/sample/CHANGELOG.md", BASE_CHANGELOG, "1.0.0", "manifest"),
            [],
        )

    def test_version_missing(self):
        failures = ccs.check_current_version(
            "sample", "plugins/sample/CHANGELOG.md", BASE_CHANGELOG, "1.0.1", "manifest"
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("## [1.0.1]", failures[0])


class TestReleasedHistory(unittest.TestCase):
    def _changes(self, base, head):
        return [(change.version, change.kind) for change in ccs.compare_released_history(base, head)]

    def test_historic_section_unchanged(self):
        self.assertEqual(self._changes(BASE_CHANGELOG, BASE_CHANGELOG), [])

    def test_historic_section_modified(self):
        head = BASE_CHANGELOG.replace("- First release.", "- First release with edits.")
        self.assertEqual(self._changes(BASE_CHANGELOG, head), [("1.0.0", "modified")])

    def test_historic_section_removed(self):
        head = """# Changelog

## [Unreleased]

### Changed

- Draft item.
"""
        self.assertEqual(self._changes(BASE_CHANGELOG, head), [("1.0.0", "removed")])

    def test_new_released_section_added(self):
        head = BASE_CHANGELOG.replace(
            "## [1.0.0]",
            "## [1.0.1] - 2026-01-02\n\n### Changed\n\n- New release.\n\n## [1.0.0]",
        )
        self.assertEqual(self._changes(BASE_CHANGELOG, head), [])

    def test_unreleased_section_edited(self):
        head = BASE_CHANGELOG.replace("- Draft item.", "- Updated draft item.")
        self.assertEqual(self._changes(BASE_CHANGELOG, head), [])

    def test_crlf_is_normalized(self):
        self.assertEqual(self._changes(BASE_CHANGELOG.replace("\n", "\r\n"), BASE_CHANGELOG), [])


class DuplicateHeadingTests(unittest.TestCase):
    def test_detects_duplicate_released_heading(self):
        content = "# Changelog\n\n## [1.0.0] - a\n\n- x\n\n## [1.0.0] - b\n\n- y\n"
        self.assertEqual(ccs.duplicate_released_headings(content), ["1.0.0"])

    def test_no_duplicate(self):
        content = "# Changelog\n\n## [1.1.0]\n\n- x\n\n## [1.0.0]\n\n- y\n"
        self.assertEqual(ccs.duplicate_released_headings(content), [])


class GitShowTests(unittest.TestCase):
    class _Result(object):
        def __init__(self, returncode, stdout=b"", stderr=b""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def test_missing_path_is_skip_note(self):
        result = self._Result(128, stderr=b"fatal: path 'x' does not exist in 'origin/main'")
        with unittest.mock.patch.object(ccs.subprocess, "run", return_value=result):
            content, error, note = ccs.git_show_text(ccs.ROOT, "origin/main", "x")
        self.assertIsNone(content)
        self.assertIsNone(error)
        self.assertIn("new at", note)

    def test_bad_ref_is_hard_error(self):
        result = self._Result(128, stderr=b"fatal: invalid object name 'origin/main'")
        with unittest.mock.patch.object(ccs.subprocess, "run", return_value=result):
            content, error, note = ccs.git_show_text(ccs.ROOT, "origin/main", "x")
        self.assertIsNone(content)
        self.assertIsNotNone(error)
        self.assertIsNone(note)

    def test_success_returns_content(self):
        result = self._Result(0, stdout=b"hello")
        with unittest.mock.patch.object(ccs.subprocess, "run", return_value=result):
            content, error, note = ccs.git_show_text(ccs.ROOT, "origin/main", "x")
        self.assertEqual(content, "hello")
        self.assertIsNone(error)


class CurrentVersionForTests(unittest.TestCase):
    def _root(self):
        import tempfile
        from pathlib import Path
        return Path(tempfile.mkdtemp())

    def test_pkg_layout_plugin_json(self):
        root = self._root()
        pkg = root / "plugins" / "p" / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "plugin.json").write_text('{"version": "2.3.4"}', encoding="utf-8")
        version, source = ccs.current_version_for(root, "./plugins/p/pkg", {"name": "p", "version": "9.9.9"})
        self.assertEqual(version, "2.3.4")
        self.assertIn("plugin.json", source)

    def test_plugin_dir_layout_plugin_json(self):
        root = self._root()
        pdir = root / "plugins" / "p"
        pdir.mkdir(parents=True)
        (pdir / "plugin.json").write_text('{"version": "1.2.0"}', encoding="utf-8")
        version, source = ccs.current_version_for(root, "./plugins/p", {"name": "p", "version": "9.9.9"})
        self.assertEqual(version, "1.2.0")
        self.assertIn("plugin.json", source)

    def test_skill_source_falls_back_to_manifest_entry(self):
        root = self._root()
        (root / "plugins" / "p" / "skills" / "s").mkdir(parents=True)
        version, source = ccs.current_version_for(
            root, "./plugins/p/skills/s", {"name": "p", "version": "4.5.6"})
        self.assertEqual(version, "4.5.6")
        self.assertIn("marketplace entry", source)


class ResolveBaseRefTests(unittest.TestCase):
    def test_uses_merge_base_when_it_differs_from_head(self):
        with unittest.mock.patch.object(ccs, "_rev_parse", side_effect=lambda r, ref: "head" if ref == "HEAD" else None), \
             unittest.mock.patch.object(ccs, "_git_out", return_value="mergebase"):
            self.assertEqual(ccs.resolve_base_ref(ccs.ROOT, "origin/main"), "mergebase")

    def test_falls_back_to_parent_when_merge_base_is_head(self):
        def rp(root, ref):
            return {"HEAD": "same", "HEAD^": "parent"}.get(ref)
        with unittest.mock.patch.object(ccs, "_rev_parse", side_effect=rp), \
             unittest.mock.patch.object(ccs, "_git_out", return_value="same"):
            self.assertEqual(ccs.resolve_base_ref(ccs.ROOT, "origin/main"), "HEAD^")

    def test_falls_back_to_base_when_history_unavailable(self):
        with unittest.mock.patch.object(ccs, "_rev_parse", return_value=None), \
             unittest.mock.patch.object(ccs, "_git_out", return_value=None):
            self.assertEqual(ccs.resolve_base_ref(ccs.ROOT, "origin/main"), "origin/main")

    def test_merge_base_failure_does_not_downgrade_to_parent(self):
        # merge-base fails (None) but HEAD^ exists (shallow checkout): must NOT use HEAD^
        # (that would only check the last commit); fall back to base_ref for a hard fail.
        with unittest.mock.patch.object(ccs, "_rev_parse", side_effect=lambda r, ref: "parent" if ref == "HEAD^" else "head"), \
             unittest.mock.patch.object(ccs, "_git_out", return_value=None):
            self.assertEqual(ccs.resolve_base_ref(ccs.ROOT, "origin/main"), "origin/main")


if __name__ == "__main__":
    unittest.main()
