# Example prompt - Release readiness review

A minimal prompt that produces the companion `report-checklist.html`. It is a sign-off
surface built around commentable **layered checklists**, so it exercises the four-state
item controls, parent aggregation, and the state-change bundle in both the nested-list and
the sortable-table shapes.

## Prompt

> Make me a commentable HTML release readiness review built around layered checklists. Add
> a nested "Sign-off checklist" with Backend (migrations, load test, feature flags),
> Frontend (accessibility, localization), plus release notes and a rollback plan, each with
> a four-state checkbox. Then add a sortable "Component audit" table whose rows link to a
> parent (Network -> firewall, TLS; Identity -> MFA, secrets rotation) with an Owner column,
> and finish with a short "How to use this" section.

## What you get

From that one line, the skill produces a single self-contained HTML file you can open in
any browser and share:

- Every item has a four-state checkbox (blank, check, cross, question) with pretty icons;
  click to cycle it, or click a parent to push its state to all of its children.
- A parent row aggregates its children automatically, showing a neutral dash when they
  disagree, and the table shape uses `data-cmh-parent` so the hierarchy survives sorting.
- Your state changes are saved in the browser, surfaced as one per-list card with jump and
  Reset, and collected into Copy all so an agent can cement them back into the source with
  `tools/checklist_apply.py`.
- Item labels stay ordinary commentable text, so you can still leave a note on any item.
