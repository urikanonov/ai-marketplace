---
id: TASK-12
title: >-
  Runtime: Clear does not revert dynamic widget changes in checklist mode (and
  likely triage board)
status: In Progress
assignee:
  - '@me'
created_date: '2026-07-14 17:20'
updated_date: '2026-07-14 18:36'
labels: []
dependencies: []
ordinal: 11000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Clicking Clear (assets/js/56-copy-clear.js) removes comments but does not revert dynamic widget state changes: checklist item state edits made in checklist mode persist after Clear, and the same likely affects triage-board drag moves. Clear should restore widgets (checklist item states, triage card positions) to their authored baseline in addition to clearing comments. Work test-first.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 After making checklist state changes then clicking Clear, the checklist returns to its authored baseline state
- [x] #2 After moving triage-board cards then clicking Clear, the board returns to its authored baseline layout
- [x] #3 Reproduce each with a failing Playwright test first (TDD, confirmed red), then fix so they pass
- [x] #4 Add feature-id rows in plugins/commentable-html/dev/SPEC.md naming the covering tests
- [x] #5 Bump plugin version, update CHANGELOG.md, rebuild via python scripts/rebuild_all.py, confirm --check is clean
<!-- AC:END -->











## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Write Playwright tests that change checklist state and triage card layout, click Clear, and expect authored baselines to return.\n2. Confirm the new tests fail against the current built runtime.\n3. Reset dynamic widget state during Clear, then rebuild and validate the tests pass.
<!-- SECTION:PLAN:END -->
