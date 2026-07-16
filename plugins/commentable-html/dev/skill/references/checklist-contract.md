# Layered checklist contract

A layered checklist turns a nested list (or a table) into interactive, four-state checkboxes whose
parent state aggregates from its children, whose state persists in `localStorage`, and whose changes
travel back to the agent through the Copy-all bundle so the states can be cemented into the source HTML.

## Author markup

A checklist is any element marked `data-cmh-checklist="<id>"`. An **item** is any descendant carrying
`data-cmh-state` or `data-cmh-item`; the attribute is the opt-in, so an item can be a `<li>`, a table
`<tr>`, or a `<div>`. A **branch** is an item that has child items; a **leaf** has none. The runtime
injects a `cm-skip` state control into each item (before a list item's label, or into a table row's
first cell or its `[data-cmh-state-cell]`); the item's label text stays ordinary commentable content.

- `data-cmh-checklist="<id>"` - the checklist id. It is the storage sub-key, the Copy-all heading, and
  the `checklist_apply.py` target, so keep it unique per document.
- `data-cmh-checklist-label="..."` - an optional friendly title (defaults to the id).
- `data-cmh-state` - the authored baseline for a leaf: `blank` | `check` | `cross` | `question`
  (omitted = `blank`). Ignored on a branch, which always derives its state.
- `data-cmh-item="<id>"` - an optional stable item id. When absent, the item's identity is its 1-based
  position in document order within the checklist. Identity is never rendered (no visible numeration).
- `data-cmh-parent="<item-id>"` - for the table shape only, names the parent item's `data-cmh-item`
  id, since table rows cannot nest. Required to build hierarchy in a table (which may be sorted).

### Shape A - nested list (hierarchy by DOM nesting)

```html
<div class="cmh-checklist" data-cmh-checklist="release" data-cmh-checklist-label="Release readiness">
  <ul>
    <li data-cmh-item="backend" data-cmh-state="blank">Backend
      <ul>
        <li data-cmh-item="mig" data-cmh-state="check">Migrations applied</li>
        <li data-cmh-item="load" data-cmh-state="cross">Load test green</li>
      </ul>
    </li>
    <li data-cmh-item="docs" data-cmh-state="question">Docs updated</li>
  </ul>
</div>
```

### Shape B - table (hierarchy by explicit parent, sortable-safe)

```html
<table class="cmh-checklist" data-cmh-checklist="audit" data-cmh-checklist-label="Security audit">
  <thead><tr><th></th><th>Control</th></tr></thead>
  <tbody>
    <tr data-cmh-item="net"                       data-cmh-state="blank"><td></td><td>Network</td></tr>
    <tr data-cmh-item="fw"  data-cmh-parent="net"  data-cmh-state="check"><td></td><td>Firewall rules</td></tr>
    <tr data-cmh-item="tls" data-cmh-parent="net"  data-cmh-state="cross"><td></td><td>TLS enforced</td></tr>
  </tbody>
</table>
```

Do not hand-write the ids and parent links: generate the markup with
`python tools/checklist/checklist_scaffold.py --in outline.txt --shape list|table --id <id> --label "..."`.

## Runtime behavior

- **States and cycle.** Clicking (or Enter/Space on) a leaf cycles
  `blank -> check -> cross -> question -> blank`, drawn with inline-SVG icons.
- **Aggregation.** A branch derives its state from its DIRECT children: all-same shows that state, any
  disagreement shows a neutral `mixed` marker. This rolls up recursively.
- **Propagation.** Clicking a branch cycles it to its next state (from `mixed`, to `check`) and sets
  every descendant leaf to that state.
- **Persistence.** Only leaves whose current state differs from their authored baseline are stored,
  as one-character codes (`v`/`x`/`q`/`b`) under `COMMENT_KEY + "::cl"`; returning a leaf to its
  baseline prunes its entry. Branch states are never stored (they recompute).
- **Change card.** Each checklist with changes shows one non-comment card in the sidebar (placed by
  document order) with a jump button and a Reset button that reverts that checklist to its authored
  baseline. It is not counted as a comment.
- **Copy all.** The bundle gains a `## Checklist "<id>"` section listing each changed item's
  `from -> to`, plus a machine-readable `CHECKLIST_STATE_JSON: {...}` line.
- **Export.** Every export (Portable / Offline / Plain / Standalone) bakes each leaf's current state
  into its `data-cmh-state`, so the exported file opens with no pending changes.

## Cementing states into the source (the agent step)

When the reviewer pastes a Copy-all bundle back, cement the states into the source HTML deterministically:

```
python tools/checklist/checklist_apply.py source.html --from-bundle bundle.txt   # or: - for stdin
python tools/checklist/checklist_apply.py source.html --state-json '{"audit":{"fw":"cross"}}'
```

It rewrites `data-cmh-state` on each named item (by `data-cmh-item` id, else positional key), leaves
branches untouched, is idempotent, and skips invalid tokens. Run `python tools/validate/validate.py --strict`
afterward.

## Validation

`validate.py` (a no-op for a checklist-free document) warns - and, under `--strict`, fails - on
duplicate `data-cmh-checklist` ids, invalid `data-cmh-state` tokens, a checklist with no items,
duplicate `data-cmh-item` ids within one checklist, and a `data-cmh-parent` that does not resolve to
an item in the same checklist.
