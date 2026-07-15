---
id: TASK-47
title: >-
  Deck comment-mode chrome cleanup: hide toggle when panel open, no action
  toolbar, full-width background
status: Done
assignee:
  - '@me'
created_date: '2026-07-15 09:53'
updated_date: '2026-07-15 10:37'
labels: []
dependencies: []
ordinal: 34000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In deck comment mode the corner comment-toggle icon is poorly colored while the side panel is open, the comments action toolbar (Copy all/Show/...) leaks into decks, and the slide background does not span full width when the panel is hidden. Reported via screenshots.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 In a deck, the comment-mode toggle icon is hidden whenever the comment side panel is open (all viewport widths), and reappears when the panel is hidden
- [x] #2 The comments action toolbar (.cm-toolbar) never appears in a deck; only the single corner icon and the nav bar are shown
- [x] #3 In deck comment mode with the side panel hidden, the slide/stage background spans the full screen width (no reserved black bar)
- [x] #4 Existing deck comment-mode behavior (enter/exit, sidebar, keyboard gating) is unchanged; SPEC row + Playwright coverage added; validators and deck tests pass
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add red Playwright tests in tests/52-deck.spec.js: toggle hidden when sidebar open on wide viewport; .cm-toolbar hidden in a deck even in comment mode with panel closed; deck-viewport spans full width when comment mode + sidebar closed. 2. CSS 90-deck.css: hide .cmh-deck-mode-toggle when body.sidebar-open in deck comment mode (all widths); hide .cm-toolbar in deck; gate the .deck-viewport right-inset on body.sidebar-open. 3. Bump dev/VERSION to 1.70.0, add SPEC row CMH-DECK-14, update CHANGELOG. 4. Rebuild (scripts/rebuild_all.py) and run deck specs + validators.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Deck comment-mode chrome cleanup shipped in commentable-html 1.72.0 (dev/assets/css/90-deck.css). The corner comment-mode toggle now hides at every width while the side panel is open (was only hidden on narrow screens and mis-coloured over the slide); the comments action toolbar (.cm-toolbar) is hidden in any deck in both present and comment mode via body:has(#commentRoot[data-cmh-mode=deck]); and the deck-viewport sidebar inset is gated on body.sidebar-open so the stage spans the full width when the panel is hidden (no black bar). Covered by SPEC CMH-DECK-14 and three Playwright tests in tests/52-deck.spec.js; two existing toggle tests (CMH-DECK-05a, CMH-DECK-11) updated for the new exit path (hide panel to reveal the toggle). All deck + chrome suites, validators, and rebuild --check pass.
<!-- SECTION:FINAL_SUMMARY:END -->
