#!/usr/bin/env python3
"""Fail if any tracked file looks like a secret-bearing file or a scratch dump.

This is the enforceable equivalent of a "block .env / .pem / .key" push rule for
a public, user-owned repository. GitHub push rulesets are only available on
organization-owned repos, so this check runs in the required `validate` CI job
and in the `.githooks/pre-commit` hook instead, ensuring a private key, keystore,
or dotenv file cannot be committed even by the owner.

Run from the repo root:
    python scripts/check_forbidden_files.py
"""

from __future__ import annotations

import fnmatch
import subprocess
import sys
from pathlib import Path

# Basename globs that indicate a private key, keystore, or environment/secret file.
FORBIDDEN_GLOBS = (
    ".env",
    ".env.*",
    "*.env",
    ".envrc",
    ".netrc",
    ".npmrc",
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    "*.p8",
    "*.jks",
    "*.kdb",
    "*.keystore",
    "*.ppk",
    "credentials.json",
    "credentials.*.json",
    "service-account.json",
    "service-account.*.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
)

# Suffixes that turn an otherwise-matching name into a safe, shareable template.
ALLOWED_SUFFIXES = (".example", ".sample", ".template", ".dist")

# Scratch dumps that belong in the gitignored tmp/, never in the tree. The root-anchored
# .gitignore block only swallows these at the REPO ROOT, but an agent's working directory is
# usually a subdirectory - which is how a 180KB, unreferenced `changes.diff` came to live
# inside .github/skills/demo-video, and `diff_local.patch` before it. Nothing in this repo
# legitimately tracks a .diff or .patch, so refusing them outright costs nothing.
SCRATCH_GLOBS = (
    "*.diff",
    "*.patch",
)

# The repository ROOT is a CLOSED set: these are the only files that legitimately live there.
# An agent's one-off probe lands beside AGENTS.md as `test_svg_exec.html`, `temp.txt`,
# `local.js`, `screenshot.png`, or a bare `x` - shapes the tree-wide diff/patch rule never saw,
# so `git add -A` could commit one and every gate would stay green (that is how `diff.txt` and
# `js-diff.txt`, two unreferenced 38KB diff captures, came to be tracked at the root). A
# denylist of shapes can never keep up with what a probe is named, and the root is small and
# stable, so anything else tracked HERE is scratch by definition. The rule is anchored to the
# root, so a report under examples/, a page under site/, or anything in a plugin is untouched.
# To add a real top-level file, add its name below (and, if the root-anchored .gitignore block
# would hide it, a `!/name` line there). Names are compared EXACTLY: on a case-sensitive
# filesystem a lowercase `readme.md` is a DIFFERENT file from `README.md`, so folding case here
# would widen the closed set instead of narrowing it.
ROOT_ALLOWED = frozenset(
    (
        ".editorconfig",
        ".gitattributes",
        ".gitignore",
        ".ignore",
        "AGENTS.md",
        "CLAUDE.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "MAINTAINING.md",
        "README.md",
        "SECURITY.md",
        "ai-marketplace.code-workspace",
    )
)


def is_root_scratch(path: str) -> bool:
    """Return True when `path` is a file at the repository root that does not belong there.

    `path` is a git index path, so `/` is the only separator: a literal backslash is part of
    the NAME on a case-sensitive filesystem, and translating it would let a root file called
    `foo\\bar` pose as a nested one.
    """
    norm = path
    while norm.startswith("./"):
        norm = norm[2:]
    if "/" in norm or not norm:
        return False
    return norm not in ROOT_ALLOWED


def is_scratch_artifact(path: str) -> bool:
    """Return True when the file looks like a committed scratch dump."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in SCRATCH_GLOBS):
        return True
    return is_root_scratch(path)


def is_forbidden(path: str) -> bool:
    """Return True when the file at `path` looks like committed secret material."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.endswith(ALLOWED_SUFFIXES):
        return False
    # Match case-insensitively (name is lowered, patterns are lowercase) so an
    # uppercase extension like SERVER.PEM is caught on case-sensitive Linux CI too.
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in FORBIDDEN_GLOBS)


def repo_root() -> "str | None":
    """Return the top level of the repository this script lives in, or None if there is none.

    Anchoring on the script's own location (not the ambient cwd) matters twice: `git ls-files`
    run from a subdirectory reports paths relative to THAT directory, which would make every
    file look root-level to `is_root_scratch`, and the script test suite runs from a throwaway
    sandbox where a cwd-relative git call sees no repository at all.
    """
    here = str(Path(__file__).resolve().parent)
    try:
        result = subprocess.run(
            ["git", "-C", here, "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("check_forbidden_files: git is not installed; skipping the tracked-file scan.")
        return None
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        if "not a git repository" in stderr.lower():
            print("check_forbidden_files: not a git repository; skipping the tracked-file scan.")
            return None
        # Same fail-closed rule as tracked_files(): only a genuine non-repo is a legitimate skip.
        print(f"check_forbidden_files: 'git rev-parse' failed (exit {exc.returncode}): {stderr}")
        raise SystemExit(1)
    return result.stdout.strip() or None


def tracked_files() -> "list[str] | None":
    root = repo_root()
    if root is None:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", root, "ls-files", "-z", "--full-name"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("check_forbidden_files: git is not installed; skipping the tracked-file scan.")
        return None
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        if "not a git repository" in stderr.lower():
            print("check_forbidden_files: not a git repository; skipping the tracked-file scan.")
            return None
        # Any other git failure (corrupt index, permissions, locked repo) is unexpected:
        # fail closed rather than silently skipping the guard.
        print(f"check_forbidden_files: 'git ls-files' failed (exit {exc.returncode}): {stderr}")
        raise SystemExit(1)
    return [path for path in result.stdout.split("\0") if path]


def main() -> int:
    files = tracked_files()
    if files is None:
        return 0
    status = 0
    offenders = sorted(path for path in files if is_forbidden(path))
    if offenders:
        print("check_forbidden_files: secret-bearing files must never be committed:")
        for path in offenders:
            print(f"  - {path}")
        print("Remove them, add the pattern to .gitignore, and rotate any exposed secret.")
        status = 1
    scratch = sorted(path for path in files if is_scratch_artifact(path))
    if scratch:
        print("check_forbidden_files: scratch dumps must never be committed:")
        for path in scratch:
            print(f"  - {path}")
        print("Write them to the gitignored tmp/ instead, with an absolute or tmp/-prefixed path.")
        print(
            "A diff/patch dump is refused anywhere; at the repo ROOT only the files listed in "
            "ROOT_ALLOWED in this script are allowed - add a real top-level file there."
        )
        status = 1
    if status == 0:
        print("check_forbidden_files: no secret-bearing files or scratch dumps are tracked. OK")
    return status


if __name__ == "__main__":
    sys.exit(main())
