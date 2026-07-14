---
id: TASK-18
title: 'Comment search matches only the comment note, not the quoted anchor text'
status: In Progress
assignee:
  - '@urikanonov'
created_date: '2026-07-14 18:22'
updated_date: '2026-07-14 18:26'
labels: []
dependencies: []
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The sidebar comment-search filter currently matches the reviewer's note AND the quoted anchor text (plus section path and pin), so typing a word that appears only in the quoted passage keeps a comment visible. Reviewers expect the search to filter by what THEY wrote (the comment text), not by the surrounding quote. Change the search haystack to the comment note only.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Comment search matches only the comment note text; a query that appears only in the quoted anchor (or section/pin) no longer matches
- [x] #2 Searching a word present in the note still matches; existing case-insensitive substring, shown/total count, clear button, and no-results behaviors are unchanged
- [x] #3 A covering Playwright test (CMH-SEARCH-04) is added and the SPEC row updated; the plugin version is bumped and the changelog updated
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
TDD: add a red Playwright test that adds a comment, reads a distinctive word from its rendered .quote, and asserts searching that quote-only word yields 0 matches (fails on current code). Then narrow _commentCardHaystack() in assets/js/51-comment-search.js to collect only .note. Update the CMH-SEARCH-01 SPEC wording, add CMH-SEARCH-04, bump version, changelog, rebuild dist+fixtures+site.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Narrowed _commentCardHaystack() in assets/js/51-comment-search.js from '.note, .quote, .section, .pin' to '.note' only. Added Playwright test CMH-SEARCH-04 (searches a word taken from the rendered .quote and asserts 0 matches) and updated the CMH-SEARCH-01 SPEC wording. Version 1.52.0; dist/fixtures/site rebuilt.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Comment search filters by the reviewer's note text only; a quote-only query no longer matches. TDD red->green, CMH-SEARCH-04 added, shipped in commentable-html 1.52.0.
<!-- SECTION:FINAL_SUMMARY:END -->
