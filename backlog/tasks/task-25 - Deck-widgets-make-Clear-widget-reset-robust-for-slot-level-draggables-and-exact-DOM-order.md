---
id: TASK-25
title: >-
  Deck/widgets: make Clear widget-reset robust for slot-level draggables and
  exact DOM order
status: To Do
assignee: []
created_date: '2026-07-15 00:10'
labels: []
dependencies: []
ordinal: 23000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Follow-up from the Clear-reverts-widgets fix (PR #133): a review panel noted two edge cases (no regression, currently unexercised): (1) boards that opt into drag via data-cm-draggable on SLOTS (not the widget root) may not be captured/reset; (2) restore re-appends parts in document order, which can reposition a non-part sibling interleaved with cards and rewrites untouched boards. Improve fidelity: restore exact original sibling order, only touch changed widgets, and support slot-level opt-in.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Clear restores slot-level draggable boards and exact DOM order; untouched widgets are not mutated
- [ ] #2 Tests cover a two-board case (one untouched) and a slot-level board with multiple moves
<!-- AC:END -->
