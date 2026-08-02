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

A serial run measured 639.8s, which is why `--jobs` exists: it fans the suite out across worker
PROCESSES, each with its OWN throwaway sandbox, while the repository snapshot is taken once around
the whole run. Splitting is by individual TEST (a deterministic stride over the discovered order),
so one very slow module cannot pin the wall time.

    python scripts/run_script_tests.py
    python scripts/run_script_tests.py --jobs auto            # fan out across the CPUs
    python scripts/run_script_tests.py --no-worktree-check   # while editing the tree concurrently
"""
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_test_env import clean_git_env  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parent

HINT = ("write scratch files under tempfile.TemporaryDirectory() (or another absolute temp path) "
        "and clean them up; never a bare relative name, which lands in the caller's cwd")

#: What "the repository is unchanged" means. `git status --porcelain` alone would miss a suite that
#: COMMITTED its fixtures (status comes back clean), moved a ref, or rewrote the CONTENT of a file
#: that was already dirty before the run - so HEAD, the CHECKED-OUT REF (a suite that detached HEAD
#: or switched to another branch at the same commit leaves every other probe identical), the refs
#: THIS worktree owns (see `owned_refs`), and the full diff are all part of the snapshot. Untracked
#: files are hashed separately, since status only names them. A detached HEAD records the ref probe
#: as unavailable, which is stable and therefore still comparable.
_PROBES = (
    ("status", ["status", "--porcelain"]),
    ("head", ["rev-parse", "HEAD"]),
    ("branch", ["symbolic-ref", "-q", "HEAD"]),
    ("diff", ["diff", "HEAD"]),
)

#: The per-worktree ref namespaces. Unlike `refs/heads/*` and `refs/remotes/*`, git resolves these
#: against the worktree's own git dir, so a sibling can never move them - and a suite that left a
#: bisect or a rebase running in the repository is a leak no other probe here notices.
_OWNED_REF_PATTERNS = ("refs/bisect/*", "refs/rewritten/*", "refs/worktree/*")


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


def select_shard(items, index, total):
    """Round-robin slice: shard `index` (1-based) of `total`.

    A plain stride, so the shards are an exact partition (nothing dropped, nothing run twice) and
    neighbouring items - which tend to cost the same - land on different workers.
    """
    if total < 1:
        raise ValueError("shard total must be >= 1")
    if not (1 <= index <= total):
        raise ValueError("shard index %d out of range 1..%d" % (index, total))
    return list(items)[index - 1::total]


def compose_shard(index, total, job_index, jobs):
    """The single shard that selects job `job_index` of `jobs` WITHIN shard `index`/`total`.

    Workers are re-invocations of this script rather than handed an explicit test list, so the two
    levels of stride collapse into one "i/N" pair. Because select_shard is a plain stride the
    composition is exact:

        items[index-1::total][job-1::jobs] == items[(index-1)+(job-1)*total :: total*jobs]
    """
    if total < 1:
        raise ValueError("shard total must be >= 1")
    if not (1 <= index <= total):
        raise ValueError("shard index %d out of range 1..%d" % (index, total))
    if jobs < 1:
        raise ValueError("jobs must be >= 1")
    if not (1 <= job_index <= jobs):
        raise ValueError("job index %d out of range 1..%d" % (job_index, jobs))
    return ((index - 1) + (job_index - 1) * total + 1, total * jobs)


def resolve_jobs(spec):
    """Resolve --jobs: a positive integer, or "auto" for the CPU count (1 if unknown)."""
    if spec == "auto":
        return os.cpu_count() or 1
    try:
        n = int(spec)
    except (TypeError, ValueError):
        raise ValueError("--jobs must be a positive integer or 'auto', got %r" % (spec,)) from None
    if n < 1:
        raise ValueError("--jobs must be >= 1, got %d" % n)
    return n


def iter_tests(suite):
    """Flatten a suite into its individual tests, preserving discovery order."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_tests(item)
        else:
            yield item


def dedupe_tests(tests):
    """The discovered tests with exact duplicates removed, first occurrence kept.

    A compatibility module that re-exports another module's cases (`test_build_site_data.py` does
    `from test_build_site_data_drift import *`) makes discovery yield the SAME test twice, since a
    test's id is its defining module plus class plus method. Serially that only wasted time; across
    workers the two copies could run CONCURRENTLY, which no test is written to survive.
    """
    seen = set()
    unique = []
    for test in tests:
        try:
            key = test.id()
        except Exception:  # noqa: BLE001 - an unidentifiable test is kept rather than dropped
            unique.append(test)
            continue
        if key in seen:
            continue
        seen.add(key)
        unique.append(test)
    return unique


def _sandbox():
    """A throwaway directory context. `ignore_cleanup_errors` keeps a leaked open handle on
    Windows from masking the real verdict."""
    try:
        return tempfile.TemporaryDirectory(prefix="script-tests-", ignore_cleanup_errors=True)
    except TypeError:  # Python < 3.10
        return tempfile.TemporaryDirectory(prefix="script-tests-")


def build_child_argv(index, total, job_index, jobs, args, sandbox=None, python=None):
    """Argv for one worker: its composed shard plus the suite selection.

    Deliberately omits --jobs (a worker can never recurse into another fan-out) and passes
    --no-worktree-check, because the PARENT snapshots the repository once around the whole run;
    letting every worker snapshot it too would only race their `git update-index` calls. The
    parent also OWNS each worker's sandbox and passes it in, so the leftover check is made by a
    process the tests cannot terminate.
    """
    idx, tot = compose_shard(index, total, job_index, jobs)
    argv = [python or sys.executable, str(Path(__file__).resolve()),
            "--tests-dir", str(args.tests_dir), "--pattern", str(args.pattern),
            "--repo-root", str(args.repo_root), "--no-worktree-check",
            "--shard", "%d/%d" % (idx, tot)]
    if sandbox is not None:
        argv += ["--sandbox", str(sandbox)]
    return argv


def aggregate_results(results):
    """(returncode, error messages) for a finished fan-out. Fails CLOSED.

    Anything that is not an exit-0 worker - a failed suite, a crash, a worker that could not be
    launched at all, or an empty result set - reds the whole run.
    """
    errors = []
    if not results:
        return 1, ["no workers ran, so nothing was tested"]
    for job, res in enumerate(results, start=1):
        if isinstance(res, BaseException):
            errors.append("worker %d/%d could not run: %s: %s"
                          % (job, len(results), type(res).__name__, res))
        elif res.returncode != 0:
            errors.append("worker %d/%d failed (exit %d)" % (job, len(results), res.returncode))
    return (1 if errors else 0), errors


#: How a worker reports what it saw, and the parent's parse of it. Each worker discovers the suite
#: independently, so the stride is a partition of the SUITE only if they all saw the same
#: population - hence the cross-check rather than trusting each worker's own arithmetic.
COVERAGE = "run_script_tests: shard %d/%d discovered %d test(s), running %d"
_COVERAGE_RE = re.compile(
    r"^run_script_tests: shard \d+/\d+ discovered (\d+) test\(s\), running (\d+)$", re.M)


def check_coverage(outputs):
    """Error messages when the workers did not, between them, run the whole suite exactly once.

    `outputs` is each worker's captured output, in job order. Fails CLOSED: a worker that reported
    nothing, a worker that discovered a different number of tests than its peers, or a set of
    shards whose sizes do not add up to the population is an error - all of which mean tests may
    have run zero times while every worker still exited 0.
    """
    errors = []
    seen = []
    for job, text in enumerate(outputs, start=1):
        match = _COVERAGE_RE.search(text or "")
        if match is None:
            errors.append("worker %d/%d did not report what it discovered, so the suite cannot be "
                          "confirmed covered" % (job, len(outputs)))
            continue
        seen.append((job, int(match.group(1)), int(match.group(2))))
    if errors or not seen:
        return errors or ["no worker reported what it discovered"]
    totals = {discovered for _, discovered, _ in seen}
    if len(totals) > 1:
        return ["the workers disagree about how many tests exist (%s), so the shards are not a "
                "partition of the suite" % ", ".join(
                    "worker %d saw %d" % (job, discovered) for job, discovered, _ in seen)]
    discovered = totals.pop()
    ran = sum(count for _, _, count in seen)
    if ran != discovered:
        errors.append("the workers ran %d test(s) of the %d discovered" % (ran, discovered))
    return errors



def run_parallel(index, total, jobs, args, env):
    """Fan the selected shard out across `jobs` worker processes; replay output in job order.

    Workers are separate PROCESSES. The PARENT creates each worker's throwaway sandbox and checks
    it afterwards, so the #791 leak guard belongs to a process the tests cannot exit early from
    (and an abandoned sandbox is still cleaned up when a worker is killed).

    Returns (returncode, leftovers) where `leftovers` names anything found in a worker sandbox.
    """
    # Workers write UTF-8 whatever the console code page says, so the parent's UTF-8 decode below
    # cannot mojibake a non-ASCII traceback. Without this a piped worker on Windows encodes to the
    # ANSI code page and can even die with UnicodeEncodeError while printing a failure.
    env = dict(env)
    env["PYTHONIOENCODING"] = "utf-8"
    print("Running the scripts suite across %d parallel worker(s)." % jobs)

    def run_one(cmd):
        # Merge the streams so a worker's output stays in chronological order, and pin the decode:
        # errors="replace" turns an odd byte into mojibake rather than losing the whole worker's
        # output to a UnicodeDecodeError in the PARENT.
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace", env=env)

    with contextlib.ExitStack() as stack:
        sandboxes = [stack.enter_context(_sandbox()) for _ in range(jobs)]
        commands = [build_child_argv(index, total, j, jobs, args, sandbox=sandboxes[j - 1])
                    for j in range(1, jobs + 1)]
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = [pool.submit(run_one, c) for c in commands]
            for f in futures:
                try:
                    results.append(f.result())
                except Exception as exc:  # noqa: BLE001 - a launch failure must red the run
                    results.append(exc)

        for job, res in enumerate(results, start=1):
            print("\n===== worker %d/%d =====" % (job, jobs))
            if isinstance(res, BaseException):
                print("(worker could not run; see the error below)")
                continue
            if res.stdout:
                print(res.stdout, end="")

        leftovers = []
        for job, cwd in enumerate(sandboxes, start=1):
            stray = sandbox_leftovers(cwd)
            if stray:
                print("run_script_tests: worker %d/%d sandbox: %s" % (job, jobs, cwd),
                      file=sys.stderr)
            leftovers += stray

    rc, errors = aggregate_results(results)
    if rc == 0:
        # Only meaningful when every worker passed: a failed worker already reds the run, and its
        # output is the thing to read. This is the check that catches a GREEN run in which some
        # tests never executed.
        errors += check_coverage([res.stdout for res in results])
        rc = 1 if errors else 0
    for message in errors:
        print("run_script_tests: %s" % message, file=sys.stderr)
    return rc, leftovers


def run_shard(tests_dir, pattern, index, total, cwd):
    """Run shard `index`/`total` of the discovered suite in THIS process, from `cwd`.

    Discovery happens after the chdir, so even a module that writes at import time lands in the
    sandbox. Returns the process exit code.
    """
    previous = os.getcwd()
    os.chdir(cwd)
    try:
        suite = unittest.TestLoader().discover(tests_dir, pattern=pattern,
                                               top_level_dir=tests_dir)
        tests = dedupe_tests(iter_tests(suite))
        if not tests:
            # Serially an empty discovery is a visible "Ran 0 tests"; N silent workers are not, so
            # a fan-out that found nothing to run must fail rather than look clean.
            print("run_script_tests: discovered no tests in %s (pattern %s)"
                  % (tests_dir, pattern), file=sys.stderr)
            return 1
        mine = select_shard(tests, index, total)
        # The parent cross-checks these two numbers across the workers (see check_coverage): the
        # stride is only a partition of the SUITE if every worker discovered the same population,
        # and a worker whose discovery collapsed (an import error turns a module into a single
        # _FailedTest) would otherwise stride a different list and leave tests unrun.
        print(COVERAGE % (index, total, len(tests), len(mine)))
        if not mine:
            return 0
        result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(mine))
        return 0 if result.wasSuccessful() else 1
    finally:
        os.chdir(previous)



#: A stale index stat-cache makes git report line-ending noise - a CRLF working tree against an
#: LF-normalized HEAD - on one call and nothing on the next, so two snapshots of an untouched
#: repository could differ and fail the run for a change nobody made. Refreshing the cache first
#: makes the probes deterministic. It is the git equivalent of what `git status` does anyway.
_REFRESH = ["update-index", "-q", "--refresh"]


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


def owned_refs(repo_root, env=None):
    """`refname objectname` for the refs THIS worktree owns, or None when they cannot be listed.

    Every worktree shares one `.git` refs store, so snapshotting ALL refs made the guard fail for
    work this checkout never did: a sibling worktree committing on its own branch, or any concurrent
    `git fetch` refreshing `refs/remotes/*`, moved a ref and the run was blamed for it (#830). In a
    repo whose whole workflow is parallel worktrees that fires routinely, and a guard that has to be
    waved through by habit stops catching the real leak it exists for.

    So only the refs a leak in THIS run could move are compared: the branch HEAD has checked out
    (a suite that commits its fixtures moves it) and the per-worktree namespaces in
    `_OWNED_REF_PATTERNS`. A detached HEAD owns no branch, which is recorded as such rather than
    dropped, so the snapshot stays comparable.

    The accepted cost: a suite that leaves a stray BRANCH, TAG or STASH behind is no longer caught,
    because those live in the shared store and are indistinguishable from a sibling's work. They
    leave the checkout itself untouched, which is what this guard is for - a stray FILE (issue #791)
    still fails through `status`, `diff` and the untracked digest.
    """
    if not repo_root:
        return None
    env = clean_git_env() if env is None else env
    patterns = list(_OWNED_REF_PATTERNS)
    try:
        head = subprocess.run(["git", "-C", str(repo_root), "symbolic-ref", "-q", "HEAD"],
                              capture_output=True, text=True, env=env)
        branch = head.stdout.strip() if head.returncode == 0 else ""
        if branch:
            patterns.append(branch)
        proc = subprocess.run(["git", "-C", str(repo_root), "for-each-ref",
                               "--format=%(refname) %(objectname)", "--"] + sorted(patterns),
                              capture_output=True, text=True, env=env)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    text = proc.stdout if branch else "<detached>\n" + proc.stdout
    return text if text.endswith("\n") else text + "\n"


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
    try:
        # Exits non-zero merely because files ARE modified, and can lose a race for `index.lock`;
        # neither is a reason to fail, so the result is deliberately ignored.
        subprocess.run(["git", "-C", str(repo_root)] + _REFRESH,
                       capture_output=True, text=True, env=env)
    except OSError:
        return None
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
    refs = owned_refs(repo_root, env)
    if refs is None:
        unavailable += 1
        refs = "<unavailable>\n"
    parts.append("[refs]\n%s" % refs)
    digest = untracked_digest(repo_root, env)
    if digest is None:
        unavailable += 1
        digest = "<unavailable>\n"
    parts.append("[untracked]\n%s" % digest)
    if unavailable == len(_PROBES) + 2:
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
    parser.add_argument("-j", "--jobs", default="1",
                        help="run the suite across N worker processes, or 'auto' for the CPU "
                             "count (default 1 = one serial run, unchanged behavior)")
    parser.add_argument("--shard", default="1/1",
                        help="run only shard I of N of the discovered tests, formatted I/N "
                             "(used internally by --jobs; each shard gets its own sandbox)")
    parser.add_argument("--sandbox", default=None,
                        help="run a --shard from this existing directory instead of a fresh one "
                             "(used internally by --jobs, so the PARENT owns the leftover check)")
    args = parser.parse_args(argv)

    try:
        index_s, total_s = args.shard.split("/", 1)
        index, total = int(index_s), int(total_s)
    except ValueError:
        print("run_script_tests: --shard must look like I/N, got %r" % args.shard, file=sys.stderr)
        return 2
    try:
        jobs = resolve_jobs(args.jobs)
        compose_shard(index, total, 1, jobs)
    except ValueError as exc:
        print("run_script_tests: %s" % exc, file=sys.stderr)
        return 2

    args.tests_dir = str(Path(args.tests_dir).resolve())
    # Absolute, because a shard chdirs into its sandbox before importing anything: a relative root
    # would then resolve against the wrong directory on sys.path and PYTHONPATH.
    args.repo_root = str(Path(args.repo_root).resolve()) if args.repo_root else ""
    env = clean_git_env()
    repo_root = args.repo_root or None
    if repo_root:
        # The suite used to run WITH the repository root as its cwd, so the root was importable.
        # Keep that true from the sandbox, or a test that imports a top-level package would start
        # failing for a reason that has nothing to do with what it tests.
        inherited = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(repo_root) + (os.pathsep + inherited if inherited else "")
    watched = None if args.no_worktree_check else repo_root

    if jobs > 1:
        before = worktree_state(watched, env)
        rc, leftovers = run_parallel(index, total, jobs, args, env)
        after = worktree_state(watched, env)
        problems = describe_leak(leftovers, before, after)
        for problem in problems:
            print("run_script_tests: %s" % problem, file=sys.stderr)
        if problems:
            print("run_script_tests: %s" % HINT, file=sys.stderr)
            return rc or 1
        return rc

    with contextlib.ExitStack() as stack:
        # A worker of a fan-out runs from the sandbox the PARENT owns and inspects, so a test that
        # ends the process early (os._exit) cannot skip the leftover check. Any other invocation
        # builds and checks its own.
        parent_owned = bool(args.sandbox) and total > 1
        cwd = args.sandbox if parent_owned else stack.enter_context(_sandbox())
        before = worktree_state(watched, env)
        if total > 1:
            # A worker: discover and run in THIS process, from the sandbox. The suite must see the
            # SAME environment the serial path hands its subprocess - git location variables
            # scrubbed (#283), a hermetic git identity, and the repository on PYTHONPATH - which
            # for an in-process run means replacing os.environ, not just passing env along.
            os.environ.clear()
            os.environ.update(env)
            if repo_root and str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            returncode = run_shard(args.tests_dir, args.pattern, index, total, cwd)
        else:
            returncode = subprocess.run(discover_argv(args.tests_dir, args.pattern),
                                        cwd=cwd, env=env).returncode
        after = worktree_state(watched, env)
        leftovers = [] if parent_owned else sandbox_leftovers(cwd)
        problems = describe_leak(leftovers, before, after)
        if problems:
            print("run_script_tests: sandbox: %s" % cwd, file=sys.stderr)

    for problem in problems:
        print("run_script_tests: %s" % problem, file=sys.stderr)
    if problems:
        print("run_script_tests: %s" % HINT, file=sys.stderr)
        return returncode or 1
    return returncode


if __name__ == "__main__":
    sys.exit(main())
