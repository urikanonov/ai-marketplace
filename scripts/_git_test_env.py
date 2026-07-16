"""Shared test support: build a subprocess environment that is isolated from any
inherited git repository state.

When the scripts unit tests run from the `pre-push` git hook, git exports location
variables (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, ...) pointing at the REAL
repo/worktree. A test that spawns `git init`/`add`/`commit` in a temporary directory
inherits those variables and operates on the real repo instead of the temp one,
committing a stray tree onto the current branch (issue #283). Every git-spawning test
must build its subprocess env through `clean_git_env()` so those inherited variables
are scrubbed and the command always targets the intended directory.
"""
import os

# Location/discovery variables that make git act on an already-open repository. If any
# of these leak in from the parent process, a `git` call in a temp dir silently targets
# the inherited repo instead. They are scrubbed unconditionally.
_GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
    "GIT_CEILING_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
    "GIT_INDEX_VERSION",
)

# A stable author/committer identity so commits succeed in a hermetic temp repo that has
# no user.name/user.email configured (and so CI machines need no global git identity).
_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def clean_git_env(base=None, **overrides):
    """Return a copy of ``base`` (default ``os.environ``) with inherited git location
    variables removed and a hermetic author/committer identity applied.

    Pass ``overrides`` to set extra variables (they win over the identity defaults).
    Use the result as the ``env=`` argument of every ``subprocess`` call that spawns
    ``git`` so the command targets the intended directory, never an inherited repo.
    """
    env = dict(os.environ if base is None else base)
    for var in _GIT_LOCATION_VARS:
        env.pop(var, None)
    for key, value in _GIT_IDENTITY.items():
        env.setdefault(key, value)
    env.update(overrides)
    return env
