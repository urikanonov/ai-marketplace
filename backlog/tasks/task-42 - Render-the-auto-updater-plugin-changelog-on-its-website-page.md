---
id: TASK-42
title: Render the auto-updater plugin changelog on its website page
status: In Progress
assignee:
  - '@me'
created_date: '2026-07-15 10:00'
updated_date: '2026-07-15 10:01'
labels: []
dependencies: []
ordinal: 35000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The commentable-html page shows a generated Changelog section built from its CHANGELOG.md, but the auto-updater page has none. Generalize build_site_data.py to render the auto-updater changelog on its page, add a #changelog section with a BEGIN:changelog marker, and a nav Changelog link.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The auto-updater page has a generated #changelog section built from the plugin CHANGELOG.md, with a nav Changelog link and a link to the full changelog on GitHub
- [ ] #2 build_site_data.py --check is clean and a covering test (generator + Playwright) asserts the changelog renders
<!-- AC:END -->
