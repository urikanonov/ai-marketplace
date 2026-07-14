---
id: TASK-1
title: Set up Backlog.md as the repo backlog and enforce backlog-first
status: Done
assignee:
  - '@urikanonov'
created_date: '2026-07-14 14:37'
updated_date: '2026-07-14 14:39'
labels: []
dependencies: []
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Track all work in git-committed Backlog.md task files and require a tracked task before any work starts, so work stops getting lost between AI sessions.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 backlog init run; backlog/ committed with config.yml
- [x] #2 AGENTS.md non-negotiable rule 1 requires a Backlog.md task In Progress before any work
- [x] #3 AGENTS.md documents the search-consolidate-create-plan-implement-finalize lifecycle
- [x] #4 backlog/ task files pass validate_markdown.py and validate_marketplace.py stays green
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Install backlog CLI and run backlog init (cli, agents)\n2. Commit backlog/ (config.yml) tmax-style\n3. Add AGENTS.md non-negotiable rule 1 (backlog-first) plus a Backlog-first workflow section\n4. Reset bypass_git_hooks to false\n5. Validate markdown + marketplace, open PR
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Installed Backlog.md and ran backlog init (cli, agents). Committed backlog/config.yml tmax-style. AGENTS.md now makes backlog-first non-negotiable rule 1 (no work before a tracked task In Progress) and documents the search-consolidate-create-plan-implement-finalize lifecycle in a Backlog-first section. Reset bypass_git_hooks to false. validate_markdown.py, validate_marketplace.py, and the script unit tests all pass.
<!-- SECTION:FINAL_SUMMARY:END -->
