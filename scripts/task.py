#!/usr/bin/env python3
"""task.py - thin wrapper over the `gh` CLI for the repo's issue-first workflow.

Wraps the maintainer task lifecycle (search, new, claim, plan, check-ac, finish)
with the repo conventions baked in: the `task` label, plain-ASCII bodies, and the
Task issue-form section shape. Agents and contributors should prefer this wrapper
over raw `gh` so those conventions are not re-typed each time.

The pure helpers (build_body, create_args, tick_checkbox, assert_ascii) are unit
tested in scripts/test_task.py; the thin `_run` layer shells out to `gh`.

Usage:
  python scripts/task.py search "panel width" [--all]
  python scripts/task.py new "UI: title" -d "Why" --ac "Outcome A" --ac "Outcome B" [--plan "1. ..."]
  python scripts/task.py claim 188
  python scripts/task.py plan 188 "1. Rebase  2. Fix  3. Test"
  python scripts/task.py check-ac 188 1
  python scripts/task.py finish 188 "Short PR-style summary"
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

REPO = "urikanonov/ai-marketplace"
TASK_LABEL = "task"
IN_PROGRESS_LABEL = "status: in progress"

# Smart characters the house style forbids, mapped to their ASCII equivalents.
SMART = {
    "\u2014": " - ", "\u2013": "-", "\u2026": "...",
    "\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'",
}


def assert_ascii(text, field):
    """Raise ValueError if text has any non-ASCII character (the house style is plain ASCII)."""
    try:
        text.encode("ascii")
    except UnicodeEncodeError:
        bad = sorted({c for c in text if ord(c) > 127})
        hint = ", ".join(f"{c!r} -> {SMART[c]!r}" if c in SMART else repr(c) for c in bad)
        raise ValueError(f"{field} contains non-ASCII characters ({hint}); use plain ASCII.")


def build_body(description, acceptance, plan=None):
    """Assemble a Task issue body from its sections. Acceptance items become checkboxes."""
    assert_ascii(description, "description")
    parts = [description.strip()]
    if acceptance:
        lines = ["## Acceptance criteria", ""]
        for item in acceptance:
            assert_ascii(item, "acceptance criterion")
            lines.append(f"- [ ] {item.strip()}")
        parts.append("\n".join(lines))
    if plan:
        assert_ascii(plan, "plan")
        parts.append("## Implementation plan\n\n" + plan.strip())
    return "\n\n".join(parts)


def create_args(title, body_file, labels):
    """Build the `gh issue create` argument list."""
    assert_ascii(title, "title")
    args = ["gh", "issue", "create", "--repo", REPO, "--title", title, "--body-file", body_file]
    for lb in labels:
        args += ["--label", lb]
    return args


def _acceptance_bounds(lines):
    """Return [start, end) line indices to search for acceptance-criteria checkboxes: the
    region under a '## Acceptance criteria' heading (case-insensitive) until the next '## '
    heading, or the whole body if that heading is absent."""
    for i, line in enumerate(lines):
        if re.match(r"^\s*#{2,}\s+acceptance criteria\b", line, re.I):
            for j in range(i + 1, len(lines)):
                if re.match(r"^\s*#{2,}\s+\S", lines[j]):
                    return i + 1, j
            return i + 1, len(lines)
    return 0, len(lines)


def tick_checkbox(body, k):
    """Return body with the k-th (1-based) acceptance-criterion checkbox checked.

    Counts every checkbox in the '## Acceptance criteria' section by stable ordinal, so the
    index does not shift as items are checked; a box outside that section is never counted.
    If the k-th criterion is already checked, the body is returned unchanged (idempotent).
    Raises IndexError if k is below 1 or exceeds the number of criteria, so a wrong index
    fails loudly instead of silently checking the wrong box.
    """
    if k < 1:
        raise IndexError(f"acceptance-criterion index must be >= 1, got {k}")
    lines = body.splitlines()
    start, end = _acceptance_bounds(lines)
    seen = 0
    for i in range(start, end):
        stripped = lines[i].lstrip()
        if stripped.startswith(("- [ ] ", "- [x] ", "- [X] ")) or stripped in ("- [ ]", "- [x]", "- [X]"):
            seen += 1
            if seen == k:
                if stripped.startswith("- [ ]"):
                    indent = lines[i][: len(lines[i]) - len(stripped)]
                    lines[i] = indent + "- [x]" + stripped[5:]
                return "\n".join(lines)
    raise IndexError(f"no acceptance criterion #{k} (found {seen}) in the issue body")


def _run(args):
    """Run a command inheriting stdio; return its exit code."""
    return subprocess.run(args).returncode


def _capture(args):
    """Run a command and return its stdout; exit non-zero (surfacing stderr) on failure."""
    res = subprocess.run(args, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        raise SystemExit(res.returncode)
    return res.stdout


def _write_temp(text):
    tf = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    tf.write(text)
    tf.close()
    return tf.name


def cmd_search(a):
    args = ["gh", "issue", "list", "--repo", REPO, "--search", a.topic]
    if a.all:
        args += ["--state", "all"]
    raise SystemExit(_run(args))


def cmd_new(a):
    body = build_body(a.description, a.ac, a.plan)
    labels = [TASK_LABEL] + list(a.label or [])
    path = _write_temp(body)
    try:
        code = _run(create_args(a.title, path, labels))
    finally:
        os.unlink(path)
    raise SystemExit(code)


def cmd_claim(a):
    raise SystemExit(_run(["gh", "issue", "edit", str(a.number), "--repo", REPO,
                           "--add-assignee", "@me", "--add-label", IN_PROGRESS_LABEL]))


def cmd_plan(a):
    assert_ascii(a.text, "plan")
    raise SystemExit(_run(["gh", "issue", "comment", str(a.number), "--repo", REPO,
                           "--body", a.text]))


def cmd_check_ac(a):
    body = _capture(["gh", "issue", "view", str(a.number), "--repo", REPO,
                     "--json", "body", "--jq", ".body"])
    path = _write_temp(tick_checkbox(body, a.index))
    try:
        code = _run(["gh", "issue", "edit", str(a.number), "--repo", REPO, "--body-file", path])
    finally:
        os.unlink(path)
    raise SystemExit(code)


def cmd_finish(a):
    assert_ascii(a.summary, "summary")
    raise SystemExit(_run(["gh", "issue", "comment", str(a.number), "--repo", REPO,
                           "--body", "Final summary: " + a.summary]))


def build_parser():
    p = argparse.ArgumentParser(description="Issue-first task wrapper over gh.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="search issues")
    s.add_argument("topic")
    s.add_argument("--all", action="store_true", help="include closed history")
    s.set_defaults(func=cmd_search)

    n = sub.add_parser("new", help="create a task issue")
    n.add_argument("title")
    n.add_argument("-d", "--description", required=True)
    n.add_argument("--ac", action="append", default=[], help="acceptance criterion (repeatable)")
    n.add_argument("--plan")
    n.add_argument("--label", action="append", help="extra label (repeatable)")
    n.set_defaults(func=cmd_new)

    c = sub.add_parser("claim", help="assign @me and mark In Progress")
    c.add_argument("number", type=int)
    c.set_defaults(func=cmd_claim)

    pl = sub.add_parser("plan", help="post an implementation-plan comment")
    pl.add_argument("number", type=int)
    pl.add_argument("text")
    pl.set_defaults(func=cmd_plan)

    ca = sub.add_parser("check-ac", help="tick the k-th acceptance criterion")
    ca.add_argument("number", type=int)
    ca.add_argument("index", type=int)
    ca.set_defaults(func=cmd_check_ac)

    f = sub.add_parser("finish", help="record a final-summary comment")
    f.add_argument("number", type=int)
    f.add_argument("summary")
    f.set_defaults(func=cmd_finish)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
