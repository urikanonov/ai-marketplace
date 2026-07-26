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
  matches CI.
* On any other host it runs the capture inside the pinned Playwright container. The image tag is
  DERIVED from the ``@playwright/test`` version resolved in ``package-lock.json``, so the container's
  browser can never drift from the one the suite runs; a hardcoded tag would.

Usage (from ``plugins/commentable-html/dev``)::

    npm run shots:linux          # regenerate
    npm run shots:linux:check    # verify only, no writes

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
        "    2. Regenerate on any Linux machine or WSL with 'npm run shots' - no Docker needed there.\n"
        "    3. Leave the PNGs untouched: if your change does not affect them, restore them with\n"
        "       'git checkout origin/main -- plugins/commentable-html/docs/assets'.\n"
        "\n"
        "  See %s ('Regenerating the tutorial screenshots')." % (sys.platform, image, GUIDE))


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
    ns = parser.parse_args(argv[1:])
    extra = ["--check"] if ns.check else []

    if not _deps_installed():
        return _fail(_deps_missing_message())

    node = shutil.which("node")
    if host_is_linux():
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
