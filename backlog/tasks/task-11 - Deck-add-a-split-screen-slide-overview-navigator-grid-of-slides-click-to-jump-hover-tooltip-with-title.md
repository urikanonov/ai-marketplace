---
id: TASK-11
title: >-
  Deck: add a split-screen slide-overview navigator (grid of slides, click to
  jump, hover tooltip with title)
status: To Do
assignee: []
created_date: '2026-07-14 17:19'
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
- [ ] #1 A toggle opens an overview grid showing a thumbnail for every slide in the deck
- [ ] #2 Clicking a slide in the grid navigates the deck to that slide and closes the overview
- [ ] #3 Hovering a slide shows a tooltip containing that slides title
- [ ] #4 The overview is keyboard accessible (open/close and select) and works in both present and comment modes
- [ ] #5 Add feature-id rows in plugins/commentable-html/dev/SPEC.md naming covering Playwright tests
- [ ] #6 Bump plugin version, update CHANGELOG.md, rebuild via python scripts/rebuild_all.py, confirm --check is clean
<!-- AC:END -->
