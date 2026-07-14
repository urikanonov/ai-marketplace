---
id: TASK-5
title: 'Site: drop the >  prefix on feature-card headings, keep only the icons'
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 17:19'
updated_date: '2026-07-14 18:32'
labels: []
dependencies: []
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
On the commentable-html site page the feature cards render an icon then a literal greater-than prefix before each title (Comment on anything, Rich content, Self-contained, etc.). The prefix comes from the CSS rule .feature h3::before { content: 'GREATER '; } in site-src/css/34-cards.css. Remove the prefix so only the per-card SVG icon and the heading text show.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The .feature h3::before greater-than prefix is removed so no card heading renders a leading greater-than glyph
- [x] #2 Each feature cards SVG icon still renders and heading text is unchanged
- [x] #3 Edit the source site-src/css/34-cards.css (never site/), rerun python scripts/build_site_data.py, and confirm --check is clean
- [x] #4 Add or update a feature-id row in tests/site/SPEC.md naming a covering site test that asserts no card heading starts with the greater-than prefix
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a site Playwright regression test and spec row proving feature-card headings have no CSS-generated prefix. 2. Remove the feature-card h3 pseudo-element prefix while keeping icon markup intact. 3. Rebuild site/dist, run targeted and required validations, then commit, push, and open the PR.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented SITE-PLUGIN-17 coverage, removed the generated heading prefix from site/css/34-cards.css, rebuilt site/dist, and opened PR #128. Validation passed: build_site_data.py --check, SITE-PLUGIN-15/17 Playwright tests, validate_markdown.py, validate_marketplace.py, and the pre-push hook.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Removed the CSS-generated greater-than prefix from commentable-html feature-card headings while keeping SVG icons intact. Added SITE-PLUGIN-17 coverage, rebuilt site/dist, validated locally, and opened PR #128.
<!-- SECTION:FINAL_SUMMARY:END -->
