---
id: TASK-2
title: >-
  Make advisory checks accurate: blank-heading tolerates HTML comments;
  version-lane clarifies trailing lanes
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 15:32'
updated_date: '2026-07-14 15:40'
labels: []
dependencies: []
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Two advisory CI checks produce misleading output. validate_markdown flags Backlog.md's generated '## Section' immediately followed by an '<!-- MARKER -->' comment as a blank-heading warning, even though task files must not be hand-edited. And check_version_lane reports a PR that TRAILS a higher open lane as a collision and tells it to bump above the higher lane, which is backwards for intentional stacked merges (the lower version should merge first).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 validate_markdown does not emit a blank-heading warning when a heading is immediately followed by an HTML comment line, and the committed backlog task files pass validate_markdown with zero warnings
- [x] #2 check_version_lane distinguishes a DUPLICATE lane (real conflict, must re-bump) from TRAILING a higher open lane (fine when this PR merges first), with clear messaging that never tells a trailing PR to bump above the higher lane
- [x] #3 Both fixes are covered by tests in scripts/test_validate_markdown.py and scripts/test_check_version_lane.py, written red-first
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. TDD blank-heading in test_validate_markdown.py (red), then let check_blank_after_heading accept a following HTML-comment line. 2. TDD version-lane in test_check_version_lane.py (red) pinning DUPLICATE=conflict vs TRAILING-higher=no-conflict, then fix evaluate() and the message. 3. Run both test files, validate_markdown (0 warnings), validate_marketplace. 4. Commit, push, PR (scripts-only, no version bump).
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Fixed two misleading advisory checks. validate_markdown's blank-heading rule now allows an HTML comment immediately after a heading, so Backlog.md's generated '## Section' + '<!-- MARKER -->' task files pass with zero warnings (the whole repo is now 0 markdown warnings). check_version_lane now treats only a DUPLICATE lane as a conflict (exit 1); trailing a higher open lane is an informational note and exits 0, since that is the intentional stacked-merge order (lower version merges first) - the old code wrongly told a trailing PR to bump above the higher lane. Covered red-first by scripts/test_validate_markdown.py and scripts/test_check_version_lane.py; AGENTS.md updated to match. Scripts-only, no plugin version bump.
<!-- SECTION:FINAL_SUMMARY:END -->
