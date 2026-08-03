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

# Scratch shapes that are forbidden at the REPO ROOT only. An agent's one-off probe lands
# beside AGENTS.md as `test_svg_exec.html`, `temp.txt`, `local.js`, or a bare `x` - shapes the
# tree-wide diff/patch rule never saw, so `git add -A` could commit one and every gate would
# stay green (that is how `diff.txt` and `js-diff.txt`, two unreferenced 38KB diff captures,
# came to be tracked at the root). The root holds only its documented top-level files - no
# code, no HTML, no captured output - so anchoring the rule here refuses a probe without
# touching a real report under examples/, a page under site/, or anything in a plugin.
# Mirrors the root-anchored block in .gitignore; keep the two in step.
ROOT_SCRATCH_GLOBS = (
    "*.html",
    "*.htm",
    "*.txt",
    "*.json",
    "*.xml",
    "*.csv",
    "*.js",
    "*.mjs",
    "*.cjs",
    "*.ts",
    "*.py",
    "*.sh",
    "*.ps1",
    "test_*",
    "test-*",
    "temp",
    "temp.*",
    "tmp_*",
    "tmp-*",
    "probe*",
    "scratch*",
    "out.*",
    "err.*",
    "x",
    "x.*",
)

# Names that legitimately live at the repo root despite matching a pattern above. Add one here
# (and a `!/name` line in .gitignore) rather than widening the globs.
ROOT_ALLOWED = frozenset()


def is_root_scratch(path: str) -> bool:
    """Return True when `path` is a scratch probe sitting at the repository root."""
    norm = path.replace("\\", "/")
    if "/" in norm:
        return False
    name = norm.lower()
    if name in ROOT_ALLOWED:
        return False
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in ROOT_SCRATCH_GLOBS)


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


def tracked_files() -> "list[str] | None":
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
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
        print("A diff/patch dump is refused anywhere; a probe shape is refused at the repo root.")
        status = 1
    if status == 0:
        print("check_forbidden_files: no secret-bearing files or scratch dumps are tracked. OK")
    return status


if __name__ == "__main__":
    sys.exit(main())
