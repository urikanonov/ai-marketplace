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
# Obsolete top-level dirs that a PRE-1.132 install unzipped into the skill dir and the current
# package no longer ships (moved online); pruned after a successful swap so an upgrade converges to
# the minimal runtime tree. Only pruned when NOT present in the freshly extracted runtime.
LEGACY_PRUNE_DIRS = ("docs", "examples")
# Names in the shipped skill dir that the swap must never overwrite from a (tampered) zip. Compared
# with str.casefold() (NOT os.path.normcase, which only folds case on Windows and is a no-op on
# macOS/Linux) because Windows and default macOS filesystems are case-insensitive, so a staging dir
# named e.g. `skill.md` resolves to the real `SKILL.md`.
_RESERVED_TOP_NAMES = {"SKILL.md", "LICENSE", "THIRD_PARTY_NOTICES.md", DEFAULT_ZIP_NAME}
_RESERVED_TOP_CASEFOLD = {n.casefold() for n in _RESERVED_TOP_NAMES}
# A fresh grace budget for rolling a failed swap back to the previous version. The main deadline is
# usually already spent (that is why the swap failed), so rollback needs its own window to clear a
# transient lock and restore the old tree.
ROLLBACK_GRACE_SECONDS = 30.0
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
# Bound a (possibly tampered) skill-resources.zip so extraction can never exhaust disk or memory:
# a hard cap on entry count, on each entry's expanded size, on the total expanded size, and on the
# overall compression ratio (a decompression-bomb signal). The shipped zip is ~3 MB with ~99
# entries expanding to ~6 MB, so these caps sit far above the real runtime yet reject a bomb. The
# caps are enforced by a preflight over infolist() BEFORE any bytes are written, AND again by a
# streaming per-entry byte cap during extraction, so a member whose header lies about its size
# cannot expand unbounded on disk.
MAX_ZIP_ENTRIES = 5000
MAX_ZIP_ENTRY_BYTES = 64 * 1024 * 1024      # 64 MB per member (expanded)
MAX_ZIP_TOTAL_BYTES = 256 * 1024 * 1024     # 256 MB expanded overall
MAX_ZIP_COMPRESSION_RATIO = 200
_EXTRACT_CHUNK = 1024 * 1024                 # stream members in 1 MB chunks so the cap check is
# reached before a giant member is fully read into memory.
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
    but never starting an attempt or sleeping past `deadline` (time.monotonic seconds). A non-lock
    error, an exhausted retry count, or an expired budget re-raises immediately."""
    attempt = 0
    delay = backoff
    while True:
        if deadline is not None and attempt > 0 and time.monotonic() >= deadline:
            raise TimeoutError("extraction budget exceeded")
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


def _preflight_zip(members):
    """Reject a tampered / decompression-bomb archive from its central directory BEFORE writing any
    bytes: too many entries, an entry whose declared expanded size is too large, a total expanded
    size over budget, or an overall compression ratio that signals a bomb. Raises ValueError with a
    message naming the breached cap so extract_all fails closed (no marker, previous version intact).
    Directory entries and the stored sizes come from the zip central directory; the streaming cap in
    _extract_member is the second line of defence for a member whose header understates its size."""
    if len(members) > MAX_ZIP_ENTRIES:
        raise ValueError("zip has too many entries: %d (limit %d)" % (len(members), MAX_ZIP_ENTRIES))
    total_uncompressed = 0
    total_compressed = 0
    for member in members:
        size = member.file_size
        if size > MAX_ZIP_ENTRY_BYTES:
            raise ValueError("zip member %r exceeds the per-entry size limit: %d (limit %d)"
                             % (member.filename, size, MAX_ZIP_ENTRY_BYTES))
        total_uncompressed += size
        total_compressed += member.compress_size
    if total_uncompressed > MAX_ZIP_TOTAL_BYTES:
        raise ValueError("zip expands to %d bytes, over the total limit %d"
                         % (total_uncompressed, MAX_ZIP_TOTAL_BYTES))
    if total_compressed > 0:
        ratio = total_uncompressed / float(total_compressed)
        if ratio > MAX_ZIP_COMPRESSION_RATIO:
            raise ValueError("zip compression ratio %.1f exceeds limit %d (decompression bomb?)"
                             % (ratio, MAX_ZIP_COMPRESSION_RATIO))


def _extract_member(zf, member, dest):
    """Stream one member to disk under a per-entry ACTUAL-byte cap so a member whose header lies
    about its size cannot expand unbounded. The write target is resolved through _safe_member_path
    (fail closed on traversal); on overflow the partial file is removed and ValueError is raised."""
    target = _safe_member_path(dest, member.filename)
    if member.is_dir() or member.filename.endswith("/"):
        os.makedirs(target, exist_ok=True)
        return 0
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    written = 0
    try:
        with zf.open(member) as src, open(target, "wb") as out:
            while True:
                chunk = src.read(_EXTRACT_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_ZIP_ENTRY_BYTES:
                    raise ValueError("zip member %r exceeds the per-entry byte cap %d while "
                                     "extracting" % (member.filename, MAX_ZIP_ENTRY_BYTES))
                out.write(chunk)
    except ValueError:
        try:
            os.remove(target)
        except OSError:
            pass
        raise
    return written


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


def _add_write_bit(p, is_dir):
    """Restore write (and, for a directory, execute/search) access on top of the existing mode so
    rmtree can descend and unlink. Adding to the current mode - rather than chmod-ing to S_IWRITE
    only - matters on POSIX, where clearing a directory's execute bit makes its children
    unreachable; S_IWRITE alone (0o200) is enough on Windows but would strip that bit on POSIX."""
    try:
        mode = os.stat(p).st_mode
    except OSError:
        mode = 0
    want = mode | stat.S_IWRITE | (stat.S_IXUSR if is_dir else 0)
    try:
        os.chmod(p, want)
    except OSError:
        pass


def _is_reparse(path):
    """True if path is a symlink OR a Windows junction / directory reparse point. os.path.islink
    misses junctions, so cleanup that only checked islink could rmtree/os.walk THROUGH a junction and
    hit its target (on Python < 3.12 shutil.rmtree lacked junction protection). st_file_attributes is
    available on Windows for all supported Python; on POSIX it is absent (only islink matters)."""
    if os.path.islink(path):
        return True
    try:
        attrs = os.lstat(path).st_file_attributes  # Windows only
    except (AttributeError, OSError):
        return False
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _unlink_reparse(path):
    """Remove a symlink/junction by unlinking the reparse point itself, never its target."""
    try:
        os.rmdir(path)  # a directory junction / dir symlink
    except OSError:
        try:
            os.remove(path)  # a file symlink
        except OSError:
            pass


def _prune_nested_reparse(path):
    """Unlink every reparse point (symlink/junction) NESTED anywhere under path, so a subsequent
    shutil.rmtree cannot traverse into a junction's external target and delete files there. On
    Python < 3.12 shutil.rmtree lacked this protection (bpo-31818), and os.walk's followlinks=False
    does not stop it descending into Windows junctions (os.path.islink is False for them), so we walk
    top-down and prune each junction from `dirs` IN PLACE (which stops os.walk descending into it)
    after unlinking it.

    Returns True only if the tree is now FREE of nested reparse points (safe to shutil.rmtree). If a
    junction could not be unlinked (e.g. a transient lock), OR a subtree could not be scanned (so a
    junction might hide there unseen), returns False - the caller MUST NOT call shutil.rmtree, or it
    could traverse a surviving junction into its external target."""
    if _is_reparse(path):
        return True  # the caller handles a top-level reparse point itself; nothing nested to prune
    state = {"clean": True}

    def _onerr(_exc):
        # os.walk cannot scan a directory: a junction could hide unseen inside it, so fail closed.
        state["clean"] = False

    for root, dirs, files in os.walk(path, topdown=True, onerror=_onerr):
        keep = []
        for d in dirs:
            p = os.path.join(root, d)
            if _is_reparse(p):
                _unlink_reparse(p)  # remove the junction; do NOT descend into its target
                if os.path.lexists(p):
                    state["clean"] = False  # unlink failed (locked); do not let rmtree follow it
            else:
                keep.append(d)
        dirs[:] = keep
    return state["clean"]


def _make_writable(path):
    """Best-effort: restore write/execute access across a tree so an AV-quarantined-and-restored
    file (which can come back read-only on Windows, or with cleared bits on POSIX) does not defeat
    rmtree with a permanent EACCES. A reparse point (symlink/junction) is left alone - never walked
    into - so we do not chmod its target's files."""
    try:
        if _is_reparse(path):
            return
        if os.path.isfile(path):
            _add_write_bit(path, is_dir=False)
            return
        _add_write_bit(path, is_dir=True)
        for root, dirs, files in os.walk(path):
            # Prune reparse points (symlinks/junctions) from the walk IN PLACE so os.walk does not
            # descend into their targets - os.walk's followlinks=False only skips POSIX symlinks, not
            # Windows junctions (os.path.islink is False for a junction), so without this it would
            # walk into and chmod files under the junction's external target.
            dirs[:] = [d for d in dirs if not _is_reparse(os.path.join(root, d))]
            for name in dirs:
                _add_write_bit(os.path.join(root, name), is_dir=True)
            for name in files:
                _add_write_bit(os.path.join(root, name), is_dir=False)
    except OSError:
        pass


def _rmtree_retry(path, retries, backoff, sleep, deadline):
    """Remove a directory tree, retrying a transient lock (do NOT ignore_errors, so a Defender lock
    is retried rather than silently leaving files behind). Clears read-only attributes first. A
    reparse point (symlink/junction) is unlinked as itself, never followed into its target."""
    if not os.path.lexists(path):  # lexists is True for a broken symlink/junction too
        return
    _make_writable(path)

    def _rm():
        if _is_reparse(path):
            _unlink_reparse(path)
            if os.path.lexists(path):  # unlink failed (locked); raise so _retry retries it
                raise OSError(errno.EBUSY, "reparse point still present after unlink", path)
        elif os.path.isfile(path):
            os.remove(path)
        else:
            # Unlink nested junctions FIRST; only rmtree if none survived, else raise so _retry
            # retries (never let shutil.rmtree traverse a surviving junction into its target).
            if not _prune_nested_reparse(path):
                raise OSError(errno.EBUSY, "nested reparse point could not be unlinked under", path)
            shutil.rmtree(path)
    try:
        _retry(_rm, retries, backoff, sleep, deadline)
    except FileNotFoundError:
        pass


def clear_markers(skill_dir):
    """Remove any .skill-resources-*.ok markers and leftover .tmp files so a stale or crashed
    extraction does not leave a misleading marker or temp cruft. A path that is unexpectedly a
    directory (tampering, or a crash that landed a dir under the marker name) is removed too, so a
    later marker write is never blocked by a same-named directory."""
    try:
        names = os.listdir(skill_dir)
    except OSError:
        return
    for name in names:
        if not name.startswith(MARKER_PREFIX):
            continue
        if name.endswith(MARKER_SUFFIX) or name.endswith(".tmp"):
            p = os.path.join(skill_dir, name)
            try:
                os.remove(p)
            except OSError:
                # a same-named directory (or a reparse point) under the marker name
                if _is_reparse(p):
                    _unlink_reparse(p)
                elif _prune_nested_reparse(p):  # only rmtree if no nested junction survived
                    shutil.rmtree(p, ignore_errors=True)


def _write_marker(skill_dir, version, retries=DEFAULT_RETRIES, backoff=DEFAULT_BACKOFF,
                  sleep=time.sleep, deadline=None):
    """Write the version marker with a no-follow temp create (so a pre-planted `.tmp` symlink cannot
    redirect the write), then move it into place, retrying a transient lock on the final rename so a
    Defender lock on the just-written temp does not cost an unnecessary full re-extract. The temp
    name is pid-unique so a leftover `.tmp` locked from a crashed run cannot block the O_EXCL create
    (clear_markers still sweeps any stale one)."""
    tmp = marker_path(skill_dir, version) + ".%d.tmp" % os.getpid()
    try:
        os.remove(tmp)
    except OSError:
        pass
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, (version + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    _retry(lambda: os.replace(tmp, marker_path(skill_dir, version)),
           retries, backoff, sleep, deadline)


def _is_swappable(skill_dir, entry):
    """A staging top-level entry is installed only if it is a real directory and not a reserved or
    bookkeeping name, so a (tampered or accidental) zip cannot overwrite SKILL.md/LICENSE/
    THIRD_PARTY_NOTICES.md/the zip (matched case-insensitively for case-insensitive filesystems), any
    dot-prefixed marker/lock/staging file, or collide with a `<dir>.skill-resources-old` backup name."""
    if entry.startswith(".") or entry.endswith(BACKUP_SUFFIX):
        return False
    if entry.casefold() in _RESERVED_TOP_CASEFOLD:
        return False
    return os.path.isdir(os.path.join(skill_dir, STAGING_NAME, entry))


def _cleanup_leftovers(skill_dir, retries, backoff, sleep, deadline):
    """Recover leftovers from a prior crashed run: restore a backup whose live dir went missing
    (a crash between rename-aside and move-in), then remove leftover staging, orphan backup dirs,
    and stale-lock sidecars so they cannot accumulate or confuse a fresh extraction."""
    _rmtree_retry(os.path.join(skill_dir, STAGING_NAME), retries, backoff, sleep, deadline)
    try:
        names = os.listdir(skill_dir)
    except OSError:
        return
    for name in sorted(names):
        p = os.path.join(skill_dir, name)
        if name.endswith(BACKUP_SUFFIX):
            live = os.path.join(skill_dir, name[:-len(BACKUP_SUFFIX)])
            if not os.path.lexists(live):  # lexists catches a broken symlink/junction at live too
                # A crash left the live dir missing but its backup intact: restore it (retried). Do
                # NOT swallow a restore failure - if we did, the swap below would still delete this
                # backup via its pre-loop _rmtree_retry(bak), so the "keep the only copy" intent
                # would be a lie. Instead let the exception abort this extraction so the backup
                # survives for the next session to retry (which re-extracts from the zip regardless).
                _retry(lambda p=p, live=live: os.replace(p, live),
                       retries, backoff, sleep, deadline)
                continue
            # The live dir exists, so the swap completed and this backup is orphan cruft: remove it.
            _rmtree_retry(p, retries, backoff, sleep, deadline)
        elif name.startswith(LOCK_NAME + ".stale."):
            try:
                os.remove(p)
            except OSError:
                pass


def _swap_into_place(skill_dir, staging, retries, backoff, sleep, deadline):
    """Install each extracted top-level directory transactionally: rename the existing dir aside to a
    backup, move the new one in, then delete the backups. If ANY entry fails, roll every touched
    entry back to the previous version (with the same lock-retry discipline and a fresh grace
    budget, since the main deadline may be spent), so the installed skill is either fully upgraded or
    left exactly as it was - never a mixed or missing state."""
    entries = [e for e in sorted(os.listdir(staging)) if _is_swappable(skill_dir, e)]
    if not entries:
        # A truncated/empty/wrong zip yielded no installable directory. Do NOT proceed to mark this
        # a success (that would permanently cache a broken install); raise so extract_all writes no
        # marker and the next session re-extracts.
        raise RuntimeError("skill-resources.zip contained no installable directories")
    touched = []  # (dst, bak_or_None): entries whose new dir we began moving into place
    try:
        for entry in entries:
            src = os.path.join(staging, entry)
            dst = os.path.join(skill_dir, entry)
            bak = dst + BACKUP_SUFFIX
            _rmtree_retry(bak, retries, backoff, sleep, deadline)
            had_old = os.path.lexists(dst)  # lexists so a broken junction at dst is renamed aside too
            if had_old:
                _retry(lambda d=dst, b=bak: os.replace(d, b), retries, backoff, sleep, deadline)
            touched.append((dst, bak if had_old else None))
            _retry(lambda s=src, d=dst: os.replace(s, d), retries, backoff, sleep, deadline)
    except BaseException:
        rb_deadline = time.monotonic() + ROLLBACK_GRACE_SECONDS
        for dst, bak in reversed(touched):
            # Isolate each entry so one stubborn lock cannot cancel the remaining restores; the
            # original swap exception is still re-raised below (no marker -> self-heal next session).
            try:
                _rmtree_retry(dst, retries, backoff, sleep, rb_deadline)  # remove new/partial
                if bak is not None:
                    _retry(lambda d=dst, b=bak: os.replace(b, d), retries, backoff, sleep,
                           rb_deadline)  # restore the previous version
            except Exception:  # noqa: BLE001 - best effort; keep restoring the rest
                pass
        raise
    for _dst, bak in touched:
        if bak is not None:
            # Best-effort: the swap already fully succeeded, so a transient lock on an orphan backup
            # must NOT abort the marker write (that would needlessly re-extract next session). Any
            # backup left behind is removed by _cleanup_leftovers on the next run.
            try:
                _rmtree_retry(bak, retries, backoff, sleep, deadline)
            except Exception:  # noqa: BLE001 - orphan cruft; cleaned up next session
                pass
    return entries


def _prune_legacy(skill_dir, installed, retries, backoff, sleep, deadline):
    """Remove obsolete top-level dirs a PRE-1.132 install unzipped into the skill dir that the
    current package no longer ships (the tutorial `docs/` and worked `examples/`, now published
    online), so an in-place upgrade converges to the minimal runtime tree instead of leaving stale
    content behind. Guarded: a name is only pruned if the CURRENT extraction did NOT install it (so a
    future version that re-adds one of these dirs to the zip is never deleted), and only real
    directories - never a control file or a reparse point's target - are touched."""
    for name in LEGACY_PRUNE_DIRS:
        if name in installed:
            continue
        p = os.path.join(skill_dir, name)
        if os.path.isdir(p) and not _is_reparse(p):
            try:
                _rmtree_retry(p, retries, backoff, sleep, deadline)
            except Exception:  # noqa: BLE001 - best effort; stale cruft, never fatal
                pass


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
    _cleanup_leftovers(skill_dir, retries, backoff, sleep, deadline)
    staging = os.path.join(skill_dir, STAGING_NAME)
    os.makedirs(staging, exist_ok=True)
    try:
        zf = _retry(lambda: zipfile.ZipFile(zip_path), retries, backoff, sleep, open_deadline)
        with zf:
            members = zf.infolist()
            _preflight_zip(members)  # fail closed on a bomb/tampered zip before writing anything
            for member in members:
                _safe_member_path(staging, member.filename)  # fail closed before writing anything
            for member in members:
                extract_member_with_retry(zf, member, staging, retries, backoff,
                                          sleep=sleep, extract=extract, deadline=deadline)
        _swapped = _swap_into_place(skill_dir, staging, retries, backoff, sleep, deadline)
        _prune_legacy(skill_dir, _swapped, retries, backoff, sleep, deadline)
    finally:
        # Only rmtree staging if no nested junction survived pruning (never traverse one out of it).
        if _prune_nested_reparse(staging):
            shutil.rmtree(staging, ignore_errors=True)
    # The swap succeeded; give the marker write a fresh grace budget so a transient lock on its
    # rename does not waste the whole successful extraction (and re-extract needlessly next session).
    _write_marker(skill_dir, version, retries, backoff, sleep,
                  time.monotonic() + ROLLBACK_GRACE_SECONDS)


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
    # Only remove the lock if we can POSITIVELY read our own pid from it. If the read fails, the
    # content is empty, or it carries another pid (a concurrent session stole ours and created its
    # own), we leave it alone rather than risk deleting another session's lock. A leaked lock of our
    # own is harmless: it is younger than STALE_LOCK_SECONDS and clears on a later run.
    try:
        with open(lock, "rb") as fh:
            content = fh.read().strip()
    except OSError:
        return
    if content == str(os.getpid()).encode("ascii"):
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
    if os.path.isfile(marker) and not force:
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
        if os.path.isfile(marker) and not force:
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
