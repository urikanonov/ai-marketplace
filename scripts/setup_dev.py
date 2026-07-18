#!/usr/bin/env python3
"""Make a fresh clone dev-ready with one command. Standard library only.

A fresh clone is NOT dev-ready: the git hooks are off (nothing runs until core.hooksPath is set),
the Python validator deps (jsonschema, pyyaml) are not installed, and each Node suite (site/tests
and every plugins/<x>/dev with a package.json) has no node_modules or Playwright browser. Git has
no post-clone hook - a hook cannot install the thing that enables hooks - so this is the single
idempotent script a developer runs once after cloning; it also enables the hooks.

Usage:
  python scripts/setup_dev.py               # enable hooks, install Python + Node deps + browsers
  python scripts/setup_dev.py --no-browsers # skip the Playwright browser download
  python scripts/setup_dev.py --check       # report readiness without installing (non-zero if not)
"""
import argparse
import collections
import importlib.util
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

Step = collections.namedtuple("Step", ["label", "cwd", "cmd", "suite"])


def _rel(root, path):
    return os.path.relpath(path, root).replace(os.sep, "/")


def _candidate_suite_dirs(root):
    dirs = [os.path.join(root, "site", "tests")]
    plugins_dir = os.path.join(root, "plugins")
    if os.path.isdir(plugins_dir):
        for name in sorted(os.listdir(plugins_dir)):
            dirs.append(os.path.join(plugins_dir, name, "dev"))
    return dirs


def discover_node_suites(root):
    """Every Node suite a fresh clone must `npm ci`: site/tests plus each plugins/<x>/dev that has a
    package.json. Discovered (not hard-coded) so a new plugin's dev suite is picked up automatically."""
    return [d for d in _candidate_suite_dirs(root)
            if os.path.isfile(os.path.join(d, "package.json"))]


def suite_needs_browsers(suite_dir):
    """True when the suite depends on Playwright, so its browser must be installed."""
    try:
        with open(os.path.join(suite_dir, "package.json"), encoding="utf-8") as fh:
            pkg = json.load(fh)
    except (OSError, ValueError):
        return False
    deps = {}
    for key in ("dependencies", "devDependencies"):
        section = pkg.get(key)
        if isinstance(section, dict):
            deps.update(section)
    return "playwright" in deps or "@playwright/test" in deps


def plan(root, browsers=True):
    """The ordered list of setup Steps. Pure: it builds the commands without running them, so it is
    fully unit-testable and deterministic (every command is safe to re-run - the setup is idempotent)."""
    steps = [
        Step("enable git hooks (core.hooksPath)", root,
             ["git", "config", "core.hooksPath", ".githooks"], None),
        Step("install Python validator deps (jsonschema, pyyaml)", root,
             [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
              "jsonschema", "pyyaml"], None),
    ]
    for suite in discover_node_suites(root):
        rel = _rel(root, suite)
        steps.append(Step("install Node deps: " + rel, suite, ["npm", "ci", "--ignore-scripts"], rel))
        if browsers and suite_needs_browsers(suite):
            steps.append(Step("install Playwright browser (chromium): " + rel, suite,
                              ["npx", "playwright", "install", "chromium"], rel))
    return steps


def _require_tools(browsers):
    """Names of required external tools that are not on PATH (so setup can fail fast with a list).
    npx is only needed when browsers are requested AND a discovered suite actually uses Playwright."""
    needed = ["git", "npm"]
    if browsers and any(suite_needs_browsers(s) for s in discover_node_suites(ROOT)):
        needed.append("npx")
    return [t for t in needed if shutil.which(t) is None]


def _git_hookspath(root):
    # Resolve git via PATH the same way _run does, so a .cmd/.bat git shim on Windows is found and a
    # transient FileNotFoundError does not make --check falsely report the hooks as disabled.
    exe = shutil.which("git") or "git"
    try:
        out = subprocess.run([exe, "config", "--get", "core.hooksPath"],
                             cwd=root, capture_output=True, text=True)
    except OSError:
        return ""
    return out.stdout.strip()


def _playwright_cache_dir():
    """The directory Playwright installs browsers into by default (or PLAYWRIGHT_BROWSERS_PATH)."""
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override:
        return override
    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(base, "ms-playwright")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Caches", "ms-playwright")
    return os.path.join(home, ".cache", "ms-playwright")


def _chromium_installed():
    """Best-effort check that a COMPLETE Playwright Chromium build is present in the browser cache.
    Playwright writes an INSTALLATION_COMPLETE marker into a browser directory only after a full
    download, so requiring it rejects a partial/interrupted browser install. With
    PLAYWRIGHT_BROWSERS_PATH=0 the browsers live inside each node_modules, which we cannot cheaply
    enumerate, so treat that as installed (best-effort, not a false NOT-ready)."""
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") == "0":
        return True
    cache = _playwright_cache_dir()
    try:
        entries = os.listdir(cache)
    except OSError:
        return False
    return any(name.startswith("chromium")
               and os.path.isfile(os.path.join(cache, name, "INSTALLATION_COMPLETE"))
               for name in entries)


def _node_deps_installed(suite):
    """A COMPLETED `npm ci` writes node_modules/.package-lock.json; a bare or interrupted install
    leaves node_modules without it. Requiring the marker rejects a partial install as not-ready."""
    return (os.path.isdir(os.path.join(suite, "node_modules"))
            and os.path.isfile(os.path.join(suite, "node_modules", ".package-lock.json")))


def readiness_problems(root, browsers=True):
    """Human-readable reasons the clone is not dev-ready (empty list means ready). `browsers=False`
    (from `--check --no-browsers`) omits the Playwright browser requirement, matching an intentional
    browser-free setup."""
    problems = []
    for tool in ("git", "npm"):
        if shutil.which(tool) is None:
            problems.append("required tool not on PATH: " + tool)
    if _git_hookspath(root) != ".githooks":
        problems.append("git hooks are not enabled (core.hooksPath != .githooks)")
    for mod, label in (("jsonschema", "jsonschema"), ("yaml", "pyyaml")):
        if importlib.util.find_spec(mod) is None:
            problems.append("Python dependency not installed: " + label)
    suites = discover_node_suites(root)
    for suite in suites:
        if not _node_deps_installed(suite):
            problems.append("Node deps not installed (or incomplete) in " + _rel(root, suite))
    if browsers and any(suite_needs_browsers(s) for s in suites) and not _chromium_installed():
        problems.append("Playwright browser (chromium) not installed "
                        "(run 'python scripts/setup_dev.py' without --no-browsers)")
    return problems


def _run(label, cwd, cmd):
    print("== " + label + " ==")
    exe = shutil.which(cmd[0]) or cmd[0]
    proc = subprocess.run([exe] + list(cmd[1:]), cwd=cwd)
    return proc.returncode


def main(argv=None):
    argv = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(
        prog="setup_dev.py",
        description="Make a fresh clone dev-ready: enable hooks, install Python + Node deps + browsers.")
    parser.add_argument("--no-browsers", action="store_true",
                        help="skip the Playwright browser download")
    parser.add_argument("--check", action="store_true",
                        help="report readiness without installing (non-zero if not ready)")
    ns = parser.parse_args(argv[1:])

    if ns.check:
        problems = readiness_problems(ROOT, browsers=not ns.no_browsers)
        if problems:
            sys.stderr.write("dev environment is NOT ready:\n")
            for p in problems:
                sys.stderr.write("  - " + p + "\n")
            sys.stderr.write("Run: python scripts/setup_dev.py\n")
            return 1
        print("dev environment is ready.")
        return 0

    browsers = not ns.no_browsers
    missing = _require_tools(browsers)
    if missing:
        sys.stderr.write("Required tools not found on PATH: " + ", ".join(missing) + "\n")
        sys.stderr.write("Install Git, Node.js (npm/npx), and Python, then re-run.\n")
        return 1

    failed = []
    failed_suites = set()
    for step in plan(ROOT, browsers=browsers):
        # Do not run a suite's Playwright browser install if that suite's `npm ci` failed: without a
        # local Playwright, `npx playwright install` would prompt to fetch playwright@latest (hanging
        # a headless run) and pull an unpinned Chromium. Skip it and report clearly instead.
        if step.suite is not None and step.suite in failed_suites and step.cmd[:1] == ["npx"]:
            print("== %s == skipped (npm ci failed for %s)" % (step.label, step.suite))
            continue
        if _run(step.label, step.cwd, step.cmd) != 0:
            failed.append(step.label)
            if step.suite is not None:
                failed_suites.add(step.suite)
    if failed:
        sys.stderr.write("setup_dev FAILED for: " + ", ".join(failed) + "\n")
        return 1
    print("setup_dev OK (dev environment ready" + ("" if browsers else "; browsers skipped") + ").")
    return 0


if __name__ == "__main__":
    sys.exit(main())
