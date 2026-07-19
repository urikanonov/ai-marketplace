/* ---------- Export Offline (portable + zero-network rich-content embedding) ---------- */
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
    const type = (s.getAttribute("type") || "").split(";")[0].trim().toLowerCase();
    if (type && type !== "module" && type !== "text/javascript" && type !== "application/javascript") return;
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
      if (n.nodeType === 8 && /Third-party notice - .* bundled inline for offline use under the MIT License:/.test(n.nodeValue || "")) {
        if (n.parentNode) n.parentNode.removeChild(n);
      }
    });
  }
  doc.querySelectorAll("script[src]").forEach(function (s) {
    const src = s.getAttribute("src") || "";
    if (/(^|\/)(?:mermaid(?:\.esm)?(?:\.min)?\.mjs|mermaid(?:\.min)?\.js|chart(?:\.umd)?(?:\.min)?\.js)(?:[?#]|$)/i.test(src) ||
        /\/chart\.js@/i.test(src)) {
      s.remove();
    }
  });
  doc.querySelectorAll("script").forEach(function (s) {
    const type = (s.getAttribute("type") || "").split(";")[0].trim().toLowerCase();
    if (type && type !== "module" && type !== "text/javascript" && type !== "application/javascript") return;
    const body = s.textContent || "";
    if (/__commentableHtmlReady|const CMH_VERSION|COMMENT_KEY = /.test(body)) return;
    if (/mermaid/i.test(body) && (/\bimport\s*\(/.test(body) || /\bmermaid\.(?:initialize|run)\b/i.test(body) || /\.run\s*\(/.test(body))) {
      s.remove();
      return;
    }
    if (!/\bnew\s+(?:Chart|(?:window|globalThis|self)\.Chart)\s*\(/.test(body) &&
        /chart(?:\.umd)?(?:\.min)?\.js|chart\.js@|window\.Chart\s*=\s*undefined/i.test(body)) {
      s.remove();
    }
  });
}
let _offlineVendoredRichLibsPromise = null;
function _offlineLiveDocNeedsRichLibs() {
  return !!root.querySelector("pre.mermaid, div.mermaid, figure.chart canvas, canvas.cmh-chart");
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
  return !!(docRoot && docRoot.querySelector("pre.mermaid, div.mermaid"));
}
function _offlineDocUsesCharts(doc) {
  const docRoot = doc.getElementById("commentRoot") || doc.body;
  return !!(docRoot && docRoot.querySelector("figure.chart canvas, canvas.cmh-chart"));
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
    " Third-party notice - " + name + " is bundled inline for offline use under the MIT License:\n"
    + text + "\n"));
}
function _offlineHoistChartScripts(doc) {
  const body = doc.body || doc.querySelector("body");
  if (!body) return;
  const scripts = Array.from(doc.querySelectorAll("script")).filter(function (s) {
    const type = (s.getAttribute("type") || "").split(";")[0].trim().toLowerCase();
    if (type && type !== "text/javascript" && type !== "application/javascript") return false;
    return /\bnew\s+(?:Chart|(?:window|globalThis|self)\.Chart)\s*\(/.test(s.textContent || "");
  });
  scripts.forEach(function (s) { body.appendChild(s); });
}
function _offlineRemoveVendoredBundleScript(doc) {
  const el = doc.getElementById("cmhVendoredRichLibs");
  if (el) el.remove();
}
async function _offlineInlineRichLibs(doc) {
  const head = doc.head || doc.querySelector("head");
  if (!head) return;
  const needMermaid = _offlineDocUsesMermaid(doc);
  const needCharts = _offlineDocUsesCharts(doc);
  if (!needMermaid && !needCharts) {
    _offlineRemoveVendoredBundleScript(doc);
    return;
  }
  const bundle = await _offlineVendoredRichLibs();
  if (needCharts) {
    if (!bundle.chartjs) throw new Error("Offline export is missing the vendored Chart.js bundle.");
    _offlineAppendLibNotice(doc, head, "Chart.js", bundle.chartjsLicense);
    _offlineAppendInlineScript(doc, head, bundle.chartjs, { "data-cmh-offline-lib": "chartjs" });
  }
  if (needMermaid) {
    if (!bundle.mermaid) throw new Error("Offline export is missing the vendored mermaid bundle.");
    _offlineAppendLibNotice(doc, head, "mermaid", bundle.mermaidLicense);
    _offlineAppendInlineScript(doc, head, bundle.mermaid, { "data-cmh-offline-lib": "mermaid" });
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
      + "    var all = Array.prototype.slice.call(document.querySelectorAll('pre.mermaid, div.mermaid'));\n"
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
  _stripOfflineRichRenderers(doc);
  _stripOfflineNetworkLoads(doc);
  _stripOfflineEventHandlers(doc);
  _offlineHoistChartScripts(doc);
  await _offlineInlineRichLibs(doc);
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
  showToast("Downloaded " + filename + " - offline HTML with zero-network mermaid and Chart.js embedded.");
}
["btnExportOffline", "btnExportOfflineTop"].forEach(function (id) {
  const b = document.getElementById(id);
  if (b) b.addEventListener("click", saveOffline);
});
_primeOfflineVendoredRichLibs();
