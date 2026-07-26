#!/usr/bin/env python3
"""Tests for scripts/rebuild_all.py (the generate-everything orchestrator)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rebuild_all  # noqa: E402


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self._orig_run = rebuild_all._run
        self.calls = []

        def fake_run(label, cmd):
            self.calls.append((label, cmd))
            return 0
        rebuild_all._run = fake_run

    def tearDown(self):
        rebuild_all._run = self._orig_run

    def test_check_runs_build_spec_screenshots_and_site_in_order_with_check_flag(self):
        # Hermetic: mock shutil.which so the node-gated screenshots/fixtures steps are always
        # present regardless of whether node is installed on the host. Without this the test
        # raises StopIteration on a node-less machine (no "Tutorial screenshots" label), which
        # is exactly what made a node-less pre-push run fail spuriously and tempt a bypass.
        # The host is pinned to Linux for the same reason: the screenshots step is Linux-only
        # (CMH-BUILD-16), so on a Windows/macOS dev box the label would legitimately be absent.
        with mock.patch.object(rebuild_all.shutil, "which", return_value="/usr/bin/node"), \
                mock.patch.object(rebuild_all, "_host_renders_ci_shots", return_value=True), \
                mock.patch.object(rebuild_all, "_tutorial_deps_installed", return_value=True):
            rc = rebuild_all.main(["rebuild_all.py", "--check"])
        self.assertEqual(rc, 0)
        labels = [c[0] for c in self.calls]
        # build.py runs first, the SPEC assembler is checked, screenshots precede the site sync,
        # and every step carries --check.
        self.assertTrue(labels[0].startswith("commentable-html layer dist"))
        self.assertTrue(any(lbl.startswith("commentable-html dev SPEC") for lbl in labels))
        self.assertTrue(labels[-1].startswith("GitHub Pages site"))
        self.assertLess(
            next(i for i, lbl in enumerate(labels) if lbl.startswith("commentable-html layer dist")),
            next(i for i, lbl in enumerate(labels) if lbl.startswith("commentable-html dev SPEC")),
        )
        self.assertLess(
            next(i for i, lbl in enumerate(labels) if lbl.startswith("Tutorial screenshots")),
            next(i for i, lbl in enumerate(labels) if lbl.startswith("GitHub Pages site")),
        )
        for _, cmd in self.calls:
            self.assertIn("--check", cmd)

    def test_build_mode_passes_no_check_flag(self):
        rebuild_all.main(["rebuild_all.py"])
        for _, cmd in self.calls:
            self.assertNotIn("--check", cmd)

    def test_nonzero_step_makes_the_run_fail(self):
        def failing_run(label, cmd):
            self.calls.append((label, cmd))
            return 1 if "site" in label.lower() else 0
        rebuild_all._run = failing_run
        self.assertEqual(rebuild_all.main(["rebuild_all.py", "--check"]), 1)

    def test_tutorial_screenshots_skipped_when_dev_deps_absent(self):
        # node is present but the commentable-html dev node_modules (@playwright/test) is not
        # installed, so the screenshots step is skipped with a note instead of a cryptic
        # ERR_MODULE_NOT_FOUND failure - and the run still succeeds.
        import io
        import contextlib
        with mock.patch.object(rebuild_all.shutil, "which", return_value="/usr/bin/node"), \
                mock.patch.object(rebuild_all, "_host_renders_ci_shots", return_value=True), \
                mock.patch.object(rebuild_all, "_tutorial_deps_installed", return_value=False):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = rebuild_all.main(["rebuild_all.py", "--check"])
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        labels = [c[0] for c in self.calls]
        self.assertFalse(any("Tutorial screenshots" in lbl for lbl in labels))
        # The actionable skip message is printed (not the misleading "node not found").
        self.assertIn("commentable-html dev node_modules not installed", out)
        self.assertIn("scripts/setup_dev.py", out)
        # The rest of the pipeline still runs (the skip is surgical, not a bail-out).
        self.assertTrue(any(lbl.startswith("GitHub Pages site") for lbl in labels))

    def test_fixtures_step_is_skipped_when_node_is_absent(self):
        orig_which = rebuild_all.shutil.which
        rebuild_all.shutil.which = lambda name: None
        try:
            rebuild_all.main(["rebuild_all.py", "--check"])
        finally:
            rebuild_all.shutil.which = orig_which
        labels = [c[0] for c in self.calls]
        self.assertFalse(any("fixtures" in lbl.lower() for lbl in labels))

    def test_screenshots_skip_message_distinguishes_missing_script(self):
        # node present + deps present, but the capture script path does not exist -> a distinct
        # "capture script not found" note (not the misleading "node not found" or the deps note).
        import io
        import contextlib
        with mock.patch.object(rebuild_all.shutil, "which", return_value="/usr/bin/node"), \
                mock.patch.object(rebuild_all, "_host_renders_ci_shots", return_value=True), \
                mock.patch.object(rebuild_all, "_tutorial_deps_installed", return_value=True), \
                mock.patch.object(rebuild_all.os.path, "exists", return_value=False):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = rebuild_all.main(["rebuild_all.py", "--check"])
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn(
            "Tutorial screenshots (capture_tutorial.mjs) == skipped (capture script not found)", out)

    def test_the_shared_predicate_fails_closed_when_the_tool_cannot_be_imported(self):
        # Guessing "this host renders like CI" when the shared guard is unavailable is exactly how
        # wrong PNGs got committed, so an import failure must mean "skip", not "go ahead".
        with mock.patch.dict(sys.modules, {"shots_linux": None}), \
                mock.patch.object(rebuild_all, "SHOTS_TOOL_DIR", "/nonexistent"):
            import builtins
            real_import = builtins.__import__

            def boom(name, *args, **kwargs):
                if name == "shots_linux":
                    raise ImportError("no shared predicate")
                return real_import(name, *args, **kwargs)

            with mock.patch.object(builtins, "__import__", boom):
                self.assertFalse(rebuild_all._host_renders_ci_shots())

    def test_screenshots_are_skipped_on_a_non_linux_host_with_an_actionable_note(self):
        # CMH-BUILD-16: the committed PNGs are Linux-rendered. On another OS this step would
        # re-render them with the HOST rasterizer, and --check would compare against that same
        # host renderer - so the run goes green locally and then fails the required
        # playwright-heavy job. Skip it and name the tool that does it correctly.
        import io
        import contextlib
        with mock.patch.object(rebuild_all.shutil, "which", return_value="/usr/bin/node"), \
                mock.patch.object(rebuild_all, "_host_renders_ci_shots", return_value=False), \
                mock.patch.object(rebuild_all, "_tutorial_deps_installed", return_value=True):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = rebuild_all.main(["rebuild_all.py", "--check"])
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        labels = [c[0] for c in self.calls]
        self.assertFalse(any("Tutorial screenshots" in lbl for lbl in labels))
        # Names the command that renders correctly, and says WHY this host cannot.
        self.assertIn("npm run shots", out)
        self.assertIn("renderer", out)
        # The skip is surgical - every other generator still runs.
        self.assertTrue(any(lbl.startswith("GitHub Pages site") for lbl in labels))


if __name__ == "__main__":
    unittest.main()
