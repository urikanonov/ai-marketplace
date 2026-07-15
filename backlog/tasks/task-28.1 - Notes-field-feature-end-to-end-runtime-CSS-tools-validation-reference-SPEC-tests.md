---
id: TASK-28.1
title: >-
  Notes-field feature end to end (runtime, CSS, tools, validation, reference,
  SPEC, tests)
status: Done
assignee: []
created_date: '2026-07-15 04:58'
updated_date: '2026-07-15 06:20'
labels: []
dependencies: []
parent_task_id: TASK-28
ordinal: 25000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Implement the editable notes-field layer in commentable-html, mirroring the layered checklist. Runtime partial (assets/js) that upgrades each data-cmh-note element into an editable field, records edits as a minimal delta vs the authored baseline (data-cmh-note-baseline / element text) in localStorage under COMMENT_KEY, renders one per-field change card in the sidebar (placed by document order, not counted as a comment, with a first-change timestamp and a Reset-to-baseline button), flips the mode badge to Not portable while unsaved, appends a Copy-all section plus a machine-readable NOTES_STATE_JSON line, and bakes the current text into the source on every export. CSS partial for the editable field and card. Tools notes_scaffold.py (emit validator-clean data-cmh-note markup with a stable id) and notes_apply.py (deterministically and idempotently cement NOTES_STATE_JSON text back into each data-cmh-note element, from a bundle or --state-json). validate.py notes checks (duplicate ids, empty id) as strict-escalated warnings. references/notes-contract.md and a minimal SKILL.md mention. SPEC rows CMH-NOTE-NN each naming a covering test. Tests: Playwright for the interactive layer and Python for the tools, including a full end-to-end round-trip test (edit -> Copy-all bundle -> notes_apply cements -> reload shows baked baseline, no pending change). Bump dev/VERSION, update CHANGELOG, run rebuild_all.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 An authored data-cmh-note field is editable in the browser; edits persist as a minimal localStorage delta and restore on reload; returning to baseline prunes the entry
- [x] #2 Each changed note renders one non-comment change card (jump + reset-to-baseline) placed by document order; the comment count stays 0; the badge flips to Not portable with a note-naming reason until re-exported
- [x] #3 Copy all emits a Notes section and a NOTES_STATE_JSON line; every export bakes the current note text into the source markup
- [x] #4 notes_scaffold.py emits validator-clean markup with a stable id; notes_apply.py cements NOTES_STATE_JSON text deterministically and idempotently from a bundle or --state-json; validate.py flags duplicate/empty note ids under --strict
- [x] #5 A single automated end-to-end test proves the full reviewer-edit -> agent round-trip; every CMH-NOTE-NN spec row names a passing test; rebuild_all --check, validator, version bump and changelog all pass
- [x] #6 SKILL.md growth is minimal and the detail lives in references/notes-contract.md
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Two more user review points (round 2): (1) The note change card's jump/reset buttons must use the SAME theme as regular comment cards (reuse the existing .cm-card .acts data-act button styling, exactly like the checklist card's jump/reset already do - do NOT invent new button styles). (2) Notes must be SEARCHABLE: wire note change cards / note text into the sidebar comment search (51-comment-search.js) so a search term matches a changed note (by label and/or current+baseline text) and filters/highlights its card like comment cards. Add a CMH-NOTE spec row + Playwright test for searchability, and confirm the card markup carries whatever text/attributes the search indexer reads.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Shipped in PR #147 (commentable-html 1.62.0): editable data-cmh-note fields (textarea + single/multi-line toggle), minimal ::note delta persistence, per-note change card (jump/reset, searchable), badge flip, Copy-all NOTES_STATE_JSON, export bake, notes_scaffold.py + notes_apply.py, validate.py guardrails, references/notes-contract.md, report-notes.html demo, SPEC CMH-NOTE-01..15 + CMH-DEMO-05. 972 Python tests + 13 notes Playwright tests green (incl the full E2E round-trip).
<!-- SECTION:FINAL_SUMMARY:END -->
