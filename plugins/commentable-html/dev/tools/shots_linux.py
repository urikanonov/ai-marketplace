#!/usr/bin/env python3
"""Render the tutorial screenshots in ONE pinned container - locally and in CI (CMH-BUILD-16).

The committed PNGs under ``plugins/commentable-html/docs/assets/`` are produced by a browser, and
font rasterization is decided by the OS image the browser runs on, not by the browser version.
Two renderers therefore have to be identical down to their font and fontconfig packages, or a
regeneration that passes every local check still fails the required ``playwright-heavy`` CI job.

This tool removes the second renderer. Every render and every check - on Windows, macOS, Linux, and
on the CI runner - happens inside the SAME pinned ``mcr.microsoft.com/playwright`` image, so the
authority is one fixed environment rather than two that must agree:

* The image is pinned on both axes that decide the pixels: the ``@playwright/test`` version resolved
  in ``package-lock.json`` (the chromium binary) and the Ubuntu release in the image variant (the
  fonts). Neither is hardcoded at a call site.
* It is pinned by DIGEST, not just by tag: ``tools/shots-image.lock`` records the sha256 the tag
  resolved to, so a registry rebuild of that tag (a newer base OS, different font packages) cannot
  silently change the renderer. Re-record it with ``npm run shots:digest`` after a Playwright bump;
  until then the tool degrades to the tag and says so rather than hard-failing.
* ``--platform linux/amd64`` so an Apple Silicon host does not render with the arm64 stack.

Docker is therefore the renderer, but it is not a blanket requirement for development: only the
shots commands need it. ``npm run shots:check`` (which ``npm test`` runs) SKIPS with a note when
Docker is unavailable, so a developer without Docker is never blocked - but it NEVER skips in CI,
where it is the required drift gate, and the write direction never skips anywhere.

``--native`` is an explicit, non-authoritative escape hatch that renders with the host browser.

Usage (from ``plugins/commentable-html/dev``)::

    npm run shots            # regenerate in the pinned container
    npm run shots:check      # verify; skips with a note when Docker is unavailable
    npm run shots:digest     # re-pin the container by digest after a @playwright/test bump

Without Docker a stale screenshot is still FIXABLE, not merely detectable (CMH-BUILD-28). The
failing CI gate uploads what the pinned container rendered as the ``tutorial-shots-drift``
artifact, and those bytes are the authoritative render for that commit::

    python tools/shots_linux.py --adopt-run <run-id>   # fetch with gh, then adopt
    python tools/shots_linux.py --adopt <dir>          # adopt an artifact already unzipped

That matters because a stale shot on ``main`` reddens a required check for EVERY open pull request.
Adopting is a re-baseline from the same renderer the gate uses, never a verdict: only
``shots:check`` in the container says the screenshots are right.

Standard library only.
"""
import argparse
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import zlib

DEV_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(DEV_DIR)))
CAPTURE = os.path.join("tools", "capture_tutorial.mjs")
# The image family. Only the VERSION varies, and it is read from the lockfile - see image_ref().
IMAGE_REPO = "mcr.microsoft.com/playwright"
IMAGE_VARIANT = "noble"
# The image is multi-arch; without this an Apple Silicon host would render with the arm64 stack.
IMAGE_PLATFORM = "linux/amd64"
LOCK_KEY = "node_modules/@playwright/test"
# The recorded digest of the image tag above: what makes the renderer immutable rather than
# merely named. Written by --record-digest, read on every run.
IMAGE_LOCK = os.path.join(DEV_DIR, "tools", "shots-image.lock")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
GUIDE = "docs/testing-guidelines.md"
# The artifact the required playwright-heavy job uploads when the drift gate fails. It carries the
# PNGs the PINNED container just rendered, so it is the authoritative render for this commit even on
# a machine that cannot run the renderer at all.
DRIFT_ARTIFACT = "tutorial-shots-drift"
PLUGIN_DIR = os.path.dirname(DEV_DIR)
# The committed baselines the capture writes and the gate compares against.
SHOTS_DIR = os.path.join(PLUGIN_DIR, "docs", "assets")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
RUN_ID_RE = re.compile(r"\A[0-9]+\Z")
# A committed screenshot is well under 1 MB. This is not a tuning knob, it is a ceiling that keeps a
# hostile or mistaken artifact from being read wholesale into memory; it leaves ~60x headroom.
MAX_SHOT_BYTES = 32 * 1024 * 1024
# Set for the capture script so it knows a guarded renderer invoked it; capture_tutorial.mjs
# refuses to render or verify the COMMITTED screenshots without it, which is what stops a raw
# `node capture_tutorial.mjs` from rewriting them with the host's fonts.
RENDERER_ENV = "CMH_SHOTS_RENDERER"
# With --user the invoking uid may have no passwd entry in the image, and docker then points HOME
# at an unwritable "/". Pinning it keeps every run identical and writable rather than depending on
# the runner's uid happening to match a user the image ships.
CONTAINER_HOME = "/tmp"

NATIVE_WARNING = (
    "shots_linux: --native renders with THIS machine's browser and fonts, which is NOT the "
    "authoritative renderer - the committed screenshots and the required CI gate both use the "
    "pinned container. Treat the result as provisional and verify with 'npm run shots:check'.\n")


class ShotsError(Exception):
    """A precondition failed with an operator-actionable explanation."""


def _in_ci():
    """True on a CI runner.

    This no longer selects a renderer (the container renders everywhere); it only means "this run
    is a gate", which forbids the check from skipping itself.
    """
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false", "no")


def pinned_playwright_version(dev_dir):
    """The EXACT @playwright/test version from package-lock.json.

    package.json carries a semver RANGE; the lockfile carries what is actually
    installed and therefore what the suite runs, so it is the only value that keeps the container's
    browser in lockstep with the tests.
    """
    lock = os.path.join(dev_dir, "package-lock.json")
    try:
        with open(lock, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ShotsError("could not read %s (%s); run 'python scripts/setup_dev.py'" % (lock, exc))
    version = (data.get("packages") or {}).get(LOCK_KEY, {}).get("version")
    if not version:
        raise ShotsError("%s has no resolved '%s' version; run 'npm install' in %s"
                         % (lock, LOCK_KEY, dev_dir))
    return version


def image_ref(version):
    return "%s:v%s-%s" % (IMAGE_REPO, version, IMAGE_VARIANT)


def read_image_lock(path=None):
    """The recorded {image, digest}, or {} when nothing usable is recorded.

    A missing or malformed lock is "no digest recorded", never an error: the run then falls back to
    the tag with a loud note, so a Playwright bump degrades the pin instead of breaking the render.
    """
    path = IMAGE_LOCK if path is None else path
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Keep only well-typed values: a hand-edited or tool-written lock with a non-string digest must
    # take the documented mutable-tag path, never raise on a caller that expects text.
    return {"image": _text(data.get("image")), "digest": _text(data.get("digest"))} if data else {}


def _text(value):
    return value if isinstance(value, str) else None


def write_image_lock(path, image, digest):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump({"image": image, "digest": digest}, handle, indent=2)
        handle.write("\n")


def parse_repo_digest(repo_digests, repo=IMAGE_REPO):
    """The sha256 digest docker reports for OUR repository, or None.

    Scoped to the pinned repository so a stray entry for a differently-named mirror can never be
    recorded as this image's identity.
    """
    for entry in repo_digests or []:
        if not isinstance(entry, str) or not entry.startswith(repo + "@"):
            continue
        digest = entry.split("@", 1)[1]
        if DIGEST_RE.match(digest):
            return digest
    return None


def resolved_image(tag, lock=None):
    """(reference to run, warning or None): the digest pin when it covers this exact tag.

    Falling back to the tag keeps a @playwright/test bump from breaking every render, but the
    warning names the exact command that restores the immutable pin.
    """
    lock = read_image_lock() if lock is None else (lock or {})
    recorded = _text(lock.get("image"))
    digest = (_text(lock.get("digest")) or "").strip()
    if recorded == tag and DIGEST_RE.match(digest):
        return "%s@%s" % (IMAGE_REPO, digest), None
    if recorded == tag:
        why = "its recorded digest %r is not a sha256 reference" % digest
    elif recorded:
        why = "the lock pins %s" % recorded
    else:
        why = "no digest is recorded"
    warning = ("shots_linux: falling back to the MUTABLE tag %s (%s). A registry can rebuild a tag "
               "on a newer base OS with different fonts, so re-pin the renderer with "
               "'npm run shots:digest' and commit tools/shots-image.lock." % (tag, why))
    return tag, warning


def docker_command(repo_root, dev_rel, image, extra_args, uid_gid=None, ci=False):
    """The docker argv that runs the capture inside the pinned image against the mounted worktree.

    The repo is mounted (not copied) so the regenerated PNGs land straight back in the worktree.
    On a Linux host (including the CI runner, whose workspace is owned by the runner user) the
    container runs as the invoking user, otherwise every PNG it rewrites - and the scratch dir it
    creates - would be left root-owned. `ci` forwards the CI marker the capture script reads to
    double its settle deadlines; docker inherits no host environment, so without it a CI run would
    silently get the tighter, flakier timings.
    """
    workdir = "/repo/" + dev_rel.replace("\\", "/")
    inner = "node " + shlex.quote(CAPTURE.replace("\\", "/"))
    if extra_args:
        inner += " " + " ".join(shlex.quote(a) for a in extra_args)
    # --ipc=host is the image's documented invocation: the default 64MB /dev/shm can crash chromium
    # mid-capture, which on the required gate would mean an unreproducible stack trace.
    cmd = ["docker", "run", "--rm", "--platform", IMAGE_PLATFORM, "--ipc=host"]
    if uid_gid:
        cmd += ["--user", "%s:%s" % uid_gid]
    cmd += ["-e", "HOME=" + CONTAINER_HOME, "-e", "%s=container" % RENDERER_ENV]
    # Test-only fault injection (CMH-BUILD-18). docker inherits no host environment, so the
    # hook that forces a mid-capture failure has to be passed through explicitly or the
    # keep-the-evidence test could never drive the real check.
    if os.environ.get("CMH_SHOTS_FAIL_AFTER_SCENE"):
        cmd += ["-e", "CMH_SHOTS_FAIL_AFTER_SCENE=" + os.environ["CMH_SHOTS_FAIL_AFTER_SCENE"]]
    if ci:
        cmd += ["-e", "CI=true"]
    cmd += [
        "-v", "%s:/repo" % repo_root,
        "-w", workdir,
        image,
        "bash", "-lc", "cd " + shlex.quote(workdir) + " && " + inner,
    ]
    return cmd


def _host_uid_gid():
    """The uid:gid to run the container as, or None to leave docker's default.

    Only a native Linux daemon needs this: it writes bind-mounted files as the container user, so
    without it every regenerated PNG is left root-owned. Docker Desktop (Windows/macOS) already maps
    ownership, and passing it a host uid that has no passwd entry in the image is actively harmful.
    """
    if not sys.platform.startswith("linux"):
        return None
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:
        return None
    return (getuid(), getgid())


def _deps_installed(dev_dir=None):
    dev_dir = DEV_DIR if dev_dir is None else dev_dir
    return os.path.isdir(os.path.join(dev_dir, "node_modules", "@playwright", "test"))


def _docker_daemon_ok():
    try:
        proc = subprocess.run(["docker", "version"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        # A wedged or unreachable daemon must fail fast: hanging here would burn a CI job's whole
        # timeout instead of printing the actionable message.
        return False
    return proc.returncode == 0


def renderer_available():
    """True when the pinned container can actually run here (docker present, daemon up).

    The single shared answer to "can this machine render the screenshots correctly?", so
    scripts/rebuild_all.py and the shots commands can never disagree.
    """
    return bool(shutil.which("docker")) and _docker_daemon_ok()


def _run(cmd, env=None, cwd=None):
    return subprocess.run(cmd, env=env, cwd=cwd).returncode


def _capture(cmd, env=None, cwd=None):
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              env=env, cwd=cwd)
    except OSError:
        return None
    return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else None


def _fail(message):
    sys.stderr.write(message.rstrip() + "\n")
    return 2


def _docker_missing_message(image):
    return (
        "shots_linux: Docker is not installed (or 'docker' is not on PATH).\n"
        "\n"
        "  Why Docker is involved: the committed tutorial screenshots are rendered in ONE pinned\n"
        "  container - the same one the required CI job validates them with - because browser font\n"
        "  rasterization is decided by the OS image. Rendering them with this machine's browser\n"
        "  instead would pass every local check and then fail that job.\n"
        "\n"
        "  Options:\n"
        "    1. Install Docker Desktop / Docker Engine, then re-run 'npm run shots'.\n"
        "       It runs the pinned image %s (derived from package-lock.json).\n"
        "    2. Leave the PNGs untouched: if your change does not affect them, restore them with\n"
        "       'git checkout origin/main -- plugins/commentable-html/docs/assets'.\n"
        "\n"
        "  See %s ('Regenerating the tutorial screenshots')." % (image, GUIDE))


def _daemon_down_message(image):
    return (
        "shots_linux: Docker is installed but its daemon is not responding.\n"
        "\n"
        "  'docker version' failed, so the pinned renderer cannot start. Start Docker Desktop (or\n"
        "  'sudo systemctl start docker') and re-run the same command.\n"
        "  The pinned image is %s.\n"
        "\n"
        "  See %s ('Regenerating the tutorial screenshots')." % (image, GUIDE))


def _deps_missing_message(native):
    where = ("capture_tutorial.mjs imports @playwright/test."
             if native else
             "capture_tutorial.mjs imports @playwright/test, and the container reuses the mounted\n"
             "  node_modules rather than installing its own.")
    return (
        "shots_linux: the commentable-html dev node_modules are not installed.\n"
        "\n"
        "  %s Run:\n"
        "\n"
        "    python scripts/setup_dev.py\n"
        "\n"
        "  then re-run the same command." % where)


def _skip_message(reason, image):
    return ("shots_linux: screenshot check skipped (%s, and the committed screenshots are rendered "
            "ONLY in the pinned container %s - comparing against this machine's renderer would be "
            "meaningless). Start Docker and re-run 'npm run shots:check'; CI runs that same "
            "container as the authoritative gate." % (reason, image))


def _report_pin(warning):
    """Print a digest-pin warning; return False when it must be FATAL instead.

    Degrading to a mutable tag is a developer convenience so a @playwright/test bump never leaves a
    contributor unable to regenerate. In CI it is not acceptable: the gate must validate against the
    exact recorded image, not whatever the registry serves that day.
    """
    if _in_ci():
        sys.stderr.write(warning.replace("falling back to the MUTABLE tag",
                                         "REFUSING to fall back to the MUTABLE tag in CI") + "\n")
        return False
    sys.stderr.write(warning + "\n")
    return True


def _regular_file(path):
    """True only for a real file: not a symlink, not a device, not a directory.

    An artifact is a downloaded ZIP or, for --adopt, any directory the operator names, so a symlink
    inside it would make the read pull a file from OUTSIDE the tree and install its bytes as a
    baseline. Refusing non-regular entries keeps "the bytes come from this artifact" true here
    rather than resting on an external tool happening to dereference links at upload time.
    """
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _inside(root, path):
    """True when `path` really resolves inside `root` (after links and junctions)."""
    try:
        root_real = os.path.realpath(root)
        path_real = os.path.realpath(path)
        return os.path.commonpath([root_real, path_real]) == root_real
    except (OSError, ValueError):
        return False


def png_problem(data):
    """None when `data` is a usable PNG, else a short reason.

    The gate DECODES these files and this installs the one it will decode, so a signature test is
    not enough: a truncated download keeps the 8-byte signature and would red the drift gate
    permanently with an undecodable baseline. Walk the chunk stream instead - stdlib only, no image
    decoder - and require a well-formed `IHDR..IDAT..IEND` with correct CRCs, a compressed stream
    that actually inflates, and nothing trailing after IEND. That makes the refusal message
    literally true, and rejects data smuggled after the image ends.
    """
    if not data.startswith(PNG_MAGIC):
        return "not a PNG (wrong signature)"
    pos, first, seen_end = len(PNG_MAGIC), True, False
    idat = zlib.decompressobj()
    idat_chunks = 0
    while pos < len(data):
        if pos + 8 > len(data):
            return "truncated: a chunk header runs past the end of the file"
        length = int.from_bytes(data[pos:pos + 4], "big")
        ctype = data[pos + 4:pos + 8]
        kind = ctype.decode("latin-1")
        body = pos + 8
        # Compare against the remaining length so a huge declared size is refused before any slice.
        if length > len(data) - body - 4:
            return "truncated: chunk %r runs past the end of the file" % kind
        if first:
            if ctype != b"IHDR":
                return "malformed: the first chunk is %r, not IHDR" % kind
            if length != 13:
                return "malformed: IHDR is %d bytes, not 13" % length
            width = int.from_bytes(data[body:body + 4], "big")
            height = int.from_bytes(data[body + 4:body + 8], "big")
            if not width or not height:
                return "malformed: the image is %dx%d" % (width, height)
        expect = int.from_bytes(data[body + length:body + length + 4], "big")
        if zlib.crc32(data[pos + 4:body + length]) & 0xFFFFFFFF != expect:
            return "corrupt: the CRC of chunk %r does not match" % kind
        if ctype == b"IDAT":
            idat_chunks += 1
            try:
                # Inflate and DISCARD: this asks "does the pixel stream decompress?" without
                # holding a decompressed frame (several MB per shot) in memory.
                idat.decompress(data[body:body + length], 1)
                while idat.unconsumed_tail:
                    idat.decompress(idat.unconsumed_tail, 1 << 16)
            except zlib.error as exc:
                return "corrupt: the compressed image data does not inflate (%s)" % exc
        first = False
        pos = body + length + 4
        if ctype == b"IEND":
            if length:
                return "malformed: IEND carries %d bytes of data" % length
            seen_end = True
            break
    if not seen_end:
        return "truncated: the image has no IEND chunk"
    if not idat_chunks:
        return "malformed: the image has no IDAT chunk"
    if pos != len(data):
        return "malformed: %d byte(s) of data follow the IEND chunk" % (len(data) - pos)
    return None


def find_artifact_shots(root):
    """{file name: path} for every candidate shot in an unzipped drift artifact.

    The artifact unzips to a ``<pid>/<scene>/`` tree, so the walk is depth-agnostic and keys on the
    FILE NAME - which is exactly the committed baseline's name. Three classes are refused or skipped
    rather than adopted: the per-shot ``*.diff.png`` the check writes beside a failing render (a
    magenta-marked report of the failure, so installing one would commit a picture of the drift),
    any entry that is not a regular file, and any DIRECTORY that is a link.

    Directories matter as much as files here. ``os.walk(followlinks=False)`` does not follow a POSIX
    directory symlink, but it DOES descend into an NTFS junction, so a junction inside the artifact
    would silently supply files whose real path is outside it (reproduced with ``mklink /J``). Every
    directory is therefore pruned unless it is a real directory, and every candidate file must also
    resolve inside the root.

    The suffix tests are case-INSENSITIVE on purpose. A lowercase-only test would silently ignore a
    ``.PNG``, quietly adopting the rest of the artifact - and "silently adopt a subset" is the one
    outcome this tool must never produce. Matching it here means such a name is either adopted or
    refused by name as a stranger, loudly, either way.
    """
    found, folded = {}, {}
    for dirpath, dirs, files in os.walk(root):
        for name in sorted(dirs):
            sub = os.path.join(dirpath, name)
            try:
                linked = stat.S_ISLNK(os.lstat(sub).st_mode)
            except OSError:
                linked = True
            if linked or not _inside(root, sub):
                raise ShotsError(
                    "%s is a link, not a directory in the artifact. Adopting through it would "
                    "install bytes from outside the artifact as a committed screenshot - nothing "
                    "was written." % sub)
        for name in sorted(files):
            lower = name.lower()
            if not lower.endswith(".png") or lower.endswith(".diff.png"):
                continue
            path = os.path.join(dirpath, name)
            if not _regular_file(path) or not _inside(root, path):
                raise ShotsError(
                    "%s is not a regular file inside the artifact (a link or a device). Adopting "
                    "it would install bytes from outside the artifact as a committed screenshot - "
                    "nothing was written." % path)
            # Fold the key for the DUPLICATE test: on a case-insensitive filesystem two spellings
            # address one baseline, so they must collide here rather than race each other later.
            if lower in folded:
                raise ShotsError(
                    "%r appears more than once under %s (%s and %s). Unzip ONE run's artifact into "
                    "an empty directory: adopting from two would silently pick whichever the walk "
                    "reached last." % (name, root, folded[lower], path))
            folded[lower] = path
            found[name] = path
    return found


class AdoptionPlan(object):
    """What an adoption would do, decided - and fully READ - before a single byte is written."""

    def __init__(self, changed, unchanged):
        self.changed = changed      # [(name, new bytes, current bytes)] - baselines that change
        self.unchanged = unchanged  # [name] - already byte-identical to the artifact


def _read(path, what, limit=None):
    """Read a file, refusing a link swapped in after the scan and anything absurdly large."""
    limit = MAX_SHOT_BYTES if limit is None else limit
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ShotsError("%s %s is not a regular file - nothing was written."
                                 % (what, path))
            if info.st_size > limit:
                raise ShotsError(
                    "%s %s is %d bytes, far larger than any tutorial screenshot (limit %d) - "
                    "nothing was written." % (what, path, info.st_size, limit))
            with os.fdopen(fd, "rb") as handle:
                fd = -1
                return handle.read()
        finally:
            if fd >= 0:
                os.close(fd)
    except OSError as exc:
        raise ShotsError("could not read %s %s (%s) - nothing was written." % (what, path, exc))


def plan_adoption(artifact_root, shots_dir):
    """Decide the adoption, or raise ShotsError explaining why the artifact is not adoptable.

    The safety property is that adopting only ever REWRITES a baseline that already exists. A PNG
    whose name is not a committed shot is the signature of the wrong artifact (another repo, another
    tool, a hand-assembled directory), so it refuses the WHOLE operation rather than adopting the
    part it recognizes - a partly-adopted set is the one outcome nobody can review.

    Every byte on BOTH sides is read HERE, into the returned plan, so the write phase cannot re-read
    a file that changed underneath it, and the rollback restores exactly the bytes the plan compared
    against.
    """
    if not os.path.isdir(artifact_root):
        raise ShotsError(
            "%s is not a directory. Point --adopt at the unzipped %s artifact (its root is the "
            "<pid>/<scene>/ tree), or use --adopt-run <run-id> to fetch it."
            % (artifact_root, DRIFT_ARTIFACT))
    shots = find_artifact_shots(artifact_root)
    if not shots:
        raise ShotsError(
            "no screenshots found under %s. Point --adopt at the unzipped %s artifact (its root is "
            "the <pid>/<scene>/ tree), or use --adopt-run <run-id> to fetch it."
            % (artifact_root, DRIFT_ARTIFACT))
    # The EXACT committed names. os.path.isfile would answer case-insensitively on Windows and let
    # a differently-cased name through, which the write would then store under the artifact's
    # spelling and change the tracked file's case.
    try:
        baselines = set(os.listdir(shots_dir))
    except OSError as exc:
        raise ShotsError("could not list the committed screenshots in %s (%s)." % (shots_dir, exc))
    strangers = sorted(n for n in shots if n not in baselines)
    if strangers:
        raise ShotsError(
            "%s carries %d PNG(s) that are not committed tutorial screenshots: %s. Adopting only "
            "ever rewrites an existing baseline in %s, so this is either the wrong artifact or a "
            "shot this repository renders but has never committed - and a NEW baseline has to come "
            "from the renderer, not from here. Nothing was written."
            % (artifact_root, len(strangers), ", ".join(strangers), shots_dir))
    sources, problems = {}, []
    for name in sorted(shots):
        data = _read(shots[name], "the artifact's")
        why = png_problem(data)
        if why:
            problems.append("%s (%s)" % (name, why))
        else:
            sources[name] = data
    if problems:
        raise ShotsError(
            "%s carries %d file(s) that are not usable PNGs: %s. The drift gate DECODES these, so "
            "installing one would red it permanently - nothing was written."
            % (artifact_root, len(problems), "; ".join(problems)))
    changed, unchanged = [], []
    for name in sorted(sources):
        current = _read(os.path.join(shots_dir, name), "the committed screenshot")
        if sources[name] == current:
            unchanged.append(name)
        else:
            changed.append((name, sources[name], current))
    return AdoptionPlan(changed, unchanged)


def _write_atomically(path, data):
    """Replace `path` with `data` via a sibling temp file, so a failure never truncates it."""
    directory = os.path.dirname(path) or "."
    handle, temp = tempfile.mkstemp(dir=directory, prefix=".shots-adopt-", suffix=".tmp")
    # Close the descriptor mkstemp owns before reopening by name: on Windows an open handle makes
    # the cleanup unlink below fail, which would leave the temp file behind for good.
    os.close(handle)
    try:
        with open(temp, "wb") as fh:
            fh.write(data)
        if os.path.exists(path):
            # mkstemp creates 0600. Carry the baseline's own mode across so an adopt does not
            # silently make the committed screenshots owner-only on this machine.
            shutil.copymode(path, temp)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def adopt_artifact(artifact_root, shots_dir):
    """Re-baseline the committed screenshots from a drift artifact. Returns an exit code.

    This is a re-baseline, never a verdict: the bytes come from the pinned container (CI rendered
    them), but only `shots:check` in that container says the screenshots are RIGHT.

    All-or-nothing in the write phase too, not merely in the decision: each file is replaced
    atomically, and if ANY exception interrupts the loop - including a Ctrl-C between two files -
    the ones already written are restored from the bytes the plan read. Otherwise a disk-full error
    or an interrupt mid-loop would leave a half-adopted set, the exact outcome the refusals prevent.
    """
    plan = plan_adoption(artifact_root, shots_dir)
    if not plan.changed:
        print("shots_linux: no drift - the %d screenshot(s) %s carries already match %s. That is "
              "the artifact's own coverage, NOT a statement that every committed shot is fresh; "
              "the pinned container's 'shots:check' is what says that."
              % (len(plan.unchanged), artifact_root, shots_dir))
        return 0
    written = []
    try:
        for name, data, _current in plan.changed:
            _write_atomically(os.path.join(shots_dir, name), data)
            written.append(name)
    except BaseException as exc:
        restore_failed = []
        for name, _data, current in plan.changed:
            if name not in written:
                continue
            try:
                _write_atomically(os.path.join(shots_dir, name), current)
            except OSError:
                restore_failed.append(name)
        if restore_failed:
            raise ShotsError(
                "could not finish adopting (%s), and restoring %s failed too. Recover with "
                "'git checkout -- %s'." % (exc, ", ".join(restore_failed), shots_dir))
        if not isinstance(exc, OSError):
            raise
        raise ShotsError(
            "could not write a screenshot (%s). The %d already written were rolled back, so "
            "nothing changed." % (exc, len(written)))
    for name in written:
        print("shots_linux: adopted %s" % name)
    print("shots_linux: adopted %d screenshot(s) from %s (%d already matched). These are the pixels "
          "the PINNED container rendered, so commit them and let 'shots:check' in that container - "
          "the required playwright-heavy gate - confirm it."
          % (len(plan.changed), artifact_root, len(plan.unchanged)))
    return 0


def checkout_repo():
    """`owner/name` for this checkout's `origin` remote, or None.

    Derived from the worktree rather than hardcoded, so it stays a single source of truth, and
    forced onto gh as GH_REPO because cwd alone does NOT settle the question: `gh repo set-default`
    records its answer in the checkout's own git config, and with several remotes gh prefers by
    NAME. This clone really does carry stray remotes, so "wherever gh looks" is not good enough.
    """
    url = _capture(["git", "-C", REPO_ROOT, "remote", "get-url", "origin"])
    if not url:
        return None
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    match = re.search(r"[/:]([^/:]+)/([^/]+)\Z", url)
    return "%s/%s" % (match.group(1), match.group(2)) if match else None


def _gh_env():
    """The environment for a `gh` call, pinned to this checkout's repository.

    gh resolves the repository from GH_REPO first, then `gh repo set-default` (stored in the
    checkout's git config), then the cwd's remotes by name preference. Setting GH_REPO from the
    origin remote overrides all three, so a run id names a run of THIS repository whatever the local
    config says. When the remote cannot be read, GH_REPO is removed rather than left to an ambient
    value and gh falls back to resolving from cwd.
    """
    env = dict(os.environ)
    repo = checkout_repo()
    if repo:
        env["GH_REPO"] = repo
    else:
        env.pop("GH_REPO", None)
    return env


def download_drift_artifact(run_id, dest):
    """Fetch a run's drift artifact with `gh` into dest."""
    run_id = ("" if run_id is None else str(run_id)).strip()
    if not RUN_ID_RE.match(run_id):
        raise ShotsError(
            "%r is not a workflow run id. Pass the numeric id from the run's URL "
            "(.../actions/runs/<run-id>)." % run_id)
    if not shutil.which("gh"):
        raise ShotsError(
            "gh is not installed (or not on PATH), so the %s artifact cannot be downloaded. "
            "Install the GitHub CLI, or download the artifact from the failing run's page and pass "
            "the unzipped directory to --adopt instead." % DRIFT_ARTIFACT)
    rc = _run(["gh", "run", "download", run_id, "-n", DRIFT_ARTIFACT, "-D", dest],
              env=_gh_env(), cwd=REPO_ROOT)
    if rc:
        raise ShotsError(
            "gh could not download the %s artifact from run %s. A green run does not produce one "
            "(it is uploaded only when the drift gate FAILS), and artifacts expire; check the run "
            "page." % (DRIFT_ARTIFACT, run_id))


def report_run_provenance(run_id):
    """Print what produced the bytes about to be installed, and warn when it is not `main`'s.

    Two things the operator cannot otherwise see at decision time. First, the COMMIT: adopting a run
    of a different commit is not a gate bypass (the container re-diffs against the real source) but
    it commits pixels that were never this tree's. Second, and more important, the EVENT: the drift
    artifact is uploaded by `pull_request` runs too, and those pixels were rendered from that pull
    request's own source. Both are warnings rather than refusals - a maintainer fixing `main` from a
    worktree legitimately has a different HEAD - and the whole lookup is best-effort, because no
    failure here may cost the operator the fix.
    """
    head = _capture(["git", "-C", REPO_ROOT, "rev-parse", "HEAD"])
    raw = _capture(["gh", "run", "view", str(run_id), "--json", "headSha,headBranch,event,url"],
                   env=_gh_env(), cwd=REPO_ROOT)
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        data = None
    if not isinstance(data, dict) or not _text(data.get("headSha")):
        print("shots_linux: could not read run %s's provenance; adopt only a run of the commit you "
              "are baselining, and only a push run." % run_id)
        return
    run_sha = data["headSha"]
    branch = _text(data.get("headBranch")) or "?"
    event = _text(data.get("event")) or "?"
    print("shots_linux: run %s rendered %s (%s, event %s) %s"
          % (run_id, run_sha[:12], branch, event, _text(data.get("url")) or ""))
    if event != "push":
        print("shots_linux: WARNING - this is a %r run, so its pixels were rendered from THAT "
              "change's source rather than from the branch you are baselining." % event)
    if head and head.strip() != run_sha:
        print("shots_linux: WARNING - your HEAD is %s, so these pixels were rendered from DIFFERENT "
              "source. Adopt them only if you know that commit's screenshots are the ones you want."
              % head.strip()[:12])


def record_digest(tag, lock_path=None):
    """Pull the pinned tag and record the sha256 it resolves to, so the renderer is immutable."""
    lock_path = IMAGE_LOCK if lock_path is None else lock_path
    if not shutil.which("docker"):
        return _fail(_docker_missing_message(tag))
    if not _docker_daemon_ok():
        return _fail(_daemon_down_message(tag))
    print("shots_linux: pulling %s to record its digest" % tag, flush=True)
    rc = _run(["docker", "pull", "--platform", IMAGE_PLATFORM, tag])
    if rc:
        return rc
    raw = _capture(["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", tag])
    try:
        entries = json.loads(raw) if raw else None
    except ValueError:
        entries = None
    digest = parse_repo_digest(entries if isinstance(entries, list) else [])
    if not digest:
        return _fail("shots_linux: docker reported no %s digest for %s, so the renderer cannot be "
                     "pinned immutably. Pull it from the registry (not a local build) and retry."
                     % (IMAGE_REPO, tag))
    write_image_lock(lock_path, tag, digest)
    print("shots_linux: pinned %s@%s (recorded in %s)" % (IMAGE_REPO, digest, lock_path))
    return 0


def _adopt_main(adopt_dir, adopt_run):
    """--adopt / --adopt-run: install a drift artifact's PNGs as the committed baselines."""
    if adopt_dir is not None:
        try:
            return adopt_artifact(adopt_dir, SHOTS_DIR)
        except ShotsError as exc:
            return _fail("shots_linux: " + str(exc))
    holding = os.path.join(REPO_ROOT, "tmp", "shots-adopt")
    try:
        os.makedirs(holding, exist_ok=True)
        # A unique directory the OS creates atomically, not a guessable pid-derived path that a
        # previous crashed run may have left populated (its leftovers would adopt as this run's).
        scratch = tempfile.mkdtemp(dir=holding, prefix="run-")
    except OSError as exc:
        return _fail("shots_linux: could not create a scratch directory under %s (%s)."
                     % (holding, exc))
    # The DOWNLOAD is its own phase: when it fails there is nothing on disk to inspect, so keeping
    # the empty directory and telling the operator to re-run '--adopt' on it would be false and
    # would accumulate junk on exactly the most common failures (bad run id, no gh, expired
    # artifact). Only a download that actually produced something is worth keeping.
    try:
        download_drift_artifact(adopt_run, scratch)
    except ShotsError as exc:
        shutil.rmtree(scratch, ignore_errors=True)
        return _fail("shots_linux: " + str(exc))
    keep = False
    try:
        report_run_provenance(adopt_run)
        return adopt_artifact(scratch, SHOTS_DIR)
    except ShotsError as exc:
        # KEEP the download when the adoption is refused: it is the only unzipped copy, the error
        # tells the operator to inspect it, and re-downloading it is pure cost. This mirrors the
        # keep-the-evidence rule the drift gate itself follows (CMH-BUILD-18).
        keep = True
        return _fail("shots_linux: %s\n\n  The downloaded artifact was kept at %s - inspect it, "
                     "then re-run with '--adopt %s' rather than downloading it again."
                     % (exc, scratch, scratch))
    finally:
        if not keep:
            shutil.rmtree(scratch, ignore_errors=True)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(
        prog="shots_linux.py",
        allow_abbrev=False,  # unknown args are forwarded; abbreviation would swallow capture flags
        description="Render or verify the tutorial screenshots in the pinned container.")
    parser.add_argument("--check", action="store_true",
                        help="verify the committed screenshots instead of rewriting them")
    parser.add_argument("--native", action="store_true",
                        help="EXPLICIT opt-in: render with the host browser instead of the pinned "
                             "container. Not the authoritative renderer; results are provisional")
    parser.add_argument("--skip-without-renderer", action="store_true",
                        help="with --check, skip (exit 0) instead of failing when Docker is "
                             "unavailable; used by 'npm run shots:check' so 'npm test' does not "
                             "demand Docker. Never skips in CI")
    parser.add_argument("--print-image", action="store_true",
                        help="print the exact image reference the render will use and exit")
    parser.add_argument("--record-digest", action="store_true",
                        help="pull the pinned tag and record its sha256 in tools/shots-image.lock")
    parser.add_argument("--adopt", metavar="DIR",
                        help="re-baseline the committed screenshots from an unzipped %s artifact, "
                             "for a machine that cannot run the renderer" % DRIFT_ARTIFACT)
    parser.add_argument("--adopt-run", metavar="RUN_ID",
                        help="download this repository's %s artifact for a workflow run with gh, "
                             "then adopt it" % DRIFT_ARTIFACT)
    ns, passthrough = parser.parse_known_args(argv[1:])
    if ns.print_image and ns.record_digest:
        return _fail("shots_linux: --print-image and --record-digest are mutually exclusive.")
    adopting = ns.adopt is not None or ns.adopt_run is not None
    if ns.adopt is not None and ns.adopt_run is not None:
        return _fail("shots_linux: --adopt and --adopt-run are mutually exclusive (--adopt-run "
                     "downloads the directory --adopt would read).")
    if adopting and (ns.check or ns.native or ns.print_image or ns.record_digest
                     or ns.skip_without_renderer):
        # Adopting INSTALLS a render made elsewhere; rendering or verifying here at the same time
        # would leave it ambiguous which pixels won. --skip-without-renderer belongs to the same
        # set: adopting needs no renderer, so accepting it would silently discard a flag.
        return _fail("shots_linux: --adopt/--adopt-run installs the pixels another run rendered, "
                     "so it cannot be combined with --check, --native, --print-image, "
                     "--record-digest or --skip-without-renderer.")
    if adopting and passthrough:
        # Unknown args are forwarded to the capture script on the render paths. Adopting runs no
        # capture, so a forwarded arg would be silently dropped - including a typo'd flag, which
        # would then read as a successful adoption of something the operator did not ask for.
        return _fail("shots_linux: --adopt/--adopt-run runs no capture, so it accepts no extra "
                     "arguments; %s would be ignored." % " ".join(passthrough))
    if adopting:
        if not (ns.adopt if ns.adopt is not None else ns.adopt_run).strip():
            return _fail("shots_linux: %s was given an empty value (an unset shell variable?). "
                         "Pass the unzipped artifact directory, or a numeric run id."
                         % ("--adopt" if ns.adopt is not None else "--adopt-run"))
        return _adopt_main(ns.adopt, ns.adopt_run)
    # capture_tutorial.mjs takes optional [example] [outDir] [prefix] and --print-paths; forward
    # them so a single-scene recapture does not have to fall back to the raw, unguarded command.
    extra = (["--check"] if ns.check else []) + list(passthrough)

    if ns.print_image or ns.record_digest:
        try:
            tag = image_ref(pinned_playwright_version(DEV_DIR))
        except ShotsError as exc:
            return _fail("shots_linux: " + str(exc))
        if ns.record_digest:
            return record_digest(tag)
        ref, warning = resolved_image(tag)
        if warning and not _report_pin(warning):
            return 2
        print(ref)
        return 0

    if not _deps_installed():
        return _fail(_deps_missing_message(ns.native))

    node = shutil.which("node")
    if ns.native:
        sys.stderr.write(NATIVE_WARNING)
        if not node:
            return _fail("shots_linux: node is not on PATH; run 'python scripts/setup_dev.py'.")
        return _run([node, os.path.join(DEV_DIR, "tools", "capture_tutorial.mjs")] + extra,
                    env=dict(os.environ, **{RENDERER_ENV: "native"}))

    try:
        ref, warning = resolved_image(image_ref(pinned_playwright_version(DEV_DIR)))
    except ShotsError as exc:
        return _fail("shots_linux: " + str(exc))
    if warning and not _report_pin(warning):
        return 2

    # The skip applies to the CHECK direction on a developer machine only. Regenerating is the
    # dangerous direction (it must produce a correct PNG or refuse loudly), and in CI this IS the
    # drift gate, so a renderer that cannot start must red the job rather than pass quietly.
    skippable = ns.skip_without_renderer and ns.check and not _in_ci()
    if not shutil.which("docker"):
        if skippable:
            print(_skip_message("Docker is not installed", ref), flush=True)
            return 0
        return _fail(_docker_missing_message(ref))
    if not _docker_daemon_ok():
        if skippable:
            print(_skip_message("the Docker daemon is not responding", ref), flush=True)
            return 0
        return _fail(_daemon_down_message(ref))

    dev_rel = os.path.relpath(DEV_DIR, REPO_ROOT).replace("\\", "/")
    print("shots_linux: %s in %s" % ("checking" if ns.check else "regenerating", ref), flush=True)
    return _run(docker_command(REPO_ROOT, dev_rel, ref, extra, _host_uid_gid(), _in_ci()))


if __name__ == "__main__":
    sys.exit(main())
