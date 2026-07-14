---
id: TASK-8
title: 'Deck: fix broken Mermaid diagram rendering inside deck slides'
status: To Do
assignee: []
created_date: '2026-07-14 17:19'
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
- [ ] #1 A Mermaid diagram authored on a deck slide renders as a correct, legible diagram (nodes and edges), not stray blocks
- [ ] #2 The dark deck theme does not wash out Mermaid node text or edges (adequate contrast)
- [ ] #3 Reproduce with a failing Playwright test first (TDD, confirmed red), then fix so it passes
- [ ] #4 Add a feature-id row in plugins/commentable-html/dev/SPEC.md naming the covering test
- [ ] #5 Bump plugin version, update CHANGELOG.md, rebuild via python scripts/rebuild_all.py, confirm --check is clean
<!-- AC:END -->
