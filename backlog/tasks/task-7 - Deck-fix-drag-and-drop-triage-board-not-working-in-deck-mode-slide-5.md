---
id: TASK-7
title: 'Deck: fix drag-and-drop triage board not working in deck mode (slide 5)'
status: To Do
assignee: []
created_date: '2026-07-14 17:19'
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
- [ ] #1 Cards in the deck triage board can be dragged between columns in deck mode, matching report-mode behavior
- [ ] #2 Reproduce the defect with a failing Playwright test first (TDD, confirmed red), then fix so it passes
- [ ] #3 Add a feature-id row in plugins/commentable-html/dev/SPEC.md naming the covering test
- [ ] #4 Bump the plugin version and update CHANGELOG.md; rebuild dist, fixtures, and site via python scripts/rebuild_all.py and confirm --check is clean
<!-- AC:END -->
