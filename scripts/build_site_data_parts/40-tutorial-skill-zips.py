def sync_tutorial_images(root, check):
    src_dir = os.path.join(root, TUTORIAL_IMAGES_SRC)
    dst_dir = os.path.join(root, TUTORIAL_IMAGES_DST)
    drift = []
    if not os.path.isdir(src_dir):
        drift.extend(_orphans(dst_dir, [], check))
        return drift
    src_names = [n for n in sorted(os.listdir(src_dir)) if os.path.isfile(os.path.join(src_dir, n))]
    for name in src_names:
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, name)
        with open(src, "rb") as fh:
            data = fh.read()
        if check:
            existing = None
            if os.path.exists(dst):
                with open(dst, "rb") as fh:
                    existing = fh.read()
            if existing != data:
                drift.append(name)
        else:
            _safe_makedirs(dst_dir)
            with open(dst, "wb") as fh:
                fh.write(data)
    drift.extend(_orphans(dst_dir, src_names, check))
    return drift


def build_skill_zip_members(root, skill_dir_rel, skill_name):
    """The ordered [(arcname, bytes)] contents of a skill ZIP: every file under the shipped skill
    directory, placed under a single top-level `<skill_name>/` folder (with SKILL.md at its root),
    which is the structure Claude Desktop / claude.ai skill import expects. Sorted by arcname so the
    archive is deterministic.

    Files are the git-TRACKED set (exactly what `plugin install` ships), so untracked developer
    noise (`.DS_Store`, `__pycache__`, editor temp files) can never leak into the committed ZIP and
    break a clean-checkout `--check`. Outside a git checkout it falls back to a filtered walk."""
    skill_dir = os.path.join(root, skill_dir_rel.replace("/", os.sep))
    if not os.path.isdir(skill_dir):
        raise SystemExit("Claude Desktop skill ZIP: skill directory is missing: %s" % skill_dir_rel)
    rels = _tracked_skill_files(root, skill_dir_rel)
    if rels is None:
        rels = _walk_skill_files(skill_dir)
    members = []
    for rel in sorted(rels):
        full = os.path.join(skill_dir, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            continue
        with open(full, "rb") as fh:
            members.append(("%s/%s" % (skill_name, rel), _normalize_zip_member(fh.read())))
    members.sort(key=lambda m: m[0])
    _reject_duplicate_members(members)
    if not any(arcname == "%s/SKILL.md" % skill_name for arcname, _ in members):
        raise SystemExit("Claude Desktop skill ZIP: %s has no SKILL.md at the root of %s"
                         % (skill_name, skill_dir_rel))
    return members


def _reject_duplicate_members(members):
    """Fail closed if two members share an arcname. A ZIP may legally carry a path twice, so a
    duplicate in the member list means an upstream bug: it would bloat the shipped archive, and the
    only reason --check would notice is the ordered comparison below."""
    seen = set()
    for arcname, _ in members:
        if arcname in seen:
            raise SystemExit("Claude Desktop skill ZIP: duplicate member: %s" % arcname)
        seen.add(arcname)
    return members


def _normalize_zip_member(data):
    """Normalize a skill-ZIP member for cross-platform byte reproducibility. A text file's line
    endings are folded to LF so the packaged bytes do not depend on the checkout's line-ending
    config (a CRLF checkout, for example a Windows one where `.gitattributes eol=lf` is not honored,
    then produces the same ZIP as a Linux CI rebuild). A binary file - detected by a NUL byte - is
    returned byte-for-byte, since its CR/LF bytes are data, not line endings."""
    if b"\x00" in data:
        return data
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


# Untracked developer noise that must never be packaged into a skill ZIP (the git-tracked path
# already excludes all of this; these apply only to the non-git filtered-walk fallback).
_SKILL_ZIP_SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".idea", ".vscode",
                        ".pytest_cache", ".mypy_cache"}
_SKILL_ZIP_SKIP_NAMES = {".DS_Store", "Thumbs.db"}
_SKILL_ZIP_SKIP_SUFFIXES = (".pyc", ".pyo")


def _tracked_skill_files(root, skill_dir_rel):
    """The git-tracked files under the skill dir, relative to the skill dir (forward slashes), or
    None when git is unavailable or this is not a git checkout so the caller can fall back."""
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z", "--", skill_dir_rel],
                             capture_output=True, check=True).stdout.decode("utf-8")
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        return None
    prefix = skill_dir_rel.rstrip("/") + "/"
    rels = [p[len(prefix):] for p in out.split("\0") if p and p.startswith(prefix)]
    # `git ls-files` prints an UNMERGED path once per index stage (three times during a conflicted
    # merge or rebase). Refuse rather than dedupe: the working-tree bytes of a half-resolved file
    # may still carry conflict markers, and packaging them would smuggle a conflict into a binary
    # artifact no text-scanning gate can see.
    unmerged = sorted({rel for rel in rels if rels.count(rel) > 1})
    if unmerged:
        raise SystemExit(
            "Claude Desktop skill ZIP: %s has unmerged (conflicted) index entries; resolve the "
            "conflict and `git add` before rebuilding: %s"
            % (skill_dir_rel, ", ".join(unmerged[:5])))
    return rels or None


def _walk_skill_files(skill_dir):
    """Fallback file enumeration for a skill dir outside a git checkout: a filtered walk that skips
    well-known untracked noise so the archive stays deterministic."""
    rels = []
    for dirpath, dirs, names in os.walk(skill_dir):
        dirs[:] = [d for d in dirs if d not in _SKILL_ZIP_SKIP_DIRS]
        for name in names:
            if name in _SKILL_ZIP_SKIP_NAMES or name.endswith(_SKILL_ZIP_SKIP_SUFFIXES):
                continue
            full = os.path.join(dirpath, name)
            rels.append(os.path.relpath(full, skill_dir).replace(os.sep, "/"))
    return rels


def _skill_zip_bytes(members):
    """A deterministic ZIP of `members`: fixed timestamps, permissions, and creator system, plus a
    stable member order, so a rebuild from the same skill files is reproducible across platforms."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for arcname, data in _reject_duplicate_members(members):
            archive.writestr(_zip_member_info(arcname), data)
    return buf.getvalue()


def _zip_member_info(arcname):
    """The canonical ZipInfo the writer stamps on every member. The single source of truth for that
    stamping, so the writer and the --check comparison below cannot drift apart."""
    info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
    info.external_attr = 0o644 << 16
    info.create_system = 3  # Unix, so the host OS never changes the archive bytes.
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _zip_member_entry(info, data):
    """One comparable entry: the member's name and canonical stamps alongside its uncompressed
    bytes. The compressed bytes are deliberately excluded, since they vary with the host zlib."""
    return (info.filename, info.date_time, info.external_attr, info.create_system,
            info.compress_type, data)


try:
    import lzma as _lzma
    _LZMA_ERRORS = (_lzma.LZMAError,)
except ImportError:  # a Python built without liblzma can never raise it
    _LZMA_ERRORS = ()

# What "this committed archive cannot be read" looks like. Every one of these must yield None so
# --check reports the archive as stale and a write run replaces it, rather than crashing the
# required site gate: a bad container or an unsupported/encrypted member (BadZipFile,
# NotImplementedError, RuntimeError), a garbage compressed payload (zlib.error, lzma.LZMAError -
# bz2 raises OSError), a member name flagged UTF-8 that is not valid UTF-8 (UnicodeDecodeError), or
# member data that ends early (EOFError, which CPython's overlapped-entry check currently pre-empts
# with BadZipFile, so it is carried as a fail-safe rather than a reachable path).
# MemoryError and bare ValueError are deliberately NOT swallowed: those are resource exhaustion or
# a bug here, not a stale artifact.
_UNREADABLE_ZIP_ERRORS = (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError,
                          UnicodeDecodeError, EOFError, zlib.error) + _LZMA_ERRORS


def _zip_logical_members(path):
    """The ORDERED list of logical members of a committed ZIP - one `_zip_member_entry` per
    `infolist()` entry, in archive order - or None when it is missing or cannot be read (see
    `_UNREADABLE_ZIP_ERRORS`). Comparing logical members (not raw archive bytes) makes the --check
    drift guard immune to zlib/platform differences in the compressed container.

    The list is ordered, and each member's bytes are read by its ZipInfo rather than by name, so a
    REPEATED or REORDERED path registers as drift instead of being collapsed: a name->bytes map
    reported a bloated archive carrying every path three times (what a rebuild during a conflicted
    rebase used to produce) as in sync, so it survived every --check and write mode never rewrote
    it. Carrying the stamps too means an archive repacked with host timestamps/modes or stored
    members is likewise replaced."""
    if not os.path.isfile(path):
        return None
    try:
        with zipfile.ZipFile(path, "r") as archive:
            return [_zip_member_entry(info, archive.read(info)) for info in archive.infolist()]
    except _UNREADABLE_ZIP_ERRORS:
        return None


def sync_skill_zips(root, check, skills=None):
    """Generate (or, in check mode, verify) a downloadable ZIP of each Claude-Desktop skill under
    site/dist/skills/. In check mode a stale or missing ZIP is drift (compared by logical contents,
    so compression/platform differences never cause a false failure). In write mode the ZIP is only
    rewritten when its logical contents changed, so an unchanged skill never produces a spurious
    multi-MB diff. An orphaned ZIP (its skill was removed) is flagged/deleted."""
    skills = list(DESKTOP_SKILLS.values()) if skills is None else skills
    dst_dir = os.path.join(root, SITE_OUT, "skills")
    drift = []
    written = []
    for descriptor in skills:
        zip_name = descriptor["zip"].split("/")[-1]
        written.append(zip_name)
        dst = os.path.join(dst_dir, zip_name)
        members = build_skill_zip_members(root, descriptor["skill_dir"], descriptor["skill"])
        expected = [_zip_member_entry(_zip_member_info(arcname), data)
                    for arcname, data in members]
        if check:
            if _zip_logical_members(dst) != expected:
                drift.append(zip_name)
        elif _zip_logical_members(dst) != expected:
            _safe_makedirs(dst_dir)
            with open(dst, "wb") as fh:
                fh.write(_skill_zip_bytes(members))
    drift.extend(_orphans(dst_dir, set(written), check))
    return drift
