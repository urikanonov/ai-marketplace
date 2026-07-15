---
id: TASK-26
title: 'Docs: correct the repo-wide site SPEC test-file citation path'
status: To Do
assignee: []
created_date: '2026-07-15 00:10'
labels: []
dependencies: []
ordinal: 24000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
All rows in site/tests/SPEC.md cite site/tests/site/tests.spec.js, but the real Playwright suite is site/tests/tests/site.spec.js (the cited path does not exist). Rows bind by test name and CI passes, but the file citation is misleading. Correct the path repo-wide in one pass, or document the canonical-label convention if intentional.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Every site SPEC row cites a real existing test file path (or the convention is documented)
- [ ] #2 No test-name bindings change; the site suite still passes
<!-- AC:END -->
