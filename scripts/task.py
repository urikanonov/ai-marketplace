#!/usr/bin/env python3
"""task.py - thin wrapper over the `gh` CLI for the repo's issue-first workflow.

Wraps the maintainer task lifecycle (search, new, claim, plan, check-ac, finish)
with the repo conventions baked in: the `task` label, plain-ASCII bodies, and the
Task issue-form section shape. Agents and contributors should prefer this wrapper
over raw `gh` so those conventions are not re-typed each time.

The pure helpers (build_body, create_args, tick_checkbox, tick_all_checkboxes, apply_ac_check,
assert_ascii, assert_valid_session, status_body, bump_last_active, set_session, parse_session,
board_row, format_board, find_status_comment, status_comments, extra_status_comment_ids,
parse_last_active, parse_branch, is_stale, is_newer, utc_stamp, assert_valid_branch, branch_slug,
derive_branch, resolve_project_number, select_text_field_id,
select_item_id_for_project, build_field_update_variables, item_field_text, field_updates,
field_action, parse_active_scopes) are unit tested in scripts/test_task.py; the thin `_run` layer
shells out to `gh` and `git`.

Usage:
  python scripts/task.py search "panel width" [--all]
  python scripts/task.py new "UI: title" -d "Why" --ac "Outcome A" --ac "Outcome B" [--plan "1. ..."]
  python scripts/task.py start 188 [--slug "short desc"]   # worktree + branch + claim + stamp
  python scripts/task.py claim 188 [--branch issue-188-foo] [--session-id <id>]
  python scripts/task.py heartbeat 188 [--watch] [--interval 300] [--session-id <id>]
  python scripts/task.py stale [--minutes 15]
  python scripts/task.py board [--all-labels] [--json] [--minutes 15]
  python scripts/task.py project-sync [--issue 188] [--dry-run]  # Projects v2 fields
  python scripts/task.py plan 188 "1. Rebase  2. Fix  3. Test"
  python scripts/task.py check-ac 188 1
  python scripts/task.py check-ac 188 --all
  python scripts/task.py finish 188 "Short PR-style summary"

The handling Copilot session id defaults to the COPILOT_AGENT_SESSION_ID environment variable, so
`start`/`claim`/`heartbeat` record which session is on an issue without an explicit flag; `board`
surfaces it (with the branch and last activity) across all open issues.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

REPO = "urikanonov/ai-marketplace"
TASK_LABEL = "task"
IN_PROGRESS_LABEL = "status: in progress"

# The single pinned "Work status" comment carries the worktree branch and a rolling UTC
# heartbeat. It is edited in place (found by this marker) so the timeline is not spammed.
STATUS_MARKER = "<!-- task-status: heartbeat -->"
# How often the heartbeat daemon refreshes the timestamp while work is active.
HEARTBEAT_INTERVAL_SECONDS = 300
# A heartbeat older than this (or missing) means no agent is actively working the issue.
HEARTBEAT_STALE_MINUTES = 15
# Only a marker comment authored by one of these associations is trusted as THE status comment.
# On a public repo anyone can comment, so an outsider (CONTRIBUTOR/NONE) could plant the marker;
# adopting only maintainer/collaborator comments stops that from hijacking the automation.
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
# The fixed-width UTC timestamp format used in the Work status comment (lexicographically sortable).
_UTC_FMT = "%Y-%m-%dT%H:%M:%SZ"


class HeartbeatStop(Exception):
    """Raised when the heartbeat cannot continue (a fatal setup error, e.g. no branch and no
    status comment). The --watch daemon stops on this but keeps beating through transient
    command failures, so a stopped heartbeat still means work genuinely stopped."""


class ProjectSyncSkip(Exception):
    """Raised when project-sync cannot proceed for an EXPECTED, non-fatal reason (the `project`
    gh scope is not granted, no project is configured, or the board lacks the target fields). It
    carries an actionable message; the command turns it into a clean no-op (exit 0) so it never
    breaks a run and is safe to call best-effort from the heartbeat."""

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


def tick_all_checkboxes(body):
    """Return body with EVERY acceptance-criterion checkbox in the '## Acceptance criteria'
    section checked, preserving all other text byte-for-byte. Idempotent (already-checked
    boxes are left as-is). Requires an explicit '## Acceptance criteria' heading and raises
    IndexError if it is absent or the section has no checkbox - so an --all run never falls
    back to the whole body and ticks unrelated checkboxes (an implementation plan, a
    'before starting' list), and it fails loudly against a body with no criteria.
    """
    lines = body.splitlines()
    if not any(re.match(r"^\s*#{2,}\s+acceptance criteria\b", ln, re.I) for ln in lines):
        raise IndexError("no '## Acceptance criteria' section in the issue body")
    start, end = _acceptance_bounds(lines)
    seen = 0
    for i in range(start, end):
        stripped = lines[i].lstrip()
        if stripped.startswith(("- [ ] ", "- [x] ", "- [X] ")) or stripped in ("- [ ]", "- [x]", "- [X]"):
            seen += 1
            if stripped.startswith("- [ ]"):
                indent = lines[i][: len(lines[i]) - len(stripped)]
                lines[i] = indent + "- [x]" + stripped[5:]
    if seen == 0:
        raise IndexError("no acceptance criteria found in the issue body")
    return "\n".join(lines)


def apply_ac_check(body, index, check_all):
    """Dispatch for the check-ac command: tick every criterion when check_all is set, else the
    single 1-based index. Raises ValueError when neither is given, or when both an index and
    --all are passed (contradictory), so the CLI fails loudly instead of silently ignoring one."""
    if check_all:
        if index is not None:
            raise ValueError("check-ac: pass an INDEX or --all, not both")
        return tick_all_checkboxes(body)
    if index is None:
        raise ValueError("check-ac needs an INDEX or --all")
    return tick_checkbox(body, index)


# --- heartbeat + branch-stamp helpers (pure) -------------------------------------------

_LAST_ACTIVE_RE = re.compile(r"^- Last active \(UTC\): .*$", re.M)


def utc_stamp(now=None):
    """Return a UTC ISO-8601 timestamp like '2026-07-18T13:55:00Z'.

    Accepts an optional timezone-aware datetime (for tests); defaults to the current
    time. A naive datetime is assumed to already be UTC.
    """
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime(_UTC_FMT)


def is_newer(candidate, existing):
    """True if `candidate` (a UTC stamp) should overwrite `existing`.

    Returns True when existing is missing or unparseable (candidate is authoritative), and
    otherwise only when candidate is strictly later than existing. This makes a heartbeat
    monotonic: an out-of-order or clock-skewed beat cannot move a newer timestamp backwards.
    """
    if not existing:
        return True
    try:
        e = datetime.strptime(existing, _UTC_FMT)
    except ValueError:
        return True
    try:
        c = datetime.strptime(candidate, _UTC_FMT)
    except ValueError:
        return False
    return c > e


def assert_valid_branch(branch):
    """Validate a branch name for use in a stamp/comment and as a git argument.

    Rejects non-ASCII (house style), a leading '-' (which git/gh could read as an option),
    backticks (which would break the markdown code span in the comment), and any whitespace.
    Returns the stripped branch. Raises ValueError on a bad name.
    """
    assert_ascii(branch, "branch")
    b = branch.strip()
    if not b or b.startswith("-") or "`" in b or any(c.isspace() for c in b):
        raise ValueError(
            f"invalid branch name {branch!r}: no leading dash, backticks, or whitespace")
    return b


def assert_valid_session(session):
    """Validate a handling-session id for use inside the status comment's code span.

    Rejects non-ASCII (house style), backticks (which would break the markdown code span),
    and whitespace. Returns the stripped id. Raises ValueError on a bad value. A Copilot CLI
    session id (a UUID) always passes.
    """
    assert_ascii(session, "session")
    s = session.strip()
    if not s or "`" in s or any(c.isspace() for c in s):
        raise ValueError(f"invalid session id {session!r}: no backticks or whitespace")
    return s


def status_body(branch, stamp, session=""):
    """Build the pinned 'Work status' comment body for a branch and UTC timestamp.

    Carries STATUS_MARKER (so the comment can be found and edited in place), the
    worktree branch (so dropped work can be resumed from it), the handling Copilot
    session id when known (so a board can show which session is on the issue), and the
    last-active timestamp (the heartbeat). Plain ASCII, per the house style.
    """
    branch = assert_valid_branch(branch)
    lines = [
        STATUS_MARKER,
        "### Work status (automated heartbeat)",
        "",
        f"- Branch: `{branch}` (local worktree; if this work is dropped, resume from this branch)",
    ]
    if session:
        lines.append(f"- Handling session: `{assert_valid_session(session)}`")
    lines += [
        f"- Last active (UTC): {stamp}",
        "",
        f"This comment is refreshed automatically at least every {HEARTBEAT_INTERVAL_SECONDS // 60} "
        "minutes while an agent is actively working this issue. If the timestamp above is more than "
        f"{HEARTBEAT_STALE_MINUTES} minutes old, no one is actively working it - it is safe to take "
        "over from the branch above.",
    ]
    return "\n".join(lines)


def bump_last_active(body, stamp):
    """Return body with only the 'Last active (UTC)' line updated to stamp.

    Preserves the branch line so a heartbeat never loses the stamped branch. Raises
    ValueError if the body has no last-active line (so a malformed comment fails loudly).
    """
    new_body, n = _LAST_ACTIVE_RE.subn(f"- Last active (UTC): {stamp}", body)
    if n == 0:
        raise ValueError("no 'Last active (UTC)' line found in the status comment body")
    return new_body


def set_session(body, session):
    """Return body with the 'Handling session' line set to `session`, inserting it after the
    Branch line (or, failing that, before the Last active line) when absent. An empty session
    returns the body unchanged (any existing session line is preserved), so a beater that does not
    know its session id never erases a known one. Removes ALL existing handling-session lines first
    (a crafted/legacy body could carry duplicates or a malformed one), then writes exactly one.
    Used by the heartbeat so the board reflects the session currently beating.
    """
    if not session:
        return body
    line = f"- Handling session: `{assert_valid_session(session)}`"
    body = re.sub(r"(?m)^- Handling session:.*\n?", "", body)  # drop any/all existing lines
    if re.search(r"^- Branch: `[^`]+`.*$", body, re.M):
        return re.sub(r"^(- Branch: `[^`]+`.*)$", lambda m: m.group(1) + "\n" + line,
                      body, count=1, flags=re.M)
    # Fallback for a comment missing the Branch line (hand-edited/malformed): anchor before the
    # Last active line so the session is still recorded rather than silently dropped.
    if re.search(r"^- Last active \(UTC\):", body, re.M):
        return re.sub(r"^(- Last active \(UTC\):.*)$", lambda m: line + "\n" + m.group(1),
                      body, count=1, flags=re.M)
    return body


def find_status_comment(comments, trusted_only=False, viewer=None):
    """Return the first matching status comment (see status_comments), or None."""
    matches = status_comments(comments, trusted_only, viewer)
    return matches[0] if matches else None


def _is_status_comment(comment, trusted_only, viewer):
    """True if comment carries STATUS_MARKER and is trusted.

    A marker comment is trusted when trusted_only is off, or its author_association is in
    TRUSTED_ASSOCIATIONS, or it was authored by `viewer` (the invoking account owns its own
    comment even if its association is NONE, e.g. a bot). Anything else is an outsider's plant.
    """
    if STATUS_MARKER not in (comment.get("body") or ""):
        return False
    if not trusted_only:
        return True
    if (comment.get("assoc") or "").upper() in TRUSTED_ASSOCIATIONS:
        return True
    return bool(viewer) and (comment.get("author") or "").lower() == viewer.lower()


def status_comments(comments, trusted_only=False, viewer=None):
    """Return every matching status comment, in list order (chronological from the API)."""
    return [c for c in comments if _is_status_comment(c, trusted_only, viewer)]


def _pick_survivor(matches):
    """Choose the canonical status comment to keep among trusted matches: prefer a globally
    trusted (maintainer/collaborator) comment over a self-only one, oldest first. This keeps
    convergence actor-safe - it never deletes a maintainer's comment in favor of a self-authored
    duplicate; the owner of a self-only comment prunes its own instead."""
    trusted = [c for c in matches if (c.get("assoc") or "").upper() in TRUSTED_ASSOCIATIONS]
    return (trusted or matches)[0]


def _max_stamp(stamps):
    """Return the newest well-formed UTC stamp from an iterable (or None). Used so converging
    duplicates never regresses the effective timestamp below the newest one already published.
    Compares parsed datetimes (not strings) so a non-zero-padded stamp cannot misorder."""
    best, best_dt = None, None
    for s in stamps:
        if not s:
            continue
        try:
            dt = datetime.strptime(s, _UTC_FMT)
        except ValueError:
            continue
        if best_dt is None or dt > best_dt:
            best, best_dt = s, dt
    return best


def extra_status_comment_ids(comments, trusted_only=False, viewer=None):
    """Return the ids of duplicate status comments (all matches except the survivor) to prune."""
    matches = status_comments(comments, trusted_only, viewer)
    if not matches:
        return []
    survivor = _pick_survivor(matches)
    return [c["id"] for c in matches if c["id"] != survivor["id"]]


def parse_last_active(body):
    """Return the UTC timestamp string from a status-comment body, or None if absent."""
    m = re.search(r"^- Last active \(UTC\): (\S+)", body or "", re.M)
    return m.group(1) if m else None


def parse_branch(body):
    """Return the branch name stamped in a status-comment body, or None if absent."""
    m = re.search(r"^- Branch: `([^`]+)`", body or "", re.M)
    return m.group(1) if m else None


def parse_session(body):
    """Return the handling Copilot session id in a status-comment body, or None if absent."""
    m = re.search(r"^- Handling session: `([^`]+)`", body or "", re.M)
    return m.group(1) if m else None


def _valid_session_or_empty(session):
    """Return the session id if it passes assert_valid_session, else '' - so a parsed value from a
    crafted/legacy status comment (e.g. spaces inside the code span) can never propagate into
    set_session and raise mid-heartbeat."""
    try:
        return assert_valid_session(session) if session else ""
    except ValueError:
        return ""


def _session_at_newest(matches, newest):
    """Return the VALID handling session from the trusted comment carrying the `newest` timestamp
    (the most recent heartbeat), or '' - so converging duplicates attribute ownership to the newest
    beat rather than the (possibly older) canonical survivor. A malformed stored value is ignored."""
    for c in matches:
        if parse_last_active(c.get("body", "")) == newest:
            s = _valid_session_or_empty(parse_session(c.get("body", "")))
            if s:
                return s
    return ""


def is_stale(stamp, now, minutes=HEARTBEAT_STALE_MINUTES):
    """True if stamp is missing, unparseable, or older than `minutes` before `now`.

    A naive `now` is treated as UTC so the comparison never raises on mixed awareness.
    """
    if not stamp:
        return True
    try:
        dt = datetime.strptime(stamp, _UTC_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - dt) > timedelta(minutes=minutes)


def branch_slug(text, maxlen=40):
    """Return a lowercase, dash-separated, length-bounded slug for a branch name."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:maxlen].rstrip("-")


def derive_branch(number, text=""):
    """Return a branch name for an issue: 'issue-<n>-<slug>' (or 'issue-<n>' with no text)."""
    slug = branch_slug(text)
    return f"issue-{number}-{slug}" if slug else f"issue-{number}"


# --- board (open issues x handling session x last activity) ----------------------------

# Upper bound on issues fetched for the board (a maintainer overview, not a paginated report);
# cmd_board warns on stderr if the fetch hits this so issues are never omitted silently.
BOARD_LIMIT = 300

BOARD_COLUMNS = [
    ("number", "Issue"),
    ("state", "State"),
    ("session", "Session"),
    ("branch", "Branch"),
    ("last_active", "Last active (UTC)"),
    ("title", "Title"),
]


def board_row(issue, status_body_text, now, minutes=HEARTBEAT_STALE_MINUTES):
    """Build one board row for an issue from its (possibly empty) Work status comment body.

    Pure: pulls the handling session, branch, and last-active stamp from the body, and derives
    a state: 'none' when the issue has no status comment, 'active' when its heartbeat is within
    `minutes` of `now`, else 'stale'.
    """
    body = status_body_text or ""
    stamp = parse_last_active(body)
    if not body:
        state = "none"
    else:
        state = "stale" if is_stale(stamp, now, minutes) else "active"
    return {
        "number": issue.get("number"),
        "title": (issue.get("title") or "").strip(),
        "session": parse_session(body) or "",
        "branch": parse_branch(body) or "",
        "last_active": stamp or "",
        "state": state,
    }


def format_board(rows):
    """Render board rows as an aligned plain-ASCII table. Returns a message when there are none."""
    if not rows:
        return "No open issues to show."
    widths = {key: len(header) for key, header in BOARD_COLUMNS}
    for r in rows:
        for key, _ in BOARD_COLUMNS:
            widths[key] = max(widths[key], len(str(r.get(key, ""))))
    def line(values):
        return "  ".join(str(values[key]).ljust(widths[key]) for key, _ in BOARD_COLUMNS).rstrip()
    header = line({key: header for key, header in BOARD_COLUMNS})
    sep = "  ".join("-" * widths[key] for key, _ in BOARD_COLUMNS).rstrip()
    return "\n".join([header, sep] + [line(r) for r in rows])


# --- project-sync (mirror session + last-active onto the Projects v2 board) -------------
#
# The board is the maintainer's user-owned GitHub Project (v2). Writing custom fields onto it
# needs the `project` gh token scope, an interactive one-time grant the automation cannot self-
# perform (`gh auth refresh -s project`), so this is opt-in and degrades to a clean no-op when the
# scope, the project, or the two fields are missing. See AGENTS.md "GitHub Issues workflow".
PROJECT_OWNER = "urikanonov"          # the Projects v2 owner (a user login); env-overridable
DEFAULT_PROJECT_NUMBER = 1            # "AI Marketplace Tasks" (projects/1); env-overridable
PROJECT_SESSION_FIELD = "Session"     # text field: the handling Copilot session id
PROJECT_LAST_ACTIVE_FIELD = "Last active"  # text field: the last-active UTC heartbeat stamp
# The scope needed to WRITE project fields (read:project alone cannot set a field value).
PROJECT_SCOPE = "project"
# Bound each `gh api graphql` call so a hung gh can never block a heartbeat beat indefinitely.
GRAPHQL_TIMEOUT_SECONDS = 30


def resolve_project_number(explicit=None, env=None):
    """Resolve the Projects v2 number to sync: an explicit --project-number, else the
    TASK_PROJECT_NUMBER env value, else DEFAULT_PROJECT_NUMBER. Returns the int, or None when the
    board is intentionally not configured (a value <= 0) or the env value is unparseable - the
    'no project configured' no-op path. Pure: the env value is passed in for testability."""
    if explicit is not None:
        val = explicit
    elif env:
        try:
            val = int(env)
        except (TypeError, ValueError):
            return None
    else:
        val = DEFAULT_PROJECT_NUMBER
    return val if isinstance(val, int) and val > 0 else None


def select_text_field_id(fields, name):
    """Return the node id of the TEXT project field named `name`, or None if there is no such
    field (or it is not a TEXT field). `fields` is a list of {id,name,dataType} dicts. Pure."""
    for f in fields or []:
        if f.get("name") == name and (f.get("dataType") or "").upper() == "TEXT":
            return f.get("id")
    return None


def select_item_id_for_project(nodes, project_id):
    """Return the project item id from an issue's projectItems nodes ({id, project:{id}}) whose
    project id matches `project_id`, or None. Matching on the globally-unique project id (not its
    per-owner number) avoids picking the wrong board when an issue sits on two projects sharing a
    number. Pure - lets project-sync resolve one issue's board item id directly (the heartbeat fast
    path) without paginating the whole board."""
    for n in nodes or []:
        if not n:
            continue
        if (n.get("project") or {}).get("id") == project_id and n.get("id"):
            return n["id"]
    return None


def build_field_update_variables(project_id, item_id, field_id, text):
    """Build the string variable map for the updateProjectV2ItemFieldValue mutation. Pure."""
    return {"projectId": project_id, "itemId": item_id, "fieldId": field_id, "value": text}


def item_field_text(field_value_nodes, field_name):
    """Return the current text of the board item's field named `field_name` from a fieldValues node
    list (ProjectV2ItemFieldTextValue nodes: {text, field:{name}}), or '' if absent. Pure."""
    for n in field_value_nodes or []:
        if not n:
            continue
        if (n.get("field") or {}).get("name") == field_name:
            return n.get("text") or ""
    return ""


def field_updates(values, current_last_active):
    """Given the desired field values and the board item's CURRENT 'Last active' text, return the
    {field_name: text} to actually write. Empty values are dropped (never clobber a field blank),
    and when the desired 'Last active' is NOT strictly newer than what the board already shows,
    NOTHING is written - so a repeat sync of unchanged data is a no-op and a sweep does not regress
    a heartbeat that was ALREADY on the board when it read. (This is snapshot-bounded: a heartbeat
    that writes AFTER a sweep reads but before it writes can still be briefly overwritten; the next
    beat re-stamps it, so it self-heals within one heartbeat interval.) Pure."""
    new_last = values.get(PROJECT_LAST_ACTIVE_FIELD, "")
    if new_last and current_last_active and not is_newer(new_last, current_last_active):
        return {}
    out = {}
    for name in (PROJECT_SESSION_FIELD, PROJECT_LAST_ACTIVE_FIELD):
        text = values.get(name, "")
        if text:
            out[name] = text
    return out


def field_action(issue_state, status_last_active, now, minutes=HEARTBEAT_STALE_MINUTES):
    """Decide whether a board item's Session/Last active fields should be SET or CLEARED so the
    board reflects only currently-live work. Returns 'set' when the issue is OPEN and its heartbeat
    (`status_last_active`) is fresh (within `minutes` of `now`); 'clear' when the issue is CLOSED,
    or OPEN with a missing/stale heartbeat (no live agent). Pure - `now` is passed in for testing."""
    if (issue_state or "").upper() != "OPEN":
        return "clear"
    return "clear" if is_stale(status_last_active, now, minutes) else "set"


def _utc_now():
    """Return the current UTC time. A thin seam so tests can pin 'now' for the sweep's set/clear
    (field_action) decision without monkeypatching datetime globally."""
    return datetime.now(timezone.utc)


# The host whose active-account scopes gate project-sync (a dual github.com + enterprise login
# lists several hosts; only the github.com token can write this board).
GITHUB_HOST = "github.com"


def parse_active_scopes(text, host=GITHUB_HOST):
    """Parse `gh auth status` output and return the ACTIVE account's token scopes for `host` as a
    set, or None when they cannot be confidently determined (no matching active block on that host,
    or an unparseable/empty scopes line). Pure. Gating on the host AND the active-account block
    prevents attributing another host's or account's scopes; returning None (never an empty set)
    makes a `gh` format shift defer to the reactive _graphql check instead of falsely asserting the
    scope is absent (which would turn a working sync into a permanent silent no-op)."""
    host_ok = False
    active = False
    for line in (text or "").splitlines():
        low = line.lower()
        m_host = re.search(r"logged in to (\S+) account", low)
        if m_host:
            host_ok = (m_host.group(1) == host.lower())
            active = False  # a new account block; not the active one until proven below
        if re.search(r"active account:\s*true", low):
            active = True
        m = re.search(r"Token scopes:\s*(.*)", line)
        if m and active and host_ok:
            found = re.findall(r"'([^']+)'", m.group(1))
            return set(found) if found else None
    return None


def _positive_int(value):
    """argparse type: an int >= 1 (used for --interval so it never hot-loops or goes negative)."""
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be an integer >= 1, got {value}")
    return n


def _non_negative_int(value):
    """argparse type: an int >= 0 (used for --minutes so the stale window is never negative)."""
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError(f"must be an integer >= 0, got {value}")
    return n


def _assert_safe_worktree_name(name):
    """Reject a --name that is not a single safe path component, so a worktree cannot be
    created outside .worktrees/. Rejects path separators, '..', '.', an absolute path, and a
    Windows drive-qualified name like 'C:foo' (which os.path.join would resolve out of tree)."""
    if name and (re.search(r"[\\/]", name) or ".." in name.split("/") or name in (".", "..")
                 or os.path.splitdrive(name)[0] or os.path.isabs(name)):
        raise SystemExit(f"--name must be a single path component (no separators or '..'), got {name!r}")
    return name


def _run(args):
    """Run a command inheriting stdio; return its exit code."""
    return subprocess.run(args).returncode


def _capture(args, timeout=None):
    """Run a command and return its stdout; exit non-zero (surfacing stderr) on failure. An
    optional `timeout` bounds the call (a TimeoutExpired becomes SystemExit) so a project-sync
    caller can guarantee a hung gh cannot block a heartbeat beat; the default (None) preserves the
    existing unbounded behavior for every other caller."""
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        sys.stderr.write("command timed out: " + " ".join(str(a) for a in args[:3]) + "\n")
        raise SystemExit(1)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        raise SystemExit(res.returncode)
    return res.stdout


def _write_temp(text):
    tf = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    tf.write(text)
    tf.close()
    return tf.name


def current_branch():
    """Return the current git branch name, or None outside a work tree or on detached HEAD."""
    res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                         capture_output=True, text=True)
    name = res.stdout.strip() if res.returncode == 0 else ""
    return name if name and name != "HEAD" else None


def _list_comments(number, timeout=None):
    """Return the issue's comments as a list of {'id','body','assoc','author'} dicts (paginated).

    'assoc' is the GitHub author_association and 'author' the login, used to trust only a
    maintainer/collaborator or the invoking account's own status comment. Malformed NDJSON
    lines are skipped rather than aborting the run. `timeout` bounds the gh call (project-sync
    passes it so the heartbeat fast path cannot hang; default None is the existing behavior).
    """
    out = _capture(["gh", "api", "--paginate",
                    f"repos/{REPO}/issues/{number}/comments",
                    "--jq", ".[] | {id: .id, body: .body, assoc: .author_association, author: .user.login}"],
                   timeout=timeout)
    comments = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            comments.append(json.loads(line))
        except ValueError:
            continue
    return comments


_VIEWER_LOGIN = None


def _viewer_login(timeout=None):
    """Return the authenticated gh account login (cached), or '' if it cannot be determined.

    Used so the automation trusts its OWN status comment even when its author_association is
    NONE (e.g. a bot). The TASK_VIEWER_LOGIN env var overrides the lookup (useful under a CI/app
    token where `gh api user` is forbidden). A failure is not cached, so a transient error retries.
    `timeout` bounds the gh lookup (project-sync passes it); default None is the existing behavior.
    """
    global _VIEWER_LOGIN
    override = os.environ.get("TASK_VIEWER_LOGIN")
    if override:
        return override.strip()
    if not _VIEWER_LOGIN:
        try:
            _VIEWER_LOGIN = _capture(["gh", "api", "user", "--jq", ".login"], timeout=timeout).strip()
        except SystemExit:
            return ""
    return _VIEWER_LOGIN


def _post_comment(number, body):
    path = _write_temp(body)
    try:
        _capture(["gh", "issue", "comment", str(number), "--repo", REPO, "--body-file", path])
    finally:
        os.unlink(path)


def _edit_comment(comment_id, body):
    path = _write_temp(body)
    try:
        _capture(["gh", "api", "--method", "PATCH",
                  f"repos/{REPO}/issues/comments/{int(comment_id)}", "-F", f"body=@{path}"])
    finally:
        os.unlink(path)


def _delete_comment(comment_id):
    """Best-effort delete of a comment; True on success. Quiet (captures output) so a race - the
    duplicate already deleted by another worker (404) - does not spam the console."""
    res = subprocess.run(["gh", "api", "--method", "DELETE",
                          f"repos/{REPO}/issues/comments/{int(comment_id)}"],
                         capture_output=True, text=True)
    return res.returncode == 0


def _prune_extras(extra_ids):
    """Best-effort delete of duplicate status comments so the one-pinned-comment invariant
    converges. Failures (already deleted, transient) are ignored - the next pass retries."""
    for cid in extra_ids:
        _delete_comment(cid)


def _upsert_status(number, branch, stamp=None, session=""):
    """Create or (in place) refresh the pinned Work status comment for a branch. Adopts only a
    trusted (maintainer/collaborator or self-authored) marker comment, edits the surviving
    canonical one, and prunes duplicates AFTER the edit so a concurrent first-write converges."""
    stamp = stamp or utc_stamp()
    viewer = _viewer_login()
    matches = status_comments(_list_comments(number), trusted_only=True, viewer=viewer)
    body = status_body(branch, stamp, session)
    if matches:
        survivor = _pick_survivor(matches)
        _edit_comment(survivor["id"], body)
        _prune_extras([c["id"] for c in matches if c["id"] != survivor["id"]])
    else:
        _post_comment(number, body)
    return stamp


def _beat_once(number, branch, session=""):
    """Post one heartbeat: refresh the surviving trusted status comment to the newest known stamp
    (never regressing it) and re-stamp the handling session, then prune duplicates; or create the
    comment from `branch` if none exists. Returns the UTC stamp now in effect. Raises HeartbeatStop
    on a fatal condition (no status comment and no branch, or a malformed survivor we cannot
    rebuild)."""
    stamp = utc_stamp()
    viewer = _viewer_login()
    comments = _list_comments(number)
    matches = status_comments(comments, trusted_only=True, viewer=viewer)
    if not matches:
        # Fail-safe: if the viewer could not be resolved and a marker comment already exists (it
        # may be ours, un-adoptable without the viewer), do NOT post an un-prunable duplicate -
        # skip and retry once the viewer resolves.
        if not viewer and status_comments(comments):
            sys.stderr.write("heartbeat: viewer unresolved and an untrusted marker comment "
                             "exists; skipping to avoid a duplicate (will retry)\n")
            return stamp
        if branch:
            _post_comment(number, status_body(branch, stamp, session))
            return stamp
        raise HeartbeatStop(
            f"no Work status comment on #{number} and no branch detected; run "
            f"`task.py claim {number} --branch <name>` from the worktree first")
    survivor = _pick_survivor(matches)
    extras = [c["id"] for c in matches if c["id"] != survivor["id"]]
    # Converge to the newest stamp across all matches so pruning a newer duplicate never
    # regresses the effective heartbeat; our own beat only advances it.
    newest = _max_stamp(parse_last_active(c["body"]) for c in matches)
    target = stamp if is_newer(stamp, newest) else newest
    # Attribute the handling session to the owner of the NEWEST heartbeat: if our beat advances the
    # timestamp we own it (our session, else keep the survivor's); if a duplicate is newer we inherit
    # that duplicate's session (else ours, else the survivor's). set_session with '' preserves the
    # survivor's existing line, so a session is never wrongly dropped.
    if is_newer(stamp, newest):
        sid = session or _valid_session_or_empty(parse_session(survivor["body"]))
    else:
        sid = _session_at_newest(matches, newest) or session or _valid_session_or_empty(parse_session(survivor["body"]))
    try:
        base = bump_last_active(survivor["body"], target)
    except ValueError:
        # Malformed survivor (marker but no timestamp line): self-heal by rebuilding from a known
        # or recoverable branch, carrying the resolved session, else stop rather than loop. Do NOT
        # prune - the survivor is not yet committed, so deleting valid duplicates would lose state.
        recovered = branch or parse_branch(survivor["body"])
        if not recovered:
            raise HeartbeatStop(
                f"status comment on #{number} is malformed and no branch is known to rebuild it")
        try:
            new_body = status_body(recovered, target, sid)
        except ValueError as exc:
            raise HeartbeatStop(
                f"status comment on #{number} has an invalid branch stamp: {exc}")
    else:
        # Session is validated upstream (_session_arg), so set_session never raises here; keeping
        # it OUT of the try above means a session problem can never be misread as a malformed body.
        new_body = set_session(base, sid)
    if new_body != survivor["body"]:
        _edit_comment(survivor["id"], new_body)
    _prune_extras(extras)  # only after the survivor is successfully committed
    return target


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


def _session_arg(a):
    """Resolve and validate the handling Copilot session id for a command: the explicit
    --session-id, else the COPILOT_AGENT_SESSION_ID environment variable, else '' (the session
    line is then omitted). A non-empty but invalid id (backticks/whitespace/non-ASCII) fails fast
    with a clean SystemExit BEFORE any gh/git mutation, so a bad value never crashes deep in a
    write path or misfires the heartbeat daemon's malformed-comment recovery."""
    session = (getattr(a, "session_id", None) or os.environ.get("COPILOT_AGENT_SESSION_ID", "")).strip()
    if not session:
        return ""
    try:
        return assert_valid_session(session)
    except ValueError as exc:
        raise SystemExit(str(exc))


def cmd_claim(a):
    session = _session_arg(a)  # validate the session first: fail fast BEFORE the claim mutation
    branch = a.branch or current_branch()
    if branch:
        try:
            branch = assert_valid_branch(branch)
        except ValueError as exc:
            raise SystemExit(str(exc))
    code = _run(["gh", "issue", "edit", str(a.number), "--repo", REPO,
                 "--add-assignee", "@me", "--add-label", IN_PROGRESS_LABEL])
    if code == 0:
        if branch:
            stamp = _upsert_status(a.number, branch, session=session)
            print(f"stamped branch `{branch}` and heartbeat {stamp} on #{a.number}")
        else:
            sys.stderr.write(
                "warning: no branch detected; run claim from the worktree or pass --branch "
                "so the issue records where the work lives\n")
    raise SystemExit(code)


def cmd_start(a):
    """Automate the start of work: create a worktree+branch off latest origin/main, claim
    the issue, and stamp the branch. Prints the worktree path and the heartbeat command."""
    _assert_safe_worktree_name(a.name)
    session = _session_arg(a)  # validate the session first: fail fast BEFORE creating the worktree
    try:
        branch = assert_valid_branch(a.branch or derive_branch(a.number, a.slug or ""))
    except ValueError as exc:
        raise SystemExit(str(exc))
    name = a.name or branch
    path = os.path.join(".worktrees", name)
    _capture(["git", "fetch", "origin"])
    if _run(["git", "worktree", "add", "-b", branch, path, "origin/main"]) != 0:
        raise SystemExit(f"could not create worktree at {path} (branch {branch})")
    if _run(["gh", "issue", "edit", str(a.number), "--repo", REPO,
             "--add-assignee", "@me", "--add-label", IN_PROGRESS_LABEL]) != 0:
        raise SystemExit(
            f"created worktree {path} (branch {branch}) but FAILED to claim #{a.number}; "
            f"claim it manually with `python scripts/task.py claim {a.number} --branch {branch}`")
    stamp = _upsert_status(a.number, branch, session=session)
    print(f"worktree ready: {path} (branch {branch}); stamped heartbeat {stamp} on #{a.number}")
    print(f"next: cd {path} ; then start the session-scoped heartbeat daemon:")
    print(f"  python scripts/task.py heartbeat {a.number} --watch")


def cmd_heartbeat(a):
    branch = a.branch or current_branch()
    if branch:
        try:
            branch = assert_valid_branch(branch)
        except ValueError as exc:
            raise SystemExit(str(exc))
    session = _session_arg(a)
    if not a.watch:
        try:
            stamp = _beat_once(a.number, branch, session)
        except HeartbeatStop as exc:
            raise SystemExit(str(exc))
        print(f"heartbeat {stamp} on #{a.number}")
        if getattr(a, "project_sync", False):
            _project_sync_best_effort(a.number)
        return
    print(f"heartbeat daemon: #{a.number} every {a.interval}s (stop it to signal work ended)",
          flush=True)
    try:
        while True:
            try:
                stamp = _beat_once(a.number, branch, session)
                print(f"heartbeat {stamp} on #{a.number}", flush=True)
                if getattr(a, "project_sync", False):
                    _project_sync_best_effort(a.number)
            except HeartbeatStop:
                raise  # fatal setup error - stop the daemon (propagates to the outer handler)
            except SystemExit as exc:
                # _capture raises SystemExit on a nonzero gh/git exit (a transient network or
                # rate-limit blip); keep beating so a blip is not misread as abandoned work.
                sys.stderr.write(f"heartbeat: transient command failure (exit {exc.code}); retrying\n")
            except Exception as exc:  # transient in-process error (e.g. a proxy JSON hiccup)
                sys.stderr.write(f"heartbeat error (will retry): {exc}\n")
            time.sleep(a.interval)
    except HeartbeatStop as exc:
        raise SystemExit(str(exc))
    except KeyboardInterrupt:
        print("heartbeat daemon stopped")


def cmd_board(a):
    """Print a board of open issues with their handling session id, branch, and last activity.

    Defaults to `task`-labeled issues (the ones the heartbeat tracks); --all-labels widens it to
    every open issue. --json emits machine-readable rows."""
    now = datetime.now(timezone.utc)
    viewer = _viewer_login()
    args = ["gh", "issue", "list", "--repo", REPO, "--state", "open",
            "--limit", str(BOARD_LIMIT), "--json", "number,title"]
    if not a.all_labels:
        args += ["--label", TASK_LABEL]
    issues = json.loads(_capture(args))
    if len(issues) >= BOARD_LIMIT:
        # Never omit issues SILENTLY: say so on stderr if the fetch hit the cap.
        sys.stderr.write(f"board: showing the first {BOARD_LIMIT} open issues; more may exist "
                         "(the board is a maintainer overview, not a paginated report)\n")
    issues.sort(key=lambda it: it.get("number", 0))
    rows = []
    for it in issues:
        # Use the same canonical-survivor selection the heartbeat uses, so duplicate marker
        # comments never make the board show a stale/non-canonical row.
        matches = status_comments(_list_comments(it["number"]), trusted_only=True, viewer=viewer)
        body = _pick_survivor(matches)["body"] if matches else ""
        rows.append(board_row(it, body, now, a.minutes))
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        print(format_board(rows))


# GraphQL for the Projects v2 board. gh sends string variables with -f and ints with -F; a nonzero
# gh exit is classified in _graphql (a missing-scope error becomes a clean ProjectSyncSkip no-op).
_PROJECT_FIELDS_QUERY = (
    "query($owner:String!,$number:Int!){"
    " user(login:$owner){ projectV2(number:$number){ id title"
    " fields(first:50){ nodes{ ... on ProjectV2FieldCommon { id name dataType } } } } } }")
_PROJECT_ITEMS_QUERY = (
    "query($owner:String!,$number:Int!,$cursor:String){"
    " user(login:$owner){ projectV2(number:$number){"
    " items(first:100, after:$cursor){ pageInfo{ hasNextPage endCursor }"
    " nodes{ id content{ ... on Issue { number state repository { nameWithOwner } } }"
    " fieldValues(first:50){ nodes{ ... on ProjectV2ItemFieldTextValue { text"
    " field{ ... on ProjectV2FieldCommon { name } } } } } } } } } }")
# Resolve ONE issue's board item id directly (the heartbeat fast path), avoiding a full-board scan.
_ISSUE_ITEMS_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!){"
    " repository(owner:$owner,name:$name){ issue(number:$number){ state"
    " projectItems(first:100){ nodes{ id project{ id }"
    " fieldValues(first:50){ nodes{ ... on ProjectV2ItemFieldTextValue { text"
    " field{ ... on ProjectV2FieldCommon { name } } } } } } } } } }")
_FIELD_UPDATE_MUTATION = (
    "mutation($projectId:ID!,$itemId:ID!,$fieldId:ID!,$value:String!){"
    " updateProjectV2ItemFieldValue(input:{projectId:$projectId,itemId:$itemId,"
    "fieldId:$fieldId,value:{text:$value}}){ projectV2Item{ id } } }")
_FIELD_CLEAR_MUTATION = (
    "mutation($projectId:ID!,$itemId:ID!,$fieldId:ID!){"
    " clearProjectV2ItemFieldValue(input:{projectId:$projectId,itemId:$itemId,"
    "fieldId:$fieldId}){ projectV2Item{ id } } }")


def _graphql(query, str_vars=None, int_vars=None):
    """Run a GraphQL query/mutation via `gh api graphql` and return the parsed response. String
    variables go with -f and integers with -F. A nonzero exit whose message names a required scope
    is mapped to ProjectSyncSkip (the graceful no-op, with `gh auth refresh` guidance); any other
    failure (including a timeout - so a hung `gh` can never block a heartbeat beat indefinitely)
    surfaces stderr and raises SystemExit, which the best-effort heartbeat wrapper swallows."""
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in (str_vars or {}).items():
        args += ["-f", f"{k}={v}"]
    for k, v in (int_vars or {}).items():
        args += ["-F", f"{k}={int(v)}"]
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=GRAPHQL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"gh api graphql timed out after {GRAPHQL_TIMEOUT_SECONDS}s\n")
        raise SystemExit(1)
    if res.returncode != 0:
        msg = (res.stderr or res.stdout or "gh api graphql failed").strip()
        low = msg.lower()
        if "required scopes" in low or "read:project" in low:
            raise ProjectSyncSkip(
                f"the gh token lacks the '{PROJECT_SCOPE}' scope; grant it once with "
                f"`gh auth refresh -s {PROJECT_SCOPE}` (a one-time interactive step), then re-run")
        sys.stderr.write(msg + "\n")
        raise SystemExit(1)
    return json.loads(res.stdout)


def _token_scopes():
    """Return the active github.com account's token scopes (or None). Bounded so a hung `gh auth
    status` cannot block a heartbeat beat; a timeout defers to the reactive _graphql check. The
    parsing is the pure parse_active_scopes helper."""
    try:
        res = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True,
                             timeout=GRAPHQL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return None  # a hung `gh auth status` must not block a heartbeat beat; defer to _graphql
    return parse_active_scopes((res.stdout or "") + (res.stderr or ""))


def _resolve_project(owner, number):
    """Return (project_id, {field_name: field_id}) for the two synced text fields. Raises
    ProjectSyncSkip when the project is not found or either field is missing (with the one-time
    field-creation guidance) - both expected, non-fatal 'not set up yet' conditions."""
    data = _graphql(_PROJECT_FIELDS_QUERY, str_vars={"owner": owner}, int_vars={"number": number})
    project = ((data.get("data") or {}).get("user") or {}).get("projectV2")
    if not project:
        raise ProjectSyncSkip(
            f"Projects v2 #{number} was not found for owner '{owner}' (check TASK_PROJECT_OWNER/"
            "TASK_PROJECT_NUMBER); nothing to sync")
    fields = (project.get("fields") or {}).get("nodes") or []
    ids = {name: select_text_field_id(fields, name)
           for name in (PROJECT_SESSION_FIELD, PROJECT_LAST_ACTIVE_FIELD)}
    missing = [name for name, fid in ids.items() if not fid]
    if missing:
        # Build the createProjectV2Field example without f-string brace-escaping gymnastics (a
        # missing `f` prefix on a brace-heavy literal is an easy future trap).
        example = ("gh api graphql -f query='mutation{ createProjectV2Field(input:{projectId:"
                   '"%s", dataType:TEXT, name:"%s" }){ projectV2Field{ ... on ProjectV2Field '
                   "{ id name } } } }'" % (project["id"], missing[0]))
        raise ProjectSyncSkip(
            f"the board is missing the text field(s) {missing}; create them once (board UI, or via "
            f"the Projects v2 API on project id {project['id']}), then re-run. Example: {example}")
    return project["id"], ids


def _fetch_project_items(owner, number):
    """Return all project item nodes ({id, content:{number, repository}}), following pagination."""
    nodes, cursor = [], None
    while True:
        str_vars = {"owner": owner}
        if cursor:
            str_vars["cursor"] = cursor
        data = _graphql(_PROJECT_ITEMS_QUERY, str_vars=str_vars, int_vars={"number": number})
        items = (((data.get("data") or {}).get("user") or {}).get("projectV2") or {}).get("items") or {}
        nodes.extend(items.get("nodes") or [])
        page = items.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return nodes
        cursor = page.get("endCursor")
        if not cursor:
            return nodes


def _issue_project_item(issue_number):
    """Return (issue_state, projectItems nodes) for ONE issue - the heartbeat fast path, avoiding a
    full-board scan. `issue_state` is 'OPEN'/'CLOSED' (or '' if the issue is missing). Each _graphql
    call is timeout-bounded internally."""
    owner, name = REPO.split("/", 1)
    data = _graphql(_ISSUE_ITEMS_QUERY, str_vars={"owner": owner, "name": name},
                    int_vars={"number": issue_number})
    issue = ((data.get("data") or {}).get("repository") or {}).get("issue") or {}
    return issue.get("state") or "", (issue.get("projectItems") or {}).get("nodes") or []


def _apply_field_values(project_id, item_id, field_ids, values, dry_run, number,
                        current_last_active=""):
    """Set the two text fields on one item, writing only field_updates(values, current_last_active):
    empty values are skipped (never clobber blank) and a desired 'Last active' that is not strictly
    newer than what the board already shows writes NOTHING, so a slow/concurrent sweep can never
    regress a newer heartbeat and an unchanged repeat is a no-op. Returns True if anything was set."""
    updates = field_updates(values, current_last_active)
    if not updates:
        return False
    for name, text in updates.items():
        if dry_run:
            print(f"project-sync: #{number} would set {name!r} = {text}")
            continue
        _graphql(_FIELD_UPDATE_MUTATION,
                 str_vars=build_field_update_variables(project_id, item_id, field_ids[name], text))
    return True


def _clear_field_values(project_id, item_id, field_ids, cur_session, cur_last, dry_run, number):
    """Clear the Session/Last active fields that currently hold a value on one item (a closed or
    stale issue). Only fields that are actually set are cleared, so an already-blank item is a
    no-op. Returns True if anything was cleared."""
    to_clear = []
    if cur_session:
        to_clear.append(PROJECT_SESSION_FIELD)
    if cur_last:
        to_clear.append(PROJECT_LAST_ACTIVE_FIELD)
    if not to_clear:
        return False
    for name in to_clear:
        if dry_run:
            print(f"project-sync: #{number} would clear {name!r}")
            continue
        _graphql(_FIELD_CLEAR_MUTATION,
                 str_vars={"projectId": project_id, "itemId": item_id, "fieldId": field_ids[name]})
    return True


def _sync_one_item(project_id, field_ids, item_id, number, state, node, viewer, now, dry_run):
    """Set or clear ONE board item's Session/Last active per field_action, so the board reflects
    only currently-live work: an OPEN issue with a fresh heartbeat is SET from its Work status
    comment (monotonically); a CLOSED or OPEN-but-stale issue is CLEARED. Returns 'set'/'clear'/''
    (empty = nothing to do)."""
    fv = (node.get("fieldValues") or {}).get("nodes")
    cur_session = item_field_text(fv, PROJECT_SESSION_FIELD)
    cur_last = item_field_text(fv, PROJECT_LAST_ACTIVE_FIELD)
    if (state or "").upper() == "OPEN":
        # Read the live heartbeat from the NEWEST trusted "Work status" comment (duplicates can
        # exist before convergence, and the oldest survivor may carry a stale stamp - using the
        # newest, as the heartbeat itself does, avoids clearing genuinely-live work).
        matches = status_comments(_list_comments(number, timeout=GRAPHQL_TIMEOUT_SECONDS),
                                  trusted_only=True, viewer=viewer)
        newest = _max_stamp(parse_last_active(c.get("body", "")) for c in matches)
        values = {PROJECT_LAST_ACTIVE_FIELD: newest or "",
                  PROJECT_SESSION_FIELD: _session_at_newest(matches, newest) if newest else ""}
        action = field_action("OPEN", values[PROJECT_LAST_ACTIVE_FIELD], now)
    else:
        values, action = {}, "clear"
    if action == "set":
        return "set" if _apply_field_values(project_id, item_id, field_ids, values, dry_run,
                                            number, cur_last) else ""
    if _clear_field_values(project_id, item_id, field_ids, cur_session, cur_last, dry_run, number):
        return "clear"
    return ""


def _run_project_sync(a):
    """Do the project-sync work; raises ProjectSyncSkip for expected 'not configured / not set up'
    conditions (the caller turns those into a clean no-op). Board-driven: for each repo issue item
    on the board it SETS live work (open + fresh heartbeat) and CLEARS closed/stale work, so the
    Session/Last active columns show only currently-live sessions."""
    number = resolve_project_number(a.project_number, os.environ.get("TASK_PROJECT_NUMBER"))
    if number is None:
        raise ProjectSyncSkip(
            "no project configured (a value <= 0 or an unparseable TASK_PROJECT_NUMBER); "
            "set TASK_PROJECT_NUMBER or pass --project-number to enable the sync")
    owner = os.environ.get("TASK_PROJECT_OWNER") or PROJECT_OWNER
    scopes = _token_scopes()
    if scopes is not None and PROJECT_SCOPE not in scopes:
        raise ProjectSyncSkip(
            f"the gh token lacks the '{PROJECT_SCOPE}' scope; grant it once with "
            f"`gh auth refresh -s {PROJECT_SCOPE}` (a one-time interactive step), then re-run")
    project_id, field_ids = _resolve_project(owner, number)
    now = _utc_now()
    if a.issue is not None:
        # Fast path: resolve just this issue's board item, no full-board scan (heartbeat-safe).
        state, nodes = _issue_project_item(a.issue)
        item_id = select_item_id_for_project(nodes, project_id)
        if not item_id:
            sys.stderr.write(
                f"project-sync: #{a.issue} is not on the board; skipping (a `{TASK_LABEL}` issue "
                "is auto-added when created)\n")
            print(f"project-sync: {'would update' if a.dry_run else 'updated'} 0, "
                  f"{'would clear' if a.dry_run else 'cleared'} 0 issue(s) on project #{number}")
            return
        node = next((n for n in nodes if n.get("id") == item_id), {})
        targets = [(a.issue, state, item_id, node)]
    else:
        nodes = _fetch_project_items(owner, number)
        targets = []
        for n in nodes:
            if not n:
                continue
            c = n.get("content") or {}
            num = c.get("number")
            # Restrict to THIS repo's issues - a user-owned board can hold other repos' items.
            if (not isinstance(num, int) or not n.get("id")
                    or (c.get("repository") or {}).get("nameWithOwner") != REPO):
                continue
            targets.append((num, c.get("state"), n["id"], n))
        targets.sort(key=lambda t: t[0])
    viewer = _viewer_login(timeout=GRAPHQL_TIMEOUT_SECONDS)
    set_count = clear_count = 0
    for num, state, item_id, node in targets:
        outcome = _sync_one_item(project_id, field_ids, item_id, num, state, node, viewer, now,
                                 a.dry_run)
        if outcome == "set":
            set_count += 1
        elif outcome == "clear":
            clear_count += 1
    verb = "would update" if a.dry_run else "updated"
    verb2 = "would clear" if a.dry_run else "cleared"
    print(f"project-sync: {verb} {set_count}, {verb2} {clear_count} issue(s) on project #{number}")


def cmd_project_sync(a):
    """Mirror the handling session id and last-active stamp onto the Projects v2 board's Session
    and Last active text fields. A missing `project` scope, unconfigured project, or missing field
    is a clean no-op (exit 0) with actionable guidance, so it never breaks a run."""
    try:
        _run_project_sync(a)
    except ProjectSyncSkip as skip:
        sys.stderr.write(f"project-sync: {skip}\n")


def _project_sync_best_effort(number):
    """Best-effort single-issue project-sync for the heartbeat: never raises, so a project/scope/
    network problem can never break a beat. Returns True only on a clean run."""
    class _A:
        issue = number
        project_number = None
        dry_run = False
    try:
        cmd_project_sync(_A())
        return True
    except (Exception, SystemExit) as exc:  # SystemExit from a non-scope gh failure must not kill a beat
        sys.stderr.write(f"project-sync (heartbeat, ignored): {exc}\n")
        return False


def cmd_stale(a):
    now = datetime.now(timezone.utc)
    viewer = _viewer_login()
    issues = json.loads(_capture([
        "gh", "issue", "list", "--repo", REPO, "--state", "open",
        "--label", TASK_LABEL, "--label", IN_PROGRESS_LABEL,
        "--limit", "200", "--json", "number,title"]))
    stale = []
    for it in issues:
        st = find_status_comment(_list_comments(it["number"]), trusted_only=True, viewer=viewer)
        stamp = parse_last_active(st["body"]) if st else None
        branch = (parse_branch(st["body"]) if st else None) or "unknown"
        if is_stale(stamp, now, a.minutes):
            stale.append((it["number"], stamp or "none", branch, it["title"]))
    if not stale:
        print(f"No stale in-progress issues (all beat within {a.minutes} min).")
        return
    print(f"Stale in-progress issues (no heartbeat in {a.minutes} min) - likely free to take over:")
    for number, stamp, branch, title in stale:
        print(f"  #{number}  last-active={stamp}  branch={branch}  {title}")


def cmd_plan(a):
    assert_ascii(a.text, "plan")
    raise SystemExit(_run(["gh", "issue", "comment", str(a.number), "--repo", REPO,
                           "--body", a.text]))


def cmd_check_ac(a):
    body = _capture(["gh", "issue", "view", str(a.number), "--repo", REPO,
                     "--json", "body", "--jq", ".body"])
    path = _write_temp(apply_ac_check(body, a.index, a.all))
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

    c = sub.add_parser("claim", help="assign @me, mark In Progress, and stamp the branch")
    c.add_argument("number", type=int)
    c.add_argument("--branch", help="worktree branch to stamp (default: current git branch)")
    c.add_argument("--session-id", help="handling Copilot session id (default: COPILOT_AGENT_SESSION_ID)")
    c.set_defaults(func=cmd_claim)

    st = sub.add_parser("start", help="worktree + branch + claim + stamp, in one step")
    st.add_argument("number", type=int)
    st.add_argument("--slug", help="short text used to derive the branch name")
    st.add_argument("--branch", help="explicit branch name (overrides --slug)")
    st.add_argument("--name", help="worktree folder under .worktrees/ (default: branch name)")
    st.add_argument("--session-id", help="handling Copilot session id (default: COPILOT_AGENT_SESSION_ID)")
    st.set_defaults(func=cmd_start)

    hb = sub.add_parser("heartbeat", help="refresh the Work status timestamp (--watch to daemon)")
    hb.add_argument("number", type=int)
    hb.add_argument("--branch", help="branch to stamp if no status comment exists yet")
    hb.add_argument("--session-id", help="handling Copilot session id (default: COPILOT_AGENT_SESSION_ID)")
    hb.add_argument("--watch", action="store_true",
                    help="loop, beating every --interval seconds until stopped")
    hb.add_argument("--interval", type=_positive_int, default=HEARTBEAT_INTERVAL_SECONDS,
                    help=f"seconds between beats in --watch mode (default {HEARTBEAT_INTERVAL_SECONDS})")
    hb.add_argument("--project-sync", action="store_true",
                    help="after each beat, best-effort sync this issue's Session/Last active fields "
                         "onto the Projects v2 board (no-op without the `project` scope)")
    hb.set_defaults(func=cmd_heartbeat)

    sl = sub.add_parser("stale", help="list in-progress issues with a missing or old heartbeat")
    sl.add_argument("--minutes", type=_non_negative_int, default=HEARTBEAT_STALE_MINUTES,
                    help=f"staleness threshold in minutes (default {HEARTBEAT_STALE_MINUTES})")
    sl.set_defaults(func=cmd_stale)

    bd = sub.add_parser("board", help="show open issues with handling session id and last activity")
    bd.add_argument("--all-labels", action="store_true",
                    help="include every open issue (default: task-labeled issues only)")
    bd.add_argument("--json", action="store_true", help="emit machine-readable JSON rows")
    bd.add_argument("--minutes", type=_non_negative_int, default=HEARTBEAT_STALE_MINUTES,
                    help=f"staleness threshold in minutes for the active/stale state (default {HEARTBEAT_STALE_MINUTES})")
    bd.set_defaults(func=cmd_board)

    ps = sub.add_parser("project-sync",
                        help="sync Session and Last active fields onto the Projects v2 board")
    ps.add_argument("--issue", type=int,
                    help="sync only this issue (default: sweep every repo issue on the board)")
    ps.add_argument("--project-number", type=int,
                    help="Projects v2 number (default: env TASK_PROJECT_NUMBER or "
                         f"{DEFAULT_PROJECT_NUMBER})")
    ps.add_argument("--dry-run", action="store_true",
                    help="print the set/clear the sweep would do without writing them")
    ps.set_defaults(func=cmd_project_sync)

    pl = sub.add_parser("plan", help="post an implementation-plan comment")
    pl.add_argument("number", type=int)
    pl.add_argument("text")
    pl.set_defaults(func=cmd_plan)

    ca = sub.add_parser("check-ac", help="tick the k-th acceptance criterion (or --all)")
    ca.add_argument("number", type=int)
    ca.add_argument("index", type=int, nargs="?", default=None,
                    help="1-based acceptance-criterion index (omit when using --all)")
    ca.add_argument("--all", action="store_true", help="tick every acceptance criterion")
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
