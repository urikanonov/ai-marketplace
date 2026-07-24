/* ---------- Export as Portable (embed comments + download a copy) ---------- */
// Strategy: always download a fresh HTML copy with the current comments
// embedded in the <script id="embeddedComments"> block. The user can keep
// the copy as-is or replace the original with it. We deliberately do NOT
// try to overwrite the original file in-place (the File System Access
// flow had confusing semantics around "which file does the next save go
// to" once the user picks a different name).
// Transient runtime UI-state classes the layer toggles on document.body (sidebar open,
// active sidebar resize, active widget drag, and deck present mode). They must never be baked
// into a saved or exported file: a persisted "sidebar-open" makes the export render full width
// with an empty right gutter (the body.sidebar-open .app layout rule) for a sidebar that is not
// shown, and "cmh-deck-present" is a deck runtime state re-derived on load. Strip them from
// ONLY the FIRST <body> open tag's class attribute (double-,
// single-, or unquoted) matching whole tokens, so a <body class="..."> literal elsewhere
// (inlined script/content) is left alone, a superstring like x-sidebar-open is preserved,
// and non-transient classes survive; the live layer re-derives the sidebar state on load.
const _TRANSIENT_BODY_CLASSES = { "sidebar-open": 1, "cm-sidebar-resizing": 1, "cm-widget-dragging": 1, "cmh-deck-present": 1, "cmh-deck-comments-off": 1 };
function _stripTransientBodyClasses(html) {
  return String(html == null ? "" : html).replace(/<body\b[^>]*>/i, function (tag) {
    return tag.replace(
      /(\sclass\s*=\s*)(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))/i,
      function (m, pre, dq, sq, uq) {
        const raw = dq != null ? dq : (sq != null ? sq : uq);
        const kept = raw.split(/\s+/).filter(function (t) {
          return t && !Object.prototype.hasOwnProperty.call(_TRANSIENT_BODY_CLASSES, t);
        });
        if (kept.length === 0) return "";  // drop an emptied class attribute (and its lead space)
        const quote = sq != null ? "'" : '"';
        return pre + quote + kept.join(" ") + quote;
      });
  });
}
// Exposed for deterministic tests (body-class normalization is pure and worth unit-testing).
window.__cmhStripTransientBody = function (h) { return _stripTransientBodyClasses(h); };
function _cmhTagEnd(html, start) {
  let quote = "";
  for (let i = start + 1; i < html.length; i += 1) {
    const ch = html[i];
    if (quote) {
      if (ch === quote) quote = "";
    } else if (ch === '"' || ch === "'") {
      quote = ch;
    } else if (ch === ">") {
      return i;
    }
  }
  return -1;
}
function _cmhTagAttributes(tag) {
  const attrs = [];
  let pos = 1;
  while (pos < tag.length && !/[\s/>]/.test(tag[pos])) pos += 1;
  while (pos < tag.length) {
    while (/\s/.test(tag[pos] || "")) pos += 1;
    if (pos >= tag.length || tag[pos] === ">" || tag[pos] === "/") break;
    const nameStart = pos;
    while (pos < tag.length && !/[\s=/>]/.test(tag[pos])) pos += 1;
    if (pos === nameStart) {
      pos += 1;
      continue;
    }
    const name = tag.slice(nameStart, pos).toLowerCase();
    while (/\s/.test(tag[pos] || "")) pos += 1;
    let valueStart = null;
    let valueEnd = null;
    let quote = "";
    if (tag[pos] === "=") {
      pos += 1;
      while (/\s/.test(tag[pos] || "")) pos += 1;
      if (tag[pos] === '"' || tag[pos] === "'") {
        quote = tag[pos];
        pos += 1;
        valueStart = pos;
        while (pos < tag.length && tag[pos] !== quote) pos += 1;
        valueEnd = pos;
        if (tag[pos] === quote) pos += 1;
      } else {
        valueStart = pos;
        while (pos < tag.length && !/[\s>]/.test(tag[pos])) pos += 1;
        valueEnd = pos;
      }
    }
    attrs.push({ name, valueStart, valueEnd, quote });
  }
  return attrs;
}
function _cmhDecodeAttribute(value) {
  const textarea = document.createElement("textarea");
  textarea.innerHTML = String(value).replace(/</g, "&lt;");
  return textarea.value;
}
function _cmhEncodeAttribute(value, quote) {
  let encoded = String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;");
  if (quote === '"') return encoded.replace(/"/g, "&quot;");
  if (quote === "'") return encoded.replace(/'/g, "&#39;");
  encoded = encoded.replace(/[\s"'`=>]/g, function (ch) {
    return "&#" + ch.charCodeAt(0) + ";";
  });
  return '"' + encoded + '"';
}
function _cmhProvenanceRootTag(html) {
  let body = null;
  for (let pos = 0; pos < html.length;) {
    const start = html.indexOf("<", pos);
    if (start < 0) break;
    if (html.slice(start, start + 4) === "<!--") {
      const commentEnd = html.indexOf("-->", start + 4);
      pos = commentEnd < 0 ? html.length : commentEnd + 3;
      continue;
    }
    if (!/[A-Za-z]/.test(html[start + 1] || "")) {
      pos = start + 1;
      continue;
    }
    const end = _cmhTagEnd(html, start);
    if (end < 0) break;
    const tag = html.slice(start, end + 1);
    const nameMatch = tag.match(/^<([A-Za-z][\w:-]*)/);
    const name = nameMatch ? nameMatch[1].toLowerCase() : "";
    const attrs = _cmhTagAttributes(tag);
    const range = { start, end: end + 1, tag, attrs };
    const idAttr = attrs.find(function (attr) { return attr.name === "id"; });
    const firstId = idAttr && idAttr.valueStart != null
      ? _cmhDecodeAttribute(tag.slice(idAttr.valueStart, idAttr.valueEnd)) : null;
    if (firstId === "commentRoot") {
      return range;
    }
    if (name === "body" && body === null) body = range;
    if (/^(?:script|style|textarea|title|template)$/.test(name)) {
      const close = html.toLowerCase().indexOf("</" + name, end + 1);
      if (close < 0) break;
      const closeEnd = _cmhTagEnd(html, close);
      pos = closeEnd < 0 ? html.length : closeEnd + 1;
    } else {
      pos = end + 1;
    }
  }
  return body;
}
function _normalizeDocSourceInHtml(html) {
  const raw = String(html == null ? "" : html);
  const rootTag = _cmhProvenanceRootTag(raw);
  if (!rootTag) return raw;
  let changed = false;
  let nextTag = rootTag.tag;
  const sources = rootTag.attrs.filter(function (attr) {
    return attr.name === "data-doc-source" && attr.valueStart != null;
  });
  for (let i = sources.length - 1; i >= 0; i -= 1) {
    const attr = sources[i];
    const source = _cmhDecodeAttribute(rootTag.tag.slice(attr.valueStart, attr.valueEnd));
    const basename = _docSourceBasename(source);
    if (basename === source) continue;
    changed = true;
    nextTag = nextTag.slice(0, attr.valueStart)
      + _cmhEncodeAttribute(basename, attr.quote)
      + nextTag.slice(attr.valueEnd);
  }
  if (!changed) return raw;
  return raw.slice(0, rootTag.start) + nextTag + raw.slice(rootTag.end);
}
function _retainSessionProvenance() {
  return Array.prototype.some.call(
    document.querySelectorAll("[data-cmh-retain-session-provenance]"),
    function (option) { return option.checked; });
}
function _stripSessionProvenanceFromHtml(html) {
  const raw = String(html == null ? "" : html);
  const lower = raw.toLowerCase();
  let out = "";
  let cursor = 0;
  let search = 0;
  for (;;) {
    const start = lower.indexOf("<meta", search);
    if (start < 0) return out + raw.slice(cursor);
    if (!/[\s/>]/.test(raw[start + 5] || "")) {
      search = start + 5;
      continue;
    }
    const end = _cmhTagEnd(raw, start);
    if (end < 0) return out + raw.slice(cursor);
    const tag = raw.slice(start, end + 1);
    const name = _cmhTagAttributes(tag).find(function (attr) {
      return attr.name === "name" && attr.valueStart != null;
    });
    const value = name
      ? _cmhDecodeAttribute(tag.slice(name.valueStart, name.valueEnd)).toLowerCase() : "";
    out += raw.slice(cursor, start);
    if (value !== "commentable-html-session-id" && value !== "commentable-html-agent") out += tag;
    cursor = end + 1;
    search = cursor;
  }
}
function _prepareExportHtml(html) {
  return _retainSessionProvenance() ? html : _stripSessionProvenanceFromHtml(html);
}
function _initSessionProvenanceOptions() {
  const options = Array.prototype.slice.call(document.querySelectorAll("[data-cmh-retain-session-provenance]"));
  options.forEach(function (option) {
    option.addEventListener("change", function () {
      options.forEach(function (other) { other.checked = option.checked; });
    });
  });
}
_initSessionProvenanceOptions();
async function _getBaseHtml() {
  // Prefer the on-disk version (cleaner diff). Fall back to the snapshot
  // taken at IIFE start if fetch fails (file://, network unavailable, blocked).
  // Either base may carry transient body state (a stale/open-sidebar source), so
  // normalize it here once for every export path (Save, Portable, Offline, Plain).
  try {
    const r = await fetch(location.href, { cache: "no-store" });
    if (r.ok) {
      const t = await r.text();
      if (t && t.includes('id="embeddedComments"')) {
        return _normalizeDocSourceInHtml(_stripTransientBodyClasses(t));
      }
    }
  } catch (e) { /* fall through to snapshot */ }
  return _normalizeDocSourceInHtml(_stripTransientBodyClasses(_snapshotWithTail()));
}
function _isInjectedChrome(n) {
  if (n.nodeType !== 1) return false;
  if (CMH_INJECTED_CHROME.has(n)) return true;
  // Lazy chrome (tooltip, composer, modal, toast) is created after init and so is not in
  // the captured set; it always carries one of these layer classes, which host tail
  // content (a chart canvas, its data/init scripts) never uses.
  const cls = (n.getAttribute && n.getAttribute("class")) || "";
  return /(^|\s)(cm-tooltip|cm-composer|cm-comment-popover|cm-modal-overlay|cm-toast)(\s|$)/.test(cls);
}
function _snapshotWithTail() {
  // SNAPSHOT_HTML is pristine (captured before any runtime mutation) but stops at the
  // layer <script>, so any host content parsed after it (chart data/init scripts placed
  // after the JS region, per charts-embedding.md) is missing and would be dropped on a file://
  // export. That tail is host-owned and never mutated by the layer, so recover it now
  // from the fully-parsed live DOM and splice it back in before the snapshot's </body>.
  const anchor = CMH_LAYER_SCRIPT;
  if (!anchor || !anchor.parentNode) return SNAPSHOT_HTML;
  const serial = function (n) {
    if (n.nodeType === 1) {
      // Skip layer-injected chrome (footer, side-TOC, scroll progress captured at init,
      // plus lazily-created tooltip/composer/modal/toast) appended after the layer
      // script; host content authored after the JS region (e.g. a chart canvas + init
      // scripts, which are themselves cm-skip) must be kept.
      if (_isInjectedChrome(n)) return "";
      return n.outerHTML;
    }
    if (n.nodeType === 8) return "<!--" + n.nodeValue + "-->";
    if (n.nodeType === 3) return n.nodeValue;
    return "";
  };
  // Collect everything after the layer script in document order, climbing out of any
  // wrapper up to <body> so a nested script still recovers the whole tail.
  let tail = "";
  for (let cur = anchor; cur && cur.parentNode; cur = cur.parentNode) {
    for (let s = cur.nextSibling; s; s = s.nextSibling) tail += serial(s);
    if (cur.parentNode === document.body) break;
  }
  if (!tail) return SNAPSHOT_HTML;
  const idx = SNAPSHOT_HTML.toLowerCase().lastIndexOf("</body>");
  if (idx < 0) return SNAPSHOT_HTML + tail;
  return SNAPSHOT_HTML.slice(0, idx) + tail + SNAPSHOT_HTML.slice(idx);
}
function _applyWidgetLayoutToHtml(html) {
  if (typeof widgetStateChanges !== "function" || !widgetStateChanges().length) return html;
  const moves = [];
  const seen = new Set();
  root.querySelectorAll("[data-cm-widget] [data-cm-part]").forEach(function (p) {
    const id = partId(p);
    if (!id) return;
    const widget = widgetName(p);
    const key = partKey(widget, id);
    if (seen.has(key)) return;
    seen.add(key);
    moves.push({ widget, part: id, slot: partSlot(p) });
  });
  if (!moves.length) return html;
  const doc = new DOMParser().parseFromString(String(html || ""), "text/html");
  const widgets = Array.from(doc.querySelectorAll("[data-cm-widget]"));
  const docWidgetName = function (w) { return w.getAttribute("data-cm-widget") || "widget"; };
  const owningWidget = function (el) { return el.closest && el.closest("[data-cm-widget]"); };
  const findWidget = function (name) { return widgets.find(function (w) { return docWidgetName(w) === name; }) || null; };
  const firstInWidget = function (widget, selector, attr, value) {
    return Array.from(widget.querySelectorAll(selector)).find(function (el) {
      return owningWidget(el) === widget && (el.getAttribute(attr) || "") === value;
    }) || null;
  };
  moves.forEach(function (move) {
    if (move.slot == null) return;
    const widget = findWidget(move.widget);
    if (!widget) return;
    const part = firstInWidget(widget, "[data-cm-part]", "data-cm-part", move.part);
    const slot = firstInWidget(widget, "[data-cm-slot]", "data-cm-slot", move.slot);
    if (part && slot && !part.contains(slot)) slot.appendChild(part);
  });
  return (/^\s*<!doctype/i.test(String(html || "")) ? "<!DOCTYPE html>\n" : "") + doc.documentElement.outerHTML;
}
function _buildSavedHtml(baseHtml, commentArr) {
  // Escape "<" as \u003c so a comment note containing a closing script tag (or an
  // HTML comment opener) cannot break out of the <script id="embeddedComments">
  // block when the saved file is opened or shared. JSON.parse restores it on load.
  const json = JSON.stringify(commentArr || [], null, 2).replace(/</g, "\\u003c");
  // The escaped slashes below (<\/script>, application\/json) keep the HTML
  // parser from treating the strings as a real closing tag inside this
  // <script> body. At runtime the strings hold the unescaped characters.
  const repl = '<script type="application\/json" id="embeddedComments">\n'
             + json
             + '\n<\/script>';
  // Match the embedded-comments script by a real, whitespace-delimited id attribute,
  // regardless of the remaining attribute order or spacing: a document authored or re-saved
  // as `<script id="embeddedComments" type="...">` must still be found. Requiring whitespace
  // before `id` (not a bare word boundary) means a decoy `data-id="embeddedComments"` or
  // `aria-id="embeddedComments"` on another script is never mistaken for the real block. The
  // body is non-greedy to the first closing tag; comment JSON escapes every "<" as \u003c,
  // so no closing script tag can appear inside it.
  const rx = /<script\b[^>]*?\sid\s*=\s*(["'])embeddedComments\1[^>]*>[\s\S]*?<\/script>/i;
  if (!rx.test(baseHtml)) {
    throw new Error('Could not find <scr' + 'ipt id="embeddedComments"> in the source HTML. Make sure the EMBEDDED COMMENTS region is present.');
  }
  // Use a REPLACER FUNCTION, not a string: `repl` is built from user comment text, and a
  // string replacement would expand `$&`, `$1`, `$\``, `$'`, and `$$` (a note containing e.g.
  // `$&` or a shell `$'` would corrupt the embedded-comments JSON and break reload).
  return baseHtml.replace(rx, () => repl);
}
function _suggestedFilename() {
  const path = location.pathname;
  let name = path.substring(path.lastIndexOf("/") + 1);
  try { name = decodeURIComponent(name); } catch (e) { /* keep raw */ }
  if (!name || !/\.html?$/i.test(name)) name = "commentable.html";
  const m = name.match(/^(.*?)(\.html?)$/i);
  const stem = m[1];
  const ext = m[2];
  // "Export as Portable" always produces a self-contained portable file, so tag it.
  // Strip any prior -comments / -portable suffix first so it never stacks.
  const clean = stem.replace(/-comments$/i, "").replace(/-portable$/i, "");
  return clean + "-portable" + ext;
}
function _suggestedOfflineFilename() {
  const path = location.pathname;
  let name = path.substring(path.lastIndexOf("/") + 1);
  try { name = decodeURIComponent(name); } catch (e) { /* keep raw */ }
  if (!name || !/\.html?$/i.test(name)) name = "commentable.html";
  const m = name.match(/^(.*?)(\.html?)$/i);
  const clean = m[1].replace(/-comments$/i, "").replace(/-portable$/i, "").replace(/-offline$/i, "");
  return clean + "-offline" + m[2];
}
function _downloadHtml(text, filename) {
  const blob = new Blob([text], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 0);
}
function _layerDescriptorJson(mode) {
  return JSON.stringify({ version: CMH_VERSION, mode, regions: CMH_REGION_NAMES });
}
function _retargetLayerDescriptor(html, mode) {
  const rx = /(<script\b[^>]*\sid\s*=\s*(["'])commentableHtmlLayer\2[^>]*>)([\s\S]*?)(<\/script>)/i;
  if (rx.test(html)) return html.replace(rx, "$1" + _layerDescriptorJson(mode) + "$4");
  return html.replace(/(<meta name="commentable-html-version" content="[^"]+" \/?>\s*)/i,
    "$1" + '<script type="application/json" id="commentableHtmlLayer">' + _layerDescriptorJson(mode) + "</scr" + "ipt>\n");
}
async function saveHtml() {
  let baseHtml;
  try { baseHtml = await _getBaseHtml(); }
  catch (e) { showToast("Could not load base HTML."); return; }
  baseHtml = _applyWidgetLayoutToHtml(baseHtml);
  baseHtml = _applyChecklistStateToHtml(baseHtml);
  baseHtml = _applyNoteStateToHtml(baseHtml);
  baseHtml = _applyReviewStateToHtml(baseHtml);
  baseHtml = _prepareExportHtml(baseHtml);
  const exportComments = _exportableComments();
  let text;
  try { text = _buildSavedHtml(baseHtml, exportComments); }
  catch (e) { showToast(e.message); return; }
  const filename = _suggestedFilename();
  const n = exportComments.length;
  const noun = "comment" + (n === 1 ? "" : "s");
  _downloadHtml(text, filename);
  showToast(`Downloaded ${filename} with ${n} embedded ${noun}. Replace the original on disk to make them stick.`);
}
