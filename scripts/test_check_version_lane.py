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

    def test_trailing_higher_lane_is_not_a_conflict(self):
        # Current is LOWER than an open PR that claimed a higher lane. That is the intentional
        # stacked-merge order (merge the lower one first), so it is NOT a re-bump conflict; it is
        # reported separately as an informational trailing lane.
        conflicts = cvl.evaluate("1.7.0", base="1.6.0", others=[other(40, "1.8.0")])
        self.assertEqual(conflicts, [])

    def test_trailing_lanes_reports_higher_open_prs(self):
        # trailing_lanes lists open PRs that claimed a HIGHER lane than current (current bumped
        # past base). Duplicates and lower/equal lanes are not trailing.
        trailing = cvl.trailing_lanes("1.7.0", base="1.6.0",
                                      others=[other(40, "1.8.0"), other(41, "1.7.0"),
                                              other(42, "1.6.0"), other(43, "1.9.0")])
        self.assertEqual(sorted(c["number"] for c in trailing), [40, 43])

    def test_no_trailing_when_current_did_not_bump(self):
        self.assertEqual(cvl.trailing_lanes("1.6.0", base="1.6.0", others=[other(40, "1.8.0")]), [])

    def test_others_that_did_not_bump_are_ignored(self):
        # An open PR still at the base version has not claimed a lane, so it never conflicts.
        conflicts = cvl.evaluate("1.7.0", base="1.6.0", others=[other(40, "1.6.0")])
        self.assertEqual(conflicts, [])

    def test_invalid_other_version_is_skipped_not_fatal(self):
        conflicts = cvl.evaluate("1.7.0", base="1.6.0",
                                 others=[other(40, "not-a-semver"), other(41, "1.7.0")])
        self.assertEqual([c["number"] for c in conflicts], [41])

    def test_suggested_next_is_above_the_highest_conflict(self):
        # Only a DUPLICATE lane is a conflict now, so evaluate returns just PR #40 (also 1.7.0);
        # the higher open PR #41 (1.9.0) is a trailing lane, not a conflict. The suggestion
        # patch-bumps above the highest CONFLICTING (duplicate) version (1.7.0 -> 1.7.1).
        conflicts = cvl.evaluate("1.7.0", base="1.6.0",
                                 others=[other(40, "1.7.0"), other(41, "1.9.0")])
        self.assertEqual([c["number"] for c in conflicts], [40])
        self.assertEqual(cvl.suggested_next(conflicts), "1.7.1")


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

    def test_trailing_higher_lane_exits_0_with_note(self):
        # This PR (1.47.0) trails an open higher lane (#119 at 1.48.0): the intentional stacked
        # order. It must NOT fail the advisory check; it prints an informational note and exits 0.
        code, text = self._run({
            "VERSION_LANE_CURRENT": "1.47.0",
            "VERSION_LANE_BASE": "1.46.0",
            "VERSION_LANE_OTHERS": json.dumps([{"number": 119, "version": "1.48.0"}]),
        })
        self.assertEqual(code, 0)
        self.assertIn("#119", text)
        self.assertIn("trails", text.lower())


if __name__ == "__main__":
    unittest.main()
