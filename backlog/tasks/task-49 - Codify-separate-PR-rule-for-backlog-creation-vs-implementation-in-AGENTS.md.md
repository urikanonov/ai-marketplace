---
id: TASK-49
title: Codify separate-PR rule for backlog creation vs implementation in AGENTS.md
status: Done
assignee:
  - '@me'
created_date: '2026-07-15 12:39'
updated_date: '2026-07-15 12:52'
labels: []
dependencies: []
ordinal: 40000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The maintainer requires that backlog-item creation always lands in its own PR (so tasks are persisted and never lost if implementation stalls), separate from the implementation PR. Batching multiple backlog-item creations into a single creation PR is allowed. Codify this in AGENTS.md so all contributors follow it.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 AGENTS.md states backlog-item creation must land in its own PR, separate from the implementation PR
- [x] #2 AGENTS.md states batching multiple backlog-item creations into one PR is allowed
- [x] #3 AGENTS.md explains the rationale (a creation-only PR guarantees the task is persisted even if the implementation PR is abandoned)
- [x] #4 validate_markdown.py passes on the edited AGENTS.md
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Backlog-creation PR (this PR): create TASK-49 and commit only the task file so the task is persisted even if implementation stalls.
2. Implementation PR (separate): add PR-structure guidance to the Backlog-first section of AGENTS.md - creation lands in its own PR separate from implementation, batching multiple creations into one PR is allowed, plus the rationale - and cross-reference it from non-negotiable rule 2. Run validate_markdown.py.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Codified in AGENTS.md that backlog-item creation lands in its own PR, separate from the implementation PR: added a bolded rule to the Backlog-first section (creation-only PR first, merged so the task persists even if implementation stalls; batching multiple creations into one PR is allowed and encouraged; creation-only PRs touch only backlog/tasks and need no version bump or test) and cross-referenced it from non-negotiable rule 2. validate_markdown.py passes.
<!-- SECTION:FINAL_SUMMARY:END -->
