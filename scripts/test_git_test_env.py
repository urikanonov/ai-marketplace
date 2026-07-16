"""Regression test for issue #283: git-spawning tests must scrub inherited git
location variables so they never operate on the real repo/branch.

Runs under `python -m unittest discover -s scripts -p "test_*.py"` (the pre-push hook
and the required `validate` job), which is exactly the context where git exports
`GIT_DIR` and friends into the environment.
"""
import os
import subprocess
import tempfile
import unittest

from _git_test_env import clean_git_env


def _git(args, cwd, env):
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env,
        capture_output=True, text=True, check=True,
    )


def _make_repo_with_commit(root, env):
    with open(os.path.join(root, "seed.txt"), "w", encoding="utf-8") as fh:
        fh.write("seed\n")
    _git(["init", "-q"], root, env)
    _git(["add", "-A"], root, env)
    _git(["commit", "-qm", "seed"], root, env)
    return _git(["rev-parse", "HEAD"], root, env).stdout.strip()


class CleanGitEnvTests(unittest.TestCase):
    def setUp(self):
        try:
            subprocess.run(["git", "--version"], capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            self.skipTest("git not available")

    def test_scrubs_location_vars(self):
        polluted = dict(
            os.environ,
            GIT_DIR="/real/.git",
            GIT_WORK_TREE="/real",
            GIT_INDEX_FILE="/real/.git/index",
            GIT_PREFIX="sub/",
            GIT_COMMON_DIR="/real/.git",
            GIT_OBJECT_DIRECTORY="/real/.git/objects",
        )
        env = clean_git_env(polluted)
        for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX",
                    "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY"):
            self.assertNotIn(var, env)
        # A hermetic identity is supplied so temp-repo commits succeed without git config.
        self.assertEqual(env["GIT_AUTHOR_EMAIL"], "test@example.com")

    def test_temp_repo_git_does_not_touch_inherited_repo(self):
        # Reproduce #283: with GIT_DIR (and friends) pointed at a REAL repo - exactly what
        # the pre-push hook exports - a git init/add/commit in a temp dir must land in the
        # temp repo, leaving the real repo's branch untouched.
        with tempfile.TemporaryDirectory() as real, tempfile.TemporaryDirectory() as work:
            base = clean_git_env()
            real_head = _make_repo_with_commit(real, base)

            # Simulate the inherited pre-push environment that points every git call at
            # the real repo.
            inherited = dict(
                os.environ,
                GIT_DIR=os.path.join(real, ".git"),
                GIT_WORK_TREE=real,
                GIT_INDEX_FILE=os.path.join(real, ".git", "index"),
            )

            # The scrubbed env is what a correct git-spawning test uses.
            safe = clean_git_env(inherited)
            with open(os.path.join(work, "work.txt"), "w", encoding="utf-8") as fh:
                fh.write("work\n")
            _git(["init", "-q"], work, safe)
            _git(["add", "-A"], work, safe)
            _git(["commit", "-qm", "work"], work, safe)

            # The real repo's HEAD must be unchanged (no stray commit leaked onto it).
            real_head_after = _git(["rev-parse", "HEAD"], real, base).stdout.strip()
            self.assertEqual(real_head, real_head_after)

            # ...and the temp dir became its own independent repo with its own commit.
            # Reading through the clean base env means this fails if the helper stops
            # scrubbing (the temp `git init` would have re-targeted the inherited repo,
            # so `work/.git` would never exist).
            work_head = _git(["rev-parse", "HEAD"], work, base).stdout.strip()
            self.assertTrue(work_head)
            self.assertNotEqual(work_head, real_head)


if __name__ == "__main__":
    unittest.main()
