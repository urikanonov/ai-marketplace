---
id: TASK-11
title: >-
  Deck: add a split-screen slide-overview navigator (grid of slides, click to
  jump, hover tooltip with title)
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 17:19'
updated_date: '2026-07-14 20:48'
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
1. Rebase deck/features onto current origin/main, resolve version lane conflicts by taking generated artifacts from main then rebuilding with version 1.56.0.
2. Renumber the comment-mode icon feature id to CMH-DECK-11 while keeping overview CMH-DECK-06 and verify no duplicate deck ids.
3. Fix review findings in setupDeck: decorative toggle icon tooltip, inert/non-focusable overview clones, preserved mark child nodes, no background navigation while overview is open, and export stripping of the lazy overview.
4. Extend deck Playwright coverage and SPEC rows, rebuild, validate, force-push, and confirm PR checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Validation passed: npx playwright test 52-deck.spec.js; python scripts/rebuild_all.py; python scripts/rebuild_all.py --check; python scripts/validate_marketplace.py; python scripts/validate_markdown.py; pre-push hook.

Review fixes passed: npx playwright test 52-deck.spec.js 62-deck-regressions.spec.js; python scripts/rebuild_all.py --check; python scripts/validate_marketplace.py; python scripts/validate_markdown.py; duplicate CMH-DECK id check.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Rebased onto origin/main, moved the lane to 1.56.0, kept overview as CMH-DECK-06, and fixed review findings for overview tab order, mark clone preservation, background-key gating, export stripping, generated artifacts, and tests.
<!-- SECTION:FINAL_SUMMARY:END -->
