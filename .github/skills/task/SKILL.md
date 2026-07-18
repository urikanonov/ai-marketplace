---
name: task
description: >-
  Manage this repository's GitHub Issues work items with the issue-first workflow. Use when creating,
  searching, claiming, planning, updating, or finishing a maintainer task in urikanonov/ai-marketplace,
  starting work (worktree + branch stamp), keeping a heartbeat on an in-progress issue, or finding
  abandoned/stale work to take over. Wraps `gh` with the repo conventions (the `task` label,
  plain-ASCII bodies, the Task issue-form sections, and the In Progress status). Trigger on: task,
  issue, work item, backlog, track work, file an issue, claim, start work, worktree, branch stamp,
  heartbeat, stale issue, abandoned work, acceptance criteria, plan, gh issue.
---

# Task (issue-first work items)

This repo tracks work as GitHub Issues (see AGENTS.md, "GitHub Issues workflow"). An issue exists the
moment you create it, decoupled from git, so work is never lost in a discarded worktree or abandoned PR.
Use the `scripts/task.py` wrapper so the repo conventions (the `task` label, plain ASCII, the Task
issue-form sections, and the `status: in progress` label) are applied for you instead of retyping `gh`
flags. It also stamps the worktree branch on the issue and runs a heartbeat, so the maintainer can tell
which in-progress issues are actively being worked on and which are abandoned (and resumable).

## When to use

Use this skill before writing any code (issue-first is a non-negotiable), and whenever a follow-up
surfaces mid-session, so nothing lives only in the chat transcript. Use `start`/`claim` to stamp the
branch, `heartbeat --watch` to keep the issue marked live for your whole session, and `stale` to find
in-progress issues nobody is working on.

## Commands

Run from the repo root with a `gh` that is authenticated to the `urikanonov` account.

```bash
# 1. Search first (consolidate rather than duplicate); --all includes closed history.
python scripts/task.py search "comment panel width" --all

# 2. Create a task issue (labeled `task`); acceptance items become checkboxes.
python scripts/task.py new "UI: enforce legible comment panel width" \
  -d "Keep the side panel from clipping action labels." \
  --ac "Labels stay legible at the minimum width" \
  --ac "Search placeholder is fully visible" \
  --plan "1. Reproduce  2. Fix CSS min-width  3. Add a test" \
  --label ui

# 3. Start work in one step: worktree + branch off latest origin/main, claim, and stamp the branch.
python scripts/task.py start 188 --slug "comment panel width"
#   (or, if you made the worktree yourself, claim from inside it - it auto-detects the branch)
python scripts/task.py claim 188

# 4. Keep a heartbeat running for the whole session (refreshes one pinned comment every 5 min in place).
#    Launch it as a session-scoped background process (NOT detached) so it stops when your session ends.
python scripts/task.py heartbeat 188 --watch

#    Find issues nobody is working on (missing or stale heartbeat); each row names the branch to resume.
python scripts/task.py stale --minutes 15

# 5. Share the implementation plan for approval before coding.
python scripts/task.py plan 188 "1. Rebase onto main  2. Fix  3. Test"

# 6. Tick each acceptance criterion as you finish it (1-based).
python scripts/task.py check-ac 188 1

# 7. Record the final summary; open the PR with `Closes #188` to close the issue.
python scripts/task.py finish 188 "Enforced a CSS min-width and covered it with a test."
```

## Conventions baked in

- Every new issue gets the `task` label; pass `--label <area>` for area labels (deck, site, ui, runtime,
  tooling, audit, documentation).
- Bodies must be plain ASCII: the wrapper rejects any non-ASCII character (em/en dashes, ellipsis,
  smart quotes, non-breaking spaces, emoji) so the house style holds. Use the wrapper (not raw
  `gh issue create`) for any operation that writes an issue body, so this guard always runs.
- `claim` adds the `status: in progress` label AND stamps the worktree branch (auto-detected, or
  `--branch <name>`) into a single pinned "Work status" comment; `start` also creates the worktree first.
  The `issue-status-sync` workflow adds the label when a PR that says `Closes #N` opens, and merging that
  PR closes the issue.
- `heartbeat <n>` refreshes the "Work status" comment's UTC timestamp IN PLACE (no new comment). With
  `--watch` it becomes a daemon beating every `--interval` seconds (default 300); run it session-scoped
  so a stopped heartbeat certainly means work stopped. `stale` lists in-progress issues whose heartbeat
  is missing or older than the threshold, so abandoned work is easy to find and resume from its branch.

The pure helpers are covered by `scripts/test_task.py`, run by the required `validate` CI check.
