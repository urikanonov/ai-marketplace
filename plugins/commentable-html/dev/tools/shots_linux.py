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

Standard library only.
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

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

    package.json carries a semver range (``^1.61.1``); the lockfile carries what is actually
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


def _run(cmd, env=None):
    return subprocess.run(cmd, env=env).returncode


def _capture(cmd):
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
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
    ns, passthrough = parser.parse_known_args(argv[1:])
    if ns.print_image and ns.record_digest:
        return _fail("shots_linux: --print-image and --record-digest are mutually exclusive.")
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
