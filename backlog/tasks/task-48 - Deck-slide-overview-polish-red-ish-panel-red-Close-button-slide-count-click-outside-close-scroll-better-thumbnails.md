---
id: TASK-48
title: >-
  Deck slide-overview polish: red-ish panel, red Close button, slide count,
  click-outside close, scroll, better thumbnails
status: Done
assignee:
  - '@me'
created_date: '2026-07-15 09:53'
updated_date: '2026-07-15 10:37'
labels: []
dependencies: []
ordinal: 35000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The deck slide overview needs visual and behavior polish per screenshots: light red-ish panel background, a Close button with the regular red-ish accent background, the slide count shown next to the title, clicking the main deck area closes the overview, the grid scrolls when slides overflow the screen, and thumbnails render the slide content instead of near-blank slides.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The overview panel has a light red-ish (accent-tinted) background instead of neutral gray
- [x] #2 The overview Close button uses the regular red-ish accent background with accent foreground text
- [x] #3 The overview title shows the slide count (e.g. 'Slide overview (16)')
- [x] #4 Clicking the main deck area (outside the overview panel) closes the overview; nav controls and the overview toggle still work
- [x] #5 When slides overflow the viewport height, the overview grid scrolls properly (flex min-height:0 fix) so every slide is reachable
- [x] #6 Overview thumbnails force-reveal animated slide content so each thumbnail shows the slide's final rendered state
- [x] #7 SPEC row(s) + Playwright coverage added; validators and deck tests pass
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add red Playwright tests: overview background accent-tinted (reddish); Close button accent bg; title shows slide count; clicking deck area closes overview; grid scrollable with min-height:0; thumbnail revealed content visible. 2. CSS 90-deck.css: accent-tinted overview background; accent Close button; grid flex+min-height:0 scroll fix; force-reveal rules for overview clones. 3. JS 95-startup.js: append slide count to overview title; add deck-area click-to-close handler (excludes overview + nav + toggle). 4. Share version lane 1.70.0 with TASK-41; SPEC row CMH-DECK-15; CHANGELOG; rebuild + tests.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Deck slide-overview polish shipped in commentable-html 1.72.0 (90-deck.css + 95-startup.js). The overview panel now uses a light accent-tinted (red-ish) background, the Close button uses the accent fill with accent-fg text, and the slide count (N slides) shows next to the title. A click on the main deck area (a slide/stage/#commentRoot, not the panel/nav/toggle) closes the overview via a document click handler added on open and removed on close. The grid gets flex:1 1 auto + min-height:0 so it scrolls reliably on overflow, and overview clones force-reveal animated content so thumbnails preview the slide's final state. Covered by SPEC CMH-DECK-15 and four Playwright tests in tests/52-deck.spec.js. All deck + chrome suites, validators, and rebuild --check pass.
<!-- SECTION:FINAL_SUMMARY:END -->
