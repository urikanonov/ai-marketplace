#!/usr/bin/env python3
"""Enforce the repository's CI trust-boundary invariants as code.

The auto-run-CI-on-outside-PRs safety documented in AGENTS.md rests on a few invariants that
`actionlint` cannot check. This gate encodes them so a future edit cannot quietly turn an
auto-run into arbitrary code execution with a privileged token, or leak a secret to PR code:

  RULE A - A `pull_request_target` workflow (which runs in the trusted base context with a
           write-capable token and secrets) must NOT check out or run PR-authored code. We
           enforce the strict, statically-checkable form: no `actions/checkout` in such a
           workflow. (Near-miss history: PR #24's pages deploy nearly ran repo code with an
           OIDC token; the fix was to keep PR code out of the privileged job.)

  RULE B - A workflow that runs PR-authored code (any `pull_request` trigger) must NOT
           reference `secrets.*`. Privileged, main-only work belongs in a separate
           `push`/`pull_request_target` workflow (AGENTS.md: "split it"). This keeps the
           gates that execute PR code read-only and secret-free on same-repo PRs, where the
           fork sandbox does not engage.

  RULE C - `.github/actionlint.yaml` must not carry a non-empty `ignore` list. History
           (PR #38 -> #44/#45): an invalid `on:` event silently disabled a required workflow;
           actionlint caught it, but a hand-written ignore claiming the event was
           "valid and load-bearing" silenced the one tool that was right.

Exit non-zero on any violation. Standard library plus PyYAML only.
"""
import glob
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS_DIR = os.path.join(ROOT, ".github", "workflows")
ACTIONLINT_CONFIG = os.path.join(ROOT, ".github", "actionlint.yaml")


def _triggers(doc):
    """Return the set of trigger names for a parsed workflow. PyYAML uses YAML 1.1, so the
    bare `on:` key is parsed as the boolean True, not the string 'on' - handle both."""
    on = doc.get("on")
    if on is None:
        on = doc.get(True)
    if on is None:
        return set()
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    if isinstance(on, dict):
        return set(on.keys())
    return set()


def check_workflow(path):
    """Return a list of violation strings for one workflow file."""
    rel = os.path.relpath(path, ROOT)
    violations = []
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return [rel + ": could not parse YAML (" + str(exc) + ")"]
    triggers = _triggers(doc)

    # RULE A: a pull_request_target workflow must not check out PR code.
    if "pull_request_target" in triggers and re.search(r"uses:\s*actions/checkout", text):
        violations.append(
            rel + ": RULE A - a pull_request_target workflow must not use actions/checkout "
            "(it would run PR-authored code with a privileged token). Move PR-code steps to a "
            "separate pull_request job.")

    # RULE B: a workflow that runs PR code (pull_request) must not reference secrets.
    if "pull_request" in triggers and re.search(r"\bsecrets\.", text):
        violations.append(
            rel + ": RULE B - a pull_request workflow must not reference secrets.* (it executes "
            "PR-authored code). Put privileged, secret-using steps in a separate push or "
            "pull_request_target workflow.")

    return violations


def check_actionlint_config():
    """Return a list of violations for a non-empty actionlint ignore list."""
    if not os.path.exists(ACTIONLINT_CONFIG):
        return []
    with open(ACTIONLINT_CONFIG, "r", encoding="utf-8") as fh:
        try:
            doc = yaml.safe_load(fh) or {}
        except yaml.YAMLError as exc:
            return [".github/actionlint.yaml: could not parse YAML (" + str(exc) + ")"]
    ignores = []
    top = doc.get("ignore")
    if isinstance(top, list):
        ignores.extend(top)
    paths = doc.get("paths")
    if isinstance(paths, dict):
        for spec in paths.values():
            if isinstance(spec, dict) and isinstance(spec.get("ignore"), list):
                ignores.extend(spec["ignore"])
    if ignores:
        return [".github/actionlint.yaml: RULE C - the actionlint ignore list must be empty. "
                "A suppression silences the tool that catches invalid workflows; fix the "
                "workflow instead of ignoring the warning. Current ignores: " + repr(ignores)]
    return []


def main():
    violations = []
    for path in sorted(glob.glob(os.path.join(WORKFLOWS_DIR, "*.yml"))
                       + glob.glob(os.path.join(WORKFLOWS_DIR, "*.yaml"))):
        violations.extend(check_workflow(path))
    violations.extend(check_actionlint_config())
    if violations:
        sys.stderr.write("check_workflow_policy FAILED:\n")
        for v in violations:
            sys.stderr.write("  - " + v + "\n")
        return 1
    print("check_workflow_policy OK (CI trust-boundary invariants hold).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
