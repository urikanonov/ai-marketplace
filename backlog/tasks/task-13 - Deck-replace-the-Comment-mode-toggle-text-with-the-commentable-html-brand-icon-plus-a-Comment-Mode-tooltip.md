---
id: TASK-13
title: >-
  Deck: replace the Comment mode toggle text with the commentable-html brand
  icon plus a Comment Mode tooltip
status: To Do
assignee: []
created_date: '2026-07-14 17:20'
labels: []
dependencies: []
ordinal: 12000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In deck mode the comment-mode toggle button (assets/js/95-startup.js sets toggle.textContent = Comment mode) renders a wide text label. Replace the text label with the commentable-html brand icon and expose the label Comment Mode as a tooltip (title) and accessible name (aria-label), keeping the existing aria-pressed toggle semantics. Add an inline brand SVG in the runtime if one is not already available.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The deck comment-mode toggle shows the commentable-html brand icon instead of the text Comment mode
- [ ] #2 Hovering the toggle shows a tooltip reading Comment Mode and the button keeps an accessible name of Comment Mode plus its aria-pressed state
- [ ] #3 Toggling still enters/exits comment mode exactly as before
- [ ] #4 Add or update a feature-id row in plugins/commentable-html/dev/SPEC.md naming a covering Playwright test
- [ ] #5 Bump plugin version, update CHANGELOG.md, rebuild via python scripts/rebuild_all.py, confirm --check is clean
<!-- AC:END -->
