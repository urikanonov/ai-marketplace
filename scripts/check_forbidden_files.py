#!/usr/bin/env python3
"""Fail if any tracked file looks like a secret-bearing file.

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
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    "*.jks",
    "*.keystore",
    "*.ppk",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
)

# Suffixes that turn an otherwise-matching name into a safe, shareable template.
ALLOWED_SUFFIXES = (".example", ".sample", ".template", ".dist")


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
    except subprocess.CalledProcessError:
        print("check_forbidden_files: not a git repository; skipping the tracked-file scan.")
        return None
    return [path for path in result.stdout.split("\0") if path]


def main() -> int:
    files = tracked_files()
    if files is None:
        return 0
    offenders = sorted(path for path in files if is_forbidden(path))
    if offenders:
        print("check_forbidden_files: secret-bearing files must never be committed:")
        for path in offenders:
            print(f"  - {path}")
        print("Remove them, add the pattern to .gitignore, and rotate any exposed secret.")
        return 1
    print("check_forbidden_files: no secret-bearing files are tracked. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
