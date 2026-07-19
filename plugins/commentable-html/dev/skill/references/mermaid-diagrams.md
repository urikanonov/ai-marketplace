# Mermaid diagrams


## Mermaid diagrams

The layer adds structural commenting to rendered mermaid diagrams inside `#commentRoot`. Raw mermaid source stays out of text selection when the host carries `cm-skip`.

### Recommended markup

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

### Commentable targets

- Flowchart nodes, clusters, and edge labels are commentable.
- Gantt task labels and task bars are commentable. Bars without text use an `id:` key when mermaid emits one.
- Sequence/gantt message text, note text, and loop text are commentable.
- Hovering empty rendered diagram area shows **Comment on diagram** and creates a whole-diagram anchor with `nodeKey: "__diagram__"`.
- Pie slices and actors are readiness signals but are treated as whole-diagram-only for commenting.

### How it behaves at runtime

1. `setupMermaidLayer()` finds each `pre.mermaid` / `div.mermaid`, stamps `class="cm-mermaid-host"` and `data-cm-mermaid-index`, then waits for a rendered SVG when needed.
2. Readiness uses mermaid's processed flag plus rendered SVG markers. Pie slices can make the diagram ready even though they fall through to whole-diagram commenting.
3. Hovering a node-like target shows **Add Comment** pinned to that target. Hovering empty diagram area shows **Comment on diagram** pinned to the diagram.
4. Saving writes an `anchorType: "mermaid"` comment keyed by `(diagramIndex, nodeKey)`, applies `cm-mermaid-hl`, and adds a sidebar card.
5. Highlights restore across reload after mermaid finishes rendering and round-trip through **Copy all**, **Export as Portable**, and handled-id pruning.

### Mermaid loader and CDN-fallback guidance

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
