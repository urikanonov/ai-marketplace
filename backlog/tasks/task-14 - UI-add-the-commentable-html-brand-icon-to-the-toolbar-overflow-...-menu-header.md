---
id: TASK-14
title: >-
  UI: add the commentable-html brand icon to the toolbar overflow (...) menu
  header
status: In Progress
assignee:
  - '@me'
created_date: '2026-07-14 17:20'
updated_date: '2026-07-14 18:36'
labels: []
dependencies: []
ordinal: 13000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In the toolbar overflow menu (assets/js/55-toolbar-menu.js), the dropdown header shows the Portable/Not portable badge on the left and leaves the top-right corner empty (see the circled area in the screenshot). Add the commentable-html brand icon in that top-right area of the menu header so the menu is branded, without disturbing the existing badge or menu items.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The overflow menu header shows the commentable-html brand icon in its top-right corner
- [x] #2 The existing Portable/Not portable badge and all menu items (Show, Export as Portable, Export Offline, Export to Plain HTML, Export to Markdown, Help & About) are unchanged and still function
- [x] #3 The brand icon is decorative (aria-hidden) and does not add a spurious tab stop or break menu keyboard navigation
- [x] #4 Add or update a feature-id row in plugins/commentable-html/dev/SPEC.md naming a covering Playwright test
- [x] #5 Bump plugin version, update CHANGELOG.md, rebuild via python scripts/rebuild_all.py, confirm --check is clean
<!-- AC:END -->











## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add Playwright coverage for the overflow menu header icon and keyboard behavior.\n2. Add decorative CMH_ICON_SVG markup to the toolbar menu header without changing the badge or menu items.\n3. Rebuild, validate, and check acceptance criteria.
<!-- SECTION:PLAN:END -->
