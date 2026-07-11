#!/usr/bin/env python3
"""Tests for scripts/check_changelog_sync.py."""

import importlib.util
import os
import unittest

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


if __name__ == "__main__":
    unittest.main()
