#!/usr/bin/env python3
"""Fail if tracked Backlog.md artifacts reappear after the GitHub Issues migration.

Run from the repo root:
    python scripts/check_no_backlog.py
"""

from __future__ import annotations

import subprocess
import sys

BACKLOG_DIR_NAMES = {"backlog", ".backlog"}
BACKLOG_CONFIG_NAMES = ("backlog.config", "backlog.config.")


def is_backlog_artifact(path: str) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    if not normalized:
        return False

    parts = normalized.lower().split("/")
    if parts[0] in BACKLOG_DIR_NAMES:
        return True

    name = parts[-1]
    return name == BACKLOG_CONFIG_NAMES[0] or name.startswith(BACKLOG_CONFIG_NAMES[1])


def find_violations(paths: "list[str]") -> "list[str]":
    return sorted(path for path in paths if is_backlog_artifact(path))


def tracked_files() -> "list[str] | None":
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("check_no_backlog: git is not installed; skipping the tracked-file scan.")
        return None
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        if "not a git repository" in stderr.lower():
            print("check_no_backlog: not a git repository; skipping the tracked-file scan.")
            return None
        print(f"check_no_backlog: 'git ls-files' failed (exit {exc.returncode}): {stderr}")
        raise SystemExit(1)
    return [path for path in result.stdout.split("\0") if path]


def main() -> int:
    files = tracked_files()
    if files is None:
        return 0

    offenders = find_violations(files)
    if offenders:
        print("check_no_backlog: Backlog.md artifacts must not be committed:")
        for path in offenders:
            print(f"  - {path}")
        print("Track work in GitHub Issues and remove these Backlog.md files or configs.")
        return 1

    print("check_no_backlog: no Backlog.md artifacts are tracked. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
