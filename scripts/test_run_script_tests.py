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
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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


class WorktreeState(unittest.TestCase):
    def test_no_repository_is_unknown_rather_than_clean(self):
        self.assertIsNone(rst.worktree_state(""))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(rst.worktree_state(tmp))

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

    def _init(self, root, env):
        proc = subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"],
                              capture_output=True, text=True, env=env)
        return proc.returncode == 0

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


if __name__ == "__main__":
    unittest.main()
