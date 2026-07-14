---
id: TASK-4
title: Split validate.py into focused cmhval submodules (drain the monolith)
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 16:41'
updated_date: '2026-07-14 19:21'
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
- [x] #1 validate.py's independent check groups (doc parser, layer contract, chart checks, checklist checks, diff/Kusto advisories, self-contained/offline checks, kind/h1 checks) are moved into focused modules under the cmhval/ (or bucketed tools/validate/) package, with validate.py reduced to a thin orchestrator plus CLI
- [x] #2 Every existing validate test (test_validate.py, test_validate_charts.py, test_validate_mermaid.py, test_validate_json.py, test_validate_failclosed.py) passes with no behavior change; each moved public symbol keeps its import path or is re-exported so callers (finalize, retrofit, upgrade, tests) are unaffected
- [x] #3 SPEC file references are updated where a test's module path changes; pure refactor, so no new feature ids are required
- [x] #4 Version bumped and CHANGELOG updated (shipped-source change); validate_marketplace and rebuild_all --check are green
- [x] #5 Started only AFTER #113, #121, and #122 merge, in a fresh worktree off the resulting main, and run as the sole in-flight editor of validate.py
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Baseline: capture golden validator output over all examples/templates. 2. Add checks/ package (parsing, resources, kind, charts, checklist, highlighting, layer) - keep cmhval/ as the optional content-syntax package so test_validate_failclosed (blocks cmhval import) still passes. 3. Extract bottom-up (parsing first, layer last), moving symbols verbatim. 4. Thin validate.py to _read/_parse/validate/validate_charts/main + cmhval fail-closed bootstrap + a re-export block covering the full test/tool surface (validate.validate, validate_charts, check_charts, check_checklists, check_mermaid_syntax, _parse, _PARSE_FAIL, REQUIRED_IDS, _DOC_KINDS, _is_nonportable, _nonportable_css_refs/js_refs/meta_versions). 5. Run full pytest after each move; confirm golden baseline unchanged. 6. Update SPEC source-pointers (not test refs) for moved functions. 7. Bump to 1.51.0 + CHANGELOG Development entry, rebuild_all, open PR alone.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Split tools/validate/validate.py (1,959 lines) into a focused checks/ package (parsing, resources, kind, charts, checklist, highlighting, layer); validate.py is now a 342-line entry point that re-exports each module's public names so no test or caller import changed. Kept cmhval/ as the separate optional content-syntax package so test_validate_failclosed (which blocks the whole cmhval import) still passes. Decomposed check_layer from ~460 lines to a 94-line orchestrator plus 13 helpers. Pure refactor: 924 tests pass unchanged, validator output byte-identical on all examples/templates (golden baseline). Bumped to 1.52.0, updated CMH-VAL-11/CMH-CONTENT-16 spec source pointers, added -h/--help and -- separator CLI tests. Shipped in PR #136.
<!-- SECTION:FINAL_SUMMARY:END -->
