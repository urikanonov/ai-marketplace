---
id: TASK-47
title: Add persistence and batch-copy selling points to the commentable-html pitch
status: Done
assignee:
  - '@me'
created_date: '2026-07-15 10:36'
updated_date: '2026-07-15 10:47'
labels: []
dependencies: []
ordinal: 35000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The pitch (plugin README and the site plugin page) does not surface two strong value props of existing behavior: comments persist in localStorage and survive a browser restart or reboot while iterating, and Copy all returns every comment at once so the agent makes one coordinated, coherent edit instead of a fragile one-at-a-time pass.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Plugin README states comments survive a browser restart/reboot (localStorage) and that Copy all returns every comment at once for one coordinated edit
- [x] #2 Site plugin page What-you-get section adds a persistence card and enriches the Round-trip card with the batch/coordinated-edit point
- [x] #3 New spec rows (CMH-DOC-11, SITE-PLUGIN-18, SITE-PLUGIN-19) each name a covering test that is red before the change and green after
- [x] #4 commentable-html version bumped, CHANGELOG updated, and all generated artifacts (dist, fixtures, site) rebuilt so rebuild_all.py --check and validators pass
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. TDD: add CMH-DOC-11 test (README) + SITE-PLUGIN-18/19 tests (site page); confirm RED. 2. Add spec rows to dev/SPEC.md and site/tests/SPEC.md. 3. Edit README.md pitch (privacy bullet, persistence + Copy-all feature bullets). 4. Edit site/pages/commentable-html/index.html (persistence card + Round-trip card). 5. Bump dev/VERSION 1.70.0->1.71.0, add CHANGELOG entry. 6. rebuild_all.py to regen dist/fixtures/site. 7. Run doc tests + site suite + validators + rebuild_all --check; go green.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added two pitch selling points for existing behavior. README and site plugin page now state that comments persist in localStorage and survive a browser restart/reboot (new 'Comments survive a restart' What-you-get card), and that Copy all returns every comment at once for one coordinated, coherent agent edit (enriched Round-trip card and README Copy-all bullet). New spec rows CMH-DOC-11 (PitchPersistenceAndBatchDocsTests), SITE-PLUGIN-18 and SITE-PLUGIN-19 with covering tests, confirmed red-first then green. Bumped commentable-html 1.70.0 -> 1.71.0, added CHANGELOG entry, rebuilt dist/fixtures/site. All gates green: validators, changelog/version-bump, doc+build (67), full site suite (80), generator unit tests, rebuild_all --check.
<!-- SECTION:FINAL_SUMMARY:END -->
