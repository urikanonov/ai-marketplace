---
id: TASK-9
title: >-
  Deck: fix low-contrast table header in the deck theme (near-invisible header
  text)
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 17:19'
updated_date: '2026-07-14 18:38'
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
- [x] #1 Table header cells on a dark deck slide have clearly legible text with sufficient contrast against the header background
- [x] #2 The fix is in the deck theme CSS partial (not a per-report hack) so any authored deck table is legible
- [x] #3 Add or update a feature-id row in plugins/commentable-html/dev/SPEC.md naming a covering test that asserts the header contrast
- [x] #4 Bump plugin version, update CHANGELOG.md, rebuild via python scripts/rebuild_all.py, confirm --check is clean
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a Playwright deck regression test that measures dark-slide table header text contrast and confirm it fails on current built output.
2. Inspect deck and content table CSS to locate the low-contrast cascade.
3. Fix the deck theme CSS partial so authored deck table headers are high contrast and rerun the regression.
4. Update SPEC, version, changelog, generated artifacts, validators, and backlog acceptance criteria.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added red-first CMH-DECK-10 Playwright coverage and deck table-header CSS for high-contrast dark-slide headers.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Fixed dark-slide table-header contrast in the deck theme CSS and verified CMH-DECK-10 with the generated roadmap deck. PR: https://github.com/urikanonov/ai-marketplace/pull/131
<!-- SECTION:FINAL_SUMMARY:END -->
