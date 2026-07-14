---
id: TASK-10
title: >-
  Tooling: automatic low-contrast foreground/background check for generated
  documents and decks
status: In Progress
assignee:
  - '@me'
created_date: '2026-07-14 17:19'
updated_date: '2026-07-14 18:32'
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
1. Add a shipped stdlib contrast utility under tools/ that parses CSS colors, resolves local custom properties, computes WCAG contrast ratios, and reports inline or style-rule text/background pairs below 4.5.\n2. Wire deck_validate.py to run the utility against the deck content region and include clear deck diagnostics for low contrast.\n3. Add red-first Python tests for the contrast math and deck low/good fixtures, then update SPEC.md and deck-contract.md with the scoped validator behavior.\n4. Bump commentable-html to 1.55.0, add the changelog entry, rebuild generated artifacts, run targeted tests and repository validators, then commit, push, open the PR, and finalize TASK-10.
<!-- SECTION:PLAN:END -->
