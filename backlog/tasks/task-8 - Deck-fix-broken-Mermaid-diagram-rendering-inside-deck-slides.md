---
id: TASK-8
title: 'Deck: fix broken Mermaid diagram rendering inside deck slides'
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 17:19'
updated_date: '2026-07-14 19:08'
labels: []
dependencies: []
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In the sample deck, the diagram on the Proposed architecture shift slide renders as a broken cluster of white blocks and dashes instead of a real diagram (see screenshot). Mermaid diagrams render correctly in report mode, so the deck profile is mis-sizing or mis-initializing Mermaid (assets/js/20-mermaid.js under the deck layout/theme). Fix so authored Mermaid diagrams render legibly on a deck slide.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A Mermaid diagram authored on a deck slide renders as a correct, legible diagram (nodes and edges), not stray blocks
- [x] #2 The dark deck theme does not wash out Mermaid node text or edges (adequate contrast)
- [x] #3 Reproduce with a failing Playwright test first (TDD, confirmed red), then fix so it passes
- [x] #4 Add a feature-id row in plugins/commentable-html/dev/SPEC.md naming the covering test
- [x] #5 Bump plugin version, update CHANGELOG.md, rebuild via python scripts/rebuild_all.py, confirm --check is clean
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Re-bump the deck fixes PR to a distinct commentable-html version lane after CI reported a duplicate.\n2. Rebuild generated artifacts from sources.\n3. Re-run required validation and push the updated branch.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added red-first CMH-DECK-09 Playwright coverage and deck Mermaid CSS overrides for high-contrast nodes, labels, and connectors on dark slides.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Fixed Mermaid rendering on dark deck slides with deck-level contrast overrides, covered it with the CMH-DECK-09 Playwright regression, and re-bumped the PR to version 1.56.0 after the CI version-lane collision.
<!-- SECTION:FINAL_SUMMARY:END -->
