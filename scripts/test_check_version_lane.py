#!/usr/bin/env python3
"""Tests for scripts/check_version_lane.py."""

import importlib.util
import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout

_MODULE_PATH = os.path.join(os.path.dirname(__file__), "check_version_lane.py")
_spec = importlib.util.spec_from_file_location("check_version_lane", _MODULE_PATH)
cvl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cvl)


def other(number, version):
    return {"number": number, "version": version}


class TestSemver(unittest.TestCase):
    def test_order(self):
        self.assertLess(cvl.semver("1.6.0"), cvl.semver("1.6.1"))
        self.assertLess(cvl.semver("1.9.0"), cvl.semver("1.10.0"))
        self.assertEqual(cvl.semver("1.6.0"), cvl.semver("1.6.0"))

    def test_invalid_raises(self):
        for bad in ("1.6", "x.y.z", "", "1.6.0.0"):
            with self.assertRaises(ValueError):
                cvl.semver(bad)


class TestEvaluate(unittest.TestCase):
    def test_no_bump_is_skipped(self):
        # Current PR did not bump past base, so it is not claiming a lane: never a conflict,
        # even if another open PR sits at a higher version.
        conflicts = cvl.evaluate("1.6.0", base="1.6.0", others=[other(40, "1.7.0")])
        self.assertEqual(conflicts, [])

    def test_distinct_higher_lane_is_clear(self):
        # Current picks a version strictly greater than every other open PR that bumped: clear.
        conflicts = cvl.evaluate("1.8.0", base="1.6.0",
                                 others=[other(40, "1.7.0"), other(41, "1.6.0")])
        self.assertEqual(conflicts, [])

    def test_duplicate_version_conflicts(self):
        conflicts = cvl.evaluate("1.7.0", base="1.6.0", others=[other(40, "1.7.0")])
        self.assertEqual([c["number"] for c in conflicts], [40])

    def test_lower_than_open_pr_conflicts(self):
        # Current is lower than an open PR that already claimed a higher lane: a merge-order
        # collision waiting to happen, so warn now.
        conflicts = cvl.evaluate("1.7.0", base="1.6.0", others=[other(40, "1.8.0")])
        self.assertEqual([c["number"] for c in conflicts], [40])

    def test_others_that_did_not_bump_are_ignored(self):
        # An open PR still at the base version has not claimed a lane, so it never conflicts.
        conflicts = cvl.evaluate("1.7.0", base="1.6.0", others=[other(40, "1.6.0")])
        self.assertEqual(conflicts, [])

    def test_invalid_other_version_is_skipped_not_fatal(self):
        conflicts = cvl.evaluate("1.7.0", base="1.6.0",
                                 others=[other(40, "not-a-semver"), other(41, "1.7.0")])
        self.assertEqual([c["number"] for c in conflicts], [41])

    def test_suggested_next_is_above_the_highest_conflict(self):
        conflicts = cvl.evaluate("1.7.0", base="1.6.0",
                                 others=[other(40, "1.7.0"), other(41, "1.9.0")])
        # Both conflict (current 1.7.0 <= each); the suggestion patch-bumps above the
        # highest (1.9.0 -> 1.9.1), matching how the repo actually cleared such a collision
        # (#40 at 1.6.0 was overtaken and #44 re-landed as 1.6.1).
        self.assertEqual(cvl.suggested_next(conflicts), "1.9.1")


class TestParseOthersEnv(unittest.TestCase):
    def test_parses_json_list(self):
        raw = json.dumps([{"number": 40, "version": "1.7.0"}])
        self.assertEqual(cvl.parse_others_env(raw), [other(40, "1.7.0")])

    def test_empty_or_missing_is_empty(self):
        self.assertEqual(cvl.parse_others_env(None), [])
        self.assertEqual(cvl.parse_others_env(""), [])


class TestMain(unittest.TestCase):
    def _run(self, env):
        out, err = io.StringIO(), io.StringIO()
        old = dict(os.environ)
        try:
            os.environ.update(env)
            with redirect_stdout(out), redirect_stderr(err):
                code = cvl.main([])
        finally:
            os.environ.clear()
            os.environ.update(old)
        return code, out.getvalue() + err.getvalue()

    def test_conflict_exits_1_via_env(self):
        code, text = self._run({
            "VERSION_LANE_CURRENT": "1.7.0",
            "VERSION_LANE_BASE": "1.6.0",
            "VERSION_LANE_OTHERS": json.dumps([{"number": 40, "version": "1.7.0"}]),
        })
        self.assertEqual(code, 1)
        self.assertIn("#40", text)

    def test_clear_exits_0_via_env(self):
        code, text = self._run({
            "VERSION_LANE_CURRENT": "1.8.0",
            "VERSION_LANE_BASE": "1.6.0",
            "VERSION_LANE_OTHERS": json.dumps([{"number": 40, "version": "1.7.0"}]),
        })
        self.assertEqual(code, 0)

    def test_no_bump_exits_0(self):
        code, _ = self._run({
            "VERSION_LANE_CURRENT": "1.6.0",
            "VERSION_LANE_BASE": "1.6.0",
            "VERSION_LANE_OTHERS": json.dumps([{"number": 40, "version": "1.7.0"}]),
        })
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
