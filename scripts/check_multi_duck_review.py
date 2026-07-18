#!/usr/bin/env python3
"""Required PR gate: every feature PR must carry a multi-duck review stamp.

Maintainer rule: before a feature PR is completed, run 2 rounds of the multi-duck review
by default. To make that auditable, a PR body must carry a stamp that it either PASSED the
multi-duck review or explicitly OPTED OUT (with a reason). Without a valid stamp this check
fails, so the PR cannot merge (the check context `multi-duck-review` is a required status
check on main - see .github/required-checks.json).

The stamp lives as a CHECKED checkbox in the PR body (the pull-request template seeds both
options; the author checks exactly one):

    - [x] Multi-Duck passed (2 rounds of multi-duck review)
    - [x] Multi-Duck opted out - reason: <a real, specific reason>

An UNCHECKED template (neither box ticked) fails, so the author cannot merge by leaving the
template untouched. An opted-out box with an empty or placeholder reason also fails.

Dependabot PRs auto-pass (they are dependency bumps, not feature work), mirroring how the
require-owner-approval gate treats automation.

Input: the checker reads the PR body and author from the GitHub Actions event payload
(`GITHUB_EVENT_PATH`) as data, so a large (up to ~65KB) PR body cannot overflow an env var and
crash the runner, and no PR-authored text is ever interpolated into a shell command. For local
use / tests it also accepts `--body-file PATH`, the `PR_BODY` env var, or stdin, and `--author` /
`PR_AUTHOR`. The verdict is a deterministic regex over the body (no LLM), so PR text cannot
prompt-inject the outcome. Exit 0 when a valid stamp (or auto-pass) is present, 1 otherwise.
Standard library only.
"""
import argparse
import json
import os
import re
import sys

# Authors whose PRs do not need a manual multi-duck stamp (automation, not feature work).
AUTO_PASS_AUTHORS = {"dependabot[bot]", "dependabot-preview[bot]"}

# A checked "passed" checkbox. The line must be JUST the canonical stamp (optionally with a
# trailing "(...)" note like "(2 rounds)"), anchored to end-of-line, so trailing prose that negates
# it - e.g. "- [x] Multi-Duck passed? No, not really" - does NOT count as a pass.
PASSED_RE = re.compile(
    r"^\s*[-*]\s*\[[xX]\]\s*multi-duck\s+passed\s*(?:\([^)\n]*\))?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# A checked "opted out" checkbox; group(1) is everything after the label, which must contain a
# real reason. "opt out", "opted-out", and "opted out" are all accepted.
OPTOUT_RE = re.compile(
    r"^\s*[-*]\s*\[[xX]\]\s*multi-duck\s+opt(?:ed)?[ -]?out\b(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
# Reason text that is really an unfilled placeholder, not a genuine justification.
_PLACEHOLDER_TOKENS = ("fill in", "fill-in", "reason here", "why the", "your reason", "tbd", "todo")


def _strip_noise(text):
    """Remove HTML comments and fenced code blocks so a checked stamp that is INVISIBLE in the
    rendered PR (hidden in `<!-- ... -->`) or merely QUOTED (in a ``` or ~~~ code fence, e.g. a PR
    that documents this very template) cannot silently pass the gate. The stamp must be a real,
    rendered checkbox."""
    text = text or ""
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"~~~.*?~~~", " ", text, flags=re.DOTALL)
    return text


def _clean_reason(raw):
    """Strip the boilerplate around an opted-out reason and return the substantive text."""
    text = (raw or "").strip()
    # Drop a leading "(reason required)" style hint and the following separator/label.
    text = re.sub(r"^\(reason[^)]*\)", "", text, flags=re.IGNORECASE).strip()
    text = text.lstrip(":-").strip()
    text = re.sub(r"^reason\s*[:\-]\s*", "", text, flags=re.IGNORECASE).strip()
    return text


def _reason_is_valid(reason):
    if len(reason) < 3:
        return False
    # Only a fully angle-bracket-wrapped value is a placeholder (the template's
    # "<a real, specific reason>"). A reason that merely CONTAINS "<" and ">" - e.g. a latency
    # target "keep p95 < 200ms and rps > 1k" - is a real reason and must be accepted.
    if reason.startswith("<") and reason.endswith(">"):
        return False
    low = reason.lower()
    return not any(tok in low for tok in _PLACEHOLDER_TOKENS)


def evaluate(body, author=None):
    """Return (ok: bool, message: str) for a PR body + author.

    Order: dependabot auto-pass; then, over the body with HTML comments and code fences stripped,
    exactly one checked box must be present - a checked "passed" box, or a checked "opted out" box
    with a valid reason. Both boxes checked, neither checked, or an opt-out without a real reason
    all fail.
    """
    if author and author.strip().lower() in AUTO_PASS_AUTHORS:
        return True, "multi-duck-review OK: %s PR auto-passes (dependency bump, not feature work)." % author
    text = _strip_noise(body or "")
    passed = PASSED_RE.search(text)
    optout = OPTOUT_RE.search(text)
    if passed and optout:
        return False, (
            "multi-duck-review FAILED: both the 'Multi-Duck passed' and 'Multi-Duck opted out' "
            "boxes are checked. Check EXACTLY ONE."
        )
    if passed:
        return True, "multi-duck-review OK: the PR is stamped multi-duck passed."
    if optout is not None:
        reason = _clean_reason(optout.group(1))
        if _reason_is_valid(reason):
            return True, 'multi-duck-review OK: the PR opted out of multi-duck with reason: "%s".' % reason
        return False, (
            "multi-duck-review FAILED: the 'Multi-Duck opted out' box is checked but has no real "
            "reason. Fill in a specific reason after 'reason:' (not a placeholder), or run the 2 "
            "rounds of multi-duck and check 'Multi-Duck passed' instead."
        )
    return False, (
        "multi-duck-review FAILED: this PR has no multi-duck stamp. Run 2 rounds of multi-duck "
        "review, then check exactly one box in the PR body:\n"
        "  - [x] Multi-Duck passed (2 rounds of multi-duck review)\n"
        "  - [x] Multi-Duck opted out - reason: <a real, specific reason>\n"
        "This gate is required (see .github/required-checks.json); it cannot be skipped by leaving "
        "the template untouched, hidden in an HTML comment, or quoted in a code block."
    )


def _read_body_and_author(args):
    """Resolve (body, author). Precedence: --body-file, then PR_BODY env (tests/manual), then the
    GitHub Actions event payload at GITHUB_EVENT_PATH (the CI path - reads the body as data, immune
    to env-size limits), then stdin."""
    if args.body_file:
        with open(args.body_file, "r", encoding="utf-8") as fh:
            return fh.read(), args.author
    env_body = os.environ.get("PR_BODY")
    if env_body is not None:
        return env_body, args.author
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and os.path.exists(event_path):
        try:
            with open(event_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            pr = data.get("pull_request") or {}
            author = args.author or ((pr.get("user") or {}).get("login") or "")
            return (pr.get("body") or ""), author
        except (OSError, ValueError):
            pass
    if not sys.stdin.isatty():
        return sys.stdin.read(), args.author
    return "", args.author


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body-file", default=None, help="Read the PR body from this file instead of the event payload.")
    parser.add_argument("--author", default=os.environ.get("PR_AUTHOR", ""), help="PR author login (for auto-pass).")
    args = parser.parse_args(argv)
    body, author = _read_body_and_author(args)
    ok, message = evaluate(body, author)
    if ok:
        print(message)
        return 0
    sys.stderr.write(message + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
