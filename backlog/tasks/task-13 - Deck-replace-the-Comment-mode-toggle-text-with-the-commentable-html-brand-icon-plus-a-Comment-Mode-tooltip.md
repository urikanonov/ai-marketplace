---
id: TASK-13
title: >-
  Deck: replace the Comment mode toggle text with the commentable-html brand
  icon plus a Comment Mode tooltip
status: In Progress
assignee:
  - '@me'
created_date: '2026-07-14 17:20'
updated_date: '2026-07-14 18:33'
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
- [x] #1 The deck comment-mode toggle shows the commentable-html brand icon instead of the text Comment mode
- [x] #2 Hovering the toggle shows a tooltip reading Comment Mode and the button keeps an accessible name of Comment Mode plus its aria-pressed state
- [x] #3 Toggling still enters/exits comment mode exactly as before
- [x] #4 Add or update a feature-id row in plugins/commentable-html/dev/SPEC.md naming a covering Playwright test
- [x] #5 Bump plugin version, update CHANGELOG.md, rebuild via python scripts/rebuild_all.py, confirm --check is clean
<!-- AC:END -->











## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add Playwright coverage first for the deck comment-mode toggle icon, Comment Mode tooltip, aria-label, aria-pressed state, and unchanged toggle behavior.
2. Replace the text label in setupDeck with the existing CMH_ICON_SVG markup while preserving the button state updates and click handler.
3. Update SPEC and release metadata alongside TASK-11, rebuild generated artifacts, and run targeted and repository checks.
<!-- SECTION:PLAN:END -->
