#!/usr/bin/env python3
"""Tests for scripts/setup_dev.py (the fresh-clone dev bootstrap)."""
import json
import os
import shutil
import sys
import tempfile
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
        with mock.patch.object(setup_dev, "readiness_problems", lambda root, browsers=True: []):
            self.assertEqual(setup_dev.main(["setup_dev.py", "--check"]), 0)
        with mock.patch.object(setup_dev, "readiness_problems", lambda root, browsers=True: ["x"]):
            self.assertEqual(setup_dev.main(["setup_dev.py", "--check"]), 1)


class SuiteNeedsBrowsersEdgeTests(unittest.TestCase):
    def _write(self, d, obj):
        with open(os.path.join(d, "package.json"), "w", encoding="utf-8") as fh:
            json.dump(obj, fh)

    def test_non_dict_deps_do_not_throw(self):
        # A parseable package.json whose dependencies sections are not objects must not crash plan().
        with tempfile.TemporaryDirectory() as d:
            self._write(d, {"dependencies": ["playwright"], "devDependencies": "nope"})
            self.assertFalse(setup_dev.suite_needs_browsers(d))

    def test_true_when_playwright_in_devdeps(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, {"devDependencies": {"@playwright/test": "^1"}})
            self.assertTrue(setup_dev.suite_needs_browsers(d))


class SyntheticDiscoveryTests(unittest.TestCase):
    def test_discovers_only_suite_dirs_that_have_a_package_json(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, "site", "tests"))
            with open(os.path.join(d, "site", "tests", "package.json"), "w", encoding="utf-8") as fh:
                json.dump({"devDependencies": {"@playwright/test": "^1"}}, fh)
            os.makedirs(os.path.join(d, "plugins", "foo", "dev"))
            with open(os.path.join(d, "plugins", "foo", "dev", "package.json"), "w", encoding="utf-8") as fh:
                json.dump({"devDependencies": {"adm-zip": "^0"}}, fh)
            os.makedirs(os.path.join(d, "plugins", "bar", "dev"))   # no package.json
            os.makedirs(os.path.join(d, "plugins", "baz"))          # no dev
            rels = sorted(setup_dev._rel(d, s) for s in setup_dev.discover_node_suites(d))
            self.assertEqual(rels, ["plugins/foo/dev", "site/tests"])
        finally:
            shutil.rmtree(d)


class NodeDepsMarkerTests(unittest.TestCase):
    def test_requires_completion_marker_not_just_the_dir(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(setup_dev._node_deps_installed(d))
            os.makedirs(os.path.join(d, "node_modules"))
            self.assertFalse(setup_dev._node_deps_installed(d))  # partial: dir but no marker
            open(os.path.join(d, "node_modules", ".package-lock.json"), "w").close()
            self.assertTrue(setup_dev._node_deps_installed(d))


class ReadinessProblemsTests(unittest.TestCase):
    def _root(self, complete=True, browsers_needed=True):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "site", "tests"))
        deps = {"@playwright/test": "^1"} if browsers_needed else {"adm-zip": "^0"}
        with open(os.path.join(d, "site", "tests", "package.json"), "w", encoding="utf-8") as fh:
            json.dump({"devDependencies": deps}, fh)
        nm = os.path.join(d, "site", "tests", "node_modules")
        os.makedirs(nm)
        if complete:
            open(os.path.join(nm, ".package-lock.json"), "w").close()
        return d

    def test_partial_node_install_is_flagged(self):
        d = self._root(complete=False)
        try:
            with mock.patch.object(setup_dev, "_git_hookspath", return_value=".githooks"), \
                 mock.patch.object(setup_dev.importlib.util, "find_spec", return_value=object()), \
                 mock.patch.object(setup_dev.shutil, "which", return_value="/x/tool"), \
                 mock.patch.object(setup_dev, "_chromium_installed", return_value=True):
                probs = setup_dev.readiness_problems(d)
            self.assertTrue(any("incomplete" in p for p in probs), probs)
        finally:
            shutil.rmtree(d)

    def test_missing_browser_flagged_and_no_browsers_omits_it(self):
        d = self._root(complete=True, browsers_needed=True)
        try:
            with mock.patch.object(setup_dev, "_git_hookspath", return_value=".githooks"), \
                 mock.patch.object(setup_dev.importlib.util, "find_spec", return_value=object()), \
                 mock.patch.object(setup_dev.shutil, "which", return_value="/x/tool"), \
                 mock.patch.object(setup_dev, "_chromium_installed", return_value=False):
                self.assertTrue(any("Playwright browser" in p
                                    for p in setup_dev.readiness_problems(d, browsers=True)))
                self.assertFalse(any("Playwright browser" in p
                                     for p in setup_dev.readiness_problems(d, browsers=False)))
        finally:
            shutil.rmtree(d)

    def test_flags_missing_tools_python_deps_and_hooks(self):
        d = self._root(complete=True)
        try:
            with mock.patch.object(setup_dev, "_git_hookspath", return_value=""), \
                 mock.patch.object(setup_dev.importlib.util, "find_spec", return_value=None), \
                 mock.patch.object(setup_dev.shutil, "which", return_value=None), \
                 mock.patch.object(setup_dev, "_chromium_installed", return_value=True):
                joined = "\n".join(setup_dev.readiness_problems(d))
            self.assertIn("core.hooksPath", joined)
            self.assertIn("pyyaml", joined)
            self.assertIn("jsonschema", joined)
            self.assertIn("required tool not on PATH: git", joined)
            self.assertIn("required tool not on PATH: npm", joined)
        finally:
            shutil.rmtree(d)


class RunAndHookspathTests(unittest.TestCase):
    def test_run_resolves_exe_and_passes_cwd(self):
        with mock.patch.object(setup_dev.shutil, "which", return_value="/abs/npm"), \
             mock.patch.object(setup_dev.subprocess, "run",
                               return_value=mock.Mock(returncode=0)) as mrun:
            rc = setup_dev._run("lbl", "/cwd", ["npm", "ci"])
        self.assertEqual(rc, 0)
        self.assertEqual(mrun.call_args[0][0], ["/abs/npm", "ci"])
        self.assertEqual(mrun.call_args[1].get("cwd"), "/cwd")

    def test_run_falls_back_to_cmd0_when_which_is_none(self):
        with mock.patch.object(setup_dev.shutil, "which", return_value=None), \
             mock.patch.object(setup_dev.subprocess, "run",
                               return_value=mock.Mock(returncode=3)) as mrun:
            rc = setup_dev._run("lbl", "/cwd", ["git", "config"])
        self.assertEqual(rc, 3)
        self.assertEqual(mrun.call_args[0][0], ["git", "config"])

    def test_git_hookspath_resolves_git_via_which(self):
        with mock.patch.object(setup_dev.shutil, "which", return_value="/abs/git"), \
             mock.patch.object(setup_dev.subprocess, "run",
                               return_value=mock.Mock(stdout=".githooks\n")) as mrun:
            val = setup_dev._git_hookspath("/root")
        self.assertEqual(val, ".githooks")
        self.assertEqual(mrun.call_args[0][0][0], "/abs/git")


class RequireToolsAndBrowserSkipTests(unittest.TestCase):
    def test_require_tools_gates_npx_on_browser_suites(self):
        with mock.patch.object(setup_dev.shutil, "which", return_value="/x"):
            self.assertEqual(setup_dev._require_tools(True), [])

        def which(t):
            return None if t == "npx" else "/x"
        with mock.patch.object(setup_dev.shutil, "which", side_effect=which):
            # The real repo has Playwright suites, so npx is required when browsers are requested...
            self.assertIn("npx", setup_dev._require_tools(True))
            # ...but not when browsers are skipped.
            self.assertNotIn("npx", setup_dev._require_tools(False))

    def test_browser_step_skipped_when_its_npm_ci_fails(self):
        ran = []

        def fake_run(label, cwd, cmd):
            ran.append(cmd)
            return 1 if cmd[:2] == ["npm", "ci"] else 0
        with mock.patch.object(setup_dev, "_run", fake_run), \
             mock.patch.object(setup_dev, "_require_tools", lambda browsers: []):
            rc = setup_dev.main(["setup_dev.py"])
        self.assertEqual(rc, 1)  # the npm ci failure propagates
        # No `npx playwright install` actually ran - each was skipped after its npm ci failed.
        self.assertFalse(any(cmd[:1] == ["npx"] for cmd in ran))


class ChromiumDetectionTests(unittest.TestCase):
    def test_requires_installation_complete_marker(self):
        with tempfile.TemporaryDirectory() as cache:
            browser = os.path.join(cache, "chromium-1234")
            os.makedirs(browser)
            with mock.patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": cache}):
                self.assertFalse(setup_dev._chromium_installed())  # dir but no completion marker
                open(os.path.join(browser, "INSTALLATION_COMPLETE"), "w").close()
                self.assertTrue(setup_dev._chromium_installed())

    def test_browsers_path_zero_is_treated_as_installed(self):
        with mock.patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": "0"}):
            self.assertTrue(setup_dev._chromium_installed())


if __name__ == "__main__":
    unittest.main()
