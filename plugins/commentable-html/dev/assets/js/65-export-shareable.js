/* ---------- Export as Shareable (embed comments + download a copy) ---------- */
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
// ASCII whitespace is the HTML spec's tag delimiter set. JS `\s` also matches NBSP and other
// Unicode spaces, which a browser does NOT treat as a delimiter, so `<script\u00a0id="...">`
// (one bogus unknown element to a browser) would otherwise look like a real script tag here.
const _CMH_SPACE_CH = /[\t\n\f\r ]/;
// One source of truth for "what ends a tag name" - a space belongs here, since an end tag may
// carry a space before its ">" and still close the element. Spelling the class twice let the space go missing from
// the close scanners, which made such a document impossible to export at all.
const _CMH_NAME_END_SRC = "\\t\\n\\f\\r />";
const _CMH_NAME_END_CH = new RegExp("[" + _CMH_NAME_END_SRC + "]");
// Elements whose CONTENT a browser parses as TEXT, never as markup (noscript counts because the
// layer only runs with scripting enabled). Nothing inside one of these is an element.
const _CMH_RAW_TEXT = /^(?:script|style|textarea|title|xmp|iframe|noembed|noframes|noscript)$/;
function _cmhTagEnd(html, start) {
  let quote = "";
  let afterEquals = false;
  for (let i = start + 1; i < html.length; i += 1) {
    const ch = html[i];
    if (quote) {
      if (ch === quote) quote = "";
      continue;
    }
    // A quote only opens an attribute value directly after `=`; a stray apostrophe elsewhere in
    // the tag (`<div data-x=it's ok>`) does not, and treating it as one used to swallow the
    // rest of the document.
    if (ch === '"' || ch === "'") {
      if (afterEquals) quote = ch;
      afterEquals = false;
      continue;
    }
    if (ch === "=") {
      afterEquals = true;
      continue;
    }
    if (_CMH_SPACE_CH.test(ch)) continue;
    if (ch === ">") return i;
    afterEquals = false;
  }
  return -1;
}
function _cmhTagName(html, from) {
  let i = from;
  while (i < html.length && !_CMH_NAME_END_CH.test(html[i])) i += 1;
  return html.slice(from, i).toLowerCase();
}
function _cmhCommentEnd(html, start) {
  // `<!-->` and `<!--->` are complete (empty) comments, and `--!>` also terminates one. Missing
  // those made a legal comment swallow the rest of the document.
  let i = start + 4;
  if (html[i] === ">") return i + 1;
  if (html[i] === "-" && html[i + 1] === ">") return i + 2;
  const rx = /--!?>/g;
  rx.lastIndex = i;
  const m = rx.exec(html);
  return m ? m.index + m[0].length : html.length;
}
function _cmhScriptDataClose(html, from) {
  // The tokenizer's script-data escaped states: inside a <script> body a `<!--` starts an
  // escaped run, and a nested `<script` within it starts a DOUBLE-escaped run in which the next
  // closing script tag only ends that run instead of closing the element (the classic
  // `<!--<script>` idiom). Only `-->` leaves those runs (`--!>` does not, unlike in a comment).
  const rx = new RegExp("<!--|-->|</?script(?=[" + _CMH_NAME_END_SRC + "])", "gi");
  rx.lastIndex = from;
  let escaped = false;
  let doubled = false;
  let m;
  while ((m = rx.exec(html))) {
    const tok = m[0].toLowerCase();
    if (tok === "<!--") { escaped = true; continue; }
    if (tok.charAt(0) === "-") { escaped = false; doubled = false; continue; }
    if (tok === "<script") { if (escaped) doubled = true; continue; }
    if (doubled) { doubled = false; continue; }
    return m.index;
  }
  return -1;
}
function _cmhRawTextClose(html, name, from) {
  if (name === "script") return _cmhScriptDataClose(html, from);
  // An end tag only closes a raw-text element when the name is followed by whitespace, `/`, or
  // `>`; an end tag that merely PREFIXES the name (a "scriptfoo" close) is text. Matching a bare
  // prefix ended the element early and exposed its text to this walk as markup - the very
  // failure this resolver exists to prevent.
  const rx = new RegExp("</" + name + "(?=[" + _CMH_NAME_END_SRC + "])", "gi");
  rx.lastIndex = from;
  const m = rx.exec(html);
  return m ? m.index : -1;
}
// Walk an HTML string's element tags in document order the way an HTML parser does: consume
// comments, DOCTYPEs, bogus declarations and processing instructions; skip the TEXT content of
// raw-text elements; and never report a tag inside <template> content (which is an inert
// fragment, invisible to getElementById). `visit` gets each open tag and returns a truthy value
// to stop the walk and hand that value back. All indexes are offsets into the ORIGINAL string.
function _cmhForEachTag(html, visit) {
  const raw = String(html == null ? "" : html);
  let templateDepth = 0;
  let foreignDepth = 0;
  for (let pos = 0; pos < raw.length;) {
    const start = raw.indexOf("<", pos);
    if (start < 0) break;
    if (raw.slice(start, start + 4) === "<!--") {
      pos = _cmhCommentEnd(raw, start);
      continue;
    }
    const lead = raw.charAt(start + 1);
    if (lead === "!" || lead === "?") {
      // A DOCTYPE, a bogus declaration (`<![CDATA[...`), or a processing instruction: an HTML
      // parser consumes it to the first `>`, so nothing inside it is markup.
      const gt = raw.indexOf(">", start + 1);
      pos = gt < 0 ? raw.length : gt + 1;
      continue;
    }
    if (lead === "/") {
      const endName = _cmhTagName(raw, start + 2);
      const gt = _cmhTagEnd(raw, start);
      if (endName === "template" && templateDepth > 0) templateDepth -= 1;
      if ((endName === "svg" || endName === "math") && foreignDepth > 0) foreignDepth -= 1;
      pos = gt < 0 ? raw.length : gt + 1;
      continue;
    }
    if (!/[A-Za-z]/.test(lead)) {
      pos = start + 1;
      continue;
    }
    const end = _cmhTagEnd(raw, start);
    if (end < 0) break;
    const tag = raw.slice(start, end + 1);
    const name = _cmhTagName(raw, start + 1);
    let closeStart = -1;
    let closeEnd = -1;
    let next = end + 1;
    let stop = false;
    // Inside <svg>/<math> a `/>` really self-closes, so a `<title/>` or `<style/>` there has no
    // end tag to look for; in HTML the same spelling opens a raw-text element.
    const selfClosed = foreignDepth > 0 && /\/\s*>$/.test(tag);
    if (selfClosed) {
      next = end + 1;
    } else if (name === "plaintext") {
      stop = true;  // everything after <plaintext> is text, never markup
    } else if (_CMH_RAW_TEXT.test(name)) {
      const close = _cmhRawTextClose(raw, name, end + 1);
      const closeTagEnd = close < 0 ? -1 : _cmhTagEnd(raw, close);
      if (closeTagEnd < 0) {
        // Truncated raw-text element: report no close, so a caller that needs the whole element
        // fails loudly instead of eating the rest of the document.
        stop = true;
      } else {
        closeStart = close;
        closeEnd = closeTagEnd + 1;
        next = closeEnd;
      }
    }
    if (templateDepth === 0) {
      const found = visit({ name, tag, start, tagEnd: end + 1, closeStart, closeEnd });
      if (found) return found;
    }
    if (stop) break;
    if (!selfClosed) {
      if (name === "template") templateDepth += 1;
      if (name === "svg" || name === "math") foreignDepth += 1;
    }
    pos = next;
  }
  return null;
}
function _cmhTagId(tag) {
  const attrs = _cmhTagAttributes(tag);
  const idAttr = attrs.find(function (attr) { return attr.name === "id"; });
  const value = idAttr && idAttr.valueStart != null
    ? _cmhDecodeAttribute(tag.slice(idAttr.valueStart, idAttr.valueEnd)) : null;
  return { attrs, id: value };
}
function _cmhProvenanceRootTag(html) {
  let body = null;
  const found = _cmhForEachTag(html, function (el) {
    const parsed = _cmhTagId(el.tag);
    const range = { start: el.start, end: el.tagEnd, tag: el.tag, attrs: parsed.attrs };
    if (parsed.id === "commentRoot") return range;
    if (el.name === "body" && body === null) body = range;
    return null;
  });
  return found || body;
}
// Stamp each walked candidate with a unique probe attribute in a THROWAWAY copy of the source and
// parse THAT, so every parsed element carries the index of the source range it came from. The walk
// reports SOURCE order while a parsed document reports TREE order, and markup a browser rearranges
// (an element foster-parented out of a table, say) makes the two disagree; equal counts do not rule
// that out and equal bodies cannot tell a match from a swap, so the mapping is established by
// IDENTITY rather than by position. The value carries a per-call random token, so an attribute the
// DOCUMENT itself supplies can never be mistaken for one of ours. The copy decides identity and
// containment only; the offsets spliced are always the original ones.
const _CMH_PROBE_ATTR = "data-cmh-range-probe";
function _cmhProbeToken() {
  return "p" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}
function _cmhProbeParse(src, found, token) {
  // One forward pass joined once: rebuilding the whole source per candidate would be quadratic in
  // a document that carries many same-id scripts, which authored content controls.
  const parts = [];
  let at = 0;
  for (let i = 0; i < found.length; i += 1) {
    // The walk only reports tags whose name is exactly "script", so the character after the name
    // is at start + "<script".length whatever the tag's case - an attribute inserted there is
    // separated from both the name and whatever followed. A duplicate attribute later in the same
    // tag is ignored by the parser (the first one wins), so ours is the value that survives.
    const cut = found[i].start + 7;
    parts.push(src.slice(at, cut), " ", _CMH_PROBE_ATTR, '="', token, "-", String(i), '"');
    at = cut;
  }
  parts.push(src.slice(at));
  const srcProbed = parts.join("");
  return new DOMParser().parseFromString(srcProbed, "text/html");
}
// Resolve the layer's own data <script> blocks as INFRASTRUCTURE, never by scanning the document
// text: the walk above finds the scripts whose PARSED id matches, and the result is then
// CROSS-CHECKED against the browser's own parser. A raw text scan cannot answer this question
// honestly, because the layer's own source - part of every document - contains the very markup
// being looked for: the missing-region guard could never fire, and a document that had genuinely
// lost the block had its own runtime source overwritten with the comments JSON instead of failing
// loudly. The cross-check means any residual tokenizer differential is a loud failure rather than a
// splice into text no browser ever parsed as an element.
//
// WHICH block, among several owning the id, is decided by the CONTENT-ROOT BOUNDARY
// (cmhLayerBlocks in 01-config.js), not by document position: an element inside `#commentRoot` is
// authored content and can never be one of the layer's blocks. The runtime reads them through the
// same boundary, so the exporter always rewrites exactly the block a reload reads back. The
// cross-check is likewise scoped to the blocks the boundary accepts: a decoy the walk and the
// parse see differently is only a reason to refuse when it is one of the layer's OWN candidates,
// or authored content could veto every future export of the document it sits in.
// Returns { anyOwner, contested, present, ranges }: `anyOwner` is "some element carries the id
// anywhere", `contested` is "the boundary itself is ambiguous", `present` is the browser's answer
// for the layer's own region, and `ranges` (in TREE order, each carrying its parsed `el`) is empty
// unless the walk agreed with the parse.
function _cmhVerifiedScriptRanges(html, id) {
  const src = String(html == null ? "" : html);
  const isScript = function (node) { return node && (node.tagName || "").toLowerCase() === "script"; };
  const found = [];
  _cmhForEachTag(src, function (tag) {
    if (tag.name !== "script" || tag.closeEnd < 0) return null;
    if (_cmhTagId(tag.tag).id !== id) return null;
    found.push({ start: tag.start, tagEnd: tag.tagEnd, closeStart: tag.closeStart, end: tag.closeEnd });
    return null;
  });
  const token = _cmhProbeToken();
  const doc = _cmhProbeParse(src, found, token);
  const owners = cmhLayerIdOwners(doc, id);
  const state = cmhContentRootState(doc);
  // A document may legitimately carry more than one element with the id (a host decoy that
  // borrowed a reserved one - CMH-OFFLINE-04 keeps such bytes rather than deleting them). The
  // layer's own blocks are the ones the boundary accepts, and the first of those is what the
  // runtime reads. It must be the script: a non-script shadowing the id means a reload would not
  // read the block at all.
  const outside = cmhLayerBlocks(doc, id);
  const none = {
    anyOwner: owners.length > 0, contested: state.contested,
    present: outside.length > 0, ranges: [],
  };
  if (!outside.length || !isScript(outside[0])) return none;
  // The parser normalizes CRLF to LF in text, so compare newline-normalized bodies.
  const nl = function (s) { return String(s).replace(/\r\n?/g, "\n"); };
  const used = Object.create(null);
  const rangeOf = function (el) {
    const raw = el.getAttribute(_CMH_PROBE_ATTR);
    // An absent or foreign probe means the walk never saw this element: there is no source range
    // to splice, so refuse rather than fall back to a positional guess. The index is claimed at
    // most once, so two elements can never map onto one range.
    if (typeof raw !== "string" || raw.indexOf(token + "-") !== 0) return null;
    const k = Number(raw.slice(token.length + 1));
    if (!Number.isInteger(k) || k < 0 || k >= found.length || used[k]) return null;
    used[k] = true;
    return found[k];
  };
  const ranges = [];
  for (let i = 0; i < outside.length; i += 1) {
    const el = outside[i];
    if (!isScript(el)) continue;
    const range = rangeOf(el);
    if (!range || nl(src.slice(range.tagEnd, range.closeStart)) !== nl(el.textContent)) return none;
    ranges.push({
      start: range.start, tagEnd: range.tagEnd,
      closeStart: range.closeStart, end: range.end, el: el,
    });
  }
  if (!ranges.length) return none;
  return { anyOwner: none.anyOwner, contested: none.contested, present: none.present, ranges: ranges };
}
// The single block the runtime reads back: { present, start, tagEnd, closeStart, end }, with null
// offsets unless the walk and the parse agreed.
function _cmhVerifiedScriptRange(html, id) {
  const found = _cmhVerifiedScriptRanges(html, id);
  const only = found.ranges.length ? found.ranges[0] : null;
  return {
    anyOwner: found.anyOwner,
    contested: found.contested,
    present: found.present,
    start: only ? only.start : null,
    tagEnd: only ? only.tagEnd : null,
    closeStart: only ? only.closeStart : null,
    end: only ? only.end : null,
  };
}
// One wording for the state no lookup can resolve: the boundary itself is contested.
const _CMH_CONTESTED_ROOT_ERROR = "Export aborted: this document has more than one element carrying "
  + "the commentable-html content-root id, so the layer cannot tell its own blocks from authored "
  + "content. Remove the duplicate id, then export again.";
function _cmhEmbeddedCommentsRange(html) {
  const found = _cmhVerifiedScriptRange(html, "embeddedComments");
  return found.start == null ? null : { start: found.start, end: found.end };
}
// Exposed for deterministic tests (locating the block is pure and worth unit-testing).
window.__cmhFindEmbeddedComments = function (h) { return _cmhEmbeddedCommentsRange(h); };
function _cmhTagAttributes(tag) {
  const attrs = [];
  let pos = 1;
  while (pos < tag.length && !_CMH_NAME_END_CH.test(tag[pos])) pos += 1;
  while (pos < tag.length) {
    while (_CMH_SPACE_CH.test(tag[pos] || "")) pos += 1;
    if (pos >= tag.length || tag[pos] === ">" || tag[pos] === "/") break;
    const nameStart = pos;
    while (pos < tag.length && !/[\t\n\f\r =/>]/.test(tag[pos])) pos += 1;
    if (pos === nameStart) {
      pos += 1;
      continue;
    }
    const name = tag.slice(nameStart, pos).toLowerCase();
    while (_CMH_SPACE_CH.test(tag[pos] || "")) pos += 1;
    let valueStart = null;
    let valueEnd = null;
    let quote = "";
    if (tag[pos] === "=") {
      pos += 1;
      while (_CMH_SPACE_CH.test(tag[pos] || "")) pos += 1;
      if (tag[pos] === '"' || tag[pos] === "'") {
        quote = tag[pos];
        pos += 1;
        valueStart = pos;
        while (pos < tag.length && tag[pos] !== quote) pos += 1;
        valueEnd = pos;
        if (tag[pos] === quote) pos += 1;
      } else {
        valueStart = pos;
        while (pos < tag.length && !/[\t\n\f\r >]/.test(tag[pos])) pos += 1;
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
async function _getBaseHtml() {
  // Prefer the on-disk version (cleaner diff). Fall back to the snapshot
  // taken at IIFE start if fetch fails (file://, network unavailable, blocked).
  // Either base may carry transient body state (a stale/open-sidebar source), so
  // normalize it here once for every export path (Save, Shareable, Offline, Plain).
  try {
    const r = await fetch(location.href, { cache: "no-store" });
    if (r.ok) {
      const t = await r.text();
      if (t && _cmhEmbeddedCommentsRange(t)) {
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
  // Locate the embedded-comments script STRUCTURALLY (see _cmhVerifiedScriptRange): a real,
  // parsed id attribute on a script the BROWSER also sees as that element, regardless of
  // attribute order or spacing, so a document authored or re-saved as
  // `<script id="embeddedComments" type="...">` is still found while a decoy
  // `data-id="embeddedComments"` on another script never is. A document that genuinely lost the
  // region resolves to nothing and fails here instead of exporting a corrupted copy.
  const found = _cmhVerifiedScriptRange(baseHtml, "embeddedComments");
  // The LIVE document's boundary is checked too, not just the export base's. The reader fails
  // closed on a contested live boundary (it loaded no embedded comments), so writing a base whose
  // own boundary is intact would bake that reduced set straight over the file's comments - the
  // loss this whole rule exists to prevent, arriving through the back door.
  if (found.contested || cmhContentRootState(document).contested) {
    throw new Error(_CMH_CONTESTED_ROOT_ERROR);
  }
  if (found.start == null) {
    // Distinguish the remaining failures: the block is present in the layer's own region but this
    // document's markup could not be resolved to it reliably, the only element carrying the id is
    // authored content inside the content root, or the region is simply absent. Never splice on a
    // guess, and never blame the wrong thing.
    if (found.present) {
      throw new Error('Found <scr' + 'ipt id="embeddedComments"> but could not locate it reliably in the source HTML. The document markup may be malformed; re-generate or repair it, then export again.');
    }
    if (found.anyOwner) {
      throw new Error('The only <scr' + 'ipt id="embeddedComments"> in this document sits inside the content root, where authored content lives, so it is not the layer\'s block. Move the EMBEDDED COMMENTS region above the content root, then export again.');
    }
    throw new Error('Could not find <scr' + 'ipt id="embeddedComments"> in the source HTML. Make sure the EMBEDDED COMMENTS region is present.');
  }
  // Splice by OFFSETS, never String.replace: `repl` is built from user comment text, and a
  // string replacement would expand `$&`, `$1`, `$\``, `$'`, and `$$` (a note containing e.g.
  // `$&` or a shell `$'` would corrupt the embedded-comments JSON and break reload).
  const src = String(baseHtml);
  return src.slice(0, found.start) + repl + src.slice(found.end);
}
function _suggestedFilename() {
  const path = location.pathname;
  let name = path.substring(path.lastIndexOf("/") + 1);
  try { name = decodeURIComponent(name); } catch (e) { /* keep raw */ }
  if (!name || !/\.html?$/i.test(name)) name = "commentable.html";
  const m = name.match(/^(.*?)(\.html?)$/i);
  const stem = m[1];
  const ext = m[2];
  // "Export as Shareable" always produces a self-contained shareable file, so tag it.
  // Strip any prior -comments / -shareable suffix first so it never stacks. The pre-rename
  // -portable suffix is stripped too: every file the earlier releases exported carries it, and
  // re-exporting one must not produce "<stem>-portable-shareable.html".
  const clean = stem.replace(/-comments$/i, "").replace(/-(?:shareable|portable)$/i, "");
  return clean + "-shareable" + ext;
}
function _suggestedOfflineFilename() {
  const path = location.pathname;
  let name = path.substring(path.lastIndexOf("/") + 1);
  try { name = decodeURIComponent(name); } catch (e) { /* keep raw */ }
  if (!name || !/\.html?$/i.test(name)) name = "commentable.html";
  const m = name.match(/^(.*?)(\.html?)$/i);
  const clean = m[1].replace(/-comments$/i, "").replace(/-(?:shareable|portable)$/i, "").replace(/-offline$/i, "");
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
// Inert DATA, as the browser would judge it: no `src` to fetch, and a type that does not run.
// `_offlineIsRunnableScriptType` (declared in the later partial `68-export-offline.js`; the
// partials share one hoisted IIFE scope, see MODULES.md) is the one HTML "JavaScript MIME type"
// test in this layer, so the two never drift apart. Only such a block may be rewritten as a
// descriptor copy.
function _cmhIsInertDataScript(el) {
  if (!el || el.getAttribute("src")) return false;
  return !_offlineIsRunnableScriptType(el.getAttribute("type"));
}
function _retargetLayerDescriptor(html, mode) {
  // Resolve the descriptor block the same structural way as the comments block (see
  // _cmhVerifiedScriptRanges). A text scan could not: the layer's own source spells
  // `<script type="application/json" id="commentableHtmlLayer">`, so a document that had lost
  // the real block still "matched" inside the inlined runtime and the replace overwrote a
  // quarter of a megabyte of runtime JS with the descriptor JSON.
  const src = String(html == null ? "" : html);
  const found = _cmhVerifiedScriptRanges(src, "commentableHtmlLayer");
  if (found.ranges.length) {
    // Retarget the block a reader resolves - it IS the descriptor - plus every ADDITIONAL copy in
    // the layer's own region, but only while each is inert DATA. Rewriting just the first left any
    // other reserved-id copy stale, so an exported document could ship two descriptors disagreeing
    // about what it IS, and which one a tool believed came down to document order. The inert-data
    // test is what keeps that from becoming a licence to clobber: overwriting an author's RUNNABLE
    // script (or one with a `src`) would be exactly the silent, unrequested mutation CMH-EXP-19
    // refuses to make, and would leave a classic script whose body is now JSON. That holds for the
    // resolved block too - if the element the runtime reads as the descriptor is runnable, the
    // document is broken in a way only its author can fix, so refuse instead of destroying code.
    if (!_cmhIsInertDataScript(found.ranges[0].el)) {
      throw new Error("Export aborted: the element this document exposes as its commentable-html layer descriptor is a runnable script, not an inert data block, so the export will not overwrite it. Give that script a different id (or restore the descriptor), then export again.");
    }
    const targets = found.ranges.filter(function (range) {
      return _cmhIsInertDataScript(range.el);
    });
    // Splice last-first so the earlier ranges' offsets stay valid, and only ever backwards: a
    // range that overlapped one already spliced would corrupt the output silently.
    const ordered = targets.slice().sort(function (a, b) { return b.start - a.start; });
    let out = src;
    let limit = src.length;
    for (let i = 0; i < ordered.length; i += 1) {
      const range = ordered[i];
      if (range.end > limit) {
        throw new Error("Export aborted: the commentable-html layer descriptor could not be located reliably in the source HTML.");
      }
      // Replace only the BODY, so the block keeps whatever attributes it was authored with.
      out = out.slice(0, range.tagEnd) + _layerDescriptorJson(mode) + out.slice(range.closeStart);
      limit = range.start;
    }
    return out;
  }
  if (found.contested) throw new Error(_CMH_CONTESTED_ROOT_ERROR);
  if (found.present) {
    throw new Error("Export aborted: the commentable-html layer descriptor could not be located reliably in the source HTML.");
  }
  if (found.anyOwner) {
    // An element carries the descriptor id, but only inside the content root - authored content.
    // Anchoring a fresh descriptor here would emit a document with two elements owning a
    // reserved id that the strict validator requires to be unique, so fail loudly instead.
    throw new Error("Export aborted: the only element carrying the commentable-html layer descriptor id sits inside the content root, where authored content lives. Move the descriptor above the content root (or re-generate the document), then export again.");
  }
  // No descriptor at all: anchor a fresh one to the version meta tag. Match that tag as a parser
  // would - a DOM-serialized document writes `<meta name="..." content="...">` with neither the
  // space nor the slash - and fail loudly if there is nothing to anchor to, rather than
  // downloading a document with no descriptor.
  const insert = '<script type="application/json" id="commentableHtmlLayer">'
    + _layerDescriptorJson(mode) + "</scr" + "ipt>\n";
  const anchored = src.replace(/<meta name="commentable-html-version" content="[^"]+"\s*\/?>\s*/i,
    function (m) { return m + insert; });
  if (anchored === src) {
    throw new Error("Export aborted: this document has no commentable-html layer descriptor and no version meta tag to anchor one to.");
  }
  // The anchor was matched in TEXT, so confirm the freshly minted block really landed in the
  // layer's own region: a document whose head meta is missing while its CONTENT quotes that meta
  // would otherwise have the descriptor written into authored content, and every later export
  // would then refuse it as content - a one-way brick caused by the layer itself.
  if (!_cmhVerifiedScriptRanges(anchored, "commentableHtmlLayer").ranges.length) {
    throw new Error("Export aborted: a commentable-html layer descriptor could not be re-created outside the content root. Re-generate the document, then export again.");
  }
  return anchored;
}
async function saveHtml() {
  let baseHtml;
  try { baseHtml = await _getBaseHtml(); }
  catch (e) { showToast("Could not load base HTML."); return; }
  baseHtml = _applyWidgetLayoutToHtml(baseHtml);
  baseHtml = _applyChecklistStateToHtml(baseHtml);
  baseHtml = _applyNoteStateToHtml(baseHtml);
  const review = _applyReviewStateToHtml(baseHtml);
  baseHtml = review.html;
  const exportComments = _exportableComments();
  let text;
  try {
    text = _buildSavedHtml(baseHtml, exportComments);
    // Restamp the descriptor on this path too, so "no surviving copy disagrees with the document
    // it is in" (CMH-EXP-18) holds for a plain Save, not only for the paths that CHANGE the mode.
    // The mode written is the document's own, so a re-saved Offline copy stays Offline
    // (CMH-OFFLINE-03): this is a consistency pass, never a mode change.
    text = _retargetLayerDescriptor(text, isOfflineDocument() ? "offline" : "shareable");
  } catch (e) { showToast(e.message); return; }
  const filename = _suggestedFilename();
  const n = exportComments.length;
  const noun = "comment" + (n === 1 ? "" : "s");
  _downloadHtml(text, filename);
  showToast(`Downloaded ${filename} with ${n} embedded ${noun}. Replace the original on disk to make them stick.` + review.note, { center: true });
}
