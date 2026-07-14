---
id: TASK-7
title: 'Deck: fix drag-and-drop triage board not working in deck mode (slide 5)'
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 17:19'
updated_date: '2026-07-14 19:08'
labels: []
dependencies: []
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In the current sample deck, the drag-and-drop triage board on slide 5 does not let cards be dragged between columns. The same triage widget works in report mode, so this is a deck-mode regression in the widget wiring (assets/js/35-widgets.js interacting with the deck profile setupDeck). Investigate why pointer/drag handlers are not active when the widget is inside a deck slide and fix it.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Cards in the deck triage board can be dragged between columns in deck mode, matching report-mode behavior
- [x] #2 Reproduce the defect with a failing Playwright test first (TDD, confirmed red), then fix so it passes
- [x] #3 Add a feature-id row in plugins/commentable-html/dev/SPEC.md naming the covering test
- [x] #4 Bump the plugin version and update CHANGELOG.md; rebuild dist, fixtures, and site via python scripts/rebuild_all.py and confirm --check is clean
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Re-bump the deck fixes PR to a distinct commentable-html version lane after CI reported a duplicate.\n2. Rebuild generated artifacts from sources.\n3. Re-run required validation and push the updated branch.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added red-first CMH-DECK-08 Playwright coverage, opted the roadmap deck risk board into widget drag-and-drop, rebuilt generated artifacts, and verified the regression is green.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Fixed the deck roadmap risk board by making it opt in to the draggable widget contract, covered it with the CMH-DECK-08 Playwright regression, and re-bumped the PR to version 1.56.0 after the CI version-lane collision.
<!-- SECTION:FINAL_SUMMARY:END -->
