#!/usr/bin/env python3
"""Tests for scripts/check_version_bump.py (pure evaluate() + helpers)."""

import importlib.util
import os
import unittest

_MODULE_PATH = os.path.join(os.path.dirname(__file__), "check_version_bump.py")
_spec = importlib.util.spec_from_file_location("check_version_bump", _MODULE_PATH)
cvb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cvb)


def mf(*entries):
    return {"plugins": list(entries)}


def entry(name, source, version):
    return {"name": name, "source": source, "version": version}


class TestSemver(unittest.TestCase):
    def test_order(self):
        self.assertLess(cvb.semver("1.0.0"), cvb.semver("1.0.1"))
        self.assertLess(cvb.semver("1.9.0"), cvb.semver("2.0.0"))
        self.assertGreater(cvb.semver("2.0.0"), cvb.semver("1.5.9"))

    def test_invalid(self):
        with self.assertRaises(ValueError):
            cvb.semver("1.0")


class TestSourceTouched(unittest.TestCase):
    def test_matches_prefix_only(self):
        files = ["plugins/commentable-html/pkg/skills/x/SKILL.md", "README.md"]
        self.assertTrue(cvb.source_touched("./plugins/commentable-html/pkg", files))
        self.assertFalse(cvb.source_touched("./plugins/other/pkg", files))

    def test_dev_only_change_does_not_touch_pkg_source(self):
        files = ["plugins/commentable-html/dev/tests/x.spec.js"]
        self.assertFalse(cvb.source_touched("./plugins/commentable-html/pkg", files))


class TestEvaluate(unittest.TestCase):
    def test_changed_without_bump_fails(self):
        head = mf(entry("commentable-html", "./plugins/commentable-html/pkg", "1.0.0"))
        base = mf(entry("commentable-html", "./plugins/commentable-html/pkg", "1.0.0"))
        files = ["plugins/commentable-html/pkg/plugin.json"]
        self.assertTrue(cvb.evaluate(head, base, files))

    def test_changed_with_bump_passes(self):
        head = mf(entry("commentable-html", "./plugins/commentable-html/pkg", "1.0.1"))
        base = mf(entry("commentable-html", "./plugins/commentable-html/pkg", "1.0.0"))
        files = ["plugins/commentable-html/pkg/skills/x/SKILL.md"]
        self.assertEqual(cvb.evaluate(head, base, files), [])

    def test_unchanged_plugin_skipped(self):
        head = mf(entry("commentable-html", "./plugins/commentable-html/pkg", "1.0.0"))
        base = mf(entry("commentable-html", "./plugins/commentable-html/pkg", "1.0.0"))
        files = ["README.md", "plugins/commentable-html/dev/tests/x.spec.js"]
        self.assertEqual(cvb.evaluate(head, base, files), [])

    def test_new_plugin_skipped(self):
        head = mf(entry("new-plugin", "./plugins/new-plugin", "1.0.0"))
        base = mf()
        files = ["plugins/new-plugin/plugin.json"]
        self.assertEqual(cvb.evaluate(head, base, files), [])

    def test_version_decrease_fails(self):
        head = mf(entry("commentable-html", "./plugins/commentable-html/pkg", "1.0.0"))
        base = mf(entry("commentable-html", "./plugins/commentable-html/pkg", "2.5.0"))
        files = ["plugins/commentable-html/pkg/plugin.json"]
        self.assertTrue(cvb.evaluate(head, base, files))


if __name__ == "__main__":
    unittest.main()
