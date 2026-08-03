#!/usr/bin/env python3
"""The scripts suite must leave no scratch behind, and the runner must notice when it does.

Issue #791: the suite used to write `a.md`, `b.md`, `new.md`, and `old.md` into whatever
directory it ran from - the repo root, because that is where `pre-push` runs it - so every push
left the tree dirty and two of those fixtures were swept into `main` by an unrelated PR. The
per-test fix (build fixtures under a temp dir) is only as durable as the next test author's
memory, so `run_script_tests.py` makes the leak IMPOSSIBLE to miss: it runs the suite from a
throwaway working directory and fails if anything is left in it, or if the repository working
tree changed while the suite ran.
"""
import argparse
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_script_tests as rst  # noqa: E402
from _git_test_env import clean_git_env  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent

CLEAN_TEST = """\
import unittest


class Clean(unittest.TestCase):
    def test_writes_nothing(self):
        self.assertTrue(True)
"""

LEAKING_TEST = """\
import unittest


class Leaks(unittest.TestCase):
    def test_writes_a_scratch_file_into_the_cwd(self):
        with open("a.md", "w", encoding="utf-8") as fh:
            fh.write("scratch\\n")
"""

FAILING_TEST = """\
import unittest


class Fails(unittest.TestCase):
    def test_fails(self):
        self.fail("boom")
"""


def _fake_suite(root, name, body):
    (Path(root) / name).write_text(body, encoding="utf-8")


class SandboxLeftovers(unittest.TestCase):
    def test_an_untouched_sandbox_has_no_leftovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(rst.sandbox_leftovers(tmp), [])

    def test_every_stray_path_is_reported_with_forward_slashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("x", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "sub" / "b.txt").write_text("y", encoding="utf-8")
            self.assertEqual(rst.sandbox_leftovers(tmp), ["a.md", "sub", "sub/b.txt"])


class LeakDescription(unittest.TestCase):
    def test_a_clean_run_reports_no_problem(self):
        self.assertEqual(rst.describe_leak([], "", ""), [])

    def test_leftovers_are_named_so_the_offender_is_findable(self):
        problems = rst.describe_leak(["a.md", "old.md"], "", "")
        self.assertEqual(len(problems), 1)
        self.assertIn("a.md", problems[0])
        self.assertIn("old.md", problems[0])

    def test_a_changed_worktree_is_reported(self):
        problems = rst.describe_leak([], "", "?? a.md\n")
        self.assertEqual(len(problems), 1)
        self.assertIn("?? a.md", problems[0])

    def test_a_repository_that_stopped_being_readable_is_a_change(self):
        # Deleting or corrupting `.git` mid-run makes the second probe fail. Treating that as
        # "unknown, so fine" would let the most destructive suite of all pass.
        self.assertEqual(len(rst.describe_leak([], "", None)), 1)
        self.assertEqual(len(rst.describe_leak([], None, "")), 1)

    def test_a_repository_that_was_never_readable_is_not_a_leak(self):
        # git missing, or the runner pointed at a non-repository: nothing to compare.
        self.assertEqual(rst.describe_leak([], None, None), [])

    def test_a_worktree_that_was_already_dirty_is_not_blamed_on_the_suite(self):
        self.assertEqual(rst.describe_leak([], "?? scratch.txt\n", "?? scratch.txt\n"), [])

    def test_a_repository_change_is_told_apart_from_a_file_left_behind(self):
        # Issue #930: the two failures have different causes and different fixes, so the report for
        # a repository change must not read like the scratch-file one - it says what changed, which
        # probe saw it, and never carries the "write scratch under a temp dir" hint.
        problems = rst.describe_leak([], "[status]\n", "[status]\n?? a.md\n")
        self.assertEqual(len(problems), 1)
        self.assertNotIn(rst.HINT, problems[0])
        self.assertIn("changed underneath the run", problems[0])
        self.assertIn("[status]", problems[0])
        self.assertIn("+?? a.md", problems[0])

    def test_a_file_left_behind_still_names_the_scratch_fix(self):
        problems = rst.describe_leak(["a.md"], "", "")
        self.assertIn("working directory", problems[0])


class StateDiff(unittest.TestCase):
    """Two full snapshots are unreadable side by side; only the difference is worth printing."""

    def test_identical_snapshots_differ_in_nothing(self):
        self.assertEqual(rst.state_diff("[status]\nx\n", "[status]\nx\n"), "")

    def test_only_the_probe_that_moved_is_shown(self):
        before = "[status]\n[head]\nabc\n[untracked]\nkeep.md 11\n"
        after = "[status]\n[head]\nabc\n[untracked]\nkeep.md 22\n"
        diff = rst.state_diff(before, after)
        self.assertIn("[untracked]", diff)
        self.assertNotIn("[head]", diff)
        self.assertIn("-keep.md 11", diff)
        self.assertIn("+keep.md 22", diff)

    def test_a_body_line_that_looks_like_a_header_does_not_invent_a_probe(self):
        # `git diff` and the untracked digest carry arbitrary file content and paths, so only the
        # KNOWN probe names may open a section.
        before = "[status]\n[nonsense]\none\n"
        after = "[status]\n[nonsense]\ntwo\n"
        diff = rst.state_diff(before, after)
        self.assertIn("[status]", diff)
        self.assertNotIn("[nonsense]\n+", diff)

    def test_a_huge_difference_is_truncated_rather_than_burying_the_report(self):
        after = "[diff]\n" + "".join("line %d\n" % i for i in range(500))
        diff = rst.state_diff("[diff]\n", after)
        self.assertLess(len(diff.splitlines()), 60)
        self.assertIn("more line", diff)

    def test_an_unreadable_side_is_explained_rather_than_diffed(self):
        self.assertIn("before", rst.state_diff(None, "[status]\n"))
        self.assertIn("after", rst.state_diff("[status]\n", None))


class WorktreeState(unittest.TestCase):
    def test_no_repository_is_unknown_rather_than_clean(self):
        self.assertIsNone(rst.worktree_state(""))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(rst.worktree_state(tmp))

    def test_the_index_is_refreshed_before_the_probes(self):
        # Without this, `git diff HEAD` and `git status` report line-ending noise on one call and
        # nothing on the next (a CRLF working tree against an LF-normalized HEAD), so the runner
        # would fail nondeterministically - and its message would send the author straight to the
        # escape hatch for a change nobody made.
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch.object(rst.subprocess, "run", side_effect=fake_run):
            rst.worktree_state("/repo")
        self.assertTrue(calls, "worktree_state ran no git commands")
        self.assertIn("--refresh", calls[0],
                      "the first git call must refresh the index stat-cache, got %r" % (calls[0],))

    def test_a_crlf_working_tree_snapshots_consistently(self):
        # The condition that made the real runner flake: HEAD is LF-normalized, the working tree
        # holds CRLF, and the index stat-cache goes stale while the (multi-minute) suite runs.
        with tempfile.TemporaryDirectory() as tmp:
            env = clean_git_env()
            if not self._init(tmp, env):
                self.skipTest("git is not available")
            root = Path(tmp)
            (root / ".gitattributes").write_bytes(b"* text=auto eol=lf\n")
            tracked = root / "keep.md"
            tracked.write_bytes(b"one\ntwo\n")
            self._commit(tmp, env, ".", "base")
            tracked.write_bytes(b"one\r\ntwo\r\n")
            first = rst.worktree_state(tmp)
            os.utime(tracked, None)
            self.assertEqual(rst.worktree_state(tmp), first,
                             "an untouched repository snapshotted differently twice")

    def test_a_repository_without_commits_is_still_compared(self):
        # `rev-parse HEAD` fails before the first commit; that must not blank the whole snapshot.
        with tempfile.TemporaryDirectory() as tmp:
            if not self._init(tmp, clean_git_env()):
                self.skipTest("git is not available")
            before = rst.worktree_state(tmp)
            self.assertIsNotNone(before)
            (Path(tmp) / "a.md").write_text("x", encoding="utf-8")
            self.assertNotEqual(rst.worktree_state(tmp), before)

    def test_a_committed_fixture_is_still_a_change(self):
        # `git status --porcelain` alone comes back clean after a commit, so the snapshot has to
        # carry HEAD as well.
        with tempfile.TemporaryDirectory() as tmp:
            env = clean_git_env()
            if not self._init(tmp, env):
                self.skipTest("git is not available")
            (Path(tmp) / "keep.md").write_text("keep\n", encoding="utf-8")
            self._commit(tmp, env, "keep.md", "base")
            before = rst.worktree_state(tmp)
            head_before = self._head(tmp, env)
            (Path(tmp) / "a.md").write_text("x", encoding="utf-8")
            self._commit(tmp, env, "a.md", "stray")
            self.assertNotEqual(self._head(tmp, env), head_before,
                                "the fixture did not actually commit, so this proves nothing")
            self.assertEqual(self._status(tmp, env), "",
                             "the tree is dirty, so status alone would already have caught this")
            self.assertNotEqual(rst.worktree_state(tmp), before)

    def test_rewriting_an_untracked_file_is_a_change(self):
        # Status names an untracked file but not its content, so an overwrite would otherwise be
        # invisible - the untracked digest is what catches it.
        with tempfile.TemporaryDirectory() as tmp:
            env = clean_git_env()
            if not self._init(tmp, env):
                self.skipTest("git is not available")
            scratch = Path(tmp) / "scratch.md"
            scratch.write_text("before\n", encoding="utf-8")
            before = rst.worktree_state(tmp)
            scratch.write_text("after\n", encoding="utf-8")
            self.assertEqual(self._status(tmp, env), "?? scratch.md",
                             "status is unchanged, which is the point of this test")
            self.assertNotEqual(rst.worktree_state(tmp), before)

    def test_rewriting_an_already_dirty_tracked_file_is_a_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = clean_git_env()
            if not self._init(tmp, env):
                self.skipTest("git is not available")
            tracked = Path(tmp) / "keep.md"
            tracked.write_text("one\n", encoding="utf-8")
            self._commit(tmp, env, "keep.md", "base")
            tracked.write_text("two\n", encoding="utf-8")
            before = rst.worktree_state(tmp)
            tracked.write_text("qqq\n", encoding="utf-8")
            self.assertNotEqual(rst.worktree_state(tmp), before)

    def test_detaching_head_at_the_same_commit_is_a_change(self):
        # Status, HEAD, refs, diff, and the untracked digest all stay identical when a suite
        # detaches HEAD or switches to another branch at the same commit, so the checked-out REF
        # has to be part of the snapshot: leaving the developer somewhere else is a real change.
        with tempfile.TemporaryDirectory() as tmp:
            env = clean_git_env()
            if not self._init(tmp, env):
                self.skipTest("git is not available")
            (Path(tmp) / "keep.md").write_bytes(b"keep\n")
            self._commit(tmp, env, "keep.md", "base")
            before = rst.worktree_state(tmp)
            head_before = self._head(tmp, env)
            subprocess.run(["git", "-C", tmp, "checkout", "--detach", "-q"], check=True,
                           capture_output=True, text=True, env=env)
            self.assertEqual(self._head(tmp, env), head_before,
                             "the commit moved, so this would be caught without the ref probe")
            self.assertNotEqual(rst.worktree_state(tmp), before)

    def test_a_sibling_worktrees_commit_is_not_this_worktrees_change(self):
        # Issue #830: every worktree shares one `.git` refs store, so an unrelated agent committing
        # in ITS worktree moved a ref this checkout never touched and failed the run. Nothing leaked
        # here, so the snapshot must be identical - including when the sibling leaves a PER-worktree
        # ref (`refs/bisect/*`) behind, which is the sibling's business and not this checkout's.
        with tempfile.TemporaryDirectory() as tmp:
            env = clean_git_env()
            root = Path(tmp) / "main"
            root.mkdir()
            if not self._init(root, env):
                self.skipTest("git is not available")
            (root / "keep.md").write_bytes(b"keep\n")
            self._commit(root, env, "keep.md", "base")
            sibling = Path(tmp) / "sibling"
            added = subprocess.run(["git", "-C", str(root), "worktree", "add", "-q",
                                    "-b", "sibling", str(sibling)],
                                   capture_output=True, text=True, env=env)
            self.assertEqual(added.returncode, 0, added.stderr)
            before = rst.worktree_state(root)
            (sibling / "theirs.md").write_bytes(b"theirs\n")
            self._commit(sibling, env, "theirs.md", "sibling work")
            subprocess.run(["git", "-C", str(sibling), "update-ref", "refs/bisect/bad",
                            self._ref(sibling, env, "HEAD")],
                           check=True, capture_output=True, text=True, env=env)
            self.assertNotEqual(self._ref(root, env, "refs/heads/sibling"),
                                self._ref(root, env, "refs/heads/main"),
                                "the sibling did not actually commit, so this proves nothing")
            self.assertEqual(rst.worktree_state(root), before,
                             "a sibling worktree's commit was blamed on this worktree")

    def test_a_fetch_moving_a_remote_tracking_ref_is_not_a_change(self):
        # The other half of #830: any concurrent `git fetch` rewrites `refs/remotes/*` in the shared
        # store, which this worktree neither caused nor leaked.
        with tempfile.TemporaryDirectory() as tmp:
            env = clean_git_env()
            if not self._init(tmp, env):
                self.skipTest("git is not available")
            (Path(tmp) / "keep.md").write_bytes(b"keep\n")
            self._commit(tmp, env, "keep.md", "base")
            before = rst.worktree_state(tmp)
            subprocess.run(["git", "-C", tmp, "update-ref", "refs/remotes/origin/main",
                            self._head(tmp, env)], check=True, capture_output=True, text=True,
                           env=env)
            self.assertEqual(rst.worktree_state(tmp), before,
                             "a remote-tracking ref update was blamed on this worktree")

    def test_a_left_behind_bisect_is_still_a_change(self):
        # Per-worktree refs are NOT shared, so they stay in the snapshot: a suite that leaves a
        # bisect (or a rebase) running in the repository is a leak nothing else here notices.
        with tempfile.TemporaryDirectory() as tmp:
            env = clean_git_env()
            if not self._init(tmp, env):
                self.skipTest("git is not available")
            (Path(tmp) / "keep.md").write_bytes(b"keep\n")
            self._commit(tmp, env, "keep.md", "base")
            before = rst.worktree_state(tmp)
            subprocess.run(["git", "-C", tmp, "update-ref", "refs/bisect/bad", self._head(tmp, env)],
                           check=True, capture_output=True, text=True, env=env)
            self.assertEqual(self._status(tmp, env), "",
                             "the tree is dirty, so status alone would already have caught this")
            self.assertNotEqual(rst.worktree_state(tmp), before)

    def _init(self, root, env):
        try:
            proc = subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"],
                                  capture_output=True, text=True, env=env)
        except OSError:
            return False
        return proc.returncode == 0

    def _ref(self, root, env, name):
        return subprocess.run(["git", "-C", str(root), "rev-parse", name],
                              capture_output=True, text=True, env=env).stdout.strip()

    def _commit(self, root, env, path, message):
        for args in (["add", path], ["commit", "-qm", message]):
            subprocess.run(["git", "-C", str(root)] + args, check=True,
                           capture_output=True, text=True, env=env)

    def _head(self, root, env):
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, env=env).stdout.strip()

    def _status(self, root, env):
        return subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                              capture_output=True, text=True, env=env).stdout.strip()


class DiscoverArgv(unittest.TestCase):
    def test_the_suite_is_discovered_from_the_tests_directory_itself(self):
        argv = rst.discover_argv("/repo/scripts", "test_*.py", python="py")
        self.assertEqual(argv[:4], ["py", "-m", "unittest", "discover"])
        # `-t` pins the import root, so discovery does not depend on the (sandbox) cwd.
        self.assertIn("-t", argv)
        self.assertEqual(argv[argv.index("-t") + 1], "/repo/scripts")
        self.assertEqual(argv[argv.index("-s") + 1], "/repo/scripts")
        self.assertEqual(argv[argv.index("-p") + 1], "test_*.py")


class ShardSelection(unittest.TestCase):
    """The stride partition: every test runs in exactly one shard, or the run is not equivalent."""

    def test_the_shards_are_an_exact_partition(self):
        items = list(range(23))
        for total in (1, 2, 3, 5, 16, 32):
            collected = [x for i in range(1, total + 1)
                         for x in rst.select_shard(items, i, total)]
            self.assertEqual(len(collected), len(items),
                             "shards of %d dropped or duplicated an item" % total)
            self.assertEqual(sorted(collected), items)

    def test_neighbouring_items_land_in_different_shards(self):
        # Round-robin, not contiguous slicing: files discovered next to each other tend to cost
        # the same, so striding spreads the expensive neighbours across workers.
        self.assertEqual(rst.select_shard(list(range(6)), 1, 3), [0, 3])

    def test_more_shards_than_items_leaves_empty_shards_rather_than_failing(self):
        self.assertEqual(rst.select_shard([1, 2], 3, 4), [])

    def test_an_out_of_range_shard_is_rejected(self):
        for index, total in ((0, 1), (2, 1), (1, 0), (-1, 3)):
            with self.assertRaises(ValueError):
                rst.select_shard([1, 2, 3], index, total)


class ComposedShards(unittest.TestCase):
    def test_workers_partition_the_shard_they_were_given(self):
        items = list(range(37))
        for total in (1, 3):
            for index in range(1, total + 1):
                mine = rst.select_shard(items, index, total)
                for jobs in (1, 2, 4, 7):
                    collected = []
                    for job in range(1, jobs + 1):
                        i, t = rst.compose_shard(index, total, job, jobs)
                        collected += rst.select_shard(items, i, t)
                    self.assertEqual(sorted(collected), sorted(mine),
                                     "%d job(s) of shard %d/%d is not a partition"
                                     % (jobs, index, total))

    def test_a_bad_job_index_is_rejected(self):
        for job, jobs in ((0, 1), (2, 1), (1, 0)):
            with self.assertRaises(ValueError):
                rst.compose_shard(1, 1, job, jobs)


class JobResolution(unittest.TestCase):
    def test_auto_is_the_cpu_count(self):
        self.assertEqual(rst.resolve_jobs("auto"), os.cpu_count() or 1)

    def test_an_explicit_count_is_taken_as_is(self):
        self.assertEqual(rst.resolve_jobs("3"), 3)

    def test_a_meaningless_count_is_rejected(self):
        for spec in ("0", "-2", "many", ""):
            with self.assertRaises(ValueError):
                rst.resolve_jobs(spec)


class WorkerArgv(unittest.TestCase):
    def _args(self, **over):
        base = dict(tests_dir="/repo/scripts", pattern="test_*.py", repo_root="/repo",
                    no_worktree_check=False, shard="1/1", jobs="4", sandbox=None,
                    coverage_token="")
        base.update(over)
        return argparse.Namespace(**base)

    def test_a_worker_can_never_recurse_into_another_fan_out(self):
        argv = rst.build_child_argv(1, 1, 3, 4, self._args(), python="py")
        self.assertNotIn("--jobs", argv)
        self.assertNotIn("-j", argv)

    def test_a_worker_runs_its_own_composed_shard(self):
        argv = rst.build_child_argv(1, 1, 3, 4, self._args(), python="py")
        self.assertEqual(argv[argv.index("--shard") + 1], "3/4")

    def test_a_worker_leaves_the_repository_check_to_the_parent(self):
        # The parent snapshots the repository ONCE around the whole fan-out; letting every worker
        # snapshot it too would only race their own `git update-index` calls.
        argv = rst.build_child_argv(1, 1, 1, 2, self._args(), python="py")
        self.assertIn("--no-worktree-check", argv)

    def test_a_worker_is_given_the_sandbox_the_parent_owns(self):
        # The parent creates and INSPECTS the sandbox, so a test that ends the worker early
        # (os._exit) cannot skip the leftover check.
        argv = rst.build_child_argv(1, 1, 1, 2, self._args(), sandbox="/tmp/box", python="py")
        self.assertEqual(argv[argv.index("--sandbox") + 1], "/tmp/box")

    def test_a_worker_is_told_which_fan_out_it_belongs_to(self):
        argv = rst.build_child_argv(1, 1, 1, 2, self._args(), token="run42", python="py")
        self.assertEqual(argv[argv.index("--coverage-token") + 1], "run42")

    def test_a_worker_inherits_the_suite_selection(self):
        argv = rst.build_child_argv(1, 1, 1, 2,
                                    self._args(pattern="test_check_*.py"), python="py")
        self.assertEqual(argv[argv.index("--tests-dir") + 1], "/repo/scripts")
        self.assertEqual(argv[argv.index("--pattern") + 1], "test_check_*.py")
        self.assertEqual(argv[argv.index("--repo-root") + 1], "/repo")


class DuplicateTests(unittest.TestCase):
    """A compatibility module that re-exports another's cases must not run them twice."""

    class Sample(unittest.TestCase):
        def test_one(self):
            pass

        def test_two(self):
            pass

    def _suite(self):
        loader = unittest.TestLoader()
        return loader.loadTestsFromTestCase(DuplicateTests.Sample)

    def test_the_same_test_is_kept_once(self):
        both = list(rst.iter_tests(self._suite())) + list(rst.iter_tests(self._suite()))
        self.assertEqual(len(both), 4)
        unique = rst.dedupe_tests(both)
        self.assertEqual([t.id() for t in unique], [t.id() for t in rst.iter_tests(self._suite())])

    def test_order_is_preserved(self):
        tests = list(rst.iter_tests(self._suite()))
        self.assertEqual([t.id() for t in rst.dedupe_tests(tests)], [t.id() for t in tests])


class CoverageCrossCheck(unittest.TestCase):
    """Each worker discovers independently, so the parent must confirm they saw the same suite."""

    def _report(self, index, total, digest, ran, discovered, token="tok"):
        return ("noise\n" + (rst.COVERAGE % (index, total, token, digest, ran, discovered))
                + "\nmore\n")

    def test_a_complete_partition_is_accepted(self):
        outputs = [self._report(1, 2, "abc123", 5, 10), self._report(2, 2, "abc123", 5, 10)]
        self.assertEqual(rst.check_coverage(outputs, token="tok"), [])

    def test_a_worker_that_discovered_a_different_suite_reds_the_run(self):
        # An import error collapses a module into one _FailedTest, so that worker strides a
        # DIFFERENT population and the union of shards is no longer the suite. A digest, not a
        # count: two workers can see the same NUMBER of tests and still not the same tests.
        outputs = [self._report(1, 2, "abc123", 5, 10), self._report(2, 2, "def456", 5, 10)]
        problems = rst.check_coverage(outputs, token="tok")
        self.assertEqual(len(problems), 1)
        self.assertIn("did not all discover the same suite", problems[0])

    def test_shards_that_do_not_add_up_red_the_run(self):
        outputs = [self._report(1, 2, "abc123", 5, 10), self._report(2, 2, "abc123", 4, 10)]
        problems = rst.check_coverage(outputs, token="tok")
        self.assertEqual(len(problems), 1)
        self.assertIn("9", problems[0])

    def test_a_silent_worker_reds_the_run(self):
        problems = rst.check_coverage([self._report(1, 2, "abc123", 5, 10), "nothing to see"],
                                      token="tok")
        self.assertTrue(problems)

    def test_a_worker_that_reports_twice_reds_the_run(self):
        # A worker that somehow ran twice must not let the parent pick whichever line it likes.
        doubled = self._report(1, 2, "abc123", 5, 10) + self._report(1, 2, "abc123", 5, 10)
        self.assertTrue(rst.check_coverage([doubled, self._report(2, 2, "abc123", 5, 10)],
                                           token="tok"))

    def test_a_nested_runs_report_is_ignored(self):
        # This runner's own tests RUN the runner, so a worker replays nested markers. Only the
        # markers carrying this fan-out's token count.
        nested = self._report(1, 3, "999999", 7, 21, token="other")
        outputs = [nested + self._report(1, 2, "abc123", 5, 10),
                   self._report(2, 2, "abc123", 5, 10) + nested]
        self.assertEqual(rst.check_coverage(outputs, token="tok"), [])

    def test_the_parents_own_shard_is_what_must_be_covered(self):
        # With --shard I/N AND --jobs, the workers cover only the parent's slice of the population,
        # so comparing their sum against the WHOLE population would fail every such run.
        outputs = [self._report(1, 6, "abc123", 2, 9), self._report(4, 6, "abc123", 1, 9)]
        self.assertEqual(rst.check_coverage(outputs, index=1, total=3, token="tok"), [])
        self.assertTrue(rst.check_coverage(outputs, index=1, total=1, token="tok"))

    def test_no_output_at_all_reds_the_run(self):
        self.assertTrue(rst.check_coverage([], token="tok"))

    def test_the_digest_follows_the_tests_and_their_order(self):
        class Sample(unittest.TestCase):
            def test_a(self):
                pass

            def test_b(self):
                pass

        tests = list(rst.iter_tests(unittest.TestLoader().loadTestsFromTestCase(Sample)))
        self.assertEqual(rst.population_digest(tests), rst.population_digest(list(tests)))
        self.assertNotEqual(rst.population_digest(tests),
                            rst.population_digest(list(reversed(tests))))
        self.assertNotEqual(rst.population_digest(tests), rst.population_digest(tests[:1]))


class ParallelAggregation(unittest.TestCase):
    """Fail CLOSED: only a complete set of exit-0 workers is a pass."""

    def _ok(self):
        return subprocess.CompletedProcess(["py"], 0, "ok\n", "")

    def _bad(self, code=1):
        return subprocess.CompletedProcess(["py"], code, "", "boom\n")

    def test_every_worker_succeeding_passes(self):
        rc, errors = rst.aggregate_results([self._ok(), self._ok()])
        self.assertEqual((rc, errors), (0, []))

    def test_a_failing_worker_reds_the_run(self):
        rc, errors = rst.aggregate_results([self._ok(), self._bad(2)])
        self.assertNotEqual(rc, 0)
        self.assertEqual(len(errors), 1)
        self.assertIn("2", errors[0])

    def test_a_worker_that_could_not_be_launched_reds_the_run(self):
        rc, errors = rst.aggregate_results([self._ok(), OSError("no python")])
        self.assertNotEqual(rc, 0)
        self.assertIn("no python", errors[0])

    def test_no_workers_at_all_reds_the_run(self):
        # A fan-out that launched nothing must never look like a clean suite.
        rc, errors = rst.aggregate_results([])
        self.assertNotEqual(rc, 0)
        self.assertTrue(errors)


class RunnerEndToEnd(unittest.TestCase):
    """Drive the real runner against throwaway suites; it is the gate, so it must actually gate."""

    def _run(self, tests_dir, repo_root="", extra=()):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "run_script_tests.py"),
             "--tests-dir", str(tests_dir), "--repo-root", str(repo_root)] + list(extra),
            capture_output=True, text=True, env=clean_git_env())
        return proc

    def _repo_and_dirtying_suite(self, tmp):
        """A throwaway git repo plus a suite whose test writes an ABSOLUTE path into it.

        The sandbox cwd cannot catch that one, which is why the runner also diffs the worktree."""
        repo = Path(tmp) / "repo"
        repo.mkdir()
        init = subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"],
                              capture_output=True, text=True, env=clean_git_env())
        if init.returncode != 0:
            self.skipTest("git is not available")
        tests = Path(tmp) / "suite"
        tests.mkdir()
        _fake_suite(tests, "test_dirty.py",
                    "import unittest\nfrom pathlib import Path\n\n\n"
                    "class Dirty(unittest.TestCase):\n"
                    "    def test_writes_into_the_repo(self):\n"
                    "        Path(%r).write_text('x', encoding='utf-8')\n" % str(repo / "a.md"))
        return repo, tests

    def test_a_clean_suite_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_suite(tmp, "test_clean.py", CLEAN_TEST)
            proc = self._run(tmp)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])

    def test_a_suite_that_writes_into_its_cwd_fails_and_names_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_suite(tmp, "test_leak.py", LEAKING_TEST)
            proc = self._run(tmp)
            self.assertEqual(proc.returncode, 1, proc.stdout[-2000:] + proc.stderr[-2000:])
            self.assertIn("a.md", proc.stderr)

    def test_a_failing_suite_still_fails(self):
        # The guard must not swallow the suite's own verdict.
        with tempfile.TemporaryDirectory() as tmp:
            _fake_suite(tmp, "test_fail.py", FAILING_TEST)
            self.assertNotEqual(self._run(tmp).returncode, 0)

    def test_a_suite_that_dirties_the_repository_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, tests = self._repo_and_dirtying_suite(tmp)
            proc = self._run(tests, repo_root=repo)
            self.assertEqual(proc.returncode, 1, proc.stdout[-2000:] + proc.stderr[-2000:])
            self.assertIn("a.md", proc.stderr)

    def test_a_repository_change_is_not_reported_as_a_scratch_file(self):
        # Issue #930: the sandbox was clean here, so the scratch-file hint is the wrong diagnosis -
        # it sent a reader hunting for a stray relative write that does not exist. The report must
        # name the probe that moved instead.
        with tempfile.TemporaryDirectory() as tmp:
            repo, tests = self._repo_and_dirtying_suite(tmp)
            proc = self._run(tests, repo_root=repo)
            self.assertEqual(proc.returncode, 1, proc.stdout[-2000:] + proc.stderr[-2000:])
            self.assertNotIn(rst.HINT, proc.stderr)
            self.assertIn("changed underneath the run", proc.stderr)
            self.assertIn("[status]", proc.stderr)

    def test_a_file_left_in_the_sandbox_still_gets_the_scratch_hint(self):
        # The other side of the same coin: when the suite DID leave a relative write behind, the
        # hint that names the fix is exactly what the reader needs.
        with tempfile.TemporaryDirectory() as tmp:
            _fake_suite(tmp, "test_leak.py", LEAKING_TEST)
            proc = self._run(tmp)
            self.assertEqual(proc.returncode, 1, proc.stdout[-2000:] + proc.stderr[-2000:])
            self.assertIn(rst.HINT, proc.stderr)

    def test_a_ref_moving_mid_run_leaves_the_run_green(self):
        # Issue #930/#830 end to end: another agent's worktree commits on its own branch and a
        # `git fetch` refreshes `refs/remotes/*` WHILE the suite runs. The shared `.git` store moves,
        # this checkout does not, so the run must pass.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            env = clean_git_env()
            init = subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"],
                                  capture_output=True, text=True, env=env)
            if init.returncode != 0:
                self.skipTest("git is not available")
            (repo / "keep.md").write_bytes(b"keep\n")
            for args in (["add", "keep.md"], ["commit", "-qm", "base"]):
                subprocess.run(["git", "-C", str(repo)] + args, check=True,
                               capture_output=True, text=True, env=env)
            head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, env=env).stdout.strip()
            tests = Path(tmp) / "suite"
            tests.mkdir()
            _fake_suite(tests, "test_moves_a_ref.py",
                        "import subprocess\nimport unittest\n\n\n"
                        "class MovesARef(unittest.TestCase):\n"
                        "    def test_a_sibling_moves_a_shared_ref(self):\n"
                        "        for ref in ('refs/heads/sibling', 'refs/remotes/origin/main'):\n"
                        "            proc = subprocess.run(['git', '-C', %r, 'update-ref', ref, %r],\n"
                        "                                  capture_output=True, text=True)\n"
                        "            self.assertEqual(proc.returncode, 0, proc.stderr)\n"
                        % (str(repo), head))
            proc = self._run(tests, repo_root=repo)
            self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])

    def test_the_worktree_check_can_be_opted_out_of(self):
        # A long local run while the tree is being edited would otherwise fail on the edits rather
        # than on a leak; the sandbox check (the primary guard) still applies.
        with tempfile.TemporaryDirectory() as tmp:
            repo, tests = self._repo_and_dirtying_suite(tmp)
            proc = self._run(tests, repo_root=repo, extra=["--no-worktree-check"])
            self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])

    def test_the_sandbox_is_removed_afterwards(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_suite(tmp, "test_leak.py", LEAKING_TEST)
            proc = self._run(tmp)
            leaked = [line for line in proc.stderr.splitlines() if "sandbox:" in line]
            self.assertTrue(leaked, "the runner did not report where it ran: %r" % proc.stderr)
            sandbox = leaked[0].split("sandbox:", 1)[1].strip()
            self.assertFalse(os.path.exists(sandbox),
                             "the runner left its own sandbox behind: %s" % sandbox)


#: A test that records every execution of itself as a uniquely named file, so a suite run across
#: several workers can be checked for a test that ran twice as well as one that never ran.
MARKED_TEST = """\
import tempfile
import unittest


class Marked%(n)d(unittest.TestCase):
%(bodies)s
"""

MARKED_BODY = """\
    def test_%(k)d(self):
        tempfile.mkstemp(prefix="marked%(n)d-%(k)d-", dir=%(marker)r)
"""


class ParallelRunnerEndToEnd(unittest.TestCase):
    """`--jobs` must give the same verdict as a serial run, and keep every guard."""

    def _run(self, tests_dir, repo_root="", jobs="4", extra=()):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "run_script_tests.py"),
             "--tests-dir", str(tests_dir), "--repo-root", str(repo_root),
             "--jobs", jobs] + list(extra),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=clean_git_env())

    def _marked_suite(self, tests, marker, modules=5, per_module=3):
        """`modules` fake test modules of `per_module` tests each, all marking `marker`."""
        for n in range(modules):
            bodies = "".join(MARKED_BODY % {"k": k, "n": n, "marker": str(marker)}
                             for k in range(per_module))
            _fake_suite(tests, "test_marked%d.py" % n,
                        MARKED_TEST % {"n": n, "bodies": bodies})

    def test_a_clean_suite_passes_in_parallel(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_suite(tmp, "test_clean.py", CLEAN_TEST)
            proc = self._run(tmp)
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-3000:])

    def test_every_test_runs_exactly_once_across_the_workers(self):
        # The whole point of the fan-out: a partition, not a sample and not a re-run.
        with tempfile.TemporaryDirectory() as tmp:
            tests, marker = Path(tmp) / "suite", Path(tmp) / "marks"
            tests.mkdir()
            marker.mkdir()
            self._marked_suite(tests, marker)
            proc = self._run(tests, jobs="4")
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-3000:])
            ran = sorted(p.name.rsplit("-", 1)[0] for p in marker.iterdir())
            expected = sorted("marked%d-%d" % (n, k) for n in range(5) for k in range(3))
            self.assertEqual(ran, expected,
                             "the workers did not run each test exactly once")

    def test_a_failing_test_in_any_worker_reds_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_suite(tmp, "test_clean.py", CLEAN_TEST)
            _fake_suite(tmp, "test_fail.py", FAILING_TEST)
            self.assertNotEqual(self._run(tmp).returncode, 0)

    def test_a_worker_that_leaks_into_its_sandbox_is_caught(self):
        # Each worker gets its OWN throwaway cwd, so the #791 guard survives the fan-out.
        with tempfile.TemporaryDirectory() as tmp:
            _fake_suite(tmp, "test_clean.py", CLEAN_TEST)
            _fake_suite(tmp, "test_leak.py", LEAKING_TEST)
            proc = self._run(tmp)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("a.md", proc.stderr)

    def test_a_suite_that_dirties_the_repository_still_fails(self):
        # The repository snapshot is taken once around the whole fan-out, not per worker.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            init = subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"],
                                  capture_output=True, text=True, env=clean_git_env())
            if init.returncode != 0:
                self.skipTest("git is not available")
            tests = Path(tmp) / "suite"
            tests.mkdir()
            _fake_suite(tests, "test_clean.py", CLEAN_TEST)
            _fake_suite(tests, "test_dirty.py",
                        "import unittest\nfrom pathlib import Path\n\n\n"
                        "class Dirty(unittest.TestCase):\n"
                        "    def test_writes_into_the_repo(self):\n"
                        "        Path(%r).write_text('x', encoding='utf-8')\n"
                        % str(repo / "a.md"))
            proc = self._run(tests, repo_root=repo)
            self.assertEqual(proc.returncode, 1, proc.stdout[-3000:] + proc.stderr[-3000:])
            self.assertIn("a.md", proc.stderr)

    def test_discovering_nothing_fails_closed(self):
        # A fan-out that ran zero tests must not look like a clean suite; serially an empty
        # discovery is a visible "Ran 0 tests", but N silent workers are not.
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run(tmp)
            self.assertNotEqual(proc.returncode, 0,
                                proc.stdout[-3000:] + proc.stderr[-3000:])

    def test_a_shard_runs_only_its_own_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests, marker = Path(tmp) / "suite", Path(tmp) / "marks"
            tests.mkdir()
            marker.mkdir()
            self._marked_suite(tests, marker, modules=2, per_module=2)
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "run_script_tests.py"),
                 "--tests-dir", str(tests), "--repo-root", "", "--shard", "1/2"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env=clean_git_env())
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-3000:])
            self.assertEqual(len(list(marker.iterdir())), 2,
                             "shard 1/2 of 4 tests should have run 2 of them")

    def test_the_same_tests_run_serially_and_in_parallel(self):
        # Two execution engines (a `unittest discover` subprocess serially, an in-process
        # TextTestRunner per worker) must not drift apart in what they select. Each engine gets its
        # OWN suite directory: rewriting one set of modules in place can hand the second run a
        # stale `__pycache__` entry (same size, same mtime second) and it silently re-executes the
        # first run's code.
        with tempfile.TemporaryDirectory() as tmp:
            ran = {}
            for name, jobs in (("serial", "1"), ("parallel", "3")):
                tests, marker = Path(tmp) / ("suite-" + name), Path(tmp) / ("marks-" + name)
                tests.mkdir()
                marker.mkdir()
                self._marked_suite(tests, marker, modules=3, per_module=2)
                proc = self._run(tests, jobs=jobs)
                self.assertEqual(proc.returncode, 0,
                                 proc.stdout[-3000:] + proc.stderr[-3000:])
                ran[name] = sorted(p.name.rsplit("-", 1)[0] for p in marker.iterdir())
            self.assertTrue(ran["serial"], "the serial run executed nothing, so this proves nothing")
            self.assertEqual(ran["parallel"], ran["serial"])

    def test_a_test_exported_twice_still_runs_once(self):
        # `test_build_site_data.py` star-imports the split modules, so discovery yields each of
        # their tests twice; across workers the copies could otherwise run CONCURRENTLY.
        with tempfile.TemporaryDirectory() as tmp:
            tests, marker = Path(tmp) / "suite", Path(tmp) / "marks"
            tests.mkdir()
            marker.mkdir()
            self._marked_suite(tests, marker, modules=1, per_module=3)
            _fake_suite(tests, "test_aggregator.py", "from test_marked0 import *  # noqa: F401,F403\n")
            proc = self._run(tests, jobs="3")
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-3000:])
            self.assertEqual(len(list(marker.iterdir())), 3,
                             "the re-exported tests ran more than once")

    def test_a_worker_that_exits_early_cannot_skip_the_leak_check(self):
        # The sandbox belongs to the PARENT, so a test that calls os._exit(0) after writing into
        # the cwd still reds the run.
        with tempfile.TemporaryDirectory() as tmp:
            _fake_suite(tmp, "test_clean.py", CLEAN_TEST)
            _fake_suite(tmp, "test_sneaky.py",
                        "import os\nimport unittest\n\n\n"
                        "class Sneaky(unittest.TestCase):\n"
                        "    def test_writes_then_exits(self):\n"
                        "        with open('a.md', 'w', encoding='utf-8') as fh:\n"
                        "            fh.write('scratch')\n"
                        "        os._exit(0)\n")
            proc = self._run(tmp, jobs="2")
            self.assertNotEqual(proc.returncode, 0,
                                proc.stdout[-3000:] + proc.stderr[-3000:])
            self.assertIn("a.md", proc.stderr)

    def test_a_class_that_skips_itself_does_not_look_like_missing_coverage(self):
        # `raise SkipTest` in setUpClass makes unittest report ONE skip and never start the class's
        # tests, so counting executed tests would red a run that legitimately passed.
        with tempfile.TemporaryDirectory() as tmp:
            _fake_suite(tmp, "test_clean.py", CLEAN_TEST)
            _fake_suite(tmp, "test_skipped.py",
                        "import unittest\n\n\n"
                        "class Skips(unittest.TestCase):\n"
                        "    @classmethod\n"
                        "    def setUpClass(cls):\n"
                        "        raise unittest.SkipTest('nothing to test here')\n\n"
                        "    def test_one(self):\n        pass\n\n"
                        "    def test_two(self):\n        pass\n")
            proc = self._run(tmp, jobs="2")
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-3000:])

    def test_a_shard_of_the_suite_can_itself_be_fanned_out(self):
        # --shard I/N composed with --jobs must stay a partition of the PARENT's shard.
        with tempfile.TemporaryDirectory() as tmp:
            tests, marker = Path(tmp) / "suite", Path(tmp) / "marks"
            tests.mkdir()
            marker.mkdir()
            self._marked_suite(tests, marker, modules=3, per_module=2)
            proc = self._run(tests, jobs="2", extra=["--shard", "1/3"])
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-3000:])
            self.assertEqual(len(list(marker.iterdir())), 2,
                             "shard 1/3 of 6 tests should have run 2 of them")

    def test_a_test_that_itself_runs_a_fan_out_does_not_break_the_coverage_check(self):
        # This runner's own suite runs the runner, so a worker replays a nested run's coverage
        # markers into its own output. CI caught exactly that: the worker looked like it had
        # reported five times.
        with tempfile.TemporaryDirectory() as tmp:
            inner = Path(tmp) / "inner"
            inner.mkdir()
            _fake_suite(inner, "test_inner.py", CLEAN_TEST)
            outer = Path(tmp) / "outer"
            outer.mkdir()
            _fake_suite(outer, "test_clean.py", CLEAN_TEST)
            _fake_suite(outer, "test_nested.py",
                        "import subprocess\nimport sys\nimport unittest\n\n\n"
                        "class Nested(unittest.TestCase):\n"
                        "    def test_runs_the_runner(self):\n"
                        "        proc = subprocess.run([sys.executable, %r, '--tests-dir', %r,\n"
                        "                               '--repo-root', '', '--jobs', '2'],\n"
                        "                              capture_output=True, text=True)\n"
                        "        print(proc.stdout)\n"
                        "        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)\n"
                        % (str(SCRIPTS / "run_script_tests.py"), str(inner)))
            proc = self._run(outer, jobs="2")
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-3000:])

    def test_a_worker_runs_with_the_git_environment_scrubbed(self):
        # In-process shards must see the same scrubbed environment the serial subprocess gets, or
        # a git-spawning test under a hook targets the REAL repository (#283).
        with tempfile.TemporaryDirectory() as tmp:
            _fake_suite(tmp, "test_env.py",
                        "import os\nimport unittest\n\n\n"
                        "class Env(unittest.TestCase):\n"
                        "    def test_git_dir_is_gone(self):\n"
                        "        self.assertIsNone(os.environ.get('GIT_DIR'))\n"
                        "    def test_identity_is_set(self):\n"
                        "        self.assertTrue(os.environ.get('GIT_AUTHOR_NAME'))\n")
            env = clean_git_env()
            env["GIT_DIR"] = str(Path(tmp) / "not-a-repo")
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "run_script_tests.py"),
                 "--tests-dir", tmp, "--repo-root", "", "--shard", "1/2"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-3000:])

    def test_the_coverage_check_is_actually_wired_into_the_run(self):
        # CoverageCrossCheck proves the function; this proves the parent CALLS it, so deleting the
        # call site cannot leave the suite green.
        with tempfile.TemporaryDirectory() as tmp:
            _fake_suite(tmp, "test_clean.py", CLEAN_TEST)
            argv = ["--tests-dir", tmp, "--repo-root", "", "--jobs", "2"]
            self.assertEqual(rst.main(argv), 0)
            with mock.patch.object(rst, "check_coverage", return_value=["fabricated problem"]):
                self.assertNotEqual(rst.main(argv), 0)

    def test_a_sandbox_outside_a_fan_out_is_refused(self):
        # The internal --sandbox flag has one legal shape; anywhere else it would point the suite
        # at a directory nobody inspects afterwards.
        with tempfile.TemporaryDirectory() as tmp:
            _fake_suite(tmp, "test_clean.py", CLEAN_TEST)
            box = Path(tmp) / "box"
            box.mkdir()
            for extra in (["--sandbox", str(box)],
                          ["--sandbox", str(box), "--shard", "1/2", "--jobs", "2"],
                          ["--sandbox", str(box / "missing"), "--shard", "1/2"]):
                proc = subprocess.run(
                    [sys.executable, str(SCRIPTS / "run_script_tests.py"),
                     "--tests-dir", tmp, "--repo-root", ""] + extra,
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    env=clean_git_env())
                self.assertEqual(proc.returncode, 2, "%r was accepted: %s" % (extra, proc.stderr))


if __name__ == "__main__":
    unittest.main()
