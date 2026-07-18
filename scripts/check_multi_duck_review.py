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

# A checked "passed" checkbox. Requires real GitHub task-list syntax: same-line horizontal
# whitespace (never a newline) around the bullet, marker, and label, so `-[x]Multi-Duck passed`
# or a line-split variant does NOT stamp. Indent is capped at 3 spaces (4+ is a code block). The
# line must be JUST the canonical stamp (optionally a trailing "(...)" note), anchored to EOL, so
# negating trailing prose - "- [x] Multi-Duck passed? No" - does not pass.
PASSED_RE = re.compile(
    r"^[ ]{0,3}[-*][ \t]+\[[xX]\][ \t]+multi-duck[ \t]+passed[ \t]*(?:\([^)\n]*\))?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
# A checked "opted out" checkbox (same same-line-whitespace rule); group(1) is everything after the
# label. Acceptance additionally requires a canonical separator + a real reason (see evaluate()).
OPTOUT_RE = re.compile(
    r"^[ ]{0,3}[-*][ \t]+\[[xX]\][ \t]+multi-duck[ \t]+opt(?:ed)?[ \t-]?out\b(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
# The reason must be introduced by a canonical separator (": " or " - "), optionally after a
# "(reason required)" hint. This rejects a checked opt-out whose trailing text negates it.
_OPTOUT_REASON_RE = re.compile(r"^\s*(?:\(reason[^)]*\))?\s*[:\-]\s*(.*)$", re.DOTALL)
# Reason values that are a placeholder rather than a real justification. Matched as the WHOLE reason
# (not a substring), so an ordinary reason that merely contains one of these words - e.g.
# "docs-only: explain why the page changed" - is accepted.
_PLACEHOLDER_REASONS = {"tbd", "todo", "n/a", "na", "reason", "reason here", "fill in", "fill-in",
                        "your reason", "why", "why the", "placeholder"}


def _strip_noise(text):
    """Remove code fences, inline code spans, and HTML comments so a stamp that is INVISIBLE in the
    rendered PR cannot pass and a stamp merely QUOTED cannot be over-eaten. Order matters:
      1. Fenced code blocks, line-anchored open (<=3 indent, per CommonMark); a valid CLOSING fence
         is the fence chars plus only trailing whitespace, and an UNTERMINATED fence runs to EOF.
      2. Inline code spans, so a literal `<!--` or a quoted `- [x]` cannot be mistaken for a comment
         opener or a real checkbox.
      3. HTML comments, closed or unterminated-to-EOF (GitHub hides both).
    Each stripped span becomes a newline so surrounding line boundaries survive."""
    text = text or ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?m)^[ ]{0,3}(`{3,}|~{3,})[^\n]*(?:.*?(?:\n[ ]{0,3}\1[ \t]*$|\Z))", "\n",
                  text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]*`", " ", text)
    text = re.sub(r"<!--.*?(?:-->|\Z)", "\n", text, flags=re.DOTALL)
    return text


def _clean_reason(raw):
    """Strip any leftover 'reason:' label and surrounding whitespace from an opted-out reason."""
    text = (raw or "").strip()
    text = re.sub(r"^reason\s*[:\-]\s*", "", text, flags=re.IGNORECASE).strip()
    return text


def _reason_is_valid(reason):
    r = reason.strip()
    if len(r) < 3:
        return False
    # A fully angle-bracket-wrapped value is the template placeholder "<a real, specific reason>".
    if r.startswith("<") and r.endswith(">"):
        return False
    # Reject only when the WHOLE reason is a placeholder word, never a substring of real prose.
    return r.lower() not in _PLACEHOLDER_REASONS


def evaluate(body, author=None):
    """Return (ok: bool, message: str) for a PR body + author.

    Order: dependabot auto-pass; then, over the body with code fences and HTML comments stripped,
    EXACTLY ONE checked stamp box must be present - a "passed" box, or an "opted out" box whose
    reason follows a canonical separator and is not a placeholder. Zero boxes, more than one box,
    or an opt-out without a real reason all fail.
    """
    if author and author.strip().lower() in AUTO_PASS_AUTHORS:
        return True, "multi-duck-review OK: %s PR auto-passes (dependency bump, not feature work)." % author
    text = _strip_noise(body or "")
    passed = PASSED_RE.findall(text)
    optout_tails = OPTOUT_RE.findall(text)
    total = len(passed) + len(optout_tails)
    if total == 0:
        return False, (
            "multi-duck-review FAILED: this PR has no multi-duck stamp. Run 2 rounds of multi-duck "
            "review, then check exactly one box in the PR body:\n"
            "  - [x] Multi-Duck passed (2 rounds of multi-duck review)\n"
            "  - [x] Multi-Duck opted out - reason: <a real, specific reason>\n"
            "This gate is required (see .github/required-checks.json); it cannot be skipped by "
            "leaving the template untouched, hiding the stamp in an HTML comment, or quoting it in "
            "a code block."
        )
    if total > 1:
        return False, (
            "multi-duck-review FAILED: %d stamp boxes are checked. Check EXACTLY ONE - either "
            "'Multi-Duck passed' or 'Multi-Duck opted out', not both and not more than one." % total
        )
    if passed:
        return True, "multi-duck-review OK: the PR is stamped multi-duck passed."
    sep = _OPTOUT_REASON_RE.match(optout_tails[0])
    reason = _clean_reason(sep.group(1)) if sep else ""
    if sep and _reason_is_valid(reason):
        return True, 'multi-duck-review OK: the PR opted out of multi-duck with reason: "%s".' % reason
    return False, (
        "multi-duck-review FAILED: the 'Multi-Duck opted out' box is checked but has no real "
        "reason. Write it as 'Multi-Duck opted out - reason: <a real, specific reason>' (not a "
        "placeholder), or run the 2 rounds of multi-duck and check 'Multi-Duck passed' instead."
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
