---
id: TASK-7
title: 'Deck: fix drag-and-drop triage board not working in deck mode (slide 5)'
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 17:19'
updated_date: '2026-07-14 18:38'
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
1. Add a Playwright deck regression test that drags a triage card between columns and confirm it fails on current built output.
2. Inspect deck startup and triage widget drag wiring to find why deck mode suppresses the drag path.
3. Fix the owning runtime partial, rebuild generated assets, and rerun the deck regression.
4. Update SPEC, version, changelog, generated artifacts, validators, and backlog acceptance criteria.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added red-first CMH-DECK-08 Playwright coverage, opted the roadmap deck risk board into widget drag-and-drop, rebuilt generated artifacts, and verified the regression is green.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Fixed the roadmap deck risk board by adding the missing widget drag opt-in to the source deck, regenerated the shipped deck and site demos, and verified CMH-DECK-08 plus widget/deck regression specs. PR: https://github.com/urikanonov/ai-marketplace/pull/131
<!-- SECTION:FINAL_SUMMARY:END -->
