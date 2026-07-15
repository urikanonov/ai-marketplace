# Example prompt - Design review sign-off

A minimal prompt that produces the companion `report-notes.html`. It is a sign-off surface
built around commentable **editable notes fields**, so it exercises the plain-text field, the
single/multi-line toggle, the per-note change card, and the notes-state bundle.

## Prompt

> Make me a commentable HTML design review sign-off built around editable notes fields. Add a
> short "Overall verdict" section with a single-line editable note for a go / no-go decision,
> then a "Reviewer notes" section with a multi-line editable note for free-form feedback, and
> finish with a short "How the round-trip works" section explaining that edits come back
> through Copy all.

## What you get

From that one line, the skill produces a single self-contained HTML file you can open in any
browser and share:

- Each `data-cmh-note` field becomes an editable text area with a clearly-editable look, a
  label chip, and a single/multi-line toggle.
- Typing in a note is tracked against its authored baseline and saved in the browser; a
  per-note card with jump and reset appears in the review sidebar, and the badge flips to Not
  portable until the edit is saved into the file.
- Your edits are collected into Copy all as a `NOTES_STATE_JSON` line so an agent can cement
  them back into the source with `tools/notes/notes_apply.py`, and every export bakes the
  current text into the source.
- Notes are `cm-skip`, so editing one never creates a stray highlight comment.
