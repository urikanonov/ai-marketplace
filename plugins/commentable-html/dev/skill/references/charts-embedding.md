# Chart.js embedding and tooltips

Use this reference when adding, fixing, or validating a Chart.js chart inside a Commentable HTML document. It covers dependency choices, the four commenting-layer coexistence rules, the minimal light-theme recipe, tooltip options, and tooltip verification. For per-chart-type variations, data cleanup, and dark-theme palette choices, use [Chart recipes](charts-recipes.md) instead.

## Contents

- [Dependency and portability](#dependency-and-portability)
- [Why Chart.js and not hand-rolled SVG](#why-chartjs-and-not-hand-rolled-svg)
- [Four rules for coexisting with the commenting layer](#four-rules-for-coexisting-with-the-commenting-layer)
- [Minimal copy-paste recipe (light theme)](#minimal-copy-paste-recipe-light-theme)
- [The tooltip options that matter](#the-tooltip-options-that-matter)
- [Verifying the tooltip actually works](#verifying-the-tooltip-actually-works)
- [Pitfalls checklist](#pitfalls-checklist)

## Dependency and portability

`chart_block.py` emits a bounded canvas wrapper and a guarded Chart.js CDN loader by default: it pins the full version, adds SRI plus `crossorigin="anonymous"`, keeps the loader synchronous, and guards init with `if (typeof Chart === "undefined") return;` so blocked loading leaves a blank canvas instead of throwing. Chart.js built-in tooltips need no extra library.

For a fully self-contained / offline file, vendor or inline Chart.js instead: place `chart.umd.min.js` next to the HTML and load it with a relative synchronous `<script src="./vendor/chart.umd.min.js"></script>`, or inline the library when the deliverable must be one file. Prefer this whenever a shared file must render without network access.

If the chart already rendered in the browser, **Export Offline** can also make the handoff file network-free without shipping a companion Chart.js file: it strips the CDN loader and inlines a vendored Chart.js bundle into the downloaded copy only when the document contains chart canvases. The reopened offline file keeps the live `<canvas>` plus its bootstrap script, so tooltips and interactivity still work with zero network.

## Why Chart.js and not hand-rolled SVG

- **Tooltips are free and correct.** `interaction:{mode:'index', intersect:false}` gives a
 single tooltip that reports every series at the hovered x - exactly what "tooltips when
 hovering over points" means for a multi-line chart. Reproducing this by hand in SVG
 (nearest-point search, `getScreenCTM` inverse mapping, a floating div) is fiddly and easy
 to get subtly wrong.
- **Charts stay out of the comment offset math.** The commenting layer anchors text comments by
 character offsets into `#commentRoot.textContent`. The `cm-skip` wrapper (rule 1) excludes the
 whole chart subtree from that offset walker, so a chart never shifts or corrupts existing comment
 offsets. (A bare `<canvas>` usually contributes no text either, but it may carry fallback text
 such as "Your browser does not support canvas", so `cm-skip` on the wrapper is the real guarantee,
 not the canvas element itself.) Inline SVG with `<text>` nodes contributes text and can perturb
 offsets - a further reason to prefer canvas-based Chart.js.
- **One dependency, graceful fallback.** A single local, inline, or explicitly accepted CDN `<script src>` tag. If the loader is blocked or unreachable, the canvas stays blank and the rest of the document, including comments, still works.

## Four rules for coexisting with the commenting layer

1. **Wrap the `<canvas>` (only) in a `cm-skip` container.** Put `class="cm-skip"` on the element that
 directly wraps the `<canvas>` (the `.chart-wrap`), NOT on the whole `<figure>`. `cm-skip` excludes
 its entire subtree from the comment layer, so the text-selection layer ignores the chart pixels while
 the `<figcaption>` and any surrounding prose stay commentable. Putting `cm-skip` on the `<figure>`
 would also swallow the caption, so users could not comment on it.

 ```html
 <figure class="chart">
 <div class="chart-wrap cm-skip"><canvas id="madChart"></canvas></div>
 <figcaption>Hover the plot for exact values on each date.</figcaption>
 </figure>
 ```

2. **Inject chart scripts before the FINAL `</body>`, never the first.** `dist/PORTABLE.html`
 contains an explanatory HTML comment that literally mentions "before `</body>`". A naive
 `html.replace("</body>", init + "</body>", 1)` (or any "replace first occurrence") lands your
 `<script>` **inside that comment**, so `getElementById` returns null and no chart is created -
 with no console error to hint why. Always target the last occurrence:

 ```python
 idx = html.rindex("</body>")
 html = html[:idx] + chart_scripts + html[idx:]
 ```

 Equivalently, paste the chart init `<script>` after the commentable JS region and immediately
 before the closing `</body>` tag by hand. Place the chart scripts **after the
 `END: commentable-html - JS` marker** (still before the final `</body>`): **Export to Plain HTML**
 strips only the commentable regions up to that marker, so chart scripts placed after it
 (host-owned content) survive the plain export and the chart still renders. **Export as Portable** only
 rewrites `<script id="embeddedComments">`, so charts are never touched by it either.

3. **Load Chart.js in `<head>` (or before the init script) with a plain SYNCHRONOUS tag.** Do not
 add `defer`/`async` or `type="module"`: the inline init runs at parse time and would find `Chart`
 still undefined, so it silently no-ops (a permanently blank chart). Keep the CDN tag before the
 init and un-deferred. Prefer a local or inline loader for a self-contained shareable artifact. If CDN loading is explicitly accepted, pin the version and add Subresource Integrity plus `crossorigin`:

 ```html
 <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.js"
 integrity="sha384-FcQlsUOd0TJjROrBxhJdUhXTUgNJQxTMcxZe6nHbaEfFL1zjQ+bq/uRoBQxb0KMo"
 crossorigin="anonymous"></script>
 ```

 (That hash is for `chart.js@4.4.0` UMD - the static `dist/chart.umd.js`, never jsDelivr's on-demand-minified `.min.js`, which must not be used with SRI; regenerate for any other version with
 `curl -s <url> | openssl dgst -sha384 -binary | openssl base64 -A`.) Guard the init with `if (typeof Chart === "undefined") return;` so a network-unavailable, CDN-blocked, or SRI-mismatch load degrades to a blank canvas instead of a thrown error. If the report will be served under a
 Content-Security-Policy (internal wiki, SharePoint, portal), a CDN `<script src>` and the inline
 init/style are blocked unless allowlisted: self-host `chart.umd.min.js` next to the file and move
 the init into an external `.js` (or add a CSP nonce/hash). Opened as a local `file://` there is no
 CSP.

4. **Keep chart data and init OUT of `#commentRoot`.** Put the `<canvas>` inside `#commentRoot`
 (so it appears in the document flow) but keep the `<script id="...Data" type="application/json">`
 payload and the init `<script>` outside `#commentRoot`, near the end of `<body>`. Scripts have
 no rendered text, but keeping them out of the comment root avoids any ambiguity in offset math.

## Minimal copy-paste recipe (light theme)

**In `<head>`** (Chart.js + chart CSS):

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.js"
 integrity="sha384-FcQlsUOd0TJjROrBxhJdUhXTUgNJQxTMcxZe6nHbaEfFL1zjQ+bq/uRoBQxb0KMo"
 crossorigin="anonymous"></script>
<style>
 .chart { margin: 1.2rem 0; padding: 1rem; border: 1px solid #e5e7eb; border-radius: 10px; background: #fff; max-width: 100%; overflow: hidden; }
 .chart .chart-wrap { position: relative; width: 100%; height: 440px; max-height: min(60vh, 480px); overflow: hidden; } /* REQUIRED: bounded wrapper */
 .chart canvas { display: block; width: 100% !important; height: 100% !important; max-width: 100% !important; max-height: 100% !important; }
 .chart figcaption { font-size: .82rem; color: #64748b; margin-top: .5rem; }
</style>
```

The bounded `.chart-wrap` with `position: relative` is required: Chart.js uses
`responsive: true, maintainAspectRatio: false` and sizes the canvas to its parent. Without a
sized parent the canvas collapses to zero or grows unbounded. The canvas rules keep pie and
doughnut charts inside the figure when the report or comments sidebar makes the container narrow.

**Inside `#commentRoot`** (the canvas):

```html
<figure class="chart">
 <div class="chart-wrap cm-skip"><canvas id="madChart" role="img" aria-label="MDE MAD growth line chart"></canvas></div>
 <figcaption>Hover the plot for exact values on each date (both series shown together).</figcaption>
</figure>
```

A `<canvas>` is opaque to screen readers, so give it `role="img"` + a descriptive `aria-label`, and
keep an accessible text alternative nearby (the growth tables in this report serve that purpose).

**Before the final `</body>`** (data + init):

```html
<script id="madChartData" type="application/json">{"labels":["2024-01-01","2024-02-01","2024-03-01"],"raw":[100,110,125],"dash":[100,110,125]}</script>
<script>
(function () {
 var C = JSON.parse(document.getElementById("madChartData").textContent);
 var el = document.getElementById("madChart");
 if (!el || typeof Chart === "undefined") return; // network unavailable / CDN blocked: no-op
 var BLUE = "#2563eb", AMBER = "#d97706", GRID = "#e5e7eb", TXT = "#334155";
 var fmtM = function (v) { return v == null ? "" : (v / 1e6).toFixed(2) + "M"; };
 var fmtDate = function (iso) { // ISO label -> "Nov 28, 2024"
 var d = new Date(iso + "T00:00:00Z");
 return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
 };
 new Chart(el, {
 type: "line",
 data: {
 labels: C.labels,
 datasets: [
 { label: "Raw daily rolling MAD", data: C.raw, borderColor: BLUE,
 backgroundColor: "rgba(37,99,235,.08)", borderWidth: 2, pointRadius: 0,
 pointHoverRadius: 4, tension: 0, spanGaps: true, fill: true, order: 1 },
 { label: "Dashboard-aligned", data: C.dash, borderColor: AMBER,
 backgroundColor: "transparent", borderWidth: 2, pointRadius: 0,
 pointHoverRadius: 4, stepped: true, spanGaps: true, order: 2 }
 ]
 },
 options: {
 responsive: true, maintainAspectRatio: false,
 interaction: { mode: "index", intersect: false }, // KEY: shared multi-series tooltip
 plugins: {
 legend: { labels: { color: TXT, usePointStyle: true, boxWidth: 8 } },
 tooltip: {
 backgroundColor: "#ffffff", borderColor: "#cbd5e1", borderWidth: 1,
 titleColor: "#0f172a", bodyColor: "#0f172a", padding: 10, usePointStyle: true,
 filter: function (item) { return item.parsed.y != null; }, // drop a series that gaps here
 callbacks: {
 title: function (items) { return items.length ? fmtDate(items[0].label) : ""; },
 label: function (ctx) { return ctx.dataset.label + ": " + fmtM(ctx.parsed.y); }
 }
 }
 },
 scales: {
 x: { ticks: { color: TXT, maxTicksLimit: 12, autoSkip: true, maxRotation: 0,
 callback: function (val) { // ISO tick -> "Nov 24"
 var d = new Date(this.getLabelForValue(val) + "T00:00:00Z");
 return d.toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });
 } },
 grid: { color: GRID } },
 y: { suggestedMin: 100000000, // floor so growth is not flattened; expands if data dips below
 ticks: { color: TXT, callback: function (v) { return (v / 1e6).toFixed(0) + "M"; } },
 grid: { color: GRID }, title: { display: true, text: "Monthly active devices", color: TXT } }
 }
 }
 });
})();
</script>
```

## The tooltip options that matter

- **`interaction: { mode: "index", intersect: false }`** is what makes hovering anywhere over an
 x-position show all series at that x, without needing to land exactly on a point. For a single
 series this still gives a nearest-x tooltip. This is almost always what a user means by "add
 tooltips".
- **`callbacks.title(items)`** formats the header (e.g., turn an ISO date label into "Nov 28, 2024").
- **`callbacks.label(ctx)`** formats each row: `ctx.dataset.label + ": " + fmt(ctx.parsed.y)`. Use
 `ctx.parsed.y` (or `ctx.parsed.x` on a horizontal chart) and `ctx.dataset.label`. Format big
 numbers with `.toLocaleString("en-US")` or a unit suffix (K/M/B/GB).
- **`tooltip.filter: item => item.parsed.y != null`** drops a series from the tooltip where it has a
 gap (a nulled/bridged point), so the row and its colour swatch disappear entirely. This is the
 documented, clean way to omit a series: returning `""` from `label` leaves an empty coloured row,
 and returning `null` is undocumented (use `filter` instead).
- **`pointRadius: 0` with `pointHoverRadius: 4`** hides the dots on a dense line but still shows a
 marker under the cursor.
- **`usePointStyle: true`** on legend and tooltip draws small circles instead of boxes.

## Verifying the tooltip actually works

Chart.js draws its tooltip **onto the canvas**, not as a DOM element, so you cannot assert on a
tooltip `<div>`. Two reliable checks:

1. **Programmatic (headless, deterministic).** Load the file over `http://` (many browsers block
 `file://` automation), then drive the tooltip and read it back:

 ```js
 const c = Chart.getChart("madChart");
 c.tooltip.setActiveElements([{datasetIndex:0,index:600},{datasetIndex:1,index:600}], {x:100,y:100});
 c.update();
 // c.tooltip.title -> ["Sep 24, 2025"]
 // c.tooltip.body.map(b => b.lines) -> [["Raw daily rolling MAD: 136.27M"], ["Dashboard-aligned: 136.60M"]]
 ```

 This confirms the label/title callbacks and the tooltip body shape in one shot. Note it does NOT
 prove `interaction.mode:"index"` is set: `setActiveElements` manually injects both dataset points,
 so the multi-series tooltip appears even if index-mode is missing. To verify index-mode itself, use
 a real `mousemove` (below) or `chart.getElementsAtEventForMode(evt, "index", {intersect:false})`
 and assert it returns one element per dataset.
 Also assert `Chart.getChart(id)` is truthy - a falsy/undefined result means the chart was never
 created. Triage in order: the `<script id="...Data">` element exists, its JSON parses, the
 `<canvas>` exists, and the Chart.js CDN tag loaded before the init (the most common cause is the
 init landing inside the template comment via a first-`</body>` replace, per rule 2).

2. **Visual.** Dispatch a real `mousemove` over the canvas (or use the automation tool's mouse move)
 and screenshot; the tooltip is painted on the canvas so it shows up in the image.

A quick sanity assert set: `Chart.version` is defined, `Chart.getChart(id)` is truthy, dataset count
and point count match the source, and `c.scales.y.min` is the floor you set.

3. **Automated (static, no browser).** Run `python tools/validate/validate.py <file.html>` (ships with this
 skill, standard library only). It always checks the commentable layer and, when the document has a
 `<canvas>`, also checks the chart rules above statically: `cm-skip` on the canvas wrapper (not the
 `<figure>`, so captions stay commentable), an SRI-pinned synchronous Chart.js CDN tag, valid
 non-empty chart-data JSON with no `</script>` / `<!--` breakout, chart init after the
 `END: commentable-html - JS` marker and after the Chart.js loader, and canvas `role`/`aria-label`
 + the `typeof Chart` network-failure guard. Use `--charts-only` to run just the chart checks.

## Pitfalls checklist

- Init `<script>` landed inside the template's explanatory comment because you replaced the first
 `</body>`. Use `rindex` / the last occurrence, and place chart scripts after the
 `END: commentable-html - JS` marker. (Symptom: blank canvas, no console error,
 `Chart.getChart(id)` falsy.)
- Added `defer`/`async`/`type="module"` to the CDN tag -> the inline init runs before `Chart` exists
 and silently no-ops. Keep the CDN tag synchronous and before the init (or wrap the init in a
 `DOMContentLoaded` listener and load Chart.js with `defer`).
- No bounded `.chart-wrap` -> canvas has zero or runaway height, especially for pie and doughnut charts in narrow containers.
- Forgot `cm-skip` on the chart wrapper (or put it on the whole `<figure>`) -> either the chart pixels
 catch comment selections, or (if on the figure) the `<figcaption>` becomes uncommentable. Put it on the
 `.chart-wrap` that directly wraps the `<canvas>`.
- Zero-based y-axis flattened the trend -> `suggestedMin`. A hard `min` clips real values below the
 floor - prefer `suggestedMin`.
- Glitch day spiking to the axis floor -> null it and `spanGaps: true`; filter every shared series,
 but do not delete a real dip you have not explained.
- String labels containing `</script>` in the JSON block -> escape `<` as `\u003C` when serializing;
 never hand-build the JSON.
- Thousands of points feeling sluggish -> enable the built-in decimation plugin
 (`options.plugins.decimation = { enabled: true, algorithm: "lttb" }`, with `parsing: false` and
 indexed data) and keep `pointRadius: 0`. Note decimation only runs on a `linear` or `time` x-axis,
 NOT on a `category` axis (the ISO-string recipe above uses a category axis, so decimation no-ops
 there); for large series either switch to a `time` scale (`chartjs-adapter-date-fns`) or rely on
 `pointRadius: 0` + `autoSkip`/`maxTicksLimit`.
- Asserting on a tooltip DOM node -> there is none; drive `chart.tooltip` or screenshot the canvas.
- Loaded the file via `file://` for automation and it was blocked -> serve the folder over
 `http://127.0.0.1:PORT` (e.g. `python -m http.server 8791`) and navigate there.
