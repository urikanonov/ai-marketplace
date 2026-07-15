---
id: TASK-22
title: Split large commentable-html test and build monoliths by topic
status: To Do
assignee: []
created_date: '2026-07-15 00:10'
labels: []
dependencies: []
ordinal: 20000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Audit lane-4 finding: test_validate.py (~107KB/1989ln), site.spec.js (~61KB/1216ln), test_build_site_data.py (~56KB), build_site_data.py (~42KB), build.py (~37KB), and tools/validate/checks/layer.py (~32KB) each combine many concerns and are change-prone. Split each by topic with the test runner or a thin facade reassembling them, sharing helpers/fixtures. Each split is a whole-file reorg - run alone.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Each named file is split into focused topic modules discovered/assembled without changing the single test/build command
- [ ] #2 No behavior change; all suites and --check gates stay green
<!-- AC:END -->
