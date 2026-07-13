#!/usr/bin/env python3
"""Tests for scripts/check_required_checks.py (required-check drift detector)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_required_checks as crc  # noqa: E402


class CompareTests(unittest.TestCase):
    def test_in_sync(self):
        self.assertEqual(crc.compare(["a", "b"], ["b", "a"]), ([], []))

    def test_missing_is_expected_not_live(self):
        missing, extra = crc.compare(["a", "b", "c"], ["a"])
        self.assertEqual(missing, ["b", "c"])
        self.assertEqual(extra, [])

    def test_extra_is_live_not_expected(self):
        missing, extra = crc.compare(["a"], ["a", "z"])
        self.assertEqual(missing, [])
        self.assertEqual(extra, ["z"])


class LoadExpectedTests(unittest.TestCase):
    def test_reads_the_committed_source_of_truth(self):
        branch, checks = crc.load_expected()
        self.assertEqual(branch, "main")
        for required in ("validate", "secret-scan", "pwsh-tests (ubuntu-latest)"):
            self.assertIn(required, checks)


class MainWithEnvLiveTests(unittest.TestCase):
    def _run_with_live(self, live):
        os.environ["REQUIRED_CHECKS_LIVE"] = json.dumps(live)
        try:
            return crc.main(["check_required_checks.py"])
        finally:
            del os.environ["REQUIRED_CHECKS_LIVE"]

    def test_main_passes_when_live_matches_expected(self):
        _, expected = crc.load_expected()
        self.assertEqual(self._run_with_live(expected), 0)

    def test_main_fails_on_drift(self):
        _, expected = crc.load_expected()
        dropped = expected[:-1]  # drop one required check -> drift
        self.assertEqual(self._run_with_live(dropped), 1)

    def test_main_reports_cannot_read_without_live_source(self):
        # No env override and gh unavailable/failing -> exit 2 (skip, not a false pass).
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = os.path.join(tmp, "nogh")
            os.makedirs(fake_home)
            env_path = os.environ.get("PATH", "")
            os.environ["PATH"] = fake_home
            os.environ.pop("REQUIRED_CHECKS_LIVE", None)
            try:
                rc = crc.main(["check_required_checks.py"])
            finally:
                os.environ["PATH"] = env_path
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
