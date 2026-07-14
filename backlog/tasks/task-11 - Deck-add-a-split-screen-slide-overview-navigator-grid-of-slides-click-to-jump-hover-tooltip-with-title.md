---
id: TASK-11
title: >-
  Deck: add a split-screen slide-overview navigator (grid of slides, click to
  jump, hover tooltip with title)
status: In Progress
assignee:
  - '@me'
created_date: '2026-07-14 17:19'
updated_date: '2026-07-14 18:33'
labels: []
dependencies: []
ordinal: 10000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add a deck overview mode that shows all slides as a grid (split screen). Clicking a slide jumps the deck to it; hovering a slide shows a tooltip with that slides title. This gives fast non-linear navigation for longer decks. Implement in the deck runtime profile (setupDeck) with a keyboard/toolbar toggle, matching the existing deck navigation UX.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A toggle opens an overview grid showing a thumbnail for every slide in the deck
- [x] #2 Clicking a slide in the grid navigates the deck to that slide and closes the overview
- [x] #3 Hovering a slide shows a tooltip containing that slides title
- [x] #4 The overview is keyboard accessible (open/close and select) and works in both present and comment modes
- [x] #5 Add feature-id rows in plugins/commentable-html/dev/SPEC.md naming covering Playwright tests
- [x] #6 Bump plugin version, update CHANGELOG.md, rebuild via python scripts/rebuild_all.py, confirm --check is clean
<!-- AC:END -->













## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add Playwright coverage first for the deck overview grid: open, slide count, title tooltip, click navigation, close behavior, and keyboard open/close/select in present and comment modes.
2. Extend setupDeck with an overview toggle, keyboard shortcut, slide title extraction, focus management, grid item activation, and current-slide synchronization.
3. Add deck overview CSS in 90-deck.css, update SPEC and release metadata, rebuild generated artifacts, and run targeted and repository checks.
<!-- SECTION:PLAN:END -->
