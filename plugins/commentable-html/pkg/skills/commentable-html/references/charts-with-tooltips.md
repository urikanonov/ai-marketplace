# Charts with tooltips

Detailed reference content moved out of `SKILL.md` to keep the core skill under the governance line limit.

## Charts with tooltips

When a commentable report needs real charts with hover tooltips, embed **Chart.js** (canvas based) rather than hand-rolling SVG.

### Default: offline Chart.js

- **Vendor or inline Chart.js by default.** Place `chart.umd.min.js` next to the HTML and load it with a relative `<script src="./vendor/chart.umd.min.js"></script>`, or inline the library when the deliverable must be one file. Keep the loader synchronous and before the chart init.
- **CDN loading is explicit opt-in.** A tag such as `https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js` fetches remote code and breaks the offline/privacy guarantee. If the user explicitly accepts that, pin the full version, add SRI plus `crossorigin="anonymous"`, and keep the init guarded.
- **Guard offline failure.** Wrap chart init with `if (typeof Chart === "undefined") return;` so a missing local file or blocked CDN degrades to a blank canvas rather than throwing.
- **Tooltip libraries follow the same rule.** Chart.js built-in tooltips need no extra library. If a host page deliberately adds an external tooltip library, self-host or inline it by default; CDN use is opt-in and breaks offline operation.

### Markup and comment behavior

- Put the canvas in `figure.chart`. Use a fixed-height `cm-skip` wrapper such as `.chart-wrap` so the text-offset walker ignores chart fallback text, but do **not** put `cm-skip` on the whole figure because the caption and surrounding prose should stay commentable.
- The chart `<canvas>` itself is indexed by the image layer. Hovering or focusing it shows **Add Comment**, and saved comments use `anchorType: "image"` with `imageKind: "chart"`.
- Keep chart data and init scripts outside `#commentRoot`. Inject the chart init before the final `</body>` and after the `END: commentable-html v2 - JS` marker, never after the first textual `</body>` mention in a template comment. `Export to Plain HTML` keeps those host scripts, and `Export as Portable` does not rewrite them.
- Add `role="img"` and a meaningful `aria-label` to each canvas.

### Tooltip recipe

Use Chart.js built-in callbacks:

- `interaction: { mode: "index", intersect: false }` gives one shared tooltip for every series at the hovered x value.
- Format `tooltip.callbacks.title` and `tooltip.callbacks.label` for readable units.
- Use `tooltip.filter: i => i.parsed.y != null` to drop a series where it has a bridged gap.

### Verification

Drive `Chart.getChart(id).tooltip.setActiveElements(...)` and read `tooltip.title` / `tooltip.body`; the tooltip is painted on the canvas, not a DOM node. Serve the file over `http://127.0.0.1:PORT` for automation because `file://` is often blocked.

### Network requirements

The core commentable layer makes no network calls. The only optional external assets a charted report should need are mermaid, Chart.js, and any deliberately added tooltip library. Keep all of them local or inline by default; document any CDN as an explicit opt-in.

