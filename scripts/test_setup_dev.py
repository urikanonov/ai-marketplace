#!/usr/bin/env python3
"""Tests for scripts/setup_dev.py (the fresh-clone dev bootstrap)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setup_dev  # noqa: E402


class DiscoverSuitesTests(unittest.TestCase):
    def test_discovers_site_tests_and_every_plugin_dev_suite(self):
        suites = setup_dev.discover_node_suites(setup_dev.ROOT)
        rels = {setup_dev._rel(setup_dev.ROOT, s) for s in suites}
        self.assertIn("site/tests", rels)
        self.assertIn("plugins/commentable-html/dev", rels)
        # The discovery signal is a real package.json in each returned suite.
        for s in suites:
            self.assertTrue(os.path.isfile(os.path.join(s, "package.json")), s)

    def test_a_plugin_without_a_dev_package_json_is_not_listed(self):
        # Discovery scans suite locations for package.json, so the auto-updater (no dev suite) is
        # absent - proving the list is discovered, not a hard-coded pair.
        suites = setup_dev.discover_node_suites(setup_dev.ROOT)
        rels = {setup_dev._rel(setup_dev.ROOT, s) for s in suites}
        self.assertNotIn("plugins/urikan-ai-marketplace-auto-updater/dev", rels)


class SuiteNeedsBrowsersTests(unittest.TestCase):
    def test_true_for_playwright_suites(self):
        for rel in ("site/tests", "plugins/commentable-html/dev"):
            d = os.path.join(setup_dev.ROOT, *rel.split("/"))
            self.assertTrue(setup_dev.suite_needs_browsers(d), rel)


class PlanTests(unittest.TestCase):
    def test_plan_enables_hooks_then_python_then_node_deps_and_browsers(self):
        steps = setup_dev.plan(setup_dev.ROOT, browsers=True)
        labels = [s.label for s in steps]
        # Hooks first, then the Python validator deps.
        self.assertTrue(labels[0].lower().startswith("enable git hooks"))
        self.assertEqual(steps[0].cmd, ["git", "config", "core.hooksPath", ".githooks"])
        self.assertTrue(any("python" in l.lower() for l in labels))
        # Each suite gets an npm ci; a Playwright suite also gets a browser install after it.
        cmh = os.path.join(setup_dev.ROOT, "plugins", "commentable-html", "dev")
        npm_steps = [s for s in steps if s.cmd[:2] == ["npm", "ci"] and s.cwd == cmh]
        self.assertEqual(len(npm_steps), 1)
        self.assertIn("--ignore-scripts", npm_steps[0].cmd)
        browser_steps = [s for s in steps if s.cmd[:2] == ["npx", "playwright"] and s.cwd == cmh]
        self.assertEqual(len(browser_steps), 1)
        self.assertEqual(browser_steps[0].cmd, ["npx", "playwright", "install", "chromium"])
        self.assertLess(steps.index(npm_steps[0]), steps.index(browser_steps[0]))

    def test_no_browsers_flag_omits_playwright_installs_but_keeps_node_deps(self):
        steps = setup_dev.plan(setup_dev.ROOT, browsers=False)
        self.assertFalse(any(s.cmd[:2] == ["npx", "playwright"] for s in steps))
        self.assertTrue(any(s.cmd[:2] == ["npm", "ci"] for s in steps))

    def test_plan_is_deterministic_and_idempotent(self):
        a = setup_dev.plan(setup_dev.ROOT, browsers=True)
        b = setup_dev.plan(setup_dev.ROOT, browsers=True)
        self.assertEqual([(s.label, s.cwd, s.cmd) for s in a],
                         [(s.label, s.cwd, s.cmd) for s in b])


class MainDispatchTests(unittest.TestCase):
    def test_install_mode_runs_every_planned_step(self):
        calls = []
        with mock.patch.object(setup_dev, "_run",
                               lambda label, cwd, cmd: calls.append(label) or 0), \
             mock.patch.object(setup_dev, "_require_tools", lambda browsers: []):
            rc = setup_dev.main(["setup_dev.py", "--no-browsers"])
        self.assertEqual(rc, 0)
        self.assertTrue(any("git hooks" in c.lower() for c in calls))
        self.assertTrue(any("node deps" in c.lower() for c in calls))

    def test_missing_tools_fail_fast_with_nonzero(self):
        with mock.patch.object(setup_dev, "_require_tools", lambda browsers: ["npm"]):
            rc = setup_dev.main(["setup_dev.py", "--no-browsers"])
        self.assertEqual(rc, 1)

    def test_a_failing_step_makes_the_run_fail(self):
        def failing(label, cwd, cmd):
            return 1 if "python" in label.lower() else 0
        with mock.patch.object(setup_dev, "_run", failing), \
             mock.patch.object(setup_dev, "_require_tools", lambda browsers: []):
            rc = setup_dev.main(["setup_dev.py", "--no-browsers"])
        self.assertEqual(rc, 1)

    def test_check_mode_reports_readiness(self):
        with mock.patch.object(setup_dev, "readiness_problems", lambda root: []):
            self.assertEqual(setup_dev.main(["setup_dev.py", "--check"]), 0)
        with mock.patch.object(setup_dev, "readiness_problems", lambda root: ["x"]):
            self.assertEqual(setup_dev.main(["setup_dev.py", "--check"]), 1)


if __name__ == "__main__":
    unittest.main()
