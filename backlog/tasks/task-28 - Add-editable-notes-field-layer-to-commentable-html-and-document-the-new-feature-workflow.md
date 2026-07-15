---
id: TASK-28
title: >-
  Add editable notes-field layer to commentable-html and document the
  new-feature workflow
status: Done
assignee:
  - '@me'
created_date: '2026-07-15 04:57'
updated_date: '2026-07-15 06:20'
labels: []
dependencies: []
ordinal: 24000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Introduce an authored, editable free-text notes field (data-cmh-note) that tracks edits against an authored baseline the same way the triage board and layered checklist track state changes: minimal localStorage delta, a per-field change card in the sidebar, a Copy-all bundle line, an export bake, and a deterministic apply tool that cements the edited text back into the source HTML so the round-trip between reviewer edits and the agent is fully closed and testable. Keep SKILL.md growth minimal by putting the detail in an on-demand reference. Also add a repo doc that captures the full new-feature workflow (backlog-first, worktree, TDD, spec row + test, minimal SKILL.md + reference, build/rebuild, version bump, changelog, validation) so future feature additions follow it.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A reviewer can edit an authored data-cmh-note field in the browser and the edit is tracked, persisted, and surfaced as a per-field change card like the board/checklist
- [x] #2 The edited note text travels back to the agent via Copy all and a deterministic apply tool cements it into the source HTML; the full round-trip is covered by an automated end-to-end test
- [x] #3 SKILL.md grows minimally and the detail lives in a new references/notes-contract.md
- [x] #4 A new repo guide documents the end-to-end new-feature workflow and is referenced from AGENTS.md
- [x] #5 All required gates pass: spec rows + named tests, validator, rebuild_all --check, version bump + changelog
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Design: data-cmh-note="id" editable field mirrors the layered checklist. Runtime upgrades each [data-cmh-note] into a contenteditable, cm-skip field (cmh-note-ready). Baseline = initial textContent captured at setup; edits stored as a minimal delta (only when current!=baseline) in localStorage under COMMENT_KEY+"::note" as {id:text}; back-to-baseline prunes. One per-field change card (jump + reset-to-baseline) placed by document order, not a comment, with a first-change timestamp. Badge flips Not portable while unsaved. Copy all appends a Note "<id>" section + NOTES_STATE_JSON line. Every export bakes text via _applyNoteStateToHtml. Tools notes_scaffold.py (validator-clean markup + stable id) and notes_apply.py (cement NOTES_STATE_JSON by id, deterministic + idempotent). validate.py notes checks (dup/empty id, strict-escalated). references/notes-contract.md + one-line SKILL.md mention.

New files: assets/js/37-notes.js, assets/css/86-notes.css, tools/notes/notes_scaffold.py, tools/notes/notes_apply.py, references/notes-contract.md, dev/tests/61-notes.spec.js, dev/tests/test_notes_apply.py, dev/tests/test_notes_scaffold.py, dev/tests/test_validate_notes.py, dev/examples/src/report-notes.html (+ built examples/report-notes.html), docs/adding-a-feature.md.
Edits: 50-sidebar.js, 56-copy-clear.js, 70-mode-badge.js, 65/66/67/68 exports, validate/validate.py, SKILL.md, dev/SPEC.md, CHANGELOG.md, dev/VERSION, AGENTS.md.

Tests (TDD, red first): Playwright 61-notes.spec.js CMH-NOTE-01..09 + CMH-NOTE-E2E (edit -> Copy-all bundle -> spawn python notes_apply.py -> reopen applied file -> baked text present, no pending change, badge portable). Python test_notes_apply.py (CMH-NOTE-10), test_notes_scaffold.py (CMH-NOTE-11), test_validate_notes.py (CMH-NOTE-12). Playwright loads BUILT dist so build.py before asserting runtime.

Gates: edit split partials only; bump dev/VERSION + sync plugin.json/manifest + CHANGELOG; python scripts/rebuild_all.py then --check clean; regenerate fixtures (version embeds); validate_marketplace.py + validate_markdown.py.

PRs: PR1 (TASK-28.2) docs/adding-a-feature.md + AGENTS.md link (no version bump, independent). PR2 (TASK-28.1) notes feature end-to-end (version bump + rebuild). Fresh worktree per PR off origin/main; distinct version lane.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Delivered as two PRs: #147 (editable notes-field feature, commentable-html 1.62.0) and #148 (new-feature workflow guide). Planned as a commentable-HTML doc, reviewed by a 4-model rubber-duck panel and the maintainer, then implemented with full spec-and-test coverage and all gates green.
<!-- SECTION:FINAL_SUMMARY:END -->
