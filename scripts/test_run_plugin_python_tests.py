"""Unit tests for scripts/run_plugin_python_tests.py.

Run by the validate CI job via `python -m unittest discover -s scripts -p "test_*.py"`,
so the shard-splitting, changed-plugin scoping, and discovery helpers that the CI
plugin-tests `python` matrix and the local pre-push hook rely on are covered by a
required status check. The pure helpers are exercised here; the actual unittest
loading/running is not (CI runs the real suites).
"""
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_plugin_python_tests as rp


class SelectShardTests(unittest.TestCase):
    def test_partitions_without_overlap_or_loss(self):
        files = [Path(f"plugins/p/dev/tests/test_{i}.py") for i in range(10)]
        total = 3
        shards = [rp.select_shard(files, i, total) for i in range(1, total + 1)]
        # Every file appears exactly once across all shards.
        flat = [f for shard in shards for f in shard]
        self.assertEqual(sorted(flat), sorted(files))
        self.assertEqual(len(flat), len(files))
        # Round-robin balance: shard sizes differ by at most one.
        sizes = sorted(len(s) for s in shards)
        self.assertLessEqual(sizes[-1] - sizes[0], 1)

    def test_single_shard_returns_everything(self):
        files = [Path("a"), Path("b"), Path("c")]
        self.assertEqual(rp.select_shard(files, 1, 1), files)

    def test_more_shards_than_files_yields_empty_tail_shards(self):
        files = [Path("a"), Path("b")]
        self.assertEqual(rp.select_shard(files, 1, 3), [Path("a")])
        self.assertEqual(rp.select_shard(files, 2, 3), [Path("b")])
        self.assertEqual(rp.select_shard(files, 3, 3), [])

    def test_rejects_bad_index_or_total(self):
        files = [Path("a")]
        for idx, tot in [(0, 1), (2, 1), (-1, 3), (1, 0)]:
            with self.assertRaises(ValueError):
                rp.select_shard(files, idx, tot)


class ChangedPluginsTests(unittest.TestCase):
    def test_maps_plugin_paths_to_names(self):
        paths = [
            "plugins/commentable-html/dev/assets/js/45-composer.js",
            "plugins/urikan-ai-marketplace-auto-updater/hooks/x.ps1",
            "scripts/build_site_data.py",
            "README.md",
            "",
            "   ",
        ]
        self.assertEqual(
            rp.changed_plugins(paths),
            {"commentable-html", "urikan-ai-marketplace-auto-updater"},
        )

    def test_no_plugin_paths_is_empty(self):
        self.assertEqual(rp.changed_plugins(["scripts/a.py", "docs/b.md"]), set())


class FilterByPluginsTests(unittest.TestCase):
    def test_keeps_only_selected_plugins(self):
        root = Path("/repo")
        files = [
            root / "plugins/commentable-html/dev/tests/test_a.py",
            root / "plugins/multi-duck/dev/tests/test_b.py",
        ]
        kept = rp.filter_by_plugins(files, {"commentable-html"}, root)
        self.assertEqual(kept, [files[0]])

    def test_empty_plugin_set_keeps_nothing(self):
        root = Path("/repo")
        files = [root / "plugins/commentable-html/dev/tests/test_a.py"]
        self.assertEqual(rp.filter_by_plugins(files, set(), root), [])


class DiscoverTests(unittest.TestCase):
    def test_discovers_real_repo_suites_sorted_and_nonempty(self):
        files = rp.discover_test_files(rp.REPO_ROOT)
        self.assertTrue(files, "expected at least one plugin test suite in the repo")
        rels = [f.relative_to(rp.REPO_ROOT).as_posix() for f in files]
        self.assertEqual(rels, sorted(rels))
        for r in rels:
            self.assertRegex(r, r"^plugins/[^/]+/dev/tests/(.+/)?test_.*\.py$")

    def test_real_repo_has_no_stem_collisions(self):
        # The runner loads by basename, so the real repo must keep them unique - covering
        # helper modules too, not only test_*.py.
        rp.check_no_stem_collisions(rp.discover_importable_modules(rp.REPO_ROOT))  # no raise

    def test_importable_modules_include_helpers_and_exclude_pycache(self):
        mods = rp.discover_importable_modules(rp.REPO_ROOT)
        rels = [m.relative_to(rp.REPO_ROOT).as_posix() for m in mods]
        self.assertTrue(rels, "expected some importable modules discovered")
        self.assertFalse(any("__pycache__" in r for r in rels))
        # At least one non-test helper module is included (e.g. _paths.py).
        self.assertTrue(any(not Path(r).name.startswith("test_") for r in rels))
        # Every test file is also an importable module (superset relationship).
        tests = {t.relative_to(rp.REPO_ROOT).as_posix()
                 for t in rp.discover_test_files(rp.REPO_ROOT)}
        self.assertTrue(tests.issubset(set(rels)))


class CollisionGuardTests(unittest.TestCase):
    def test_raises_on_duplicate_basename_across_plugins(self):
        files = [
            Path("plugins/a/dev/tests/test_dup.py"),
            Path("plugins/b/dev/tests/test_dup.py"),
        ]
        with self.assertRaises(SystemExit):
            rp.check_no_stem_collisions(files)

    def test_raises_on_duplicate_helper_basename(self):
        # A same-named HELPER (not a test_ file) across plugins must also be rejected.
        files = [
            Path("plugins/a/dev/tests/_paths.py"),
            Path("plugins/b/dev/tests/_paths.py"),
        ]
        with self.assertRaises(SystemExit):
            rp.check_no_stem_collisions(files)

    def test_ok_on_unique_basenames(self):
        files = [
            Path("plugins/a/dev/tests/test_one.py"),
            Path("plugins/b/dev/tests/test_two.py"),
        ]
        rp.check_no_stem_collisions(files)  # must not raise


@contextlib.contextmanager
def _temp_test_file(name: str, body: str):
    """Create a temp dir holding one test module and yield its Path.

    Cleans up the sys.path entry and imported module so the runner's load does not leak
    state into the rest of the suite.
    """
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / name
        p.write_text(body, encoding="utf-8")
        try:
            yield p
        finally:
            sys.modules.pop(p.stem, None)
            with contextlib.suppress(ValueError):
                sys.path.remove(str(p.parent))


_PASSING = (
    "import unittest\n"
    "class T(unittest.TestCase):\n"
    "    def test_ok(self):\n"
    "        self.assertTrue(True)\n"
)
_RAISES_AT_IMPORT = "raise RuntimeError('boom at import')\n"


class MainWiringTests(unittest.TestCase):
    def test_main_fails_loudly_on_collision(self):
        # Regression guard for the exact silent-drop bug: main() must call the collision
        # guard, so two same-stem modules make it raise SystemExit (not run one silently).
        dup = [
            Path("plugins/a/dev/tests/test_dup.py"),
            Path("plugins/b/dev/tests/test_dup.py"),
        ]
        with mock.patch.object(rp, "discover_importable_modules", return_value=dup), \
             mock.patch.object(rp, "discover_test_files", return_value=dup):
            with self.assertRaises(SystemExit):
                rp.main([])

    def test_main_returns_1_when_a_module_fails_to_import(self):
        # The fail-loud contract: a module that raises at import must red the shard.
        with _temp_test_file("test_boom.py", _RAISES_AT_IMPORT) as boom:
            with mock.patch.object(rp, "discover_importable_modules", return_value=[boom]), \
                 mock.patch.object(rp, "discover_test_files", return_value=[boom]):
                self.assertEqual(rp.main(["--shard", "1/1"]), 1)

    def test_changed_only_runs_all_when_base_ref_unresolvable(self):
        # _git_changed_paths -> None means "cannot determine", so run EVERYTHING (fail-safe),
        # never silently nothing.
        with _temp_test_file("test_pass.py", _PASSING) as passing:
            with mock.patch.object(rp, "discover_importable_modules", return_value=[passing]), \
                 mock.patch.object(rp, "discover_test_files", return_value=[passing]), \
                 mock.patch.object(rp, "_git_changed_paths", return_value=None):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = rp.main(["--changed-only", "--shard", "1/1"])
                self.assertEqual(rc, 0)
                self.assertIn("running 1 test file", out.getvalue())

    def test_changed_only_runs_nothing_when_no_plugin_changed(self):
        # _git_changed_paths -> [] means the ref resolved and nothing relevant changed.
        with _temp_test_file("test_pass.py", _PASSING) as passing:
            with mock.patch.object(rp, "discover_importable_modules", return_value=[passing]), \
                 mock.patch.object(rp, "discover_test_files", return_value=[passing]), \
                 mock.patch.object(rp, "_git_changed_paths", return_value=[]):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = rp.main(["--changed-only"])
                self.assertEqual(rc, 0)
                self.assertIn("nothing to run", out.getvalue())


class MainTests(unittest.TestCase):
    def test_malformed_shard_returns_2(self):
        self.assertEqual(rp.main(["--shard", "abc"]), 2)

    def test_out_of_range_shard_returns_2(self):
        # Valid-format but out-of-range shards must exit cleanly (2), not traceback.
        for bad in ["0/3", "4/3", "1/0"]:
            with mock.patch.object(rp, "discover_test_files",
                                   return_value=[rp.REPO_ROOT / "plugins/x/dev/tests/test_a.py"]):
                self.assertEqual(rp.main(["--shard", bad]), 2, bad)

    def test_require_discovered_empty_returns_1(self):
        with mock.patch.object(rp, "discover_test_files", return_value=[]):
            self.assertEqual(rp.main(["--require-discovered"]), 1)

    def test_empty_shard_is_noop_success(self):
        one = [rp.REPO_ROOT / "plugins/x/dev/tests/test_only.py"]
        with mock.patch.object(rp, "discover_test_files", return_value=one):
            # shard 3 of 3 over a single file gets nothing -> success, runs no tests.
            self.assertEqual(rp.main(["--shard", "3/3"]), 0)


class GitChangedPathsTests(unittest.TestCase):
    def test_unresolvable_base_ref_returns_none(self):
        # None (not []) signals "could not determine" so the caller runs everything.
        self.assertIsNone(
            rp._git_changed_paths("refs/does/not/exist/ever", rp.REPO_ROOT)
        )


class ComposeShardTests(unittest.TestCase):
    """--jobs subdivides the SELECTED shard, so composition must stay an exact partition.

    The parallel mode re-invokes this script with a single composed "i/N" shard rather than
    handing children an explicit file list, so the composition arithmetic is the only thing
    standing between "-j 4" and silently dropped or double-run test files.
    """

    def test_composition_equals_direct_subselection(self):
        files = [Path(f"test_{i}.py") for i in range(23)]
        for total in (1, 2, 3):
            for index in range(1, total + 1):
                for jobs in (1, 2, 4, 5):
                    outer = rp.select_shard(files, index, total)
                    rebuilt = []
                    for j in range(1, jobs + 1):
                        idx, tot = rp.compose_shard(index, total, j, jobs)
                        rebuilt.extend(rp.select_shard(files, idx, tot))
                    self.assertEqual(
                        sorted(rebuilt, key=str), sorted(outer, key=str),
                        f"index={index} total={total} jobs={jobs} lost or duplicated files",
                    )
                    self.assertEqual(len(rebuilt), len(outer))

    def test_jobs_of_one_is_identity(self):
        self.assertEqual(rp.compose_shard(2, 3, 1, 1), (2, 3))

    def test_rejects_bad_job_index_or_count(self):
        for j, jobs in [(0, 1), (2, 1), (-1, 3), (1, 0)]:
            with self.assertRaises(ValueError):
                rp.compose_shard(1, 1, j, jobs)


class ResolveJobsTests(unittest.TestCase):
    def test_auto_uses_cpu_count(self):
        with mock.patch.object(rp.os, "cpu_count", return_value=8):
            self.assertEqual(rp.resolve_jobs("auto"), 8)

    def test_auto_falls_back_to_one_when_cpu_count_unknown(self):
        with mock.patch.object(rp.os, "cpu_count", return_value=None):
            self.assertEqual(rp.resolve_jobs("auto"), 1)

    def test_explicit_integer(self):
        self.assertEqual(rp.resolve_jobs("3"), 3)

    def test_rejects_non_positive_or_garbage(self):
        for bad in ["0", "-2", "abc", ""]:
            with self.assertRaises(ValueError):
                rp.resolve_jobs(bad)


class ParallelMainTests(unittest.TestCase):
    """--jobs N must fan out to N children and aggregate their exit codes fail-CLOSED."""

    def _fake_run(self, codes):
        calls = []

        def run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, codes[len(calls) - 1], "", "")

        return run, calls

    def test_spawns_one_child_per_job_with_composed_shards(self):
        run, calls = self._fake_run([0, 0, 0])
        with mock.patch.object(rp.subprocess, "run", side_effect=run):
            rc = rp.main(["--jobs", "3"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 3)
        shards = sorted(c[c.index("--shard") + 1] for c in calls)
        self.assertEqual(shards, ["1/3", "2/3", "3/3"])
        # A child must never recurse into parallel mode.
        for c in calls:
            self.assertNotIn("--jobs", c)

    def test_any_failing_child_reds_the_run(self):
        run, _ = self._fake_run([0, 1, 0])
        with mock.patch.object(rp.subprocess, "run", side_effect=run):
            self.assertEqual(rp.main(["--jobs", "3"]), 1)

    def test_composes_with_an_outer_shard(self):
        run, calls = self._fake_run([0, 0])
        with mock.patch.object(rp.subprocess, "run", side_effect=run):
            rc = rp.main(["--shard", "2/3", "--jobs", "2"])
        self.assertEqual(rc, 0)
        shards = sorted(c[c.index("--shard") + 1] for c in calls)
        # shard 2/3 split 2 ways -> files[1::3][0::2] and files[1::3][1::2]
        self.assertEqual(shards, ["2/6", "5/6"])

    def test_forwards_changed_only_and_base_ref_to_children(self):
        run, calls = self._fake_run([0, 0])
        with mock.patch.object(rp.subprocess, "run", side_effect=run):
            rp.main(["--jobs", "2", "--changed-only", "--base-ref", "origin/dev"])
        for c in calls:
            self.assertIn("--changed-only", c)
            self.assertIn("--base-ref", c)
            self.assertEqual(c[c.index("--base-ref") + 1], "origin/dev")

    def test_jobs_of_one_runs_in_process_without_spawning(self):
        one = [rp.REPO_ROOT / "plugins/x/dev/tests/test_only.py"]
        with mock.patch.object(rp, "discover_test_files", return_value=one), \
             mock.patch.object(rp, "discover_importable_modules", return_value=one), \
             mock.patch.object(rp.subprocess, "run") as spawned:
            rp.main(["--shard", "3/3", "--jobs", "1"])
        spawned.assert_not_called()

    def test_bad_jobs_value_returns_2(self):
        for bad in ["0", "-1", "abc"]:
            self.assertEqual(rp.main(["--jobs", bad]), 2, bad)


class HookWiringTests(unittest.TestCase):
    """The pre-push hook is the reason --jobs exists, so pin the wiring it depends on.

    The hook was measured at ~30 minutes with the suites inline, and 52% of observed pushes
    used --no-verify as a result. Two properties keep it usable: the suites are opt-in behind
    PREPUSH_TESTS, and when they DO run they fan out with --jobs. A silent revert of either
    would quietly restore the slow hook that trained everyone to bypass it.
    """

    def _hook(self):
        hook = rp.REPO_ROOT / ".githooks" / "pre-push"
        if not hook.exists():
            self.skipTest("pre-push hook not present")
        return hook.read_text(encoding="utf-8")

    def test_plugin_suite_invocations_request_parallel_jobs(self):
        source = self._hook().replace("\\\n", " ")
        calls = [ln.strip() for ln in source.splitlines()
                 if "run_plugin_python_tests.py" in ln and ln.strip().startswith("run_hermetic ")]
        self.assertTrue(calls, "the hook no longer launches the plugin Python suites")
        for call in calls:
            self.assertIn("--jobs", call,
                          "the hook runs the plugin suites serially again: %r" % (call,))

    def test_suites_are_gated_behind_prepush_tests(self):
        # Assert the GUARD, not merely the word: a bare mention in a comment must not satisfy this.
        source = self._hook()
        self.assertRegex(
            source, r'if\s+\[\s+"\$\{PREPUSH_TESTS:-0\}"\s+=\s+"1"\s+\]',
            "the slow suites are inline in pre-push again (no PREPUSH_TESTS guard)")

    def test_windows_only_plugin_tests_still_have_pre_merge_coverage(self):
        """Making the local suites opt-in removed the only place Windows-only tests ran.

        Several plugin suites are skipUnless(os.name == "nt") - directory-junction containment
        and the PowerShell launcher - so they SKIP on Linux. Before PREPUSH_TESTS they were
        covered incidentally by a maintainer's local (Windows) pre-push run. CI must therefore
        carry a Windows runner, or those tests regress with every required check green.
        """
        import yaml
        wf = rp.REPO_ROOT / ".github" / "workflows" / "plugin-tests.yml"
        matrix = yaml.safe_load(wf.read_text(encoding="utf-8"))["jobs"]["python"]["strategy"]["matrix"]
        self.assertIn("os", matrix, "the plugin Python job has no OS matrix")
        self.assertTrue(
            any(str(o).startswith("windows") for o in matrix["os"]),
            "no Windows runner in the plugin Python matrix, so skipUnless(os.name=='nt') "
            "suites have no pre-merge coverage: %r" % (matrix["os"],))

    def test_windows_only_plugin_tests_actually_exist(self):
        # The guard above is only meaningful while such tests exist; if they all go away, this
        # fails and the Windows matrix can be reconsidered deliberately rather than by accident.
        hits = []
        for f in rp.discover_test_files(rp.REPO_ROOT):
            text = f.read_text(encoding="utf-8", errors="replace")
            if 'skipUnless(os.name == "nt"' in text or "skipUnless(os.name == 'nt'" in text:
                hits.append(f.name)
        self.assertTrue(hits, "no Windows-only plugin tests found; revisit the Windows CI matrix")


class ParallelSpawnSmokeTests(unittest.TestCase):
    """Exercise the REAL spawn path once, unmocked.

    Every other parallel test mocks subprocess.run, and CI shards with --shard (serially per
    runner) rather than --jobs, so without this the actual fan-out - child argv, interpreter
    launch, output capture, exit-code aggregation - would never execute in any automated run.
    An empty selection keeps it fast and independent of git state while still starting two real
    interpreters.
    """

    def test_real_workers_spawn_and_aggregate_success(self):
        n = len(rp.discover_test_files(rp.REPO_ROOT))
        empty = n + 1  # shard (n+1)/(n+1) selects nothing, whatever the corpus size
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = rp.main(["--shard", f"{empty}/{empty}", "--jobs", "2"])
        text = out.getvalue()
        self.assertEqual(rc, 0, text)
        self.assertIn("worker 1/2", text)
        self.assertIn("worker 2/2", text)
        # The children really ran and reported their own (empty) selection.
        self.assertIn("nothing to run", text)


class ShardMatrixContiguityTests(unittest.TestCase):
    """The CI shard fan-out lives as hand-written "i/N" strings in plugin-tests.yml. A dropped or
    duplicated entry (e.g. deleting "5/5") would silently orphan a slice of tests while every other
    check stays green, so assert each sharded job lists a complete, unique 1..N cover. The runner's
    select_shard is count-agnostic, so this is the guard that keeps the workflow matrix honest."""

    _SHARDED_JOBS = ("playwright", "playwright-heavy", "python")

    def _shard_lists(self):
        import yaml
        wf = rp.REPO_ROOT / ".github" / "workflows" / "plugin-tests.yml"
        jobs = yaml.safe_load(wf.read_text(encoding="utf-8"))["jobs"]
        return {name: jobs[name]["strategy"]["matrix"]["shard"] for name in self._SHARDED_JOBS}

    def test_each_sharded_job_covers_1_to_N_uniquely(self):
        for job, shards in self._shard_lists().items():
            self.assertTrue(shards, f"{job}: empty shard matrix")
            totals = {s.split("/")[1] for s in shards}
            self.assertEqual(len(totals), 1, f"{job}: mixed shard totals {shards}")
            total = int(totals.pop())
            self.assertEqual(len(shards), total,
                             f"{job}: {len(shards)} shard entries but total is /{total}: {shards}")
            indices = sorted(int(s.split("/")[0]) for s in shards)
            self.assertEqual(indices, list(range(1, total + 1)),
                             f"{job}: shard indices {indices} are not a unique, contiguous 1..{total}")


if __name__ == "__main__":
    unittest.main()
