---
id: TASK-15
title: >-
  UI: disable Copy all when there are no comments, with a No comments to copy
  tooltip
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 17:21'
updated_date: '2026-07-14 20:23'
labels: []
dependencies: []
ordinal: 14000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The Copy all button (assets/js/56-copy-clear.js) is always enabled even when the comment count is 0, so clicking it copies an empty bundle. When there are no comments to copy, disable the Copy all button and give it a tooltip reading No comments to copy. Re-enable it automatically as soon as a comment exists, and keep it in sync as comments are added, cleared, or marked handled.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 When the open-comment count is 0 the Copy all button is disabled and shows a tooltip reading No comments to copy
- [x] #2 When at least one comment exists the Copy all button is enabled and its tooltip/behavior returns to normal
- [x] #3 The enabled/disabled state stays in sync as comments are added, cleared, or marked handled (including on initial load)
- [x] #4 The disabled state is accessible (aria-disabled and not a silent no-op) and keyboard users get the same tooltip affordance
- [x] #5 Add or update a feature-id row in plugins/commentable-html/dev/SPEC.md naming a covering Playwright test (0-comment disabled, becomes enabled after a comment)
- [x] #6 Bump plugin version, update CHANGELOG.md, rebuild via python scripts/rebuild_all.py, confirm --check is clean
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Fold the disabled-empty Copy all behavior back into canonical CMH-COPY-04.\n2. Remove the redundant CMH-COPY-08 row and update the current Playwright test title/citations.\n3. Rebuild, validate, check feature-id/test-title consistency, then force-push.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Folded the disabled-empty Copy all behavior back into canonical CMH-COPY-04, removed redundant CMH-COPY-08, and verified SPEC/test citations and validators.
<!-- SECTION:FINAL_SUMMARY:END -->
