#!/usr/bin/env python3
"""Regenerate the tutorial screenshots with the SAME renderer CI uses (CMH-BUILD-16).

The committed PNGs under ``plugins/commentable-html/docs/assets/`` are produced by a browser, and
font rasterization differs per operating system. Running ``capture_tutorial.mjs`` directly on
Windows or macOS therefore rewrites every shot with the HOST renderer. That is silently wrong:
``npm run shots:check`` and ``rebuild_all.py --check`` both re-render with the same host renderer, so
they agree and go green, and only the required ``playwright-heavy`` CI job (on Linux) reports
``<name>.png differs``.

This tool makes the regeneration deterministic and one-command everywhere:

* On a LINUX host it runs the capture natively. Docker is NOT required - the host renderer already
  matches CI (which itself renders on a pinned ubuntu-24.04 runner, not in a container). Pass
  ``--container`` when the Linux host is a DIFFERENT distro or release, whose fonts may still differ.
* On any other host it runs the capture inside the pinned Playwright container. Two axes are pinned:
  the ``@playwright/test`` version resolved in ``package-lock.json`` (which fixes the chromium
  binary) and the Ubuntu release in the image variant (which fixes the FONTS - the axis that actually
  caused the original mismatch). Neither is hardcoded at a call site.

The container is equivalent to CI by AGREEMENT, not by construction: CI does not run inside this
image, it installs chromium on a bare runner. That is why the runner is pinned to the release named
in ``UBUNTU_RELEASES`` and a test couples the two - moving one without the other is a silent
divergence, so the guard forces a conscious, two-sided edit.

Usage (from ``plugins/commentable-html/dev``)::

    npm run shots                # regenerate (native on Linux, container elsewhere)
    npm run shots:check          # verify; skips with a note where the host cannot match CI
    npm run shots:linux          # force the pinned container
    npm run shots:linux:check    # force the pinned container, verify only

Standard library only.
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys

DEV_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(DEV_DIR)))
CAPTURE = os.path.join("tools", "capture_tutorial.mjs")
# The image family that matches the CI runner (ubuntu-24.04 == noble). Only the VERSION varies, and
# it is read from the lockfile - see image_ref().
IMAGE_REPO = "mcr.microsoft.com/playwright"
IMAGE_VARIANT = "noble"
# The image variant and the CI runner must name the SAME Ubuntu release. CI does NOT run inside this
# image - the playwright-heavy job installs chromium on a bare runner - so the container is only
# equivalent to CI while the two agree. A test pins this mapping against the workflow so a future
# runner bump has to be a conscious, two-sided edit.
UBUNTU_RELEASES = {"noble": "ubuntu-24.04"}
# The image is multi-arch; without this an Apple Silicon host would render with the arm64 stack while
# CI renders on x86_64.
IMAGE_PLATFORM = "linux/amd64"
LOCK_KEY = "node_modules/@playwright/test"
GUIDE = "docs/testing-guidelines.md"


class ShotsError(Exception):
    """A precondition failed with an operator-actionable explanation."""


def host_is_linux():
    return sys.platform.startswith("linux")


def pinned_playwright_version(dev_dir):
    """The EXACT @playwright/test version from package-lock.json.

    package.json carries a semver range (``^1.61.1``); the lockfile carries what is actually
    installed and therefore what CI runs, so it is the only value that keeps the container's browser
    in lockstep with the suite.
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


def docker_command(repo_root, dev_rel, image, extra_args):
    """The docker argv that runs the capture inside the pinned image against the mounted worktree.

    The repo is mounted (not copied) so the regenerated PNGs land straight back in the worktree.
    Paths are quoted with shlex because a checkout path routinely contains spaces on Windows.
    """
    workdir = "/repo/" + dev_rel.replace("\\", "/")
    inner = "node " + shlex.quote(CAPTURE.replace("\\", "/"))
    if extra_args:
        inner += " " + " ".join(shlex.quote(a) for a in extra_args)
    return [
        "docker", "run", "--rm",
        "--platform", IMAGE_PLATFORM,
        "-v", "%s:/repo" % repo_root,
        "-w", workdir,
        image,
        "bash", "-lc", "cd " + shlex.quote(workdir) + " && " + inner,
    ]


def _deps_installed(dev_dir=None):
    dev_dir = DEV_DIR if dev_dir is None else dev_dir
    return os.path.isdir(os.path.join(dev_dir, "node_modules", "@playwright", "test"))


def _docker_daemon_ok():
    try:
        proc = subprocess.run(["docker", "version"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return proc.returncode == 0


def _run(cmd):
    return subprocess.run(cmd).returncode


def _fail(message):
    sys.stderr.write(message.rstrip() + "\n")
    return 2


def _docker_missing_message(image):
    return (
        "shots_linux: Docker is not installed (or 'docker' is not on PATH).\n"
        "\n"
        "  Why Docker is involved: the committed tutorial screenshots are rendered on LINUX, and\n"
        "  browser font rasterization differs per OS. Regenerating them on %s would rewrite every\n"
        "  shot with this machine's renderer - which passes every local check and then fails the\n"
        "  required playwright-heavy CI job.\n"
        "\n"
        "  Options:\n"
        "    1. Install Docker Desktop / Docker Engine, then re-run 'npm run shots:linux'.\n"
        "       It runs the pinned image %s (tag derived from package-lock.json).\n"
        "    2. Regenerate on a Linux machine or WSL running %s with 'npm run shots' - no Docker\n"
        "       needed there. Another distro or release has its own fonts and may still differ.\n"
        "    3. Leave the PNGs untouched: if your change does not affect them, restore them with\n"
        "       'git checkout origin/main -- plugins/commentable-html/docs/assets'.\n"
        "\n"
        "  See %s ('Regenerating the tutorial screenshots')."
        % (sys.platform, image, UBUNTU_RELEASES[IMAGE_VARIANT], GUIDE))


def _daemon_down_message(image):
    return (
        "shots_linux: Docker is installed but its daemon is not responding.\n"
        "\n"
        "  'docker version' failed, so the container cannot start. Start Docker Desktop (or\n"
        "  'sudo systemctl start docker') and re-run 'npm run shots:linux'.\n"
        "  The pinned image is %s.\n"
        "\n"
        "  See %s ('Regenerating the tutorial screenshots')." % (image, GUIDE))


def _deps_missing_message():
    return (
        "shots_linux: the commentable-html dev node_modules are not installed.\n"
        "\n"
        "  capture_tutorial.mjs imports @playwright/test, and the container reuses the mounted\n"
        "  node_modules rather than installing its own. Run:\n"
        "\n"
        "    python scripts/setup_dev.py\n"
        "\n"
        "  then re-run 'npm run shots:linux'.")


def main(argv=None):
    argv = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(
        prog="shots_linux.py",
        description="Regenerate the tutorial screenshots with the renderer CI uses.")
    parser.add_argument("--check", action="store_true",
                        help="verify the committed screenshots instead of rewriting them")
    parser.add_argument("--container", action="store_true",
                        help="force the pinned container even on Linux (use when this Linux host is "
                             "not the Ubuntu release CI runs)")
    parser.add_argument("--skip-off-linux", action="store_true",
                        help="with --check, skip (exit 0) instead of running when the host renderer "
                             "cannot match CI; used by 'npm run shots:check' so 'npm test' neither "
                             "false-fails nor requires Docker")
    ns = parser.parse_args(argv[1:])
    extra = ["--check"] if ns.check else []

    native = host_is_linux() and not ns.container
    # --skip-off-linux applies to the CHECK direction only. Regenerating is the dangerous direction:
    # it must produce a correct PNG or refuse loudly, never silently do nothing.
    if ns.skip_off_linux and ns.check and not native:
        print("shots_linux: screenshot check skipped (this host does not render the committed "
              "Linux PNGs identically, so the result would be meaningless). Run "
              "'npm run shots:linux:check' to verify in the pinned container; CI is the "
              "authoritative gate.")
        return 0

    if not _deps_installed():
        return _fail(_deps_missing_message())

    node = shutil.which("node")
    if native:
        # The host renderer already matches CI - no container, no Docker dependency.
        if not node:
            return _fail("shots_linux: node is not on PATH; run 'python scripts/setup_dev.py'.")
        return _run([node, os.path.join(DEV_DIR, "tools", "capture_tutorial.mjs")] + extra)

    try:
        image = image_ref(pinned_playwright_version(DEV_DIR))
    except ShotsError as exc:
        return _fail("shots_linux: " + str(exc))

    if not shutil.which("docker"):
        return _fail(_docker_missing_message(image))
    if not _docker_daemon_ok():
        return _fail(_daemon_down_message(image))

    dev_rel = os.path.relpath(DEV_DIR, REPO_ROOT).replace("\\", "/")
    print("shots_linux: %s in %s" % ("checking" if ns.check else "regenerating", image))
    return _run(docker_command(REPO_ROOT, dev_rel, image, extra))


if __name__ == "__main__":
    sys.exit(main())
