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

Input: the PR body via the PR_BODY env var (the workflow passes
`${{ github.event.pull_request.body }}`), or `--body-file PATH`, or stdin; the PR author via
the PR_AUTHOR env var (or `--author`). Exit 0 when a valid stamp (or auto-pass) is present,
1 otherwise. Standard library only.
"""
import argparse
import os
import re
import sys

# Authors whose PRs do not need a manual multi-duck stamp (automation, not feature work).
AUTO_PASS_AUTHORS = {"dependabot[bot]", "dependabot-preview[bot]"}

# A checked "passed" checkbox. The label wording after "passed" is free-form (e.g. "(2 rounds)").
PASSED_RE = re.compile(
    r"^\s*[-*]\s*\[[xX]\]\s*multi-duck\s+passed\b",
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
    low = reason.lower()
    if reason.startswith("<") or "<" in reason and ">" in reason:
        return False
    return not any(tok in low for tok in _PLACEHOLDER_TOKENS)


def evaluate(body, author=None):
    """Return (ok: bool, message: str) for a PR body + author.

    Order: dependabot auto-pass, then a checked "passed" box, then a checked "opted out" box
    with a valid reason. Anything else fails.
    """
    if author and author.strip().lower() in AUTO_PASS_AUTHORS:
        return True, "multi-duck-review OK: %s PR auto-passes (dependency bump, not feature work)." % author
    text = body or ""
    if PASSED_RE.search(text):
        return True, "multi-duck-review OK: the PR is stamped multi-duck passed."
    m = OPTOUT_RE.search(text)
    if m is not None:
        reason = _clean_reason(m.group(1))
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
        "the template untouched."
    )


def _read_body(args):
    if args.body_file:
        with open(args.body_file, "r", encoding="utf-8") as fh:
            return fh.read()
    env = os.environ.get("PR_BODY")
    if env is not None:
        return env
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body-file", default=None, help="Read the PR body from this file instead of PR_BODY/stdin.")
    parser.add_argument("--author", default=os.environ.get("PR_AUTHOR", ""), help="PR author login (for auto-pass).")
    args = parser.parse_args(argv)
    body = _read_body(args)
    ok, message = evaluate(body, args.author)
    if ok:
        print(message)
        return 0
    sys.stderr.write(message + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
