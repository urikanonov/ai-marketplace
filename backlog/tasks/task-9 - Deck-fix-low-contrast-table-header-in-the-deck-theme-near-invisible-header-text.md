---
id: TASK-9
title: >-
  Deck: fix low-contrast table header in the deck theme (near-invisible header
  text)
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 17:19'
updated_date: '2026-07-14 19:08'
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
1. Re-bump the deck fixes PR to a distinct commentable-html version lane after CI reported a duplicate.\n2. Rebuild generated artifacts from sources.\n3. Re-run required validation and push the updated branch.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added red-first CMH-DECK-10 Playwright coverage and deck table-header CSS for high-contrast dark-slide headers.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Fixed deck table-header contrast with deck-theme CSS, covered it with the CMH-DECK-10 Playwright regression, and re-bumped the PR to version 1.56.0 after the CI version-lane collision.
<!-- SECTION:FINAL_SUMMARY:END -->
