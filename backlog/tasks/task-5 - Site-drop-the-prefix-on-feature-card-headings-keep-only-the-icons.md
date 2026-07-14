---
id: TASK-5
title: 'Site: drop the >  prefix on feature-card headings, keep only the icons'
status: To Do
assignee: []
created_date: '2026-07-14 17:19'
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
- [ ] #1 The .feature h3::before greater-than prefix is removed so no card heading renders a leading greater-than glyph
- [ ] #2 Each feature cards SVG icon still renders and heading text is unchanged
- [ ] #3 Edit the source site-src/css/34-cards.css (never site/), rerun python scripts/build_site_data.py, and confirm --check is clean
- [ ] #4 Add or update a feature-id row in tests/site/SPEC.md naming a covering site test that asserts no card heading starts with the greater-than prefix
<!-- AC:END -->
