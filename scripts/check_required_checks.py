#!/usr/bin/env python3
"""Detect drift between the committed required-status-check list and live branch protection.

History (GH-CI-CHECK-DRIFT): the required-check set is mutable state that lives outside the
repo, and it has silently regressed before (PR #27 found live protection had dropped to
[validate, summary, build]). This tool makes the required set code-reviewed: `.github/required-checks.json`
is the source of truth, and this script compares it to what branch protection actually enforces.

Live contexts are obtained one of two ways:
  - REQUIRED_CHECKS_LIVE env var: a JSON array of context strings (supplied by a workflow that
    holds a token with admin read, so no PR code ever runs with that token); or
  - `gh api repos/<owner>/<repo>/branches/<branch>/protection/required_status_checks/contexts`
    when run locally by a maintainer who has admin access.

Exit codes: 0 = in sync; 1 = drift (missing or extra contexts); 2 = could not read live state.
Standard library only.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED_FILE = os.path.join(ROOT, ".github", "required-checks.json")
DEFAULT_REPO = "urikanonov/ai-marketplace"


def load_expected(path=EXPECTED_FILE):
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    return doc.get("branch", "main"), list(doc.get("required_status_checks", []))


def compare(expected, actual):
    """Return (missing, extra): contexts expected-but-not-live, and live-but-not-expected."""
    exp, act = set(expected), set(actual)
    return sorted(exp - act), sorted(act - exp)


def _live_from_env():
    raw = os.environ.get("REQUIRED_CHECKS_LIVE")
    if not raw:
        return None
    return list(json.loads(raw))


def _live_from_gh(repo, branch):
    try:
        proc = subprocess.run(
            ["gh", "api",
             "repos/%s/branches/%s/protection/required_status_checks/contexts" % (repo, branch)],
            capture_output=True, text=True)
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        sys.stderr.write("could not read live branch protection via gh api: "
                         + (proc.stderr.strip() or "unknown error") + "\n")
        return None
    return list(json.loads(proc.stdout))


def main(argv=None):
    argv = sys.argv if argv is None else argv
    repo = os.environ.get("REQUIRED_CHECKS_REPO", DEFAULT_REPO)
    branch, expected = load_expected()
    live = _live_from_env()
    if live is None:
        live = _live_from_gh(repo, branch)
    if live is None:
        sys.stderr.write(
            "check_required_checks: could not obtain live required contexts (need admin read via "
            "gh, or set REQUIRED_CHECKS_LIVE). Skipping - this is a maintainer/scheduled tool.\n")
        return 2
    missing, extra = compare(expected, live)
    if missing or extra:
        sys.stderr.write("check_required_checks FAILED: branch protection has drifted from "
                         ".github/required-checks.json.\n")
        for c in missing:
            sys.stderr.write("  - MISSING (expected required, not enforced live): " + c + "\n")
        for c in extra:
            sys.stderr.write("  - EXTRA (enforced live, not in the committed list): " + c + "\n")
        return 1
    print("check_required_checks OK (%d required contexts match branch protection)." % len(expected))
    return 0


if __name__ == "__main__":
    sys.exit(main())
