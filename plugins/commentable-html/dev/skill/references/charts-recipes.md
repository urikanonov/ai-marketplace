# Chart.js recipes, data hygiene, and themes

Use this reference after the chart is embedded correctly and you need a chart-type recipe, data cleanup guidance, or dark-theme palette guidance. For dependencies, Commentable HTML coexistence rules, the minimal wrapper, and tooltip callbacks, use [Chart embedding and tooltips](charts-embedding.md) instead.

## Contents

- [Chart-type recipes (from the sample report)](#chart-type-recipes-from-the-sample-report)
- [Data hygiene](#data-hygiene)
- [Dark theme](#dark-theme)

## Chart-type recipes (from the sample report)

Define a shared `baseOpts` once and spread it (`{...baseOpts}`) into each chart:

```js
var TXT = "#334155", GRID = "#e5e7eb";
var baseOpts = {
 responsive: true, maintainAspectRatio: false,
 interaction: { mode: "index", intersect: false },
 plugins: { legend: { labels: { color: TXT, usePointStyle: true, boxWidth: 8 } },
 tooltip: { backgroundColor: "#ffffff", borderColor: "#cbd5e1", borderWidth: 1,
 titleColor: "#0f172a", bodyColor: "#0f172a", usePointStyle: true } },
 scales: { x: { ticks: { color: TXT }, grid: { color: GRID } },
 y: { ticks: { color: TXT }, grid: { color: GRID } } }
};
```

**Time-series line, multi-series, shared tooltip** - the recipe above. For a date axis with many
points, use a category x-axis of ISO date strings plus `maxTicksLimit` + `autoSkip`, and a tick
`callback` that reformats to "Mon YY". This avoids pulling in a date-adapter dependency.

**Grouped bar comparison:**

```js
new Chart(el, { type: "bar",
 data: { labels: ["Mar 23","Jun 8","Jun 15"], datasets: [
 { label: "Avg (ms)", data: [126,122,122], backgroundColor: "#2563eb" },
 { label: "P95 (ms)", data: [181,175,175], backgroundColor: "#d97706" } ] },
 options: { ...baseOpts, scales: { ...baseOpts.scales,
 y: { ...baseOpts.scales.y, title: { display: true, text: "ms" } } } } });
```

**Horizontal funnel / ranking:** set `indexAxis: "y"`, `plugins: { legend: { display: false } }`
(legend config lives under `plugins`, not at the top level), and
`interaction: { mode: "index", intersect: false, axis: "y" }` - with a horizontal bar the index axis
is y, so without `axis: "y"` the shared tooltip targets the wrong row. Read the value from
`ctx.parsed.x` (not `.y`) in the tooltip/label callback, and use `tooltip.filter: i => i.parsed.x != null`.

**Dual axis (two different units):** give each dataset a `yAxisID` and define `y` with
`position: "left"` and `y1` with `position: "right"` (a y scale defaults to the left, so `y1` must
set `position: "right"` explicitly or both axes stack on the left). Put `grid: { drawOnChartArea:
false }` on `y1` so the gridlines do not double up. Use per-axis tick `callback`s to format each unit
(for example GB on the left, count on the right). To mix a bar series and a line series on the two
axes (a common cost-vs-count view), set `type: "bar"` at the chart level and override `type` per
dataset:

```js
new Chart(el, { type: "bar", data: { labels, datasets: [
 { type: "bar", label: "COGS ($/mo)", data: cogs, yAxisID: "y1", backgroundColor: "#05966933", borderColor: "#059669", borderWidth: 1 },
 { type: "line", label: "MAD (devices)", data: mad, yAxisID: "y", borderColor: "#2563eb", borderWidth: 2, pointRadius: 0, tension: 0.25 } ] },
 options: { ...baseOpts, scales: { x: baseOpts.scales.x,
 y: { position: "left", ticks: { color: "#2563eb" }, title: { display: true, text: "Devices", color: "#2563eb" } },
 y1: { position: "right", grid: { drawOnChartArea: false }, ticks: { color: "#059669" }, title: { display: true, text: "COGS ($/mo)", color: "#059669" } } } } });
```

**Logarithmic axis** (values spanning orders of magnitude): `y: { type: "logarithmic", ticks: {
callback: v => Number(v).toLocaleString("en-US") } }`. A logarithmic scale cannot render `0` or
negative values - null them (or replace with a small positive floor) first, or the points vanish and
the axis can misbehave.

**Stacked bars:** set `stacked: true` on both `x` and `y` scales and give every dataset in the group
the same `stack` value (any string, e.g. `stack: "cogs"` - the value is arbitrary but must match
across the datasets you want stacked together); a `mode:"index"` tooltip then lists each stacked
segment. For a many-series stack, add `tooltip.itemSort: (a, b) => b.parsed.y - a.parsed.y` to order
the tooltip rows by value (largest first) and `tooltip.filter: i => i.parsed.y > 0` to hide zero
segments.

**Value labels on bars** (a small custom plugin, drawn after datasets):

```js
const valueLabelPlugin = { id: "valueLabel", afterDatasetsDraw(chart) {
 const { ctx } = chart;
 chart.data.datasets.forEach((ds, di) => chart.getDatasetMeta(di).data.forEach((bar, i) => {
 const v = ds.data[i]; if (v == null) return;
 ctx.save(); ctx.fillStyle = "#334155"; ctx.font = "11px system-ui"; ctx.textAlign = "center";
 ctx.fillText(v.toLocaleString("en-US"), bar.x, bar.y - 6); ctx.restore();
 }));
} };
new Chart(el, { type: "bar", data: {...}, options: {...}, plugins: [valueLabelPlugin] });
```

## Data hygiene

- **Filter obvious collection glitches, then bridge - but do not hide real drops.** Real rolling
 metrics do not fall to a fraction of normal for a day, so nulling a point below, say, 85% of a
 local (15-day) median plus `spanGaps: true` cleans up ingestion glitches. Apply the same filter to
 every series that shares the source. Caveat: a blind statistical filter also erases *legitimate*
 dips (holidays, weekends, real outages). Only filter values you have confirmed are collection
 artifacts (they crater then immediately bounce back to trend); never smooth away a drop you have
 not explained, and prefer to annotate a real dip rather than delete it.
- **It is fine to start the y-axis at a value relevant to the data, not zero.** When the interesting
 range sits far above zero (a 108M -> 145M device curve, a cost band that never approaches 0), a
 zero-based axis flattens the trend into a near-flat line and hides the story. Starting the axis near
 the data is a legitimate, encouraged choice for these charts. Prefer **`suggestedMin`** over a hard
 `min`: a hard `min` *clips* any point that legitimately falls below it (hiding a real problem off the
 bottom of the canvas), whereas `suggestedMin` keeps the floor when data stays above it and expands
 downward when a value dips below, so a real drop stays visible. When two axes on the same chart use
 different zero policies (e.g. a truncated device axis next to a zero-based cost axis), that is
 acceptable, but say so in the figcaption if the visual contrast could be read as exaggeration.
- **Embed the data safely in a `<script type="application/json">` block.** Parse it once with
 `JSON.parse(el.textContent)`. Numeric/date payloads are inert, but any *string* value (series
 names, category labels, tooltip text) can contain a literal `</script>` (or `<!--`) that terminates
 the block early and injects markup. So: never hand-build the JSON, always serialize with an
 encoder, and escape `<` before embedding - e.g. in Python `json.dumps(data).replace("<", "\\u003C")`
 (equivalently replace `</` with `<\/`). Chart.js draws tooltip/label callback return values onto
 the canvas as text, not HTML, so those are not an XSS surface; the raw JSON embedding is. If you
 build a custom `external` HTML tooltip, sanitize its content yourself.
- **The data travels with the file.** The JSON payload is plaintext inside the HTML, and the
 commentable **Export as Portable** button lets the file (data included) be shared. Treat chart data like
 any other content in the report: redact, aggregate, or anonymize sensitive/internal metrics before
 sharing, and use synthetic data in public examples.

## Dark theme

The reference report this recipe is drawn from is dark-themed. To switch, set the Chart.js globals
once and use dark palette values:

```js
Chart.defaults.color = "#8b949e"; // muted tick/label text
Chart.defaults.borderColor = "#30363d"; // grid
// tooltip: { backgroundColor: "#0d1117", borderColor: "#30363d", borderWidth: 1, titleColor: "#e6edf3", bodyColor: "#e6edf3" }
```

Default to light unless the surrounding document or an explicit request is dark. If the commentable
document supports a theme toggle, read `document.documentElement.dataset.theme` and pick the palette
at init; note that Chart.js does not re-theme a rendered chart, so a live theme switch needs a chart
`destroy()` + re-create or a page reload.
