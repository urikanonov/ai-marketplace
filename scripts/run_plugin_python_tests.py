#!/usr/bin/env python3
"""Run the plugins' Python (unittest) test suites, optionally sharded or scoped.

Why this exists: the plugin Python suites (almost all of them commentable-html's ~76
files) are the second-slowest thing in the checkin flow after the Playwright suite. A
single serial `unittest discover` run is a bottleneck both in CI (the plugin-tests
`python` job) and locally (the pre-push hook). This runner keeps the exact same
per-file, in-process execution model as `unittest discover` (so no new shared-state
parallelism is introduced), but lets the work be split two ways:

  --shard I/N       run only shard I of N (deterministic round-robin over the sorted
                    file list), so CI can fan the suite out across N runners.
  --changed-only    run only the suites of plugins changed versus a base ref, so the
                    local pre-push hook does not rerun every plugin's suite for a
                    change that does not touch it.

Loading mirrors `unittest discover`: each selected test dir is placed on sys.path and
each test module is imported by its basename (test file basenames are globally unique
across the plugins, and same-dir helper modules like `_paths` resolve off sys.path),
so intra-suite imports such as `from test_validate import ...` keep working.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def discover_test_files(repo_root: Path) -> list[Path]:
    """Return every plugins/*/dev/tests/test_*.py file, sorted deterministically."""
    files = repo_root.glob("plugins/*/dev/tests/test_*.py")
    return sorted(files, key=lambda p: p.relative_to(repo_root).as_posix())


def select_shard(files: list[Path], index: int, total: int) -> list[Path]:
    """Round-robin slice: shard `index` (1-based) of `total`.

    Round-robin (files[index-1::total]) spreads neighbouring files - which tend to
    have similar cost - across shards more evenly than contiguous slicing.
    """
    if total < 1:
        raise ValueError("shard total must be >= 1")
    if not (1 <= index <= total):
        raise ValueError(f"shard index {index} out of range 1..{total}")
    return files[index - 1 :: total]


def plugin_of(path: Path, repo_root: Path) -> str | None:
    """Return the plugin name owning `path` (plugins/<name>/...), or None."""
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        rel = path
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "plugins":
        return parts[1]
    return None


def changed_plugins(diff_paths: list[str]) -> set[str]:
    """Map a list of repo-relative changed paths to the set of plugin names touched."""
    out: set[str] = set()
    for raw in diff_paths:
        raw = raw.strip()
        if not raw:
            continue
        parts = Path(raw).parts
        if len(parts) >= 2 and parts[0] == "plugins":
            out.add(parts[1])
    return out


def filter_by_plugins(files: list[Path], plugins: set[str], repo_root: Path) -> list[Path]:
    """Keep only test files owned by one of `plugins`."""
    return [f for f in files if plugin_of(f, repo_root) in plugins]


def _git_changed_paths(base_ref: str, repo_root: Path) -> list[str]:
    """Repo-relative paths changed on HEAD since its merge-base with base_ref.

    Uses the three-dot form so only changes introduced by the branch are considered.
    Returns [] (run nothing) if the base ref cannot be resolved locally.
    """
    try:
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", base_ref],
            cwd=repo_root, check=True, capture_output=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return []
    try:
        res = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
            cwd=repo_root, check=True, capture_output=True, text=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return []
    return [line for line in res.stdout.splitlines() if line.strip()]


def _load_suite(files: list[Path]) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    seen_dirs: list[str] = []
    for f in files:
        d = str(f.parent)
        if d not in seen_dirs:
            sys.path.insert(0, d)
            seen_dirs.append(d)
    for f in files:
        suite.addTests(loader.loadTestsFromName(f.stem))
    return suite


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shard", default="1/1",
                    help="Run shard I of N, formatted I/N (default 1/1 = everything).")
    ap.add_argument("--changed-only", action="store_true",
                    help="Only run suites of plugins changed vs --base-ref.")
    ap.add_argument("--base-ref", default="origin/main",
                    help="Base ref for --changed-only (default origin/main).")
    ap.add_argument("--require-discovered", action="store_true",
                    help="Fail if no plugin test files exist at all (CI safety net).")
    ap.add_argument("-v", "--verbose", action="count", default=1)
    args = ap.parse_args(argv)

    try:
        index_s, total_s = args.shard.split("/", 1)
        index, total = int(index_s), int(total_s)
    except ValueError:
        print(f"error: --shard must look like I/N, got {args.shard!r}", file=sys.stderr)
        return 2

    all_files = discover_test_files(REPO_ROOT)
    if args.require_discovered and not all_files:
        print("error: no plugin Python test suites were discovered "
              "(expected at least one plugins/*/dev/tests/test_*.py)", file=sys.stderr)
        return 1

    files = all_files
    if args.changed_only:
        touched = changed_plugins(_git_changed_paths(args.base_ref, REPO_ROOT))
        files = filter_by_plugins(files, touched, REPO_ROOT)
        if not files:
            print(f"No changed-plugin Python suites vs {args.base_ref}; nothing to run.")
            return 0

    files = select_shard(files, index, total)
    if not files:
        print(f"Shard {index}/{total}: no test files assigned; nothing to run.")
        return 0

    print(f"Shard {index}/{total}: running {len(files)} test file(s):")
    for f in files:
        print(f"  {f.relative_to(REPO_ROOT).as_posix()}")

    suite = _load_suite(files)
    runner = unittest.TextTestRunner(verbosity=args.verbose)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
