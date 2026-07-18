#!/usr/bin/env python3
"""task.py - thin wrapper over the `gh` CLI for the repo's issue-first workflow.

Wraps the maintainer task lifecycle (search, new, claim, plan, check-ac, finish)
with the repo conventions baked in: the `task` label, plain-ASCII bodies, and the
Task issue-form section shape. Agents and contributors should prefer this wrapper
over raw `gh` so those conventions are not re-typed each time.

The pure helpers (build_body, create_args, tick_checkbox, assert_ascii, status_body,
bump_last_active, find_status_comment, status_comments, extra_status_comment_ids,
parse_last_active, parse_branch, is_stale, is_newer, utc_stamp, assert_valid_branch,
branch_slug, derive_branch) are unit tested in scripts/test_task.py; the thin `_run`
layer shells out to `gh` and `git`.

Usage:
  python scripts/task.py search "panel width" [--all]
  python scripts/task.py new "UI: title" -d "Why" --ac "Outcome A" --ac "Outcome B" [--plan "1. ..."]
  python scripts/task.py start 188 [--slug "short desc"]   # worktree + branch + claim + stamp
  python scripts/task.py claim 188 [--branch issue-188-foo]
  python scripts/task.py heartbeat 188 [--watch] [--interval 300]
  python scripts/task.py stale [--minutes 15]
  python scripts/task.py plan 188 "1. Rebase  2. Fix  3. Test"
  python scripts/task.py check-ac 188 1
  python scripts/task.py finish 188 "Short PR-style summary"
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


def status_body(branch, stamp):
    """Build the pinned 'Work status' comment body for a branch and UTC timestamp.

    Carries STATUS_MARKER (so the comment can be found and edited in place), the
    worktree branch (so dropped work can be resumed from it), and the last-active
    timestamp (the heartbeat). Plain ASCII, per the house style.
    """
    branch = assert_valid_branch(branch)
    return "\n".join([
        STATUS_MARKER,
        "### Work status (automated heartbeat)",
        "",
        f"- Branch: `{branch}` (local worktree; if this work is dropped, resume from this branch)",
        f"- Last active (UTC): {stamp}",
        "",
        f"This comment is refreshed automatically at least every {HEARTBEAT_INTERVAL_SECONDS // 60} "
        "minutes while an agent is actively working this issue. If the timestamp above is more than "
        f"{HEARTBEAT_STALE_MINUTES} minutes old, no one is actively working it - it is safe to take "
        "over from the branch above.",
    ])


def bump_last_active(body, stamp):
    """Return body with only the 'Last active (UTC)' line updated to stamp.

    Preserves the branch line so a heartbeat never loses the stamped branch. Raises
    ValueError if the body has no last-active line (so a malformed comment fails loudly).
    """
    new_body, n = _LAST_ACTIVE_RE.subn(f"- Last active (UTC): {stamp}", body)
    if n == 0:
        raise ValueError("no 'Last active (UTC)' line found in the status comment body")
    return new_body


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


def current_branch():
    """Return the current git branch name, or None outside a work tree or on detached HEAD."""
    res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                         capture_output=True, text=True)
    name = res.stdout.strip() if res.returncode == 0 else ""
    return name if name and name != "HEAD" else None


def _list_comments(number):
    """Return the issue's comments as a list of {'id','body','assoc','author'} dicts (paginated).

    'assoc' is the GitHub author_association and 'author' the login, used to trust only a
    maintainer/collaborator or the invoking account's own status comment. Malformed NDJSON
    lines are skipped rather than aborting the run.
    """
    out = _capture(["gh", "api", "--paginate",
                    f"repos/{REPO}/issues/{number}/comments",
                    "--jq", ".[] | {id: .id, body: .body, assoc: .author_association, author: .user.login}"])
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


def _viewer_login():
    """Return the authenticated gh account login (cached), or '' if it cannot be determined.

    Used so the automation trusts its OWN status comment even when its author_association is
    NONE (e.g. a bot). The TASK_VIEWER_LOGIN env var overrides the lookup (useful under a CI/app
    token where `gh api user` is forbidden). A failure is not cached, so a transient error retries.
    """
    global _VIEWER_LOGIN
    override = os.environ.get("TASK_VIEWER_LOGIN")
    if override:
        return override.strip()
    if not _VIEWER_LOGIN:
        try:
            _VIEWER_LOGIN = _capture(["gh", "api", "user", "--jq", ".login"]).strip()
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


def _upsert_status(number, branch, stamp=None):
    """Create or (in place) refresh the pinned Work status comment for a branch. Adopts only a
    trusted (maintainer/collaborator or self-authored) marker comment, edits the surviving
    canonical one, and prunes duplicates AFTER the edit so a concurrent first-write converges."""
    stamp = stamp or utc_stamp()
    viewer = _viewer_login()
    matches = status_comments(_list_comments(number), trusted_only=True, viewer=viewer)
    body = status_body(branch, stamp)
    if matches:
        survivor = _pick_survivor(matches)
        _edit_comment(survivor["id"], body)
        _prune_extras([c["id"] for c in matches if c["id"] != survivor["id"]])
    else:
        _post_comment(number, body)
    return stamp


def _beat_once(number, branch):
    """Post one heartbeat: refresh the surviving trusted status comment to the newest known stamp
    (never regressing it), then prune duplicates; or create the comment from `branch` if none
    exists. Returns the UTC stamp now in effect. Raises HeartbeatStop on a fatal condition (no
    status comment and no branch, or a malformed survivor we cannot rebuild)."""
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
            _post_comment(number, status_body(branch, stamp))
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
    try:
        new_body = bump_last_active(survivor["body"], target)
    except ValueError:
        # Malformed survivor (marker but no timestamp line): self-heal by rebuilding from a known
        # or recoverable branch, else stop rather than loop. Do NOT prune - the survivor is not
        # yet committed, so deleting valid duplicates here would lose good state.
        recovered = branch or parse_branch(survivor["body"])
        if not recovered:
            raise HeartbeatStop(
                f"status comment on #{number} is malformed and no branch is known to rebuild it")
        try:
            new_body = status_body(recovered, target)
        except ValueError as exc:
            raise HeartbeatStop(
                f"status comment on #{number} has an invalid branch stamp: {exc}")
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


def cmd_claim(a):
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
            stamp = _upsert_status(a.number, branch)
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
    stamp = _upsert_status(a.number, branch)
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
    if not a.watch:
        try:
            stamp = _beat_once(a.number, branch)
        except HeartbeatStop as exc:
            raise SystemExit(str(exc))
        print(f"heartbeat {stamp} on #{a.number}")
        return
    print(f"heartbeat daemon: #{a.number} every {a.interval}s (stop it to signal work ended)",
          flush=True)
    try:
        while True:
            try:
                stamp = _beat_once(a.number, branch)
                print(f"heartbeat {stamp} on #{a.number}", flush=True)
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

    c = sub.add_parser("claim", help="assign @me, mark In Progress, and stamp the branch")
    c.add_argument("number", type=int)
    c.add_argument("--branch", help="worktree branch to stamp (default: current git branch)")
    c.set_defaults(func=cmd_claim)

    st = sub.add_parser("start", help="worktree + branch + claim + stamp, in one step")
    st.add_argument("number", type=int)
    st.add_argument("--slug", help="short text used to derive the branch name")
    st.add_argument("--branch", help="explicit branch name (overrides --slug)")
    st.add_argument("--name", help="worktree folder under .worktrees/ (default: branch name)")
    st.set_defaults(func=cmd_start)

    hb = sub.add_parser("heartbeat", help="refresh the Work status timestamp (--watch to daemon)")
    hb.add_argument("number", type=int)
    hb.add_argument("--branch", help="branch to stamp if no status comment exists yet")
    hb.add_argument("--watch", action="store_true",
                    help="loop, beating every --interval seconds until stopped")
    hb.add_argument("--interval", type=_positive_int, default=HEARTBEAT_INTERVAL_SECONDS,
                    help=f"seconds between beats in --watch mode (default {HEARTBEAT_INTERVAL_SECONDS})")
    hb.set_defaults(func=cmd_heartbeat)

    sl = sub.add_parser("stale", help="list in-progress issues with a missing or old heartbeat")
    sl.add_argument("--minutes", type=_non_negative_int, default=HEARTBEAT_STALE_MINUTES,
                    help=f"staleness threshold in minutes (default {HEARTBEAT_STALE_MINUTES})")
    sl.set_defaults(func=cmd_stale)

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
