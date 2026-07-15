---
name: task
description: >-
  Manage this repository's GitHub Issues work items with the issue-first workflow. Use when creating,
  searching, claiming, planning, updating, or finishing a maintainer task in urikanonov/ai-marketplace,
  or whenever you would otherwise reach for raw `gh issue` commands here. Wraps `gh` with the repo
  conventions (the `task` label, plain-ASCII bodies, the Task issue-form sections, and the In Progress
  status). Trigger on: task, issue, work item, backlog, track work, file an issue, claim, acceptance
  criteria, plan, gh issue.
---

# Task (issue-first work items)

This repo tracks work as GitHub Issues (see AGENTS.md, "GitHub Issues workflow"). An issue exists the
moment you create it, decoupled from git, so work is never lost in a discarded worktree or abandoned PR.
Use the `scripts/task.py` wrapper so the repo conventions (the `task` label, plain ASCII, the Task
issue-form sections, and the `status: in progress` label) are applied for you instead of retyping `gh`
flags.

## When to use

Use this skill before writing any code (issue-first is a non-negotiable), and whenever a follow-up
surfaces mid-session, so nothing lives only in the chat transcript.

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

# 3. Claim it: assign yourself and mark In Progress.
python scripts/task.py claim 188

# 4. Share the implementation plan for approval before coding.
python scripts/task.py plan 188 "1. Rebase onto main  2. Fix  3. Test"

# 5. Tick each acceptance criterion as you finish it (1-based).
python scripts/task.py check-ac 188 1

# 6. Record the final summary; open the PR with `Closes #188` to close the issue.
python scripts/task.py finish 188 "Enforced a CSS min-width and covered it with a test."
```

## Conventions baked in

- Every new issue gets the `task` label; pass `--label <area>` for area labels (deck, site, ui, runtime,
  tooling, audit, documentation).
- Bodies must be plain ASCII: the wrapper rejects em/en dashes and ellipsis so the house style holds.
- `claim` adds the `status: in progress` label; the `issue-status-sync` workflow also adds it when a PR
  that says `Closes #N` opens, and merging that PR closes the issue.

The pure helpers are covered by `scripts/test_task.py`, run by the required `validate` CI check.
