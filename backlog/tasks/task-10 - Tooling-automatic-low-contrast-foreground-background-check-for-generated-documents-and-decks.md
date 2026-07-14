---
id: TASK-10
title: >-
  Tooling: automatic low-contrast foreground/background check for generated
  documents and decks
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 17:19'
updated_date: '2026-07-14 21:02'
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
1. Add regression tests for the six review findings first, including non-finite rgb handling, transparent backgrounds, declaration-order background precedence, url() masking, malformed rgb arity, and equal-color ratio.\n2. Update tools/validate/cmhval/contrast.py to reject non-finite values, skip semi-transparent backgrounds, preserve declaration order, ignore url()/quoted content during color fallback extraction, and enforce rgb()/rgba() arity.\n3. Update the CMH-DECK-08 spec row test list, rebuild without changing the 1.55.0 version, run targeted pytest and shipped deck validation, then run rebuild_all, rebuild_all --check, validate_marketplace, and validate_markdown.\n4. Commit the review fixes and force-push tooling/contrast-check, then finalize TASK-10 again.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Addressed review findings for the contrast checker: non-finite and malformed rgb/rgba values are skipped without crashing, semi-transparent backgrounds are skipped, background shorthand follows declaration order, url() and quoted text are ignored during fallback color extraction, equal-color ratio coverage was added, CMH-DECK-08 docs/spec were updated, generated site output was rebuilt, and validation passed with targeted pytest, deck_validate on examples/deck-roadmap.html, rebuild_all, rebuild_all --check, validate_marketplace, and validate_markdown.
<!-- SECTION:FINAL_SUMMARY:END -->
