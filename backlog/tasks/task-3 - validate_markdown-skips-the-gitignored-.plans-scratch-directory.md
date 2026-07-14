---
id: TASK-3
title: validate_markdown skips the gitignored .plans scratch directory
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 16:15'
updated_date: '2026-07-14 16:17'
labels: []
dependencies: []
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The .plans/ dir is gitignored local scratch (never committed), but validate_markdown still scans .md files inside it and reports blank-heading/style warnings on local runs, which is noise. It is the same class as .worktrees and node_modules, which are already excluded.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 validate_markdown's find_markdown_files excludes a nested .plans/ directory (its .md files are not scanned), matching how .worktrees is excluded, and still scans when the run root itself is under a .plans ancestor
- [x] #2 A local run with a .plans/*.md scratch file reports no findings for it; the change is covered by a test in scripts/test_validate_markdown.py written red-first
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a red test in scripts/test_validate_markdown.py that find_markdown_files excludes a nested .plans/ dir. 2. Add '.plans' (and 'tmp', the other gitignored scratch dir) to EXCLUDE_DIRS in validate_markdown.py. 3. Run script tests + validate_markdown. 4. Commit, push, PR, merge.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added '.plans' and 'tmp' (both gitignored local scratch dirs) to EXCLUDE_DIRS in scripts/validate_markdown.py, so their .md files are no longer scanned - matching how .worktrees and node_modules are excluded. Local runs with a .plans scratch file are now quiet; a clean CI checkout was already unaffected (those dirs are gitignored). Covered red-first by test_excludes_scratch_dirs in scripts/test_validate_markdown.py. Scripts only, no version bump.
<!-- SECTION:FINAL_SUMMARY:END -->
