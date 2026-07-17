# Commentable widgets, SVG nodes, and document-wide comments

## Commentable widgets and SVG nodes (generic opt-in)

Interactive widgets and hand-authored SVG figures are commentable per part through a small
`data-*` contract, so a reviewer can pin a comment to one control or one diagram node rather
than the whole figure. Mark the widget and its parts:

- `data-cm-widget="<name>"` on the widget root. Add `class="cm-skip"` too when the widget is
  interactive (drag/drop, toggles) so its moving text does not perturb text-comment offsets;
  the part layer still attaches to the parts inside it.
- `data-cm-part="<id>"` on each commentable part, with an optional
  `data-cm-part-label="<label>"` (the label defaults to the part's trimmed text).
- `data-cm-slot="<slot>"` on each container that holds parts, when you want layout-change
  tracking (see below).
- `data-cm-draggable` on the widget root or on selected slot containers, when cards should
  move by mouse drag-and-drop. Only direct `data-cm-part` children inside slots are moved.

A labeled SVG node is just a part:
`<g data-cm-part="ingest" data-cm-part-label="Ingest"> ... </g>`.

Each part gets a hover / keyboard **Add Comment** affordance (focus it and press
<kbd>Enter</kbd>). The comment stores `anchorType: "widget"` with the widget name, part id,
and label, and it restores by widget + part across reloads, Copy all, and Export as Portable.
The Copy-all bundle records `Anchor: widget "<name>", part "<label>"`.

```html
<div class="board cm-skip" data-cm-widget="triage" data-cm-draggable>
  <div class="col" data-cm-slot="Now">
    <div class="card" data-cm-part="t-101" data-cm-part-label="Add SSE backpressure">Add SSE backpressure</div>
  </div>
  <div class="col" data-cm-slot="Later"> ... </div>
</div>
```

## Widget layout-change tracking

When parts sit inside `data-cm-slot` containers, the layer snapshots each part's slot at load.
If the user later moves a part to another slot, including by mouse drag-and-drop on a widget or
slot that carries `data-cm-draggable`, the change is surfaced deterministically:

- a synthetic **Layout change** card appears in the sidebar listing every moved part (and the
  panel opens so the change is not missed),
- the change is copied in a **Widget layout changes** section of the Copy-all bundle so the
  agent can reformat the source to match, and
- the document is marked **Not portable** until it is re-exported (the move is not saved into
  the file yet).

Moving every part back to its original slot clears the change and restores portability. The
tracking is a pure function of the current DOM (baseline slot vs current slot), so it never
drifts and needs no persisted state.

## Document-wide comments

For feedback that is not tied to any element, right-click an empty area of the document and
choose **Comment on document**. It stores `anchorType: "document"` with no offsets and no
highlight, shows in the sidebar as a document-wide card (with no jump control), and appears in
the Copy-all bundle as `Anchor: document-wide (not tied to a specific element)`.

Right-clicking a link, image, media element, form control, or an existing comment anchor
leaves the browser's native context menu intact, so their default actions still work. On
touch / coarse-pointer devices the native selection menu is always preserved.
