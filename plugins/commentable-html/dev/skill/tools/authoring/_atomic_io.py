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
import sys
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


def default_file_mode():
    """The mode a plain `open(path, "w")` would produce: 0666 masked by the process umask.

    There is no read-only way to read the umask, so it is read by setting and restoring it. The
    restore is in a `finally` so even an interrupt cannot leave the process umask changed. If the
    umask cannot be read at all the answer is unknown, so it fails CLOSED to owner-only rather
    than guessing a world-readable default."""
    try:
        mask = os.umask(0o022)
    except OSError:
        return 0o600
    try:
        return 0o666 & ~mask
    finally:
        try:
            os.umask(mask)
        except OSError:
            pass


def preserve_mode(staged, path, fallback=None):
    """Give the staged file the mode the destination should end up with.

    mkstemp creates 0600 and `os.replace` carries the STAGED inode's mode to the target, so a
    world-readable 0644 report rewritten in place would silently become owner-only. Copy the
    destination's permission bits when it already exists. When it does NOT exist there is nothing
    to preserve, so fall back to `fallback`'s mode when a caller names the source document (a
    private 0600 report written to a new path must not be widened) and otherwise to the mode a
    plain create would have produced. Only the 0777 permission bits are copied: a setuid/setgid
    bit belongs to the file it was set on, never to a freshly staged inode owned by whoever ran
    the tool. A destination that exists but cannot be statted is left alone entirely - guessing
    there could WIDEN a deliberately private file, so the staged file keeps mkstemp's 0600.

    Applying the mode is best effort - a failure must never cost the write itself - but it is not
    SILENT: the tool says so on stderr, because a silently wrong mode is the class of bug this
    helper exists to prevent."""
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        mode = _new_file_mode(fallback)
    except OSError as exc:
        _warn_mode(path, exc)
        return
    if mode is None:
        return
    try:
        os.chmod(staged, mode & 0o777)
    except OSError as exc:
        _warn_mode(path, exc)


def _warn_mode(path, exc):
    sys.stderr.write("commentable-html: WARNING - could not preserve the file mode of %s (%s); "
                     "it may land owner-only\n" % (path, exc))


def _new_file_mode(fallback):
    """The mode a destination that does not exist yet should be created with.

    A caller that names a source document wants that document's visibility, so a source that
    cannot be statted (or is not a regular file) is NOT quietly replaced by the process default -
    that would be the very widening the fallback exists to prevent. `None` then means "leave the
    staged file alone", which keeps mkstemp's conservative 0600. The source's mode is intersected
    with what a plain create would produce, so a brand-new file is never wider than EITHER the
    source or the process umask allows."""
    if fallback:
        try:
            info = os.stat(fallback)
        except OSError:
            return None
        if not stat.S_ISREG(info.st_mode):
            return None
        return stat.S_IMODE(info.st_mode) & default_file_mode()
    return default_file_mode()


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
        preserve_mode(staged, path)
        os.replace(staged, path)
        staged = None
    finally:
        # A finally, not `except Exception`: a KeyboardInterrupt mid-write must not leak the
        # staged file either.
        if staged is not None:
            quiet_remove(staged)
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
