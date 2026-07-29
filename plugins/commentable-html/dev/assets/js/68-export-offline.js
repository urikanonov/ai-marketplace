/* ---------- Export Offline (portable + zero-network rich-content embedding) ---------- */
// Whether a document uses Chart.js is decided on a deliberately LOOSE signal: any mention of the
// `Chart` global. The two failure directions are not symmetric - a false positive inlines a library
// the document did not need (bytes), a false negative ships a chart that never renders - so this
// errs toward inlining, and it also catches indirect construction (`const C = window.Chart;
// new C(...)`, `new (Chart)(...)`, destructuring) that a literal `new Chart(` test would miss. The
// same signal keeps such a script out of the loader strip and hoists it below the inlined library,
// so provisioning and ordering can never disagree. It is read from the document BEFORE any script
// is stripped, so a script the loader strip removes cannot take the evidence with it.
const _OFFLINE_CHART_GLOBAL_RE = /\bChart\b/;
// The narrower "this script CONSTRUCTS a chart" signal. Hoisting is still keyed on it for scripts
// anywhere in the document, because the authoring validator requires chart init to sit after the
// layer's JS region (so Save-as-plain preserves the chart) - and because moving an in-content script
// changes the text offsets the comment anchors are measured against, so the move must stay rare and
// deliberate rather than firing on any mention of the global.
const _OFFLINE_CHART_CTOR_RE = /\bnew\s+(?:Chart|(?:window|globalThis|self)\.Chart)\s*\(/;
// The review layer's own script ships inside every exported document and its source text mentions
// "Chart.js" (the third-party notice it emits), so every content scan must skip it or it matches
// every document. The strip below keeps its historical broad signature (skipping too much there only
// leaves a script alone), but the EVIDENCE scan skips on a much narrower one - the layer's own
// version declaration, plus its position outside the authored content root - because there a wrong
// skip means a dropped library. `__commentableHtmlReady` is a documented public hook and
// `COMMENT_KEY = ` is generic, so an author script may legitimately contain either.
const _OFFLINE_LAYER_SCRIPT_RE = /__commentableHtmlReady|const CMH_VERSION|COMMENT_KEY = /;
const _OFFLINE_LAYER_DECL_RE = /const CMH_VERSION\s*=/;
// A script THIS exporter inlined on an earlier pass, recognized by the marker AND a value the
// exporter itself emits - so an authored script that carries the attribute for its own bookkeeping
// is neither deleted nor excluded from the evidence scan.
function _offlineIsInlinedLibScript(s) {
  const lib = s.getAttribute("data-cmh-offline-lib") || s.getAttribute("data-cmh-offline-lib-init") || "";
  return lib === "chartjs" || lib === "mermaid";
}
// The HTML "JavaScript MIME type" set: a legacy type such as `text/ecmascript` still executes, so a
// content scan that ignored it would miss real code.
function _offlineIsRunnableScriptType(type) {
  const t = String(type || "").split(";")[0].trim().toLowerCase();
  if (!t || t === "module") return true;
  return /^(?:text|application)\/(?:x-)?(?:java|ecma)script$/.test(t) ||
    /^text\/(?:javascript1\.[0-5]|jscript|livescript)$/.test(t);
}
// The MIT notice wording is single-sourced here because THREE places must agree on it byte for
// byte - the emitter, the re-export strip that removes a previous pass's notice, and the capture
// that reads one back. Wording that drifted in one of them used to fail silently: the strip would
// stop pruning (notices accumulate) or the capture would miss (the license is dropped from the
// re-export, breaking the MIT redistribution requirement).
const _OFFLINE_LIB_NOTICE_LEAD = "Third-party notice - ";
const _OFFLINE_LIB_NOTICE_TAIL = " is bundled inline for offline use under the MIT License:";
function _offlineReEscape(s) { return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
const _OFFLINE_LIB_NOTICE_ANY_RE = new RegExp(
  _offlineReEscape(_OFFLINE_LIB_NOTICE_LEAD) + "[^\\n]*" + _offlineReEscape(_OFFLINE_LIB_NOTICE_TAIL));
// Tolerate CRLF: an offline file re-saved by a Windows editor carries `\r\n`, and a notice that no
// longer matched would be silently dropped from the next export rather than travelling with the
// bytes it licenses.
const _OFFLINE_LIB_NOTICE_RE = new RegExp(
  "^\\s*" + _offlineReEscape(_OFFLINE_LIB_NOTICE_LEAD) + "(\\S+)"
  + _offlineReEscape(_OFFLINE_LIB_NOTICE_TAIL) + "\\r?\\n([\\s\\S]*)$");
const _OFFLINE_LIB_NOTICE_KEYS = { "Chart.js": "chartjsLicense", mermaid: "mermaidLicense" };
function _offlineDocFromHtml(html) {
  return new DOMParser().parseFromString(String(html || ""), "text/html");
}
function _serializeOfflineDoc(doc) {
  return "<!DOCTYPE html>\n" + doc.documentElement.outerHTML;
}
function _offlineIsNetworkUrl(v) {
  return /^(?:https?:)?\/\//i.test(String(v || "").trim());
}
function _offlineSrcsetHasNetwork(v) {
  return String(v || "").split(",").some(function (part) {
    return _offlineIsNetworkUrl(part.trim().split(/\s+/)[0]);
  });
}
function _offlineCssNoNetwork(css) {
  return String(css || "")
    .replace(/@import\s+(?:url\()?["']?(?:https?:)?\/\/[^;"')]+["']?\)?\s*;/gi, "")
    .replace(/url\(\s*(["']?)(?:https?:)?\/\/[^)"']+\1\s*\)/gi, 'url("data:,")');
}
function _stripOfflineEventHandlers(doc) {
  doc.querySelectorAll("*").forEach(function (el) {
    Array.from(el.attributes || []).forEach(function (attr) {
      if (/^on/i.test(attr.name || "")) el.removeAttribute(attr.name);
    });
  });
}
function _ensureOfflineCsp(doc) {
  const html = doc.documentElement || doc.querySelector("html");
  let head = doc.head || doc.querySelector("head");
  if (!head) {
    head = doc.createElement("head");
    if (html && html.firstChild) html.insertBefore(head, html.firstChild);
    else if (html) html.appendChild(head);
  }
  if (!head) return;
  doc.querySelectorAll("meta[http-equiv]").forEach(function (m) {
    if ((m.getAttribute("http-equiv") || "").toLowerCase() === "content-security-policy") m.remove();
  });
  const meta = doc.createElement("meta");
  meta.setAttribute("http-equiv", "Content-Security-Policy");
  meta.setAttribute("content", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'");
  head.insertBefore(meta, head.firstChild);
}
function _offlineScriptHasNetworkImport(body) {
  const src = String(body || "");
  return /\bimport\s*\(\s*["'](?:https?:)?\/\//i.test(src) ||
    (/\bimport\s*\(/.test(src) && /["'](?:https?:)?\/\/[^"']*["']/i.test(src)) ||
    /\bfrom\s+["'](?:https?:)?\/\//i.test(src) ||
    /\bimport\s+["'](?:https?:)?\/\//i.test(src);
}
function _stripOfflineNetworkLoads(doc) {
  doc.querySelectorAll("script[src]").forEach(function (s) {
    if (_offlineIsNetworkUrl(s.getAttribute("src"))) s.remove();
  });
  doc.querySelectorAll("script").forEach(function (s) {
    const id = s.getAttribute("id") || "";
    if (/^(?:embeddedComments|handledCommentIds|commentableHtmlLayer|cmhVendoredRichLibs)$/.test(id)) return;
    if (!_offlineIsRunnableScriptType(s.getAttribute("type"))) return;
    const body = s.textContent || "";
    if (_offlineScriptHasNetworkImport(body)) {
      s.remove();
    }
  });
  doc.querySelectorAll("link[href]").forEach(function (link) {
    if (!_offlineIsNetworkUrl(link.getAttribute("href"))) return;
    const rel = (link.getAttribute("rel") || "").toLowerCase().split(/\s+/);
    const loads = ["stylesheet", "preload", "modulepreload", "preconnect", "dns-prefetch", "icon", "apple-touch-icon", "manifest", "prefetch", "prerender"];
    if (rel.some(function (r) { return loads.includes(r); })) link.remove();
  });
  const clearAttr = function (el, attr) {
    if (!el.hasAttribute(attr)) return;
    const value = el.getAttribute(attr) || "";
    const network = attr === "srcset" ? _offlineSrcsetHasNetwork(value) : _offlineIsNetworkUrl(value);
    if (!network) return;
    if (el.tagName === "IMG" && attr === "src") el.setAttribute("src", "data:image/gif;base64,R0lGODlhAQABAAAAACw=");
    else el.removeAttribute(attr);
  };
  doc.querySelectorAll("meta[http-equiv]").forEach(function (m) {
    if ((m.getAttribute("http-equiv") || "").toLowerCase() === "refresh") m.remove();
  });
  doc.querySelectorAll("img").forEach(function (el) { clearAttr(el, "src"); clearAttr(el, "srcset"); });
  doc.querySelectorAll("iframe").forEach(function (el) { clearAttr(el, "src"); });
  doc.querySelectorAll("video").forEach(function (el) { clearAttr(el, "src"); clearAttr(el, "poster"); });
  doc.querySelectorAll("audio").forEach(function (el) { clearAttr(el, "src"); });
  doc.querySelectorAll("source").forEach(function (el) { clearAttr(el, "src"); clearAttr(el, "srcset"); });
  doc.querySelectorAll("track").forEach(function (el) { clearAttr(el, "src"); });
  doc.querySelectorAll("image").forEach(function (el) { clearAttr(el, "href"); clearAttr(el, "xlink:href"); });
  doc.querySelectorAll("use").forEach(function (el) { clearAttr(el, "href"); clearAttr(el, "xlink:href"); });
  doc.querySelectorAll("input[src]").forEach(function (el) {
    if ((el.getAttribute("type") || "").toLowerCase() === "image") clearAttr(el, "src");
  });
  doc.querySelectorAll("form[action]").forEach(function (el) { clearAttr(el, "action"); });
  doc.querySelectorAll("button[formaction], input[formaction]").forEach(function (el) { clearAttr(el, "formaction"); });
  doc.querySelectorAll("object").forEach(function (el) { clearAttr(el, "data"); });
  doc.querySelectorAll("embed").forEach(function (el) { clearAttr(el, "src"); });
  doc.querySelectorAll("[background]").forEach(function (el) { clearAttr(el, "background"); });
  doc.querySelectorAll("style").forEach(function (style) {
    style.textContent = _offlineCssNoNetwork(style.textContent || "");
  });
  doc.querySelectorAll("[style]").forEach(function (el) {
    const next = _offlineCssNoNetwork(el.getAttribute("style") || "");
    if (next) el.setAttribute("style", next);
    else el.removeAttribute("style");
  });
}
function _stripOfflineRichRenderers(doc) {
  // On a re-export of an already-offline document, remove any previously inlined library notice
  // comments so they are re-emitted exactly once (the inlined lib scripts below are stripped and
  // re-added the same way); otherwise each re-export would append another duplicate notice.
  const head = doc.head || doc.querySelector("head");
  if (head) {
    Array.prototype.slice.call(head.childNodes).forEach(function (n) {
      if (n.nodeType === 8 && _OFFLINE_LIB_NOTICE_ANY_RE.test(n.nodeValue || "")) {
        if (n.parentNode) n.parentNode.removeChild(n);
      }
    });
    // Libraries this exporter inlined on a previous pass carry their own marker, so remove them by
    // that marker rather than by recognizing their bundled text: a text heuristic that ever failed
    // would leave a stale 1 MB copy behind and append another on every re-export. The marker VALUE
    // must be one this exporter emits, so an authored element carrying the attribute for its own
    // bookkeeping is never silently deleted from the document.
  }
  doc.querySelectorAll("script[data-cmh-offline-lib], script[data-cmh-offline-lib-init]").forEach(function (s) {
    if (_offlineIsInlinedLibScript(s)) s.remove();
  });
  doc.querySelectorAll("script[src]").forEach(function (s) {
    const src = s.getAttribute("src") || "";
    if (/(^|\/)(?:mermaid(?:\.esm)?(?:\.min)?\.mjs|mermaid(?:\.min)?\.js|chart(?:\.umd)?(?:\.min)?\.js)(?:[?#]|$)/i.test(src) ||
        /\/chart\.js@/i.test(src)) {
      s.remove();
    }
  });
  doc.querySelectorAll("script").forEach(function (s) {
    if (!_offlineIsRunnableScriptType(s.getAttribute("type"))) return;
    const body = s.textContent || "";
    if (_OFFLINE_LAYER_SCRIPT_RE.test(body)) return;
    if (/mermaid/i.test(body) && (/\bimport\s*\(/.test(body) || /\bmermaid\.(?:initialize|run)\b/i.test(body) || /\.run\s*\(/.test(body))) {
      s.remove();
      return;
    }
    // Author code that USES the Chart global is kept: naming a bundle file (in a comment, say) must
    // not delete the very script the inlined library exists for. Only a loader shim - one that names
    // a bundle without using the global, or that disables it - is removed.
    if (/window\.Chart\s*=\s*undefined/i.test(body)) {
      s.remove();
      return;
    }
    if (!_OFFLINE_CHART_GLOBAL_RE.test(body) &&
        /chart(?:\.umd)?(?:\.min)?\.js|chart\.js@/i.test(body)) {
      s.remove();
    }
  });
}
let _offlineVendoredRichLibsPromise = null;
function _offlineLiveDocNeedsRichLibs() {
  return !!root.querySelector(CMH_RICH_CONTENT_SEL);
}
function _ensureOfflineVendoredRichLibsPromise() {
  if (_offlineVendoredRichLibsPromise) return _offlineVendoredRichLibsPromise;
  _offlineVendoredRichLibsPromise = (async function () {
    const el = document.getElementById("cmhVendoredRichLibs");
    if (!el) return {};
    const payload = JSON.parse(el.textContent || "{}");
    return {
      mermaid: await _offlineInflateVendoredScript(payload.mermaidGzipBase64),
      chartjs: await _offlineInflateVendoredScript(payload.chartjsGzipBase64),
      mermaidLicense: String(payload.mermaidLicense || ""),
      chartjsLicense: String(payload.chartjsLicense || ""),
    };
  })();
  return _offlineVendoredRichLibsPromise;
}
async function _offlineInflateVendoredScript(b64) {
  const raw = String(b64 || "").trim();
  if (!raw) return "";
  if (typeof DecompressionStream !== "function") {
    throw new Error("Offline export needs DecompressionStream support to unpack its vendored rich-content bundle.");
  }
  const bytes = Uint8Array.from(atob(raw), function (ch) { return ch.charCodeAt(0); });
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).text();
}
async function _offlineVendoredRichLibs() {
  try { return await _ensureOfflineVendoredRichLibsPromise(); }
  catch (e) { throw new Error("Offline export could not parse the vendored rich-content bundle."); }
}
function _primeOfflineVendoredRichLibs() {
  if (!_offlineLiveDocNeedsRichLibs()) return;
  const warm = function () { _ensureOfflineVendoredRichLibsPromise().catch(function () {}); };
  if (typeof requestIdleCallback === "function") requestIdleCallback(warm, { timeout: 2000 });
  else setTimeout(warm, 0);
}
function _offlineDocUsesMermaid(doc) {
  const docRoot = doc.getElementById("commentRoot") || doc.body;
  return !!(docRoot && docRoot.querySelector(CMH_MERMAID_SEL));
}
function _offlineDocUsesCharts(doc) {
  const docRoot = doc.getElementById("commentRoot") || doc.body;
  return !!(docRoot && docRoot.querySelector(CMH_CHART_CANVAS_SEL));
}
// The chart-canvas selector above is a deliberate SUPERSET of what any one renderer draws, so the
// shape of a canvas is not evidence that Chart.js is needed: a canvas carrying
// data-cmh-chart-points / data-cmh-chart-source is drawn by the runtime's own 2D renderer
// (setupInteractiveCharts) and never calls Chart.js. Decide on evidence instead - a chart canvas the
// built-in renderer will NOT draw, or a surviving script that mentions the `Chart` global - so a
// document whose charts are all built-in does not carry a megabyte of dead library. The superset
// stays load-bearing: an author may attach their own Chart.js to any canvas, including a built-in
// one, and that still wins. Detection is deliberately lopsided - a false positive costs bytes, a
// false negative ships a chart that never renders - so it errs toward inlining. Two shapes are still
// out of its reach, both unchanged from before this decision existed: an author script loaded from a
// relative `src` (its body cannot be read here, and such a document is not self-contained anyway),
// and a chart canvas placed OUTSIDE the content root (the shape gate, and the author-time decision
// about which documents carry the vendored payload at all, are both scoped to that root).
function _offlineDocReferencesChartLib(doc) {
  const docRoot = doc.getElementById("commentRoot");
  return Array.prototype.some.call(doc.querySelectorAll("script:not([src])"), function (s) {
    // The layer's own data blocks carry reviewer text; skip them by id exactly as the network strip
    // does, so a comment quoting "Chart" cannot decide a megabyte.
    if (/^(?:embeddedComments|handledCommentIds|commentableHtmlLayer|cmhVendoredRichLibs|reviewedSections)$/.test(s.getAttribute("id") || "")) return false;
    // A library THIS exporter inlined on an earlier pass is not the author's evidence; counting it
    // would make every re-export re-inline it forever.
    if (_offlineIsInlinedLibScript(s)) return false;
    if (!_offlineIsRunnableScriptType(s.getAttribute("type"))) return false;
    const body = s.textContent || "";
    // Only a script OUTSIDE the authored content root can be the review layer, so an author script
    // that happens to quote the layer's own tokens still counts as evidence.
    if ((!docRoot || !docRoot.contains(s)) && _OFFLINE_LAYER_DECL_RE.test(body)) return false;
    return _OFFLINE_CHART_GLOBAL_RE.test(body);
  });
}
// Mirror the bail conditions of the built-in renderer's own _chartConfig(): data that does not parse,
// or that yields no usable point, draws nothing - so such a canvas is NOT one the built-in renderer
// covers, and the library must still travel.
function _offlineParseChartData(raw) {
  try { return { ok: true, value: JSON.parse(String(raw || "").trim() || "null") }; }
  catch (e) { return { ok: false, value: null }; }
}
function _offlineChartDataUsable(parsed) {
  const points = Array.isArray(parsed) ? parsed : (parsed && parsed.points);
  if (!Array.isArray(points)) return false;
  return points.some(function (point) {
    return point && typeof point.label === "string" && point.label.trim() && Number.isFinite(Number(point.value));
  });
}
function _offlineDocNeedsChartLib(doc, referencesChartLib) {
  if (!_offlineDocUsesCharts(doc)) return false;
  const docRoot = doc.getElementById("commentRoot") || doc.body;
  const canvases = Array.prototype.slice.call(docRoot.querySelectorAll(CMH_CHART_CANVAS_SEL));
  const drawnByRuntime = function (canvas) {
    // Follow _chartConfig's precedence exactly: a resolvable source element WINS - unparseable
    // source JSON makes the renderer give up entirely, and only a source that parses FALSY lets it
    // fall back to the inline points.
    const sourceId = (canvas.getAttribute("data-cmh-chart-source") || "").trim();
    const source = sourceId ? doc.getElementById(sourceId) : null;
    if (source) {
      const parsed = _offlineParseChartData(source.textContent);
      if (!parsed.ok) return false;
      if (parsed.value) return _offlineChartDataUsable(parsed.value);
    }
    const inline = _offlineParseChartData(canvas.getAttribute("data-cmh-chart-points"));
    return inline.ok && _offlineChartDataUsable(inline.value);
  };
  if (!canvases.every(drawnByRuntime)) return true;
  return referencesChartLib === undefined ? _offlineDocReferencesChartLib(doc) : !!referencesChartLib;
}
function _offlineAppendInlineScript(doc, head, code, attrs) {
  const s = doc.createElement("script");
  Object.keys(attrs || {}).forEach(function (name) { s.setAttribute(name, attrs[name]); });
  s.textContent = _escClose(String(code || ""));
  head.appendChild(s);
}
function _offlineAppendLibNotice(doc, head, name, license) {
  // MIT requires the copyright + permission notice to accompany a redistributed copy of the library.
  // The Offline export inlines the library bytes, so emit its notice as an HTML comment beside it.
  // Neutralize any "--" so the comment cannot terminate early or serialize as invalid HTML (the
  // vendored MIT texts have none today; this keeps it safe if an upstream refresh introduces one).
  const text = String(license || "").replace(/-{2,}/g, function (m) { return m.split("").join(" "); });
  if (!text.trim()) return;
  head.appendChild(doc.createComment(
    " " + _OFFLINE_LIB_NOTICE_LEAD + name + _OFFLINE_LIB_NOTICE_TAIL + "\n"
    + text + "\n"));
}
function _offlineHoistChartScripts(doc) {
  const body = doc.body || doc.querySelector("body");
  const head = doc.head || doc.querySelector("head");
  if (!body || !head) return;
  const scripts = Array.from(doc.querySelectorAll("script:not([src])")).filter(function (s) {
    if (_offlineIsInlinedLibScript(s)) return false;
    if (!_offlineIsRunnableScriptType(s.getAttribute("type"))) return false;
    const text = s.textContent || "";
    if (_OFFLINE_LAYER_DECL_RE.test(text)) return false;
    if (_OFFLINE_CHART_CTOR_RE.test(text)) return true;
    // A HEAD script that only references the global still has to move: the library is appended as
    // the head's last child, so anything already in the head would otherwise run before it. Body
    // scripts already run after it, and moving one would shift comment-anchor offsets for nothing.
    return head.contains(s) && _OFFLINE_CHART_GLOBAL_RE.test(text);
  });
  scripts.forEach(function (s) { body.appendChild(s); });
}
function _offlineRemoveVendoredBundleScript(doc) {
  const el = doc.getElementById("cmhVendoredRichLibs");
  if (el) el.remove();
}
// An Offline export CONSUMES the vendored payload and removes it, so the file it produces carries
// the libraries inline and no payload at all. Re-exporting that file therefore has nothing to
// re-inline from - so read the copies already in the document (and the MIT notices beside them)
// BEFORE the strip removes them, and let the strip stay unconditional. Capturing and re-emitting,
// rather than leaving them in place, keeps the strip's exactly-one-copy and ordering guarantees.
//
// Re-emitting a captured script GRANTS IT EXECUTION in the exported file, and the document reaching
// here is UNTRUSTED (it may be hand-authored, or crafted), so the `data-cmh-offline-lib` marker is
// NOT on its own proof that this exporter wrote it. Four provenance gates make an impersonation
// grant no capability the source document did not already have://   1. it sits in <head>, where this exporter appends it and never in the authored content root;
//   2. it carries EXACTLY the attribute shape this exporter emits - the marker and nothing else.
//      That is stricter than enumerating disqualifying attributes and cannot be outflanked by one
//      nobody thought of. It rules out `src` (whose inline text never ran), any `type` (so inert
//      `application/json` / `text/plain` data is never promoted from data to code, and a bare
//      marker means the type was runnable), and - the reason a denylist would have failed -
//      `nomodule`, which every module-supporting browser SKIPS, so its body never ran, yet
//      re-emission drops the attribute and would run it;
//   3. it passes the same network-import check `_stripOfflineNetworkLoads` applies to every other
//      surviving script - capture happens BEFORE the strips and re-emission AFTER, so without this
//      a smuggled remote import would ride straight past a strip that had already run. This is a
//      strip-parity gate, NOT an egress proof: like the strip it only recognizes literal-URL import
//      forms, and the zero-network CSP is what actually enforces no egress. Both vendored bundles
//      are clean under it, so the legitimate path pays nothing;
//   4. its bytes cannot open a script-data escape. A body containing a script start tag (or a
//      script/style end tag) re-serializes into an element the parser does not close where the
//      exporter thinks it does: an HTML comment opener followed by a script start tag puts the
//      re-parse into the script-data-double-escaped state, so the emitted end tag stops closing
//      the element and the rest of the head (including the mermaid init shim) is swallowed into
//      it. `_escClose` neutralizes an end tag but cannot fix that state, so the bytes are rejected
//      instead. The vendored bundles contain none of these sequences (mermaid does contain a bare
//      comment opener, which is harmless on its own - the double-escaped state needs a script
//      start tag too - so the gate deliberately does not look for it). This very comment must
//      therefore avoid spelling those sequences out: doing so swallowed the whole runtime once.
// An adjacent MIT notice is required as well (below), but that is a LICENSING requirement, not
// authentication: the wording is a public constant and a forgery can copy it. The security
// argument rests only on gates 1-4.
//
// THREAT MODEL (deliberate, and the reason this stops here rather than at a pinned hash): these
// gates exist to ensure capture grants NO capability the source document did not already have.
// They close every case where it did - inert data, a MIME-parameter type (`text/javascript;
// charset=utf-8` does not execute: HTML matches the type's essence), or a skipped `nomodule` body
// promoted to code; a `src` script's dead inline text promoted; code carrying a remote import that
// the strip would have deleted being resurrected after the strip ran; and bytes that break the
// document's own parse. What they deliberately do NOT try to prove is that the bytes ARE the
// genuine library: an attacker who authors the document can put arbitrary executable code in a head
// script WITHOUT the marker, and the export preserves benign inline scripts by design
// (CMH-OFFLINE-04), so refusing a marked copy would not take that ability away. Verifying the bytes
// would need a build-pinned digest, and `crypto.subtle` is unavailable in a `file://` document -
// exactly where these exports are opened - so it would also reject every file produced by a
// different exporter version, reintroducing the false-rejection bug this fixes. The zero-network
// CSP remains the backstop for what any preserved script can do.
const _OFFLINE_SCRIPT_DATA_ESCAPE_RE = /<\/?script|<\/style/i;
function _offlineAdjacentLibNotice(script, lib) {
  let n = script.previousSibling;
  while (n && n.nodeType === 3 && !String(n.nodeValue || "").trim()) n = n.previousSibling;
  if (!n || n.nodeType !== 8) return "";
  const m = _OFFLINE_LIB_NOTICE_RE.exec(n.nodeValue || "");
  // Bind the notice to THIS library, and only to the notice immediately before it, so an earlier
  // duplicate or forged comment elsewhere in the head cannot shadow the authentic one. The name
  // is read from an untrusted comment, so look it up as an OWN key - `constructor` / `__proto__`
  // would otherwise resolve to an inherited value.
  if (!m || !Object.prototype.hasOwnProperty.call(_OFFLINE_LIB_NOTICE_KEYS, m[1])) return "";
  if (_OFFLINE_LIB_NOTICE_KEYS[m[1]] !== lib + "License") return "";
  return m[2].replace(/\r?\n$/, "");
}
function _offlineCaptureInlinedRichLibs(doc) {
  const found = { chartjs: "", mermaid: "", chartjsLicense: "", mermaidLicense: "" };
  const head = doc.head || doc.querySelector("head");
  if (!head) return found;
  head.querySelectorAll("script[data-cmh-offline-lib]").forEach(function (s) {
    const lib = s.getAttribute("data-cmh-offline-lib") || "";
    if (lib !== "chartjs" && lib !== "mermaid") return;
    if (s.attributes.length !== 1) return;
    const code = s.textContent || "";
    if (!code.trim() || _offlineScriptHasNetworkImport(code)) return;
    if (_OFFLINE_SCRIPT_DATA_ESCAPE_RE.test(code)) return;
    const license = _offlineAdjacentLibNotice(s, lib);
    // A blank notice would make `_offlineAppendLibNotice` a no-op, redistributing the library with
    // no MIT notice at all, so treat it as no notice.
    if (!license.trim()) return;
    // LAST match wins: this exporter appends the library as the head's last child, so a marker
    // placed earlier must never displace the genuine copy (that would "succeed" with a diagram
    // that never renders).
    found[lib] = code;
    found[lib + "License"] = license;
  });
  return found;
}
async function _offlineInlineRichLibs(doc, referencesChartLib, inlinedLibs) {
  const head = doc.head || doc.querySelector("head");
  if (!head) return;
  const needMermaid = _offlineDocUsesMermaid(doc);
  const needCharts = _offlineDocNeedsChartLib(doc, referencesChartLib);
  if (!needMermaid && !needCharts) {
    _offlineRemoveVendoredBundleScript(doc);
    return;
  }
  const bundle = await _offlineVendoredRichLibs();
  const captured = inlinedLibs || {};
  // The payload wins when it carries the library (a fresh copy of the vendored bytes); the captured
  // copy is the fallback for a document that no longer has a payload.
  const lib = function (key) {
    if (bundle[key]) return { code: bundle[key], license: bundle[key + "License"] || "" };
    return { code: captured[key] || "", license: captured[key + "License"] || "" };
  };
  if (needCharts) {
    const chartjs = lib("chartjs");
    if (!chartjs.code) throw new Error("Offline export is missing the vendored Chart.js bundle.");
    _offlineAppendLibNotice(doc, head, "Chart.js", chartjs.license);
    _offlineAppendInlineScript(doc, head, chartjs.code, { "data-cmh-offline-lib": "chartjs" });
  }
  if (needMermaid) {
    const mermaid = lib("mermaid");
    if (!mermaid.code) throw new Error("Offline export is missing the vendored mermaid bundle.");
    _offlineAppendLibNotice(doc, head, "mermaid", mermaid.license);
    _offlineAppendInlineScript(doc, head, mermaid.code, { "data-cmh-offline-lib": "mermaid" });
    _offlineAppendInlineScript(doc, head,
      "(function(){\n"
      + "  if (!window.mermaid || !window.mermaid.initialize || !window.mermaid.run) return;\n"
      + "  var isHidden = function (el) { return !(el.offsetWidth || el.offsetHeight || el.getClientRects().length); };\n"
      + "  var chain = Promise.resolve();\n"
      + "  var runVisible = function (nodes) {\n"
      + "    if (!nodes.length) return;\n"
      + "    chain = chain.then(function () { var r = window.mermaid.run({ nodes: nodes }); return r && r.catch ? r.catch(function () {}) : r; }, function () {});\n"
      + "  };\n"
      + "  var renderHidden = function (el) {\n"
      + "    if (el.hasAttribute('data-processed')) return;\n"
      + "    chain = chain.then(function () {\n"
      + "      if (el.hasAttribute('data-processed')) return;\n"
      + "      var sandbox = document.createElement('div');\n"
      + "      sandbox.setAttribute('aria-hidden', 'true');\n"
      + "      sandbox.style.cssText = 'position:fixed;left:-99999px;top:0;width:1000px;visibility:hidden;pointer-events:none;';\n"
      + "      var clone = el.cloneNode(true);\n"
      + "      clone.removeAttribute('id');\n"
      + "      clone.removeAttribute('data-processed');\n"
      + "      sandbox.appendChild(clone);\n"
      + "      document.body.appendChild(sandbox);\n"
      + "      var cleanup = function () { if (sandbox.parentNode) sandbox.parentNode.removeChild(sandbox); };\n"
      + "      var ran;\n"
      + "      try { ran = window.mermaid.run({ nodes: [clone] }); } catch (e) { cleanup(); return; }\n"
      + "      return Promise.resolve(ran).then(function () {\n"
      + "        var svg = clone.querySelector('svg');\n"
      + "        if (svg && !el.hasAttribute('data-processed')) {\n"
      + "          el.textContent = '';\n"
      + "          el.appendChild(svg);\n"
      + "          el.setAttribute('data-processed', 'true');\n"
      + "        }\n"
      + "        cleanup();\n"
      + "      }, cleanup);\n"
      + "    }, function () {});\n"
      + "  };\n"
      + "  var run = function () {\n"
      + "    var theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'default';\n"
      + "    var htmlLabels = !document.querySelector('.deck-stage');\n"
      + "    try { window.mermaid.initialize({ startOnLoad: false, theme: theme, securityLevel: 'strict', htmlLabels: htmlLabels, flowchart: { htmlLabels: htmlLabels, curve: 'basis' } }); }\n"
      + "    catch (e) { return; }\n"
      + "    var all = Array.prototype.slice.call(document.querySelectorAll(" + JSON.stringify(CMH_MERMAID_SEL) + "));\n"
      + "    runVisible(all.filter(function (el) { return !el.hasAttribute('data-processed') && !isHidden(el); }));\n"
      + "    all.filter(function (el) { return !el.hasAttribute('data-processed') && isHidden(el); }).forEach(renderHidden);\n"
      + "    window.__cmhMermaidReady = chain;\n"
      + "  };\n"
      + "  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run, { once: true });\n"
      + "  else run();\n"
      + "})();",
      { "data-cmh-offline-lib-init": "mermaid" });
  }
  _offlineRemoveVendoredBundleScript(doc);
}
async function _buildOfflineHtml(portableHtml) {
  const doc = _offlineDocFromHtml(portableHtml);
  // Read the "does this document use Chart.js" evidence BEFORE anything is stripped, so a script the
  // loader strip removes cannot take the only sign of the library with it.
  const referencesChartLib = _offlineDocReferencesChartLib(doc);
  const inlinedRichLibs = _offlineCaptureInlinedRichLibs(doc);
  _stripOfflineRichRenderers(doc);
  _stripOfflineNetworkLoads(doc);
  _stripOfflineEventHandlers(doc);
  _offlineHoistChartScripts(doc);
  await _offlineInlineRichLibs(doc, referencesChartLib, inlinedRichLibs);
  _ensureOfflineCsp(doc);
  return _retargetLayerDescriptor(_serializeOfflineDoc(doc), "offline").replace(/\n{3,}/g, "\n\n");
}
async function saveOffline() {
  let baseHtml;
  try { baseHtml = await _getBaseHtml(); }
  catch (e) { showToast("Could not load base HTML."); return; }
  baseHtml = _applyWidgetLayoutToHtml(baseHtml);
  baseHtml = _applyChecklistStateToHtml(baseHtml);
  baseHtml = _applyNoteStateToHtml(baseHtml);
  baseHtml = _applyReviewStateToHtml(baseHtml);
  baseHtml = _prepareExportHtml(baseHtml);
  const exportComments = _exportableComments();
  let portable;
  try {
    portable = NONPORTABLE_MODE
      ? _buildStandaloneHtml(baseHtml, exportComments)
      : _buildSavedHtml(baseHtml, exportComments);
  } catch (e) { showToast(e.message); return; }
  let text;
  try { text = await _buildOfflineHtml(portable); }
  catch (e) { showToast(e.message); return; }
  const filename = _suggestedOfflineFilename();
  _downloadHtml(text, filename);
  showToast("Downloaded " + filename + " - offline HTML with zero-network mermaid and Chart.js embedded.", { center: true });
}
["btnExportOffline", "btnExportOfflineTop"].forEach(function (id) {
  const b = document.getElementById(id);
  if (b) b.addEventListener("click", saveOffline);
});
_primeOfflineVendoredRichLibs();
