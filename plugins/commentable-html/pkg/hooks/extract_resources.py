#!/usr/bin/env python3
"""Unpack the commentable-html skill-resources.zip into the skill directory, once per version.

Ships unzipped alongside the SessionStart hook. The bulky runtime (tools/, references/, dist/,
vendor/) is shipped as a single skill-resources.zip so the plugin installer writes only a handful
of files - which matters on Windows, where Defender briefly locks each file as it is written and the
installer aborts the whole install on the first transient lock (the 'Access is denied. (os error 5)'
failure). The hook's native fast path checks for the version-stamped marker and only spawns this
script when the resources are missing or stale (a fresh install, or an update dropped a new zip), so
it runs at most once per version. Extraction:

- retries the zip OPEN and every member on a transient lock with backoff (the fresh zip is exactly
  the file Defender scans when the hook fires), bounded by an overall time budget under the hook
  timeout so a permanent failure cannot hang the session;
- serializes across concurrent session startups with an exclusive lock (with stale-lock recovery),
  so two windows starting at once cannot interleave writes into the same files;
- wipes the runtime dirs the zip owns before extracting, so a file removed/renamed in a newer
  version does not linger and shadow the new one;
- validates each member path (defence in depth on top of stdlib zip-slip sanitisation), failing
  closed on an absolute or traversing member;
- writes the version marker only after ALL members extract (partial failure leaves no marker, so the
  next session re-extracts), and clears stale markers and temp files.

It is non-blocking: any failure is logged and swallowed so a session is never broken. Stdlib only;
safe under `python -I`.
"""
import argparse
import errno
import os
import sys
import time
import zipfile

MARKER_PREFIX = ".skill-resources-"
MARKER_SUFFIX = ".ok"
LOCK_NAME = ".skill-resources.lock"
DEFAULT_ZIP_NAME = "skill-resources.zip"
DEFAULT_RETRIES = 8
DEFAULT_BACKOFF = 0.05  # seconds; doubles each retry, capped, so a lock clears without stalling.
_MAX_DELAY = 2.0
# Overall wall-clock budget for one extraction attempt, comfortably under the hook's 120s timeout,
# so a permanent (non-transient) failure aborts gracefully and retries next session instead of
# hanging the whole SessionStart.
DEFAULT_BUDGET_SECONDS = 90.0
# A lock older than this is treated as abandoned by a crashed process and stolen.
STALE_LOCK_SECONDS = 300.0
# Windows lock/share error codes worth retrying: ACCESS_DENIED, SHARING_VIOLATION, LOCK_VIOLATION.
_LOCK_WINERRORS = {5, 32, 33}


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
    but never past `deadline` (time.monotonic seconds). Re-raises a non-lock error immediately."""
    attempt = 0
    delay = backoff
    while True:
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - decide by kind, then re-raise
            past_deadline = deadline is not None and time.monotonic() >= deadline
            if not _is_lock_error(exc) or attempt >= retries or past_deadline:
                raise
            sleep(min(delay, _MAX_DELAY))
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
    """Fail closed on an absolute or traversing zip member (defence in depth; stdlib zipfile also
    strips these, but we reject rather than silently relocate a tampered member)."""
    target = os.path.join(dest, name)
    if not _is_within(dest, target):
        raise ValueError("unsafe zip member path: %r" % name)
    return target


def _rmtree(path):
    import shutil

    shutil.rmtree(path, ignore_errors=True)


def clear_markers(skill_dir):
    """Remove any older .skill-resources-*.ok markers and leftover .tmp files so only the current
    version's marker remains and a crashed extraction does not leave temp cruft."""
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


def _owned_top_dirs(members):
    """The top-level directories the zip owns (its members' first path segments)."""
    tops = set()
    for m in members:
        name = m.filename.replace("\\", "/")
        if m.is_dir() or "/" not in name:
            first = name.rstrip("/").split("/", 1)[0]
        else:
            first = name.split("/", 1)[0]
        if first:
            tops.add(first)
    return sorted(tops)


def extract_all(zip_path, skill_dir, version, retries=DEFAULT_RETRIES, backoff=DEFAULT_BACKOFF,
                sleep=time.sleep, extract=_extract_member, budget=DEFAULT_BUDGET_SECONDS):
    """Extract every member with per-file retry; write the marker only after ALL succeed.

    Removes the current-version marker up front (so a mid-extract failure - including a forced
    re-extract - never leaves a valid marker), wipes the runtime dirs the zip owns (so files removed
    in a newer version do not linger), validates each member path, and retries the zip open and each
    member on a transient lock within an overall time budget.
    """
    deadline = time.monotonic() + budget if budget else None
    # Invalidate first: any failure below leaves no valid marker, so the next session re-extracts.
    try:
        os.remove(marker_path(skill_dir, version))
    except OSError:
        pass
    zf = _retry(lambda: zipfile.ZipFile(zip_path), retries, backoff, sleep, deadline)
    with zf:
        members = zf.infolist()
        for name in [m.filename for m in members]:
            _safe_member_path(skill_dir, name)  # fail closed before we delete or write anything
        for top in _owned_top_dirs(members):
            _rmtree(os.path.join(skill_dir, top))
        for member in members:
            extract_member_with_retry(zf, member, skill_dir, retries, backoff,
                                      sleep=sleep, extract=extract, deadline=deadline)
    clear_markers(skill_dir)
    tmp = marker_path(skill_dir, version) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(version + "\n")
    os.replace(tmp, marker_path(skill_dir, version))


def _acquire_lock(skill_dir, sleep=time.sleep):
    """Acquire an exclusive extraction lock. Returns the lock path on success, or None if another
    session holds a fresh lock (this session should skip and let that one finish). A lock older than
    STALE_LOCK_SECONDS is assumed abandoned by a crashed process and stolen once."""
    lock = os.path.join(skill_dir, LOCK_NAME)
    for _attempt in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return lock
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(lock)
            except OSError:
                sleep(0.05)
                continue
            if age > STALE_LOCK_SECONDS:
                try:
                    os.remove(lock)
                except OSError:
                    return None
                continue
            return None
    return None


def _release_lock(lock):
    if lock:
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
    lock = _acquire_lock(skill_dir, sleep=sleep)
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
        _release_lock(lock)


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
        log("extraction failed for version %s: %s" % (args.version, exc))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
