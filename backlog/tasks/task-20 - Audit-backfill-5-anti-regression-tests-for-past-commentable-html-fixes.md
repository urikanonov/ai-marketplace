---
id: TASK-20
title: 'Audit: backfill 5 anti-regression tests for past commentable-html fixes'
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 22:43'
updated_date: '2026-07-14 23:16'
labels: []
dependencies: []
ordinal: 18000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Backfill test-only coverage for five previously fixed commentable-html regressions so they cannot silently return.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Highlight parity covers notKw tokens for CSS, Python, and Rust, with Playwright assertions that they are not keyword spans.
- [x] #2 Highlight parity covers SQL strings and uppercase SQL, Batch, and PowerShell style case-insensitive keywords in the JS highlighter.
- [x] #3 Comment search tests prove quote text, section path text, and pin or anchor labels do not drive matches.
- [x] #4 Deck validation integration covers background shorthand overriding background-color for contrast checks.
- [x] #5 Contrast parser tests ignore quoted color-looking strings such as content hash-fff.
- [x] #6 SPEC rows name the new tests, no version bump files are touched, and validators plus targeted tests pass.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect the existing highlight, search, deck validation, contrast tests, fixtures, and SPEC rows to verify each requested gap.
2. Add test-only anti-regression coverage in the existing Playwright and Python suites plus highlight fixture data.
3. Update the existing SPEC rows so CMH-TOOL-16, CMH-SEARCH-04, and CMH-DECK-12 name the new guards.
4. Run targeted Python and Playwright tests, then run rebuild_all --check and the validators.
5. Check acceptance criteria, commit only the changed tests, fixture, SPEC row, and backlog task, then push and open the PR.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Verified gaps by reading the existing tests and fixtures. Added test-only guards in the highlight parity fixture/spec, comment search Playwright spec, deck validation integration test, contrast parser test, and SPEC rows. highlight_parity.json is read directly by tests/57-highlight-parity.spec.js and tests/test_highlight_parity.py, so no highlighter golden regeneration was needed.

Validation passed: python -m pytest plugins\\commentable-html\\dev\\tests\\test_highlight_parity.py plugins\\commentable-html\\dev\\tests\\test_contrast.py::ContrastUtilityTests::test_cmh_deck_12_color_in_quoted_string_content_is_not_a_color plugins\\commentable-html\\dev\\tests\\test_deck_validate.py::DeckValidateTests::test_cmh_deck_12_background_shorthand_overrides_background_color; npx playwright test 57-highlight-parity.spec.js 60-comment-search.spec.js --grep "GH-REGRESS-HIGHLIGHT-PARITY|CMH-SEARCH-04"; python scripts\\validate_marketplace.py; python scripts\\validate_markdown.py; python scripts\\rebuild_all.py --check.

Review follow-up: reassessing the CMH-TOOL-16 notKw tokens to ensure each one would fail against the pre-v1.3.1 runtime highlighter.

Review follow-up resolved: replaced fake notKw probes with tokens removed by the v1.3.1 runtime keyword-set fix. Verified from git history that commit 110890f, the parent of 3a2f596, treated data, filter, local, process, and val as runtime keywords, while 3a2f596 removed them. The final notKw probes are CSS .filter/local/process, Python filter/local/process, and Rust data/local/val. A scratch revert that restored the old broad keyword set in assets/js/26-highlight.js, rebuilt the dist, and ran 57-highlight-parity.spec.js failed on rust:data as expected; restoring the fix passed. A direct keyword-set check showed every final notKw token has old_kw=True and current_kw=False.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Backfilled five commentable-html anti-regression guards and corrected the CMH-TOOL-16 notKw probes after review. The notKw tokens now all come from the old broad runtime keyword set and are absent from the fixed set, so the parity spec fails when that fix is reverted.
<!-- SECTION:FINAL_SUMMARY:END -->
