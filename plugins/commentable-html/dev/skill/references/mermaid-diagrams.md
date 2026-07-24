# Mermaid diagrams

The layer adds structural commenting to rendered mermaid diagrams inside `#commentRoot`. Raw mermaid source stays out of text selection when the host carries `cm-skip`.

## Contents

- [Recommended markup](#recommended-markup)
- [Commentable targets](#commentable-targets)
- [How it behaves at runtime](#how-it-behaves-at-runtime)
- [Diagram width and dense layouts](#diagram-width-and-dense-layouts)
- [A gallery of several diagrams (use `.cmh-diagram-gallery`)](#a-gallery-of-several-diagrams-use-cmh-diagram-gallery)
- [Mermaid loader and CDN-fallback guidance](#mermaid-loader-and-cdn-fallback-guidance)

## Recommended markup

```html
<pre class="mermaid cm-skip">
flowchart TD
 Start --> AsmGate{"ASM machine?"}
 ...
</pre>
```

- **Keep `cm-skip`** on the mermaid element. The mermaid layer attaches independently via the `mermaid` class, while the text-selection layer ignores the raw source.
- **No data attributes required.** Diagrams are indexed in document order; each comment stores `diagramIndex`.
- **Stable identifiers** come from mermaid's `data-id`, a generated id such as `flowchart-AsmGate-3` with the trailing counter stripped, a raw `id:` fallback, or `label:<text>`.

If mermaid source was pasted without `cm-skip`, run `tools/authoring/fix_skip.py` (or finalize with
`--fix-skip`) so raw diagram text is not selected as prose while the rendered diagram remains
structurally commentable.

## Commentable targets

- Flowchart nodes, clusters, and edge labels are commentable.
- Gantt task labels and task bars are commentable. Bars without text use an `id:` key when mermaid emits one.
- Sequence/gantt message text, note text, and loop text are commentable.
- Hovering empty rendered diagram area shows **Comment on diagram** and creates a whole-diagram anchor with `nodeKey: "__diagram__"`.
- Pie slices and actors are readiness signals but are treated as whole-diagram-only for commenting.

## How it behaves at runtime

1. `setupMermaidLayer()` finds each `pre.mermaid` / `div.mermaid`, stamps `class="cm-mermaid-host"` and `data-cm-mermaid-index`, then waits for a rendered SVG when needed.
2. Readiness uses mermaid's processed flag plus rendered SVG markers. Pie slices can make the diagram ready even though they fall through to whole-diagram commenting.
3. Hovering a node-like target shows **Add Comment** pinned to that target. Hovering empty diagram area shows **Comment on diagram** pinned to the diagram.
4. Saving writes an `anchorType: "mermaid"` comment keyed by `(diagramIndex, nodeKey)`, applies `cm-mermaid-hl`, and adds a sidebar card.
5. Highlights restore across reload after mermaid finishes rendering and round-trip through **Copy all**, **Export as Portable**, and handled-id pruning.

## Diagram width and dense layouts

In a normal (non-deck) report, a diagram that does not naturally fill the content column looks small in two distinct ways. The runtime fixes one; authoring fixes the other.

- **Pattern A - an intrinsically narrow diagram (handled automatically).** A linear `flowchart TD` pipeline is tall and thin, so its intrinsic SVG width is well under the column and mermaid's inline `max-width:<intrinsic>px` marooned it in the middle with large horizontal dead space. The runtime now classifies such a host `cmh-diagram-narrow` (symmetric to the existing `cmh-diagram-wide`) and scales the SVG up toward the column, capped at `min(100%, natural * 1.4)` and centered, so no authoring change is needed. Wide diagrams (which scroll) and deck diagrams (which fit their slide) are unaffected.
- **Pattern B - a sparse layout (an authoring choice).** A diagram whose SVG already fills the width but whose NODES are small with large internal gaps cannot be fixed by scaling - the emptiness is inside the viewBox. This is a layout decision, so author it dense:
  - Prefer `flowchart LR` over `flowchart TD` for a linear pipeline: a left-to-right row uses the wide column, where a top-down column is tall and thin (the Pattern A shape).
  - Keep architecture subgraphs dense: lay subgraphs out `LR` with `direction TB` inside each, so the two clusters sit side by side rather than being pushed far apart.
  - Avoid long cross-subgraph edges (for example `-. implemented by .->` spanning the whole diagram) and isolated/orphan nodes; dagre spreads nodes apart to route them, which is exactly what strands nodes and opens the internal gaps.

## A gallery of several diagrams (use `.cmh-diagram-gallery`)

To show SEVERAL diagrams (or figures) side by side, wrap them in a single `<div class="cmh-diagram-gallery">` rather than hand-rolling a grid. Diagrams have wildly different aspect ratios, and the naive layouts all fail on that mix: a plain CSS grid makes every row as tall as its tallest cell, so one tall diagram (a vertical `stateDiagram-v2`) strands its short siblings in dead space (marooning); bounding a cell's height by shrinking the SVG turns a tall-narrow diagram into a thin sliver; and CSS multi-column packs them but is fragile with mermaid's dynamic sizing (it can render tiny/empty diagrams in a real browser).

The shipped helper is robust by construction: a centred FLEX-WRAP of UNIFORM DIAGRAM-HEIGHT, content-HUGGING framed cards. Every diagram is rendered at one fixed HEIGHT with its WIDTH derived from the mermaid viewBox aspect ratio (at its natural, readable size), and each card SHRINKS to hug that width up to a generous cap - so every diagram fills its card in both dimensions: a tall-narrow diagram gets a narrow full-height card, a wide diagram gets a wide card, and a small diagram is scaled UP to the fixed height (never left tiny, marooned, or slivered). (A captioned `<figure>` adds its caption below the diagram, so its TOTAL card height varies with the caption while every card's DIAGRAM stays the same height.) A diagram wider than the cap keeps its full readable height and scrolls horizontally inside its card, instead of being crushed to an unreadable strip. Sizing is pure deterministic CSS anchored on a definite height, so it renders consistently (geometry-identical) across Chromium, Firefox, and WebKit and has no JS-measurement race. On the framed desktop layout the layer's own narrow/wide scale-up is additionally DISABLED for a gallery diagram (it is measurement-timing dependent and rendered diagrams tiny in a real browser). On phones (below the 481px breakpoint) the framing does not apply - the gallery collapses to a single-column flow and a wide diagram keeps the layer's normal wide-scroll handling - and print stacks it one per column at natural size.

```html
<div class="cmh-diagram-gallery">
  <pre class="mermaid cm-skip">flowchart LR
  A --> B --> C</pre>
  <pre class="mermaid cm-skip">stateDiagram-v2
  [*] --> Intake
  Intake --> Done
  Done --> [*]</pre>
  <!-- ...more diagrams... -->
</div>
```

Keep `cm-skip` on gallery diagrams you do not want individually commentable. Do NOT re-create a per-document `.visual-grid`/masonry for a diagram gallery - it is exactly the layout that failed repeatedly; use `.cmh-diagram-gallery`. The gallery is for REPORTS and PLANS; a deck slide has its own diagram-fit sizing (a diagram fills the slide), so do not wrap gallery cards inside a deck slide.

Put diagram CONTAINERS directly inside the gallery: a `<pre class="mermaid">`, a `<div class="mermaid">`, or a `<figure>` is framed as a card (a stray `<table>` or list is left alone, not forced into the layout). To caption a diagram, wrap it in a `<figure>` with a `<figcaption>` - the figure hugs the diagram with the caption centred below (a caption longer than a narrow diagram wraps to a readable, bounded width with the diagram centred above it, rather than either stretching the card to the caption's full length or towering into a tiny-width vertical strip), and if the diagram is wide enough to scroll horizontally the caption stays PINNED in view (it does not scroll off with the diagram) so the label is never lost. This gallery is for DIAGRAMS - put charts (a `figure.chart`) in the separate chart gallery (`.visual-grid`), not here, so each keeps its own framing. Every diagram is shown WHOLE at readable size in a hugging card whose DIAGRAM height is uniform across the row (a captioned figure's total height also includes its caption), so nothing is clipped, slivered, or tiny; a diagram too wide for the card scrolls horizontally at full height rather than being crushed, and an overflowing card is keyboard-focusable so a keyboard-only user can scroll it with the arrow keys. On phones each diagram expands to full width, and print stacks them one per column at natural size. The whole-diagram "Comment on diagram" button is clip-aware, so it stays clamped inside the card.

Because the gallery gives every diagram the SAME fixed height, it suits diagrams of roughly comparable, moderate aspect ratios (the common case: a handful of flowcharts, a state machine, a pie, a gantt). An EXTREME-tall diagram (for example a long vertical flowchart or a many-step sequence with a very high height-to-width ratio) is scaled down to that fixed height and can become small; such a diagram reads better OUTSIDE the gallery, as a normal standalone `<pre class="mermaid">` where the layer lets it take its full height and scroll. Keep gallery members to a sensible aspect; place an oversized one on its own.

## Mermaid loader and CDN-fallback guidance

The skill does **not** load mermaid. The host page must include a mermaid script, and diagrams should render by default. For generated reports, vendor mermaid next to the HTML and import it by relative path:

```html
<script type="module">
 try {
 const m = (await import("./vendor/mermaid.esm.min.mjs")).default;
 const theme = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "default";
 // A deck (a `.deck-stage` document) renders its slides inside a CSS-scaled stage; mermaid's HTML
 // (foreignObject) labels re-flow against that scale and clip, so a deck uses SVG <text> labels
 // (htmlLabels:false). Reports keep the richer HTML labels.
 const htmlLabels = !document.querySelector(".deck-stage");
 m.initialize({ startOnLoad: false, theme, securityLevel: "strict", htmlLabels, flowchart: { htmlLabels, curve: "basis" } });
 if (document.readyState === "loading") {
 document.addEventListener("DOMContentLoaded", () => m.run().catch(() => {}));
 } else {
 m.run().catch(() => {});
 }
 } catch (e) { /* network unavailable or missing vendor file: pre.mermaid stays as source text */ }
</script>
```

If mermaid never renders because network access is unavailable, CSP blocks it, or the source is invalid, the layer no-ops and the `pre.mermaid` block remains readable source text. Do not gate the loader behind `?mermaid=1`; the validator warns because diagrams must render on normal open.

CDN mermaid loading is an explicit opt-in. It executes remote code, so shared files depend on network availability to render the diagram. Use it only when the user accepts that tradeoff; otherwise self-host the module or inline it.

For a zero-network handoff after the page has rendered, use **Export Offline**. It removes the mermaid loader, inlines a vendored mermaid runtime into the exported document, and keeps `data-cmh-md-src` for Markdown export. The reopened offline file renders the diagram again from source, so mermaid comments can still restore their rings and the diagram stays live without any network dependency.
