---
id: TASK-17
title: >-
  Help/About: surface the author GitHub link visibly and add a plugin changelog
  link
status: In Progress
assignee:
  - '@me'
created_date: '2026-07-14 17:23'
updated_date: '2026-07-14 18:36'
labels: []
dependencies: []
ordinal: 16000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In the Help and About dialog (assets/js/75-help.js, About block) the author name already links to https://github.com/urikanonov via class cm-brand-link, but that class is styled color: inherit; text-decoration: none (assets/css/10-layout.css) so it does not look clickable until hover - which is why it reads as plain text (the v1.29.0 screenshot predates the link; current source is v1.49.0). Make the author name read as a real link, and add a new list item linking to the plugin changelog (plugins/commentable-html/CHANGELOG.md, e.g. its GitHub blob or the site changelog section) alongside Website, Source, Report an issue, Request a feature, Contribute.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The author name (Uri Kanonov) in the About dialog is clearly recognizable as a link to https://github.com/urikanonov (visible affordance, not only on hover)
- [x] #2 A new Changelog link is added to the About list that opens the commentable-html changelog
- [x] #3 All existing About links remain and keep target=_blank rel=noopener
- [x] #4 Add or update a feature-id row in plugins/commentable-html/dev/SPEC.md naming a covering test that asserts the author link and the changelog link are present
- [x] #5 Bump plugin version, update CHANGELOG.md, rebuild via python scripts/rebuild_all.py, confirm --check is clean
<!-- AC:END -->











## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add Playwright coverage for the About author link affordance and changelog link.\n2. Add the Changelog About link and update cm-brand-link CSS so the author link is visibly clickable.\n3. Rebuild, validate, and check acceptance criteria.
<!-- SECTION:PLAN:END -->
