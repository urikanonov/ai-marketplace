#!/usr/bin/env python3
"""Crash-safe file replacement shared by every tool that rewrites a document in place.

A plain `open(path, "w")` truncates the target BEFORE the replacement bytes exist, so a crash,
a full disk, an encoding error or an interrupted run destroys the user's only copy of a document
that can be megabytes long. Every tool that rewrites a document in place must stage the new bytes
in the same directory, flush them to disk, and swap them in with `os.replace`, which is atomic on
POSIX and on Windows (MoveFileEx with REPLACE_EXISTING).

This lives at the tools/ ROOT, not in a bucket: tools in `authoring/`, `notes/`, `checklist/`,
`blocks/` and `deck/` all depend on it, and it lives in one place so the guarantee cannot drift
between them.
"""
import io
import os
import shutil
import stat
import sys
import tempfile
import time


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


def atomic_write(path, text, fallback=None):
    """Replace `path` with `text` via a fully-written temp file plus os.replace.

    `fallback` names the SOURCE document a `--out` run was derived from. It is used only when
    the destination does not exist yet, so a transform that writes a private 0600 report to a
    new path keeps that visibility instead of landing at the umask default."""
    # Follow a symlink to its target: replacing the LINK would turn it into a regular file and
    # strand the real document with stale content.
    path = os.path.realpath(path)
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, staged = _stage(directory, path)
    try:
        # Write through the descriptor mkstemp already owns rather than closing and reopening by
        # name: that gap is where a Windows virus scanner takes a lock and the reopen fails.
        # atomic-write: the staged temp file, by descriptor - it has no bytes to lose.
        with io.open(fd, "w", encoding="utf-8", newline="", closefd=True) as fh:
            fh.write(text)
            fsync_file(fh)
        preserve_mode(staged, path, fallback=fallback)
        replace_with_retry(staged, path)
        staged = None
    finally:
        # A finally, not `except Exception`: a KeyboardInterrupt mid-write must not leak the
        # staged file either.
        if staged is not None:
            quiet_remove(staged)
    _fsync_directory(directory)


def commit_staged(staged, path, fallback=None):
    """Give a caller-staged file the destination's mode and swap it in, durably.

    The tail of `atomic_write`, exposed because three tools stage their own replacement
    (`upgrade`, `retrofit`, `deck_theme`) - they build the bytes with a validation step in the
    middle - and a guarantee that stopped at the `atomic_write` callers would be one the spec
    could not honestly claim. The CALLER is responsible for fsyncing the staged bytes before
    calling this; `fsync_file` does that."""
    preserve_mode(staged, path, fallback=fallback)
    replace_with_retry(staged, path)
    _fsync_directory(os.path.dirname(os.path.abspath(path)) or ".")


def fsync_file(fh):
    """Flush a staged file all the way to the disk.

    Closing a file only hands the bytes to the OS. Without this the swap can land a name that
    points at unwritten blocks, so a power failure loses the document the swap was protecting -
    the very class the staging exists to close."""
    fh.flush()
    os.fsync(fh.fileno())


# Windows fails `os.replace` with a sharing violation (ERROR_SHARING_VIOLATION 32 /
# ERROR_LOCK_VIOLATION 33) while ANOTHER process holds the destination open - a virus scanner, an
# editor, a sync client - where a truncating write would have succeeded. Those holders let go in
# milliseconds, so a short bounded retry turns that transient into the swap the caller asked for.
# The loop is bounded (four backed-off waits, ~0.75s total) so a genuinely locked file still fails
# LOUDLY rather than hanging.
_REPLACE_ATTEMPTS = 5
_REPLACE_DELAY = 0.05


def replace_with_retry(staged, path):
    """`os.replace(staged, path)`, retrying only a Windows sharing violation.

    Public because the tools that hand-roll their own staging (`upgrade`, `retrofit`,
    `deck_theme`) must make the same swap under the same conditions; a guarantee that held only
    for `atomic_write` callers would be a guarantee the spec could not honestly claim."""
    delay = _REPLACE_DELAY
    for _ in range(_REPLACE_ATTEMPTS - 1):
        try:
            os.replace(staged, path)
            return
        except PermissionError as exc:
            # Only a sharing/lock violation is transient. POSIX has none, and on Windows an
            # access-denied (a read-only destination, a destination that is a directory) is
            # deterministic - waiting three quarters of a second only delays the report.
            if os.name != "nt" or getattr(exc, "winerror", None) not in (32, 33):
                raise
            time.sleep(delay)
            delay *= 2
    os.replace(staged, path)


def atomic_copy(src, dst, fallback=None):
    """Copy `src` over `dst` crash-safely, byte for byte.

    The same guarantee as `atomic_write` for a file that is COPIED rather than composed (the
    layer companions a NonShareable document loads). `shutil.copyfile` truncates the destination
    first, so a failed copy leaves the document loading a half-written stylesheet or runtime.

    `fallback` is NOT defaulted to `src`: a copy's source is often the skill's own installed
    `dist/`, whose mode reflects how the plugin was extracted rather than the visibility the user
    wants beside their document - and a read-only one would land a companion that can never be
    refreshed again. A caller copying a file the USER owns passes it explicitly."""
    dst = os.path.realpath(dst)
    directory = os.path.dirname(os.path.abspath(dst)) or "."
    fd, staged = _stage(directory, dst, suffix=".copy")
    try:
        # atomic-write: the staged temp file, by descriptor - it has no bytes to lose.
        with io.open(fd, "wb", closefd=True) as out:
            with io.open(src, "rb") as source:
                shutil.copyfileobj(source, out)
            fsync_file(out)
        preserve_mode(staged, dst, fallback=fallback)
        replace_with_retry(staged, dst)
        staged = None
    finally:
        if staged is not None:
            quiet_remove(staged)
    _fsync_directory(directory)


def stage_copy(src, directory, dst):
    """Copy `src` into a staged file beside `dst` and return its path, WITHOUT swapping it in.

    For a caller that must land several files together (the NonShareable companions): staging
    them all first shrinks the window in which a failure can leave a mixed set to the renames
    alone. The caller commits each with `commit_staged` and removes any leftover with
    `quiet_remove`."""
    fd, staged = _stage(directory, dst, suffix=".copy")
    try:
        # atomic-write: the staged temp file, by descriptor - it has no bytes to lose.
        with io.open(fd, "wb", closefd=True) as out:
            with io.open(src, "rb") as source:
                shutil.copyfileobj(source, out)
            fsync_file(out)
    except BaseException:
        quiet_remove(staged)
        raise
    return staged


def _stage(directory, destination, suffix=".html"):
    """mkstemp beside the destination, reporting a failure in terms the USER can act on.

    The raw error names a `.cmh-write-XXXX` path they have never seen; what actually went wrong
    is that the document's own directory cannot be written."""
    try:
        return tempfile.mkstemp(prefix=".cmh-write-", suffix=suffix, dir=directory)
    except OSError as exc:
        raise OSError(exc.errno, "cannot stage a replacement for %s: %s (%s)"
                      % (destination, directory, exc.strerror or exc))


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
