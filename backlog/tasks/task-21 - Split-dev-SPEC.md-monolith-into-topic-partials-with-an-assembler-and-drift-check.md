---
id: TASK-21
title: >-
  Split dev/SPEC.md monolith into topic partials with an assembler and drift
  check
status: To Do
assignee: []
created_date: '2026-07-15 00:10'
labels: []
dependencies: []
ordinal: 19000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Audit lane-4 finding: dev/SPEC.md is ~172KB, 400 lines, 91 revisions - the top collision/clobber surface (it caused repeated feature-id collisions during the UI/deck batch). Split it into dev/spec/NN-{lifecycle,anchors,exports,ui,content,security,build,deck}.md and add a docs assembler that concatenates them into the checked SPEC.md, with a --check drift guard wired into rebuild_all and CI (mirroring the build.py partial pattern). Whole-file reorg: run alone and last.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 dev/SPEC.md is generated from dev/spec/NN-*.md partials by an assembler with a --check drift guard
- [ ] #2 Concurrent spec edits touch different partials, not one monolith
- [ ] #3 The spec-and-test gate and all readers of SPEC.md still pass
<!-- AC:END -->
