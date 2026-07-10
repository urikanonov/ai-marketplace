#!/usr/bin/env python3
"""Tests for scripts/check_version_bump.py."""

import importlib.util
import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

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
        self.assertGreater(cvb.semver("2.0.0"), cvb.semver("1.5.9"))

    def test_invalid(self):
        for bad in ("1.0", "1.0.0-rc1", "x.y.z", ""):
            with self.assertRaises(ValueError):
                cvb.semver(bad)


class TestNormSource(unittest.TestCase):
    def test_strips_leading_dot_slash_only(self):
        self.assertEqual(cvb._norm_source("./plugins/x/pkg"), "plugins/x/pkg")
        self.assertEqual(cvb._norm_source("./.github/x"), ".github/x")
        self.assertEqual(cvb._norm_source("plugins/x/"), "plugins/x")
        self.assertEqual(cvb._norm_source("./"), "")


class TestSourceTouched(unittest.TestCase):
    def test_prefix_match_only(self):
        files = ["plugins/commentable-html/pkg/skills/x/SKILL.md", "README.md"]
        self.assertTrue(cvb.source_touched("./plugins/commentable-html/pkg", files))
        self.assertFalse(cvb.source_touched("./plugins/other/pkg", files))

    def test_dev_only_change_does_not_touch_pkg_source(self):
        files = ["plugins/commentable-html/dev/tests/x.spec.js"]
        self.assertFalse(cvb.source_touched("./plugins/commentable-html/pkg", files))

    def test_changelog_is_exempt(self):
        files = ["plugins/auto-updater/CHANGELOG.md"]
        self.assertFalse(cvb.source_touched("./plugins/auto-updater", files))

    def test_changelog_plus_real_change_still_touches(self):
        files = ["plugins/auto-updater/CHANGELOG.md", "plugins/auto-updater/hooks/x.ps1"]
        self.assertTrue(cvb.source_touched("./plugins/auto-updater", files))


class TestEvaluate(unittest.TestCase):
    def _cmt(self, ver):
        return entry("commentable-html", "./plugins/commentable-html/pkg", ver)

    def test_changed_without_bump_fails(self):
        files = ["plugins/commentable-html/pkg/plugin.json"]
        self.assertTrue(cvb.evaluate(mf(self._cmt("1.0.0")), mf(self._cmt("1.0.0")), files))

    def test_changed_with_bump_passes(self):
        files = ["plugins/commentable-html/pkg/skills/x/SKILL.md"]
        self.assertEqual(cvb.evaluate(mf(self._cmt("1.0.1")), mf(self._cmt("1.0.0")), files), [])

    def test_unchanged_plugin_skipped(self):
        files = ["README.md", "plugins/commentable-html/dev/tests/x.spec.js"]
        self.assertEqual(cvb.evaluate(mf(self._cmt("1.0.0")), mf(self._cmt("1.0.0")), files), [])

    def test_changelog_only_change_skipped(self):
        files = ["plugins/commentable-html/pkg/CHANGELOG.md"]
        self.assertEqual(cvb.evaluate(mf(self._cmt("1.0.0")), mf(self._cmt("1.0.0")), files), [])

    def test_new_plugin_skipped(self):
        files = ["plugins/new-plugin/plugin.json"]
        self.assertEqual(cvb.evaluate(mf(entry("new-plugin", "./plugins/new-plugin", "1.0.0")), mf(), files), [])

    def test_version_decrease_fails(self):
        files = ["plugins/commentable-html/pkg/plugin.json"]
        self.assertTrue(cvb.evaluate(mf(self._cmt("1.0.0")), mf(self._cmt("2.5.0")), files))

    def test_source_path_change_requires_bump(self):
        head = mf(entry("p", "./plugins/p/pkg2", "1.0.0"))
        base = mf(entry("p", "./plugins/p/pkg", "1.0.0"))
        # nothing under either source touched, but the source path itself moved
        self.assertTrue(cvb.evaluate(head, base, ["README.md"]))

    def test_change_under_old_source_counts(self):
        head = mf(entry("p", "./plugins/p/pkg2", "1.0.1"))
        base = mf(entry("p", "./plugins/p/pkg", "1.0.0"))
        # a file under the OLD source path changed; union coverage still evaluates it
        self.assertEqual(cvb.evaluate(head, base, ["plugins/p/pkg/x"]), [])


class TestMain(unittest.TestCase):
    def _run(self, argv, **patches):
        buf_out, buf_err = io.StringIO(), io.StringIO()
        cm = mock.patch.multiple(cvb, **patches) if patches else mock.patch.object(cvb, "MANIFEST", cvb.MANIFEST)
        with cm, redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = cvb.main(argv)
        return rc, buf_out.getvalue() + buf_err.getvalue()

    def test_zero_sha_base_skips(self):
        rc, out = self._run(["--base", cvb._ZERO_SHA, "--head", "HEAD"])
        self.assertEqual(rc, 0)
        self.assertIn("skipping", out)

    def test_empty_base_skips(self):
        rc, out = self._run(["--base", "", "--head", "HEAD"])
        self.assertEqual(rc, 0)

    def test_invalid_base_fails_closed(self):
        with self.assertRaises(SystemExit):
            self._run(["--base", "deadbeef", "--head", "HEAD"], ref_exists=lambda r: False)

    def test_absent_base_manifest_skips(self):
        rc, out = self._run(
            ["--base", "b", "--head", "h"],
            ref_exists=lambda r: True,
            manifest_at=lambda ref: None if ref == "b" else mf(),
        )
        self.assertEqual(rc, 0)
        self.assertIn("skipping", out)

    def test_missing_head_manifest_fails(self):
        with self.assertRaises(SystemExit):
            self._run(["--base", "b", "--head", "h"],
                      ref_exists=lambda r: True, manifest_at=lambda ref: None)

    def test_env_defaults_used(self):
        cmt_head = mf(entry("commentable-html", "./plugins/commentable-html/pkg", "1.0.0"))
        cmt_base = mf(entry("commentable-html", "./plugins/commentable-html/pkg", "1.0.0"))
        with mock.patch.dict(os.environ, {"BUMP_BASE_REF": "b", "BUMP_HEAD_REF": "h"}):
            rc, out = self._run(
                [],
                ref_exists=lambda r: True,
                manifest_at=lambda ref: cmt_base if ref == "b" else cmt_head,
                merge_base=lambda a, b: a,
                changed_files=lambda a, b: ["plugins/commentable-html/pkg/plugin.json"],
            )
        self.assertEqual(rc, 1)  # touched pkg, no bump -> fail

    def test_full_pass_path(self):
        head = mf(entry("commentable-html", "./plugins/commentable-html/pkg", "1.0.1"))
        base = mf(entry("commentable-html", "./plugins/commentable-html/pkg", "1.0.0"))
        rc, out = self._run(
            ["--base", "b", "--head", "h"],
            ref_exists=lambda r: True,
            manifest_at=lambda ref: base if ref == "b" else head,
            merge_base=lambda a, b: a,
            changed_files=lambda a, b: ["plugins/commentable-html/pkg/plugin.json"],
        )
        self.assertEqual(rc, 0)
        self.assertIn("OK", out)


if __name__ == "__main__":
    unittest.main()
