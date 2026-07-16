# --------------------------------------------------------------------------- #
# Packaging: the shipped pkg carries only a handful of files so the plugin
# installer writes very little. The bulky skill content (tools/, references/,
# docs/, vendor/, dist/, examples/) is assembled into a single deterministic
# skill-resources.zip that a SessionStart hook extracts on first run (retrying
# the transient Windows Defender file lock the installer does not). The shipped
# SKILL.md and LICENSE stay unzipped (the agent discovers the skill from SKILL.md
# before extraction), and the hook configs carry the version-stamped marker name.
# --------------------------------------------------------------------------- #
import io
import zipfile

PACKAGE_ZIP_NAME = "skill-resources.zip"
# The bulky content that is zipped and extracted on first run (STAGE-relative dir names). Only what
# the skill needs to OPERATE is shipped: the tools, the reference docs the agent consults, the
# runtime dist/ (NonPortable docs load it over file://), and the deck vendor templates. The tutorial
# (docs/) and example reports (examples/) are large (inlined screenshots/images) and are NOT needed
# to run the skill - they live on the site - so they stay in the repo staging tree but ship with
# neither the zip nor the installed package.
PACKAGE_BULKY_DIRS = ("tools", "references", "vendor", "dist")
# Files copied unzipped into the shipped skill dir (SKILL.md is discovered pre-extraction).
PACKAGE_SHIPPED_FILES = ("SKILL.md", "LICENSE")
# Extensions read as raw bytes; everything else is LF-normalized text so the zip is byte-identical
# regardless of the checkout's line endings (deterministic --check across platforms).
_PACKAGE_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".woff", ".woff2", ".ttf", ".otf",
    ".zip", ".pdf",
}
_HOOKS_MARKER_RE = re.compile(r"(\.skill-resources-)[0-9]+\.[0-9]+\.[0-9]+(\.ok)")
_HOOKS_VERSION_ARG_RE = re.compile(r"(--version[ =])[0-9]+\.[0-9]+\.[0-9]+")


def resources_zip_path(pkg_dir):
    return os.path.join(pkg_dir, PACKAGE_ZIP_NAME)


_PACKAGE_SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", "node_modules"}
_PACKAGE_SKIP_EXTS = {".pyc", ".pyo"}
_PACKAGE_SKIP_NAMES = {".DS_Store", "Thumbs.db"}


def _member_bytes(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in _PACKAGE_BINARY_EXTS:
        with open(path, "rb") as fh:
            return fh.read()
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        # Text: LF-normalize so the zip is byte-identical regardless of checkout line endings.
        return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    except UnicodeDecodeError:
        return raw


def _iter_zip_members(stage_dir):
    """Sorted (posix-rel, abspath) pairs for every file in the bulky dirs, so the zip is stable.
    Machine-specific and junk paths (__pycache__, *.pyc, .DS_Store, marker files) are excluded so
    the zip is deterministic and clean across build hosts."""
    members = []
    for d in PACKAGE_BULKY_DIRS:
        base = os.path.join(stage_dir, d)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            # Reject symlinked directories: a symlink in a build input could smuggle host-local
            # (out-of-repo) files into the shipped zip, breaking the "the zip is trusted because we
            # build it" assumption. Fail closed rather than follow it.
            for x in dirs:
                if os.path.islink(os.path.join(root, x)):
                    raise SystemExit(
                        "skill-resources.zip: refusing to package a symlinked directory: "
                        + os.path.relpath(os.path.join(root, x), stage_dir))
            dirs[:] = [x for x in dirs if x not in _PACKAGE_SKIP_DIRS]
            for name in files:
                if name in _PACKAGE_SKIP_NAMES:
                    continue
                if os.path.splitext(name)[1].lower() in _PACKAGE_SKIP_EXTS:
                    continue
                full = os.path.join(root, name)
                if os.path.islink(full):
                    raise SystemExit(
                        "skill-resources.zip: refusing to package a symlinked file: "
                        + os.path.relpath(full, stage_dir))
                rel = os.path.relpath(full, stage_dir).replace(os.sep, "/")
                members.append((rel, full))
    members.sort(key=lambda pair: pair[0])
    return members


def build_resources_zip_bytes(stage_dir):
    """Deterministic bytes for skill-resources.zip: sorted members, fixed timestamp/mode/system,
    fixed deflate level. Byte-stable for a given content set on a given host; --check compares the
    zip's CONTENTS (not raw container bytes) so a different zlib build cannot cause false drift."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel, full in _iter_zip_members(stage_dir):
            info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.create_system = 3  # unix, regardless of the build host
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, _member_bytes(full))
    return buf.getvalue()


def _zip_content_map(source):
    """Map member-name -> bytes for a zip given as a path or raw bytes. Platform-independent."""
    if isinstance(source, (bytes, bytearray)):
        with zipfile.ZipFile(io.BytesIO(source)) as zf:
            return {info.filename: zf.read(info.filename) for info in zf.infolist()}
    with open(source, "rb") as fh, zipfile.ZipFile(fh) as zf:
        return {info.filename: zf.read(info.filename) for info in zf.infolist()}


def _stamp_hooks(text, version):
    text = _HOOKS_MARKER_RE.sub(lambda m: m.group(1) + version + m.group(2), text)
    return _HOOKS_VERSION_ARG_RE.sub(lambda m: m.group(1) + version, text)


def package_text_stamps(stage_dir, pkg_dir, version):
    """Return {path: text} for the shipped-pkg TEXT artifacts (the unzipped SKILL.md and LICENSE
    copies, and the two hook configs with their version-stamped marker/arg). The zip itself is
    bytes and is handled separately."""
    out = {}
    for name in PACKAGE_SHIPPED_FILES:
        src = os.path.join(stage_dir, name)
        if os.path.exists(src):
            out[os.path.join(pkg_dir, name)] = read(src)
    plugin_dir = os.path.dirname(os.path.dirname(pkg_dir))  # pkg/
    for hook in (os.path.join(plugin_dir, "hooks.json"),
                 os.path.join(plugin_dir, "hooks", "hooks.json")):
        if os.path.exists(hook):
            out[hook] = _stamp_hooks(read(hook), version)
    return out


def write_package(stage_dir, pkg_dir, version):
    """Write the shipped-pkg artifacts (zip + text stamps). Returns the list of written paths."""
    os.makedirs(pkg_dir, exist_ok=True)
    written = []
    zip_path = resources_zip_path(pkg_dir)
    with open(zip_path, "wb") as fh:
        fh.write(build_resources_zip_bytes(stage_dir))
    written.append(zip_path)
    for path, text in package_text_stamps(stage_dir, pkg_dir, version).items():
        write(path, text)
        written.append(path)
    return written


def check_package(stage_dir, pkg_dir, version):
    """Return a list of drift descriptions for the shipped-pkg artifacts (empty when in sync).

    The zip is compared by CONTENTS (member set + each member's bytes), not raw container bytes, so a
    rebuild on a different platform/zlib cannot report false drift while still catching any real
    content change (a changed, added, or removed file)."""
    drift = []
    zip_path = resources_zip_path(pkg_dir)
    fresh = _zip_content_map(build_resources_zip_bytes(stage_dir))
    if not os.path.exists(zip_path):
        drift.append(PACKAGE_ZIP_NAME + " (missing)")
    else:
        try:
            have = _zip_content_map(zip_path)
        except (zipfile.BadZipFile, OSError):
            have = None
            drift.append(PACKAGE_ZIP_NAME + " (invalid or corrupt; rebuild)")
        if have is None:
            pass
        elif set(have) != set(fresh):
            missing = sorted(set(fresh) - set(have))
            extra = sorted(set(have) - set(fresh))
            detail = []
            if missing:
                detail.append("missing " + ", ".join(missing[:5]) + ("..." if len(missing) > 5 else ""))
            if extra:
                detail.append("stale " + ", ".join(extra[:5]) + ("..." if len(extra) > 5 else ""))
            drift.append(PACKAGE_ZIP_NAME + " (member set changed: " + "; ".join(detail) + ")")
        else:
            changed = sorted(n for n in fresh if have[n] != fresh[n])
            if changed:
                drift.append(PACKAGE_ZIP_NAME + " (out of date: "
                             + ", ".join(changed[:5]) + ("..." if len(changed) > 5 else "") + ")")
    for path, text in package_text_stamps(stage_dir, pkg_dir, version).items():
        label = os.path.relpath(path, os.path.dirname(os.path.dirname(pkg_dir)))
        if not os.path.exists(path):
            drift.append(label + " (missing)")
        elif _lf(read(path)) != _lf(text):
            drift.append(label + " (out of date)")
    return drift
