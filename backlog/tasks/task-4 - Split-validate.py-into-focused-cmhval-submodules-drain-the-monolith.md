---
id: TASK-4
title: Split validate.py into focused cmhval submodules (drain the monolith)
status: To Do
assignee:
  - '@me'
created_date: '2026-07-14 16:41'
labels: []
dependencies: []
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The shipped tools/validate.py is a large single module (~1750 lines) that mixes many independent checks: the HTML doc parser, the commentable-html layer contract, chart validation, checklist checks, diff/Kusto advisories, self-contained/offline resource checks, kind/h1 checks, and the CLI. The mermaid and embedded-JSON content checks were already extracted into tools/cmhval/ in PR #113; this task continues draining the monolith so validate.py becomes a thin orchestrator over focused submodules, matching AGENTS.md non-negotiable #4 (edit split partials, never a monolith) and the house preference against giant scripts. It MUST run ALONE and LAST relative to the other in-flight tools reorgs (#121 directory consolidation, #122 tools bucketing which moves validate.py to tools/validate/validate.py, and #113 syntax validators) because a whole-file reorg cannot 3-way-merge against concurrent edits to the same file.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 validate.py's independent check groups (doc parser, layer contract, chart checks, checklist checks, diff/Kusto advisories, self-contained/offline checks, kind/h1 checks) are moved into focused modules under the cmhval/ (or bucketed tools/validate/) package, with validate.py reduced to a thin orchestrator plus CLI
- [ ] #2 Every existing validate test (test_validate.py, test_validate_charts.py, test_validate_mermaid.py, test_validate_json.py, test_validate_failclosed.py) passes with no behavior change; each moved public symbol keeps its import path or is re-exported so callers (finalize, retrofit, upgrade, tests) are unaffected
- [ ] #3 SPEC file references are updated where a test's module path changes; pure refactor, so no new feature ids are required
- [ ] #4 Version bumped and CHANGELOG updated (shipped-source change); validate_marketplace and rebuild_all --check are green
- [ ] #5 Started only AFTER #113, #121, and #122 merge, in a fresh worktree off the resulting main, and run as the sole in-flight editor of validate.py
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Wait for #113/#121/#122 to merge. 2. Fresh worktree off the resulting main. 3. Identify cohesive check groups in validate.py and extract each into its own submodule (doc_parser, layer, charts, checklist, advisories, resources, kind), keeping shared helpers in a _common module. 4. Re-export moved public names from validate.py so import paths stay stable. 5. Run the full validate test suite (stays green with only module-path reference edits). 6. Bump version + CHANGELOG, run all gates, open the PR alone.
<!-- SECTION:PLAN:END -->
