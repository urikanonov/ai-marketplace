---
id: TASK-9
title: >-
  Deck: fix low-contrast table header in the deck theme (near-invisible header
  text)
status: To Do
assignee: []
created_date: '2026-07-14 17:19'
labels: []
dependencies: []
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
On a dark deck slide, a tables header row renders with a near-white background and near-white text so the Theme / What ships / Owner / Risk labels are almost invisible (see screenshot of the Themes we plan to invest in slide). Fix the deck theme CSS so table header text has adequate contrast against its header background on dark slides.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Table header cells on a dark deck slide have clearly legible text with sufficient contrast against the header background
- [ ] #2 The fix is in the deck theme CSS partial (not a per-report hack) so any authored deck table is legible
- [ ] #3 Add or update a feature-id row in plugins/commentable-html/dev/SPEC.md naming a covering test that asserts the header contrast
- [ ] #4 Bump plugin version, update CHANGELOG.md, rebuild via python scripts/rebuild_all.py, confirm --check is clean
<!-- AC:END -->
