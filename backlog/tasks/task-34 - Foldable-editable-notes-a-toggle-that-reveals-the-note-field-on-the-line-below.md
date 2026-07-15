---
id: TASK-34
title: >-
  Foldable editable notes: a +/- toggle that reveals the note field on the line
  below
status: Done
assignee:
  - '@me'
created_date: '2026-07-15 06:45'
updated_date: '2026-07-15 07:18'
labels: []
dependencies: []
ordinal: 32000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add a foldable presentation mode to the editable notes field (data-cmh-note): an inline +/- toggle sits on a line, and expanding it reveals the editable note textarea on the line below; the + becomes - when expanded and collapses (hides) the field again when clicked. Opt-in via a data-cmh-note-foldable attribute; a foldable note starts collapsed (showing +) but auto-expands when it has an unsaved edit so the change is never hidden. Session-only fold state, accessible (button + aria-expanded/aria-controls). Extends the notes feature already in flight in PR #147 (commentable-html), so it should fold into that PR to keep the notes feature cohesive and avoid version-lane stacking.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A data-cmh-note-foldable note renders an inline +/- toggle and starts collapsed with the textarea hidden
- [x] #2 Clicking + expands to show the note field on the line below and flips the icon to -; clicking - hides the field and flips back to +
- [x] #3 A foldable note with an unsaved edit (pending change) auto-expands so the edit is visible
- [x] #4 The toggle is an accessible button (aria-expanded, aria-controls); non-foldable notes are unchanged
- [x] #5 A CMH-NOTE spec row names a covering Playwright test; validator/scaffold cover the new attribute; rebuild_all + validators pass
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Final design after 3-duck panel + user review. Fold state is per-note (note.foldable, note.collapsed), session-only, evaluated ONCE at setup: collapsed = foldable && normalizeNote(current)==='' (user: empty->collapsed showing +, has-content->expanded showing -; a persisted non-empty edit therefore auto-expands). After load only the fold button click and jumpToNote change collapsed; renders/_noteAfterChange/reset never touch fold state (manual collapse sticks). jumpToNote expands (clear cmh-note-collapsed + sync button/aria) BEFORE focus. Fold button: real <button type=button cm-skip> injected at header start ONLY for foldable notes, dynamic aria-label (Expand/Collapse note: <label>), aria-controls to a counter-based textarea id (ta.id=cmh-note-input-N), aria-expanded synced, +/- glyph via CSS, preventDefault+stopPropagation. Collapsed badge (user comment 2): container gets cmh-note-has-content when collapsed && content!=''; CSS shows a small badge; empty=no badge. CSS: #commentRoot-scoped .cmh-note-collapsed hides .cmh-note-input + .cmh-note-toggle via display:none (must outrank the id-scoped display:block). Persistence: fold state NEVER enters ::note/NOTES_STATE_JSON/notes_apply; export preserves data-cmh-note-foldable but no runtime collapsed class/button (baseHtml is the on-disk snapshot). Scaffold --foldable flag under CMH-NOTE-14 + test_notes_scaffold.py; runtime CMH-NOTE-16 in 62-notes.spec.js (collapsed-if-empty, expanded-if-content, + expands, - collapses, keyboard Enter/Space, reload-with-edit auto-expands, manual-collapse survives rerender, jump expands, non-foldable unchanged, export has no collapsed class). No validator change (case-insensitive true opts in). Amend the existing 1.64.0 CHANGELOG entry; fold into PR #147 (no new version bump).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented in PR #147: data-cmh-note-foldable renders a +/- disclosure that reveals the editable field on the line below. Starts collapsed only when empty (content -> expanded); session-only fold state evaluated once at load so a manual collapse sticks; accessible button (aria-expanded + aria-controls to a unique textarea id); collapsed-with-content badge; jumpToNote expands before focus; collapse never touches storage/export/apply. notes_scaffold.py --foldable; report-notes.html demo showcases it. SPEC CMH-NOTE-16 (4 Playwright tests) + CMH-NOTE-14 scaffold. 973 Python + 17 notes Playwright tests green.
<!-- SECTION:FINAL_SUMMARY:END -->
