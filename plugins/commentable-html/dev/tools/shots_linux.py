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
# The artifact the required playwright-heavy job uploads when the drift gate fails. It carries the
# PNGs the PINNED container just rendered, so it is the authoritative render for this commit even on
# a machine that cannot run the renderer at all.
DRIFT_ARTIFACT = "tutorial-shots-drift"
PLUGIN_DIR = os.path.dirname(DEV_DIR)
# The committed baselines the capture writes and the gate compares against.
SHOTS_DIR = os.path.join(PLUGIN_DIR, "docs", "assets")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
RUN_ID_RE = re.compile(r"^[0-9]+$")
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


def find_artifact_shots(root):
    """{file name: path} for every candidate shot in an unzipped drift artifact.

    The artifact unzips to a ``<pid>/<scene>/`` tree, so the walk is depth-agnostic and keys on the
    FILE NAME - which is exactly the committed baseline's name. The per-shot ``*.diff.png`` the
    check writes beside a failing render is excluded: it is a magenta-marked report of the failure,
    not a render, and installing one as a baseline would commit a picture of the drift.
    """
    found = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if not name.endswith(".png") or name.endswith(".diff.png"):
                continue
            path = os.path.join(dirpath, name)
            if name in found:
                raise ShotsError(
                    "%r appears more than once under %s (%s and %s). Unzip ONE run's artifact into "
                    "an empty directory: adopting from two would silently pick whichever the walk "
                    "reached last." % (name, root, found[name], path))
            found[name] = path
    return found


class AdoptionPlan(object):
    """What an adoption would do, decided before a single byte is written."""

    def __init__(self, changed, unchanged):
        self.changed = changed      # [(name, source path)] - baselines whose bytes would change
        self.unchanged = unchanged  # [name] - already byte-identical to the artifact


def _is_png(path):
    try:
        with open(path, "rb") as handle:
            return handle.read(len(PNG_MAGIC)) == PNG_MAGIC
    except OSError:
        return False


def _read(path):
    with open(path, "rb") as handle:
        return handle.read()


def plan_adoption(artifact_root, shots_dir):
    """Decide the adoption, or raise ShotsError explaining why the artifact is not adoptable.

    The safety property is that adopting only ever REWRITES a baseline that already exists. A PNG
    whose name is not a committed shot is the signature of the wrong artifact (another repo, another
    tool, a hand-assembled directory), so it refuses the WHOLE operation rather than adopting the
    part it recognizes - a partly-adopted set is the one outcome nobody can review.
    """
    shots = find_artifact_shots(artifact_root)
    if not shots:
        raise ShotsError(
            "no screenshots found under %s. Point --adopt at the unzipped %s artifact (its root is "
            "the <pid>/<scene>/ tree), or use --adopt-run <run-id> to fetch it."
            % (artifact_root, DRIFT_ARTIFACT))
    strangers = sorted(n for n in shots if not os.path.isfile(os.path.join(shots_dir, n)))
    if strangers:
        raise ShotsError(
            "%s carries %d PNG(s) that are not committed tutorial screenshots: %s. Adopting only "
            "ever rewrites an existing baseline in %s, so this looks like the wrong artifact - "
            "nothing was written." % (artifact_root, len(strangers), ", ".join(strangers),
                                      shots_dir))
    unreadable = sorted(n for n, p in shots.items() if not _is_png(p))
    if unreadable:
        raise ShotsError(
            "%s carries %d file(s) that are not PNGs: %s. A truncated download or an error page "
            "saved under a .png name would install an undecodable baseline and red the drift gate "
            "permanently - nothing was written." % (artifact_root, len(unreadable),
                                                    ", ".join(unreadable)))
    changed, unchanged = [], []
    for name in sorted(shots):
        if _read(shots[name]) == _read(os.path.join(shots_dir, name)):
            unchanged.append(name)
        else:
            changed.append((name, shots[name]))
    return AdoptionPlan(changed, unchanged)


def adopt_artifact(artifact_root, shots_dir):
    """Re-baseline the committed screenshots from a drift artifact. Returns an exit code.

    This is a re-baseline, never a verdict: the bytes come from the pinned container (CI rendered
    them), but only `shots:check` in that container says the screenshots are RIGHT.
    """
    plan = plan_adoption(artifact_root, shots_dir)
    if not plan.changed:
        print("shots_linux: no drift - all %d screenshot(s) in %s already match %s."
              % (len(plan.unchanged), artifact_root, shots_dir))
        return 0
    for name, source in plan.changed:
        shutil.copyfile(source, os.path.join(shots_dir, name))
        print("shots_linux: adopted %s" % name)
    print("shots_linux: adopted %d screenshot(s) from %s (%d already matched). These are the pixels "
          "the PINNED container rendered, so commit them and let 'shots:check' in that container - "
          "the required playwright-heavy gate - confirm it."
          % (len(plan.changed), artifact_root, len(plan.unchanged)))
    return 0


def download_drift_artifact(run_id, dest):
    """Fetch a run's drift artifact with `gh` into dest.

    No --repo: gh resolves the repository from the checkout the command runs in, so a run id can
    only ever name a run of THIS repository.
    """
    run_id = "" if run_id is None else str(run_id)
    if not RUN_ID_RE.match(run_id):
        raise ShotsError(
            "%r is not a workflow run id. Pass the numeric id from the run's URL "
            "(.../actions/runs/<run-id>)." % run_id)
    if not shutil.which("gh"):
        raise ShotsError(
            "gh is not installed (or not on PATH), so the %s artifact cannot be downloaded. "
            "Install the GitHub CLI, or download the artifact from the failing run's page and pass "
            "the unzipped directory to --adopt instead." % DRIFT_ARTIFACT)
    rc = _run(["gh", "run", "download", run_id, "-n", DRIFT_ARTIFACT, "-D", dest])
    if rc:
        raise ShotsError(
            "gh could not download the %s artifact from run %s. A green run does not produce one "
            "(it is uploaded only when the drift gate FAILS), and artifacts expire; check the run "
            "page." % (DRIFT_ARTIFACT, run_id))


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
    if adopt_dir:
        try:
            return adopt_artifact(adopt_dir, SHOTS_DIR)
        except ShotsError as exc:
            return _fail("shots_linux: " + str(exc))
    scratch = os.path.join(REPO_ROOT, "tmp", "shots-adopt", str(os.getpid()))
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch, exist_ok=True)
    try:
        download_drift_artifact(adopt_run, scratch)
        return adopt_artifact(scratch, SHOTS_DIR)
    except ShotsError as exc:
        return _fail("shots_linux: " + str(exc))
    finally:
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
    if ns.adopt and ns.adopt_run:
        return _fail("shots_linux: --adopt and --adopt-run are mutually exclusive (--adopt-run "
                     "downloads the directory --adopt would read).")
    if (ns.adopt or ns.adopt_run) and (ns.check or ns.native or ns.print_image or ns.record_digest):
        # Adopting INSTALLS a render made elsewhere; rendering or verifying here at the same time
        # would leave it ambiguous which pixels won.
        return _fail("shots_linux: --adopt/--adopt-run installs the pixels another run rendered, "
                     "so it cannot be combined with --check, --native, --print-image or "
                     "--record-digest.")
    if ns.adopt or ns.adopt_run:
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
