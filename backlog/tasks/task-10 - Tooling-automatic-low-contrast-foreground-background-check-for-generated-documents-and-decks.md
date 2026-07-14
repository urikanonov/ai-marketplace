---
id: TASK-10
title: >-
  Tooling: automatic low-contrast foreground/background check for generated
  documents and decks
status: To Do
assignee: []
created_date: '2026-07-14 17:19'
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
- [ ] #1 A reusable contrast utility computes the WCAG contrast ratio between two colors and flags pairs below a configurable threshold
- [ ] #2 The check runs from the deck validator (and/or the document validator) and reports the offending selector/color pair with an actionable message
- [ ] #3 A known low-contrast fixture is flagged and a known good fixture passes (covering tests)
- [ ] #4 Add a feature-id row in plugins/commentable-html/dev/SPEC.md naming the covering test; document the check in the relevant references/contract
- [ ] #5 Bump plugin version, update CHANGELOG.md, rebuild via python scripts/rebuild_all.py, confirm --check is clean
<!-- AC:END -->
