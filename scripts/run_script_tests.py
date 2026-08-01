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
import hashlib
import os
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

#: What "the repository is unchanged" means. `git status --porcelain` alone would miss a suite that
#: COMMITTED its fixtures (status comes back clean), moved a ref, or rewrote the CONTENT of a file
#: that was already dirty before the run - so HEAD, the refs, and the full diff are all part of the
#: snapshot. Untracked files are hashed separately, since status only names them.
_PROBES = (
    ("status", ["status", "--porcelain"]),
    ("head", ["rev-parse", "HEAD"]),
    ("refs", ["for-each-ref", "--format=%(refname) %(objectname)"]),
    ("diff", ["diff", "HEAD"]),
)


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


def untracked_digest(repo_root, env=None):
    """`path sha256` for every untracked, non-ignored file, or None when it cannot be listed.

    `git status` names an untracked file but says nothing about its CONTENT, so a suite that
    overwrote one would otherwise look like no change at all.
    """
    if not repo_root:
        return None
    env = clean_git_env() if env is None else env
    try:
        proc = subprocess.run(["git", "-C", str(repo_root), "ls-files", "--others",
                               "--exclude-standard", "-z"],
                              capture_output=True, text=True, env=env)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    lines = []
    for name in sorted(part for part in proc.stdout.split("\0") if part):
        path = Path(repo_root) / name
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            digest = "<unreadable>"
        lines.append("%s %s\n" % (name, digest))
    return "".join(lines)


def worktree_state(repo_root, env=None):
    """A snapshot of the repository the suite must not disturb, or None when it cannot be read.

    A probe that git refuses (`rev-parse HEAD` in a repository with no commits, say) is recorded as
    unavailable rather than dropping the whole snapshot, so a partially readable repository is still
    compared. None is returned only when NOTHING could be read - git missing, or the path is not a
    repository. None means "unknown", never "clean": `describe_leak` treats a snapshot that went
    from known to unknown as a change, because that is what deleting `.git` mid-run looks like.
    """
    if not repo_root:
        return None
    env = clean_git_env() if env is None else env
    parts = []
    unavailable = 0
    for name, args in _PROBES:
        try:
            proc = subprocess.run(["git", "-C", str(repo_root)] + args,
                                  capture_output=True, text=True, env=env)
        except OSError:
            return None
        if proc.returncode == 0:
            text = proc.stdout
        else:
            text = "<unavailable>"
            unavailable += 1
        parts.append("[%s]\n%s" % (name, text if text.endswith("\n") else text + "\n"))
    digest = untracked_digest(repo_root, env)
    if digest is None:
        unavailable += 1
        digest = "<unavailable>\n"
    parts.append("[untracked]\n%s" % digest)
    if unavailable == len(_PROBES) + 1:
        return None
    return "".join(parts)


def describe_leak(leftovers, before, after):
    """Human-readable problems for a finished run; empty when the run left nothing behind.

    `before`/`after` are `worktree_state` results. A tree that was ALREADY dirty is not blamed on
    the suite, only a DIFFERENCE is - including a difference where one side is None, since a
    repository that stopped being readable while the suite ran certainly changed.
    """
    problems = []
    if leftovers:
        problems.append("the suite left %d path(s) in its working directory: %s"
                        % (len(leftovers), ", ".join(leftovers)))
    if (before is not None or after is not None) and before != after:
        problems.append(
            "the repository changed while the suite ran. If you were editing files during the run, "
            "rerun on a quiet tree; ONLY if you must keep editing, pass --no-worktree-check "
            "(from the pre-push hook: PREPUSH_ALLOW_TREE_EDITS=1 git push). Never use it to "
            "silence a real leak - this is the only check that catches a test writing an ABSOLUTE "
            "path into the repository.\n"
            "--- before ---\n%s--- after ---\n%s"
            % (_render_state(before), _render_state(after)))
    return problems


def _render_state(state):
    return "<unreadable repository>\n" if state is None else state


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
    repo_root = args.repo_root or None
    if repo_root:
        # The suite used to run WITH the repository root as its cwd, so the root was importable.
        # Keep that true from the sandbox, or a test that imports a top-level package would start
        # failing for a reason that has nothing to do with what it tests.
        inherited = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(repo_root) + (os.pathsep + inherited if inherited else "")
    watched = None if args.no_worktree_check else repo_root
    # `ignore_cleanup_errors` keeps a leaked open handle on Windows from masking the real verdict.
    try:
        sandbox = tempfile.TemporaryDirectory(prefix="script-tests-", ignore_cleanup_errors=True)
    except TypeError:  # Python < 3.10
        sandbox = tempfile.TemporaryDirectory(prefix="script-tests-")
    with sandbox as cwd:
        before = worktree_state(watched, env)
        proc = subprocess.run(discover_argv(args.tests_dir, args.pattern), cwd=cwd, env=env)
        after = worktree_state(watched, env)
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
