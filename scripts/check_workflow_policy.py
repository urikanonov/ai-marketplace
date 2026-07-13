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
ACTIONLINT_CONFIGS = (
    os.path.join(ROOT, ".github", "actionlint.yaml"),
    os.path.join(ROOT, ".github", "actionlint.yml"),
)


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


def _strip_full_line_comments(text):
    """Drop YAML full-line comments (a line whose first non-space char is '#') so a mention of
    `uses: actions/checkout` or `secrets.X` inside a comment is not scanned as real config."""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


# Ways a privileged (pull_request_target) workflow could run PR-authored code. `uses: actions/checkout`
# (optionally quoted) is the common one; `gh pr checkout` is the other high-precision signal. We do
# NOT flag a bare `github.event.pull_request.head.sha` reference: reading the head SHA to POST a commit
# status (as require-owner-approval.yml does) is safe metadata use, not running PR code. Transitive PR
# checkout inside a reusable `workflow_call` callee is a known limitation - review reachable callees.
_CHECKOUT_RE = re.compile(r"""uses:\s*["']?actions/checkout""")
_PR_CODE_RES = (
    (re.compile(r"gh\s+pr\s+checkout"), "gh pr checkout"),
)
# Secret references a pull_request (PR-code) workflow must not carry: dotted, bracket, or `inherit`.
_SECRETS_RES = (
    (re.compile(r"\bsecrets\."), "secrets.*"),
    (re.compile(r"\bsecrets\s*\["), "secrets['...']"),
    (re.compile(r"\bsecrets\s*:\s*inherit"), "secrets: inherit"),
)


def check_workflow(path):
    """Return a list of violation strings for one workflow file."""
    try:
        rel = os.path.relpath(path, ROOT)
    except ValueError:
        # On Windows, relpath raises when path and ROOT are on different drives (e.g. a temp
        # file on C: while the repo is on D:). Fall back to the raw path for the message.
        rel = path
    violations = []
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    try:
        doc = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        return [rel + ": could not parse YAML (" + str(exc) + ")"]
    triggers = _triggers(doc)
    text = _strip_full_line_comments(raw)

    # RULE A: a pull_request_target workflow must not check out or otherwise materialize PR code.
    if "pull_request_target" in triggers:
        if _CHECKOUT_RE.search(text):
            violations.append(
                rel + ": RULE A - a pull_request_target workflow must not use actions/checkout "
                "(it would run PR-authored code with a privileged token). Move PR-code steps to a "
                "separate pull_request job.")
        for rx, label in _PR_CODE_RES:
            if rx.search(text):
                violations.append(
                    rel + ": RULE A - a pull_request_target workflow must not materialize PR code via "
                    + label + " (it would run PR-authored code with a privileged token).")

    # RULE B: a workflow that runs PR code (pull_request) must not reference secrets in any form.
    if "pull_request" in triggers:
        for rx, label in _SECRETS_RES:
            if rx.search(text):
                violations.append(
                    rel + ": RULE B - a pull_request workflow must not reference " + label
                    + " (it executes PR-authored code). Put privileged, secret-using steps in a "
                    "separate push or pull_request_target workflow.")

    return violations


def check_actionlint_config():
    """Return a list of violations for a non-empty actionlint ignore list (either config filename)."""
    for config in ACTIONLINT_CONFIGS:
        if not os.path.exists(config):
            continue
        rel = os.path.relpath(config, ROOT)
        with open(config, "r", encoding="utf-8") as fh:
            try:
                doc = yaml.safe_load(fh) or {}
            except yaml.YAMLError as exc:
                return [rel + ": could not parse YAML (" + str(exc) + ")"]
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
            return [rel + ": RULE C - the actionlint ignore list must be empty. "
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
