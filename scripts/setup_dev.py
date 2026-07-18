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

Step = collections.namedtuple("Step", ["label", "cwd", "cmd"])


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
    deps.update(pkg.get("dependencies") or {})
    deps.update(pkg.get("devDependencies") or {})
    return "playwright" in deps or "@playwright/test" in deps


def plan(root, browsers=True):
    """The ordered list of setup Steps. Pure: it builds the commands without running them, so it is
    fully unit-testable and deterministic (every command is safe to re-run - the setup is idempotent)."""
    steps = [
        Step("enable git hooks (core.hooksPath)", root,
             ["git", "config", "core.hooksPath", ".githooks"]),
        Step("install Python validator deps (jsonschema, pyyaml)", root,
             [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
              "jsonschema", "pyyaml"]),
    ]
    for suite in discover_node_suites(root):
        rel = _rel(root, suite)
        steps.append(Step("install Node deps: " + rel, suite, ["npm", "ci", "--ignore-scripts"]))
        if browsers and suite_needs_browsers(suite):
            steps.append(Step("install Playwright browser (chromium): " + rel, suite,
                              ["npx", "playwright", "install", "chromium"]))
    return steps


def _require_tools(browsers):
    """Names of required external tools that are not on PATH (so setup can fail fast with a list)."""
    needed = ["git", "npm"]
    if browsers:
        needed.append("npx")
    return [t for t in needed if shutil.which(t) is None]


def _git_hookspath(root):
    try:
        out = subprocess.run(["git", "config", "--get", "core.hooksPath"],
                             cwd=root, capture_output=True, text=True)
    except OSError:
        return ""
    return out.stdout.strip()


def readiness_problems(root):
    """Human-readable reasons the clone is not dev-ready (empty list means ready)."""
    problems = []
    if _git_hookspath(root) != ".githooks":
        problems.append("git hooks are not enabled (core.hooksPath != .githooks)")
    for mod, label in (("jsonschema", "jsonschema"), ("yaml", "pyyaml")):
        if importlib.util.find_spec(mod) is None:
            problems.append("Python dependency not installed: " + label)
    for suite in discover_node_suites(root):
        if not os.path.isdir(os.path.join(suite, "node_modules")):
            problems.append("Node deps not installed in " + _rel(root, suite))
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
        problems = readiness_problems(ROOT)
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
    for step in plan(ROOT, browsers=browsers):
        if _run(step.label, step.cwd, step.cmd) != 0:
            failed.append(step.label)
    if failed:
        sys.stderr.write("setup_dev FAILED for: " + ", ".join(failed) + "\n")
        return 1
    print("setup_dev OK (dev environment ready" + ("" if browsers else "; browsers skipped") + ").")
    return 0


if __name__ == "__main__":
    sys.exit(main())
