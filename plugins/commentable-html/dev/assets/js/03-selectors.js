/* ---------- Shared content selectors ----------
   ONE definition of the rich-content shapes the runtime recognises. The live chart renderer and
   the image comment layer (30-images.js) and the Offline exporter (68-export-offline.js) all
   derive their queries from these constants, and the author-time payload detector
   (tools/authoring/vendored_libs.py) pins its own list to them, so they can no longer drift into
   disagreeing about what a chart is - which is how a bare data-bearing canvas came to draw on a
   window resize but not at load, and to be missed entirely by the exporter (issue #740). */
const CMH_MERMAID_SEL = "pre.mermaid, div.mermaid";
// The authored "this is a chart" markers. They are matched as ancestor-or-self on any media
// element, because an <img> inside a chart figure is chart media too, not only a canvas.
const CMH_CHART_FIGURE_SEL = "figure.chart";
const CMH_CHART_MARK_SEL = ".cmh-chart";
// A canvas the BUILT-IN chart renderer draws: it carries its points inline or by source id.
const CMH_CHART_DATA_SEL = "canvas[data-cmh-chart-points], canvas[data-cmh-chart-source]";
// Every canvas the runtime treats as a chart. A strict superset of CMH_CHART_DATA_SEL, because an
// authored `figure.chart` / `.cmh-chart` canvas may instead be drawn by the document's own Chart.js,
// which the Offline export has to inline. Keeping it a superset by CONSTRUCTION is the invariant:
// anything the renderer draws is something the exporter provisions for.
const CMH_CHART_CANVAS_SEL =
  CMH_CHART_FIGURE_SEL + " canvas, canvas" + CMH_CHART_MARK_SEL + ", " + CMH_CHART_DATA_SEL;
const CMH_RICH_CONTENT_SEL = CMH_MERMAID_SEL + ", " + CMH_CHART_CANVAS_SEL;
