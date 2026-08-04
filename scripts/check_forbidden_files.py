#!/usr/bin/env python3
"""Fail if any tracked file looks like a secret-bearing file or a scratch dump.

This is the enforceable equivalent of a "block .env / .pem / .key" push rule for
a public, user-owned repository. GitHub push rulesets are only available on
organization-owned repos, so this check runs in the required `validate` CI job
and in the `.githooks/pre-commit` hook instead, ensuring a private key, keystore,
or dotenv file cannot be committed even by the owner. It also refuses a scratch
diff/patch dump anywhere in the tree, and anything whose top-level entry is not
one of the repository's allowlisted top-level files or directories.

The SCAN is cwd-independent (it anchors on this script's own repository), but the
command below is not - it names the script relative to the repo root:
    python scripts/check_forbidden_files.py
From a subdirectory, give the script's own path instead, for example
`python ../scripts/check_forbidden_files.py`.
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

# An `_`-prefixed name means one of exactly two things here: a PRIVATE MODULE (the `_paths.py`,
# `_shard.mjs`, `__init__.py` convention - eighteen are tracked, every one of them .py or .mjs),
# or a scratch dump. `_t1.txt`, `_t2.txt` and `_review_diff1.txt` reached main that way, and
# `_diff_record.txt`, `_diff_script.txt` and `_wip_diff.txt` were left behind while #927 was in
# flight; the root allowlist below refuses them at the root, but a SUBDIRECTORY - where an
# agent's cwd usually is - saw only the diff/patch rule above.
#
# So the rule here is an ALLOWLIST, for the same reason the repo root is one: a denylist of dump
# extensions cannot keep up with what the next probe is named (`_notes.md`, `_out.csv`,
# `_probe.html`, a bare `_wip`), and getting it wrong means the dump lands silently. An
# `_`-prefixed file is scratch unless it wears a SOURCE extension. Adding a genuine `_`-prefixed
# source of a new kind means adding its extension here - a rare, reviewable event.
UNDERSCORE_SOURCE_SUFFIXES = (
    ".py",
    ".pyi",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".d.ts",
    ".mts",
    ".cts",
    ".css",
    ".sh",
    ".ps1",
    ".psm1",
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

# The top-level DIRECTORIES are a closed set for the same reason, and closing only the file half
# leaves the obvious dodge open: `captures/out.txt` or `_scratch/probe.html` has a slash, so a
# file-only rule waves it through on a plain `git add -A` while it is every bit as much a dump.
# A new top-level directory is a rare, reviewable event, so it earns a line here.
ROOT_DIR_ALLOWED = frozenset(
    (
        ".claude-plugin",
        ".githooks",
        ".github",
        ".vscode",
        "docs",
        "plugins",
        "scripts",
        "site",
    )
)

# tmp/ is deliberately NOT a directory above. It is the place this guard tells you to write
# scratch, so allowing the directory wholesale would wave through the very dumps it exists to
# refuse (`tmp/dump.txt` force-added past the .gitignore). Only its marker file may be tracked.
ROOT_PATH_ALLOWED = frozenset(("tmp/.gitkeep",))


def is_root_scratch(path: str) -> bool:
    """Return True when `path` is not under an approved top-level entry of the repository.

    `path` is a git index path, so `/` is the only separator: a literal backslash is part of
    the NAME on a case-sensitive filesystem, and translating it would let a root file called
    `foo\\bar` pose as a nested one.
    """
    norm = path
    while norm.startswith("./"):
        norm = norm[2:]
    if norm in ROOT_PATH_ALLOWED:
        return False
    if not norm:
        return False
    head, slash, _ = norm.partition("/")
    if slash:
        return head not in ROOT_DIR_ALLOWED
    return head not in ROOT_ALLOWED


def _is_source_module(name: str) -> bool:
    """Return True when the lowercased basename `name` is a source file, not a dump."""
    # Longest suffix first, so `_types.d.ts` is judged on `.d.ts` rather than on `.ts`.
    for suffix in sorted(UNDERSCORE_SOURCE_SUFFIXES, key=len, reverse=True):
        if name.endswith(suffix):
            # A dump can wear a source suffix on top of its own (`_t1.txt.py`, `_wip.diff.py`),
            # so what remains has to be a plain name: `__init__` qualifies, `_t1.txt` does not.
            return "." not in name[: -len(suffix)]
    return False


def is_underscore_scratch(path: str) -> bool:
    """Return True when `path` is an `_`-prefixed dump rather than private source.

    The whole index path is judged, not just the basename: `scripts/_scratch/wip.txt` is the same
    dump parked one directory down. A `_`-prefixed DIRECTORY is not itself an offence, though -
    a private package (`scripts/_helpers/__init__.py`) is the same convention as a private
    module - so what decides is whether the FILE is source. `/` is the only separator a git index
    path has, so a literal backslash stays part of the NAME; translating one would let
    `scripts/_wip\\notes.txt` show a basename of `notes.txt` and skip the rule entirely.
    """
    segments = path.split("/")
    name = segments[-1].lower()
    if not name.startswith("_") and not any(seg.startswith("_") for seg in segments[:-1]):
        return False
    return not _is_source_module(name)


def is_scratch_artifact(path: str) -> bool:
    """Return True when the file looks like a committed scratch dump."""
    name = path.rsplit("/", 1)[-1].lower()
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in SCRATCH_GLOBS):
        return True
    if is_underscore_scratch(path):
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
            # A non-ASCII path has to survive two hops, and each corruption is a SILENT
            # allowlist miss: `core.quotePath=false` stops git C-quoting the name (-z only
            # changes the delimiter, not the quoting), and the explicit decode below stops
            # Python reading git's path bytes with the locale codec (cp1252 on Windows).
            ["git", "-C", root, "-c", "core.quotePath=false", "ls-files", "-z", "--full-name"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            # surrogateescape keeps a genuinely non-UTF-8 name intact instead of raising.
            errors="surrogateescape",
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


def display_path(path: str) -> str:
    """Render `path` so it can always be printed, whatever the console encoding is.

    A name that is not valid UTF-8 is carried as surrogates by the decode in tracked_files();
    printing one straight to a cp1252 console raises UnicodeEncodeError, which would replace an
    actionable refusal with a traceback - the guard failing in the one case it must be clearest.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    literal = path.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")
    return literal.encode(encoding, "backslashreplace").decode(encoding, "replace")


def main() -> int:
    files = tracked_files()
    if files is None:
        return 0
    status = 0
    offenders = sorted({path for path in files if is_forbidden(path)})
    if offenders:
        print("check_forbidden_files: secret-bearing files must never be committed:")
        for path in offenders:
            print(f"  - {display_path(path)}")
        print("Remove them, add the pattern to .gitignore, and rotate any exposed secret.")
        status = 1
    scratch = sorted({path for path in files if is_scratch_artifact(path)})
    if scratch:
        print("check_forbidden_files: scratch dumps must never be committed:")
        for path in scratch:
            print(f"  - {display_path(path)}")
        print("Write them to the gitignored tmp/ instead, with an absolute or tmp/-prefixed path.")
        print(
            "A diff/patch dump is refused anywhere, as is an `_`-prefixed file that is not a "
            "source module; at the repo ROOT only the entries listed in ROOT_ALLOWED / "
            "ROOT_DIR_ALLOWED in this script are allowed - add a real top-level file or directory "
            "there. If an `_`-prefixed file above is a genuine private source of a kind this repo "
            "has not tracked before, add its extension to UNDERSCORE_SOURCE_SUFFIXES instead."
        )
        status = 1
    if status == 0:
        print("check_forbidden_files: no secret-bearing files or scratch dumps are tracked. OK")
    return status


if __name__ == "__main__":
    sys.exit(main())
