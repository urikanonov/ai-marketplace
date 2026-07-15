---
id: TASK-40
title: Surface the commentable-html version visibly in dist/README.md and SKILL.md
status: In Progress
assignee:
  - '@me'
created_date: '2026-07-15 09:33'
updated_date: '2026-07-15 09:46'
labels: []
dependencies: []
ordinal: 33000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The CHM skill version currently lives only in machine-readable spots (dev/VERSION, manifest.json, CMH_VERSION const, plugin.json, marketplace entry, and page meta). A human opening the shipped skill or dist folder cannot easily see which version they have. Add a clear, human-readable version line to the shipped SKILL.md and dist/README.md, single-sourced from dev/VERSION and stamped by build.py so it never drifts, with build --check catching staleness.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The shipped dist/README.md shows the current version in a clear, human-readable place
- [x] #2 The shipped SKILL.md shows the current version in a clear, human-readable place
- [x] #3 build.py stamps both files from dev/VERSION (single source of truth) and build --check fails when either is stale
- [x] #4 A SPEC row names covering automated tests and the plugin test/validators pass
<!-- AC:END -->



## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. TDD: add failing tests - docs test asserting shipped SKILL.md and dist/README.md show a visible version equal to the shipped runtime version; build test for stamp helpers + source_stamps includes both files + --check catches drift.
2. Add a clear version line to dist/README.md and SKILL.md (initial value = current version).
3. Implement build.py stamping and wire into source_stamps so build re-stamps and --check gates drift.
4. Add SPEC row CMH-DOC-09 naming the tests.
5. Bump dev/VERSION, run rebuild_all.py, update CHANGELOG.
6. Validate: pytest build+docs, validate_marketplace, validate_markdown, rebuild_all --check.
<!-- SECTION:PLAN:END -->
