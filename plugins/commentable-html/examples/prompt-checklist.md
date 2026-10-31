# Example prompt - Release readiness review

A minimal prompt that produces the companion `report-checklist.html`. It is a sign-off
surface for the **Dynamic Controls demo**: four-state layered checklists in both nested-list and
sortable-table shapes, editable review notes and an editable follow-up table in one document.

## Prompt

> Make me a commentable HTML release readiness review built around layered checklists. Add
> a nested "Sign-off checklist" with Backend (migrations, load test, feature flags),
> Frontend (accessibility, localization), plus release notes and a rollback plan, each with
> a four-state checkbox. Then add a sortable "Component audit" table whose rows link to a
> parent (Network -> firewall, TLS; Identity -> MFA, secrets rotation) with an Owner column,
> then add editable Release verdict and Reviewer notes. Add an editable follow-up table with
> Follow-up, Owner, numeric Effort (hours), and single-choice Status columns. Include row/column
> insertion, mouse column dragging, resize/Autofit, explicit title/cell comments, and Undo/Redo.
> Finish with a short "How to use this" section explaining the combined Copy all and export flow.

## What you get

From that one line, the skill produces a single self-contained HTML file you can open in
any browser and share:

- Every item has a four-state checkbox (blank, check, cross, question) with pretty icons;
  click to cycle it, or click a parent to push its state to all of its children.
- A parent row aggregates its children automatically, showing a neutral dash when they
  disagree, and the table shape uses `data-cmh-parent` so the hierarchy survives sorting.
- Your state changes are saved in the browser, surfaced as one per-list card with jump and
  Reset, and collected into Copy all so an agent can cement them back into the source with
  `tools/checklist/checklist_apply.py`.
- Item labels stay ordinary commentable text, so you can still leave a note on any item.
- Notes keep their own per-field cards; the editable table keeps one cumulative card for cell,
  structure and width changes. Sorting is presentation-only, and explicit title/cell comment
  icons create separate threads.
- Copy all carries checklist, note and table state to their respective apply tools. Export as
  Shareable or Offline bakes all current values into the new copy; edits alone save only in this
  browser, and Copy selected carries only selected comment threads.
