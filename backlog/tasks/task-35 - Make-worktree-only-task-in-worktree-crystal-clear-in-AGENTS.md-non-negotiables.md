---
id: TASK-35
title: >-
  Make worktree-only + task-in-worktree crystal clear in AGENTS.md
  non-negotiables
status: Done
assignee:
  - '@me'
created_date: '2026-07-15 07:24'
updated_date: '2026-07-15 07:26'
labels: []
dependencies: []
ordinal: 26000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The AGENTS.md non-negotiables list backlog-first as rule 1 with 'before the worktree, create the task', which contradicts the worktree-first rule and causes task files to be created in the primary tree. Reorder and harden so the worktree comes first and ALL work, including backlog task creation, happens inside the worktree; the primary checkout is off-limits.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 AGENTS.md non-negotiables make the worktree the first rule and state the primary tree is off-limits for all files including backlog tasks
- [x] #2 The backlog-first rule explicitly says the task is created and committed INSIDE the worktree (never the primary tree)
- [x] #3 The Backlog-first task tracking section agrees (no 'before the worktree' wording)
- [x] #4 validate_markdown passes
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Reordered the AGENTS.md non-negotiables so the worktree is rule 1 (primary tree is OFF-LIMITS for all files including backlog task files) and backlog-first is rule 2 (task created via the CLI run FROM inside the worktree). Updated the Backlog-first task tracking section and the Parallel work Rules line to agree. Removes the old 'before the worktree, create the task' wording that caused task files to land in the primary tree.
<!-- SECTION:FINAL_SUMMARY:END -->
