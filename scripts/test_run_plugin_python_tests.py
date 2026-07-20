"""Unit tests for scripts/run_plugin_python_tests.py.

Run by the validate CI job via `python -m unittest discover -s scripts -p "test_*.py"`,
so the shard-splitting, changed-plugin scoping, and discovery helpers that the CI
plugin-tests `python` matrix and the local pre-push hook rely on are covered by a
required status check. The pure helpers are exercised here; the actual unittest
loading/running is not (CI runs the real suites).
"""
import contextlib
import io
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
