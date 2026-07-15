---
id: TASK-42
title: >-
  Author the pitch/showcase deck per the duck-reviewed plan (replace the
  pre-plan deck)
status: Done
assignee:
  - '@urikanonov'
created_date: '2026-07-15 10:11'
updated_date: '2026-07-15 14:35'
labels: []
dependencies: []
ordinal: 35000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The shipped deck-showcase.html (v1.58.0) predates the duck-reviewed plan. Author the deck the plan specifies: a 17-slide, light-only Parchment and Amber deck (raspberry accent + the amber comment-highlight motif as a decorative class, not the live mark.cm-hl), five acts with a self-contained 5-10 minute hook, one running example (report-community-garden) threaded through slides 2-8, and about five disciplined live interactions (each a different proof). Source at dev/examples/src/deck-showcase.html (keep the shipped filename); rebuild the shipped/site copies. Supersedes the completed task-16 deck.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 17-slide Parchment and Amber deck authored at dev/examples/src/deck-showcase.html per the plan outline; light-only (pins data-theme=light); rebuilt to the shipped examples + site demo
- [x] #2 One running example threaded through slides 2-8; about five disciplined live interactions
- [x] #3 CMH-DECK-SHOWCASE spec rows updated to describe the new deck; deck mounts + present/comment modes tested
- [x] #4 rebuild_all --check clean; version bump + CHANGELOG
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Reworked deck-showcase.html into the plan's 17-slide light-only Parchment and Amber deck: 5-act narrative, one community-garden running example threaded through Act 2, disciplined interactions, all rich content rethemed for light slides (chart, Mermaid, triage board, checklist, diff, KQL). CMH-DECK-SHOWCASE-01/02 rewritten, -03 added. v1.76.0. Deck build v2.
<!-- SECTION:FINAL_SUMMARY:END -->
