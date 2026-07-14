---
id: TASK-10
title: >-
  Tooling: automatic low-contrast foreground/background check for generated
  documents and decks
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 17:19'
updated_date: '2026-07-14 21:15'
labels: []
dependencies: []
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add an author-time check that flags color pairs whose foreground and background are too similar (insufficient contrast), so problems like the invisible deck table header are caught before publish. Compute a WCAG-style contrast ratio for text-vs-background color pairs used in the document/deck and fail (or warn) when the ratio is below a threshold. Wire it into the deck validator (deck/deck_validate.py) and/or the general validator so it runs deterministically.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A reusable contrast utility computes the WCAG contrast ratio between two colors and flags pairs below a configurable threshold
- [x] #2 The check runs from the deck validator (and/or the document validator) and reports the offending selector/color pair with an actionable message
- [x] #3 A known low-contrast fixture is flagged and a known good fixture passes (covering tests)
- [x] #4 Add a feature-id row in plugins/commentable-html/dev/SPEC.md naming the covering test; document the check in the relevant references/contract
- [x] #5 Bump plugin version, update CHANGELOG.md, rebuild via python scripts/rebuild_all.py, confirm --check is clean
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Rebase tooling/contrast-check onto origin/main and resolve conflicts by keeping main for generated artifacts, preserving contrast source/test changes, and re-laning to the next free version.\n2. Rename the contrast feature id from CMH-DECK-08 to CMH-DECK-12 across spec and tests, then verify there are no duplicate CMH-DECK ids after the rebase.\n3. Rebuild generated outputs, run targeted contrast tests, deck example validation, rebuild/validation checks, and push with the pre-push hook.\n4. Finalize TASK-10 and report the final version, feature id, and hook result.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Rebased tooling/contrast-check onto origin/main, re-laned commentable-html to 1.57.0, renumbered the contrast feature to CMH-DECK-12, preserved the contrast checker hardening fixes, rebuilt generated artifacts, verified no duplicate CMH-DECK ids, and validated with targeted pytest, deck_validate on shipped deck examples, rebuild_all, rebuild_all --check, validate_marketplace, and validate_markdown.
<!-- SECTION:FINAL_SUMMARY:END -->
