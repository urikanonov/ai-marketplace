---
id: TASK-8
title: 'Deck: fix broken Mermaid diagram rendering inside deck slides'
status: In Progress
assignee:
  - '@me'
created_date: '2026-07-14 17:19'
updated_date: '2026-07-14 18:32'
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
1. Add a Playwright deck regression test that loads a Mermaid diagram on a deck slide and confirms rendered nodes, edges, and contrast, then confirm it fails on current built output.
2. Inspect Mermaid initialization, deck lifecycle, and deck dark-theme CSS for sizing or color conflicts.
3. Fix the owning Mermaid runtime or CSS partials, rebuild generated assets, and rerun the regression.
4. Update SPEC, version, changelog, generated artifacts, validators, and backlog acceptance criteria.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added red-first CMH-DECK-09 Playwright coverage and deck Mermaid CSS overrides for high-contrast nodes, labels, and connectors on dark slides.
<!-- SECTION:NOTES:END -->
