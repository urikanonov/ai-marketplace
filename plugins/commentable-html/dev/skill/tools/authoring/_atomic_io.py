#!/usr/bin/env python3
"""Crash-safe file replacement shared by the authoring tools that rewrite a document in place.

A plain `open(path, "w")` truncates the target BEFORE the replacement bytes exist, so a crash,
a full disk, an encoding error or an interrupted run destroys the user's only copy of a document
that can be megabytes long. Every tool that rewrites a document in place must stage the new bytes
in the same directory, flush them to disk, and swap them in with `os.replace`, which is atomic on
POSIX and on Windows (MoveFileEx with REPLACE_EXISTING).

This lives in one place so the guarantee cannot drift between the tools that depend on it.
"""
import io
import os
import stat
import tempfile


def quiet_remove(path):
    """Best-effort delete. Clears a read-only bit first: on Windows the staged file inherits the
    target's mode, and a read-only staged file cannot be removed, so cleanup would leak it."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass
    try:
        os.remove(path)
    except OSError:
        pass


def atomic_write(path, text):
    """Replace `path` with `text` via a fully-written temp file plus os.replace."""
    # Follow a symlink to its target: replacing the LINK would turn it into a regular file and
    # strand the real document with stale content.
    path = os.path.realpath(path)
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, staged = tempfile.mkstemp(prefix=".cmh-write-", suffix=".html", dir=directory)
    try:
        # Write through the descriptor mkstemp already owns rather than closing and reopening by
        # name: that gap is where a Windows virus scanner takes a lock and the reopen fails.
        with io.open(fd, "w", encoding="utf-8", newline="", closefd=True) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        # mkstemp creates 0600 and os.replace carries that inode's mode to the target,
        # so a 0644 report would silently become owner-only. Keep the target's mode.
        try:
            os.chmod(staged, stat.S_IMODE(os.stat(path).st_mode))
        except OSError:
            pass
        os.replace(staged, path)
    except Exception:
        quiet_remove(staged)
        raise
    _fsync_directory(directory)


def _fsync_directory(directory):
    """Persist the rename itself. Without this the swap can be lost to a power failure even
    though the staged bytes were fsynced. Not available on Windows, where it is a no-op."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except (OSError, AttributeError):
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
