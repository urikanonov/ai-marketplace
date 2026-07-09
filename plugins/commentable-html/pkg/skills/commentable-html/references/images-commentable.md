# Images

Detailed reference content moved out of `SKILL.md` to keep the core skill under the governance line limit.

## Images (commentable)

Any `<img>` inside `#commentRoot` (that is not under a `.cm-skip` element) is commentable. A chart `<canvas>` inside `figure.chart` or carrying `.cmh-chart` is also commentable and is stored as `imageKind: "chart"`. On load `setupImageLayer()` indexes each image or chart canvas in document order (`imageIndex`), makes it keyboard-focusable, and:

1. Hovering an image - or focusing it and pressing <kbd>Enter</kbd> - reveals the floating **Add Comment** button (`#imageAddBtn`) at its top-right (and it stays pinned to the image while scrolling).
2. Clicking it opens the shared composer with the image's `alt` (or a short `src`) pre-filled as the quote.
3. Saving anchors the comment to `(imageIndex)` with the `src` as a fallback key for images, marks the target with `class="cm-img-hl"` (a colored ring) + `data-cid`, and adds a sidebar card pinned `image N` or `chart N`.
4. The ring is restored across reload, and the comment round-trips through **Copy all** (`Anchor: image #N` or `Anchor: chart #N` plus alt/label data) and **Export as Portable** like text, mermaid, and diff comments.

An image or chart is a whole-target anchor: you can leave several comments on the same target (each new **Add Comment** adds one, tracked in `data-cids`), and the ring stays until the last one is deleted. These comments carry no character offsets, so - like mermaid and diff comments - they are skipped by `backfillContext()` and restored by `setupImageLayer()` rather than `restoreHighlights()`.

