#!/usr/bin/env python3
"""Unpack the commentable-html skill-resources.zip into the skill directory, once per version.

Ships unzipped alongside the SessionStart hook. The bulky runtime (tools/, references/, dist/,
vendor/) is shipped as a single skill-resources.zip so the plugin installer writes only a handful of
files - which matters on Windows, where Defender briefly locks each file as it is written and the
installer aborts the whole install on the first transient lock (the 'Access is denied. (os error 5)'
failure). The hook's native fast path checks for the version-stamped marker and only spawns this
script when the resources are missing or stale, so it runs at most once per version. Extraction is
built to be robust and to NEVER leave a half-usable skill:

- it extracts into a private STAGING subdir first, then atomically swaps each top-level runtime dir
  into place, so a transient lock, timeout, or crash mid-extract leaves the PREVIOUS version fully
  intact (the swap removes the old dir and renames the new one in, retrying a transient lock);
- because removed/renamed files are replaced by a fresh directory, nothing lingers across a version
  upgrade, and because the swap targets come from the real extracted directories (not from raw zip
  member names) there is no path-derivation mismatch;
- every member path is validated (reject absolute / drive / `..` / backslash-separated members) on
  top of stdlib zip-slip sanitisation, failing closed on a tampered zip;
- the zip OPEN and every member are retried on a transient lock (the fresh zip is what Defender
  scans) within time budgets under the hook timeout, so a permanent failure aborts gracefully and
  retries next session instead of hanging;
- concurrent session startups are serialised by an exclusive lock (held open for the duration, with
  an atomic steal of a lock abandoned by a crashed process), so two windows cannot extract at once.

It is non-blocking: any failure is logged and swallowed so a session is never broken. Stdlib only;
safe under `python -I`.
"""
import argparse
import errno
import os
import shutil
import stat
import sys
import time
import zipfile

MARKER_PREFIX = ".skill-resources-"
MARKER_SUFFIX = ".ok"
LOCK_NAME = ".skill-resources.lock"
STAGING_NAME = ".skill-resources-staging"
BACKUP_SUFFIX = ".skill-resources-old"
DEFAULT_ZIP_NAME = "skill-resources.zip"
# Names in the shipped skill dir that the swap must never overwrite from a (tampered) zip.
_RESERVED_TOP_NAMES = {"SKILL.md", "LICENSE", DEFAULT_ZIP_NAME}
DEFAULT_RETRIES = 8
DEFAULT_BACKOFF = 0.05  # seconds; doubles each retry, capped, so a lock clears without stalling.
_MAX_DELAY = 2.0
# ONE overall wall-clock budget for a whole extraction attempt, comfortably under the hook's 120s
# timeout AND under STALE_LOCK_SECONDS, so a live holder can never be mistaken for a crashed one. The
# zip OPEN gets a sub-slice of this budget so a slow-to-open zip cannot starve member extraction, but
# open + members + swap all share the SAME deadline, so total runtime stays within budget.
DEFAULT_BUDGET_SECONDS = 90.0
_OPEN_BUDGET_SECONDS = 15.0
# A lock older than this is treated as abandoned by a crashed process and stolen. A live holder
# finishes within DEFAULT_BUDGET_SECONDS (90s), well under this, so a running session is never seen
# as stale; this only governs recovery from a hard-crashed holder.
STALE_LOCK_SECONDS = 150.0
# Windows lock/share/transient codes worth retrying: ACCESS_DENIED, SHARING_VIOLATION,
# LOCK_VIOLATION, and DIR_NOT_EMPTY (the NTFS delete-pending window after an rmtree, before an
# os.replace onto the same path).
_LOCK_WINERRORS = {5, 32, 33, 145}


def _is_lock_error(exc):
    """A transient file lock we should retry (Defender / antivirus / another scanner / another
    session mid-write)."""
    if getattr(exc, "winerror", None) in _LOCK_WINERRORS:
        return True
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.EBUSY):
        return True
    return False


def default_skill_dir():
    """The shipped skill dir, resolved from this script's location (hooks/ is a sibling)."""
    here = os.path.dirname(os.path.abspath(__file__))
    plugin_root = os.path.dirname(here)
    return os.path.join(plugin_root, "skills", "commentable-html")


def marker_path(skill_dir, version):
    return os.path.join(skill_dir, MARKER_PREFIX + version + MARKER_SUFFIX)


def _retry(func, retries, backoff, sleep, deadline):
    """Call func(), retrying a transient lock up to `retries` times with capped exponential backoff,
    but never sleeping past `deadline` (time.monotonic seconds). A non-lock error, an exhausted
    retry count, or an expired budget re-raises immediately - so no attempt is made after the
    deadline."""
    attempt = 0
    delay = backoff
    while True:
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - decide by kind, then re-raise
            if not _is_lock_error(exc) or attempt >= retries:
                raise
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise
            nap = min(delay, _MAX_DELAY)
            if remaining is not None:
                nap = min(nap, remaining)
            sleep(nap)
            delay *= 2
            attempt += 1


def _extract_member(zf, member, dest):
    zf.extract(member, dest)


def extract_member_with_retry(zf, member, dest, retries, backoff,
                              sleep=time.sleep, extract=_extract_member, deadline=None):
    """Extract one member, retrying a transient lock up to `retries` times with backoff."""
    _retry(lambda: extract(zf, member, dest), retries, backoff, sleep, deadline)


def _is_within(base, target):
    base = os.path.normpath(os.path.abspath(base))
    target = os.path.normpath(os.path.abspath(target))
    return target == base or target.startswith(base + os.sep)


def _safe_member_path(dest, name):
    """Resolve a zip member under dest, failing closed on an absolute / drive-letter / traversing
    member. Treats BOTH `/` and `\\` as separators so a backslash-encoded `..\\x` cannot slip past
    on POSIX (defence in depth; stdlib zipfile also sanitises)."""
    norm = name.replace("\\", "/")
    if norm.startswith("/") or os.path.isabs(name) or (len(name) > 1 and name[1] == ":"):
        raise ValueError("unsafe (absolute) zip member path: %r" % name)
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError("unsafe (traversing) zip member path: %r" % name)
    target = os.path.join(dest, *parts) if parts else dest
    if not _is_within(dest, target):
        raise ValueError("unsafe zip member path: %r" % name)
    return target


def _make_writable(path):
    """Best-effort: clear the read-only attribute across a tree so an AV-quarantined-and-restored
    file (which can come back read-only on Windows) does not defeat rmtree with a permanent EACCES."""
    try:
        if os.path.isfile(path) or os.path.islink(path):
            os.chmod(path, stat.S_IWRITE)
            return
        for root, dirs, files in os.walk(path):
            for name in dirs + files:
                try:
                    os.chmod(os.path.join(root, name), stat.S_IWRITE)
                except OSError:
                    pass
    except OSError:
        pass


def _rmtree_retry(path, retries, backoff, sleep, deadline):
    """Remove a directory tree, retrying a transient lock (do NOT ignore_errors, so a Defender lock
    is retried rather than silently leaving files behind). Clears read-only attributes first."""
    if not os.path.exists(path) and not os.path.islink(path):
        return
    _make_writable(path)

    def _rm():
        if os.path.islink(path) or os.path.isfile(path):
            os.remove(path)
        else:
            shutil.rmtree(path)
    try:
        _retry(_rm, retries, backoff, sleep, deadline)
    except FileNotFoundError:
        pass


def clear_markers(skill_dir):
    """Remove any .skill-resources-*.ok markers and leftover .tmp files so a stale or crashed
    extraction does not leave a misleading marker or temp cruft."""
    try:
        names = os.listdir(skill_dir)
    except OSError:
        return
    for name in names:
        if not name.startswith(MARKER_PREFIX):
            continue
        if name.endswith(MARKER_SUFFIX) or name.endswith(MARKER_SUFFIX + ".tmp"):
            try:
                os.remove(os.path.join(skill_dir, name))
            except OSError:
                pass


def _write_marker(skill_dir, version):
    """Write the version marker with a no-follow temp create (so a pre-planted `.tmp` symlink cannot
    redirect the write), then atomically move it into place."""
    tmp = marker_path(skill_dir, version) + ".tmp"
    try:
        os.remove(tmp)
    except OSError:
        pass
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, (version + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, marker_path(skill_dir, version))


def _is_swappable(skill_dir, entry):
    """A staging top-level entry is installed only if it is a real directory and not a reserved
    control name, so a (tampered) zip cannot overwrite SKILL.md, LICENSE, the zip itself, or any
    dot-prefixed marker/lock/staging/backup file via the swap."""
    if entry.startswith(".") or entry in _RESERVED_TOP_NAMES:
        return False
    return os.path.isdir(os.path.join(skill_dir, STAGING_NAME, entry))


def _cleanup_leftovers(skill_dir, retries, backoff, sleep, deadline):
    """Remove a leftover staging dir, old-version backup dirs, and stale-lock sidecars from a prior
    crashed run so they cannot accumulate or confuse a fresh extraction."""
    _rmtree_retry(os.path.join(skill_dir, STAGING_NAME), retries, backoff, sleep, deadline)
    try:
        names = os.listdir(skill_dir)
    except OSError:
        return
    for name in names:
        if name.endswith(BACKUP_SUFFIX) or name.startswith(LOCK_NAME + ".stale."):
            p = os.path.join(skill_dir, name)
            try:
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
            except OSError:
                pass


def _swap_into_place(skill_dir, staging, retries, backoff, sleep, deadline):
    """Install each extracted top-level directory transactionally: rename the existing dir aside to a
    backup, move the new one in, then delete the backups. If ANY entry fails, roll every touched
    entry back to the previous version, so the installed skill is either fully upgraded or left
    exactly as it was - never a mixed or missing state."""
    entries = [e for e in sorted(os.listdir(staging)) if _is_swappable(skill_dir, e)]
    touched = []  # (dst, bak_or_None): entries whose new dir we began moving into place
    try:
        for entry in entries:
            src = os.path.join(staging, entry)
            dst = os.path.join(skill_dir, entry)
            bak = dst + BACKUP_SUFFIX
            _rmtree_retry(bak, retries, backoff, sleep, deadline)
            had_old = os.path.exists(dst) or os.path.islink(dst)
            if had_old:
                _retry(lambda d=dst, b=bak: os.replace(d, b), retries, backoff, sleep, deadline)
            touched.append((dst, bak if had_old else None))
            _retry(lambda s=src, d=dst: os.replace(s, d), retries, backoff, sleep, deadline)
    except BaseException:
        for dst, bak in reversed(touched):
            shutil.rmtree(dst, ignore_errors=True)  # remove the new/partial content
            if bak is not None:
                try:
                    os.replace(bak, dst)  # restore the previous version
                except OSError:
                    pass
        raise
    for _dst, bak in touched:
        if bak is not None:
            shutil.rmtree(bak, ignore_errors=True)


def extract_all(zip_path, skill_dir, version, retries=DEFAULT_RETRIES, backoff=DEFAULT_BACKOFF,
                sleep=time.sleep, extract=_extract_member, budget=DEFAULT_BUDGET_SECONDS):
    """Extract into a staging dir, then transactionally swap each top-level dir into place, and write
    the marker only after ALL of it succeeds. Every phase (open, members, swap) shares ONE overall
    deadline under the hook timeout, and the swap rolls back on failure, so any failure leaves the
    previous version intact and no marker - the next session re-extracts (self-heal)."""
    now = time.monotonic
    deadline = None if budget is None else now() + budget
    open_deadline = deadline if deadline is None else min(now() + _OPEN_BUDGET_SECONDS, deadline)
    # Invalidate the current marker and clear old markers/temps/leftovers up front, so a failure
    # below never leaves a marker pointing at a tree we are about to replace.
    try:
        os.remove(marker_path(skill_dir, version))
    except OSError:
        pass
    clear_markers(skill_dir)
    _cleanup_leftovers(skill_dir, retries, backoff, sleep, open_deadline)
    staging = os.path.join(skill_dir, STAGING_NAME)
    os.makedirs(staging, exist_ok=True)
    try:
        zf = _retry(lambda: zipfile.ZipFile(zip_path), retries, backoff, sleep, open_deadline)
        with zf:
            members = zf.infolist()
            for member in members:
                _safe_member_path(staging, member.filename)  # fail closed before writing anything
            for member in members:
                extract_member_with_retry(zf, member, staging, retries, backoff,
                                          sleep=sleep, extract=extract, deadline=deadline)
        _swap_into_place(skill_dir, staging, retries, backoff, sleep, deadline)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    _write_marker(skill_dir, version)


def _acquire_lock(skill_dir):
    """Acquire an exclusive extraction lock, held open for the duration and stamped with our pid.
    Returns (lock_path, fd) on success, or (None, None) if another session holds a fresh lock (skip
    and let it finish). A lock older than STALE_LOCK_SECONDS is assumed abandoned by a crashed
    process and stolen atomically (rename-to-unique, so only one racing session wins the steal)."""
    lock = os.path.join(skill_dir, LOCK_NAME)
    for _attempt in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            except OSError:
                pass
            return lock, fd
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(lock)
            except OSError:
                return None, None
            if age <= STALE_LOCK_SECONDS:
                return None, None
            stolen = lock + ".stale.%d" % os.getpid()
            try:
                os.replace(lock, stolen)  # atomic: the loser's source is already gone
            except OSError:
                return None, None  # another session won the steal
            try:
                os.remove(stolen)
            except OSError:
                pass
            # loop once more to create our own lock
    return None, None


def _release_lock(lock, fd):
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    if not lock:
        return
    # Only remove the lock if it is still OURS: if a concurrent session stole ours (mistaking us for
    # crashed) and created its own, the file now carries that session's pid, so we must not delete it.
    try:
        with open(lock, "rb") as fh:
            content = fh.read().strip()
    except OSError:
        content = None
    if content in (None, b"", str(os.getpid()).encode("ascii")):
        try:
            os.remove(lock)
        except OSError:
            pass


def run(skill_dir, version, zip_path=None, retries=DEFAULT_RETRIES, backoff=DEFAULT_BACKOFF,
        force=False, sleep=time.sleep, extract=_extract_member, log=None,
        budget=DEFAULT_BUDGET_SECONDS):
    """Extract the resources if the version marker is missing (or force). Returns 0 on no-op/success.

    Serializes concurrent sessions with an exclusive lock and re-checks the marker after acquiring
    it, so exactly one session extracts and the others see the finished marker.
    """
    marker = marker_path(skill_dir, version)
    if os.path.exists(marker) and not force:
        return 0
    if zip_path is None:
        zip_path = os.path.join(skill_dir, DEFAULT_ZIP_NAME)
    if not os.path.isfile(zip_path):
        if log:
            log("skill-resources.zip not found at %s; nothing to extract." % zip_path)
        return 0
    lock, fd = _acquire_lock(skill_dir)
    if lock is None:
        if log:
            log("another session is extracting skill resources; skipping.")
        return 0
    try:
        if os.path.exists(marker) and not force:
            return 0
        extract_all(zip_path, skill_dir, version, retries=retries, backoff=backoff,
                    sleep=sleep, extract=extract, budget=budget)
        return 0
    finally:
        _release_lock(lock, fd)


def _log_dir(agent):
    if agent == "claude":
        home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
            os.path.expanduser("~"), ".claude")
    else:
        home = os.environ.get("COPILOT_HOME") or os.path.join(
            os.path.expanduser("~"), ".copilot")
    return os.path.join(home, "plugin-data")


def _make_logger(agent):
    def _log(message):
        try:
            d = _log_dir(agent)
            os.makedirs(d, exist_ok=True)
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            with open(os.path.join(d, "commentable-html-extract.log"), "a",
                      encoding="utf-8") as fh:
                fh.write("%s  [%s] %s\n" % (stamp, agent, message))
        except Exception:  # noqa: BLE001 - logging must never break the session
            pass
    return _log


def main(argv=None):
    parser = argparse.ArgumentParser(description="Extract commentable-html skill resources.")
    parser.add_argument("--version", required=True, help="the shipped skill version (marker name).")
    parser.add_argument("--skill-dir", default=None, help="override the skill directory.")
    parser.add_argument("--zip", dest="zip_path", default=None, help="override the zip path.")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--backoff", type=float, default=DEFAULT_BACKOFF)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--agent", choices=("copilot", "claude"), default="copilot")
    args = parser.parse_args(argv)

    skill_dir = args.skill_dir or default_skill_dir()
    log = _make_logger(args.agent)
    try:
        run(skill_dir, args.version, zip_path=args.zip_path, retries=args.retries,
            backoff=args.backoff, force=args.force, log=log)
        return 0
    except Exception as exc:  # noqa: BLE001 - non-blocking: log and swallow
        log("extraction failed for version %s: %s; the previous version is left intact and the "
            "next session will re-extract." % (args.version, exc))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
