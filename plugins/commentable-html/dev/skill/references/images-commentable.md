# Images


## Images (commentable)

Any `<img>` inside `#commentRoot` (that is not under a `.cm-skip` element) is commentable. A chart `<canvas>` inside `figure.chart` or carrying `.cmh-chart` is also commentable and is stored as `imageKind: "chart"`. An authored inline `<svg>` figure is commentable too (see "Inline SVG figures" below). On load `setupImageLayer()` indexes each image, chart canvas or inline svg in document order (`imageIndex`), makes it keyboard-focusable, and:

1. Hovering an image - or focusing it and pressing <kbd>Enter</kbd> - reveals the floating **Add Comment** button (`#imageAddBtn`) at its top-right (and it stays pinned to the image while scrolling).
2. Clicking it opens the shared composer with the image's `alt` (or a short `src`) pre-filled as the quote.
3. Saving anchors the comment to `(imageIndex)` with the `src` as a fallback key for images, marks the target with `class="cm-img-hl"` (a colored ring) + `data-cid`, and adds a sidebar card pinned `image N` or `chart N`.
4. The ring is restored across reload, and the comment round-trips through **Copy all** (`Anchor: image #N` or `Anchor: chart #N` plus alt/label data) and **Export as Portable** like text, mermaid, and diff comments.

An image or chart is a whole-target anchor: you can leave several comments on the same target (each new **Add Comment** adds one, tracked in `data-cids`), and the ring stays until the last one is deleted. These comments carry no character offsets, so - like mermaid and diff comments - they are skipped by `backfillContext()` and restored by `setupImageLayer()` rather than `restoreHighlights()`.

## Inline SVG figures (commentable)

An authored inline `<svg>` in `#commentRoot` is commentable media exactly like an `<img>`: it is indexed with the other media, made focusable, reveals the same floating **Add Comment** button on hover or <kbd>Enter</kbd>, and stores an `anchorType: "image"` comment. Its quote and `imageAlt` come from the svg's `aria-label`, falling back to a DIRECT-CHILD `<title>` (only a direct child names the svg, so a figure never borrows a nested shape's tooltip). ALWAYS give a commentable graphic one of those: the label is the only metadata an svg anchor has (it has no `src`), so an unlabeled graphic can only be found again by its position. A graphic with neither is still commentable and quotes `image N`; the layer then adds an affordance `aria-label` so it is not a nameless focus stop, and marks that synthesized label (`data-cm-img-auto-label="1"`) so it never becomes anchor metadata. The layer adds `role="img"` when the svg has no role, and never rewrites an author's `aria-label` or `<title>`.

Author a commentable graphic as a plain figure:

```html
<figure aria-labelledby="headroom-cap">
  <svg viewBox="0 0 620 160" role="img" aria-label="Capacity headroom by region"> ... </svg>
  <figcaption id="headroom-cap">Capacity headroom by region.</figcaption>
</figure>
```

An svg placed directly inside `figure.chart` (or carrying `.cmh-chart`) is chart media like any other media there, so it is stored as `imageKind: "chart"` and pinned `chart N`. Note that the chart block the skill emits wraps its drawing surface in `<div class="chart-wrap cm-skip">`, and `.cm-skip` is UNCONDITIONAL for svg: an svg inside that wrapper is NOT commentable. Put a hand-drawn chart svg directly in the `figure.chart` (outside any `.cm-skip`) when you want it to be a comment target.

SVG that another layer or the runtime owns stays inert, so these are NOT given an image affordance:

- anything under `.cm-skip` (UI chrome - unconditionally, even inside a chart figure) and any rendered mermaid (`.cm-mermaid-host`) or diff (`.cmh-diff-host`) surface - mermaid nodes and diff lines have their own anchors;
- a decorative graphic: one under an `aria-hidden="true"` element (the svg itself or any ancestor - the common wrapper idiom) or marked `role="presentation"` / `role="none"`;
- an icon inside an `<a href>`, `<button>`, `<summary>`, `<label>`, `[role="button"]` or `[role="link"]`;
- a definitions-only sprite sheet: an svg whose children are all non-drawing (`<defs>`, `<symbol>`, `<style>`, `<title>`, `<desc>`, `<metadata>`, gradients, filters, masks, patterns), or one with `width="0"` / `height="0"` / an inline `display:none`;
- an svg that carries or contains `[data-cm-part]` INSIDE a `[data-cm-widget]` (the widget layer makes those nodes individually commentable - see [Commentable widgets](commentable-widgets.md)); a stray `[data-cm-part]` with no widget ancestor is owned by neither layer, so the whole figure stays commentable;
- an inner `<svg>` nested inside another `<svg>`; the outermost element is the figure a reader means.

Two notes on stability. Media are indexed ONCE at load, so a graphic that is inline-`display:none`
or `hidden` at load time is skipped for good even if a script later reveals it. And because inline
SVG now joins the same media index as images and chart canvases, `imageIndex` numbering shifts in a
document that gains one: labelled media re-anchors through its stored label, so ALWAYS label a
commentable graphic (and an unlabelled chart `<canvas>` too, with `aria-label`).

