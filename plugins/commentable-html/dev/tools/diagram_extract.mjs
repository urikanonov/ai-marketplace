// Shared, browser-free extraction of the "complex syntax" blocks from a CMH
// document: mermaid diagram sources and Chart.js JSON configs. Used by the
// real-parser oracle (validate_render.mjs) and its Playwright spec. Pure string
// work so it can run in Node without a DOM; the actual PARSING is done by the
// real libraries in a browser.

// Single-pass HTML entity decode that mirrors the browser (each entity is decoded
// exactly once; produced characters are not re-scanned), so `&amp;amp;` yields
// `&amp;` just as innerHTML would, not `&`.
const NAMED = { lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ", amp: "&" };

export function decodeEntities(s) {
  return String(s).replace(/&(#x[0-9a-fA-F]+|#\d+|lt|gt|quot|apos|nbsp|amp);/g, (m, e) => {
    if (e[0] === "#") {
      const code = e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : m;
    }
    return NAMED[e] ?? m;
  });
}

// Match a `name="value"` OR `name='value'` attribute; group is the value.
const attrValue = (name) => new RegExp(`\\b${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)')`, "i");

// Layer-owned application/json blocks that are NOT chart data.
export const LAYER_JSON_IDS = new Set([
  "handledCommentIds", "embeddedComments", "commentableHtmlLayer",
]);

// <pre class="mermaid"> / <div class="mermaid"> source blocks that have NOT yet
// rendered to <svg>. A rendered block's inner HTML is SVG, not diagram source.
export function extractMermaid(html) {
  const re = /<(pre|div)\b([^>]*)>([\s\S]*?)<\/\1\s*>/gi;
  const out = [];
  let m;
  while ((m = re.exec(html)) !== null) {
    const attrs = m[2] || "";
    const classM = attrValue("class").exec(attrs);
    const cls = classM ? (classM[1] ?? classM[2] ?? "") : "";
    if (!/(?:^|\s)mermaid(?:\s|$)/.test(cls)) continue;
    const inner = m[3];
    if (/<svg[\s>]/i.test(inner)) continue;
    const src = decodeEntities(inner).trim();
    if (src) out.push({ index: out.length + 1, src });
  }
  return out;
}

// Chart.js configs: <script type="application/json" id="...">{...}</script> whose
// id is not a layer block. Returns the raw JSON text (Chart.js parses it itself).
export function extractCharts(html) {
  const re = /<script\b([^>]*?)>([\s\S]*?)<\/script\s*>/gi;
  const out = [];
  let m;
  while ((m = re.exec(html)) !== null) {
    const attrs = m[1] || "";
    const body = m[2];
    const typeM = attrValue("type").exec(attrs);
    const type = typeM ? (typeM[1] ?? typeM[2] ?? "") : "";
    if (type.split(";")[0].trim().toLowerCase() !== "application/json") continue;
    const idM = attrValue("id").exec(attrs);
    const id = idM ? (idM[1] ?? idM[2] ?? null) : null;
    if (id && LAYER_JSON_IDS.has(id)) continue;
    out.push({ id, index: out.length + 1, text: body.trim() });
  }
  return out;
}
