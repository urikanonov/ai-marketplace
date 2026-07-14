/* ---------- Export Offline (portable + rendered rich-content snapshots) ---------- */
function _offlineDocFromHtml(html) {
  return new DOMParser().parseFromString(String(html || ""), "text/html");
}
function _serializeOfflineDoc(doc) {
  return "<!DOCTYPE html>\n" + doc.documentElement.outerHTML;
}
function _offlineTemplateNode(doc, html) {
  const tpl = doc.createElement("template");
  tpl.innerHTML = String(html || "").trim();
  return tpl.content.firstElementChild;
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
    if (/^(?:embeddedComments|handledCommentIds|commentableHtmlLayer)$/.test(id)) return;
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
  const offlineChartIds = Array.from(doc.querySelectorAll("[data-cm-offline-chart][id]"))
    .map(function (el) { return el.getAttribute("id") || ""; })
    .filter(Boolean);
  const referencesOfflineChart = function (body) {
    return /\b(?:cmh-chart|figure\.chart|data-cm-offline-chart)\b/i.test(body) ||
      offlineChartIds.some(function (id) { return new RegExp(_cmhEscapeRegExp(id)).test(body); });
  };
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
    if (/mermaid/i.test(body) && (/\bimport\s*\(/.test(body) || /\bmermaid\.(?:initialize|run)\b/i.test(body) || /\.run\s*\(/.test(body))) {
      s.remove();
      return;
    }
    if (/\bnew\s+(?:Chart|(?:window|globalThis|self)\.Chart)\s*\(/.test(body) ||
        (/\.getContext\s*\(/.test(body) && referencesOfflineChart(body))) {
      s.remove();
    }
  });
}
function _offlineMermaidSnapshots() {
  return Array.from(root.querySelectorAll("pre.mermaid, div.mermaid")).map(function (host) {
    if (!host.querySelector("svg")) {
      throw new Error("Offline export needs mermaid diagrams to finish rendering first.");
    }
    const clone = host.cloneNode(true);
    clone.classList.add("cm-skip");
    clone.setAttribute("data-processed", "true");
    const src = host.getAttribute("data-cmh-md-src");
    if (src && !clone.hasAttribute("data-cmh-md-src")) clone.setAttribute("data-cmh-md-src", src);
    return clone.outerHTML;
  });
}
function _replaceOfflineMermaid(doc, snapshots) {
  const docRoot = doc.getElementById("commentRoot") || doc.body;
  const targets = Array.from(docRoot.querySelectorAll("pre.mermaid, div.mermaid"));
  if (targets.length !== snapshots.length) {
    throw new Error("Offline export could not match every mermaid diagram in the source HTML.");
  }
  targets.forEach(function (target, i) {
    const next = _offlineTemplateNode(doc, snapshots[i]);
    if (!next) throw new Error("Offline export could not serialize a rendered mermaid diagram.");
    target.replaceWith(next);
  });
}
function _offlineChartSnapshots() {
  return Array.from(root.querySelectorAll("figure.chart canvas, canvas.cmh-chart")).map(function (canvas) {
    let src = "";
    try { src = canvas.toDataURL("image/png"); }
    catch (e) { throw new Error("Offline export could not snapshot a chart canvas. It may contain cross-origin pixels."); }
    if (!/^data:image\/png;base64,/i.test(src)) {
      throw new Error("Offline export could not snapshot a chart canvas as PNG.");
    }
    const rect = canvas.getBoundingClientRect();
    const rawClass = (canvas.getAttribute("class") || "").split(/\s+/)
      .filter(function (c) { return c && !/^cm-img-/.test(c); });
    if (!rawClass.includes("cmh-chart")) rawClass.push("cmh-chart");
    return {
      id: canvas.getAttribute("id") || "",
      src,
      alt: (canvas.getAttribute("aria-label") || canvas.getAttribute("alt") || "Chart snapshot").trim() || "Chart snapshot",
      width: canvas.getAttribute("width") || String(canvas.width || Math.max(1, Math.round(rect.width))),
      height: canvas.getAttribute("height") || String(canvas.height || Math.max(1, Math.round(rect.height))),
      className: rawClass.join(" "),
    };
  });
}
function _replaceOfflineCharts(doc, snapshots) {
  const docRoot = doc.getElementById("commentRoot") || doc.body;
  const targets = Array.from(docRoot.querySelectorAll("figure.chart canvas, canvas.cmh-chart"));
  if (targets.length !== snapshots.length) {
    throw new Error("Offline export could not match every chart canvas in the source HTML.");
  }
  targets.forEach(function (canvas, i) {
    const s = snapshots[i];
    const img = doc.createElement("img");
    if (s.id) img.setAttribute("id", s.id);
    img.setAttribute("class", s.className);
    img.setAttribute("src", s.src);
    img.setAttribute("alt", s.alt);
    img.setAttribute("role", "img");
    img.setAttribute("aria-label", s.alt);
    img.setAttribute("width", s.width);
    img.setAttribute("height", s.height);
    img.setAttribute("data-cm-offline-chart", "true");
    canvas.replaceWith(img);
  });
}
function _insertOfflineChartGuard(doc) {
  const head = doc.head || doc.querySelector("head");
  if (!head) return;
  const s = doc.createElement("script");
  s.textContent = "window.Chart = undefined;";
  head.appendChild(s);
}
function _buildOfflineHtml(portableHtml) {
  const mermaid = _offlineMermaidSnapshots();
  const charts = _offlineChartSnapshots();
  const doc = _offlineDocFromHtml(portableHtml);
  _replaceOfflineMermaid(doc, mermaid);
  _replaceOfflineCharts(doc, charts);
  _stripOfflineRichRenderers(doc);
  _stripOfflineNetworkLoads(doc);
  _stripOfflineEventHandlers(doc);
  if (charts.length) _insertOfflineChartGuard(doc);
  _ensureOfflineCsp(doc);
  return _retargetLayerDescriptor(_serializeOfflineDoc(doc), "offline").replace(/\n{3,}/g, "\n\n");
}
async function saveOffline() {
  let baseHtml;
  try { baseHtml = await _getBaseHtml(); }
  catch (e) { showToast("Could not load base HTML."); return; }
  baseHtml = _applyWidgetLayoutToHtml(baseHtml);
  baseHtml = _applyChecklistStateToHtml(baseHtml);
  const exportComments = _exportableComments();
  let portable;
  try {
    portable = NONPORTABLE_MODE
      ? _buildStandaloneHtml(baseHtml, exportComments)
      : _buildSavedHtml(baseHtml, exportComments);
  } catch (e) { showToast(e.message); return; }
  let text;
  try { text = _buildOfflineHtml(portable); }
  catch (e) { showToast(e.message); return; }
  const filename = _suggestedOfflineFilename();
  _downloadHtml(text, filename);
  showToast("Downloaded " + filename + " - offline HTML with rendered mermaid and chart snapshots.");
}
["btnExportOffline", "btnExportOfflineTop"].forEach(function (id) {
  const b = document.getElementById(id);
  if (b) b.addEventListener("click", saveOffline);
});

