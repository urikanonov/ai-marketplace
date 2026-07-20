"""Unit tests for scripts/run_plugin_python_tests.py.

Run by the validate CI job via `python -m unittest discover -s scripts -p "test_*.py"`,
so the shard-splitting, changed-plugin scoping, and discovery helpers that the CI
plugin-tests `python` matrix and the local pre-push hook rely on are covered by a
required status check. The pure helpers are exercised here; the actual unittest
loading/running is not (CI runs the real suites).
"""
import unittest
from pathlib import Path

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
            self.assertRegex(r, r"^plugins/[^/]+/dev/tests/test_.*\.py$")


if __name__ == "__main__":
    unittest.main()
