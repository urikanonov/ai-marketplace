// Shared, browser-free extraction of the "complex syntax" blocks from a CMH
// document: mermaid diagram sources and Chart.js JSON configs. Used by the
// real-parser oracle (validate_render.mjs) and its Playwright spec. Pure string
// work so it can run in Node without a DOM; the actual PARSING is done by the
// real libraries in a browser.

const NAMED = {
  "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'", "&#39;": "'",
  "&nbsp;": " ", "&amp;": "&",
};

export function decodeEntities(s) {
  return String(s)
    .replace(/&#x([0-9a-fA-F]+);/g, (_, h) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(parseInt(d, 10)))
    .replace(/&(?:lt|gt|quot|apos|#39|nbsp|amp);/g, (m) => NAMED[m])
    // decode &amp; last so an entity written as &amp;lt; still resolves once
    .replace(/&amp;/g, "&");
}

// Layer-owned application/json blocks that are NOT chart data.
export const LAYER_JSON_IDS = new Set([
  "handledCommentIds", "embeddedComments", "commentableHtmlLayer",
]);

// <pre class="mermaid"> / <div class="mermaid"> source blocks that have NOT yet
// rendered to <svg>. A rendered block's inner HTML is SVG, not diagram source.
export function extractMermaid(html) {
  const re = /<(pre|div)\b[^>]*\bclass\s*=\s*"[^"]*\bmermaid\b[^"]*"[^>]*>([\s\S]*?)<\/\1\s*>/gi;
  const out = [];
  let m;
  while ((m = re.exec(html)) !== null) {
    const inner = m[2];
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
    const typeM = /\btype\s*=\s*"([^"]*)"/i.exec(attrs);
    if (!typeM || typeM[1].split(";")[0].trim().toLowerCase() !== "application/json") continue;
    const idM = /\bid\s*=\s*"([^"]*)"/i.exec(attrs);
    const id = idM ? idM[1] : null;
    if (id && LAYER_JSON_IDS.has(id)) continue;
    out.push({ id, index: out.length + 1, text: body.trim() });
  }
  return out;
}
