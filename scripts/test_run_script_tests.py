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

    def test_an_unavailable_worktree_state_is_not_a_leak(self):
        # `git` missing, or the runner pointed at a non-repository: unknown is not "changed".
        self.assertEqual(rst.describe_leak([], None, None), [])
        self.assertEqual(rst.describe_leak([], "", None), [])

    def test_a_worktree_that_was_already_dirty_is_not_blamed_on_the_suite(self):
        self.assertEqual(rst.describe_leak([], "?? scratch.txt\n", "?? scratch.txt\n"), [])


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
