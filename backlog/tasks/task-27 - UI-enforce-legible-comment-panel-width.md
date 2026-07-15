---
id: TASK-27
title: 'UI: enforce legible comment panel width'
status: In Progress
assignee:
  - '@me'
created_date: '2026-07-15 03:52'
labels: []
dependencies: []
ordinal: 25000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Keep the commentable-html side panel from becoming narrow enough to clip core action labels, and keep the comment search placeholder readable at the minimum panel width.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Sidebar resize and CSS minimum width keep Copy all, export button labels, and the search placeholder legible at the minimum width.
- [ ] #2 The comment search field uses enough horizontal space for the full Search comments placeholder at the minimum panel width.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Rebase the existing PR onto origin/main. 2. Re-lane commentable-html to 1.61.0 and preserve main's released history. 3. Merge the search anti-regression test with the PR placeholder-width test. 4. Rebuild generated artifacts and validate before pushing.
<!-- SECTION:PLAN:END -->
