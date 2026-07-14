---
id: TASK-13
title: >-
  Deck: replace the Comment mode toggle text with the commentable-html brand
  icon plus a Comment Mode tooltip
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 17:20'
updated_date: '2026-07-14 20:48'
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
1. Rebase deck/features onto current origin/main, resolve version lane conflicts by taking generated artifacts from main then rebuilding with version 1.56.0.
2. Renumber the comment-mode icon feature id to CMH-DECK-11 while keeping overview CMH-DECK-06 and verify no duplicate deck ids.
3. Fix review findings in setupDeck: decorative toggle icon tooltip, inert/non-focusable overview clones, preserved mark child nodes, no background navigation while overview is open, and export stripping of the lazy overview.
4. Extend deck Playwright coverage and SPEC rows, rebuild, validate, force-push, and confirm PR checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Validation passed: npx playwright test 52-deck.spec.js; python scripts/rebuild_all.py; python scripts/rebuild_all.py --check; python scripts/validate_marketplace.py; python scripts/validate_markdown.py; pre-push hook.

Review fixes passed: npx playwright test 52-deck.spec.js 62-deck-regressions.spec.js; python scripts/rebuild_all.py --check; python scripts/validate_marketplace.py; python scripts/validate_markdown.py; duplicate CMH-DECK id check.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Rebased onto origin/main, renumbered the comment-mode icon feature to CMH-DECK-11, made the inserted brand SVG decorative so the button tooltip stays Comment Mode, and verified toggle behavior with Playwright coverage.
<!-- SECTION:FINAL_SUMMARY:END -->
