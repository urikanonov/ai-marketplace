#!/usr/bin/env python3
"""Unpack the commentable-html skill-resources.zip into the skill directory, once per version.

Ships unzipped alongside the SessionStart hook. The bulky skill payload (tools/, references/,
dist/, vendor/, examples/, docs/) is shipped as a single skill-resources.zip so the plugin
installer writes only a handful of files - which matters on Windows, where Defender briefly locks
each file as it is written and the installer aborts the whole install on the first transient lock
(the 'Access is denied. (os error 5)' failure). The hook's native fast path checks for the
version-stamped marker and only spawns this script when the resources are missing or stale (a fresh
install, or an update dropped a new zip), so it runs at most once per version. Extraction retries
each member with backoff so the same transient lock that defeats the installer does not defeat us,
and it is non-blocking: any failure is logged and swallowed so a session is never broken.

Standard library only; safe under `python -S -E`.
"""
import argparse
import errno
import os
import sys
import time
import zipfile

MARKER_PREFIX = ".skill-resources-"
MARKER_SUFFIX = ".ok"
DEFAULT_ZIP_NAME = "skill-resources.zip"
DEFAULT_RETRIES = 8
DEFAULT_BACKOFF = 0.05  # seconds; doubles each retry, capped, so a lock clears without stalling.
_MAX_DELAY = 2.0


def _is_lock_error(exc):
    """A transient file lock we should retry (Defender / antivirus / another scanner)."""
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, "winerror", None)
    if winerror in (5, 32):  # ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION
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


def _extract_member(zf, member, dest):
    zf.extract(member, dest)


def extract_member_with_retry(zf, member, dest, retries, backoff,
                              sleep=time.sleep, extract=_extract_member):
    """Extract one member, retrying a transient lock up to `retries` times with backoff."""
    attempt = 0
    delay = backoff
    while True:
        try:
            extract(zf, member, dest)
            return
        except Exception as exc:  # noqa: BLE001 - decide by kind, then re-raise
            if not _is_lock_error(exc) or attempt >= retries:
                raise
            sleep(min(delay, _MAX_DELAY))
            delay *= 2
            attempt += 1


def clear_markers(skill_dir):
    """Remove any older .skill-resources-*.ok markers so only the current version's remains."""
    try:
        names = os.listdir(skill_dir)
    except OSError:
        return
    for name in names:
        if name.startswith(MARKER_PREFIX) and name.endswith(MARKER_SUFFIX):
            try:
                os.remove(os.path.join(skill_dir, name))
            except OSError:
                pass


def extract_all(zip_path, skill_dir, version, retries=DEFAULT_RETRIES, backoff=DEFAULT_BACKOFF,
                sleep=time.sleep, extract=_extract_member):
    """Extract every member with per-file retry; write the marker only after ALL succeed.

    A partial extraction (an exhausted retry on any member) raises before the marker is written, so
    the next session sees no marker and retries the whole extraction.
    """
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            extract_member_with_retry(zf, member, skill_dir, retries, backoff,
                                      sleep=sleep, extract=extract)
    clear_markers(skill_dir)
    tmp = marker_path(skill_dir, version) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(version + "\n")
    os.replace(tmp, marker_path(skill_dir, version))


def run(skill_dir, version, zip_path=None, retries=DEFAULT_RETRIES, backoff=DEFAULT_BACKOFF,
        force=False, sleep=time.sleep, extract=_extract_member, log=None):
    """Extract the resources if the version marker is missing (or force). Returns 0 on no-op/success.

    The marker check here mirrors the hook's native fast path; it lets the lazy self-heal guard and
    tests reuse the same idempotency without spawning a shell.
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
    extract_all(zip_path, skill_dir, version, retries=retries, backoff=backoff,
                sleep=sleep, extract=extract)
    return 0


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
