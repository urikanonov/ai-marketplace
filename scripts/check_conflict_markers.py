#!/usr/bin/env python3
"""Fail if any tracked text file still carries an unresolved git conflict marker.

A bad conflict resolution can be committed and merged with every other gate green: a
marker line is valid Markdown, a generated file that was assembled from a broken source
still matches its source, and no schema or link checker looks at it. That happened - a
`<<<<<<< HEAD` / `=======` / `>>>>>>>` block reached `main` inside the commentable-html
doc-surface registry, which silently malformed the coverage rows for six shipped feature
ids (issue #763). This guard closes that hole for the whole repository.

Note the scope: it catches an UNFINISHED merge, not a WRONG one. A resolution that keeps
only one side leaves no markers and is still invisible here.

Two properties matter, and both cost real design:

1. WHAT COUNTS IS NARROW, because the repository legitimately contains lines made of
   equals signs (a Markdown setext heading underline, a rule in console output). Only a
   line at COLUMN 0 counts; the marker runs are seven characters OR MORE (seven is git's
   default and the `conflict-marker-size` attribute raises it, so an exact-seven rule
   would let the one setting a maintainer might reach for turn the guard off); and a
   separator (`=======`) counts only in a file that also carries a bracket or base marker,
   so `Summary` / `=======` (a real setext H1) is never flagged. A file that must
   legitimately DISPLAY a conflict block opts out with a pragma line - see
   `_ALLOW_LINE_RE`; the pragma must be the whole line (bar comment punctuation), so
   merely mentioning it in prose, as this docstring does, exempts nothing.

2. IT CANNOT PASS WITHOUT LOOKING. Everything is scanned as BYTES, so an encoding the
   repo does not use cannot hide a real marker behind a decode error; git always runs
   against the repository ROOT with root-relative paths, so invoking this from a
   subdirectory cannot list files that are then not found on disk; and if entries were
   listed but NONE could be read it FAILS instead of printing a green summary. Binary
   files are a legitimate skip, not a failure, so a commit of only images still passes.

Run from anywhere in the checkout:
    python scripts/check_conflict_markers.py            # scan the working tree
    python scripts/check_conflict_markers.py --staged   # scan staged content (pre-commit)
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

_START_RE = re.compile(rb"^<{7,}(?:[ \t].*)?$")
_END_RE = re.compile(rb"^>{7,}(?:[ \t].*)?$")
_SEPARATOR_RE = re.compile(rb"^={7,}$")
_BASE_RE = re.compile(rb"^\|{7,}(?:[ \t].*)?$")

# The opt-out for a file that must legitimately display a conflict block. It must be the
# WHOLE line apart from comment punctuation: a substring test would exempt every file
# that merely documents the pragma, including this module and AGENTS.md.
_ALLOW_LINE_RE = re.compile(
    rb"^[\s#/*<!;%-]*check-conflict-markers:[ \t]*allow-file[\s*/>-]*$")

_BOM_UTF8 = b"\xef\xbb\xbf"
# UTF-16/32 text is full of NUL bytes, so it would otherwise be skipped as binary.
_BOM_UTF16_32 = ((b"\xff\xfe\x00\x00", "utf-32-le"), (b"\x00\x00\xfe\xff", "utf-32-be"),
                 (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"))

BINARY = "binary"
UNREAD = "unread"


def _to_scannable(data: bytes) -> "bytes | None":
    """Normalize `data` to UTF-8-ish bytes, or None when it is binary."""
    for bom, encoding in _BOM_UTF16_32:
        if data.startswith(bom):
            try:
                return data[len(bom):].decode(encoding).encode("utf-8", errors="replace")
            except UnicodeDecodeError:
                return None
    if b"\0" in data:
        return None
    if data.startswith(_BOM_UTF8):
        # A byte-order mark would otherwise push a first-line marker off column 0.
        return data[len(_BOM_UTF8):]
    return data


def scan_bytes(data: bytes) -> "list[tuple[int, str]]":
    """Return [(line number, line)] for every conflict marker line in `data`.

    Byte-oriented on purpose: the markers are ASCII, so a latin-1 or otherwise non-UTF-8
    text file cannot hide one behind a decode error, and splitting on `\\n` alone means
    only a real line break starts a new line (`str.splitlines()` also breaks on U+2028,
    form feed, and friends, which would widen what counts as column 0).
    """
    normalized = _to_scannable(data)
    if normalized is None:
        return []
    lines = [line[:-1] if line.endswith(b"\r") else line for line in normalized.split(b"\n")]
    if any(_ALLOW_LINE_RE.match(line) for line in lines):
        return []
    # A bracket or base marker is reported wherever it appears; the separator needs one of
    # them in the file, because a lone line of equals signs is ordinary Markdown. Gating on
    # any of the three (not just `<<<<<<<`) catches a half-finished hand resolution that
    # deleted the start line.
    def marker(line):
        return _START_RE.match(line) or _END_RE.match(line) or _BASE_RE.match(line)
    conflicted = any(marker(line) for line in lines)
    hits = []
    for number, line in enumerate(lines, start=1):
        if marker(line) or (conflicted and _SEPARATOR_RE.match(line)):
            hits.append((number, line))
    return [(number, line.decode("utf-8", errors="replace")) for number, line in hits]


def scan_text(text: str) -> "list[tuple[int, str]]":
    """Convenience wrapper over `scan_bytes` for callers that already hold text."""
    return scan_bytes(text.encode("utf-8", errors="surrogateescape"))


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _git(args: "list[str]", label: str) -> "bytes | None":
    """Run a git command AT THE REPO ROOT and return raw stdout, or None if git is absent."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root())] + args,
            check=True,
            capture_output=True,
        )
    except FileNotFoundError:
        print(f"check_conflict_markers: git is not installed; skipping the {label} scan.")
        return None
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        if "not a git repository" in stderr.lower():
            print(f"check_conflict_markers: not a git repository; skipping the {label} scan.")
            return None
        # Any other git failure is unexpected: fail closed rather than skipping the guard.
        print(f"check_conflict_markers: git {args[0]} failed (exit {exc.returncode}): {stderr}")
        raise SystemExit(1)
    return result.stdout


def _split_paths(raw: bytes) -> "list[str]":
    """Decode NUL-separated git output, de-duplicated, order preserved.

    `os.fsdecode` rather than `text=True`: under `-z` git emits path bytes verbatim, and
    decoding them with the platform locale would mangle a non-ASCII path on Windows. An
    unmerged path is listed once per stage, hence the de-duplication.
    """
    names = [os.fsdecode(part) for part in raw.split(b"\0") if part]
    return list(dict.fromkeys(names))


def tracked_files() -> "list[str] | None":
    """Every tracked path, relative to the repo ROOT regardless of the caller's cwd."""
    raw = _git(["ls-files", "-z", "--full-name"], "tracked-file")
    return None if raw is None else _split_paths(raw)


def staged_files() -> "list[str] | None":
    """Paths the commit will record, relative to the repo root.

    `--diff-filter=d` excludes only deletions, so a rename or a type change - a staged
    `git mv` of a file whose conflict was hand-resolved badly - is still scanned. An
    `--diff-filter=ACM` list drops those silently.
    """
    raw = _git(["diff", "--cached", "--name-only", "-z", "--diff-filter=d"], "staged-file")
    return None if raw is None else _split_paths(raw)


def read_worktree(name: str) -> "bytes | None":
    try:
        return (repo_root() / name).read_bytes()
    except OSError:
        # Deleted-but-tracked, sparse, or unreadable; counted as unread, not as clean.
        return None


def read_staged(name: str) -> "bytes | None":
    """The staged CONTENT of `name` - what the commit will record, not what is on disk."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root()), "show", f":{name}"],
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout


def read_staged_batch(names: "list[str]") -> "dict[str, bytes | None]":
    """Read every staged blob through ONE `git cat-file --batch`.

    A `git show` per path costs a process spawn each (~30 ms on Windows), which a large
    staged set - a squash, a bulk regeneration - turns into a multi-second pre-commit.
    Streaming keeps it to a single spawn. A name containing a newline cannot be expressed
    in the line-oriented batch protocol, so it falls back to `read_staged`.
    """
    simple = [name for name in names if "\n" not in name]
    blobs: "dict[str, bytes | None]" = {name: read_staged(name) for name in names if "\n" in name}
    if not simple:
        return blobs
    try:
        proc = subprocess.Popen(
            ["git", "-C", str(repo_root()), "cat-file", "--batch"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        return {name: None for name in names}
    request = b"".join(b":" + os.fsencode(name) + b"\n" for name in simple)
    out, _ = proc.communicate(request)
    pos = 0
    for name in simple:
        newline = out.find(b"\n", pos)
        if newline == -1:
            blobs[name] = None
            continue
        header = out[pos:newline].split(b" ")
        if len(header) < 3:
            # "<input> missing" - the path is not in the index.
            blobs[name] = None
            pos = newline + 1
            continue
        kind, size = header[1], int(header[2])
        body = out[newline + 1:newline + 1 + size]
        # A gitlink resolves to a commit object; it holds no file content to scan.
        blobs[name] = body if kind == b"blob" else None
        pos = newline + 1 + size + 1
    return blobs


def scan_names(names: "list[str]", read) -> "tuple[list, int, dict[str, int]]":
    """Scan each name with `read`. Returns (offenders, scanned, {BINARY: n, UNREAD: n}).

    Binary and unreadable are counted SEPARATELY: a binary file is a legitimate skip (a
    commit of only images must still pass), while "nothing could be read at all" is the
    broken-invocation shape that must fail rather than report a green empty scan.
    """
    offenders = []
    scanned = 0
    skipped = {BINARY: 0, UNREAD: 0}
    for name in names:
        data = read(name)
        if data is None:
            skipped[UNREAD] += 1
            continue
        if _to_scannable(data) is None:
            skipped[BINARY] += 1
            continue
        scanned += 1
        for number, line in scan_bytes(data):
            offenders.append((name, number, line))
    return offenders, scanned, skipped


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_conflict_markers.py",
        description="Fail if a tracked file carries an unresolved git conflict marker.")
    parser.add_argument("--staged", action="store_true",
                        help="scan the staged content instead of the working tree (what a "
                             "commit would record; used by the pre-commit hook)")
    args = parser.parse_args(argv)

    # A non-ASCII offender path must be printable rather than crashing the report.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")

    if args.staged:
        names = staged_files()
        what = "staged files"
        blobs = read_staged_batch(names) if names else {}
        read = blobs.get
    else:
        names = tracked_files()
        what = "tracked files"
        read = read_worktree
    if names is None:
        return 0

    offenders, scanned, skipped = scan_names(names, read)
    if names and scanned == 0 and skipped[BINARY] == 0:
        print(f"check_conflict_markers: could not read any of the {len(names)} {what}; refusing "
              "to report a scan that examined nothing.")
        return 1
    if offenders:
        print("check_conflict_markers: unresolved conflict markers are present:")
        for name, number, line in offenders:
            snippet = line if len(line) <= 60 else line[:57] + "..."
            print(f"  - {name}:{number}: {snippet}")
        print("Finish the merge or rebase: resolve each block by KEEPING BOTH sides where both")
        print("are wanted, then rebuild any generated file assembled from it.")
        return 1
    counts = [f"{skipped[BINARY]} binary"] if skipped[BINARY] else []
    if skipped[UNREAD]:
        counts.append(f"{skipped[UNREAD]} unreadable")
    note = f" ({', '.join(counts)})" if counts else ""
    print(f"check_conflict_markers: no conflict markers in {scanned} {what}{note}. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
