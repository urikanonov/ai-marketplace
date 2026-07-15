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
    """Raise ValueError if text carries smart punctuation the house style forbids."""
    bad = sorted({c for c in text if c in SMART})
    if bad:
        hint = ", ".join(f"{c!r} -> {SMART[c]!r}" for c in bad)
        raise ValueError(f"{field} contains non-ASCII smart characters ({hint}); use plain ASCII.")


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


def tick_checkbox(body, k):
    """Return body with the k-th (1-based) unchecked `- [ ]` item checked.

    Raises IndexError if there is no k-th unchecked item, so a wrong index fails
    loudly instead of silently checking the wrong box.
    """
    if k < 1:
        raise IndexError(f"acceptance-criterion index must be >= 1, got {k}")
    seen = 0
    out = []
    done = False
    for line in body.splitlines():
        stripped = line.lstrip()
        if not done and stripped.startswith("- [ ]"):
            seen += 1
            if seen == k:
                indent = line[: len(line) - len(stripped)]
                out.append(indent + "- [x]" + stripped[len("- [ ]"):])
                done = True
                continue
        out.append(line)
    if not done:
        raise IndexError(f"no unchecked acceptance criterion #{k} in the issue body")
    return "\n".join(out)


def _run(args, capture=False):
    """Shell out to `gh` (or another command). Thin, so tests mock this boundary."""
    if capture:
        res = subprocess.run(args, capture_output=True, text=True)
        if res.returncode != 0:
            sys.stderr.write(res.stderr)
            sys.exit(res.returncode)
        return res.stdout
    sys.exit(subprocess.run(args).returncode)


def _write_temp(text):
    tf = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    tf.write(text)
    tf.close()
    return tf.name


def cmd_search(a):
    args = ["gh", "issue", "list", "--repo", REPO, "--search", a.topic]
    if a.all:
        args += ["--state", "all"]
    _run(args)


def cmd_new(a):
    body = build_body(a.description, a.ac, a.plan)
    labels = [TASK_LABEL] + list(a.label or [])
    _run(create_args(a.title, _write_temp(body), labels))


def cmd_claim(a):
    _run(["gh", "issue", "edit", str(a.number), "--repo", REPO,
          "--add-assignee", "@me", "--add-label", IN_PROGRESS_LABEL])


def cmd_plan(a):
    assert_ascii(a.text, "plan")
    _run(["gh", "issue", "comment", str(a.number), "--repo", REPO, "--body", a.text])


def cmd_check_ac(a):
    body = _run(["gh", "issue", "view", str(a.number), "--repo", REPO,
                 "--json", "body", "--jq", ".body"], capture=True)
    _run(["gh", "issue", "edit", str(a.number), "--repo", REPO,
          "--body-file", _write_temp(tick_checkbox(body, a.index))])


def cmd_finish(a):
    assert_ascii(a.summary, "summary")
    _run(["gh", "issue", "comment", str(a.number), "--repo", REPO,
          "--body", "Final summary: " + a.summary])


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
