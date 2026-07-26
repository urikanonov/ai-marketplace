#!/usr/bin/env python3
"""Rebuild every generated artifact in the correct order, or verify they are all in sync.

History (GH-RELEASE-REGEN-CHURN): after a version bump or a rebase, the three generators must be
run in order, and it is easy to forget one - which produced a string of "regenerate to fix the
gate" fixup commits. This is the single command that runs them all deterministically:

  1. tools/build.py         - the commentable-html layer dist bundles + stamped manifests
  2. tools/build_spec.py    - the generated commentable-html dev/SPEC.md
  3. tests/fixtures/generate.mjs - the Playwright fixtures (embed the runtime version)
  4. tools/shots_linux.py   - tutorial screenshots, rendered in the pinned container
  5. scripts/build_site_data.py  - the GitHub Pages site (pages, demos, sitemap, llms)

Usage:
  python scripts/rebuild_all.py           # regenerate everything in order
  python scripts/rebuild_all.py --check   # verify everything is in sync (no writes); non-zero on drift

The fixtures step needs node; when node is absent it is skipped with a clear note (CI's
plugin-tests job remains the authoritative fixtures gate). Standard library only.
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_PY = os.path.join(ROOT, "plugins", "commentable-html", "dev", "tools", "build.py")
BUILD_SPEC = os.path.join(ROOT, "plugins", "commentable-html", "dev", "tools", "build_spec.py")
ASSETS_DIR = os.path.join(ROOT, "plugins", "commentable-html", "dev", "assets")
# The full editable + built skill tree (STAGE); the shipped pkg carries only a minimal set plus the
# skill-resources.zip that build.py assembles from the STAGE and a SessionStart hook extracts.
STAGE_DIR = os.path.join(ROOT, "plugins", "commentable-html", "dev", "skill")
PKG_DIR = os.path.join(ROOT, "plugins", "commentable-html", "pkg", "skills", "commentable-html")
# The built demo reports/prompts live at the plugin top level (not shipped, not in the zip).
EXAMPLES_DIR = os.path.join(ROOT, "plugins", "commentable-html", "examples")
FIXTURES_GEN = os.path.join(ROOT, "plugins", "commentable-html", "dev", "tests", "fixtures", "generate.mjs")
TUTORIAL_SHOTS = os.path.join(ROOT, "plugins", "commentable-html", "dev", "tools", "shots_linux.py")
SHOTS_TOOL_DIR = os.path.join(ROOT, "plugins", "commentable-html", "dev", "tools")
# capture_tutorial.mjs imports @playwright/test, and the container reuses the mounted node_modules
# rather than installing its own, so the commentable-html dev deps must be installed (run
# scripts/setup_dev.py). When they are absent the step is skipped with a note rather than failing
# with a cryptic ERR_MODULE_NOT_FOUND.
TUTORIAL_DEPS = os.path.join(ROOT, "plugins", "commentable-html", "dev", "node_modules",
                             "@playwright", "test")
SITE_DATA = os.path.join(ROOT, "scripts", "build_site_data.py")


def _tutorial_deps_installed():
    return os.path.isdir(TUTORIAL_DEPS)


def _pinned_renderer_available():
    """True when the pinned screenshot container can actually run on this machine.

    The committed PNGs are rendered in ONE digest-pinned Playwright image on every host and in CI,
    so the only local precondition is a working Docker. Delegate to the single helper in the
    plugin's shots tool so this orchestrator and `npm run shots` can never disagree.
    """
    try:
        sys.path.insert(0, SHOTS_TOOL_DIR)
        import shots_linux
        return shots_linux.renderer_available()
    except Exception:
        # Fail CLOSED: without the shared helper we cannot tell whether the pinned renderer is
        # available, and rendering with whatever this host has is what produced wrong PNGs.
        return False


def _run(label, cmd):
    print("== " + label + " ==")
    proc = subprocess.run(cmd, cwd=ROOT)
    return proc.returncode


def main(argv=None):
    argv = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(prog="rebuild_all.py",
                                     description="Rebuild or --check every generated artifact in order.")
    parser.add_argument("--check", action="store_true",
                        help="verify everything is in sync instead of writing")
    ns = parser.parse_args(argv[1:])
    check = ["--check"] if ns.check else []

    steps = [
        ("commentable-html layer dist (build.py)",
         [sys.executable, BUILD_PY, "--assets-dir", ASSETS_DIR, "--out-dir", STAGE_DIR,
          "--pkg-dir", PKG_DIR, "--examples-dir", EXAMPLES_DIR] + check),
        ("commentable-html dev SPEC (build_spec.py)", [sys.executable, BUILD_SPEC] + check),
    ]
    node = shutil.which("node")
    if node and os.path.exists(FIXTURES_GEN):
        steps.append(("Playwright fixtures (generate.mjs)", [node, FIXTURES_GEN] + check))
    else:
        print("== Playwright fixtures (generate.mjs) == skipped (node not found; CI plugin-tests runs it)")
    if not _pinned_renderer_available():
        print("== Tutorial screenshots (shots_linux.py) == skipped (Docker is not available, and "
              "the committed screenshots are rendered ONLY in the pinned Playwright container - "
              "the same renderer the required CI job validates them with - so re-rendering them "
              "with this machine's browser would pass every local check and then fail that job). "
              "Start Docker and run 'npm run shots' from plugins/commentable-html/dev; CI "
              "plugin-tests remains the authoritative gate.")
    elif node and os.path.exists(TUTORIAL_SHOTS) and _tutorial_deps_installed():
        steps.append(("Tutorial screenshots (shots_linux.py)",
                      [sys.executable, TUTORIAL_SHOTS] + check))
    elif node and os.path.exists(TUTORIAL_SHOTS):
        print("== Tutorial screenshots (shots_linux.py) == skipped "
              "(commentable-html dev node_modules not installed; run 'python scripts/setup_dev.py'; "
              "CI plugin-tests runs it)")
    elif not node:
        print("== Tutorial screenshots (shots_linux.py) == skipped (node not found; CI plugin-tests runs it)")
    else:
        print("== Tutorial screenshots (shots_linux.py) == skipped (capture script not found)")
    steps.append(("GitHub Pages site (build_site_data.py)", [sys.executable, SITE_DATA] + check))

    failed = []
    for label, cmd in steps:
        rc = _run(label, cmd)
        if rc != 0:
            failed.append(label)
    if failed:
        sys.stderr.write("rebuild_all FAILED for: " + ", ".join(failed) + "\n")
        return 1
    print("rebuild_all OK (" + ("all artifacts in sync" if ns.check else "all artifacts regenerated") + ").")
    return 0


if __name__ == "__main__":
    sys.exit(main())
