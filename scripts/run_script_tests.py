#!/usr/bin/env python3
"""Run the `scripts/` unit suite from a throwaway working directory, and fail if it leaks.

The suite used to write scratch Markdown (`a.md`, `b.md`, `new.md`, `old.md`) with bare relative
names, so the files landed in whatever directory it was launched from - the repository root, for
both `pre-push` and CI. Every push left the tree dirty (which then blocked a following rebase),
and two of those fixtures were swept into `main` by an unrelated PR's `git add -A` (#791).

Fixing the offending tests one at a time only lasts until the next one forgets, so this runner
makes the mistake impossible to miss instead:

  * the suite runs with its cwd set to a temporary sandbox, so a bare relative write lands there
    rather than in the repository, and
  * afterwards the sandbox must be EMPTY and the repository working tree must be UNCHANGED -
    otherwise the run fails and names what was left behind.

It costs no extra time: the suite runs exactly once, just somewhere harmless. The git location
variables are scrubbed too (see `_git_test_env`), so the runner is safe to call from a git hook.

    python scripts/run_script_tests.py
    python scripts/run_script_tests.py --no-worktree-check   # while editing the tree concurrently
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_test_env import clean_git_env  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parent

HINT = ("write scratch files under tempfile.TemporaryDirectory() (or another absolute temp path) "
        "and clean them up; never a bare relative name, which lands in the caller's cwd")


def discover_argv(tests_dir, pattern="test_*.py", python=None):
    """The `unittest discover` command line, pinned to `tests_dir` for BOTH the start directory
    and the import root so discovery does not depend on the (sandbox) working directory."""
    tests_dir = str(tests_dir)
    return [python or sys.executable, "-m", "unittest", "discover",
            "-s", tests_dir, "-t", tests_dir, "-p", pattern]


def sandbox_leftovers(sandbox):
    """Every path the suite left in its working directory, relative and slash-separated."""
    root = Path(sandbox)
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def worktree_state(repo_root, env=None):
    """`git status --porcelain` for `repo_root`, or None when that cannot be read.

    None means "unknown" (git missing, or not a repository), never "clean" - an unknown state is
    compared against another unknown one, so it can neither raise nor silently pass a real leak.
    """
    if not repo_root:
        return None
    try:
        proc = subprocess.run(["git", "-C", str(repo_root), "status", "--porcelain"],
                              capture_output=True, text=True,
                              env=clean_git_env() if env is None else env)
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def describe_leak(leftovers, before, after):
    """Human-readable problems for a finished run; empty when the run left nothing behind.

    `before`/`after` are `worktree_state` results: a tree that was ALREADY dirty is not blamed on
    the suite, only a difference is.
    """
    problems = []
    if leftovers:
        problems.append("the suite left %d path(s) in its working directory: %s"
                        % (len(leftovers), ", ".join(leftovers)))
    if before is not None and after is not None and before != after:
        problems.append("the repository working tree changed while the suite ran (if you edited "
                        "files during the run, that is this message - rerun on a quiet tree, or "
                        "pass --no-worktree-check).\n"
                        "--- git status before ---\n%s--- git status after ---\n%s"
                        % (before, after))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tests-dir", default=str(SCRIPTS),
                        help="directory to discover tests in (default: scripts/)")
    parser.add_argument("--pattern", default="test_*.py",
                        help="test file pattern (default: test_*.py)")
    parser.add_argument("--repo-root", default=str(REPO_ROOT),
                        help="repository to diff for stray writes; empty to skip that check")
    parser.add_argument("--no-worktree-check", action="store_true",
                        help="skip the repository diff (use when the tree is being edited "
                             "concurrently; the sandbox check still runs)")
    args = parser.parse_args(argv)

    env = clean_git_env()
    repo_root = None if args.no_worktree_check else (args.repo_root or None)
    # `ignore_cleanup_errors` keeps a leaked open handle on Windows from masking the real verdict.
    try:
        sandbox = tempfile.TemporaryDirectory(prefix="script-tests-", ignore_cleanup_errors=True)
    except TypeError:  # Python < 3.10
        sandbox = tempfile.TemporaryDirectory(prefix="script-tests-")
    with sandbox as cwd:
        before = worktree_state(repo_root, env)
        proc = subprocess.run(discover_argv(args.tests_dir, args.pattern), cwd=cwd, env=env)
        after = worktree_state(repo_root, env)
        leftovers = sandbox_leftovers(cwd)
        problems = describe_leak(leftovers, before, after)
        if problems:
            print("run_script_tests: sandbox: %s" % cwd, file=sys.stderr)

    for problem in problems:
        print("run_script_tests: %s" % problem, file=sys.stderr)
    if problems:
        print("run_script_tests: %s" % HINT, file=sys.stderr)
        return proc.returncode or 1
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
