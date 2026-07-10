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
        self.assertFalse(cvb.source_touched("./plugins/commentable-html/pkg",
                                            ["plugins/commentable-html/dev/tests/x.spec.js"]))

    def test_top_level_changelog_is_exempt(self):
        self.assertFalse(cvb.source_touched("./plugins/p", ["plugins/p/CHANGELOG.md"]))

    def test_nested_changelog_is_not_exempt(self):
        # A CHANGELOG.md deeper in the shipped tree is shipped content, not the release changelog.
        self.assertTrue(cvb.source_touched("./plugins/p", ["plugins/p/docs/CHANGELOG.md"]))

    def test_changelog_plus_real_change_still_touches(self):
        self.assertTrue(cvb.source_touched("./plugins/p", ["plugins/p/CHANGELOG.md", "plugins/p/x.ps1"]))


class TestEvaluate(unittest.TestCase):
    def _cmt(self, ver):
        return entry("commentable-html", "./plugins/commentable-html/pkg", ver)

    def test_changed_without_bump_fails(self):
        self.assertTrue(cvb.evaluate(mf(self._cmt("1.0.0")), mf(self._cmt("1.0.0")),
                                     ["plugins/commentable-html/pkg/plugin.json"]))

    def test_changed_with_bump_passes(self):
        self.assertEqual(cvb.evaluate(mf(self._cmt("1.0.1")), mf(self._cmt("1.0.0")),
                                      ["plugins/commentable-html/pkg/skills/x/SKILL.md"]), [])

    def test_unchanged_plugin_skipped(self):
        self.assertEqual(cvb.evaluate(mf(self._cmt("1.0.0")), mf(self._cmt("1.0.0")),
                                      ["README.md", "plugins/commentable-html/dev/tests/x.spec.js"]), [])

    def test_top_level_changelog_only_change_skipped(self):
        self.assertEqual(cvb.evaluate(mf(entry("p", "./plugins/p", "1.0.0")),
                                      mf(entry("p", "./plugins/p", "1.0.0")),
                                      ["plugins/p/CHANGELOG.md"]), [])

    def test_new_plugin_skipped(self):
        self.assertEqual(cvb.evaluate(mf(entry("new", "./plugins/new", "1.0.0")), mf(),
                                      ["plugins/new/plugin.json"]), [])

    def test_version_decrease_fails(self):
        self.assertTrue(cvb.evaluate(mf(self._cmt("1.0.0")), mf(self._cmt("2.5.0")),
                                     ["plugins/commentable-html/pkg/plugin.json"]))

    def test_source_path_change_requires_bump_even_with_no_touched_files(self):
        head = mf(entry("p", "./plugins/p/pkg2", "1.0.0"))
        base = mf(entry("p", "./plugins/p/pkg", "1.0.0"))
        self.assertTrue(cvb.evaluate(head, base, ["README.md"]))

    def test_renamed_out_of_source_counts(self):
        # With --no-renames, a file moved OUT of the source appears as a delete under the source.
        self.assertTrue(cvb.evaluate(mf(self._cmt("1.0.0")), mf(self._cmt("1.0.0")),
                                     ["plugins/commentable-html/pkg/old.js", "elsewhere/old.js"]))


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
        self.assertEqual(self._run(["--base", "", "--head", "HEAD"])[0], 0)

    def test_invalid_base_fails_closed(self):
        with self.assertRaises(SystemExit):
            self._run(["--base", "deadbeef", "--head", "HEAD"], ref_exists=lambda r: False)

    def test_absent_base_manifest_skips(self):
        rc, out = self._run(["--base", "b", "--head", "h"],
                            ref_exists=lambda r: True,
                            manifest_at=lambda ref: None if ref == "b" else mf())
        self.assertEqual(rc, 0)
        self.assertIn("skipping", out)

    def test_missing_head_manifest_fails(self):
        with self.assertRaises(SystemExit):
            self._run(["--base", "b", "--head", "h"], ref_exists=lambda r: True,
                      manifest_at=lambda ref: None)

    def test_env_defaults_used_with_strict_refs(self):
        seen = {}

        def strict_manifest(ref):
            if ref not in ("envbase", "envhead"):
                raise AssertionError("unexpected ref %r (env defaults not honored)" % ref)
            return mf(entry("commentable-html", "./plugins/commentable-html/pkg",
                            "1.0.0" if ref == "envbase" else "1.0.0"))

        def rec_changed(a, b):
            seen["from"], seen["to"] = a, b
            return ["plugins/commentable-html/pkg/plugin.json"]

        with mock.patch.dict(os.environ, {"BUMP_BASE_REF": "envbase", "BUMP_HEAD_REF": "envhead",
                                          "BUMP_EVENT": "pull_request"}):
            rc, _ = self._run([], ref_exists=lambda r: True, manifest_at=strict_manifest,
                              merge_base=lambda a, b: "mb", changed_files=rec_changed)
        self.assertEqual(rc, 1)             # touched pkg, no bump -> fail
        self.assertEqual(seen["from"], "mb")  # PR event used merge base
        self.assertEqual(seen["to"], "envhead")

    def test_push_event_uses_two_dot_not_merge_base(self):
        seen = {}

        def rec_changed(a, b):
            seen["from"] = a
            return []

        rc, _ = self._run(["--base", "before", "--head", "after", "--event", "push"],
                          ref_exists=lambda r: True, manifest_at=lambda ref: mf(),
                          merge_base=lambda a, b: (_ for _ in ()).throw(AssertionError("merge_base used on push")),
                          changed_files=rec_changed)
        self.assertEqual(rc, 0)
        self.assertEqual(seen["from"], "before")  # push diffs base..head directly

    def test_full_pass_path(self):
        head = mf(entry("commentable-html", "./plugins/commentable-html/pkg", "1.0.1"))
        base = mf(entry("commentable-html", "./plugins/commentable-html/pkg", "1.0.0"))
        rc, out = self._run(["--base", "b", "--head", "h", "--event", "pull_request"],
                            ref_exists=lambda r: True,
                            manifest_at=lambda ref: base if ref == "b" else head,
                            merge_base=lambda a, b: a,
                            changed_files=lambda a, b: ["plugins/commentable-html/pkg/plugin.json"])
        self.assertEqual(rc, 0)
        self.assertIn("OK", out)


if __name__ == "__main__":
    unittest.main()
