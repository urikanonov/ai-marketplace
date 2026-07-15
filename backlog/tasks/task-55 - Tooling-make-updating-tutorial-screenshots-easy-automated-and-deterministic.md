---
id: TASK-55
title: 'Tooling: make updating tutorial screenshots easy, automated, and deterministic'
status: To Do
assignee: []
created_date: '2026-07-15 13:09'
labels: []
dependencies: []
ordinal: 44000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The commentable-html tutorial page uses screenshots that must be refreshed when the UI changes. Provide an easy, automated, deterministic process (for example a Playwright-driven script with a fixed viewport, fonts, seeded state, and no timestamps) to regenerate all tutorial screenshots reproducibly, and wire a drift check so stale screenshots are caught.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A single documented command regenerates all tutorial screenshots
- [ ] #2 The process is deterministic (fixed viewport, fonts, and state; no timestamps or randomness) so re-running produces byte-identical images
- [ ] #3 Regenerated screenshots are committed and the tutorial page references them
- [ ] #4 A drift check or documented gate catches stale tutorial screenshots
<!-- AC:END -->
