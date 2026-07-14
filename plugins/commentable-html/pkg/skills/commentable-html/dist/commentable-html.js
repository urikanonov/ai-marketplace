(() => {
// Pristine snapshot of the document, captured before any DOM mutation
// (mermaid render, restored highlights, dynamic composers, etc). Used as a
// fallback by "Export as Portable" when fetch() of the page URL is unavailable
// (e.g., file://, blocked fetch, or CSP). The snapshot is taken on the very first line
// of the IIFE so it predates every runtime change this script makes.
const SNAPSHOT_HTML = "<!DOCTYPE html>\n" + document.documentElement.outerHTML;
// The layer runs synchronously during parse, so SNAPSHOT_HTML stops at THIS <script>:
// host content placed after the layer (per charts.md, chart data + init scripts land
// after the "END: commentable-html - JS" marker, before the final </body>) has not been
// parsed yet and is absent from the snapshot. Capture the script element now, while
// document.currentScript is still valid, so an export can recover that tail from the
// fully-parsed DOM (see _snapshotWithTail).
const CMH_LAYER_SCRIPT = document.currentScript;
// Layer chrome injected during init (footer, side-TOC, scroll progress) is captured in
// this set at the end of the IIFE - before the browser parses any host content that
// follows the layer <script> - so a file:// export tail can exclude it while keeping
// host content (which may itself be cm-skip, e.g. a chart <canvas>). See _snapshotWithTail.
const CMH_INJECTED_CHROME = new Set();

/* ---------- Config (auto-discovered, never edit per-doc) ---------- */
const root = document.getElementById("commentRoot") || document.body;
const COMMENT_KEY = root.dataset.commentKey || ("commentable-html:" + location.pathname);
const DOC_LABEL   = root.dataset.docLabel   || document.title || location.pathname;
const DOC_SOURCE  = root.dataset.docSource  || location.pathname;
// Deck profile: a commentable-native slide deck (see references/deck-contract.md). When
// active, the layer replaces the flow-document chrome (heading anchors, collapsible
// sections, side TOC, footer, scroll progress) with slide navigation and commenting.
const IS_DECK = !!(root.getAttribute && root.getAttribute("data-cmh-mode") === "deck");
const SIDEBAR_WIDTH_KEY = "commentable-html::sidebarWidth";
// Comment ids are generated as "c" + base36 timestamp + 4 base36 chars and are
// later interpolated into HTML attributes (data-cid="...") and CSS selectors.
// Loaded and embedded comment ids must match this format - otherwise a
// malformed id could break out of an attribute or poison a selector.
const SAFE_ID_RE = /^c[a-z0-9]{6,63}$/;

// Version of this runtime, stamped from dev/VERSION by build.py. Do not hand-edit;
// bump dev/VERSION and rebuild.
const CMH_VERSION = "1.47.0";
const CMH_REGION_NAMES = ["CSS", "HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "JS"];
// Inline brand icon (a comment bubble) used in the sidebar meta row, the footer, and the
// Help About section. Uses the accent color so it matches the theme.
const CMH_ICON_SVG = (
  '<svg class="cm-brand-icon" viewBox="0 0 24 24" width="16" height="16" role="img" focusable="false"'
  + ' aria-label="Commentable HTML v' + CMH_VERSION + '" data-cmh-tip="Commentable HTML v' + CMH_VERSION + '">'
  + '<path d="M3 5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9l-4.5 3.5A1 1 0 0 1 3 19.7V5z" fill="var(--cp-accent)"/>'
  + '<rect x="6" y="7" width="12" height="1.8" rx="0.9" fill="#fff"/>'
  + '<rect x="6" y="10.5" width="8" height="1.8" rx="0.9" fill="#fff"/>'
  + '</svg>'
);
// Public project site the brand mark links to (opens in a new tab). Used by the sidebar
// meta-row brand icon and the footer brand.
const CMH_SITE_URL = "https://urikanonov.github.io/ai-marketplace/commentable-html/";
function cmBrandLink(inner) {
  return '<a class="cm-brand-link" href="' + CMH_SITE_URL
    + '" target="_blank" rel="noopener noreferrer"'
    + ' aria-label="commentable-html project site (opens in a new tab)">' + inner + '</a>';
}
// Small monochrome line-icons (stroke = currentColor) for chrome controls. Kept as
// path data so a single helper renders them at any size without external assets.
// Icons consumed by _cmIco() for runtime chrome (TOC, scroll, Help search). The three
// sidebar action-button icons (Portable/Plain/Clear) are authored inline in
// template.shell.html and are intentionally not duplicated here.
const _CM_ICONS = {
  expand:   "M8 9l4-4 4 4 M8 15l4 4 4-4",
  collapse: "M8 5l4 4 4-4 M8 19l4-4 4 4",
  top:      "M12 19V6 M6 11l6-6 6 6",
  bottom:   "M12 5v13 M6 13l6 6 6-6",
  search:   "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M20 20l-3.5-3.5",
};
function _cmIco(name, size) {
  const d = _CM_ICONS[name];
  if (!d) return "";
  const s = size || 14;
  return '<svg class="cm-ui-ico" viewBox="0 0 24 24" width="' + s + '" height="' + s
    + '" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="2"'
    + ' stroke-linecap="round" stroke-linejoin="round"><path d="' + d + '"/></svg>';
}
// In nonportable mode the page loads an external commentable-html.assets.js
// that defines window.__COMMENTABLE_ASSETS__ = { version, css, js } - the string
// payloads used to rebuild a fully self-contained file for "Export standalone".
// A separate assets file (never the runtime embedding its own source) avoids any
// self-referential embedding loop. It is absent in inline/standalone documents.
const CMH_ASSETS = (typeof window !== "undefined" && window.__COMMENTABLE_ASSETS__) || null;
// NonPortable = the layer's CSS/JS live in companion files next to this HTML. Detected
// by the presence of the assets registry OR an external commentable-html script.
const NONPORTABLE_MODE = !!CMH_ASSETS
  || !!document.querySelector('script[src*="commentable-html"], link[href*="commentable-html"]');
function declaredAssetVersion() {
  const meta = document.querySelector('meta[name="commentable-html-version"]');
  return meta ? (meta.getAttribute("content") || "").trim() : "";
}
function parseSemver(s) {
  const m = String(s || "").trim().match(/^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$/);
  if (!m) return null;
  return { major: Number(m[1]), minor: Number(m[2]), patch: Number(m[3]) };
}
function compareSemver(a, b) {
  if (a.major !== b.major) return a.major - b.major;
  if (a.minor !== b.minor) return a.minor - b.minor;
  return a.patch - b.patch;
}
function runtimeCompatibleWith(pageVer, runtimeVer) {
  const page = parseSemver(pageVer);
  const runtime = parseSemver(runtimeVer);
  if (!page || !runtime) return null;
  if (page.major !== runtime.major) return { kind: "major", page, runtime };
  if (compareSemver(runtime, page) < 0) return { kind: "runtime-older", page, runtime };
  return { kind: "compatible", page, runtime };
}

const sidebar = document.getElementById("sidebar");
const listEl = document.getElementById("commentList");
const menu = document.getElementById("contextMenu");
const toast = document.getElementById("toast");
const toolbarCount = document.getElementById("toolbarCount");
const sidebarCount = document.getElementById("sidebarCount");

let comments = [];
let pendingRange = null;
let pendingQuote = "";

const openComposers = new Set();
const openEditComposers = new Map();
let lastFocusedComposer = null;
let composerZ = 210;

/* ---------- Persistence ---------- */
function loadComments() {
  let local = [];
  try {
    const raw = localStorage.getItem(COMMENT_KEY);
    local = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(local)) local = [];
  } catch (e) { local = []; }
  // Exclude embedded comments that were deleted in a prior session (tombstoned), so a
  // baked-in comment stays deleted across reload instead of resurrecting from the file.
  const tomb = _deletedEmbeddedIds();
  const embedded = getEmbeddedComments().filter(function (c) { return !(c && tomb.has(c.id)); });
  comments = mergeCommentSets(local, embedded);
  // If the merge changed localStorage, persist so reloads converge.
  try {
    if (JSON.stringify(comments) !== JSON.stringify(local)) saveComments();
  } catch (e) { /* serialization noise, ignore */ }
}
function saveComments() {
  try { localStorage.setItem(COMMENT_KEY, JSON.stringify(comments)); return true; }
  catch (e) {
    // Storage full or blocked: the comment is still in memory (visible in the list),
    // but it will not survive a reload. Surface this as an alert with a recovery path
    // instead of letting the save look successful.
    showToast("Comment NOT saved to this browser (storage full or blocked) - it will be lost on "
      + "reload. Use Copy all or Export as Portable to keep it.", { alert: true, duration: 8000 });
    return false;
  }
}
const CMH_DELETED_KEY = COMMENT_KEY + "::deleted";
function _deletedEmbeddedIds() {
  try {
    const a = JSON.parse(localStorage.getItem(CMH_DELETED_KEY) || "[]");
    return new Set(Array.isArray(a) ? a.filter(id => SAFE_ID_RE.test(id)) : []);
  } catch (e) { return new Set(); }
}
// Record that embedded-in-file comment ids were deleted this session, so a reload does
// not re-merge them back in from the baked-in embeddedComments block.
function _tombstoneEmbedded(ids) {
  const emb = _embeddedCommentSig();
  const t = _deletedEmbeddedIds();
  let changed = false;
  (ids || []).forEach(function (id) { if (id && emb.has(id) && !t.has(id)) { t.add(id); changed = true; } });
  if (changed) { try { localStorage.setItem(CMH_DELETED_KEY, JSON.stringify([...t])); } catch (e) { /* ignore */ } }
}
function commentTimestamp(c) {
  return (c && (c.updatedAt || c.createdAt)) || "";
}
// Merge two comment arrays by id. For each id present in both, keep the
// entry with the later updatedAt (fallback createdAt). Ids only in one
// side pass through. Order is preserved best-effort (a first, then new
// b entries appended). Entries whose id fails SAFE_ID_RE are dropped here
// (the single load/merge choke point), so an unsafe id from localStorage or
// the embeddedComments block can never reach a data-cid attribute or selector.
function mergeCommentSets(a, b) {
  const map = new Map();
  const order = [];
  for (const c of (a || [])) {
    if (!c || !c.id || !SAFE_ID_RE.test(c.id)) continue;
    const existing = map.get(c.id);
    if (!existing) {
      map.set(c.id, c);
      order.push(c.id);            // dedupe: an id repeated in the persisted array appears once
    } else if (commentTimestamp(c) > commentTimestamp(existing)) {
      map.set(c.id, c);
    }
  }
  for (const c of (b || [])) {
    if (!c || !c.id || !SAFE_ID_RE.test(c.id)) continue;
    const existing = map.get(c.id);
    if (!existing) {
      map.set(c.id, c);
      order.push(c.id);
    } else if (commentTimestamp(c) > commentTimestamp(existing)) {
      map.set(c.id, c);
    }
  }
  return order.map(id => map.get(id));
}
function getEmbeddedComments() {
  const el = document.getElementById("embeddedComments");
  if (!el) return [];
  try {
    const arr = JSON.parse((el.textContent || "").trim() || "[]");
    return Array.isArray(arr) ? arr : [];
  } catch (e) {
    console.warn("Could not parse embeddedComments JSON:", e);
    return [];
  }
}

/* ---------- Text-offset helpers ---------- */
function getTextNodes() {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      if (!n.nodeValue) return NodeFilter.FILTER_REJECT;
      if (n.parentElement && n.parentElement.closest(".cm-skip"))
        return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const arr = [];
  let n;
  while ((n = walker.nextNode())) arr.push(n);
  return arr;
}
function firstTextNodeIn(el) {
  const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      if (!n.nodeValue) return NodeFilter.FILTER_REJECT;
      if (n.parentElement && n.parentElement.closest(".cm-skip")) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  return w.nextNode();
}
function lastTextNodeIn(el) {
  const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      if (!n.nodeValue) return NodeFilter.FILTER_REJECT;
      if (n.parentElement && n.parentElement.closest(".cm-skip")) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  let last = null, n;
  while ((n = w.nextNode())) last = n;
  return last;
}
// A selection boundary can land on an ELEMENT node (element, childIndex) instead of a
// text node - browsers do this when a selection starts or ends at the very edge of a
// block, e.g. selecting a heading from its start yields (h3, 0). offsetWithin only
// matches text nodes, so an element boundary returned -1 and aborted anchoring
// ("Could not anchor that selection"). Resolve such a boundary to the equivalent
// (textNode, offset) using the same cm-skip filter as getTextNodes.
function acceptableTextNode(n) {
  return !!(n && n.nodeType === 3 && n.nodeValue &&
    !(n.parentElement && n.parentElement.closest(".cm-skip")));
}
function normalizeBoundary(node, off) {
  if (!node || node.nodeType === 3) return [node, off];
  if (node.nodeType !== 1) return [node, off];
  const kids = node.childNodes;
  for (let i = off; i < kids.length; i++) {
    const k = kids[i];
    const t = acceptableTextNode(k) ? k : (k.nodeType === 1 ? firstTextNodeIn(k) : null);
    if (t) return [t, 0];
  }
  for (let i = Math.min(off, kids.length) - 1; i >= 0; i--) {
    const k = kids[i];
    const t = acceptableTextNode(k) ? k : (k.nodeType === 1 ? lastTextNodeIn(k) : null);
    if (t) return [t, t.nodeValue.length];
  }
  return [node, off];
}
function offsetWithin(node, off) {
  [node, off] = normalizeBoundary(node, off);
  const nodes = getTextNodes();
  let total = 0;
  for (const tn of nodes) {
    if (tn === node) return total + off;
    total += tn.nodeValue.length;
  }
  // The boundary normalized to a node that is not one of the counted text nodes -
  // typically a cm-skip element (e.g. an injected section caret) that a triple-click
  // or other block selection swept in just past the real text. If that node is still
  // inside the comment root, resolve the boundary by DOCUMENT POSITION: the summed
  // length of every counted text node lying at or before the boundary point. A
  // boundary outside the root stays rejected so cross-region selections still fail.
  if (!node || !root.contains(node)) return -1;
  total = 0;
  for (const tn of nodes) {
    if (_comparePointAt(tn, tn.nodeValue.length, node, off) <= 0) { total += tn.nodeValue.length; continue; }
    if (_comparePointAt(tn, 0, node, off) < 0) {
      const sub = document.createRange();
      sub.setStart(tn, 0); sub.setEnd(node, off);
      total += sub.toString().length;
    }
    break;
  }
  return total;
}
// Document-order comparison of two boundary points: -1 if (a,ao) precedes (b,bo),
// 0 if equal, 1 if it follows. Used to place a boundary that landed on a cm-skip node.
function _comparePointAt(a, ao, b, bo) {
  const r = document.createRange();
  r.setStart(b, bo); r.setEnd(b, bo);
  try { return r.comparePoint(a, ao); } catch (e) { return 1; }
}
function rangeFromOffsets(start, end) {
  const nodes = getTextNodes();
  let total = 0;
  const range = document.createRange();
  let sSet = false, eSet = false;
  for (const tn of nodes) {
    const next = total + tn.nodeValue.length;
    if (!sSet && start >= total && start <= next) { range.setStart(tn, start - total); sSet = true; }
    if (!eSet && end   >= total && end   <= next) { range.setEnd(tn,   end   - total); eSet = true; }
    if (sSet && eSet) return range;
    total = next;
  }
  return null;
}

/* ---------- Context capture (section + surrounding text) ---------- */
const CTX_PAD = 80;
const BLOCK_TAG_RE = /^(P|LI|TD|TH|H[1-6]|BLOCKQUOTE|PRE|DD|DT|FIGCAPTION|CAPTION|ARTICLE|SECTION|ASIDE)$/;
const MAX_BLOCK_LEN = 280;
function captureContext(start, end, range) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
    acceptNode(n) {
      if (n.nodeType === 1) {
        if (n.closest(".cm-skip")) return NodeFilter.FILTER_REJECT;
        return /^H[1-6]$/i.test(n.tagName) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
      }
      if (n.parentElement && n.parentElement.closest(".cm-skip")) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  let total = 0, full = "";
  const headings = [];
  let n;
  while ((n = walker.nextNode())) {
    if (n.nodeType === 1) {
      headings.push({
        offset: total,
        level: parseInt(n.tagName.slice(1), 10),
        text: n.textContent.trim().replace(/\s+/g, " "),
      });
      continue;
    }
    full += n.nodeValue;
    total += n.nodeValue.length;
  }
  const beforeRaw = full.slice(Math.max(0, start - CTX_PAD), start);
  const afterRaw  = full.slice(end, Math.min(full.length, end + CTX_PAD));
  const before = (start > CTX_PAD ? "..." : "") + beforeRaw.replace(/\s+/g, " ").trimStart();
  const after  = afterRaw.replace(/\s+/g, " ").trimEnd() + (end + CTX_PAD < full.length ? "..." : "");

  const headingPath = [];
  let curOffset = 0;
  for (const h of headings) {
    if (h.offset > start) break;
    while (headingPath.length && headingPath[headingPath.length - 1].level >= h.level) headingPath.pop();
    headingPath.push(h);
    curOffset = h.offset;
  }
  const section = headingPath.length ? headingPath[headingPath.length - 1].text : null;
  const curLevel = headingPath.length ? headingPath[headingPath.length - 1].level : 0;
  let sectionEnd = full.length;
  for (const h of headings) {
    if (h.offset <= curOffset) continue;
    if (h.level <= curLevel) { sectionEnd = h.offset; break; }
  }
  const quote = full.slice(start, end);
  let occurrence = 0, occurrenceTotal = 0;
  if (quote.length > 0) {
    const sectionText = full.slice(curOffset, sectionEnd);
    const localStart = start - curOffset;
    let idx = 0;
    while ((idx = sectionText.indexOf(quote, idx)) !== -1) {
      occurrenceTotal++;
      if (idx <= localStart) occurrence++;
      idx += Math.max(1, quote.length);
    }
  }
  let blockTag = null, blockText = null, isCode = false, codeLanguage = null;
  if (range) {
    let el = range.startContainer;
    if (el && el.nodeType !== 1) el = el.parentElement;
    // Treat the selection as "code" only when it is inside a <pre> block (optionally
    // wrapping an inner <code>). Inline <code> in prose must NOT flip isCode, otherwise
    // we lose prose context (In context / Containing <p>) and emit a fenced code block
    // for a normal sentence that just happened to mention `foo`.
    const preAnc = el ? el.closest("pre") : null;
    if (preAnc) {
      isCode = true;
      const inlineCodeEl = el ? el.closest("code") : null;
      const codeEl = (inlineCodeEl && preAnc.contains(inlineCodeEl))
        ? inlineCodeEl
        : preAnc.querySelector("code");
      if (codeEl) {
        for (const cls of codeEl.classList) {
          const m = /^language-(.+)$/i.exec(cls);
          if (m) { codeLanguage = m[1].toLowerCase(); break; }
        }
      }
    }
    while (el && el !== root && !BLOCK_TAG_RE.test(el.tagName)) el = el.parentElement;
    if (el && el !== root) {
      blockTag = el.tagName.toLowerCase();
      const raw = (el.textContent || "").trim().replace(/\s+/g, " ");
      blockText = raw.length > MAX_BLOCK_LEN ? raw.slice(0, MAX_BLOCK_LEN) + "..." : raw;
    }
  }
  return {
    section,
    headingPath: headingPath.map(h => ({ level: h.level, text: h.text })),
    before, after,
    occurrence, occurrenceTotal,
    blockTag, blockText,
    isCode, codeLanguage,
  };
}
function backfillContext() {
  let changed = false;
  for (const c of comments) {
    const hasAll = c.section !== undefined && c.before !== undefined && c.after !== undefined &&
                   c.headingPath !== undefined && c.occurrence !== undefined && c.blockTag !== undefined &&
                   c.isCode !== undefined;
    if (hasAll) continue;
    if (typeof c.start !== "number" || typeof c.end !== "number") continue;
    const range = rangeFromOffsets(c.start, c.end);
    const ctx = captureContext(c.start, c.end, range);
    Object.assign(c, ctx);
    changed = true;
  }
  if (changed) saveComments();
}
function wrapRangeWithMark(range, id) {
  const nodes = getTextNodes();
  const toWrap = nodes.filter(n => range.intersectsNode(n));
  toWrap.forEach(tn => {
    let s = 0, e = tn.nodeValue.length;
    if (tn === range.startContainer) s = range.startOffset;
    if (tn === range.endContainer)   e = range.endOffset;
    if (s >= e) return;
    if (e < tn.nodeValue.length) tn.splitText(e);
    let target = tn;
    if (s > 0) target = tn.splitText(s);
    const m = document.createElement("mark");
    m.className = "cm-hl";
    m.dataset.cid = id;
    target.parentNode.insertBefore(m, target);
    m.appendChild(target);
  });
}
function unwrapMarks(id) {
  root.querySelectorAll(`mark.cm-hl[data-cid="${id}"]`).forEach(m => {
    const parent = m.parentNode;
    while (m.firstChild) parent.insertBefore(m.firstChild, m);
    parent.removeChild(m);
    parent.normalize();
  });
}
function removeHighlight(comment) {
  if (!comment) return;
  if (comment.anchorType === "mermaid") clearMermaidHighlight(comment.id);
  else if (comment.anchorType === "diff") clearDiffHighlight(comment.id);
  else if (comment.anchorType === "image") clearImageHighlight(comment.id);
  else if (comment.anchorType === "widget") clearWidgetHighlight(comment.id);
  else if (comment.anchorType === "document") { /* no anchored highlight to remove */ }
  else unwrapMarks(comment.id);
}

/* ---------- Mermaid commenting layer ----------
   Lets the user click rendered diagram nodes inside
   pre.mermaid / div.mermaid blocks and attach a comment.
   Anchors by (diagramIndex, nodeKey) rather than text
   offsets. mermaid renders asynchronously, so a per-host
   MutationObserver waits for SVG insertion before
   attaching handlers and restoring highlights. */
const mermaidAddBtn = document.getElementById("mermaidAddBtn");
const mermaidDiagrams = [];
let pendingMermaid = null;
let mermaidAddHideTimer = null;
let mermaidActiveNode = null;
// The floating add-comment buttons (image / mermaid / diff) are position:fixed and
// positioned once at hover time. `_activeAdd` remembers the currently-shown one and
// how to re-run its positioning, so a scroll/resize can keep it pinned to its target
// (or hide it when the target scrolls out of view) instead of letting it drift.
let _activeAdd = null;
// True when the button's natural (unclamped) anchor sits comfortably on-screen. A
// scroll reposition hides a button whose target scrolled (partly) out of view rather
// than clamping it to a viewport edge, where it would look detached from its target.
function _addFits(left, top, w, h) {
  return left >= 8 && left <= window.innerWidth - w - 8 &&
         top >= 8 && top <= window.innerHeight - h - 8;
}
// Whether an anchor rect is at least partially within the viewport. Used to decide
// whether a floating add button should stay (anchor visible) or hide (anchor scrolled
// away). The button position itself is clamped on-screen separately, so an anchor near
// a viewport edge must NOT be treated as "gone".
function _rectInViewport(r) {
  return r.width > 0 && r.height > 0 &&
    r.bottom > 4 && r.top < window.innerHeight - 4 &&
    r.right > 4 && r.left < window.innerWidth - 4;
}
function _clipContainerFor(node) {
  const el = node && (node.nodeType === 1 ? node : node.parentElement);
  return el && el.closest ? el.closest("pre.mermaid, figure.chart, table, .cmh-diff-raw") : null;
}
function _intersectRects(a, b) {
  const left = Math.max(a.left, b.left);
  const right = Math.min(a.right, b.right);
  const top = Math.max(a.top, b.top);
  const bottom = Math.min(a.bottom, b.bottom);
  if (right <= left || bottom <= top) return null;
  return { left, right, top, bottom, width: right - left, height: bottom - top };
}
function _clipAwareRect(node, rect) {
  let visible = _intersectRects(rect, {
    left: 4, right: window.innerWidth - 4, top: 4, bottom: window.innerHeight - 4,
  });
  if (!visible) return null;
  const clip = _clipContainerFor(node);
  if (clip) visible = _intersectRects(visible, clip.getBoundingClientRect());
  return visible;
}
function _floatingBounds(node) {
  const clip = _clipContainerFor(node);
  const viewport = { left: 8, right: window.innerWidth - 8, top: 8, bottom: window.innerHeight - 8 };
  if (!clip) return viewport;
  const clipped = _intersectRects(viewport, clip.getBoundingClientRect());
  return clipped || viewport;
}
function _clamp(v, min, max) {
  if (max < min) return min;
  return Math.max(min, Math.min(v, max));
}
function cmRectContains(outer, inner) {
  return inner.left >= outer.left - 1 && inner.right <= outer.right + 1 &&
         inner.top >= outer.top - 1 && inner.bottom <= outer.bottom + 1;
}

// Commentable mermaid elements across diagram types. Flowchart uses g.node/g.cluster/
// g.edgeLabel; gantt/sequence expose text-bearing elements (task labels, messages,
// notes) which give stable, descriptive anchor keys. MERMAID_RENDERED_SEL is the wider
// "the diagram has painted meaningful content" probe used for readiness (a gantt has no
// g.node, so the flowchart-only probe never fired for it).
var MERMAID_NODE_SEL = "g.node, g.cluster, g.edgeLabel, .task, .taskText, .taskTextOutsideRight, .taskTextOutsideLeft, .taskTextOutsideCenter, .messageText, .noteText, .loopText, .actor";
// Readiness probe: every node-commentable element (svg-scoped) PLUS a couple of markers
// that only signal "rendered" (pie slices are paths that fall through to whole-diagram).
// Derived from MERMAID_NODE_SEL so the two can never drift.
var MERMAID_RENDERED_SEL = MERMAID_NODE_SEL.split(", ").map(function (s) { return "svg " + s; }).join(", ") + ", svg .pieCircle";

function indexMermaidDiagrams() {
  mermaidDiagrams.length = 0;
  const hosts = root.querySelectorAll("pre.mermaid, div.mermaid");
  hosts.forEach((host, i) => {
    host.classList.add("cm-mermaid-host");
    host.dataset.cmMermaidIndex = String(i);
    // Preserve the diagram source for Markdown export before mermaid replaces the element
    // content with rendered SVG (after which textContent would be SVG text, not the source).
    if (!host.hasAttribute("data-cmh-md-src") && !host.querySelector("svg") && !host.hasAttribute("data-processed")) {
      host.setAttribute("data-cmh-md-src", host.textContent || "");
    }
    mermaidDiagrams.push(host);
  });
}
function mermaidHostForIndex(i) { return mermaidDiagrams[i] || null; }
function mermaidNodeKey(nodeEl) {
  const ds = nodeEl.dataset && nodeEl.dataset.id;
  if (ds) return ds;
  const rawId = nodeEl.id || "";
  const m = rawId.match(/^(?:flowchart|class|state|er|gantt|sequence|mindmap|timeline)[-_](.+?)(?:[-_]\d+)?$/);
  if (m && m[1]) return m[1];
  const label = mermaidNodeLabel(nodeEl);
  if (label) return "label:" + label.slice(0, 200);
  if (rawId) return "id:" + rawId;   // e.g. gantt task bars (rect id) with no own text
  return "label:";
}
function mermaidNodeLabel(nodeEl) {
  return (nodeEl.textContent || "").trim().replace(/\s+/g, " ");
}
function findMermaidNode(diagramIndex, nodeKey) {
  const host = mermaidHostForIndex(diagramIndex);
  if (!host) return null;
  if (nodeKey === "__diagram__") return host; // whole-diagram anchor
  const candidates = host.querySelectorAll(MERMAID_NODE_SEL);
  for (const n of candidates) {
    if (mermaidNodeKey(n) === nodeKey) return n;
  }
  if (nodeKey && nodeKey.startsWith("label:")) {
    const want = nodeKey.slice(6);
    for (const n of candidates) {
      if (mermaidNodeLabel(n) === want) return n;
    }
  }
  if (nodeKey && nodeKey.startsWith("id:")) {
    const want = nodeKey.slice(3);
    for (const n of candidates) {
      if ((n.id || "") === want) return n;
    }
  }
  return null;
}
function applyMermaidHighlight(comment) {
  const node = findMermaidNode(comment.diagramIndex, comment.nodeKey);
  if (!node) return false;
  // A node can carry several comments; track them all in data-cids (first in
  // data-cid for legacy selectors), like the diff-row and image layers.
  node.classList.add("cm-mermaid-hl");
  const cids = (node.getAttribute("data-cids") || "").split(/\s+/).filter(Boolean);
  if (!cids.includes(comment.id)) cids.push(comment.id);
  node.setAttribute("data-cids", cids.join(" "));
  node.setAttribute("data-cid", cids[0]);
  return true;
}
function clearMermaidHighlight(id) {
  root.querySelectorAll(".cm-mermaid-hl").forEach(n => {
    const cids = (n.getAttribute("data-cids") || n.getAttribute("data-cid") || "").split(/\s+/).filter(Boolean);
    const rest = cids.filter(c => c !== id);
    if (rest.length === cids.length) return;
    if (rest.length) {
      n.setAttribute("data-cids", rest.join(" "));
      n.setAttribute("data-cid", rest[0]);
    } else {
      n.classList.remove("cm-mermaid-hl", "cm-mermaid-active");
      n.removeAttribute("data-cid");
      n.removeAttribute("data-cids");
    }
  });
}
function flashMermaid(id) {
  const node = [...root.querySelectorAll(".cm-mermaid-hl")].find(n =>
    (n.getAttribute("data-cids") || n.getAttribute("data-cid") || "").split(/\s+/).includes(id));
  if (!node) return;
  node.classList.add("cm-mermaid-active");
  setTimeout(() => node.classList.remove("cm-mermaid-active"), 2200);
}
function captureMermaidContext(host) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, {
    acceptNode(n) {
      if (n.closest(".cm-skip") && !host.contains(n)) return NodeFilter.FILTER_REJECT;
      return /^H[1-6]$/i.test(n.tagName) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    },
  });
  const headings = [];
  let n;
  while ((n = walker.nextNode())) {
    if (host.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING) break;
    headings.push({ level: parseInt(n.tagName.slice(1), 10), text: n.textContent.trim().replace(/\s+/g, " ") });
  }
  const headingPath = [];
  for (const h of headings) {
    while (headingPath.length && headingPath[headingPath.length - 1].level >= h.level) headingPath.pop();
    headingPath.push(h);
  }
  return {
    section: headingPath.length ? headingPath[headingPath.length - 1].text : null,
    headingPath,
  };
}
function positionMermaidAdd(node) {
  const rect = node.getBoundingClientRect();
  const visible = _clipAwareRect(node, rect);
  if (!visible) return false;
  const btnW = mermaidAddBtn.offsetWidth || 120;
  const btnH = mermaidAddBtn.offsetHeight || 28;
  const bounds = _floatingBounds(node);
  const left = visible.right - btnW;
  let top  = visible.top - btnH - 4;
  if (top < bounds.top) top = visible.bottom + 4;
  mermaidAddBtn.style.left = _clamp(left, bounds.left, bounds.right - btnW) + "px";
  mermaidAddBtn.style.top  = _clamp(top, bounds.top, bounds.bottom - btnH) + "px";
  return true;
}
function showMermaidAddFor(node, host) {
  const rect = node.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return;
  pendingMermaid = {
    diagramIndex: parseInt(host.dataset.cmMermaidIndex, 10) || 0,
    nodeKey: mermaidNodeKey(node),
    nodeLabel: mermaidNodeLabel(node),
  };
  if (mermaidAddHideTimer) { clearTimeout(mermaidAddHideTimer); mermaidAddHideTimer = null; }
  mermaidAddBtn.hidden = false;
  mermaidAddBtn.textContent = "Add Comment";
  if (!positionMermaidAdd(node)) { mermaidAddBtn.hidden = true; pendingMermaid = null; return; }
  _activeAdd = { el: node, btn: mermaidAddBtn, position: () => positionMermaidAdd(node), clear: () => { pendingMermaid = null; } };
}
function mermaidDiagramLabel(host) {
  const t = host.querySelector(".titleText, text.title, .title, .cmh-diagram-title");
  const s = t && (t.textContent || "").trim().replace(/\s+/g, " ");
  return s ? ("diagram: " + s) : "entire diagram";
}
// Whole-diagram affordance: shown when hovering the diagram's empty area (e.g. the
// middle of a gantt timeline) so the ENTIRE graph is commentable, not only nodes.
function showMermaidWholeFor(host) {
  const svg = host.querySelector("svg");
  const rect = (svg || host).getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return false;
  pendingMermaid = {
    diagramIndex: parseInt(host.dataset.cmMermaidIndex, 10) || 0,
    nodeKey: "__diagram__",
    nodeLabel: mermaidDiagramLabel(host),
  };
  if (mermaidAddHideTimer) { clearTimeout(mermaidAddHideTimer); mermaidAddHideTimer = null; }
  mermaidAddBtn.hidden = false;
  mermaidAddBtn.textContent = "Comment on diagram";
  const bw = mermaidAddBtn.offsetWidth || 160, bh = mermaidAddBtn.offsetHeight || 28;
  const left = rect.right - bw - 6, top = rect.top + 6;
  mermaidAddBtn.style.left = Math.max(8, Math.min(left, window.innerWidth - bw - 8)) + "px";
  mermaidAddBtn.style.top = Math.max(8, Math.min(top, window.innerHeight - bh - 8)) + "px";
  _activeAdd = { el: host, btn: mermaidAddBtn, position: () => showMermaidWholeFor(host), clear: () => { pendingMermaid = null; } };
  return _rectInViewport(rect);
}
function scheduleHideMermaidAdd() {
  if (mermaidAddHideTimer) clearTimeout(mermaidAddHideTimer);
  mermaidAddHideTimer = setTimeout(() => {
    if (!mermaidAddBtn.matches(":hover")) { mermaidAddBtn.hidden = true; mermaidActiveNode = null; pendingMermaid = null; }
  }, 220);
}
function attachMermaidHostHandlers(host) {
  if (host._cmAttached) return;
  host._cmAttached = true;
  host.addEventListener("mousemove", (e) => {
    const node = e.target.closest && e.target.closest(MERMAID_NODE_SEL);
    if (node && host.contains(node)) {
      // Re-show even if the sentinel still points here but the button was hidden
      // (e.g. after a prior comment add/delete hid it).
      if (node === mermaidActiveNode && !mermaidAddBtn.hidden) return;
      // While the button is showing for a node, moving toward it crosses the
      // surrounding subgraph cluster. Don't let that ancestor cluster hijack the
      // button (it would jump to the cluster corner). Keep the current node.
      if (!mermaidAddBtn.hidden && mermaidActiveNode && mermaidActiveNode.classList &&
          node.classList && node.classList.contains("cluster") &&
          cmRectContains(node.getBoundingClientRect(), mermaidActiveNode.getBoundingClientRect())) {
        return;
      }
      mermaidActiveNode = node;
      showMermaidAddFor(node, host);
      return;
    }
    // Empty diagram area (e.g. the middle of a gantt): offer commenting on the whole graph.
    if (!host.querySelector("svg")) return;
    // Don't let a stray empty-area mousemove clobber an active NODE affordance while the
    // pointer is heading to the (fixed) Add button - that would swap a node comment for a
    // whole-diagram comment on click. Only offer whole-diagram when no node button shows.
    if (mermaidActiveNode && mermaidActiveNode !== host && !mermaidAddBtn.hidden) return;
    if (mermaidActiveNode === host && !mermaidAddBtn.hidden) return;
    mermaidActiveNode = host;
    showMermaidWholeFor(host);
  });
  host.addEventListener("mouseleave", scheduleHideMermaidAdd);
  host.addEventListener("click", (e) => {
    const hl = e.target.closest && e.target.closest(".cm-mermaid-hl");
    if (!hl) return;
    const id = hl.getAttribute("data-cid");
    if (!id) return;
    openSidebar();
    const card = listEl.querySelector(`.cm-card[data-cid="${id}"]`);
    if (card) { card.scrollIntoView({ behavior: "smooth", block: "center" }); flashActive(id); }
    flashMermaid(id);
  });
}
mermaidAddBtn.addEventListener("mouseenter", () => {
  if (mermaidAddHideTimer) { clearTimeout(mermaidAddHideTimer); mermaidAddHideTimer = null; }
});
mermaidAddBtn.addEventListener("mouseleave", scheduleHideMermaidAdd);
mermaidAddBtn.addEventListener("click", () => {
  if (!pendingMermaid) return;
  const info = pendingMermaid;
  pendingMermaid = null;
  mermaidAddBtn.hidden = true;
  mermaidActiveNode = null;
  openMermaidComposer(info);
});
function openMermaidComposer(info) {
  return createComposerElement({ mode: "new-mermaid", mermaid: info });
}
function setupMermaidLayer() {
  indexMermaidDiagrams();
  if (!mermaidDiagrams.length) return;
  // Readiness signal: mermaid v9+ stamps data-processed="true" on the host
  // once it has finished rendering the SVG. Falls back to checking for
  // populated nodes in case a different renderer is in use.
  const isReady = (host) =>
    host.dataset.processed === "true" ||
    !!host.querySelector(MERMAID_RENDERED_SEL);
  const restoreForHost = (host) => {
    // Defer one frame: mermaid stamps data-processed before the SVG nodes
    // are actually in the DOM in some versions, so highlight application
    // must wait until the painted nodes exist.
    const apply = () => {
      const i = parseInt(host.dataset.cmMermaidIndex, 10) || 0;
      comments.forEach(c => {
        if (c.anchorType === "mermaid" && c.diagramIndex === i) applyMermaidHighlight(c);
      });
      attachMermaidHostHandlers(host);
    };
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(apply);
    else setTimeout(apply, 0);
  };
  mermaidDiagrams.forEach(host => {
    if (isReady(host) && host.querySelector(MERMAID_RENDERED_SEL)) {
      restoreForHost(host);
      return;
    }
    const obs = new MutationObserver((_m, observer) => {
      if (isReady(host) && host.querySelector(MERMAID_RENDERED_SEL)) {
        observer.disconnect();
        restoreForHost(host);
      }
    });
    obs.observe(host, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-processed"] });
  });
}

/* ---------- Diff / code-review layer ----------
   Renders unified-diff blocks (pre.cmh-diff / div.cmh-diff) into a colored
   review view with a per-block toggle between side-by-side and inline layouts.
   Diff lines are commentable: hovering a changed/context line shows a
   "+ comment" button and the comment anchors by (diffIndex, lineKey) - a
   structural anchor, like mermaid nodes - so it survives the layout toggle,
   reload, copy, and Export as Portable. The rendered view lives inside a .cm-skip
   host so diff text stays out of the text-offset system, and the raw unified
   diff is preserved in a hidden <script class="cmh-diff-src"> so an exported
   file re-renders on open. */
const CMH_DIFF_LAYOUT_KEY = COMMENT_KEY + "::diffLayout";
const diffBlocks = [];
const diffAddBtn = document.getElementById("diffAddBtn");
let pendingDiff = null;
let pendingDiffSel = null;
let diffAddHideTimer = null;
let diffActiveLineEl = null;

// Store the raw diff inside the hidden <script class="cmh-diff-src"> as base64 so
// that a diff OF markup (whose decoded text can contain a literal closing script
// tag) can never break out of that script element when the rendered host is
// serialized by a save/export path. btoa is Latin1-only, so round-trip via UTF-8
// bytes. Older saved files store the raw diff as plain text (no data-enc) and are
// still read verbatim.
function _b64EncodeUtf8(s) {
  const bytes = new TextEncoder().encode(String(s == null ? "" : s));
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}
function _b64DecodeUtf8(s) {
  try {
    const bin = atob(String(s == null ? "" : s).replace(/\s+/g, ""));
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new TextDecoder().decode(bytes);
  } catch (e) { return ""; }
}

function defaultDiffLayout() {
  // Default to side-by-side; a persisted "inline" choice is honored.
  try {
    const v = localStorage.getItem(CMH_DIFF_LAYOUT_KEY);
    return v === "inline" ? "inline" : "split";
  } catch (e) { return "split"; }
}
function setDefaultDiffLayout(layout) {
  try { localStorage.setItem(CMH_DIFF_LAYOUT_KEY, layout); } catch (e) { /* ignore */ }
}

/* ---------- Diff syntax highlighting (runtime, self-contained, default ON) ----------
   A compact tokenizer emitting the same .cmh-code-* classes as the author-time
   tools/highlight_code.py, applied to each diff line's code. Diff comments anchor
   structurally (diffIndex + lineKey + side), never by text offset, and the diff
   host is cm-skip, so wrapping tokens in spans is anchor-safe. Each line is
   highlighted independently (no cross-line block comments). A per-document toggle
   (default ON) is persisted. */
const CMH_DIFF_HL_KEY = COMMENT_KEY + "::diffSyntax";
let _diffSyntaxMem = null; // in-memory fallback when localStorage is unavailable
function diffSyntaxOn() {
  try {
    const v = localStorage.getItem(CMH_DIFF_HL_KEY);
    if (v !== null) return v !== "off";
  } catch (e) { /* storage blocked - use memory */ }
  return _diffSyntaxMem === null ? true : _diffSyntaxMem;
}
function setDiffSyntaxOn(on) {
  _diffSyntaxMem = !!on; // remember in-session even if storage throws
  try { localStorage.setItem(CMH_DIFF_HL_KEY, on ? "on" : "off"); } catch (e) { /* non-persistent */ }
}
const _HL_FAMILY = {
  javascript: "c", js: "c", jsx: "c", typescript: "c", ts: "c", tsx: "c", java: "c", c: "c", cpp: "c",
  "c++": "c", cs: "c", csharp: "c", go: "c", golang: "c", rust: "c", rs: "c", php: "c", swift: "c",
  kotlin: "c", kt: "c", scala: "c", dart: "c", json: "c", groovy: "c", objectivec: "c", objc: "c",
  python: "hash", py: "hash", ruby: "hash", rb: "hash", shell: "hash", bash: "hash", sh: "hash",
  yaml: "hash", yml: "hash", toml: "hash", perl: "hash", pl: "hash", r: "hash", elixir: "hash", ex: "hash", exs: "hash",
  sql: "sql",
  css: "css", lua: "lua", haskell: "haskell", hs: "haskell",
  powershell: "powershell", ps1: "powershell", ps: "powershell",
  batch: "batch", bat: "batch", cmd: "batch",
};
const _EXT_LANG = {
  py: "python", js: "javascript", jsx: "javascript", mjs: "javascript", ts: "typescript", tsx: "typescript",
  java: "java", c: "c", h: "c", cpp: "cpp", cc: "cpp", hpp: "cpp", cs: "csharp", go: "go", rs: "rust",
  rb: "ruby", php: "php", swift: "swift", kt: "kotlin", scala: "scala", sql: "sql", sh: "shell",
  bash: "shell", yml: "yaml", yaml: "yaml", toml: "toml", json: "json", css: "css", lua: "lua",
  hs: "haskell", ex: "elixir", exs: "elixir", ps1: "powershell", bat: "batch", cmd: "batch",
  groovy: "groovy", gradle: "groovy", pl: "perl", r: "r", m: "objectivec", mm: "objectivec",
};
function inferDiffLang(el, label) {
  const explicit = (el.getAttribute("data-diff-lang") || "").trim().toLowerCase();
  if (explicit) return explicit;
  const m = /\.([A-Za-z0-9]+)\s*$/.exec(label || "");
  return m ? (_EXT_LANG[m[1].toLowerCase()] || "") : "";
}
function diffLangKnown(lang) { return !!(lang && _HL_FAMILY[String(lang).toLowerCase()]); }
const _HL_KW_SET = new Set(("abstract as async await base bool boolean break byte case catch char class const continue "
  + "def default defer del delete do double elif else enum event export extends final finally float fn for foreach from "
  + "func function global go goto if impl implements import in include instanceof int interface is lambda let long match "
  + "module mut namespace new nil none not null object or override package pass private protected public raise readonly "
  + "ref return self short static struct super switch synchronized template this throw throws trait try type typedef "
  + "typeof union unsafe use using var virtual void volatile when where while with yield true false and "
  + "cond defmacro defmodule defp defstruct deriving elseif newtype quote unquote receive rescue repeat until").split(" "));
const _hlCache = {};
function _hlTokenRe(fam) {
  if (_hlCache[fam]) { _hlCache[fam].lastIndex = 0; return _hlCache[fam]; }
  // Unrolled, linear-time string forms (a failed/unterminated match resolves in one pass instead of
  // rescanning from every later quote). Double/backtick may omit the closer (unterminated highlights
  // to end of line); the single-quote form REQUIRES its closer so a lone ' (Rust lifetime, apostrophe,
  // digit separator) is not swallowed as a string. Block comments fall back to end-of-line ($).
  const dq = "\"[^\"\\\\]*(?:\\\\[\\s\\S][^\"\\\\]*)*\"?";
  const sq = "'[^'\\\\]*(?:\\\\[\\s\\S][^'\\\\]*)*'";
  const bt = "`[^`\\\\]*(?:\\\\[\\s\\S][^`\\\\]*)*`?";
  let com, str, flags = "g";
  if (fam === "hash") { com = "#[^\\n]*"; str = dq + "|" + sq; }
  else if (fam === "sql") { com = "/\\*[\\s\\S]*?(?:\\*/|$)|--[^\\n]*"; str = "'[^']*(?:''[^']*)*'"; flags = "gi"; }
  else if (fam === "css") { com = "/\\*[\\s\\S]*?(?:\\*/|$)"; str = dq + "|" + sq; }
  else if (fam === "lua") { com = "--\\[\\[[\\s\\S]*?(?:\\]\\]|$)|--[^\\n]*"; str = dq + "|" + sq; }
  else if (fam === "haskell") { com = "\\{-[\\s\\S]*?(?:-\\}|$)|--[^\\n]*"; str = dq; }
  else if (fam === "powershell") { com = "<#[\\s\\S]*?(?:#>|$)|#[^\\n]*"; str = dq + "|" + sq; flags = "gi"; }
  else if (fam === "batch") { com = "(?:rem\\b|::)[^\\n]*"; str = dq; flags = "gi"; }
  else { com = "/\\*[\\s\\S]*?(?:\\*/|$)|//[^\\n]*"; str = dq + "|" + sq + "|" + bt; }
  const num = "0[xX][0-9a-fA-F]+|\\d[\\d_]*(?:\\.\\d+)?(?:[eE][+-]?\\d+)?";
  const id = "[A-Za-z_$][A-Za-z0-9_$]*";
  const op = "[+\\-*/%=<>!&|^~?:.,;(){}\\[\\]]";
  const re = new RegExp("(?<com>" + com + ")|(?<str>" + str + ")|(?<num>" + num + ")|(?<id>" + id + ")|(?<op>" + op + ")", flags);
  _hlCache[fam] = re;
  return re;
}
function cmhHighlightCode(text, lang) {
  const fam = _HL_FAMILY[String(lang || "").toLowerCase()] || "c";
  const re = _hlTokenRe(fam);
  let out = "", last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out += escapeHtml(text.slice(last, m.index));
    const t = m[0], g = m.groups;
    let cls = null;
    if (g.com) cls = "com";
    else if (g.str) cls = "str";
    else if (g.num) cls = "num";
    else if (g.id) cls = _HL_KW_SET.has(re.ignoreCase ? t.toLowerCase() : t) ? "kw" : (text[re.lastIndex] === "(" ? "fn" : null);
    else if (g.op) cls = "op";
    out += cls ? ('<span class="cmh-code-' + cls + '">' + escapeHtml(t) + "</span>") : escapeHtml(t);
    last = re.lastIndex;
    if (m.index === re.lastIndex) re.lastIndex++;
  }
  if (last < text.length) out += escapeHtml(text.slice(last));
  return out;
}
function rerenderAllDiffs() {
  diffBlocks.forEach(b => { renderDiffBlock(b); applyDiffHighlightsForIndex(b.index); });
}

// Parse a unified diff into logical lines. Each carries a stable key (its index)
// so a comment keyed by (diffIndex, key) re-attaches regardless of layout.
function parseUnifiedDiff(src) {
  const out = [];
  let oldNo = 1, newNo = 1, k = 0, oldRem = 0, newRem = 0;
  const raw = String(src == null ? "" : src).replace(/\r\n?/g, "\n").split("\n");
  if (raw.length && raw[raw.length - 1] === "") raw.pop();
  const push = (type, text, o, n) => out.push({ key: String(k++), type: type, text: text, oldNo: o, newNo: n });
  // Unambiguous file-section headers. A real hunk BODY line always carries a
  // +/-/space prefix, so a line beginning at column 0 with one of these tokens
  // can only be a header (never a content line). `--- ` / `+++ ` are handled
  // separately because they collide with del/add prefixes INSIDE a hunk.
  const FILE_HDR = /^(diff |index |new file|deleted file|rename |copy |similarity |dissimilarity |old mode|new mode|Index: |={3,}$|Binary files )/;
  for (let i = 0; i < raw.length; i++) {
    const line = raw[i];
    if (/^@@ /.test(line)) {
      // The hunk header declares exactly how many old-side and new-side lines the
      // hunk contains. Tracking that budget is what makes `--- x` / `+++ x` body
      // lines unambiguous: inside a hunk they are del/add; only once the budget is
      // spent does a following `--- ` become the next file's header.
      const m = line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
      if (m) {
        oldNo = parseInt(m[1], 10); newNo = parseInt(m[3], 10);
        oldRem = m[2] == null ? 1 : parseInt(m[2], 10);
        newRem = m[4] == null ? 1 : parseInt(m[4], 10);
      } else { oldRem = 0; newRem = 0; }
      push("hunk", line, null, null);
      continue;
    }
    if (FILE_HDR.test(line)) { oldRem = 0; newRem = 0; push("file", line, null, null); continue; }
    const inHunk = oldRem > 0 || newRem > 0;
    if (!inHunk && (/^--- /.test(line) || /^\+\+\+ /.test(line))) {
      // Between hunks (or before the first one) `--- ` / `+++ ` are file headers.
      push("file", line, null, null);
      continue;
    }
    const c = line[0];
    if (c === "\\") { push("meta", line.slice(1).trim(), null, null); continue; }
    if (c === "+") { push("add", line.slice(1), null, newNo++); if (newRem > 0) newRem--; continue; }
    if (c === "-") { push("del", line.slice(1), oldNo++, null); if (oldRem > 0) oldRem--; continue; }
    push("ctx", c === " " ? line.slice(1) : line, oldNo++, newNo++);
    if (oldRem > 0) oldRem--;
    if (newRem > 0) newRem--;
  }
  return out;
}

function diffLineCommentable(ln) {
  return ln && (ln.type === "add" || ln.type === "del" || ln.type === "ctx");
}

// Build one rendered diff-line element for a logical line on a given side
// ("old" | "new" | "both"). data-line-key ties it back to the logical line.
function makeDiffLineEl(block, ln, side) {
  const row = document.createElement("div");
  row.className = "cmh-dl cmh-dl-" + ln.type;
  row.dataset.diffIndex = String(block.index);
  row.dataset.lineKey = ln.key;
  row.dataset.side = side;
  if (ln.type === "hunk" || ln.type === "file" || ln.type === "meta") {
    const code = document.createElement("span");
    code.className = "cmh-dl-code";
    code.textContent = ln.text;
    row.appendChild(code);
    row.classList.add("cmh-dl-full");
    return row;
  }
  const gutter = document.createElement("span");
  gutter.className = "cmh-dl-gutter";
  gutter.setAttribute("aria-hidden", "true");
  gutter.textContent = side === "old" ? (ln.oldNo == null ? "" : ln.oldNo)
    : side === "new" ? (ln.newNo == null ? "" : ln.newNo)
    : (ln.newNo != null ? ln.newNo : (ln.oldNo != null ? ln.oldNo : ""));
  const sign = document.createElement("span");
  sign.className = "cmh-dl-sign";
  sign.setAttribute("aria-hidden", "true");
  sign.textContent = ln.type === "add" ? "+" : ln.type === "del" ? "-" : " ";
  const code = document.createElement("span");
  code.className = "cmh-dl-code";
  if (ln.text.length && diffSyntaxOn() && diffLangKnown(block.lang)) {
    code.innerHTML = cmhHighlightCode(ln.text, block.lang);
  } else {
    code.textContent = ln.text.length ? ln.text : "\u00a0";
  }
  row.appendChild(gutter);
  row.appendChild(sign);
  row.appendChild(code);
  // Keyboard access: a changed/context line is focusable and Enter opens the
  // composer (see attachDiffHostHandlers), so commenting is not mouse-only.
  row.tabIndex = 0;
  row.setAttribute("role", "button");
  row.setAttribute("aria-label",
    (ln.type === "add" ? "Added" : ln.type === "del" ? "Removed" : "Context")
    + " line" + (ln.newNo != null ? " " + ln.newNo : ln.oldNo != null ? " " + ln.oldNo : "")
    + ": " + (ln.text || "") + ". Press Enter to comment.");
  return row;
}

function renderDiffInline(body, block) {
  const pane = document.createElement("div");
  pane.className = "cmh-diff-pane cmh-diff-pane-unified";
  block.lines.forEach(ln => pane.appendChild(makeDiffLineEl(block, ln, "both")));
  body.appendChild(pane);
}

// Side-by-side: deletions on the left, additions on the right, aligned by
// zipping each del/add run; context lines appear on both sides sharing one key.
// Rows are appended DIRECTLY into the 1fr-1fr grid body (old cell, then new cell)
// so each grid row stretches to the taller of its two cells - keeping the two
// columns aligned even when a long line wraps. Full-width rows span both columns.
function renderDiffSplit(body, block) {
  const spacer = (side) => {
    const s = document.createElement("div");
    s.className = "cmh-dl cmh-dl-spacer";
    s.dataset.side = side;
    s.setAttribute("aria-hidden", "true");
    return s;
  };
  const lines = block.lines;
  let i = 0;
  while (i < lines.length) {
    const ln = lines[i];
    if (ln.type === "hunk" || ln.type === "file" || ln.type === "meta") {
      body.appendChild(makeDiffLineEl(block, ln, "both")); // cmh-dl-full spans both cols
      i++; continue;
    }
    if (ln.type === "ctx") {
      body.appendChild(makeDiffLineEl(block, ln, "old"));
      body.appendChild(makeDiffLineEl(block, ln, "new"));
      i++; continue;
    }
    // Collect a contiguous del/add run, tolerating interspersed `\ No newline`
    // meta lines (git emits them between the -/+ lines at EOF) so the deletion and
    // addition still pair side by side; the meta lines render full-width below.
    const dels = [], adds = [], metas = [];
    while (i < lines.length && (lines[i].type === "del" || lines[i].type === "meta")) {
      (lines[i].type === "meta" ? metas : dels).push(lines[i]); i++;
    }
    while (i < lines.length && (lines[i].type === "add" || lines[i].type === "meta")) {
      (lines[i].type === "meta" ? metas : adds).push(lines[i]); i++;
    }
    if (!dels.length && !adds.length && !metas.length) { i++; continue; }
    const n = Math.max(dels.length, adds.length);
    for (let j = 0; j < n; j++) {
      body.appendChild(dels[j] ? makeDiffLineEl(block, dels[j], "old") : spacer("old"));
      body.appendChild(adds[j] ? makeDiffLineEl(block, adds[j], "new") : spacer("new"));
    }
    metas.forEach(m => body.appendChild(makeDiffLineEl(block, m, "both")));
  }
}

// Above this many logical lines, a diff renders as inert raw text (no per-line
// rows / commenting) so a pathologically large authored diff cannot freeze the
// page on open. The raw source is still preserved for export.
const CMH_DIFF_MAX_LINES = 2000;
function renderDiffRaw(body, block) {
  const notice = document.createElement("div");
  notice.className = "cmh-diff-toobig";
  notice.textContent = "Large diff (" + (block.rawLineCount || block.lines.length) + " lines) shown as raw text; "
    + "per-line commenting is disabled above " + CMH_DIFF_MAX_LINES + " lines.";
  const pre = document.createElement("pre");
  pre.className = "cmh-diff-raw";
  pre.textContent = block.rawSrc;
  body.appendChild(notice);
  body.appendChild(pre);
}

function renderDiffBlock(block) {
  const tooBig = !!block.tooBig;
  const layout = block.layout === "split" ? "split" : "inline";
  const view = document.createElement("div");
  view.className = "cmh-diff-view cmh-diff-" + (tooBig ? "raw" : layout);
  view.dataset.diffIndex = String(block.index);

  const bar = document.createElement("div");
  bar.className = "cmh-diff-bar";
  const label = document.createElement("span");
  label.className = "cmh-diff-label";
  label.textContent = block.label || "diff";
  bar.appendChild(label);
  let toggle = null;
  if (!tooBig) {
    toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "cmh-diff-toggle";
    toggle.textContent = layout === "split" ? "To inline view" : "To side-by-side view";
    toggle.title = "Switch between side-by-side and inline diff";
    bar.appendChild(toggle);
  }
  let hlToggle = null;
  if (!tooBig && diffLangKnown(block.lang)) {
    hlToggle = document.createElement("button");
    hlToggle.type = "button";
    hlToggle.className = "cmh-diff-hltoggle";
    const on = diffSyntaxOn();
    hlToggle.textContent = on ? "Syntax: on" : "Syntax: off";
    hlToggle.title = "Toggle syntax highlighting in diffs";
    hlToggle.setAttribute("aria-pressed", String(on));
    bar.appendChild(hlToggle);
  }
  view.appendChild(bar);

  const bodyEl = document.createElement("div");
  bodyEl.className = "cmh-diff-body";
  if (tooBig) renderDiffRaw(bodyEl, block);
  else if (layout === "split") renderDiffSplit(bodyEl, block);
  else renderDiffInline(bodyEl, block);
  view.appendChild(bodyEl);

  const src = document.createElement("script");
  src.type = "text/plain";
  src.className = "cmh-diff-src";
  src.setAttribute("data-enc", "base64");
  src.textContent = _b64EncodeUtf8(block.rawSrc);
  view.appendChild(src);

  block.host.replaceChildren(view);
  if (toggle) {
    toggle.addEventListener("click", () => {
      block.layout = block.layout === "split" ? "inline" : "split";
      setDefaultDiffLayout(block.layout);
      renderDiffBlock(block);
      applyDiffHighlightsForIndex(block.index);
    });
  }
  if (hlToggle) {
    hlToggle.addEventListener("click", () => {
      setDiffSyntaxOn(!diffSyntaxOn());
      rerenderAllDiffs();
    });
  }
  attachDiffHostHandlers(block);
}

function findDiffLineEls(diffIndex, lineKey) {
  // diffIndex / lineKey are always code-generated non-negative integers. Guard
  // against a hand-edited / poisoned persisted comment whose values could
  // otherwise inject into (and throw from) the querySelectorAll string.
  if (!/^\d+$/.test(String(diffIndex)) || !/^\d+$/.test(String(lineKey))) return [];
  return root.querySelectorAll(
    `.cmh-dl[data-diff-index="${diffIndex}"][data-line-key="${lineKey}"]`);
}
// Build a Range spanning [start,end] character offsets within el.textContent
// (walks text nodes, including those inside existing marks, so offsets stay
// stable as more sub-line marks are added to the same line).
function rangeInEl(el, start, end) {
  const r = document.createRange();
  let acc = 0, state = 0;
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
  let n;
  while ((n = walker.nextNode())) {
    const len = n.data.length;
    // Use `<` for the start so a boundary that sits at the end of one text node
    // resolves to the NEXT node - avoids an empty mark fragment when a new region
    // is adjacent to an existing mark.
    if (state === 0 && start < acc + len) { r.setStart(n, start - acc); state = 1; }
    if (state === 1 && end <= acc + len) { r.setEnd(n, end - acc); state = 2; break; }
    acc += len;
  }
  return state === 2 ? r : null;
}
function wrapDiffSubRange(lineEl, comment) {
  const codeEl = lineEl.querySelector(".cmh-dl-code");
  if (!codeEl) return false;
  const s = comment.subStart, e = comment.subEnd;
  // Guard against a poisoned persisted comment: the offsets must be sane integers
  // within the line's own text, or building the Range throws and breaks init.
  if (!Number.isInteger(s) || !Number.isInteger(e) || s < 0 || e <= s || e > codeEl.textContent.length) return false;
  try {
    if (codeEl.querySelector(`mark.cmh-dl-mark[data-cid="${comment.id}"]`)) return true; // already applied
    const r = rangeInEl(codeEl, s, e);
    if (!r) return false;
    // Apply-time overlap defense: never wrap a range that intersects an existing
    // (foreign) region mark - nesting marks corrupts the DOM. This also guards a
    // crafted/legacy persisted set that contains overlapping regions (the create-
    // time guard only covers new selections). Overlapping regions stay listed but
    // only the first-applied one is highlighted.
    for (const m of codeEl.querySelectorAll("mark.cmh-dl-mark")) {
      if (r.intersectsNode(m)) return false;
    }
    const mark = document.createElement("mark");
    mark.className = "cmh-dl-mark";
    mark.setAttribute("data-cid", comment.id);
    mark.appendChild(r.extractContents());
    r.insertNode(mark);
    codeEl.normalize();
    return true;
  } catch (e2) { return false; }
}
function _addRowCid(el, id) {
  const cids = (el.getAttribute("data-cids") || "").split(/\s+/).filter(Boolean);
  if (!cids.includes(id)) cids.push(id);
  el.setAttribute("data-cids", cids.join(" "));
  el.setAttribute("data-cid", cids[0]);
}
function applyDiffHighlight(comment) {
  const els = findDiffLineEls(comment.diffIndex, comment.lineKey);
  if (!els.length) return false;
  // Sub-line comment: wrap the selected range in each rendered copy of the line.
  if (comment.subStart != null && comment.subEnd != null) {
    let ok = false;
    els.forEach(el => { if (wrapDiffSubRange(el, comment)) ok = true; });
    return ok;
  }
  // Whole-line comment: highlight the row. Several comments can share a line.
  els.forEach(el => { el.classList.add("cmh-dl-hl"); _addRowCid(el, comment.id); });
  return true;
}
function clearDiffHighlight(id) {
  // Sub-line marks for this id: unwrap, keeping the text.
  root.querySelectorAll(`mark.cmh-dl-mark[data-cid="${id}"]`).forEach(mk => {
    const parent = mk.parentNode;
    while (mk.firstChild) parent.insertBefore(mk.firstChild, mk);
    parent.removeChild(mk);
    parent.normalize();
  });
  // Whole-line rows: drop this id; remove the row highlight only if it was the last.
  root.querySelectorAll(".cmh-dl-hl").forEach(el => {
    const cids = (el.getAttribute("data-cids") || el.getAttribute("data-cid") || "").split(/\s+/).filter(Boolean);
    const rest = cids.filter(c => c !== id);
    if (rest.length === cids.length) return;
    if (rest.length) { el.setAttribute("data-cids", rest.join(" ")); el.setAttribute("data-cid", rest[0]); }
    else { el.classList.remove("cmh-dl-hl", "cmh-dl-active"); el.removeAttribute("data-cid"); el.removeAttribute("data-cids"); }
  });
}
function flashDiff(id) {
  root.querySelectorAll(".cmh-dl-hl").forEach(el => {
    if ((el.getAttribute("data-cids") || el.getAttribute("data-cid") || "").split(/\s+/).includes(id)) {
      el.classList.add("cmh-dl-active");
      setTimeout(() => el.classList.remove("cmh-dl-active"), 2200);
    }
  });
  root.querySelectorAll(`mark.cmh-dl-mark[data-cid="${id}"]`).forEach(mk => {
    mk.classList.add("cmh-dl-mark-active");
    setTimeout(() => mk.classList.remove("cmh-dl-mark-active"), 2200);
  });
}
function applyDiffHighlightsForIndex(index) {
  comments.forEach(c => {
    if (c.anchorType === "diff" && c.diffIndex === index) applyDiffHighlight(c);
  });
}

function diffLineInfo(block, el) {
  const key = el.dataset.lineKey;
  const ln = block.lines.find(l => l.key === key);
  if (!ln) return null;
  return {
    diffIndex: block.index,
    lineKey: key,
    side: el.dataset.side || "both",
    lineType: ln.type,
    oldNo: ln.oldNo,
    newNo: ln.newNo,
    text: ln.text,
    sign: ln.type === "add" ? "+" : ln.type === "del" ? "-" : " ",
    label: block.label || "",
  };
}
function _closestDiffCode(node) {
  const el = node && (node.nodeType === 1 ? node : node.parentElement);
  return el && el.closest ? el.closest(".cmh-dl-code") : null;
}
// If the current selection is inside a single diff line's code, return its line
// info plus the sub-range (subStart, subEnd) and quoted substring; else null.
function diffSelectionInfo(block) {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
  const r = sel.getRangeAt(0);
  const codeEl = _closestDiffCode(r.startContainer);
  if (!codeEl || codeEl !== _closestDiffCode(r.endContainer)) return null; // one line only
  if (!block.host.contains(codeEl)) return null;
  const lineEl = codeEl.closest(".cmh-dl");
  if (!lineEl || lineEl.classList.contains("cmh-dl-full") || lineEl.classList.contains("cmh-dl-spacer")) return null;
  const info = diffLineInfo(block, lineEl);
  if (!info || !diffLineCommentable({ type: info.lineType })) return null;
  const full = codeEl.textContent;
  const pre = document.createRange();
  pre.selectNodeContents(codeEl);
  let subStart, subEnd;
  try { pre.setEnd(r.startContainer, r.startOffset); subStart = pre.toString().length; } catch (e) { return null; }
  try { pre.setEnd(r.endContainer, r.endOffset); subEnd = pre.toString().length; } catch (e) { return null; }
  if (subStart > subEnd) { const t = subStart; subStart = subEnd; subEnd = t; }
  const quote = full.slice(subStart, subEnd);
  if (subStart >= subEnd || !quote.trim()) return null;
  return Object.assign({}, info, { subStart, subEnd, quote, rect: r.getBoundingClientRect() });
}
function positionDiffAdd(el) {
  const rect = el.getBoundingClientRect();
  const visible = _clipAwareRect(el, rect);
  if (!visible) return false;
  const btnW = diffAddBtn.offsetWidth || 96;
  const btnH = diffAddBtn.offsetHeight || 26;
  const bounds = _floatingBounds(el);
  const left = visible.right - btnW;
  const lineCenter = rect.top + ((rect.bottom - rect.top) / 2);
  const top = lineCenter - (btnH / 2);
  diffAddBtn.style.left = _clamp(left, bounds.left, bounds.right - btnW) + "px";
  diffAddBtn.style.top = top + "px";
  return true;
}
function showDiffAddFor(el, info) {
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return;
  pendingDiff = info;
  if (diffAddHideTimer) { clearTimeout(diffAddHideTimer); diffAddHideTimer = null; }
  diffAddBtn.hidden = false;
  if (!positionDiffAdd(el)) { diffAddBtn.hidden = true; pendingDiff = null; return; }
  _activeAdd = { el, btn: diffAddBtn, position: () => positionDiffAdd(el), clear: () => { pendingDiff = null; } };
}
function scheduleHideDiffAdd() {
  if (diffAddHideTimer) clearTimeout(diffAddHideTimer);
  diffAddHideTimer = setTimeout(() => {
    if (!diffAddBtn.matches(":hover")) { diffAddBtn.hidden = true; diffActiveLineEl = null; pendingDiff = null; }
  }, 220);
}
function attachDiffHostHandlers(block) {
  const host = block.host;
  if (host._cmDiffAttached) return;
  host._cmDiffAttached = true;
  host.addEventListener("mousemove", (e) => {
    const el = e.target.closest && e.target.closest(".cmh-dl");
    if (!el || !host.contains(el) || el.classList.contains("cmh-dl-full") || el.classList.contains("cmh-dl-spacer")) return;
    if (el === diffActiveLineEl) return;
    const info = diffLineInfo(block, el);
    if (!info || !diffLineCommentable({ type: info.lineType })) return;
    diffActiveLineEl = el;
    showDiffAddFor(el, info);
  });
  host.addEventListener("mouseleave", scheduleHideDiffAdd);
  // Selecting text inside a diff line's code opens the "Add comment" popup, so a
  // reviewer can comment a specific region of a line just like regular prose.
  host.addEventListener("mouseup", () => {
    setTimeout(() => {
      const info = diffSelectionInfo(block);
      if (!info) return;
      pendingDiffSel = info;
      pendingRange = null;
      pendingQuote = "";
      diffAddBtn.hidden = true;
      _setMenuMode("text");
      const r = info.rect;
      showMenu(r.left + Math.min(40, r.width / 2), r.bottom);
    }, 0);
  });
  host.addEventListener("click", (e) => {
    // A sub-line mark takes precedence over the row (a line can carry both).
    const mk = e.target.closest && e.target.closest("mark.cmh-dl-mark");
    const hl = e.target.closest && e.target.closest(".cmh-dl-hl");
    const id = mk ? mk.getAttribute("data-cid") : (hl ? hl.getAttribute("data-cid") : null);
    if (!id) return;
    openSidebar();
    const card = listEl.querySelector(`.cm-card[data-cid="${id}"]`);
    if (card) { card.scrollIntoView({ behavior: "smooth", block: "center" }); flashActive(id); }
    flashDiff(id);
  });
  // Keyboard: focusing a commentable line reveals the + button; Enter opens the
  // composer directly, so diff commenting works without a mouse.
  host.addEventListener("focusin", (e) => {
    const el = e.target.closest && e.target.closest(".cmh-dl");
    if (!el || !host.contains(el) || el.classList.contains("cmh-dl-full") || el.classList.contains("cmh-dl-spacer")) return;
    const info = diffLineInfo(block, el);
    if (!info || !diffLineCommentable({ type: info.lineType })) return;
    diffActiveLineEl = el;
    showDiffAddFor(el, info);
  });
  host.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const el = e.target.closest && e.target.closest(".cmh-dl");
    if (!el || !host.contains(el) || el.classList.contains("cmh-dl-full") || el.classList.contains("cmh-dl-spacer")) return;
    const info = diffLineInfo(block, el);
    if (!info || !diffLineCommentable({ type: info.lineType })) return;
    e.preventDefault();
    pendingDiff = null;
    diffAddBtn.hidden = true;
    diffActiveLineEl = null;
    createComposerElement({ mode: "new-diff", diff: info });
  });
}
if (diffAddBtn) {
  diffAddBtn.addEventListener("mouseenter", () => {
    if (diffAddHideTimer) { clearTimeout(diffAddHideTimer); diffAddHideTimer = null; }
  });
  diffAddBtn.addEventListener("mouseleave", scheduleHideDiffAdd);
  diffAddBtn.addEventListener("click", () => {
    if (!pendingDiff) return;
    const info = pendingDiff;
    pendingDiff = null;
    diffAddBtn.hidden = true;
    diffActiveLineEl = null;
    createComposerElement({ mode: "new-diff", diff: info });
  });
}
function diffBlockForIndex(index) {
  return diffBlocks.find(b => b.index === index) || null;
}
// Human-readable pinpoint for a diff comment: "+42" / "-17" / "line 30".
function diffLineLocator(c) {
  if (c.lineType === "add") return "+" + (c.newNo != null ? c.newNo : "?");
  if (c.lineType === "del") return "-" + (c.oldNo != null ? c.oldNo : "?");
  return "line " + (c.newNo != null ? c.newNo : (c.oldNo != null ? c.oldNo : "?"));
}
function isNumberedCodeBlock(pre) {
  if (!pre || pre.tagName !== "PRE" || !root.contains(pre)) return false;
  if (typeof isCommentableCodeBlock === "function") return isCommentableCodeBlock(pre);
  return !pre.classList.contains("mermaid") && !pre.classList.contains("cmh-diff")
    && !pre.closest(".cm-skip")
    && !pre.closest(".cmh-diff") && !pre.closest(".cmh-diff-host");
}
function ensureCodeLineGutter(target, extraClass) {
  if (!target || target.dataset.cmhLineNumbers === "1") return;
  const lines = String(target.textContent || "").replace(/\r\n?/g, "\n").split("\n");
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  const gutter = document.createElement("span");
  gutter.className = "cmh-code-gutter cm-skip";
  gutter.setAttribute("aria-hidden", "true");
  const count = Math.max(1, lines.length);
  const lh = parseFloat(getComputedStyle(target).lineHeight) || 20;
  gutter.style.height = (count * lh) + "px";
  for (let i = 0; i < count; i++) {
    const line = document.createElement("span");
    line.className = "cmh-code-line" + (extraClass ? (" " + extraClass) : "");
    line.style.top = (i * lh) + "px";
    line.style.height = lh + "px";
    gutter.appendChild(line);
  }
  target.classList.add("cmh-code-lined");
  target.dataset.cmhLineNumbers = "1";
  target.insertBefore(gutter, target.firstChild);
}
function setupCodeLineNumbers() {
  root.querySelectorAll("pre").forEach((pre) => {
    if (!isNumberedCodeBlock(pre)) return;
    const code = pre.querySelector("code");
    const target = code || pre;
    const isKql = !!pre.closest("figure.cmh-kql");
    ensureCodeLineGutter(target, isKql ? "cmh-kql-line" : "");
  });
}
function setupDiffLayer() {
  diffBlocks.length = 0;
  const hosts = root.querySelectorAll("pre.cmh-diff, div.cmh-diff");
  hosts.forEach((el, i) => {
    const srcScript = el.querySelector ? el.querySelector("script.cmh-diff-src") : null;
    const rawSrc = srcScript
      ? (srcScript.getAttribute("data-enc") === "base64"
          ? _b64DecodeUtf8(srcScript.textContent)
          : srcScript.textContent)
      : el.textContent;
    // Collapse newlines/tabs so a crafted data-diff-label cannot inject extra
    // lines into the copied review bundle (the label goes into a one-line field).
    const label = (el.getAttribute("data-diff-label") || "").replace(/[\r\n\t]+/g, " ").trim();
    const host = document.createElement("div");
    host.className = "cmh-diff cmh-diff-host cm-skip";
    host.dataset.cmDiffIndex = String(i);
    host.setAttribute("data-diff-index", String(i));
    if (label) host.setAttribute("data-diff-label", label);
    const lang = inferDiffLang(el, label);
    if (lang) host.setAttribute("data-diff-lang", lang);
    el.replaceWith(host);
    // Pre-count raw lines and SKIP the full parse when the diff is pathologically
    // large, so a huge authored diff cannot allocate one object per line (and
    // freeze the page) before the cap is checked. rawSrc is identical across save
    // and reload, so this tooBig verdict is deterministic on both paths.
    const rawLineCount = rawSrc ? String(rawSrc).replace(/\r\n?/g, "\n").split("\n").length : 0;
    const tooBig = rawLineCount > CMH_DIFF_MAX_LINES;
    const block = { host, index: i, label, rawSrc, tooBig, rawLineCount, lang,
      lines: tooBig ? [] : parseUnifiedDiff(rawSrc), layout: defaultDiffLayout() };
    diffBlocks.push(block);
    renderDiffBlock(block);
    applyDiffHighlightsForIndex(i);
  });
  setupCodeLineNumbers();
}
/* ---------- Image comment layer ----------
   Makes any <img> inside #commentRoot commentable. Each image is indexed in
   document order (imageIndex); hovering or keyboard-focusing it reveals a
   floating "+ comment" button, and the comment anchors by (imageIndex) with the
   src as a fallback key so it survives reload, Copy all, and Export as Portable. This
   mirrors the mermaid-node layer: images carry no text offsets, so image
   comments are excluded from backfillContext / restoreHighlights. */
const imageEls = [];
const imageAddBtn = document.getElementById("imageAddBtn");
let pendingImage = null;
let imageAddHideTimer = null;
let imageActiveEl = null;

function indexImages() {
  imageEls.length = 0;
  root.querySelectorAll("img, canvas").forEach((el) => {
    const isChartMedia = el.closest("figure.chart") || el.classList.contains("cmh-chart");
    if (el.tagName === "IMG") {
      if (el.closest(".cm-skip") && !isChartMedia) return; // skip UI-chrome images
    } else { // CANVAS: only chart canvases are commentable media (never mermaid/diff surfaces).
      if (!isChartMedia) return;
      if (el.closest(".cm-mermaid-host") || el.closest(".cmh-diff-host")) return;
    }
    const i = imageEls.length;
    el.classList.add("cm-img-commentable");
    el.dataset.cmImageIndex = String(i);
    if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
    if (el.tagName === "IMG") {
      const alt = (el.getAttribute("alt") || "").trim();
      el.setAttribute("aria-label", (alt ? alt + " - " : "Image - ") + "press Enter to comment");
    }
    imageEls.push(el);
  });
}
function findImageEl(index) {
  if (!/^\d+$/.test(String(index))) return null;
  return imageEls[index] || root.querySelector(`[data-cm-image-index="${index}"]`) || null;
}
function imageInfo(img) {
  const i = parseInt(img.dataset.cmImageIndex, 10) || 0;
  const isCanvas = img.tagName === "CANVAS";
  const alt = (img.getAttribute("alt") || img.getAttribute("aria-label") || "").replace(/[\r\n\t]+/g, " ").replace(/\s+/g, " ").trim();
  const src = (img.getAttribute("src") || "").replace(/[\r\n\t]+/g, " ").trim();
  const shortSrc = src.length > 120 ? src.slice(0, 117) + "..." : src;
  const kind = (isCanvas || img.closest("figure.chart") || img.classList.contains("cmh-chart")) ? "chart" : "image";
  const quote = alt || (isCanvas ? ("chart " + (i + 1)) : ("image: " + (shortSrc || "(no src)")));
  return { imageIndex: i, src, alt, quote, kind };
}
function applyImageHighlight(comment) {
  let img = findImageEl(comment.imageIndex);
  // If the document was re-ordered, relocate the image by its stored src.
  if ((!img || (comment.imageSrc && img.getAttribute("src") !== comment.imageSrc)) && comment.imageSrc) {
    const bySrc = imageEls.find(im => im.getAttribute("src") === comment.imageSrc);
    if (bySrc) img = bySrc;
  }
  if (!img) return false;
  // An image can carry several comments; track them all in data-cids and keep the
  // first in data-cid for backward-compatible selectors.
  img.classList.add("cm-img-hl");
  const cids = (img.getAttribute("data-cids") || "").split(/\s+/).filter(Boolean);
  if (!cids.includes(comment.id)) cids.push(comment.id);
  img.setAttribute("data-cids", cids.join(" "));
  img.setAttribute("data-cid", cids[0]);
  return true;
}
function _imgCids(im) {
  return (im.getAttribute("data-cids") || im.getAttribute("data-cid") || "").split(/\s+/).filter(Boolean);
}
function clearImageHighlight(id) {
  root.querySelectorAll("img.cm-img-hl, canvas.cm-img-hl").forEach(im => {
    const cids = _imgCids(im);
    const rest = cids.filter(c => c !== id);
    if (rest.length === cids.length) return;
    if (rest.length) {
      im.setAttribute("data-cids", rest.join(" "));
      im.setAttribute("data-cid", rest[0]);
    } else {
      im.classList.remove("cm-img-hl", "cm-img-active");
      im.removeAttribute("data-cid");
      im.removeAttribute("data-cids");
    }
  });
}
function flashImage(id) {
  const img = [...root.querySelectorAll("img.cm-img-hl, canvas.cm-img-hl")].find(im => _imgCids(im).includes(id));
  if (!img) return;
  img.classList.add("cm-img-active");
  setTimeout(() => img.classList.remove("cm-img-active"), 2200);
}
function positionImageAdd(img) {
  const rect = img.getBoundingClientRect();
  const visible = _clipAwareRect(img, rect);
  if (!visible) return false;
  const btnW = imageAddBtn.offsetWidth || 96;
  const btnH = imageAddBtn.offsetHeight || 26;
  const bounds = _floatingBounds(img);
  const left = visible.right - btnW - 6;
  const top = visible.top + 6;
  imageAddBtn.style.left = _clamp(left, bounds.left, bounds.right - btnW) + "px";
  imageAddBtn.style.top = _clamp(top, bounds.top, bounds.bottom - btnH) + "px";
  return true;
}
function showImageAddFor(img) {
  const rect = img.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return;
  pendingImage = imageInfo(img);
  imageAddBtn.title = pendingImage.kind === "chart" ? "Comment on this chart" : "Comment on this image";
  if (imageAddHideTimer) { clearTimeout(imageAddHideTimer); imageAddHideTimer = null; }
  imageAddBtn.hidden = false;
  if (!positionImageAdd(img)) { imageAddBtn.hidden = true; imageActiveEl = null; pendingImage = null; return; }
  _activeAdd = { el: img, btn: imageAddBtn, position: () => positionImageAdd(img), clear: () => { pendingImage = null; } };
}
function scheduleHideImageAdd() {
  if (imageAddHideTimer) clearTimeout(imageAddHideTimer);
  imageAddHideTimer = setTimeout(() => {
    if (!imageAddBtn.matches(":hover")) { imageAddBtn.hidden = true; imageActiveEl = null; pendingImage = null; }
  }, 220);
}
function openImageComposer(info) {
  return createComposerElement({ mode: "new-image", image: info });
}
function setupImageLayer() {
  if (!imageAddBtn) return;
  indexImages();
  imageEls.forEach(img => {
    if (!img._cmImgAttached) {
      img._cmImgAttached = true;
      img.addEventListener("mouseenter", () => { imageActiveEl = img; showImageAddFor(img); });
      img.addEventListener("mouseleave", scheduleHideImageAdd);
      img.addEventListener("focus", () => { imageActiveEl = img; showImageAddFor(img); });
      img.addEventListener("blur", scheduleHideImageAdd);
      img.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        pendingImage = null;
        imageAddBtn.hidden = true;
        imageActiveEl = null;
        openImageComposer(imageInfo(img));
      });
      img.addEventListener("click", () => {
        if (!img.classList.contains("cm-img-hl")) return;
        const id = img.getAttribute("data-cid");
        if (!id) return;
        openSidebar();
        const card = listEl.querySelector(`.cm-card[data-cid="${id}"]`);
        if (card) { card.scrollIntoView({ behavior: "smooth", block: "center" }); flashActive(id); }
        flashImage(id);
      });
    }
  });
  comments.forEach(c => { if (c.anchorType === "image") applyImageHighlight(c); });
}
if (imageAddBtn) {
  imageAddBtn.addEventListener("mouseenter", () => {
    if (imageAddHideTimer) { clearTimeout(imageAddHideTimer); imageAddHideTimer = null; }
  });
  imageAddBtn.addEventListener("mouseleave", scheduleHideImageAdd);
  imageAddBtn.addEventListener("click", () => {
    if (!pendingImage) return;
    const info = pendingImage;
    pendingImage = null;
    imageAddBtn.hidden = true;
    imageActiveEl = null;
    openImageComposer(info);
  });
}

/* ---------- Commentable widgets and SVG nodes (generic opt-in) ----------
   Any element marked data-cm-widget declares a commentable widget. Descendants marked
   data-cm-part (with an optional data-cm-part-label) become individually commentable even
   when the widget itself is cm-skip. A labeled SVG <g data-cm-part> is just a part, so
   commenting on a diagram node uses the same mechanism. Parts inside containers marked
   data-cm-slot also get state-change tracking: their slot at load is the baseline, and any
   later move is surfaced as a synthetic "layout change" record (see widgetStateChanges). */
const widgetAddBtn = document.getElementById("widgetAddBtn");
const widgetParts = [];
let pendingWidget = null;
let widgetAddHideTimer = null;
let _widgetBaseline = null;   // Map partKey -> slot name at load (baseline for state diff)
let _widgetObserver = null;
let _widgetRaf = 0;
let _hadWidgetChanges = false;
let _widgetOrder = new Map(); // Map partKey -> document order (O(1) sort lookup)
let _lastWidgetSig = null;    // last widget state signature, to skip no-op re-renders
let _widgetDrag = null;
let _widgetDomBaseline = null;   // Array of {widget, part, parent}: each part's load-time DOM home, for reset.
let _widgetFirstChangeAt = null; // ISO time of the 0 -> >0 layout-change transition (null while clean).

function _cssEsc(s) { return (window.CSS && CSS.escape) ? CSS.escape(String(s)) : String(s).replace(/["\\]/g, "\\$&"); }
function widgetName(el) { const w = el.closest("[data-cm-widget]"); return w ? (w.getAttribute("data-cm-widget") || "widget") : "widget"; }
function partId(el) { return el.getAttribute("data-cm-part") || ""; }
function partLabel(el) {
  const l = el.getAttribute("data-cm-part-label");
  return (l != null && l !== "") ? l.replace(/\s+/g, " ").trim() : (el.textContent || "").replace(/\s+/g, " ").trim();
}
function partSlot(el) { const s = el.closest("[data-cm-slot]"); return s ? (s.getAttribute("data-cm-slot") || "") : null; }
function partKey(widget, id) { return widget + "\u0000" + id; }

function _wireWidgetPart(el) {
  if (el._cmWidgetAttached) return;
  el._cmWidgetAttached = true;
  el.addEventListener("mouseenter", () => showWidgetAddFor(el));
  el.addEventListener("mouseleave", scheduleHideWidgetAdd);
  el.addEventListener("focus", () => showWidgetAddFor(el));
  el.addEventListener("blur", scheduleHideWidgetAdd);
  el.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    const info = widgetInfo(el);
    pendingWidget = null; if (widgetAddBtn) widgetAddBtn.hidden = true;
    openWidgetComposer(info);
  });
}
function indexWidgetParts() {
  widgetParts.length = 0;
  _widgetOrder = new Map();
  const seenPerWidget = new Map();
  root.querySelectorAll("[data-cm-widget] [data-cm-part]").forEach((el) => {
    const w = widgetName(el), id = partId(el);
    if (!id) { try { console.warn("commentable-html: ignoring a [data-cm-part] with an empty id in widget", w); } catch (e) { /* no-op */ } return; }
    let seen = seenPerWidget.get(w);
    if (!seen) { seen = new Set(); seenPerWidget.set(w, seen); }
    if (seen.has(id)) { try { console.warn("commentable-html: ignoring a duplicate [data-cm-part] id", id, "in widget", w); } catch (e) { /* no-op */ } return; }
    seen.add(id);
    el.classList.add("cm-part-commentable");
    if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
    if (!el.getAttribute("aria-label")) {
      const label = partLabel(el);
      el.setAttribute("aria-label", (label ? label + " - " : "") + "press Enter to comment");
    }
    _wireWidgetPart(el);
    _widgetOrder.set(partKey(w, id), widgetParts.length);
    widgetParts.push(el);
  });
}
function findWidgetPart(widget, id) {
  try {
    const hit = root.querySelector('[data-cm-widget="' + _cssEsc(widget) + '"] [data-cm-part="' + _cssEsc(id) + '"]');
    if (hit) return hit;
  } catch (e) { /* an invalid selector from exotic attribute values - fall through to the scan */ }
  return widgetParts.find((el) => widgetName(el) === widget && partId(el) === id) || null;
}
function widgetInfo(el) {
  const widget = widgetName(el), id = partId(el), label = partLabel(el);
  return { widget, part: id, label, slot: partSlot(el), quote: label || id || widget };
}
function _widgetDragOptIn(slot, widget) {
  return !!(widget && (widget.hasAttribute("data-cm-draggable") || slot.hasAttribute("data-cm-draggable")));
}
function _widgetDragPartFromEvent(e) {
  if (e.button !== 0 || (e.pointerType && e.pointerType !== "mouse")) return null;
  const target = e.target && e.target.closest ? e.target : null;
  if (!target || target.closest("button, input, textarea, select, option, a[href], [contenteditable='true']")) return null;
  const part = target.closest("[data-cm-widget] [data-cm-part]");
  if (!part || !root.contains(part)) return null;
  const slot = part.closest("[data-cm-slot]");
  const widget = part.closest("[data-cm-widget]");
  if (!slot || !widget || part === slot || !_widgetDragOptIn(slot, widget)) return null;
  return { part, slot, widget };
}
function _widgetSlotAtPoint(x, y, widget) {
  const el = document.elementFromPoint(x, y);
  if (!el) return null;
  const slot = el.closest && el.closest("[data-cm-slot]");
  return slot && widget.contains(slot) ? slot : null;
}
function _setWidgetDropSlot(slot) {
  if (_widgetDrag && _widgetDrag.dropSlot === slot) return;
  if (_widgetDrag && _widgetDrag.dropSlot) _widgetDrag.dropSlot.classList.remove("cm-widget-drop-target");
  if (_widgetDrag) _widgetDrag.dropSlot = slot || null;
  if (slot) slot.classList.add("cm-widget-drop-target");
}
function _clearWidgetDrag() {
  if (!_widgetDrag) return;
  if (_widgetDrag.dropSlot) _widgetDrag.dropSlot.classList.remove("cm-widget-drop-target");
  _widgetDrag.part.classList.remove("cm-widget-drag-source");
  document.body.classList.remove("cm-widget-dragging");
  try { _widgetDrag.part.releasePointerCapture(_widgetDrag.pointerId); } catch (e) { /* already released */ }
  document.removeEventListener("pointermove", _onWidgetPointerMove, true);
  document.removeEventListener("pointerup", _onWidgetPointerUp, true);
  document.removeEventListener("pointercancel", _onWidgetPointerCancel, true);
  _widgetDrag = null;
}
function _startWidgetDrag(e, hit) {
  _widgetDrag = {
    pointerId: e.pointerId,
    part: hit.part,
    fromSlot: hit.slot,
    widget: hit.widget,
    startX: e.clientX,
    startY: e.clientY,
    active: false,
    dropSlot: null,
  };
  document.addEventListener("pointermove", _onWidgetPointerMove, true);
  document.addEventListener("pointerup", _onWidgetPointerUp, true);
  document.addEventListener("pointercancel", _onWidgetPointerCancel, true);
}
function _activateWidgetDrag(e) {
  _widgetDrag.active = true;
  _widgetDrag.part.classList.add("cm-widget-drag-source");
  document.body.classList.add("cm-widget-dragging");
  if (widgetAddBtn) { widgetAddBtn.hidden = true; pendingWidget = null; }
  // Draggable cards suppress text selection by design: the whole card is a drag or comment target.
  try { window.getSelection().removeAllRanges(); } catch (err) { /* selection may be unavailable */ }
  try { _widgetDrag.part.setPointerCapture(_widgetDrag.pointerId); } catch (err) { /* capture can fail after cancellation */ }
  _setWidgetDropSlot(_widgetSlotAtPoint(e.clientX, e.clientY, _widgetDrag.widget));
}
function _onWidgetPointerMove(e) {
  if (!_widgetDrag || e.pointerId !== _widgetDrag.pointerId) return;
  const dx = e.clientX - _widgetDrag.startX;
  const dy = e.clientY - _widgetDrag.startY;
  if (!_widgetDrag.active && Math.sqrt(dx * dx + dy * dy) < 6) return;
  if (!_widgetDrag.active) _activateWidgetDrag(e);
  e.preventDefault();
  _setWidgetDropSlot(_widgetSlotAtPoint(e.clientX, e.clientY, _widgetDrag.widget));
}
function _onWidgetPointerUp(e) {
  if (!_widgetDrag || e.pointerId !== _widgetDrag.pointerId) return;
  const drag = _widgetDrag;
  try {
    if (drag.active) {
      e.preventDefault();
      const target = drag.dropSlot;
      if (target && target !== drag.fromSlot && !drag.part.contains(target)) {
        target.appendChild(drag.part);
        _onWidgetMutation();
      }
    }
  } finally {
    _clearWidgetDrag();
  }
}
function _onWidgetPointerCancel(e) {
  if (_widgetDrag && e.pointerId === _widgetDrag.pointerId) _clearWidgetDrag();
}
function setupWidgetDragDrop() {
  if (root._cmWidgetDragAttached) return;
  root._cmWidgetDragAttached = true;
  root.addEventListener("pointerdown", function (e) {
    const hit = _widgetDragPartFromEvent(e);
    if (hit) _startWidgetDrag(e, hit);
  }, true);
}
function applyWidgetHighlight(comment) {
  const el = findWidgetPart(comment.widget, comment.part);
  if (!el) return false;
  el.classList.add("cm-part-hl");
  const cids = (el.getAttribute("data-cids") || "").split(/\s+/).filter(Boolean);
  if (!cids.includes(comment.id)) cids.push(comment.id);
  el.setAttribute("data-cids", cids.join(" "));
  el.setAttribute("data-cid", cids[0]);
  return true;
}
function _partCids(el) { return (el.getAttribute("data-cids") || el.getAttribute("data-cid") || "").split(/\s+/).filter(Boolean); }
function clearWidgetHighlight(id) {
  root.querySelectorAll("[data-cm-part].cm-part-hl").forEach((el) => {
    const cids = _partCids(el);
    const rest = cids.filter((c) => c !== id);
    if (rest.length === cids.length) return;
    if (rest.length) { el.setAttribute("data-cids", rest.join(" ")); el.setAttribute("data-cid", rest[0]); }
    else { el.classList.remove("cm-part-hl", "cm-part-active"); el.removeAttribute("data-cid"); el.removeAttribute("data-cids"); }
  });
}
function flashWidget(id) {
  const el = [...root.querySelectorAll("[data-cm-part].cm-part-hl")].find((x) => _partCids(x).includes(id));
  if (!el) return;
  el.classList.add("cm-part-active");
  setTimeout(() => el.classList.remove("cm-part-active"), 2200);
}
function positionWidgetAdd(el) {
  const rect = el.getBoundingClientRect();
  const visible = _clipAwareRect(el, rect);
  if (!visible) return false;
  const bw = widgetAddBtn.offsetWidth || 96, bh = widgetAddBtn.offsetHeight || 26;
  const bounds = _floatingBounds(el);
  const left = visible.right - bw - 6, top = visible.top + 6;
  widgetAddBtn.style.left = _clamp(left, bounds.left, bounds.right - bw) + "px";
  widgetAddBtn.style.top = _clamp(top, bounds.top, bounds.bottom - bh) + "px";
  return true;
}
function showWidgetAddFor(el) {
  if (!widgetAddBtn) return;
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return;
  pendingWidget = widgetInfo(el);
  widgetAddBtn.title = 'Comment on "' + (pendingWidget.quote || "this element") + '"';
  if (widgetAddHideTimer) { clearTimeout(widgetAddHideTimer); widgetAddHideTimer = null; }
  widgetAddBtn.hidden = false;
  if (!positionWidgetAdd(el)) { widgetAddBtn.hidden = true; pendingWidget = null; return; }
  _activeAdd = { el, btn: widgetAddBtn, position: () => positionWidgetAdd(el), clear: () => { pendingWidget = null; } };
}
function scheduleHideWidgetAdd() {
  if (widgetAddHideTimer) clearTimeout(widgetAddHideTimer);
  widgetAddHideTimer = setTimeout(() => {
    if (widgetAddBtn && !widgetAddBtn.matches(":hover")) { widgetAddBtn.hidden = true; pendingWidget = null; }
  }, 220);
}
function openWidgetComposer(info) { return createComposerElement({ mode: "new-widget", widget: info }); }

// Canonical slot value: a part with no data-cm-slot ancestor reads as "(no slot)", used
// identically by the snapshot, the signature, and the change detector so they never disagree.
function _partSlotCanon(p) { const s = partSlot(p); return s == null ? "(no slot)" : s; }
// State-change tracking: snapshot each part's slot at load, then report moves. Pure
// function of the current DOM, so widgetStateChanges() is deterministic and idempotent.
function _snapshotWidgetState() {
  _widgetBaseline = new Map();
  root.querySelectorAll("[data-cm-widget] [data-cm-part]").forEach((p) => {
    const id = partId(p);
    if (!id) return;
    const key = partKey(widgetName(p), id);
    if (_widgetBaseline.has(key)) return;   // first-seen wins, matching indexWidgetParts dedupe
    _widgetBaseline.set(key, _partSlotCanon(p));
  });
  // A parallel DOM baseline for draggable widgets: each part's element and its original
  // parent, in document order, so resetWidgetMoves can put every card back where it loaded.
  _widgetDomBaseline = [];
  root.querySelectorAll("[data-cm-widget][data-cm-draggable] [data-cm-part]").forEach((p) => {
    _widgetDomBaseline.push({ widget: p.closest("[data-cm-widget]"), part: p, parent: p.parentElement });
  });
}
// Return the ISO time of the current widget layout change run (null when the layout matches
// its load baseline), so the sidebar can show when a board was first edited.
function widgetFirstChangeAt() { return _widgetFirstChangeAt; }
// Put every recorded part of one widget back into its original parent slot in load order,
// then re-run the mutation pass so the sidebar, badge, and reset buttons resync.
function resetWidgetMoves(widgetEl) {
  if (!widgetEl || !_widgetDomBaseline) return;
  _widgetDomBaseline.forEach((rec) => {
    if (rec.widget !== widgetEl || !rec.part || !rec.parent) return;
    rec.parent.appendChild(rec.part);
  });
  _onWidgetMutation();
}
// Show a "Reset moves" button on each draggable widget that currently differs from its load
// baseline, and remove it once the widget is clean again. The button is cm-skip and is not a
// data-cm-part, so it never enters the layout signature and cannot loop the MutationObserver.
function _syncWidgetResetButtons() {
  const changed = new Set(((typeof widgetStateChanges === "function") ? widgetStateChanges() : []).map((ch) => ch.widget));
  root.querySelectorAll("[data-cm-widget][data-cm-draggable]").forEach((w) => {
    const has = changed.has(w.getAttribute("data-cm-widget") || "widget");
    let btn = w.querySelector(":scope > .cm-widget-reset");
    if (has && !btn) {
      btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cm-skip cm-widget-reset";
      btn.textContent = "Reset moves";
      btn.title = "Return cards to their original positions";
      btn.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); resetWidgetMoves(w); });
      w.appendChild(btn);
    } else if (!has && btn) {
      btn.remove();
    }
  });
}
// A stable signature of the current widget layout (part keys + slots), used to skip no-op
// sidebar rebuilds when a mutation did not actually change any part or slot.
function _widgetStateSig() {
  const parts = [];
  const seen = new Set();
  root.querySelectorAll("[data-cm-widget] [data-cm-part]").forEach((p) => {
    const id = partId(p);
    if (!id) return;
    const key = partKey(widgetName(p), id);
    if (seen.has(key)) return;
    seen.add(key);
    parts.push(key + "\u0000" + _partSlotCanon(p));
  });
  return parts.join("\u0001");
}
function widgetStateChanges() {
  if (!_widgetBaseline || !_widgetBaseline.size) return [];
  const out = [];
  const seen = new Set();
  root.querySelectorAll("[data-cm-widget] [data-cm-part]").forEach((p) => {
    const id = partId(p);
    if (!id) return;
    const key = partKey(widgetName(p), id);
    if (!_widgetBaseline.has(key) || seen.has(key)) return;
    seen.add(key);
    const to = _partSlotCanon(p);
    const from = _widgetBaseline.get(key);
    if (from !== to) out.push({ widget: widgetName(p), part: id, label: partLabel(p), from, to });
  });
  // A part present at load but now gone from the DOM is a removal.
  _widgetBaseline.forEach((from, key) => {
    if (seen.has(key)) return;
    const sep = key.indexOf("\u0000");
    const part = key.slice(sep + 1);
    out.push({ widget: key.slice(0, sep), part, label: part, from, to: "(removed)" });
  });
  return out;
}
function _onWidgetMutation() {
  if (_widgetRaf) return;
  const run = () => {
    _widgetRaf = 0;
    // Always re-index and reapply widget highlights, so a part node replaced in place (same
    // widget/part/slot, e.g. a framework re-render) regains its listeners and highlight.
    indexWidgetParts();
    comments.forEach((c) => { if (c.anchorType === "widget") applyWidgetHighlight(c); });
    // Only rebuild the sidebar / re-evaluate the state card when the layout actually changed,
    // so cosmetic mutations (class toggles, mermaid attribute churn) do not thrash the panel.
    const sig = _widgetStateSig();
    if (sig === _lastWidgetSig) return;
    _lastWidgetSig = sig;
    // Track when the first layout change happened (0 -> >0 transition) BEFORE rendering, so
    // the state card can show the timestamp on the same pass. Clear it once the layout
    // returns to its baseline.
    const has = widgetStateChanges().length > 0;
    if (has && !_hadWidgetChanges) _widgetFirstChangeAt = new Date().toISOString();
    if (!has) _widgetFirstChangeAt = null;
    renderComments();
    // Surface a newly-detected layout change: open the panel so the state card (which is
    // not counted as a comment) is not missed. Only on the 0 -> >0 transition, so a user
    // who closes the panel is not fought.
    if (has && !_hadWidgetChanges && typeof openSidebar === "function") openSidebar();
    _hadWidgetChanges = has;
    _syncWidgetResetButtons();
  };
  if (typeof requestAnimationFrame !== "function") { run(); return; }
  _widgetRaf = requestAnimationFrame(run);
}
function setupWidgetLayer() {
  if (!widgetAddBtn) return;
  indexWidgetParts();
  setupWidgetDragDrop();
  _snapshotWidgetState();
  _lastWidgetSig = _widgetStateSig();
  _hadWidgetChanges = widgetStateChanges().length > 0;
  _widgetFirstChangeAt = null;
  comments.filter((c) => c.anchorType === "widget").forEach((c) => {
    if (!applyWidgetHighlight(c)) console.warn("Could not restore widget highlight for", c.id);
  });
  if (!widgetAddBtn._cmWired) {
    widgetAddBtn._cmWired = true;
    widgetAddBtn.addEventListener("mouseenter", () => { if (widgetAddHideTimer) { clearTimeout(widgetAddHideTimer); widgetAddHideTimer = null; } });
    widgetAddBtn.addEventListener("mouseleave", scheduleHideWidgetAdd);
    widgetAddBtn.addEventListener("click", () => {
      if (!pendingWidget) return;
      const info = pendingWidget;
      pendingWidget = null; widgetAddBtn.hidden = true;
      openWidgetComposer(info);
    });
  }
  const widgets = root.querySelectorAll("[data-cm-widget]");
  if (widgets.length && "MutationObserver" in window) {
    if (_widgetObserver) _widgetObserver.disconnect();
    _widgetObserver = new MutationObserver(_onWidgetMutation);
    widgets.forEach((w) => _widgetObserver.observe(w, { childList: true, subtree: true }));
  }
  _syncWidgetResetButtons();
}

/* ---------- Layered checklist (four-state items, aggregation, minimal persistence) ----------
   A container marked data-cmh-checklist is a checklist. Any descendant carrying data-cmh-state
   (or data-cmh-item) is an item; an item with child items is a branch (its checkbox aggregates
   over its DIRECT children), otherwise a leaf. Hierarchy comes from DOM nesting (lists) or an
   explicit data-cmh-parent reference to a parent's data-cmh-item id (tables, which cannot nest
   rows and may be sorted). Leaf state cycles blank -> check -> cross -> question -> blank; a
   branch click propagates its next state to every descendant leaf. Only leaves whose state
   differs from their authored data-cmh-state baseline are stored, as one-character codes under
   COMMENT_KEY + "::cl", so a large checklist with a few edits costs a few bytes. Changes surface
   as one per-list card (jump + reset) in the sidebar and a Copy-all section the agent can cement
   back into the source with tools/checklist_apply.py; export bakes current states into
   data-cmh-state. */
const CMH_CHECK_STATES = ["blank", "check", "cross", "question"];
const CMH_CHECK_CODE = { blank: "b", check: "v", cross: "x", question: "q" };
const CMH_CHECK_TOKEN = { b: "blank", v: "check", x: "cross", q: "question" };
const CMH_CL_KEY = COMMENT_KEY + "::cl";
const checklists = [];
let _clOverrides = {};   // { [checklistId]: { [itemKey]: token } } - current leaf states (any value)
let _clHadChanges = false;

function _clToken(v) {
  const s = (v == null ? "" : String(v)).trim().toLowerCase();
  return CMH_CHECK_STATES.indexOf(s) >= 0 ? s : "blank";
}
function _clNextState(s) {
  const i = CMH_CHECK_STATES.indexOf(s);
  return i < 0 ? "check" : CMH_CHECK_STATES[(i + 1) % CMH_CHECK_STATES.length];  // mixed/unknown -> check
}
function _clSvg(state, size) {
  const s = size || 20;
  const box = '<rect x="2.5" y="2.5" width="15" height="15" rx="4" ';
  let inner;
  if (state === "check") inner = box + 'fill="#1f8f4e" stroke="#1f8f4e" stroke-width="1.6"/><path d="M6 10.5 L9 13.3 L14.5 6.8" fill="none" stroke="#fff" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>';
  else if (state === "cross") inner = box + 'fill="#c8402c" stroke="#c8402c" stroke-width="1.6"/><path d="M6.6 6.6 L13.4 13.4 M13.4 6.6 L6.6 13.4" stroke="#fff" stroke-width="2.1" stroke-linecap="round"/>';
  else if (state === "question") inner = box + 'fill="#d98a1f" stroke="#d98a1f" stroke-width="1.6"/><text x="10" y="15" text-anchor="middle" font-size="13" font-weight="700" fill="#fff" font-family="Segoe UI, Arial, sans-serif">?</text>';
  else if (state === "mixed") inner = box + 'fill="none" stroke="#8a94a6" stroke-width="1.6"/><path d="M6 10 H14" stroke="#8a94a6" stroke-width="2" stroke-linecap="round"/>';
  else inner = box + 'fill="none" stroke="#8a94a6" stroke-width="1.6"/>';
  return '<svg viewBox="0 0 20 20" width="' + s + '" height="' + s + '" aria-hidden="true" focusable="false">' + inner + '</svg>';
}
// The item's own label: for a table row, the cells other than the state cell; for a list item,
// its direct text (excluding any nested list / nested items / the injected control).
function _clLabel(el) {
  if (el.tagName === "TR") {
    const cells = Array.prototype.filter.call(el.children, (c) => c.tagName === "TD" || c.tagName === "TH");
    const stateCell = el.querySelector("[data-cmh-state-cell]") || cells[0];
    const labelCell = cells.find((c) => c !== stateCell);
    const txt = labelCell ? (labelCell.textContent || "").replace(/\s+/g, " ").trim() : "";
    return txt || (el.textContent || "").replace(/\s+/g, " ").trim();
  }
  let s = "";
  Array.prototype.forEach.call(el.childNodes, (n) => {
    if (n.nodeType === 3) s += n.nodeValue;
    else if (n.nodeType === 1 && !n.matches("ul,ol,table,[data-cmh-checklist],[data-cmh-state],[data-cmh-item],.cmh-check")) s += n.textContent;
  });
  s = s.replace(/\s+/g, " ").trim();
  return s || (el.getAttribute("data-cmh-item") || "");
}
// Where the state control lives: a table row's state cell (or first cell), else the item itself.
function _clSlot(el) {
  if (el.tagName === "TR") return el.querySelector("[data-cmh-state-cell]") || el.querySelector("td, th") || el;
  return el;
}
function _clParentEl(el, setEls, container) {
  let p = el.parentElement;
  while (p && p !== container && p !== root) {
    if (setEls.has(p)) return p;
    p = p.parentElement;
  }
  return null;
}
function _clLeafState(item) {
  const m = _clOverrides[item.checklist];
  const ov = m ? m[item.key] : null;
  return ov || item.baseline;
}
function _clItemState(item, cache) {
  if (cache.has(item)) return cache.get(item);
  let s;
  if (item.isBranch) {
    const kids = item.children.map((c) => _clItemState(c, cache));
    if (!kids.length) s = "blank";
    else if (kids.some((k) => k === "mixed")) s = "mixed";
    else s = kids.every((k) => k === kids[0]) ? kids[0] : "mixed";
  } else {
    s = _clLeafState(item);
  }
  cache.set(item, s);
  return s;
}
function _clDescendantLeaves(item) {
  const out = [];
  (function walk(it) {
    if (!it.isBranch) { out.push(it); return; }
    it.children.forEach(walk);
  })(item);
  return out;
}
function _clSetLeaf(item, token) {
  const cid = item.checklist;
  if (token === item.baseline) { if (_clOverrides[cid]) delete _clOverrides[cid][item.key]; }
  else { if (!_clOverrides[cid]) _clOverrides[cid] = {}; _clOverrides[cid][item.key] = token; }
  if (_clOverrides[cid] && !Object.keys(_clOverrides[cid]).length) delete _clOverrides[cid];
}
function _clLoad() {
  _clOverrides = {};
  let raw = null;
  try { raw = localStorage.getItem(CMH_CL_KEY); } catch (e) { raw = null; }
  let data = {};
  try { data = raw ? JSON.parse(raw) : {}; } catch (e) { data = {}; }
  if (!data || typeof data !== "object") return;
  Object.keys(data).forEach((cid) => {
    const m = data[cid];
    if (!m || typeof m !== "object") return;
    Object.keys(m).forEach((key) => {
      const token = CMH_CHECK_TOKEN[m[key]];
      if (token) { if (!_clOverrides[cid]) _clOverrides[cid] = {}; _clOverrides[cid][key] = token; }
    });
  });
}
function _clSave() {
  const out = {};
  checklists.forEach((cl) => {
    cl.leaves.forEach((item) => {
      const cur = _clLeafState(item);
      if (cur !== item.baseline) { if (!out[item.checklist]) out[item.checklist] = {}; out[item.checklist][item.key] = CMH_CHECK_CODE[cur]; }
    });
  });
  try {
    if (Object.keys(out).length) localStorage.setItem(CMH_CL_KEY, JSON.stringify(out));
    else localStorage.removeItem(CMH_CL_KEY);
    return true;
  } catch (e) {
    showToast("Checklist state NOT saved to this browser (storage full or blocked) - it will be lost on reload.",
      { alert: true, duration: 8000 });
    return false;
  }
}
function _clRefresh() {
  const cache = new Map();
  checklists.forEach((cl) => {
    cl.items.forEach((item) => {
      if (!item.btn) return;
      const s = _clItemState(item, cache);
      item.btn.setAttribute("data-cmh-check-state", s);
      item.btn.innerHTML = _clSvg(s, 20);
      const lbl = (item.label || item.key || "item") + ": " + s + ". Activate to change.";
      item.btn.setAttribute("aria-label", lbl);
      item.btn.title = "State: " + s;
    });
  });
}
function _clAfterChange() {
  _clSave();
  _clRefresh();
  if (typeof renderComments === "function") renderComments();
  if (typeof updateDocTypeUi === "function") updateDocTypeUi();
  // Surface a newly-detected change: open the panel once on the 0 -> >0 transition so the
  // per-list card (which is not a comment) is not missed, matching the widget state card.
  const has = checklistChanges().length > 0;
  if (has && !_clHadChanges && typeof openSidebar === "function") openSidebar();
  _clHadChanges = has;
}
function _clCycleItem(item) {
  const cache = new Map();
  const next = _clNextState(_clItemState(item, cache));
  if (item.isBranch) _clDescendantLeaves(item).forEach((l) => _clSetLeaf(l, next));
  else _clSetLeaf(item, next);
  _clAfterChange();
}
function _clMakeBtn(item) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "cmh-check cm-skip";
  b.setAttribute("data-cmh-check-btn", "");
  b.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); _clCycleItem(item); });
  b.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") { e.preventDefault(); _clCycleItem(item); }
  });
  return b;
}
// Leaves whose current state differs from their authored baseline, one record per change.
function checklistChanges() {
  const out = [];
  checklists.forEach((cl) => {
    cl.leaves.forEach((item) => {
      const cur = _clLeafState(item);
      if (cur !== item.baseline) out.push({ checklist: cl.id, checklistLabel: cl.label, key: item.key, label: item.label, from: item.baseline, to: cur });
    });
  });
  return out;
}
function _clMini(token) { return '<span class="cmh-cl-mini">' + _clSvg(token, 14) + "</span>"; }
function _renderOneChecklistCard(cl, list) {
  const items = list.map((ch) =>
    "<li>" + _clMini(ch.from) + ' <span class="cmh-cl-arrow">&rarr;</span> ' + _clMini(ch.to)
    + " " + escapeHtml(ch.label || ch.key) + "</li>"
  ).join("");
  return `
    <article class="cm-card cm-card-checklist" data-cmh-checklist-name="${escapeHtml(cl.id)}">
      <div class="section">checklist: <strong>${escapeHtml(cl.label)}</strong></div>
      <div class="cm-card-state-title">${list.length} item${list.length === 1 ? "" : "s"} changed</div>
      <ul class="cmh-cl-changes">${items}</ul>
      <div class="note">Auto-tracked from the current checklist state. Included in Copy all so the agent can cement it into the source; the file stays Not portable until re-exported.</div>
      <div class="meta">
        <span></span>
        <span class="acts">
          <button type="button" data-act="cl-jump" data-cmh-checklist-name="${escapeHtml(cl.id)}" title="Scroll to this checklist">jump</button>
          <button type="button" data-act="cl-reset" data-cmh-checklist-name="${escapeHtml(cl.id)}" title="Revert this checklist to its authored state">reset</button>
        </span>
      </div>
    </article>`;
}
// Sidebar cards for changed checklists, each tagged with a document-order position so the
// sidebar can interleave them with the comment cards instead of pinning them on top.
function checklistCardPieces() {
  const changes = checklistChanges();
  if (!changes.length) return [];
  const byCl = new Map();
  changes.forEach((ch) => { if (!byCl.has(ch.checklist)) byCl.set(ch.checklist, []); byCl.get(ch.checklist).push(ch); });
  const pieces = [];
  checklists.forEach((cl) => {
    const list = byCl.get(cl.id);
    if (!list || !list.length) return;
    let pos = 1e15;
    try { const o = offsetWithin(cl.container, 0); if (typeof o === "number" && o >= 0) pos = o; } catch (e) { /* no text position */ }
    pieces.push({ pos, html: _renderOneChecklistCard(cl, list) });
  });
  return pieces;
}
function resetChecklist(cid) {
  if (!_clOverrides[cid]) return;
  delete _clOverrides[cid];
  _clAfterChange();
}
function jumpToChecklist(cid) {
  const cl = checklists.find((c) => c.id === cid);
  if (!cl || !cl.container) return;
  if (typeof expandCollapsedAncestors === "function") expandCollapsedAncestors(cl.container);
  cl.container.scrollIntoView({ behavior: "smooth", block: "center" });
  cl.container.classList.add("cmh-check-flash");
  setTimeout(() => cl.container.classList.remove("cmh-check-flash"), 2200);
}
// Bake current leaf states into data-cmh-state so an exported file reflects them and opens
// with no pending changes (mirrors _applyWidgetLayoutToHtml for the layout case).
function _clDocItemMap(container) {
  const els = Array.prototype.filter.call(
    container.querySelectorAll("[data-cmh-state], [data-cmh-item]"),
    (el) => el.closest("[data-cmh-checklist]") === container);
  const map = new Map();
  els.forEach((el, idx) => { const key = el.getAttribute("data-cmh-item") || String(idx + 1); if (!map.has(key)) map.set(key, el); });
  return map;
}
function _applyChecklistStateToHtml(html) {
  if (!checklists.length || !checklistChanges().length) return html;
  const doc = new DOMParser().parseFromString(String(html || ""), "text/html");
  checklists.forEach((cl) => {
    let container = null;
    try { container = doc.querySelector('[data-cmh-checklist="' + _cssEsc(cl.id) + '"]'); } catch (e) { container = null; }
    if (!container) return;
    const map = _clDocItemMap(container);
    cl.leaves.forEach((item) => {
      const el = map.get(item.key);
      if (el) el.setAttribute("data-cmh-state", _clLeafState(item));
    });
  });
  const doctype = /^\s*<!doctype/i.test(String(html || "")) ? "<!DOCTYPE html>\n" : "";
  return doctype + doc.documentElement.outerHTML;
}
function setupChecklistLayer() {
  checklists.length = 0;
  _clLoad();
  root.querySelectorAll("[data-cmh-checklist]").forEach((container) => {
    const id = container.getAttribute("data-cmh-checklist") || "";
    if (!id) return;
    const itemEls = Array.prototype.filter.call(
      container.querySelectorAll("[data-cmh-state], [data-cmh-item]"),
      (el) => el.closest("[data-cmh-checklist]") === container);
    if (!itemEls.length) return;
    const setEls = new Set(itemEls);
    const items = [];
    const byKey = new Map();
    const elItem = new Map();
    itemEls.forEach((el, idx) => {
      const key = el.getAttribute("data-cmh-item") || String(idx + 1);
      const item = { checklist: id, key, el, label: _clLabel(el), parentKey: null, children: [], isBranch: false, baseline: _clToken(el.getAttribute("data-cmh-state")), btn: null };
      items.push(item);
      elItem.set(el, item);
      if (!byKey.has(key)) byKey.set(key, item);
    });
    items.forEach((item) => {
      const explicit = item.el.getAttribute("data-cmh-parent");
      if (explicit && byKey.has(explicit)) { item.parentKey = explicit; return; }
      const pEl = _clParentEl(item.el, setEls, container);
      if (pEl && elItem.get(pEl)) item.parentKey = elItem.get(pEl).key;
    });
    items.forEach((item) => { if (item.parentKey && byKey.has(item.parentKey) && byKey.get(item.parentKey) !== item) byKey.get(item.parentKey).children.push(item); });
    items.forEach((item) => { item.isBranch = item.children.length > 0; });
    items.forEach((item) => {
      item.el.classList.add("cmh-check-item");
      item.el.setAttribute("data-cmh-check-role", item.isBranch ? "branch" : "leaf");
      const btn = _clMakeBtn(item);
      item.btn = btn;
      const slot = _clSlot(item.el);
      slot.insertBefore(btn, slot.firstChild);
    });
    container.classList.add("cmh-checklist-ready");
    checklists.push({ id, label: container.getAttribute("data-cmh-checklist-label") || id, container, items, byKey, leaves: items.filter((i) => !i.isBranch) });
  });
  if (checklists.length) _clRefresh();
  _clHadChanges = checklistChanges().length > 0;
}

/* ---------- Document-wide comments ---------- */
// A comment not tied to any element (raised by right-clicking empty space). It has no
// highlight and no offsets; it just carries a note about the whole document.
function openDocumentComposer() { return createComposerElement({ mode: "new-document" }); }

/* ---------- Selection handling ---------- */
function selectionInRoot() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed) return null;
  const r = sel.getRangeAt(0);
  if (!root.contains(r.commonAncestorContainer)) return null;
  // Ignore whitespace-only selections: they would anchor a highlight to no visible
  // text, producing a phantom comment with an empty quote.
  if (!sel.toString().trim()) return null;
  const anc = r.commonAncestorContainer.nodeType === 1
    ? r.commonAncestorContainer
    : r.commonAncestorContainer.parentElement;
  if (anc && anc.closest(".cm-skip")) return null;
  return { sel, range: r };
}
// Touch / coarse-pointer devices have no separate right-click: a long-press both
// selects text and is the only gesture that opens the browser's native selection
// menu (Copy, Share, Look up...). Hijacking contextmenu there would leave the reader
// unable to copy, so on those devices we let the native menu through and rely on the
// floating "Add comment" popup (raised from the selection/mouseup path) for commenting.
const _coarsePointer = !!(window.matchMedia
  && window.matchMedia("(hover: none), (pointer: coarse)").matches);
function _setMenuMode(mode) {
  const mc = document.getElementById("menuComment");
  const md = document.getElementById("menuDocComment");
  if (mc) mc.hidden = (mode !== "text");
  if (md) md.hidden = (mode !== "document");
}
document.addEventListener("contextmenu", (e) => {
  if (e.target.closest(".cm-skip")) { hideMenu(); return; }
  // Deck present mode is a clean full-screen presentation with no commenting UI: keep the
  // native context menu and do not raise the text/document comment menu.
  if (document.body.classList.contains("cmh-deck-present")) return;
  if (_coarsePointer) return;
  const got = selectionInRoot();
  if (got) {
    e.preventDefault();
    pendingDiffSel = null;
    pendingRange = got.range.cloneRange();
    pendingQuote = got.sel.toString();
    _setMenuMode("text");
    showMenu(e.clientX, e.clientY);
    return;
  }
  // No selection: offer a document-wide comment on an "empty" right-click inside the
  // document area, but leave the native menu for links, media, form controls, and existing
  // comment anchors so their default actions (open link, comment on a part) still work.
  const t = e.target;
  const inDoc = (root.contains(t) || t === document.body || (t.closest && t.closest(".app")));
  if (!inDoc) { hideMenu(); return; }
  if (t.closest && t.closest("a[href], img, canvas, svg, button, input, textarea, select, [data-cm-part], mark.cm-hl")) { hideMenu(); return; }
  e.preventDefault();
  pendingRange = null; pendingQuote = ""; pendingDiffSel = null;
  _setMenuMode("document");
  showMenu(e.clientX, e.clientY);
});
document.addEventListener("mouseup", (e) => {
  // A right-button release, or a macOS Ctrl-click (a primary-button release with the Control
  // key held, which the platform turns into a contextmenu gesture), belongs to the contextmenu
  // flow that opens the doc-comment or text menu. Running the selection cleanup below on it
  // would queue a hideMenu() that clobbers the just-opened menu, so the menu flickers open then
  // vanishes. Plain left/middle button releases still drive the text-selection popup.
  if (e.button === 2 || e.ctrlKey) return;
  // A release inside the add-comment menu itself (clicking the Add Comment pill) is the
  // menu's own click that opens the composer, not a new selection gesture; reprocessing it
  // would re-show the menu on top of the just-opened composer.
  if (menu && menu.contains && menu.contains(e.target)) return;
  // A release over a cm-skip element (a tall chart canvas below its caption, the Add-Comment
  // pill itself) must NOT bail before the selection is checked: the pointer often lifts over
  // that neighbour while a valid content selection still stands. Remember it so the no-selection
  // cleanup below can skip clobbering an open menu when the release landed on chrome.
  const onSkip = !!(e.target.closest && e.target.closest(".cm-skip"));
  // Deck present mode: no text-selection comment popup (the comment UI is hidden).
  if (document.body.classList.contains("cmh-deck-present")) return;
  setTimeout(() => {
    const got = selectionInRoot();
    if (!got) {
      // A collapsed or whitespace-only selection: drop any menu/pending state left
      // over from a prior selection so "Add comment" cannot fire on stale text - but only
      // when the release was not on cm-skip chrome, so clicking the Add-Comment pill does
      // not tear down the menu it belongs to.
      if (!onSkip) {
        hideMenu();
        pendingRange = null;
        pendingQuote = "";
      }
      return;
    }
    pendingDiffSel = null;
    pendingRange = got.range.cloneRange();
    pendingQuote = got.sel.toString();
    _setMenuMode("text");
    showMenuForRange(got.range);
  }, 0);
});
// Touch / coarse-pointer selection path. On phones a selection is made by dragging the
// native selection handles, which never fires `mouseup`, so the desktop popup path above
// never runs and touch users only get the native long-press menu. A debounced
// `selectionchange` raises the SAME "Add comment" popup once the selection settles, and
// hides it when the selection collapses. Gated to coarse pointers so desktop mouse
// behavior (the mouseup path) is untouched.
if (_coarsePointer) {
  let _touchSelTimer = null;
  const raiseTouchSelectionMenu = () => {
    if (document.body.classList.contains("cmh-deck-present")) { hideMenu(); return; }
    const got = selectionInRoot();
    if (!got) { hideMenu(); pendingRange = null; pendingQuote = ""; return; }
    pendingDiffSel = null;
    pendingRange = got.range.cloneRange();
    pendingQuote = got.sel.toString();
    _setMenuMode("text");
    showMenuForRange(got.range);
  };
  document.addEventListener("selectionchange", () => {
    const sel = window.getSelection();
    // A collapsed selection dismisses the popup immediately (no debounce) so a tap that
    // clears the selection hides it at once.
    if (!sel || sel.isCollapsed) {
      if (_touchSelTimer) { clearTimeout(_touchSelTimer); _touchSelTimer = null; }
      hideMenu();
      pendingRange = null;
      pendingQuote = "";
      return;
    }
    // Debounce so the popup fires after the user finishes dragging the handles, not on
    // every intermediate change.
    if (_touchSelTimer) clearTimeout(_touchSelTimer);
    _touchSelTimer = setTimeout(raiseTouchSelectionMenu, 400);
  });
}
document.addEventListener("click", (e) => {
  if (menu.hidden) return;
  if (!menu.contains(e.target)) hideMenu();
});
document.addEventListener("keydown", (e) => {
  if (e.isComposing) return;
  if (e.key === "Escape") {
    // Priority: an open toolbar overflow menu closes first and consumes the key,
    // so Escape does not also discard an open composer.
    const tmenu = document.getElementById("toolbarMenu");
    if (tmenu && !tmenu.hidden) {
      tmenu.hidden = true;
      const tbtn = document.getElementById("btnToolbarMenu");
      if (tbtn) { tbtn.setAttribute("aria-expanded", "false"); tbtn.focus(); }
      return;
    }
    // An open add-comment selection menu closes first and consumes Escape, so the key
    // does not also discard an open composer draft behind it.
    if (menu && !menu.hidden) { hideMenu(); return; }
    hideMenu();
    let target = (lastFocusedComposer && openComposers.has(lastFocusedComposer)) ? lastFocusedComposer : null;
    if (!target && openComposers.size) target = [...openComposers].pop();
    if (target) closeComposerElement(target);
  }
});
function showMenu(x, y) {
  menu.hidden = false;
  // Measure the menu's real footprint (the single "Add Comment" pill) rather than
  // a hardcoded size, so the clamp keeps it snug to the selection near viewport edges.
  const w = menu.offsetWidth || 120;
  const h = menu.offsetHeight || 32;
  menu.style.left = Math.max(8, Math.min(x, window.innerWidth - w - 8)) + "px";
  menu.style.top  = Math.max(8, Math.min(y, window.innerHeight - h - 8)) + "px";
}
function showMenuForRange(range) {
  const rects = range.getClientRects();
  const last = rects.length ? rects[rects.length - 1] : range.getBoundingClientRect();
  const x = last.right;
  const y = last.bottom + 6;
  showMenu(x, y);
}
function hideMenu() { menu.hidden = true; }
document.getElementById("menuComment").addEventListener("click", () => {
  hideMenu();
  // Diff sub-line selection: comment the selected region of a line; the same
  // region re-opens its existing comment, a different region makes a new one.
  if (pendingDiffSel) {
    const d = pendingDiffSel;
    pendingDiffSel = null;
    const existing = comments.find(c => c.anchorType === "diff" && c.diffIndex === d.diffIndex
      && c.lineKey === d.lineKey && c.subStart === d.subStart && c.subEnd === d.subEnd);
    if (existing) { openComposerForEdit(existing); return; }
    // A partial overlap with another region on the same line would nest the marks;
    // reject it (like the text layer rejects overlapping selections). An exact
    // match re-opens (above); a fully-disjoint region makes a new comment.
    const overlaps = comments.some(c => c.anchorType === "diff" && c.diffIndex === d.diffIndex
      && c.lineKey === d.lineKey && c.subStart != null && c.subEnd != null
      && c.subStart < d.subEnd && d.subStart < c.subEnd);
    if (overlaps) {
      showToast("That region overlaps an existing comment. Pick a non-overlapping region, or select the exact same region to edit it.");
      return;
    }
    createComposerElement({ mode: "new-diff", diff: d });
    return;
  }
  if (!pendingRange) return;
  // If this exact selection already has a text comment, re-open it for editing
  // instead of stacking a duplicate. A different range (even overlapping) still
  // makes a new comment.
  const s = offsetWithin(pendingRange.startContainer, pendingRange.startOffset);
  const e = offsetWithin(pendingRange.endContainer, pendingRange.endOffset);
  if (s >= 0 && e > s) {
    const existing = comments.find(c => !c.anchorType && c.start === s && c.end === e);
    if (existing) { openComposerForEdit(existing); return; }
  }
  openComposer(pendingRange, pendingQuote);
});
const _menuDocBtn = document.getElementById("menuDocComment");
if (_menuDocBtn) _menuDocBtn.addEventListener("click", () => { hideMenu(); openDocumentComposer(); });

/* ---------- Composer (per-instance, parallel-safe) ---------- */
function bringToFront(el) { el.style.zIndex = ++composerZ; }

function positionComposerNear(el, anchorRect) {
  const w = el.offsetWidth || 380;
  const h = el.offsetHeight || 220;
  const margin = 8;
  let left = Math.min(anchorRect.left, window.innerWidth - w - margin);
  let top  = anchorRect.bottom + margin;
  if (top + h > window.innerHeight) top = Math.max(margin, anchorRect.top - h - margin);
  const step = 28;
  for (let i = 0; i < 8; i++) {
    const collision = [...openComposers].some(other => {
      if (other === el) return false;
      const r = other.getBoundingClientRect();
      return Math.abs(r.left - left) < 8 && Math.abs(r.top - top) < 8;
    });
    if (!collision) break;
    left += step; top += step;
    if (left + w > window.innerWidth - margin || top + h > window.innerHeight - margin) {
      left = margin; top = margin;
      break;
    }
  }
  // Final clamp: keep the whole composer within the viewport even when the anchor
  // itself is off-screen (e.g. a selection below the fold), so its Save button is
  // always reachable.
  left = Math.min(Math.max(margin, left), Math.max(margin, window.innerWidth - w - margin));
  top = Math.min(Math.max(margin, top), Math.max(margin, window.innerHeight - h - margin));
  el.style.left = left + "px";
  el.style.top  = top + "px";
}

function createComposerElement({ mode, range, quote, comment, mermaid, diff, image, widget }) {
  const el = document.createElement("div");
  // Remember what had focus so keyboard users return to the diagram node / diff
  // line / image (not <body>) after the composer closes.
  el._opener = (document.activeElement && document.activeElement !== document.body
    && root.contains(document.activeElement)) ? document.activeElement : null;
  el.className = "cm-composer cm-skip";
  el.setAttribute("role", "group");
  el.setAttribute("aria-label", "Review comment composer");
  el.innerHTML = `
    <div class="cm-composer-handle" title="Drag to move">
      <span class="grip" aria-hidden="true">&#x22EE;&#x22EE;</span>
      <span class="label">drag to move</span>
    </div>
    <div class="quote"></div>
    <textarea aria-label="Review comment" placeholder="Write your review comment... (Ctrl/Cmd+Enter to save, Esc to cancel)"></textarea>
    <div class="row">
      <button type="button" data-act="cancel">Cancel</button>
      <button type="button" class="primary" data-act="save">Save comment</button>
    </div>`;
  const handle = el.querySelector(".cm-composer-handle");
  const quoteEl = el.querySelector(".quote");
  const ta = el.querySelector("textarea");
  const cancelBtn = el.querySelector('[data-act="cancel"]');
  const saveBtn = el.querySelector('[data-act="save"]');
  // Associate the quoted anchor with the textarea for screen readers, and clear the
  // invalid state as soon as the reviewer starts typing.
  const _quoteId = "cm-quote-" + Math.random().toString(36).slice(2, 9);
  quoteEl.id = _quoteId;
  ta.setAttribute("aria-describedby", _quoteId);
  ta.addEventListener("input", () => { ta.removeAttribute("aria-invalid"); ta.classList.remove("cm-invalid"); });

  el._mode = mode;
  el._editingId = comment ? comment.id : null;
  let isCodeQuote = false;
  if (mode === "new") {
    const start = offsetWithin(range.startContainer, range.startOffset);
    const end   = offsetWithin(range.endContainer,   range.endOffset);
    if (start < 0 || end < 0 || start >= end) {
      showToast("Could not anchor that selection. Try again with a single contiguous text range.");
      return null;
    }
    el._start = start;
    el._end = end;
    el._quote = quote;
    let anc = range.startContainer;
    if (anc && anc.nodeType !== 1) anc = anc.parentElement;
    isCodeQuote = !!(anc && anc.closest("code, pre"));
  } else if (mode === "new-mermaid") {
    el._mermaid = mermaid;
    el._quote = mermaid.nodeLabel || mermaid.nodeKey;
  } else if (mode === "new-diff") {
    el._diff = diff;
    el._quote = diff.subStart != null ? diff.quote : ((diff.sign || " ") + diff.text);
    isCodeQuote = true;
  } else if (mode === "new-image") {
    el._image = image;
    el._quote = image.quote;
  } else if (mode === "new-widget") {
    el._widget = widget;
    el._quote = widget.quote || widget.label || widget.part || widget.widget;
  } else if (mode === "new-document") {
    el._quote = "(document-wide comment)";
  } else {
    el._quote = comment.quote;
    isCodeQuote = !!comment.isCode;
  }

  if (isCodeQuote) quoteEl.classList.add("cm-quote-code");
  quoteEl.textContent = el._quote;
  ta.value = comment ? comment.note : "";

  document.body.appendChild(el);
  bringToFront(el);

  let anchorRect;
  if (mode === "new") {
    anchorRect = range.getBoundingClientRect();
  } else if (mode === "new-mermaid") {
    const node = findMermaidNode(mermaid.diagramIndex, mermaid.nodeKey);
    anchorRect = node ? node.getBoundingClientRect() : { left: 100, top: 100, bottom: 130, right: 200 };
  } else if (mode === "new-diff") {
    const el2 = findDiffLineEls(diff.diffIndex, diff.lineKey)[0];
    anchorRect = el2 ? el2.getBoundingClientRect() : { left: 100, top: 100, bottom: 130, right: 200 };
  } else if (mode === "new-image") {
    const imgEl = findImageEl(image.imageIndex);
    anchorRect = imgEl ? imgEl.getBoundingClientRect() : { left: 100, top: 100, bottom: 130, right: 200 };
  } else if (mode === "new-widget") {
    const p = findWidgetPart(widget.widget, widget.part);
    anchorRect = p ? p.getBoundingClientRect() : { left: 120, top: 100, bottom: 130, right: 320 };
  } else if (mode === "new-document") {
    const cx = Math.max(20, Math.round(window.innerWidth / 2) - 190);
    anchorRect = { left: cx, top: 90, bottom: 120, right: cx + 380 };
  } else {
    let anchorEl = null;
    if (comment.anchorType === "mermaid") {
      anchorEl = findMermaidNode(comment.diagramIndex, comment.nodeKey);
    } else if (comment.anchorType === "diff") {
      anchorEl = findDiffLineEls(comment.diffIndex, comment.lineKey)[0];
    } else if (comment.anchorType === "image") {
      anchorEl = findImageEl(comment.imageIndex);
    } else if (comment.anchorType === "widget") {
      anchorEl = findWidgetPart(comment.widget, comment.part);
    } else {
      anchorEl = root.querySelector(`mark.cm-hl[data-cid="${comment.id}"]`);
    }
    anchorRect = anchorEl ? anchorEl.getBoundingClientRect() : { left: 100, top: 100, bottom: 130, right: 200 };
  }
  positionComposerNear(el, anchorRect);

  const cleanups = [];
  cleanups.push(addListener(cancelBtn, "click", () => closeComposerElement(el)));
  cleanups.push(addListener(saveBtn, "click", () => saveComposerElement(el)));
  cleanups.push(addListener(ta, "keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); saveComposerElement(el); }
    else if (e.key === "Escape") { e.preventDefault(); closeComposerElement(el); }
  }));
  cleanups.push(addListener(el, "focusin", () => { lastFocusedComposer = el; bringToFront(el); }));
  cleanups.push(addListener(el, "mousedown", () => { lastFocusedComposer = el; bringToFront(el); }));

  attachDrag(el, handle, cleanups);

  el._cleanup = () => { while (cleanups.length) { try { cleanups.pop()(); } catch (e) {} } };

  openComposers.add(el);
  if (el._editingId) openEditComposers.set(el._editingId, el);
  lastFocusedComposer = el;
  setTimeout(() => ta.focus(), 0);
  return el;
}

function addListener(target, type, fn, opts) {
  target.addEventListener(type, fn, opts);
  return () => target.removeEventListener(type, fn, opts);
}

function attachDrag(el, handle, cleanups) {
  let dragging = false, offX = 0, offY = 0;
  function clamp() {
    const margin = 4;
    const rect = el.getBoundingClientRect();
    const maxLeft = window.innerWidth - rect.width - margin;
    const maxTop = window.innerHeight - rect.height - margin;
    let left = parseFloat(el.style.left) || rect.left;
    let top = parseFloat(el.style.top) || rect.top;
    left = Math.max(margin, Math.min(left, Math.max(margin, maxLeft)));
    top = Math.max(margin, Math.min(top, Math.max(margin, maxTop)));
    el.style.left = left + "px";
    el.style.top = top + "px";
  }
  function onDown(e) {
    const pt = e.touches ? e.touches[0] : e;
    const rect = el.getBoundingClientRect();
    offX = pt.clientX - rect.left;
    offY = pt.clientY - rect.top;
    dragging = true;
    el.classList.add("dragging");
    lastFocusedComposer = el;
    bringToFront(el);
    e.preventDefault();
  }
  function onMove(e) {
    if (!dragging) return;
    const pt = e.touches ? e.touches[0] : e;
    el.style.left = (pt.clientX - offX) + "px";
    el.style.top  = (pt.clientY - offY) + "px";
    clamp();
    e.preventDefault();
  }
  function onUp() {
    if (!dragging) return;
    dragging = false;
    el.classList.remove("dragging");
  }
  cleanups.push(addListener(handle, "mousedown", onDown));
  cleanups.push(addListener(document, "mousemove", onMove));
  cleanups.push(addListener(document, "mouseup", onUp));
  cleanups.push(addListener(handle, "touchstart", onDown, { passive: false }));
  cleanups.push(addListener(document, "touchmove", onMove, { passive: false }));
  cleanups.push(addListener(document, "touchend", onUp));
}

function flashComposer(el) {
  el.classList.remove("flash");
  void el.offsetWidth;
  el.classList.add("flash");
  setTimeout(() => el.classList.remove("flash"), 700);
}

function openComposer(range, quote) {
  return createComposerElement({ mode: "new", range, quote });
}

function openComposerForEdit(comment) {
  const existing = openEditComposers.get(comment.id);
  if (existing) {
    bringToFront(existing);
    flashComposer(existing);
    const r = existing.getBoundingClientRect();
    const outOfView = r.bottom < 0 || r.top > window.innerHeight || r.right < 0 || r.left > window.innerWidth;
    if (outOfView) {
      let anchorEl = null;
      if (comment.anchorType === "mermaid") anchorEl = findMermaidNode(comment.diagramIndex, comment.nodeKey);
      else if (comment.anchorType === "diff") anchorEl = findDiffLineEls(comment.diffIndex, comment.lineKey)[0];
      else if (comment.anchorType === "image") anchorEl = findImageEl(comment.imageIndex);
      else if (comment.anchorType === "widget") anchorEl = findWidgetPart(comment.widget, comment.part);
      else anchorEl = root.querySelector(`mark.cm-hl[data-cid="${comment.id}"]`);
      if (anchorEl) positionComposerNear(existing, anchorEl.getBoundingClientRect());
    }
    existing.querySelector("textarea").focus();
    return existing;
  }
  return createComposerElement({ mode: "edit", comment });
}

function closeComposerElement(el) {
  if (!el || !openComposers.has(el)) return;
  openComposers.delete(el);
  if (el._editingId) openEditComposers.delete(el._editingId);
  if (lastFocusedComposer === el) lastFocusedComposer = null;
  if (typeof el._cleanup === "function") el._cleanup();
  const opener = el._opener;
  el.remove();
  // Return focus to whatever opened the composer (e.g. a keyboard-focused diff
  // line or image) if it is still connected, so keyboard users keep their place.
  if (opener && opener.isConnected && root.contains(opener)) {
    try { opener.focus(); } catch (e) {}
  }
}

function saveComposerElement(el) {
  const ta = el.querySelector("textarea");
  const note = ta.value.trim();
  if (!note) {
    // Blank note: mark the field invalid (announced to screen readers) instead of
    // silently doing nothing, then return focus for the reviewer to type.
    ta.setAttribute("aria-invalid", "true");
    ta.classList.add("cm-invalid");
    ta.focus();
    return;
  }
  ta.removeAttribute("aria-invalid");
  ta.classList.remove("cm-invalid");
  if (el._editingId) {
    const c = comments.find(c => c.id === el._editingId);
    if (c) { c.note = note; c.updatedAt = new Date().toISOString(); }
  } else if (el._mode === "new-mermaid") {
    const info = el._mermaid;
    const host = mermaidHostForIndex(info.diagramIndex);
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const ctx = host ? captureMermaidContext(host) : { section: null, headingPath: [] };
    const comment = {
      id,
      anchorType: "mermaid",
      diagramIndex: info.diagramIndex,
      nodeKey: info.nodeKey,
      nodeLabel: info.nodeLabel,
      quote: info.nodeLabel || info.nodeKey,
      note,
      createdAt: new Date().toISOString(),
      ...ctx,
    };
    comments.push(comment);
    if (!applyMermaidHighlight(comment)) {
      showToast("Comment saved, but the mermaid node could not be highlighted (the diagram may have re-rendered).");
    }
  } else if (el._mode === "new-diff") {
    const info = el._diff;
    const block = diffBlockForIndex(info.diffIndex);
    const host = block ? block.host : null;
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const ctx = host ? captureMermaidContext(host) : { section: null, headingPath: [] };
    const comment = {
      id,
      anchorType: "diff",
      diffIndex: info.diffIndex,
      lineKey: info.lineKey,
      side: info.side,
      lineType: info.lineType,
      oldNo: info.oldNo,
      newNo: info.newNo,
      diffLabel: info.label,
      subStart: info.subStart != null ? info.subStart : null,
      subEnd: info.subEnd != null ? info.subEnd : null,
      quote: info.subStart != null ? info.quote : ((info.sign || " ") + info.text),
      isCode: true,
      note,
      createdAt: new Date().toISOString(),
      ...ctx,
    };
    comments.push(comment);
    if (!applyDiffHighlight(comment)) {
      showToast("Comment saved, but the diff line could not be highlighted (the diff may have re-rendered).");
    }
  } else if (el._mode === "new-image") {
    const info = el._image;
    const img = findImageEl(info.imageIndex);
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const ctx = img ? captureMermaidContext(img) : { section: null, headingPath: [] };
    const comment = {
      id,
      anchorType: "image",
      imageIndex: info.imageIndex,
      imageSrc: info.src,
      imageAlt: info.alt,
      imageKind: info.kind || "image",
      quote: info.quote,
      note,
      createdAt: new Date().toISOString(),
      ...ctx,
    };
    comments.push(comment);
    if (!applyImageHighlight(comment)) {
      showToast("Comment saved, but the image could not be highlighted.");
    }
  } else if (el._mode === "new-widget") {
    const info = el._widget;
    const partEl = findWidgetPart(info.widget, info.part);
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const ctx = partEl ? captureMermaidContext(partEl) : { section: null, headingPath: [] };
    const comment = {
      id,
      anchorType: "widget",
      widget: info.widget,
      part: info.part,
      partLabel: info.label,
      slot: info.slot != null ? info.slot : null,
      quote: info.quote,
      note,
      createdAt: new Date().toISOString(),
      ...ctx,
    };
    comments.push(comment);
    if (!applyWidgetHighlight(comment)) {
      showToast("Comment saved, but the widget part could not be highlighted.");
    }
  } else if (el._mode === "new-document") {
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const comment = {
      id,
      anchorType: "document",
      quote: "(document-wide)",
      note,
      createdAt: new Date().toISOString(),
      section: null,
      headingPath: [],
    };
    comments.push(comment);
  } else {
    const r = rangeFromOffsets(el._start, el._end);
    if (!r) {
      showToast("Could not re-anchor that selection (the text may have changed). Try again.");
      return;
    }
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const ctx = captureContext(el._start, el._end, r);
    const comment = {
      id, quote: el._quote, note,
      start: el._start, end: el._end,
      createdAt: new Date().toISOString(),
      ...ctx,
    };
    comments.push(comment);
    try {
      wrapRangeWithMark(r, id);
    } catch (e) {
      comments.pop();
      showToast("Could not highlight that range (it may overlap an existing comment). Comment was not saved.");
      return;
    }
    window.getSelection().removeAllRanges();
  }
  saveComments();
  renderComments();
  closeComposerElement(el);
  openSidebar();
}

/* ---------- Sidebar rendering ---------- */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
function formatTime(iso) {
  try {
    // Month name (not a number) so the date is unambiguous across M/D/Y and D/M/Y
    // locales (e.g. "Jul 9, 2026, 13:07"). 24-hour time, no AM/PM.
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", hour12: false
    });
  }
  catch (e) { return iso; }
}
let commentSort = "pos";
try { commentSort = localStorage.getItem(COMMENT_KEY + "::commentSort") || "pos"; } catch (e) { /* private mode */ }
function commentTimeValue(c) {
  const t = Date.parse((c && (c.updatedAt || c.createdAt)) || "");
  return isNaN(t) ? 0 : t;
}
// The sidebar shows a "Generated on" / "Last comment" info line. "Generated on" comes
// from a data-generated attribute on #commentRoot when the author set one (deterministic),
// else the file's own last-modified time; "Last comment" is the newest comment timestamp.
function updateSideInfo() {
  const gen = document.getElementById("cmGenerated");
  const last = document.getElementById("cmLastComment");
  if (gen) {
    let g = root.getAttribute("data-generated");
    if (!g) { const lm = Date.parse(document.lastModified); if (!isNaN(lm)) g = new Date(lm).toISOString(); }
    gen.textContent = "Generated on: " + (g ? formatTime(g) : "unknown");
  }
  if (last) {
    if (comments.length) {
      const t = Math.max.apply(null, comments.map(commentTimeValue));
      last.textContent = "Last comment: " + (t ? formatTime(new Date(t).toISOString()) : "-");
    } else {
      last.textContent = "Last comment: none yet";
    }
  }
}
function updateSortUi() {
  const a = document.getElementById("btnSortAsc"), d = document.getElementById("btnSortDesc");
  if (a) a.setAttribute("aria-pressed", commentSort === "time-asc" ? "true" : "false");
  if (d) d.setAttribute("aria-pressed", commentSort === "time-desc" ? "true" : "false");
}
function renderComments() {
  toolbarCount.textContent = comments.length;
  sidebarCount.textContent = comments.length;
  if (typeof updateDocTypeUi === "function") updateDocTypeUi();
  updateSideInfo();
  updateSortUi();
  const stateChanges = (typeof widgetStateChanges === "function") ? widgetStateChanges() : [];
  const stateHtml = stateChanges.length ? _renderWidgetStateCard(stateChanges) : "";
  const clPieces = (typeof checklistCardPieces === "function") ? checklistCardPieces() : [];
  if (!comments.length && !stateChanges.length && !clPieces.length) {
    const deckHint = IS_DECK
      ? "<p><strong>On this deck:</strong> in comment mode, select text on the current slide and choose <em>Add Comment</em>, or right-click empty slide space for a whole-slide comment. Move between slides with Prev / Next or the arrow keys.</p>"
      : "";
    listEl.innerHTML = `
      <div class="cm-empty">
        <p><strong>No comments yet.</strong></p>
        ${deckHint}
        <p>Select any text in the document, then right-click and choose <em>Add Comment</em>. Mermaid nodes, diff lines, images, and widget parts: hover (or keyboard-focus) and click <em>Add Comment</em>. Right-click empty space for a document-wide comment. Comments stay here until the agent processes them. Click <kbd>Copy all</kbd> to send the bundle to the clipboard; the agent then marks them handled in this HTML file, and they are pruned automatically on the next reload.</p>
      </div>`;
    if (typeof applyCommentSearch === "function") applyCommentSearch();
    return;
  }
  const sortKey = (c) => (c.anchorType === "document")
    ? -1
    : (c.anchorType === "mermaid")
    ? (1e12 + (c.diagramIndex || 0) * 1000)
    : (c.anchorType === "diff")
    ? (2e12 + (c.diffIndex || 0) * 1e6 + (parseInt(c.lineKey, 10) || 0))
    : (c.anchorType === "image")
    ? (3e12 + (c.imageIndex || 0))
    : (c.anchorType === "widget")
    ? (4e12 + _widgetOrderKey(c))
    : (typeof c.start === "number" ? c.start : 0);
  const sorted = (commentSort === "time-asc")
    ? [...comments].sort((a, b) => (commentTimeValue(a) - commentTimeValue(b)) || (sortKey(a) - sortKey(b)))
    : (commentSort === "time-desc")
    ? [...comments].sort((a, b) => (commentTimeValue(b) - commentTimeValue(a)) || (sortKey(a) - sortKey(b)))
    : [...comments].sort((a, b) => sortKey(a) - sortKey(b));
  const commentHtml = sorted.map((c, i) => {
    const isMermaid = c.anchorType === "mermaid";
    const isDiff = c.anchorType === "diff";
    const isImage = c.anchorType === "image";
    const isWidget = c.anchorType === "widget";
    const isDocument = c.anchorType === "document";
    const path = (c.headingPath && c.headingPath.length)
      ? c.headingPath.map(h => escapeHtml(h.text)).join(" &rsaquo; ")
      : (c.section ? escapeHtml(c.section) : "");
    const sectionHtml = path ? `<div class="section">in: <strong>${path}</strong></div>` : "";
    let quoteHtml;
    if (isMermaid) {
      quoteHtml = `<div class="quote"><span class="ctx">${c.nodeKey === "__diagram__" ? "mermaid diagram: " : "mermaid node: "}</span><span class="quoted">"${escapeHtml(c.nodeLabel || c.nodeKey || "")}"</span></div>`;
    } else if (isImage) {
      const mediaLbl = c.imageKind === "chart" ? "chart: " : "image: ";
      quoteHtml = `<div class="quote"><span class="ctx">${mediaLbl}</span><span class="quoted">${escapeHtml(c.imageAlt || c.quote || c.imageSrc || "")}</span></div>`;
    } else if (isWidget) {
      quoteHtml = `<div class="quote"><span class="ctx">${escapeHtml(c.widget || "widget")}: </span><span class="quoted">"${escapeHtml(c.partLabel || c.part || "")}"</span></div>`;
    } else if (isDocument) {
      quoteHtml = `<div class="quote"><span class="quoted">(document-wide comment)</span></div>`;
    } else if (c.isCode) {
      // Code-block quotes are rendered as a single preformatted block (no before/after
      // ctx) because surrounding code lines look misleading when collapsed to one line.
      quoteHtml = `<div class="quote cm-quote-code">${escapeHtml(c.quote)}</div>`;
    } else if (c.before || c.after) {
      quoteHtml = `<div class="quote"><span class="ctx">${escapeHtml(c.before || "")}</span><span class="quoted">"${escapeHtml(c.quote)}"</span><span class="ctx">${escapeHtml(c.after || "")}</span></div>`;
    } else {
      quoteHtml = `<div class="quote"><span class="quoted">"${escapeHtml(c.quote)}"</span></div>`;
    }
    const pinBits = [];
    if (isMermaid) {
      pinBits.push(`mermaid diagram ${(Number(c.diagramIndex) || 0) + 1}`);
      if (c.nodeKey && c.nodeKey !== "__diagram__") pinBits.push(`node ${escapeHtml(c.nodeKey)}`);
      else pinBits.push("whole diagram");
    } else if (isDiff) {
      pinBits.push(`diff${c.diffLabel ? " " + escapeHtml(c.diffLabel) : ""}`);
      pinBits.push(escapeHtml(diffLineLocator(c)));
    } else if (isImage) {
      pinBits.push(`${c.imageKind === "chart" ? "chart" : "image"} ${(Number(c.imageIndex) || 0) + 1}`);
      const src = String(c.imageSrc == null ? "" : c.imageSrc);
      if (src) pinBits.push(escapeHtml(src.length > 60 ? src.slice(0, 57) + "..." : src));
    } else if (isWidget) {
      pinBits.push(`widget "${escapeHtml(c.widget || "")}"`);
      pinBits.push(`part "${escapeHtml(c.partLabel || c.part || "")}"`);
    } else if (isDocument) {
      pinBits.push("document-wide");
    } else {
      if (c.isCode) {
        pinBits.push(c.codeLanguage ? `code (${escapeHtml(c.codeLanguage)})` : "code block");
      }
      // The prose pinpoint ("in <li> - match 2 of 4") is internal grep-help for the
      // agent; it is still emitted in the Copy bundle's Pinpoint line but is not shown
      // on the sidebar card, which only surfaces reader-facing anchor info.
    }
    const pinHtml = pinBits.length ? `<div class="pin">${pinBits.join(" - ")}</div>` : "";
    const jumpTarget = isMermaid ? "node" : isDiff ? "diff line" : isImage ? (c.imageKind === "chart" ? "chart" : "image") : isWidget ? "element" : "text";
    const cardClass = isDocument ? "cm-card cm-card-doc" : "cm-card";
    const jumpBtn = isDocument ? "" : `<button type="button" data-act="jump" title="Scroll to highlighted ${jumpTarget}">jump</button>`;
    return `
    <article class="${cardClass}" data-cid="${c.id}">
      ${sectionHtml}
      ${quoteHtml}
      ${pinHtml}
      <div class="note">${escapeHtml(c.note)}</div>
      <div class="meta">
        <span>#${i + 1} - ${escapeHtml(formatTime(c.updatedAt || c.createdAt))}${c.updatedAt ? " (edited)" : ""}</span>
        <span class="acts">
          ${jumpBtn}
          <button type="button" data-act="edit" title="Edit comment">edit</button>
          <button type="button" class="del" data-act="del" title="Delete comment">delete</button>
        </span>
      </div>
    </article>`;
  });
  const commentPieces = commentHtml.map((html, i) => ({ pos: sortKey(sorted[i]), html }));
  // Insert each checklist card by document position while preserving the comments' current
  // (position or time) sort order, so a time sort is not overridden and no card is dropped.
  const cls = clPieces.slice().sort((a, b) => a.pos - b.pos);
  const parts = [];
  let ci = 0;
  commentPieces.forEach((cp) => {
    while (ci < cls.length && cls[ci].pos <= cp.pos) parts.push(cls[ci++].html);
    parts.push(cp.html);
  });
  while (ci < cls.length) parts.push(cls[ci++].html);
  listEl.innerHTML = stateHtml + parts.join("");
  if (typeof applyCommentSearch === "function") applyCommentSearch();
}
function _widgetOrderKey(c) {
  const o = _widgetOrder.get(partKey(c.widget, c.part));
  return o == null ? 1e9 : o;
}
// The display name for a board in the sidebar: its author-supplied aria-label if present,
// else the raw data-cm-widget name.
function _widgetDisplayName(name) {
  try {
    const el = root.querySelector('[data-cm-widget="' + _cssEsc(name) + '"]');
    if (el) { const al = el.getAttribute("aria-label"); if (al && al.trim()) return al.trim(); }
  } catch (e) { /* invalid selector from an exotic name - fall through */ }
  return name;
}
// Scroll a board into view and flash it, so a state card's "jump" behaves like a comment card.
function _jumpToWidget(name) {
  if (!name) return;
  let el = null;
  try { el = root.querySelector('[data-cm-widget="' + _cssEsc(name) + '"]'); } catch (e) { /* invalid selector */ }
  if (!el) return;
  expandCollapsedAncestors(el);
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("cm-widget-flash");
  setTimeout(() => el.classList.remove("cm-widget-flash"), 2200);
}
// One state card PER changed board, shaped like a regular comment card: an "in: <board>"
// title, a jump button that focuses that board, the moved-part list, and a meta line with the
// first-change time plus a "Reset changes" button that restores that board only.
function _renderWidgetStateCard(changes) {
  const groups = new Map();
  changes.forEach((ch) => {
    if (!groups.has(ch.widget)) groups.set(ch.widget, []);
    groups.get(ch.widget).push(ch);
  });
  const first = (typeof widgetFirstChangeAt === "function") ? widgetFirstChangeAt() : null;
  const timeHtml = first ? escapeHtml(formatTime(first)) : "";
  let html = "";
  groups.forEach((list, name) => {
    const items = list.map((ch) =>
      `<li>"${escapeHtml(ch.label || ch.part)}" moved from <strong>${escapeHtml(ch.from)}</strong> to <strong>${escapeHtml(ch.to)}</strong></li>`
    ).join("");
    html += `
    <article class="cm-card cm-card-state" data-cm-state="1" data-cm-widget-name="${escapeHtml(name)}">
      <div class="section">in: <strong>${escapeHtml(_widgetDisplayName(name))}</strong></div>
      <div class="cm-card-state-title">Layout change - ${list.length} item${list.length === 1 ? "" : "s"} moved</div>
      <ul>${items}</ul>
      <div class="note">Auto-tracked from the current layout. Included in Copy all so the agent can reformat the source; the file stays Not portable until re-exported.</div>
      <div class="meta">
        <span>${timeHtml}</span>
        <span class="acts">
          <button type="button" data-act="state-jump" data-cm-widget-name="${escapeHtml(name)}" title="Scroll to this board">jump</button>
          <button type="button" data-act="state-reset" data-cm-widget-name="${escapeHtml(name)}" title="Return cards to their original positions">Reset changes</button>
        </span>
      </div>
    </article>`;
  });
  return html;
}
// Scroll the anchored content (text highlight, mermaid node, diff line, or image) into
// view and flash it. Shared by the jump button and by edit/delete (so the user sees which
// comment is affected before the composer opens or the confirm dialog appears).
function scrollToAnchor(c) {
  if (!c) return;
  let el = null;
  if (c.anchorType === "mermaid") el = findMermaidNode(c.diagramIndex, c.nodeKey);
  else if (c.anchorType === "diff") el = findDiffLineEls(c.diffIndex, c.lineKey)[0];
  else if (c.anchorType === "image") el = findImageEl(c.imageIndex);
  else if (c.anchorType === "widget") el = findWidgetPart(c.widget, c.part);
  else if (c.anchorType === "document") {
    // On a fixed-stage deck, window.scrollTo is a no-op; jump to the first slide (the natural
    // document start) so a document-wide comment card does not strand the presenter.
    if (window.__cmhDeck) window.__cmhDeck.showSlide(0);
    else window.scrollTo({ top: 0, behavior: "smooth" });
    flashActive(c.id);
    return;
  }
  else el = root.querySelector(`mark.cm-hl[data-cid="${c.id}"]`);
  if (el) { expandCollapsedAncestors(el); el.scrollIntoView({ behavior: "smooth", block: "center" }); flashActive(c.id); }
}
// A comment can live inside a collapsed section (display:none = no layout box), so
// expand every collapsed ancestor section before scrolling to it.
function expandCollapsedAncestors(el) {
  let sec = el && el.closest && el.closest("section.cmh-section-collapsed");
  while (sec) {
    sec.classList.remove("cmh-section-collapsed");
    const caret = sec.querySelector(":scope > .cmh-section-heading .cmh-sec-caret");
    if (caret) { caret.setAttribute("aria-expanded", "true"); caret.title = "Collapse section"; }
    sec = sec.parentElement && sec.parentElement.closest && sec.parentElement.closest("section.cmh-section-collapsed");
  }
}
listEl.addEventListener("click", (e) => {
  // Checklist change cards are not comments: jump focuses the checklist, Reset reverts it to
  // the authored state. Handle before the .cm-card comment path (a checklist card is a .cm-card).
  const clCard = e.target.closest(".cm-card-checklist");
  if (clCard) {
    const cid = e.target.getAttribute("data-cmh-checklist-name") || clCard.getAttribute("data-cmh-checklist-name");
    if (e.target.dataset.act === "cl-reset") { if (typeof resetChecklist === "function") resetChecklist(cid); }
    else if (typeof jumpToChecklist === "function") jumpToChecklist(cid);
    return;
  }
  // Widget state cards are not comments: their jump focuses the board and their Reset
  // restores that board's layout. Handle them before the comment-id path below.
  const stateCard = e.target.closest(".cm-card-state");
  if (stateCard) {
    const name = e.target.getAttribute("data-cm-widget-name") || stateCard.getAttribute("data-cm-widget-name");
    if (e.target.dataset.act === "state-reset") {
      let wel = null;
      try { wel = root.querySelector('[data-cm-widget="' + _cssEsc(name) + '"]'); } catch (err) { /* invalid selector */ }
      if (wel && typeof resetWidgetMoves === "function") resetWidgetMoves(wel);
    } else {
      _jumpToWidget(name);
    }
    return;
  }
  const card = e.target.closest(".cm-card");
  if (!card) return;
  const id = card.dataset.cid;
  const act = e.target.dataset.act;
  if (act === "del") {
    const c = comments.find(x => x.id === id);
    scrollToAnchor(c);                       // jump to the anchor first, then confirm
    if (confirm("Delete this comment?")) {
      _tombstoneEmbedded([id]);
      comments = comments.filter(x => x.id !== id);
      removeHighlight(c);
      saveComments();
      renderComments();
    }
    return;
  }
  if (act === "edit") {
    const c = comments.find(c => c.id === id);
    if (c) { scrollToAnchor(c); openComposerForEdit(c); }   // jump first, then edit
    return;
  }
  const c = comments.find(x => x.id === id);
  scrollToAnchor(c);
});
function flashActive(id) {
  root.querySelectorAll("mark.cm-hl.active").forEach(m => m.classList.remove("active"));
  listEl.querySelectorAll(".cm-card.active").forEach(c => c.classList.remove("active"));
  root.querySelectorAll(`mark.cm-hl[data-cid="${id}"]`).forEach(m => m.classList.add("active"));
  flashMermaid(id);
  flashDiff(id);
  flashImage(id);
  flashWidget(id);
  const card = listEl.querySelector(`.cm-card[data-cid="${id}"]`);
  if (card) card.classList.add("active");
  setTimeout(() => {
    root.querySelectorAll(`mark.cm-hl[data-cid="${id}"]`).forEach(m => m.classList.remove("active"));
  }, 2200);
}
root.addEventListener("click", (e) => {
  const m = e.target.closest("mark.cm-hl");
  if (!m) return;
  const id = m.dataset.cid;
  openSidebar();
  const card = listEl.querySelector(`.cm-card[data-cid="${id}"]`);
  if (card) { card.scrollIntoView({ behavior: "smooth", block: "center" }); flashActive(id); }
});

/* ---------- Comment search / filter ---------- */
// A single search field in the sidebar header filters the rendered comment cards to only
// those whose text matches the query case-insensitively, and shows a "shown / total" count.
// The query is module-level so it survives re-renders: renderComments() re-applies it at the
// end of every render, so adding, editing, or sorting comments keeps the active filter.
let commentSearchQuery = "";

// The substantive, reader-facing text of a comment card: the reviewer's note plus the quoted
// content, section path, and pin. Action-button labels (jump/edit/delete) and the meta line
// are excluded so a query never matches chrome.
function _commentCardHaystack(card) {
  let text = "";
  card.querySelectorAll(".note, .quote, .section, .pin").forEach((el) => {
    text += " " + (el.textContent || "");
  });
  return text.toLowerCase();
}

function _toggleSearchEmptyNote(show) {
  if (!listEl) return;
  let note = listEl.querySelector(".cm-search-empty");
  if (show) {
    if (!note) {
      note = document.createElement("div");
      note.className = "cm-empty cm-search-empty";
      note.innerHTML = "<p>No comments match your search.</p>";
      listEl.appendChild(note);
    }
    note.hidden = false;
  } else if (note) {
    note.hidden = true;
  }
}

// Re-apply the active query to the currently-rendered cards. Called by the input handler and
// at the end of renderComments(). With no comments the whole row is hidden (nothing to search).
function applyCommentSearch() {
  const row = document.querySelector(".head-search");
  const countEl = document.getElementById("cmSearchCount");
  const clearBtn = document.getElementById("cmSearchClear");
  const total = Array.isArray(comments) ? comments.length : 0;
  if (row) row.hidden = total === 0;
  if (total === 0) {
    _toggleSearchEmptyNote(false);
    return;
  }
  const q = commentSearchQuery.trim().toLowerCase();
  if (clearBtn) clearBtn.hidden = q === "";
  const cards = listEl ? listEl.querySelectorAll(".cm-card[data-cid]") : [];
  let shown = 0;
  cards.forEach((card) => {
    const match = q === "" || _commentCardHaystack(card).indexOf(q) !== -1;
    card.classList.toggle("cm-hidden", !match);
    if (match) shown++;
  });
  // A widget layout-change card and a checklist card are not comments; while a search is
  // active they would be noise, so hide them. An empty query restores them.
  if (listEl) {
    listEl.querySelectorAll(".cm-card-state, .cm-card-checklist").forEach((c) => {
      c.classList.toggle("cm-hidden", q !== "");
    });
  }
  if (countEl) {
    countEl.textContent = shown + " / " + total;
    countEl.hidden = false;
  }
  _toggleSearchEmptyNote(q !== "" && shown === 0);
}

function setupCommentSearch() {
  const input = document.getElementById("cmSearchInput");
  const clearBtn = document.getElementById("cmSearchClear");
  if (!input) return;
  input.addEventListener("input", () => {
    commentSearchQuery = input.value || "";
    applyCommentSearch();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && input.value) {
      input.value = "";
      commentSearchQuery = "";
      applyCommentSearch();
      e.stopPropagation();
    }
  });
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      input.value = "";
      commentSearchQuery = "";
      applyCommentSearch();
      input.focus();
    });
  }
  applyCommentSearch();
}
/* ---------- Hover bubble to open a comment ----------
   A highlighted region can itself be a link (or other clickable element), so a plain
   click there navigates instead of opening the comment. Hovering any highlight shows
   this small bubble; clicking it opens the comment regardless of what the text links to. */
const hlBubble = document.getElementById("hlBubble");
let hlBubbleCid = null, hlBubbleMark = null, hlBubbleHideTimer = null;
function positionHlBubble(mark) {
  const rect = mark.getClientRects()[0] || mark.getBoundingClientRect();
  const visible = _clipAwareRect(mark, rect);
  if (!visible) {
    hlBubble.hidden = true; hlBubbleCid = null; hlBubbleMark = null; return;
  }
  const bw = hlBubble.offsetWidth || 22, bh = hlBubble.offsetHeight || 22;
  const bounds = _floatingBounds(mark);
  let left = visible.right - bw / 2;
  let top  = visible.top - bh + 4;
  if (top < bounds.top) top = visible.bottom - 4;
  left = _clamp(left, bounds.left, bounds.right - bw);
  top  = _clamp(top, bounds.top, bounds.bottom - bh);
  hlBubble.style.left = left + "px";
  hlBubble.style.top  = top  + "px";
}
function showHlBubbleFor(mark) {
  if (!mark.dataset.cid) return;
  if (hlBubbleHideTimer) { clearTimeout(hlBubbleHideTimer); hlBubbleHideTimer = null; }
  hlBubbleCid = mark.dataset.cid;
  hlBubbleMark = mark;
  hlBubble.hidden = false;
  positionHlBubble(mark);
}
function scheduleHideHlBubble() {
  if (hlBubbleHideTimer) clearTimeout(hlBubbleHideTimer);
  hlBubbleHideTimer = setTimeout(() => {
    if (!hlBubble.matches(":hover")) { hlBubble.hidden = true; hlBubbleCid = null; hlBubbleMark = null; }
  }, 240);
}
root.addEventListener("mouseover", (e) => {
  if (e.buttons) return; // mid-drag: user is selecting text, don't pop the bubble
  const mark = e.target.closest && e.target.closest("mark.cm-hl");
  if (!mark || !root.contains(mark)) return;
  if (mark === hlBubbleMark && !hlBubble.hidden) {
    if (hlBubbleHideTimer) { clearTimeout(hlBubbleHideTimer); hlBubbleHideTimer = null; }
    return;
  }
  showHlBubbleFor(mark);
});
root.addEventListener("mouseout", (e) => {
  if (!(e.target.closest && e.target.closest("mark.cm-hl"))) return;
  const to = e.relatedTarget;
  if (to && to.closest && (to.closest("mark.cm-hl") || to.closest(".cm-hl-bubble"))) return;
  scheduleHideHlBubble();
});
hlBubble.addEventListener("mouseenter", () => {
  if (hlBubbleHideTimer) { clearTimeout(hlBubbleHideTimer); hlBubbleHideTimer = null; }
});
hlBubble.addEventListener("mouseleave", scheduleHideHlBubble);
hlBubble.addEventListener("click", (e) => {
  e.preventDefault(); e.stopPropagation();
  const id = hlBubbleCid;
  hlBubble.hidden = true; hlBubbleCid = null; hlBubbleMark = null;
  if (!id) return;
  openSidebar();
  const card = listEl.querySelector(`.cm-card[data-cid="${id}"]`);
  if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
  flashActive(id);
});
window.addEventListener("scroll", () => {
  if (hlBubble.hidden) return;
  if (hlBubbleMark && root.contains(hlBubbleMark)) positionHlBubble(hlBubbleMark);
  else { hlBubble.hidden = true; hlBubbleCid = null; hlBubbleMark = null; }
}, true);
// Keep the floating add-comment buttons (image / mermaid / diff) pinned to their
// target while scrolling or resizing, instead of leaving them at a stale fixed
// position. If the target scrolls out of view, hide the button rather than clamp
// it to a viewport edge (detached from what it points at).
function repositionActiveAdd() {
  if (!_activeAdd || !_activeAdd.btn || _activeAdd.btn.hidden) return;
  const el = _activeAdd.el;
  // Re-run positioning only (never show*AddFor), so a scroll cannot cancel the
  // mouseleave hide-timer and leave a stuck button. position() returns false when
  // the target scrolled out of view or collapsed to zero size; hide and clear then.
  if (!el || !root.contains(el) || !_activeAdd.position()) {
    _activeAdd.btn.hidden = true;
    if (_activeAdd.clear) _activeAdd.clear();
    _activeAdd = null;
  }
}
let _repositionAddRaf = 0;
function scheduleRepositionActiveAdd() {
  if (_repositionAddRaf) return;
  if (typeof requestAnimationFrame !== "function") { repositionActiveAdd(); return; }
  _repositionAddRaf = requestAnimationFrame(() => { _repositionAddRaf = 0; repositionActiveAdd(); });
}
window.addEventListener("scroll", scheduleRepositionActiveAdd, true);
window.addEventListener("resize", scheduleRepositionActiveAdd);
window.addEventListener("resize", () => {
  if (hlBubble.hidden) return;
  if (hlBubbleMark && root.contains(hlBubbleMark)) positionHlBubble(hlBubbleMark);
  else { hlBubble.hidden = true; hlBubbleCid = null; hlBubbleMark = null; }
});
// A mousedown that is not on the bubble means a click or selection is starting; drop the
// bubble so it can never act on a stale highlight (e.g. a drag-select that began on another mark).
document.addEventListener("mousedown", (e) => {
  if (hlBubble.hidden) return;
  if (e.target.closest && e.target.closest(".cm-hl-bubble")) return;
  if (hlBubbleHideTimer) { clearTimeout(hlBubbleHideTimer); hlBubbleHideTimer = null; }
  hlBubble.hidden = true; hlBubbleCid = null; hlBubbleMark = null;
});


let _sidebarWidthPx = 0;
function _sidebarWidthBounds() {
  const vw = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0, 1);
  const narrow = vw < 700;
  const min = Math.min(narrow ? 144 : 192, Math.max(108, vw - 48));
  const max = Math.max(min, Math.min(narrow ? Math.round(vw * 0.82) : 720, vw - 24));
  return { min: min, max: max, defaultWidth: Math.max(min, Math.min(400, max)) };
}
function _clampSidebarWidth(value) {
  const b = _sidebarWidthBounds();
  const n = Number(value);
  if (!Number.isFinite(n)) return b.defaultWidth;
  return Math.max(b.min, Math.min(b.max, Math.round(n)));
}
function _setSidebarWidth(value, persist) {
  const b = _sidebarWidthBounds();
  const w = _clampSidebarWidth(value);
  _sidebarWidthPx = w;
  document.documentElement.style.setProperty("--cm-sidebar-w", w + "px");
  if (sidebar) sidebar.classList.toggle("is-narrow", w <= 340);
  const handle = document.getElementById("sidebarResizeHandle");
  if (handle) {
    handle.setAttribute("aria-valuemin", String(b.min));
    handle.setAttribute("aria-valuemax", String(b.max));
    handle.setAttribute("aria-valuenow", String(w));
    handle.setAttribute("aria-valuetext", w + " pixels");
  }
  if (persist) {
    try { localStorage.setItem(SIDEBAR_WIDTH_KEY, String(w)); } catch (e) { /* private mode */ }
  }
  _syncFloatingAfterLayoutShift();
  return w;
}
function setupSidebarResize() {
  if (!sidebar) return;
  let saved = null;
  try { saved = localStorage.getItem(SIDEBAR_WIDTH_KEY); } catch (e) { saved = null; }
  _setSidebarWidth(saved == null ? _sidebarWidthBounds().defaultWidth : Number(saved), false);
  window.addEventListener("resize", function () { _setSidebarWidth(_sidebarWidthPx || _sidebarWidthBounds().defaultWidth, false); });
  const handle = document.getElementById("sidebarResizeHandle");
  if (!handle || handle._cmWired) return;
  handle._cmWired = true;
  let dragging = false;
  function widthFromEvent(e) { return (window.innerWidth || document.documentElement.clientWidth || 0) - e.clientX; }
  function onDrag(e) {
    if (!dragging) return;
    _setSidebarWidth(widthFromEvent(e), false);
    e.preventDefault();
  }
  function finish(e) {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove("cm-sidebar-resizing");
    document.removeEventListener("pointermove", onDrag, true);
    document.removeEventListener("pointerup", finish, true);
    document.removeEventListener("pointercancel", finish, true);
    try { handle.releasePointerCapture(e.pointerId); } catch (err) { /* pointer may already be released */ }
    _setSidebarWidth(_sidebarWidthPx, true);
  }
  handle.addEventListener("pointerdown", beginPointerResize);
  handle.addEventListener("pointermove", onDrag);
  handle.addEventListener("pointerup", finish);
  handle.addEventListener("pointercancel", finish);
  function onMouseDrag(e) {
    if (!dragging) return;
    _setSidebarWidth(widthFromEvent(e), false);
    e.preventDefault();
  }
  function finishMouse(e) {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove("cm-sidebar-resizing");
    document.removeEventListener("mousemove", onMouseDrag, true);
    document.removeEventListener("mouseup", finishMouse, true);
    _setSidebarWidth(_sidebarWidthPx, true);
    e.preventDefault();
  }
  function beginMouseResize(e) {
    if (dragging || (e.button != null && e.button !== 0)) return false;
    dragging = true;
    handle.focus({ preventScroll: true });
    document.body.classList.add("cm-sidebar-resizing");
    document.addEventListener("mousemove", onMouseDrag, true);
    document.addEventListener("mouseup", finishMouse, true);
    _setSidebarWidth(widthFromEvent(e), false);
    e.preventDefault();
    return true;
  }
  function beginPointerResize(e) {
    if (dragging || (e.button != null && e.button !== 0)) return false;
    dragging = true;
    handle.focus({ preventScroll: true });
    document.body.classList.add("cm-sidebar-resizing");
    try { handle.setPointerCapture(e.pointerId); } catch (err) { /* capture is best effort */ }
    document.addEventListener("pointermove", onDrag, true);
    document.addEventListener("pointerup", finish, true);
    document.addEventListener("pointercancel", finish, true);
    _setSidebarWidth(widthFromEvent(e), false);
    e.preventDefault();
    return true;
  }
  handle.addEventListener("mousedown", beginMouseResize);
  if (sidebar) {
    sidebar.addEventListener("mousedown", function (e) {
      const r = sidebar.getBoundingClientRect();
      if (e.clientX <= r.left + 12) beginMouseResize(e);
    });
    sidebar.addEventListener("pointerdown", function (e) {
      const r = sidebar.getBoundingClientRect();
      if (e.clientX <= r.left + 12) beginPointerResize(e);
    });
  }
  handle.addEventListener("dblclick", function () { _setSidebarWidth(_sidebarWidthBounds().defaultWidth, true); });
  handle.addEventListener("keydown", function (e) {
    const b = _sidebarWidthBounds();
    const step = e.shiftKey ? 60 : 20;
    let next = null;
    if (e.key === "ArrowLeft") next = (_sidebarWidthPx || b.defaultWidth) + step;
    else if (e.key === "ArrowRight") next = (_sidebarWidthPx || b.defaultWidth) - step;
    else if (e.key === "Home") next = b.min;
    else if (e.key === "End") next = b.max;
    if (next != null) {
      _setSidebarWidth(next, true);
      e.preventDefault();
    }
  });
}

/* ---------- Sidebar open/close ---------- */
function updateSidebarToggle() {
  const btn = document.getElementById("btnToggleSidebar");
  if (!btn) return;
  const open = document.body.classList.contains("sidebar-open");
  btn.textContent = open ? "Hide" : "Show";
  btn.setAttribute("aria-expanded", open ? "true" : "false");
}
function _syncSidebarInert() {
  const sb = document.getElementById("sidebar");
  if (sb) sb.inert = !document.body.classList.contains("sidebar-open");
}
function _syncFloatingAfterLayoutShift() {
  // Opening/closing the panel reflows .app (its padding changes), so any floating
  // add-comment button or highlight bubble is now at a stale position. Re-pin them.
  repositionActiveAdd();
  if (!hlBubble.hidden) {
    if (hlBubbleMark && root.contains(hlBubbleMark)) positionHlBubble(hlBubbleMark);
    else { hlBubble.hidden = true; hlBubbleCid = null; hlBubbleMark = null; }
  }
}
function openSidebar()  { document.body.classList.add("sidebar-open"); updateSidebarToggle(); _syncSidebarInert(); _syncFloatingAfterLayoutShift(); }
function closeSidebar() { document.body.classList.remove("sidebar-open"); updateSidebarToggle(); _syncSidebarInert(); _syncFloatingAfterLayoutShift(); }
document.getElementById("btnToggleSidebar").addEventListener("click", () => { document.body.classList.toggle("sidebar-open"); updateSidebarToggle(); _syncSidebarInert(); _syncFloatingAfterLayoutShift(); });
document.getElementById("btnCloseSidebar").addEventListener("click", closeSidebar);
(function () {
  // "Show" entry in the overflow menu reopens the panel (the menu's own click handler
  // closes the menu). Redundant with the toolbar toggle but discoverable from the menu.
  const b = document.getElementById("btnShowTop");
  if (b) b.addEventListener("click", openSidebar);
})();

/* ---------- Toolbar overflow menu (declutters the save/export actions) ---------- */
(function () {
  const btn = document.getElementById("btnToolbarMenu");
  const menu = document.getElementById("toolbarMenu");
  if (!btn || !menu) return;
  function setOpen(open) {
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  }
  btn.addEventListener("click", (e) => { e.stopPropagation(); setOpen(menu.hidden); });
  menu.addEventListener("click", () => setOpen(false));
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target) && !btn.contains(e.target)) setOpen(false);
  });
  // Escape is handled centrally (toolbar menu has priority) in the global keydown
  // listener above, so it is not duplicated here.
})();

/* ---------- Copy all + Clear all ---------- */
function buildCopyText() {
  const liveComments = withoutHandled(comments);
  const stateChanges = (typeof widgetStateChanges === "function") ? widgetStateChanges() : [];
  const clChanges = (typeof checklistChanges === "function") ? checklistChanges() : [];
  if (!liveComments.length && !stateChanges.length && !clChanges.length) return "";
  const sortKey = (c) => (c.anchorType === "document")
    ? -1
    : (c.anchorType === "mermaid")
    ? (1e12 + (c.diagramIndex || 0) * 1000)
    : (c.anchorType === "diff")
    ? (2e12 + (c.diffIndex || 0) * 1e6 + (parseInt(c.lineKey, 10) || 0))
    : (c.anchorType === "image")
    ? (3e12 + (c.imageIndex || 0))
    : (c.anchorType === "widget")
    ? (4e12 + _widgetOrderKey(c))
    : (typeof c.start === "number" ? c.start : 0);
  const sorted = [...liveComments].sort((a, b) => sortKey(a) - sortKey(b));
  const lines = [];
  // Structured one-line metadata fields must not carry newlines/tabs, or a poisoned
  // persisted comment could inject an extra line (e.g. a fake HANDLED_IDS_JSON:) into
  // the copied bundle. The free-text note and the fenced quote are emitted in their
  // own sections; the handled-id contract is anchored to the LAST HANDLED_IDS line.
  const oneLine = (s) => String(s == null ? "" : s).replace(/[\r\n\t]+/g, " ").trim();
  lines.push(`# ${oneLine(DOC_LABEL)} review (${sorted.length} comment${sorted.length === 1 ? "" : "s"})`);
  lines.push(`Source: ${oneLine(DOC_SOURCE)}`);
  lines.push("");
  sorted.forEach((c, i) => {
    const isMermaid = c.anchorType === "mermaid";
    const isDiff = c.anchorType === "diff";
    const isImage = c.anchorType === "image";
    const isWidget = c.anchorType === "widget";
    const isDocument = c.anchorType === "document";
    lines.push(`## Comment ${i + 1}${isMermaid ? " (mermaid)" : isDiff ? " (diff)" : isImage ? " (image)" : isWidget ? " (widget)" : isDocument ? " (document)" : ""}`);
    lines.push(`Id: ${c.id}`);
    lines.push(`When: ${formatTime(c.createdAt)}${c.updatedAt ? " (edited " + formatTime(c.updatedAt) + ")" : ""}`);
    if (c.headingPath && c.headingPath.length) {
      const path = c.headingPath.map(h => `H${Number(h.level) || 0} "${oneLine(h.text)}"`).join(" > ");
      lines.push(`Where: ${path}`);
    } else if (c.section) {
      lines.push(`Section: ${oneLine(c.section)}`);
    }
    if (isMermaid) {
      if (c.nodeKey === "__diagram__") {
        lines.push(`Anchor: mermaid diagram #${(c.diagramIndex || 0) + 1} (whole diagram)`);
      } else {
        lines.push(`Anchor: mermaid diagram #${(c.diagramIndex || 0) + 1}, node "${oneLine(c.nodeKey)}"`);
      }
      if (c.nodeLabel && c.nodeLabel !== c.nodeKey) {
        lines.push(`Node label: ${oneLine(c.nodeLabel)}`);
      }
      lines.push("");
      lines.push("Comment:");
      lines.push(c.note);
    } else if (isDiff) {
      const loc = c.lineType === "add" ? "added line " + (c.newNo != null ? c.newNo : "?")
        : c.lineType === "del" ? "removed line " + (c.oldNo != null ? c.oldNo : "?")
        : "context line " + (c.newNo != null ? c.newNo : (c.oldNo != null ? c.oldNo : "?"));
      lines.push(`Anchor: diff${c.diffLabel ? " " + oneLine(c.diffLabel) : ""}, ${loc}`);
      lines.push("");
      lines.push("Diff line:");
      // Fence longer than any backtick run in the line so a diff line that itself
      // contains ``` cannot break out of the fenced block into the copied bundle.
      let dMaxRun = 0;
      const dRunRe = /`+/g;
      let dm;
      while ((dm = dRunRe.exec(c.quote)) !== null) {
        if (dm[0].length > dMaxRun) dMaxRun = dm[0].length;
      }
      const dFence = "`".repeat(Math.max(3, dMaxRun + 1));
      lines.push(dFence + "diff");
      c.quote.split(/\r?\n/).forEach(l => lines.push(l));
      lines.push(dFence);
      lines.push("");
      lines.push("Comment:");
      lines.push(c.note);
    } else if (isImage) {
      const rawSrc = oneLine(c.imageSrc);
      const sSrc = rawSrc.length > 100 ? rawSrc.slice(0, 100) + "..." : rawSrc;
      const mediaWord = c.imageKind === "chart" ? "chart" : "image";
      lines.push(`Anchor: ${mediaWord} #${(c.imageIndex || 0) + 1}${sSrc ? " (" + sSrc + ")" : ""}`);
      if (c.imageAlt) lines.push(`Alt: ${oneLine(c.imageAlt)}`);
      lines.push("");
      lines.push("Comment:");
      lines.push(c.note);
    } else if (isWidget) {
      lines.push(`Anchor: widget "${oneLine(c.widget)}", part "${oneLine(c.partLabel || c.part)}"${c.slot ? " (in " + oneLine(c.slot) + ")" : ""}`);
      lines.push("");
      lines.push("Comment:");
      lines.push(c.note);
    } else if (isDocument) {
      lines.push("Anchor: document-wide (not tied to a specific element)");
      lines.push("");
      lines.push("Comment:");
      lines.push(c.note);
    } else {
      const pin = [];
      if (c.isCode) {
        pin.push(c.codeLanguage ? `code (${oneLine(c.codeLanguage)})` : "code block");
      } else if (c.blockTag) {
        pin.push(`<${oneLine(c.blockTag)}>`);
      }
      if (Number(c.occurrenceTotal) > 1) pin.push(`match ${Number(c.occurrence) || 0} of ${Number(c.occurrenceTotal) || 0} in section`);
      else if (Number(c.occurrenceTotal) === 1) pin.push("unique match in section");
      if (pin.length) lines.push(`Pinpoint: ${pin.join(" - ")}`);
      lines.push(`Offsets: [${Number(c.start) || 0}, ${Number(c.end) || 0}]`);
      lines.push("");
      lines.push("Quoted text:");
      if (c.isCode) {
        // Emit a fenced code block so newlines and indentation survive paste-back into
        // markdown-aware editors (ADO PR comments, GitHub issues, etc.). Choose a fence
        // longer than any backtick run in the quote so a literal ``` line inside the
        // selection cannot prematurely close the block.
        let maxRun = 0;
        const runRe = /`+/g;
        let mm;
        while ((mm = runRe.exec(c.quote)) !== null) {
          if (mm[0].length > maxRun) maxRun = mm[0].length;
        }
        const fenceLen = Math.max(3, maxRun + 1);
        const fenceBar = "`".repeat(fenceLen);
        lines.push(fenceBar + oneLine(c.codeLanguage));
        c.quote.split(/\r?\n/).forEach(line => lines.push(line));
        lines.push(fenceBar);
      } else {
        c.quote.split(/\r?\n/).forEach(line => lines.push("> " + line));
      }
      // "In context" only makes sense for prose. Skip it for code blocks - the fenced
      // quote already preserves the structure that matters.
      if (!c.isCode && (c.before || c.after)) {
        lines.push("");
        lines.push("In context:");
        const ctxLine = (c.before || "") + '"' + c.quote.replace(/\s+/g, " ") + '"' + (c.after || "");
        ctxLine.split(/\r?\n/).forEach(line => lines.push("> " + line));
      }
      if (c.blockText && !c.isCode) {
        lines.push("");
        lines.push(`Containing <${oneLine(c.blockTag) || "block"}>:`);
        c.blockText.split(/\r?\n/).forEach(line => lines.push("> " + line));
      }
      lines.push("");
      lines.push("Comment:");
      lines.push(c.note);
    }
    lines.push("");
    lines.push("---");
    lines.push("");
  });
  if (stateChanges.length) {
    lines.push("## Widget layout changes");
    lines.push("Drag/drop moves not yet saved into the file. Reformat the source to match this layout, then re-export.");
    lines.push("");
    stateChanges.forEach((ch) => lines.push(`- widget "${oneLine(ch.widget)}": "${oneLine(ch.label || ch.part)}" moved from ${oneLine(ch.from)} to ${oneLine(ch.to)}`));
  }
  if (clChanges.length) {
    const byCl = new Map();
    clChanges.forEach((ch) => {
      if (!byCl.has(ch.checklist)) byCl.set(ch.checklist, { label: ch.checklistLabel, items: [] });
      byCl.get(ch.checklist).items.push(ch);
    });
    const stateMap = {};
    byCl.forEach((info, cid) => {
      const label = (info.label && info.label !== cid) ? ` (${oneLine(info.label)})` : "";
      lines.push(`## Checklist "${oneLine(cid)}"${label}`);
      lines.push("Apply with tools/checklist_apply.py, or set data-cmh-state on each item.");
      lines.push("");
      info.items.forEach((ch) => {
        lines.push(`- [${oneLine(ch.key)}] "${oneLine(ch.label || ch.key)}": ${oneLine(ch.from)} -> ${oneLine(ch.to)}`);
        if (!stateMap[cid]) stateMap[cid] = {};
        stateMap[cid][ch.key] = ch.to;
      });
      lines.push("");
    });
    lines.push("CHECKLIST_STATE_JSON: " + JSON.stringify(stateMap));
  }
  lines.push("");
  lines.push("---");
  lines.push("");
  lines.push("AGENT INSTRUCTIONS:");
  lines.push("After acting on the comments above, append every processed id");
  lines.push("to the JSON array inside the `<script id=\"handledCommentIds\">`");
  lines.push(`block of \`${DOC_SOURCE}\`. Existing entries must be preserved.`);
  lines.push("On the next page load those comments are pruned from");
  lines.push("localStorage and their highlights are dropped.");
  lines.push("");
  lines.push("HANDLED_IDS_JSON: " + JSON.stringify(sorted.map(c => c.id)));
  return lines.join("\n").trim() + "\n";
}
async function copyAll() {
  const live = withoutHandled(comments);
  const changes = (typeof widgetStateChanges === "function") ? widgetStateChanges() : [];
  const clCh = (typeof checklistChanges === "function") ? checklistChanges() : [];
  if (!live.length && !changes.length && !clCh.length) { showToast("No comments to copy."); return; }
  const n = live.length;
  const text = buildCopyText();
  let copied = false;
  try { await navigator.clipboard.writeText(text); copied = true; }
  catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.left = "-9999px";
    document.body.appendChild(ta); ta.select();
    try { copied = document.execCommand("copy"); } catch (err) { copied = false; }
    document.body.removeChild(ta);
    if (!copied) {
      window.prompt("Automatic copy was blocked. Copy the text below manually, then dismiss:", text);
      // Do NOT claim success: the reviewer may have cancelled the prompt without copying.
      showToast("Automatic copy was blocked - the bundle was shown for manual copy.",
        { alert: true, duration: 6000 });
      return;
    }
  }
  if (copied) {
    const extra = changes.length ? ` plus ${changes.length} layout change${changes.length === 1 ? "" : "s"}` : "";
    showToast(`Copied ${n} comment${n === 1 ? "" : "s"}${extra}. They stay here until the agent marks them handled in the HTML.`);
  }
}
document.getElementById("btnCopyAll").addEventListener("click", copyAll);
document.getElementById("btnCopyAllTop").addEventListener("click", copyAll);

/* ---------- Export to Markdown (deterministic content -> Markdown) ----------
   Walks #commentRoot structure (never rendered layout) and maps each block kind to one
   fixed Markdown construct, so the output is byte-stable and idempotent. cm-skip subtrees
   are excluded EXCEPT a mermaid <pre> (its source is content) and a diff host (its raw
   source is recovered). Sortable tables emit in original row order. */
const _MD_SKIP_TAGS = { SCRIPT: 1, STYLE: 1, NAV: 1, NOSCRIPT: 1, TEMPLATE: 1 };
const _MD_ALERT = { info: "NOTE", success: "TIP", warning: "WARNING", danger: "CAUTION" };
function _mdCollapse(s) { return String(s == null ? "" : s).replace(/\s+/g, " ").trim(); }
function _mdSkip(el) {
  if (!el || el.nodeType !== 1) return false;
  if (_MD_SKIP_TAGS[el.tagName]) return true;
  // A mermaid host (pre.mermaid or div.mermaid) and a diff host carry content we export
  // from a stashed source, so they are never skipped even though they are cm-skip.
  if (el.classList && el.classList.contains("mermaid")) return false;
  if (el.classList && el.classList.contains("cmh-diff-host")) return false;
  if (el.hasAttribute && el.hasAttribute("data-cm-widget")) return false;
  return !!(el.classList && (el.classList.contains("cm-skip") || el.classList.contains("cm-toc")));
}
function _mdDedent(text) {
  const arr = String(text).replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  while (arr.length && arr[0].trim() === "") arr.shift();
  while (arr.length && arr[arr.length - 1].trim() === "") arr.pop();
  let indent = null;
  arr.forEach((ln) => { if (!ln.trim()) return; const m = ln.match(/^[ \t]*/)[0].length; indent = indent === null ? m : Math.min(indent, m); });
  indent = indent || 0;
  return arr.map((ln) => ln.slice(indent)).join("\n");
}
function _mdFence(lang, text) {
  const body = _mdDedent(text);
  let maxRun = 0; const re = /`+/g; let m;
  while ((m = re.exec(body)) !== null) { if (m[0].length > maxRun) maxRun = m[0].length; }
  const bar = "`".repeat(Math.max(3, maxRun + 1));
  // Sanitize the info string: a backtick or space in a derived language class would void a
  // backtick fence (CommonMark forbids backticks in the info string), so keep it to a safe set.
  const info = String(lang == null ? "" : lang).replace(/[^A-Za-z0-9_.+-]/g, "");
  return bar + info + "\n" + body + "\n" + bar;
}
// Inline code span with a backtick run longer than any run inside the content (CommonMark
// requires the fence to exceed the longest inner run), padded with a space when the content
// starts or ends with a backtick. Newlines are collapsed so a code span stays one line.
function _mdInlineCode(text) {
  const s = String(text == null ? "" : text).replace(/\r?\n/g, " ");
  let maxRun = 0; const re = /`+/g; let m;
  while ((m = re.exec(s)) !== null) { if (m[0].length > maxRun) maxRun = m[0].length; }
  const ticks = "`".repeat(maxRun + 1);
  // Pad with a space when the content starts/ends with a backtick or space, so CommonMark's
  // one-space strip leaves the original content intact.
  const pad = (s === "" || /^[`\s]/.test(s) || /[`\s]$/.test(s)) ? " " : "";
  return ticks + pad + s + pad + ticks;
}
// Escape a raw attribute-derived label (image alt, appendix widget/part/node names) with the
// same set as text nodes, so a value like `<img onerror=...>` cannot become live HTML when the
// exported Markdown is rendered by an HTML-permissive renderer, and brackets/backslash cannot
// break the [..] syntax. (Anchor label text rides _mdText via _mdInlineText and is not passed here.)
function _mdLinkLabel(text) { return _mdText(text); }
// A link/image destination: strip control chars, and wrap in angle brackets (encoding any
// literal '<'/'>') when it contains characters that would otherwise break the (..) destination.
function _mdUrl(url) {
  const u = String(url == null ? "" : url).replace(/[\x00-\x1f\x7f]+/g, "").trim();
  // Neutralize executable schemes that have no legitimate use in an exported document; leave
  // http/https/mailto/tel and relative/anchor destinations untouched.
  if (/^(?:javascript|vbscript):/i.test(u)) return "about:blank";
  // Allow only image data URLs; a bare data: URL (data:text/html, data:application/..., etc.)
  // is an inline-payload vector with no place in exported prose, so drop it.
  if (/^data:/i.test(u) && !/^data:image\//i.test(u)) return "about:blank";
  if (/[()\s<>]/.test(u)) return "<" + u.replace(/</g, "%3C").replace(/>/g, "%3E") + ">";
  return u;
}
// Escape a plain text node so its characters cannot open a code span, link, or raw-HTML tag
// in the exported Markdown (block-leading triggers are handled by _mdEscapeLeading).
function _mdText(s) { return String(s == null ? "" : s).replace(/[\\`<\[\]*_~]/g, "\\$&"); }
// Escape GFM table-cell pipes without disturbing pipes that are already escaped (an odd run of
// preceding backslashes), so a code span like `a\|b` inside a table cell keeps its pipe escaped
// rather than forging a column boundary, and a backslash before a pipe cannot cancel the escape.
function _mdEscapePipes(s) { return String(s == null ? "" : s).replace(/(\\*)\|/g, function (m, bs) { return bs.length % 2 ? m : bs + "\\|"; }); }
// Escape a leading block trigger (heading, blockquote, list, ordered list, thematic break)
// so ordinary prose cannot forge document structure in the exported Markdown.
function _mdEscapeLeading(s) {
  // Setext heading underline: a line of only '=' or only '-' turns the preceding line into a
  // heading. This is reachable where raw newlines are preserved (comment notes); a bare '-' or
  // one/two dashes also slips past the 3+-run thematic-break check below.
  if (/^\s{0,3}=+\s*$/.test(s)) return s.replace(/=/, "\\=");
  if (/^\s{0,3}-+\s*$/.test(s)) return s.replace(/-/, "\\-");
  if (/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(s)) return s.replace(/(\\|[-*_])/g, "\\$1");
  return s.replace(/^(\s*)(#{1,6}(?=\s|$)|>|[-+*](?=\s)|\d+[.)](?=\s))/, function (mm, ws, tok) {
    if (/^\d/.test(tok)) return ws + tok.replace(/([.)])$/, "\\$1");
    return ws + "\\" + tok;
  });
}
function _mdInlineOne(ch) {
  if (ch.nodeType === 3) return _mdText(ch.nodeValue);
  if (ch.nodeType !== 1 || _mdSkip(ch)) return "";
  const t = ch.tagName;
  if (t === "STRONG" || t === "B") return "**" + _mdCollapse(_mdInlineText(ch)) + "**";
  if (t === "EM" || t === "I") return "*" + _mdCollapse(_mdInlineText(ch)) + "*";
  if (t === "CODE") return _mdInlineCode(ch.textContent || "");
  if (t === "A") return "[" + _mdCollapse(_mdInlineText(ch)) + "](" + _mdUrl(ch.getAttribute("href") || "") + ")";
  if (t === "IMG") return "![" + _mdLinkLabel(ch.getAttribute("alt") || "") + "](" + _mdUrl(ch.getAttribute("src") || "") + ")";
  if (t === "BR") return " ";
  if (t === "SPAN" && ch.classList.contains("badge")) return _mdInlineCode(ch.textContent || "");
  return _mdInlineText(ch);
}
// Append one child's inline serialization to acc, escaping a trailing "!" so an <a> that
// follows a literal "!" cannot forge image syntax.
function _mdAppendInline(acc, ch) {
  const piece = _mdInlineOne(ch);
  if (!piece) return acc;
  if (piece[0] === "[" && acc.slice(-1) === "!") acc = acc.slice(0, -1) + "\\!";
  return acc + piece;
}
function _mdInlineText(node) {
  let out = "";
  const kids = node.childNodes;
  for (let i = 0; i < kids.length; i++) {
    out = _mdAppendInline(out, kids[i]);
  }
  return out;
}
function _mdTableRows(el) {
  const cells = (tr, sel) => Array.prototype.map.call(tr.querySelectorAll(sel), (c) => _mdEscapePipes(_mdCollapse(_mdInlineText(c))));
  const head = el.querySelector("thead tr") || el.querySelector("tr");
  if (!head) return "";
  const headers = cells(head, "th,td");
  let bodyRows = Array.prototype.slice.call(el.querySelectorAll("tbody tr"));
  if (!bodyRows.length) bodyRows = Array.prototype.filter.call(el.querySelectorAll("tr"), (tr) => tr !== head);
  if (bodyRows.some((r) => r.dataset && r.dataset.cmhRow != null)) {
    bodyRows = bodyRows.slice().sort((a, b) => (parseInt(a.dataset.cmhRow, 10) || 0) - (parseInt(b.dataset.cmhRow, 10) || 0));
  }
  const rows = bodyRows.map((tr) => cells(tr, "td,th"));
  const out = [];
  out.push("| " + headers.join(" | ") + " |");
  out.push("| " + headers.map(() => "---").join(" | ") + " |");
  rows.forEach((r) => out.push("| " + r.join(" | ") + " |"));
  return out.join("\n");
}
function _mdFigure(el) {
  const cap = el.querySelector("figcaption");
  const caption = cap ? _mdCollapse(_mdInlineText(cap)) : "";
  if (el.classList.contains("cmh-kql")) {
    const code = el.querySelector("pre code, code");
    const run = el.querySelector("a.cmh-kql-run, a[href]");
    const parts = [];
    if (code) parts.push(_mdFence("kusto", code.textContent || ""));
    if (run && run.getAttribute("href")) parts.push("[Run in Azure Data Explorer](" + _mdUrl(run.getAttribute("href")) + ")");
    if (caption) parts.push("_" + caption + "_");
    return parts.join("\n\n");
  }
  const offlineChart = el.querySelector("img[data-cm-offline-chart]");
  if (offlineChart) {
    // Offline chart snapshots can carry large data: URLs; Markdown keeps only the human label.
    const label = caption || _mdCollapse(_mdText(offlineChart.getAttribute("alt") || "Chart snapshot"));
    return "_[Chart snapshot: " + label + "]_";
  }
  if (el.classList.contains("chart") || el.querySelector("canvas")) return "_[Chart: " + caption + "]_";
  const img = el.querySelector("img");
  if (img) {
    // The alt attribute is raw; when it is empty, fall back to the caption's raw text (not the
    // already-escaped `caption`) so _mdLinkLabel applies exactly one escape pass.
    const alt = img.getAttribute("alt") || (cap ? _mdCollapse(cap.textContent || "") : "");
    return "![" + _mdLinkLabel(alt) + "](" + _mdUrl(img.getAttribute("src") || "") + ")";
  }
  if (el.querySelector("svg")) return "_[Figure: " + caption + "]_";
  return caption ? "_[Figure: " + caption + "]_" : _mdChildren(el);
}
function _mdList(el, indent) {
  const ordered = el.tagName === "OL";
  const out = [];
  let n = 0;
  const BLOCK = /^(P|PRE|BLOCKQUOTE|TABLE|FIGURE|H[1-6]|DIV|SECTION)$/;
  Array.prototype.forEach.call(el.children, (li) => {
    if (li.tagName !== "LI") return;
    n++;
    const marker = ordered ? n + ". " : "- ";
    const cont = indent + " ".repeat(marker.length);   // continuation indent = marker width
    const segs = [];   // ordered runs: {t:"inline"|"block", v} in DOM order
    let inline = "";
    const flush = () => { const c = _mdCollapse(inline); inline = ""; if (c) segs.push({ t: "inline", v: c }); };
    Array.prototype.forEach.call(li.childNodes, (ch) => {
      if (ch.nodeType === 1 && (ch.tagName === "UL" || ch.tagName === "OL")) { flush(); segs.push({ t: "block", v: _mdList(ch, cont) }); }
      else if (ch.nodeType === 1 && BLOCK.test(ch.tagName) && !_mdSkip(ch)) {
        flush();
        const md = _mdBlock(ch);
        if (md && md.trim()) segs.push({ t: "block", v: md.split("\n").map((l) => cont + l).join("\n") });
      } else if (ch.nodeType === 3) inline = _mdAppendInline(inline, ch);
      else if (ch.nodeType === 1 && !_mdSkip(ch)) inline = _mdAppendInline(inline, ch);
    });
    flush();
    const lines = [];
    if (!segs.length) { lines.push(indent + marker.replace(/\s+$/, "")); }
    segs.forEach((s, i) => {
      if (i === 0) {
        if (s.t === "inline") lines.push(indent + marker + _mdEscapeLeading(s.v));
        else { lines.push(indent + marker.replace(/\s+$/, "")); lines.push(s.v); }
      } else {
        lines.push(s.t === "inline" ? cont + _mdEscapeLeading(s.v) : s.v);
      }
    });
    out.push(lines.join("\n"));
  });
  return out.join("\n");
}
function _mdCallout(el) {
  let variant = "";
  el.classList.forEach((c) => { const m = c.match(/^cmh-callout-(info|success|warning|danger)$/); if (m) variant = m[1]; });
  const out = [];
  if (variant) out.push("> [!" + _MD_ALERT[variant] + "]");
  out.push("> " + _mdEscapeLeading(_mdCollapse(_mdInlineText(el))));
  return out.join("\n");
}
function _mdDiff(el) {
  const src = el.querySelector("script.cmh-diff-src");
  let raw = "";
  if (src) {
    try { raw = src.getAttribute("data-enc") === "base64" ? _b64DecodeUtf8(src.textContent) : (src.textContent || ""); }
    catch (e) { raw = ""; }
  }
  if (!raw) {
    // Never silently drop content: fall back to the rendered diff text, but strip the
    // encoded source <script> first so its base64 payload is not exported.
    const clone = el.cloneNode(true);
    Array.prototype.forEach.call(clone.querySelectorAll("script"), (s) => s.remove());
    raw = (clone.textContent || "").replace(/\u00a0/g, " ").replace(/[ \t]+$/gm, "").trim();
    if (raw) { try { console.warn("commentable-html: diff source unavailable; exported rendered text"); } catch (e) { /* no-op */ } }
  }
  return _mdFence("diff", raw || "");
}
function _mdPartLabel(el) {
  return _mdEscapePipes(_mdCollapse(_mdText(el.getAttribute("data-cm-part-label") || el.textContent || "")));
}
function _mdWidget(el) {
  const title = _mdCollapse(_mdText(el.getAttribute("aria-label") || el.getAttribute("data-cm-widget") || "Widget"));
  const slots = Array.prototype.filter.call(el.querySelectorAll("[data-cm-slot]"), (slot) =>
    slot.closest("[data-cm-widget]") === el);
  if (slots.length) {
    const headers = slots.map((slot) =>
      _mdEscapePipes(_mdCollapse(_mdText(slot.getAttribute("data-cm-slot") || slot.getAttribute("aria-label") || "Slot"))));
    const columns = slots.map((slot) =>
      Array.prototype.filter.call(slot.querySelectorAll("[data-cm-part]"), (part) =>
        part !== slot && part.closest("[data-cm-widget]") === el && part.closest("[data-cm-slot]") === slot)
        .map(_mdPartLabel));
    const rows = [];
    const height = Math.max.apply(null, columns.map((col) => col.length).concat([0]));
    rows.push("| " + headers.join(" | ") + " |");
    rows.push("| " + headers.map(() => "---").join(" | ") + " |");
    for (let r = 0; r < height; r++) {
      rows.push("| " + columns.map((col) => col[r] || "").join(" | ") + " |");
    }
    return "_[Widget: " + title + "]_\n\n" + rows.join("\n");
  }
  const parts = Array.prototype.filter.call(el.querySelectorAll("[data-cm-part]"), (part) =>
    part.closest("[data-cm-widget]") === el).map((part) => "- " + _mdPartLabel(part));
  return parts.length ? "_[Widget: " + title + "]_\n\n" + parts.join("\n") : "";
}
function _mdBlock(el) {
  const t = el.tagName;
  if (el.classList && el.classList.contains("mermaid")) return _mdFence("mermaid", el.getAttribute("data-cmh-md-src") || el.textContent || "");
  if (el.hasAttribute && el.hasAttribute("data-cm-widget")) return _mdWidget(el);
  if (/^H[1-6]$/.test(t)) return "#".repeat(+t[1]) + " " + _mdCollapse(_mdInlineText(el));
  if (t === "P") return _mdEscapeLeading(_mdCollapse(_mdInlineText(el)));
  if (t === "UL" || t === "OL") return _mdList(el, "");
  if (t === "TABLE") return _mdTableRows(el);
  if (t === "FIGURE") return _mdFigure(el);
  if (t === "IMG") return "![" + _mdLinkLabel(el.getAttribute("alt") || "") + "](" + _mdUrl(el.getAttribute("src") || "") + ")";
  if (el.classList && el.classList.contains("cmh-diff-host")) return _mdDiff(el);
  if (t === "PRE") {
    const code = el.querySelector("code");
    let lang = "";
    (((code || el).className) || "").split(/\s+/).forEach((c) => { const m = c.match(/^language-(.+)$/); if (m) lang = m[1]; });
    return _mdFence(lang, (code || el).textContent || "");
  }
  if (t === "BLOCKQUOTE") return "> " + _mdEscapeLeading(_mdCollapse(_mdInlineText(el)));
  if (el.classList && el.classList.contains("cmh-callout")) return _mdCallout(el);
  return _mdChildren(el);
}
function _mdChildren(el) {
  const out = [];
  Array.prototype.forEach.call(el.childNodes, (ch) => {
    if (ch.nodeType === 3) {
      // Direct text under a container (div/section/#commentRoot) is escaped like any prose,
      // so a bare "# x" or link/HTML syntax cannot forge structure in the export.
      const t = _mdEscapeLeading(_mdCollapse(_mdText(ch.nodeValue)));
      if (t) out.push(t);
      return;
    }
    if (ch.nodeType !== 1 || _mdSkip(ch)) return;
    const md = _mdBlock(ch);
    if (md && md.trim()) out.push(md);
  });
  return out.join("\n\n");
}
function htmlToMarkdown(rootEl) {
  if (!rootEl) return "";
  return _mdChildren(rootEl).replace(/\n{3,}/g, "\n\n").trim() + "\n";
}
function _mdCommentsAppendix() {
  const live = withoutHandled(comments);
  if (!live.length) return "";
  const oneLine = (s) => String(s == null ? "" : s).replace(/\s+/g, " ").trim();
  const esc = (s) => _mdLinkLabel(oneLine(s));   // bracket/backslash-escape so a crafted label cannot inject a link into the heading
  const out = ["## Review comments (" + live.length + ")"];
  live.forEach((c, i) => {
    let where = "";
    if (c.anchorType === "document") where = "document-wide";
    else if (c.anchorType === "widget") where = 'widget "' + esc(c.widget) + '" / ' + esc(c.partLabel || c.part);
    else if (c.anchorType === "mermaid") where = "mermaid " + esc(c.nodeLabel || c.nodeKey);
    else if (c.anchorType === "diff") where = "diff line";
    else if (c.anchorType === "image") where = (c.imageKind === "chart" ? "chart" : "image") + " " + ((c.imageIndex || 0) + 1);
    else if (c.quote) where = '"' + esc(oneLine(c.quote).slice(0, 80)) + '"';
    out.push("");
    out.push("### " + (i + 1) + ". " + (oneLine(where) || "comment"));
    out.push("");
    // Escape each preserved note line like prose (raw HTML, inline markup, leading structural
    // markers including setext underlines) and neutralize pipes so a multi-line note cannot
    // forge a GFM table either.
    String(c.note == null ? "" : c.note).split(/\r?\n/).forEach((ln) => {
      const e = _mdEscapePipes(_mdEscapeLeading(_mdText(ln)));
      out.push(e.trim() ? "> " + e : ">");
    });
  });
  return out.join("\n") + "\n";
}
function buildMarkdownDoc() {
  let md = htmlToMarkdown(root);
  const appendix = _mdCommentsAppendix();
  if (appendix) md += "\n" + appendix;
  return md;
}
function _downloadTextFile(text, filename, mime) {
  const blob = new Blob([text], { type: (mime || "text/plain") + ";charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => { try { URL.revokeObjectURL(url); } catch (e) {} }, 1000);
}
function _mdFilename() {
  let stem = "document";
  try {
    const p = (DOC_SOURCE || location.pathname || "document").split(/[\\/]/).pop() || "document";
    stem = p.replace(/\.[^.]+$/, "") || "document";
  } catch (e) { /* keep default */ }
  return stem + ".md";
}
async function exportMarkdown() {
  const md = buildMarkdownDoc();
  const filename = _mdFilename();
  _downloadTextFile(md, filename, "text/markdown");
  showToast(`Markdown downloaded as ${filename}.`);
}
["btnExportMd", "btnExportMdTop"].forEach((id) => {
  const b = document.getElementById(id);
  if (b) b.addEventListener("click", exportMarkdown);
});
// Exposed for deterministic tests and programmatic use.
window.__cmhToMarkdown = function () { return buildMarkdownDoc(); };

// Copy arbitrary text to the clipboard (navigator.clipboard with an execCommand
// fallback), then show a toast. Returns a promise. Used by the per-code-block Copy
// button and the Kusto cluster-name copy affordance.
async function copyPlain(text, toastMsg) {
  let copied = false;
  try { await navigator.clipboard.writeText(text); copied = true; }
  catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.left = "-9999px";
    document.body.appendChild(ta); ta.select();
    try { copied = document.execCommand("copy"); } catch (err) { copied = false; }
    document.body.removeChild(ta);
  }
  showToast(copied ? (toastMsg || "Copied to clipboard.") : "Copy failed.");
  return copied;
}

// A persistent per-code-block Copy button. Each commentable code block is wrapped in a
// position:relative .cmh-code-wrap and gets an always-visible cm-skip Copy button in the
// top-right (so it never moves on hover and is excluded from the text-offset system).
function isCommentableCodeBlock(pre) {
  return pre && pre.tagName === "PRE" && root.contains(pre)
    && !pre.classList.contains("mermaid") && !pre.classList.contains("cmh-diff")
    && !pre.closest(".cm-skip")
    && !pre.closest(".cmh-diff") && !pre.closest(".cmh-diff-host");
}
var _CODE_LANG_LABELS = {
  python: "Python", py: "Python", javascript: "JavaScript", js: "JavaScript",
  typescript: "TypeScript", ts: "TypeScript", csharp: "C#", cs: "C#", json: "JSON",
  bash: "Bash", sh: "Bash", shell: "Bash", sql: "SQL", go: "Go", golang: "Go",
  yaml: "YAML", yml: "YAML", kql: "KQL", kusto: "KQL", html: "HTML", xml: "XML",
  css: "CSS", java: "Java", cpp: "C++", c: "C", rust: "Rust", rs: "Rust",
  ruby: "Ruby", rb: "Ruby", php: "PHP", diff: "Diff", text: "Text", plaintext: "Text",
};
function _codeLangLabel(lang) {
  if (!lang) return "";
  var k = String(lang).toLowerCase();
  if (_CODE_LANG_LABELS[k]) return _CODE_LANG_LABELS[k];
  return k.charAt(0).toUpperCase() + k.slice(1);
}
function setupCodeCopy() {
  root.querySelectorAll("pre").forEach(function (pre) {
    if (!isCommentableCodeBlock(pre)) return;
    if (pre.parentElement && pre.parentElement.classList.contains("cmh-code-wrap")) return;
    const wrap = document.createElement("div");
    wrap.className = "cmh-code-wrap";
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    const tools = document.createElement("div");
    tools.className = "cm-code-tools cm-skip";
    // A small language pill (Python, C#, KQL, ...) sits next to the Copy button.
    const codeEl = pre.querySelector("code");
    const lm = /(?:^|\s)language-([\w#+.-]+)/i.exec(codeEl ? (codeEl.className || "") : "");
    const label = lm ? _codeLangLabel(lm[1]) : "";
    if (label) {
      const pill = document.createElement("span");
      pill.className = "cm-code-lang";
      pill.textContent = label;
      pill.title = label + " code block";
      tools.appendChild(pill);
    }
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "cm-code-copy cm-skip";
    btn.textContent = "Copy";
    btn.title = "Copy this code block to the clipboard";
    btn.addEventListener("click", function () {
      const code = pre.querySelector("code") || pre;
      copyPlain(code.textContent.replace(/\n$/, ""), "Code copied to clipboard.");
    });
    tools.appendChild(btn);
    wrap.appendChild(tools);
  });
}

// Generic click-to-copy affordance: any element carrying data-cmh-copy copies that
// value to the clipboard and shows a toast. Used by the Kusto cluster-name title.
root.addEventListener("click", function (e) {
  const el = e.target.closest("[data-cmh-copy]");
  if (!el || !root.contains(el)) return;
  e.preventDefault();
  copyPlain(el.getAttribute("data-cmh-copy") || el.textContent, "Cluster copied to clipboard.");
});

/* ---------- Sortable tables ----------
   Every column of an authored table (one with a real <thead>) gets up/down chevrons.
   Sorting reorders the <tbody> rows for display; numeric columns sort numerically.
   Reordering rows shifts the text-offset coordinate system, so after each sort we
   recompute every text comment's offsets from its live <mark>s and persist both the
   comments and the applied sort. The sort is re-applied on load BEFORE restore so the
   stored offsets always match the displayed order. */
const CMH_TABLE_SORT_KEY = COMMENT_KEY + "::tableSort";
let _tableSortState = {};
function _loadTableSortState() {
  try { _tableSortState = JSON.parse(localStorage.getItem(CMH_TABLE_SORT_KEY) || "{}"); }
  catch (e) { _tableSortState = {}; }
  if (!_tableSortState || typeof _tableSortState !== "object") _tableSortState = {};
}
function _saveTableSortState() {
  try { localStorage.setItem(CMH_TABLE_SORT_KEY, JSON.stringify(_tableSortState)); } catch (e) { /* private mode */ }
}
function _tableBody(t) { return (t.tBodies && t.tBodies[0]) || null; }
function _tableHeaderRow(t) {
  return (t.tHead && t.tHead.rows.length) ? t.tHead.rows[t.tHead.rows.length - 1] : null;
}
function _sortableTables() {
  return [...root.querySelectorAll("table")].filter(function (t) {
    if (t.closest(".cm-skip")) return false;
    const body = _tableBody(t), hdr = _tableHeaderRow(t);
    if (!(body && hdr && body.rows.length >= 2 && hdr.cells.length)) return false;
    // Only sort simple rectangular bodies: every row has the same cell count as the
    // header and no colspan/rowspan. Complex bodies (grouped/spanned) would reorder
    // wrongly, so leave them un-sortable rather than scramble them.
    const ncols = hdr.cells.length;
    if ([...hdr.cells].some(c => (c.colSpan || 1) !== 1)) return false;
    return [...body.rows].every(function (r) {
      return r.cells.length === ncols &&
        [...r.cells].every(c => (c.colSpan || 1) === 1 && (c.rowSpan || 1) === 1);
    });
  });
}
function _tableKey(t, idx) {
  const hdr = _tableHeaderRow(t);
  const sig = hdr ? [...hdr.cells].map(c => (c.textContent || "").trim()).join("|") : "";
  return idx + "::" + sig.slice(0, 120);
}
function _parseNum(s) {
  if (s == null) return null;
  const t = String(s).replace(/[\s,$%]/g, "");
  if (t === "" || !/^[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?$/.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}
function _reorderBody(body, rows) {
  const frag = document.createDocumentFragment();
  rows.forEach(r => frag.appendChild(r));
  body.appendChild(frag);
}
// A cell's sortable text, EXCLUDING cm-skip UI (e.g. a code-block Copy button) so layer
// chrome never pollutes the sort key or flips numeric detection to lexicographic.
function _cellSortText(cell) {
  if (!cell) return "";
  const w = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      return (n.parentElement && n.parentElement.closest(".cm-skip"))
        ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
    },
  });
  let s = "", n;
  while ((n = w.nextNode())) s += n.nodeValue;
  return s.trim().replace(/\s+/g, " ");
}
function _sortRows(body, col, dir) {
  const rows = [...body.rows];
  const vals = rows.map(r => _cellSortText(r.cells[col]));
  const numeric = vals.every((v) => v === "" || _parseNum(v) !== null) && vals.some(v => _parseNum(v) !== null);
  const order = rows.map((r, i) => i);
  order.sort(function (a, b) {
    let cmp;
    if (numeric) {
      const na = _parseNum(vals[a]), nb = _parseNum(vals[b]);
      // Handle empties WITHOUT arithmetic on Infinity (-Infinity - -Infinity === NaN,
      // which corrupts Array.sort). Empty cells sort first in ascending order.
      if (na === null && nb === null) cmp = 0;
      else if (na === null) cmp = -1;
      else if (nb === null) cmp = 1;
      else cmp = na - nb;
    } else {
      cmp = vals[a].localeCompare(vals[b], undefined, { numeric: true, sensitivity: "base" });
    }
    if (cmp === 0) cmp = a - b;
    return dir === "desc" ? -cmp : cmp;
  });
  _reorderBody(body, order.map(i => rows[i]));
}
function _unsortRows(body) {
  const rows = [...body.rows];
  rows.sort((a, b) => (parseInt(a.dataset.cmhRow, 10) || 0) - (parseInt(b.dataset.cmhRow, 10) || 0));
  _reorderBody(body, rows);
}
function _indexTableRows() {
  _sortableTables().forEach(function (t) {
    const body = _tableBody(t);
    [...body.rows].forEach(function (r, ri) { if (r.dataset.cmhRow == null) r.dataset.cmhRow = String(ri); });
  });
}
function recomputeTextOffsets(persist) {
  if (persist === undefined) persist = true;
  let changed = false;
  const allNodes = getTextNodes();
  comments.forEach(function (c) {
    if (c.anchorType === "mermaid" || c.anchorType === "diff" || c.anchorType === "image") return;
    const marks = [...root.querySelectorAll('mark.cm-hl[data-cid="' + c.id + '"]')];
    if (!marks.length) return;
    const fT = firstTextNodeIn(marks[0]);
    const lT = lastTextNodeIn(marks[marks.length - 1]);
    if (!fT || !lT) return;
    // Contiguity guard: a text comment's marks must form ONE contiguous run. After a sort
    // scatters a multi-row selection, marks[0]..marks[last] can straddle unrelated rows;
    // collapsing that to a single [start,end] span would over-wrap them on reload. If the
    // run is discontiguous, skip recompute (accept graceful anchor loss, not corruption).
    const si = allNodes.indexOf(fT), ei = allNodes.indexOf(lT);
    if (si < 0 || ei < 0 || ei < si) return;
    let contiguous = true;
    for (let i = si; i <= ei; i++) {
      const p = allNodes[i].parentElement;
      if (!p || !p.closest('mark.cm-hl[data-cid="' + c.id + '"]')) { contiguous = false; break; }
    }
    if (!contiguous) return;
    const s = offsetWithin(fT, 0);
    const e = offsetWithin(lT, lT.nodeValue.length);
    if (s >= 0 && e > s && (s !== c.start || e !== c.end)) { c.start = s; c.end = e; changed = true; }
  });
  if (changed && persist) saveComments();
}
// Comments with offsets in the ORIGINAL (snapshot) DOM order, for export. While a table
// is sorted, live comment offsets are in sorted order, but exports serialize the original
// (pre-sort) snapshot; without this a comment on a sorted table cell would mis-anchor for
// a recipient who has no sort state. Restores original order, recomputes, snapshots, then
// re-applies the sorted view - leaving the live state untouched. Widget moves are not
// reverted here because Portable and Offline exports save the moved widget DOM.
function _canonicalCommentsForExport() {
  if (!_tableSortState || Object.keys(_tableSortState).length === 0) {
    recomputeTextOffsets(false);
    return comments.map(function (c) { return Object.assign({}, c); });
  }
  const savedState = JSON.parse(JSON.stringify(_tableSortState));
  _sortableTables().forEach(function (t) { _unsortRows(_tableBody(t)); });
  recomputeTextOffsets(false);
  const snap = comments.map(function (c) { return Object.assign({}, c); });
  _sortableTables().forEach(function (t, i) {
    const st = savedState[_tableKey(t, i)];
    if (st) _sortRows(_tableBody(t), st.col, st.dir);
  });
  recomputeTextOffsets(false);
  return snap;
}
function _exportableComments() {
  return withoutHandled(_canonicalCommentsForExport());
}
// Runs BEFORE backfillContext/restoreHighlights: re-applies the last persisted sort so
// the DOM order matches the persisted comment offsets.
function applyPersistedTableSorts() {
  _loadTableSortState();
  _indexTableRows();
  _sortableTables().forEach(function (t, i) {
    const st = _tableSortState[_tableKey(t, i)];
    if (st && typeof st.col === "number" && (st.dir === "asc" || st.dir === "desc")) {
      _sortRows(_tableBody(t), st.col, st.dir);
    }
  });
}
function _reflectSortIco(btn, dir) {
  btn.dataset.dir = dir || "";
  btn.setAttribute("aria-pressed", dir ? "true" : "false");
}
function setupSortableTables() {
  _sortableTables().forEach(function (t, i) {
    const key = _tableKey(t, i);
    const hdr = _tableHeaderRow(t);
    const body = _tableBody(t);
    t.classList.add("cmh-sortable");
    const cur = _tableSortState[key] || null;
    [...hdr.cells].forEach(function (th, ci) {
      if (th.querySelector(".cmh-sort-ctrl")) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cmh-sort-ctrl cm-skip";
      btn.title = "Sort by this column";
      btn.setAttribute("aria-label", "Sort by " + ((th.textContent || "").trim() || ("column " + (ci + 1))));
      btn.innerHTML = '<span class="cmh-sort-up" aria-hidden="true"></span><span class="cmh-sort-dn" aria-hidden="true"></span>';
      th.appendChild(btn);
      _reflectSortIco(btn, cur && cur.col === ci ? cur.dir : "");
      btn.addEventListener("click", function () {
        const prev = _tableSortState[key];
        let dir;
        if (prev && prev.col === ci) dir = prev.dir === "asc" ? "desc" : (prev.dir === "desc" ? "" : "asc");
        else dir = "asc";
        if (dir === "") { delete _tableSortState[key]; _unsortRows(body); }
        else { _tableSortState[key] = { col: ci, dir: dir }; _sortRows(body, ci, dir); }
        _saveTableSortState();
        [...hdr.cells].forEach(function (h2, cj) {
          const b2 = h2.querySelector(".cmh-sort-ctrl");
          if (b2) _reflectSortIco(b2, (dir && ci === cj) ? dir : "");
        });
        recomputeTextOffsets();
      });
    });
  });
}
let _cmModalSeq = 0;
// A small self-contained confirm dialog returning a Promise<boolean>. The safe choice
// (Cancel) is focused by default, so pressing Enter cancels; Escape and a backdrop
// click also cancel. Used for destructive actions such as Clear Comments.
function showConfirm(opts) {
  opts = opts || {};
  return new Promise((resolve) => {
    const prevFocus = document.activeElement;
    const overlay = document.createElement("div");
    overlay.className = "cm-modal-overlay cm-skip";
    const box = document.createElement("div");
    box.className = "cm-modal";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    const msg = document.createElement("p");
    msg.className = "cm-modal-msg";
    msg.id = "cm-modal-msg-" + (++_cmModalSeq);
    msg.textContent = opts.message || "Are you sure?";
    box.setAttribute("aria-labelledby", msg.id);
    const actions = document.createElement("div");
    actions.className = "cm-modal-actions";
    const okBtn = document.createElement("button");
    okBtn.type = "button";
    okBtn.textContent = opts.confirmLabel || "OK";
    if (opts.danger) okBtn.className = "danger";
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "cm-modal-default";
    cancelBtn.textContent = opts.cancelLabel || "Cancel";
    actions.append(okBtn, cancelBtn);   // Cancel is last (rightmost) and the default.
    box.append(msg, actions);
    overlay.append(box);
    document.body.appendChild(overlay);
    let done = false;
    function close(result) {
      if (done) return; done = true;
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
      if (prevFocus && typeof prevFocus.focus === "function") prevFocus.focus();
      resolve(result);
    }
    function onKey(e) {
      if (e.key === "Escape") {
        // Consume Escape so it dismisses only the dialog, not an open composer/menu behind it.
        e.preventDefault(); e.stopPropagation(); close(false); return;
      }
      if (e.key === "Tab") {
        // Trap focus between the two buttons so Tab cannot reach the page behind the modal.
        // Always consume Tab; if focus escaped the dialog, pull it back to the default (Cancel).
        e.preventDefault();
        const order = [okBtn, cancelBtn];
        const i = order.indexOf(document.activeElement);
        if (i === -1) { cancelBtn.focus(); return; }
        order[(i + (e.shiftKey ? order.length - 1 : 1)) % order.length].focus();
      }
    }
    okBtn.addEventListener("click", () => close(true));
    cancelBtn.addEventListener("click", () => close(false));
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(false); });
    document.addEventListener("keydown", onKey, true);
    cancelBtn.focus();  // Cancel is the Enter-default.
  });
}
let _clearAllBusy = false;
document.getElementById("btnClearAll").addEventListener("click", async () => {
  if (_clearAllBusy || !comments.length) return;  // guard re-entrant double-clicks
  _clearAllBusy = true;
  try {
    const ok = await showConfirm({
      message: `Delete all ${comments.length} comment(s)? This cannot be undone.`,
      confirmLabel: "OK",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok) return;
    _tombstoneEmbedded(comments.map(c => c.id));
    comments.forEach(c => removeHighlight(c));
    comments = [];
    saveComments();
    renderComments();
  } finally {
    _clearAllBusy = false;
  }
});

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
const _TRANSIENT_BODY_CLASSES = { "sidebar-open": 1, "cm-sidebar-resizing": 1, "cm-widget-dragging": 1, "cmh-deck-present": 1 };
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
async function _getBaseHtml() {
  // Prefer the on-disk version (cleaner diff). Fall back to the snapshot
  // taken at IIFE start if fetch fails (file://, network unavailable, blocked).
  // Either base may carry transient body state (a stale/open-sidebar source), so
  // normalize it here once for every export path (Save, Portable, Offline, Plain).
  try {
    const r = await fetch(location.href, { cache: "no-store" });
    if (r.ok) {
      const t = await r.text();
      if (t && t.includes('id="embeddedComments"')) return _stripTransientBodyClasses(t);
    }
  } catch (e) { /* fall through to snapshot */ }
  return _stripTransientBodyClasses(_snapshotWithTail());
}
function _isInjectedChrome(n) {
  if (n.nodeType !== 1) return false;
  if (CMH_INJECTED_CHROME.has(n)) return true;
  // Lazy chrome (tooltip, composer, modal, toast) is created after init and so is not in
  // the captured set; it always carries one of these layer classes, which host tail
  // content (a chart canvas, its data/init scripts) never uses.
  const cls = (n.getAttribute && n.getAttribute("class")) || "";
  return /(^|\s)(cm-tooltip|cm-composer|cm-modal-overlay|cm-toast)(\s|$)/.test(cls);
}
function _snapshotWithTail() {
  // SNAPSHOT_HTML is pristine (captured before any runtime mutation) but stops at the
  // layer <script>, so any host content parsed after it (chart data/init scripts placed
  // after the JS region, per charts.md) is missing and would be dropped on a file://
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
/* ---------- Save as plain HTML (strip the comment layer) ---------- */
// Produces a standalone copy of the document with the commenting *ability* removed but
// its appearance intact: the HTML-comment regions (HANDLED IDS, EMBEDDED COMMENTS,
// COMMENT UI) and the runtime JS are deleted, while every stylesheet is kept - the
// inline CSS region (or the nonportable companion <link>) carries the document's own
// content styling (tables, sections, code, diff, KQL, images), so the plain copy looks
// the same. The now-unused .cm-* UI rules are inert because their elements are gone.
//
// The base HTML here is the on-disk file or the IIFE-start snapshot (see SNAPSHOT_HTML),
// which never carries runtime comment artifacts (highlight marks, rings, data-cid) -
// those are added later by the layer - so there is nothing to sanitize out of the host
// content, and attempting to do so with document-wide regexes would risk corrupting
// legitimate host markup (code samples, host data-cid attributes, script literals).
function _buildPlainHtml(baseHtml) {
  let t = baseHtml;
  _assertSingleLayerRegions(t);
  const layerDescriptorScript = new RegExp("[ \\t]*<scr" + "ipt\\b[^>]*\\sid\\s*=\\s*([\"'])"
    + "commentableHtmlLayer\\1[^>]*>[\\s\\S]*?<\\/scr" + "ipt>\\s*", "i");
  t = t.replace(layerDescriptorScript, "");
  t = t.replace(/<!--\s*BEGIN: commentable-html - NONPORTABLE BOOTSTRAP[\s\S]*?END: commentable-html - NONPORTABLE BOOTSTRAP\s*-->\s*/i, "");
  // Remove the HTML-comment regions. The END anchor requires its own "<!-- ... END ... -->"
  // comment: embedded comment notes escape every "<" as \u003c, so a note can never forge
  // a "<!--". That prevents note text like "END: commentable-html - EMBEDDED COMMENTS -->"
  // from terminating the region early and leaking the comments that follow it.
  ["HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI"].forEach(function (name) {
    t = t.replace(new RegExp("<!--\\s*=*\\s*BEGIN: commentable-html - " + name +
      "[\\s\\S]*?<!--\\s*=*\\s*END: commentable-html - " + name + "\\s*=*\\s*-->"), "");
  });
  // The JS region sits last. Opened from file://, fetch() is blocked so
  // _getBaseHtml() returns a DOM snapshot taken while THIS script runs - the
  // parser has not reached the trailing "END ... JS" comment yet, so anchor on
  // the script's own closing tag instead (eat a trailing END marker if present).
  t = t.replace(new RegExp("<!--\\s*=*\\s*BEGIN: commentable-html - JS[\\s\\S]*?"
    + _cmhScriptClosePattern() + "\\s*(?:<!--\\s*=*\\s*END: commentable-html - JS\\s*-->)?"), "");
  // NonPortable mode loads the runtime from a companion <script src> file; drop only the
  // JS companion (the CSS companion <link> stays so the content keeps its styling).
  t = t.replace(/[ \t]*<!--\s*commentable-html - layer loaded[^\n]*-->\s*/i, "");
  t = t.replace(_cmhScriptTagPattern("[^>]*commentable-html[^>]*\\.js[^>]*", "\\s*", "ig"), "");
  t = t.replace(/[ \t]*<!--\s*END: commentable-html - JS\s*-->\s*/i, "");
  t = _stripTransientBodyClasses(t);
  // Data-safety net: the comment-data scripts must be gone. If a malformed or hand-edited
  // marker made a region strip miss, fail loudly instead of downloading a plain file that
  // still leaks the comments.
  if (/id\s*=\s*["'](?:handledCommentIds|embeddedComments)["']/.test(t)) {
    throw new Error("Plain export aborted: the comment regions could not be fully removed (malformed markers?).");
  }
  return t.replace(/\n{3,}/g, "\n\n");
}
function _suggestedPlainFilename() {
  const p = location.pathname;
  let name = p.substring(p.lastIndexOf("/") + 1);
  try { name = decodeURIComponent(name); } catch (e) { /* keep raw */ }
  if (!name || !/\.html?$/i.test(name)) name = "document.html";
  const m = name.match(/^(.*?)(\.html?)$/i);
  return m[1].replace(/-comments$/i, "") + ".plain" + m[2];
}
async function saveAsPlain() {
  let baseHtml;
  try { baseHtml = await _getBaseHtml(); }
  catch (e) { showToast("Could not load base HTML."); return; }
  baseHtml = _applyChecklistStateToHtml(baseHtml);
  let text;
  try { text = _buildPlainHtml(baseHtml); }
  catch (e) { showToast(e.message); return; }
  const filename = _suggestedPlainFilename();
  _downloadHtml(text, filename);
  showToast("Downloaded " + filename + " (plain HTML, comment layer removed).");
}
const _btnSaveHtml = document.getElementById("btnSaveHtml");
const _btnSaveHtmlTop = document.getElementById("btnSaveHtmlTop");
// "Export as Portable" always downloads ONE combined/standalone file
// with the current comments embedded: saveStandalone() rebuilds an inline file in
// nonportable mode and falls back to the in-file embed for inline documents.
if (_btnSaveHtml) _btnSaveHtml.addEventListener("click", saveStandalone);
if (_btnSaveHtmlTop) _btnSaveHtmlTop.addEventListener("click", saveStandalone);
const _btnSavePlain = document.getElementById("btnSavePlain");
const _btnSavePlainTop = document.getElementById("btnSavePlainTop");
if (_btnSavePlain) _btnSavePlain.addEventListener("click", saveAsPlain);
if (_btnSavePlainTop) _btnSavePlainTop.addEventListener("click", saveAsPlain);

/* ---------- Export standalone (nonportable -> single self-contained file) ---------- */
// In nonportable mode the live page only references companion files via <link> and
// <script src>. To produce ONE portable file we must inline those assets. We do
// NOT fetch() them (blocked from file://); instead we read the string payloads
// from window.__COMMENTABLE_ASSETS__, which loaded as a classic <script src> and
// therefore works even when the document is opened by double-click (file://).
function _escClose(s) { return String(s).replace(/<\/(script|style)>/gi, "<\\/$1>"); }
function _cmhScriptClosePattern() { return String.fromCharCode(60) + "\\/" + "script>"; }
function _cmhScriptTagPattern(attrs, tail, flags) {
  return new RegExp("[ \\t]*" + String.fromCharCode(60) + "script\\b" + attrs + ">\\s*"
    + _cmhScriptClosePattern() + (tail || ""), flags);
}
function _cmhEscapeRegExp(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
function _cmhAdvanceCommentState(line, state) {
  let i = 0;
  while (i < line.length) {
    if (state === "html") {
      const close = line.indexOf("-->", i);
      if (close < 0) return "html";
      state = "";
      i = close + 3;
      continue;
    }
    if (state === "css") {
      const close = line.indexOf("*/", i);
      if (close < 0) return "css";
      state = "";
      i = close + 2;
      continue;
    }
    const htmlOpen = line.indexOf("<!--", i);
    const cssOpen = line.indexOf("/*", i);
    let open = -1, next = "";
    if (htmlOpen >= 0 && (cssOpen < 0 || htmlOpen < cssOpen)) {
      open = htmlOpen;
      next = "html";
    } else if (cssOpen >= 0) {
      open = cssOpen;
      next = "css";
    }
    if (open < 0) return "";
    state = next;
    i = open + (next === "html" ? 4 : 2);
  }
  return state;
}
function _cmhRegionMarkerMatches(html, kind, name) {
  const marker = kind + ": commentable-html - " + name;
  const markerSource = _cmhEscapeRegExp(marker);
  const bare = new RegExp("^[ \\t]*(?:=+[ \\t]*)?(" + markerSource + ")[ \\t]*(?:=+[ \\t]*)?$");
  const inline = new RegExp("^[ \\t]*(?:<!--[ \\t]*|/\\*[ \\t]*)(?:=+[ \\t]*)?(" + markerSource + ")[ \\t]*(?:=+[ \\t]*)?(?:-->|\\*/)[ \\t]*$");
  const out = [];
  const lines = String(html || "").match(/[^\n]*(?:\n|$)/g) || [];
  let offset = 0, state = "";
  lines.forEach(function (line) {
    if (!line) return;
    const body = line.replace(/\r?\n$/, "");
    const inlineMatch = body.match(inline);
    const bareMatch = body.match(bare);
    const match = inlineMatch || ((state === "html" || state === "css") ? bareMatch : null);
    if (match) {
      const markerOffset = body.indexOf(match[1]);
      out.push({ index: offset + markerOffset });
    }
    state = _cmhAdvanceCommentState(body, state);
    offset += line.length;
  });
  return out;
}
function _assertSingleRegionMarkers(html, name) {
  const begins = _cmhRegionMarkerMatches(html, "BEGIN", name);
  const ends = _cmhRegionMarkerMatches(html, "END", name);
  if (begins.length !== 1 || ends.length !== 1) {
    throw new Error("Export aborted: malformed commentable-html region markers for " + name + ".");
  }
  if (begins[0].index >= ends[0].index) {
    throw new Error("Export aborted: commentable-html region " + name + " ends before it begins.");
  }
}
function _assertSingleLayerRegions(html) {
  CMH_REGION_NAMES.forEach(function (name) { _assertSingleRegionMarkers(html, name); });
}
// Insert `insertion` immediately before the LAST occurrence of </tag>. The real
// closing tag of a well-formed document is the last one; earlier matches can sit
// inside the pre-<html> documentation comment (whose prose literally mentions
// "</body>" and "<head>") or inside an inlined script string. A naive first-match
// replace would splice the payload into that comment and corrupt the file. This
// only bites when the base HTML is the raw on-disk file (fetched over http); a DOM
// snapshot drops the pre-<html> comment, which is why file:// exports were unaffected.
function _insertBeforeLastTag(html, tag, insertion) {
  const rx = new RegExp("</" + tag + "\\s*>", "gi");
  let idx = -1, m;
  while ((m = rx.exec(html))) idx = m.index;
  if (idx < 0) throw new Error("Could not find </" + tag + "> to inline into.");
  return html.slice(0, idx) + insertion + html.slice(idx);
}
function _inlineNonPortableAssets(baseHtml) {
  if (!CMH_ASSETS || !CMH_ASSETS.css || !CMH_ASSETS.js) {
    throw new Error("Cannot export standalone: the commentable-html assets file "
      + "(__COMMENTABLE_ASSETS__) did not load. Keep the companion .assets.js next "
      + "to this HTML, or keep the companion files alongside it.");
  }
  if (CMH_ASSETS.version && CMH_VERSION && CMH_ASSETS.version !== CMH_VERSION) {
    // Inlining a companion whose CSS/JS is a different version than the running layer
    // would bake a mismatched runtime into the portable file. Abort with guidance
    // rather than emit a document that silently disagrees with itself.
    throw new Error("Cannot export standalone: the companion assets file is version "
      + CMH_ASSETS.version + " but this document's runtime is " + CMH_VERSION
      + ". Refresh the companion .assets.js (or regenerate the document) so both match, then export again.");
  }
  let t = baseHtml;
  if (!/<link\b[^>]*commentable-html[^>]*\.css/i.test(t)) {
    throw new Error("Could not find the commentable-html stylesheet <link> to inline.");
  }
  _assertSingleLayerRegions(t);
  // 1) Strip every piece of nonportable scaffolding BEFORE inlining the payloads, so
  //    the marker-like strings inside the runtime source can never be matched and
  //    no leftover companion reference survives. _getBaseHtml() may hand us a
  //    file:// DOM snapshot whose whitespace around trailing markers is collapsed,
  //    so we re-emit the CSS/JS regions from scratch with their own newlines
  //    rather than trusting the snapshot's line breaks.
  t = _retargetLayerDescriptor(t, "portable");
  t = t.replace(/[ \t]*<!--\s*BEGIN: commentable-html - NONPORTABLE BOOTSTRAP[\s\S]*?END: commentable-html - NONPORTABLE BOOTSTRAP\s*-->[ \t]*/i, "");
  const cssRegion = /[ \t]*<!--\s*=*\s*BEGIN: commentable-html - CSS[\s\S]*?<!--\s*=*\s*END: commentable-html - CSS\s*=*\s*-->[ \t]*\n?/i;
  const jsRegion = /[ \t]*<!--\s*=*\s*BEGIN: commentable-html - JS[\s\S]*?<!--\s*=*\s*END: commentable-html - JS\s*=*\s*-->[ \t]*\n?/i;
  if (cssRegion.test(t)) {
    t = t.replace(cssRegion, "");
  } else {
    t = t.replace(/[ \t]*<link\b[^>]*commentable-html[^>]*\.css[^>]*>[ \t]*\n?/ig, "");
  }
  if (jsRegion.test(t)) {
    t = t.replace(jsRegion, "");
  } else {
    const companionScript = new RegExp("[ \\t]*<scr" + "ipt\\b[^>]*commentable-html[^>]*\\.js[^>]*>"
      + "\\s*<\\/scr" + "ipt>[ \\t]*\\n?", "ig");
    t = t.replace(/[ \t]*<!--\s*commentable-html - layer loaded[\s\S]*?-->[ \t]*\n?/i, "");
    t = t.replace(companionScript, "");
    t = t.replace(/[ \t]*<!--\s*END: commentable-html - JS\s*-->[ \t]*\n?/ig, "");
  }

  // 2) Inline the CSS in place of the removed <link>, and the runtime just before
  //    </body>. Each block carries its own region markers on their own lines.
  const styleBlock = "\n<style>\n"
    + "/* ============================================================\n"
    + "   BEGIN: commentable-html - CSS\n"
    + "   ============================================================ */\n"
    + _escClose(CMH_ASSETS.css) + "\n"
    + "/* ============================================================\n"
    + "   END: commentable-html - CSS\n"
    + "   ============================================================ */\n"
    + "</style>\n";
  const jsBlock = "\n<!-- ============================================================\n"
    + "     BEGIN: commentable-html - JS\n"
    + "     ============================================================ -->\n"
    + "<script>\n" + _escClose(CMH_ASSETS.js) + "\n</scr" + "ipt>\n"
    + "<!-- END: commentable-html - JS -->\n";
  if (!/<\/head>/i.test(t)) throw new Error("Could not find </head> to inline the stylesheet.");
  if (!/<\/body>/i.test(t)) throw new Error("Could not find </body> to inline the runtime.");
  // Insert the CSS before the LAST </head> and the runtime before the LAST </body>,
  // then re-collapse blank runs. Head first, so the runtime's own "</head>" string
  // literals cannot be mistaken for the document's real head.
  t = _insertBeforeLastTag(t, "head", styleBlock);
  t = _insertBeforeLastTag(t, "body", jsBlock);
  return t.replace(/\n{3,}/g, "\n\n");
}
function _buildStandaloneHtml(baseHtml, commentArr) {
  return _inlineNonPortableAssets(_buildSavedHtml(baseHtml, commentArr));
}
async function saveStandalone() {
  // "Export as Portable" always yields ONE combined file with the
  // comments embedded. An inline document is already self-contained, so the plain
  // in-file embed (saveHtml) IS the combined file there; only nonportable documents
  // need the CSS/JS inlined to become portable.
  if (!NONPORTABLE_MODE) return saveHtml();
  let baseHtml;
  try { baseHtml = await _getBaseHtml(); }
  catch (e) { showToast("Could not load base HTML."); return; }
  baseHtml = _applyWidgetLayoutToHtml(baseHtml);
  baseHtml = _applyChecklistStateToHtml(baseHtml);
  const exportComments = _exportableComments();
  let text;
  try { text = _buildStandaloneHtml(baseHtml, exportComments); }
  catch (e) { showToast(e.message); return; }
  const filename = _suggestedFilename();
  const n = exportComments.length;
  _downloadHtml(text, filename);
  showToast(`Downloaded ${filename} - one portable file, ${n} comment${n === 1 ? "" : "s"} embedded, no companion files needed.`);
}

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

/* ---------- Mode badge + asset-version handshake ---------- */
function assetBannerDismissKey(pageVer, runtimeVer) {
  return "commentable-html::assetBannerDismissed::" + COMMENT_KEY + "::" + String(pageVer || "")
    + "::" + String(runtimeVer || "");
}
function assetBannerDismissed(key) {
  if (!key) return false;
  try { return localStorage.getItem(key) === "1"; } catch (e) { return false; }
}
function ensureAssetBannerChrome(b) {
  let msgEl = b.querySelector(".cmh-asset-message");
  let btn = b.querySelector(".cmh-asset-dismiss");
  if (!msgEl) {
    const current = b.innerHTML;
    b.innerHTML = '<span class="cmh-asset-message"></span>'
      + '<button type="button" class="cmh-asset-dismiss cm-skip" aria-label="Dismiss">X</button>';
    msgEl = b.querySelector(".cmh-asset-message");
    btn = b.querySelector(".cmh-asset-dismiss");
    if (msgEl) msgEl.innerHTML = current;
  }
  if (btn && !btn.dataset.cmhBound) {
    btn.dataset.cmhBound = "1";
    btn.addEventListener("click", function () {
      const key = b.dataset.cmhDismissKey || "";
      if (key) {
        try { localStorage.setItem(key, "1"); } catch (e) { /* ignore */ }
      }
      b.hidden = true;
    });
  }
  return msgEl;
}
function revealAssetBanner(msg, pageVer, runtimeVer) {
  const b = document.getElementById("cmhAssetBanner");
  if (!b) return;
  const key = (pageVer || runtimeVer) ? assetBannerDismissKey(pageVer, runtimeVer) : "";
  if (assetBannerDismissed(key)) {
    b.hidden = true;
    return;
  }
  const msgEl = ensureAssetBannerChrome(b);
  if (msg && msgEl) msgEl.innerHTML = msg;
  b.dataset.cmhDismissKey = key;
  b.hidden = false;
}
function versionBannerMessage(label, pageVer, runtimeVer) {
  const compat = runtimeCompatibleWith(pageVer, runtimeVer);
  const pageHtml = '<code>' + escapeHtml(pageVer) + '</code>';
  const runtimeHtml = '<code>' + escapeHtml(runtimeVer) + '</code>';
  if (compat && compat.kind === "compatible") return null;
  if (compat && compat.kind === "major") {
    return "Commentable-html version mismatch: " + label + " was generated for commentable-html "
      + '<code>' + compat.page.major + ".x</code> but the loaded runtime is " + runtimeHtml
      + "; they are not compatible. Regenerate the document or restore a matching runtime.";
  }
  if (compat && compat.kind === "runtime-older") {
    return "Commentable-html version notice: " + label + " expects a newer commentable-html "
      + pageHtml + " than the loaded runtime " + runtimeHtml
      + "; update the companion files or refresh with cache disabled.";
  }
  if (String(pageVer || "") !== String(runtimeVer || "")) {
    return "Commentable-html version mismatch: " + label + " expects assets "
      + pageHtml + " but the loaded runtime is " + runtimeHtml
      + ". Refresh with cache disabled, or update the companion files.";
  }
  return null;
}
function maybeRevealVersionBanner(label, pageVer, runtimeVer) {
  if (!pageVer || !runtimeVer) return false;
  const msg = versionBannerMessage(label, pageVer, runtimeVer);
  if (!msg) return false;
  revealAssetBanner(msg, pageVer, runtimeVer);
  return true;
}
let _embeddedSigCache = null;
// Map of embedded comment id -> a content signature (updatedAt, else createdAt) so the
// "Standalone with comments" state reflects the embedded CONTENT, not just id presence:
// editing a comment bumps its updatedAt, so a stale embedded copy no longer counts.
function _embeddedCommentSig() {
  if (!_embeddedSigCache) {
    _embeddedSigCache = new Map();
    getEmbeddedComments().forEach(function (c) {
      // Use the same id-universe as mergeCommentSets (which drops unsafe ids from the
      // live set), otherwise an unsafe embedded id looks like a "deleted in session"
      // comment and falsely flips the badge to Not portable.
      if (c && c.id && SAFE_ID_RE.test(c.id)) _embeddedSigCache.set(c.id, c.updatedAt || c.createdAt || "");
    });
  }
  return _embeddedSigCache;
}
// The document is either "Portable" (self-contained and safe to share: assets embedded
// and every current comment embedded, or none) or "Not portable" (it references external
// skill/companion resources, and/or has comments that are not embedded in the file). The
// bubble hover explains WHY a file is not portable.
function isOfflineDocument() {
  const script = document.getElementById("commentableHtmlLayer");
  if (script) {
    try {
      const data = JSON.parse((script.textContent || "").trim() || "{}");
      if (data && data.mode === "offline") return true;
    } catch (e) { /* malformed descriptors are handled by validate.py */ }
  }
  return !!document.querySelector("#commentRoot [data-cm-offline-chart]");
}
function currentDocState() {
  const reasons = [];
  if (NONPORTABLE_MODE) reasons.push("it references external skill / companion resources");
  if (typeof widgetStateChanges === "function" && widgetStateChanges().length > 0) {
    reasons.push("a widget's layout was changed in this session and is not saved into the file");
  }
  if (typeof checklistChanges === "function" && checklistChanges().length > 0) {
    reasons.push("a checklist's state was changed in this session and is not saved into the file");
  }
  const emb = _embeddedCommentSig();
  if (comments.length > 0) {
    const hasUnembedded = !comments.every(function (c) {
      return emb.has(c.id) && emb.get(c.id) === (c.updatedAt || c.createdAt || "");
    });
    if (hasUnembedded) reasons.push("it has comments that are not embedded in the file");
  }
  // Embedded comments that are neither live nor marked handled still sit in the file even
  // though they were deleted in this session: sharing the file as-is would show them. The
  // file is stale (not portable) until re-exported.
  if (emb.size > 0) {
    const handled = getHandledIds();
    const liveIds = new Set(comments.map(function (c) { return c.id; }));
    let hasStale = false;
    emb.forEach(function (_sig, id) { if (!liveIds.has(id) && !handled.has(id)) hasStale = true; });
    if (hasStale) reasons.push("it still contains embedded comments that were removed in this session (re-export to drop them from the file)");
  }
  if (reasons.length === 0) {
    if (isOfflineDocument()) {
      return { type: "Offline", reason: "Offline: self-contained and works with no network - the review layer, styles, charts, and diagrams are all embedded in this one file." };
    }
    return { type: "Portable", reason: "Portable: self-contained and safe to share (assets embedded and every comment embedded)." };
  }
  return { type: "Not portable", reason: "Not portable because " + reasons.join(", and ") + ". Use Export as Portable to share it." };
}
function updateDocTypeUi() {
  const st = currentDocState();
  ["cmTypeBadge", "cmhModeBadge"].forEach(function (id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = st.type;
    el.setAttribute("data-doc-type", st.type);
    el.setAttribute("aria-label", st.reason);
    // If the tooltip layer already adopted this control (title moved to data-cmh-tip),
    // update the managed attributes in place so the new reason shows without a native-title
    // flash; otherwise set title and let the tooltip layer adopt it on first hover.
    if (el.hasAttribute("data-cmh-tip")) {
      el.setAttribute("data-cmh-tip", st.reason);
      el.removeAttribute("title");
    } else {
      el.title = st.reason;
    }
  });
}
function setupModeUi() {
  const ver = document.getElementById("cmVersion");
  if (ver) ver.textContent = "v" + CMH_VERSION;
  const meta = document.querySelector(".cm-sidebar .head-meta");
  if (meta && !meta.querySelector(".cm-brand-icon")) meta.insertAdjacentHTML("afterbegin", cmBrandLink(CMH_ICON_SVG));
  if (NONPORTABLE_MODE) {
    document.body.classList.add("cm-nonportable");
    // In nonportable (companion) mode the portability action embeds everything into one file.
    ["btnSaveHtml", "btnSaveHtmlTop"].forEach(function (id) {
      const b = document.getElementById(id);
      if (b) {
        // Preserve each button's icon + label span; the sidebar button uses the compact
        // "Portable" label, the overflow-menu item keeps the full "Export as Portable".
        const span = b.querySelector("span");
        const label = (id === "btnSaveHtmlTop") ? "Export as Portable" : "Portable";
        if (span) span.textContent = label; else b.textContent = label;
        b.title = "Download one self-contained, portable HTML with the commentable-html assets AND the current comments embedded, so it no longer depends on the skill folder or companion files.";
      }
    });
  }
  updateDocTypeUi();
  // Version handshake: the document declares the asset version it was generated
  // against. Same-major newer runtimes are compatible; older or breaking-major
  // runtimes warn rather than fail silently. Version strings are HTML-escaped since
  // they originate from an author-controlled <meta> / companion file.
  const declared = declaredAssetVersion();
  if (maybeRevealVersionBanner("this page", declared, CMH_VERSION)) {
    return;
  } else if (CMH_ASSETS && maybeRevealVersionBanner("the assets file", CMH_ASSETS.version, CMH_VERSION)) {
    return;
  } else {
    // No mismatch: make sure a banner the bootstrap watchdog may have raced to
    // show (slow-but-successful load) is hidden now that the runtime is up.
    const b = document.getElementById("cmhAssetBanner");
    if (b) b.hidden = true;
  }
}

/* ---------- Help dialog ---------- */
// Static, trusted help content (no user input) describing every feature and control.
function showHelp(restoreEl) {
  if (document.querySelector(".cm-help-overlay")) return; // one at a time
  const prevFocus = restoreEl || document.activeElement;
  const overlay = document.createElement("div");
  overlay.className = "cm-modal-overlay cm-help-overlay cm-skip";
  const box = document.createElement("div");
  box.className = "cm-modal cm-help";
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-label", "Commentable HTML help");
  const T = function (title, body, open) {
    return '<details class="cm-help-topic' + (open ? ' cm-help-default-open' : '') + '"' + (open ? ' open' : '') + '>'
      + '<summary>' + title + '</summary>'
      + '<div class="cm-help-topic-body">' + body + '</div>'
      + '</details>';
  };
  box.innerHTML =
    '<div class="cm-help-head">' +
      '<h2>' + CMH_ICON_SVG + ' Commentable HTML v' + CMH_VERSION + ' - Help</h2>' +
      '<button type="button" class="cm-help-close" title="Close help" aria-label="Close help">&times;</button>' +
    '</div>' +
    '<div class="cm-help-search">' +
      _cmIco("search", 15) +
      '<input type="search" class="cm-help-search-input" placeholder="Search help (e.g. export, diff, shortcuts)..." aria-label="Search help" autocomplete="off" spellcheck="false">' +
    '</div>' +
    '<div class="cm-help-body">' +
      T('Getting started',
        '<p>Commentable HTML turns any report into a review you can hand straight back to an AI agent. The loop has four steps:</p>' +
        '<ol>' +
          '<li><strong>Generate</strong> - ask an AI chat or terminal agent to produce the report or document as a commentable HTML file.</li>' +
          '<li><strong>Review</strong> - open the file in your browser and leave inline comments anywhere: text, code, tables, charts, diagrams, diffs or images.</li>' +
          '<li><strong>Hand back</strong> - click <strong>Copy all</strong> and paste the bundle back to the agent (or export the file and send it along).</li>' +
          '<li><strong>Refresh and repeat</strong> - the agent edits the source and marks your comments handled; reload the updated file and the addressed comments disappear. Repeat until none remain.</li>' +
        '</ol>' +
        '<figure class="cm-loop-figure">' +
          '<svg viewBox="0 0 640 250" role="img" aria-labelledby="cmLoopTitle cmLoopDesc">' +
            '<title id="cmLoopTitle">Commentable HTML self-review loop</title>' +
            '<desc id="cmLoopDesc">An AI agent generates a commentable HTML report; you review it and leave inline comments; you Copy all the comments back to the agent; the agent returns the updated file and you repeat until every comment is resolved.</desc>' +
            '<defs><marker id="cmLoopAh" markerWidth="10" markerHeight="10" refX="7.5" refY="4.5" orient="auto" markerUnits="userSpaceOnUse"><path class="cm-loop-head" d="M1,1 L8,4.5 L1,8 Z" /></marker></defs>' +
            '<rect class="cm-loop-bg" x="1" y="1" width="638" height="248" rx="16" />' +
            '<rect class="cm-loop-node" x="60" y="96" width="170" height="64" rx="12" />' +
            '<text class="cm-loop-title" x="145" y="133" text-anchor="middle" font-size="17" font-weight="600">AI agent</text>' +
            '<rect class="cm-loop-node" x="410" y="96" width="170" height="64" rx="12" />' +
            '<text class="cm-loop-title" x="495" y="133" text-anchor="middle" font-size="17" font-weight="600">You</text>' +
            '<text class="cm-loop-sub" x="320" y="106" text-anchor="middle" font-size="12.5">1. Generates HTML</text>' +
            '<line class="cm-loop-arrow" x1="236" y1="116" x2="402" y2="116" marker-end="url(#cmLoopAh)" />' +
            '<text class="cm-loop-sub" x="495" y="52" text-anchor="middle" font-size="12.5">2. Comment inline</text>' +
            '<path class="cm-loop-arrow" d="M468,95 C 456,60 534,60 522,95" marker-end="url(#cmLoopAh)" />' +
            '<line class="cm-loop-arrow" x1="404" y1="142" x2="238" y2="142" marker-end="url(#cmLoopAh)" />' +
            '<text class="cm-loop-sub" x="320" y="160" text-anchor="middle" font-size="12.5">3. Copy all back to the agent</text>' +
            '<path class="cm-loop-arrow" d="M160,175 C 250,235 380,235 470,161" marker-end="url(#cmLoopAh)" />' +
            '<text class="cm-loop-sub" x="320" y="242" text-anchor="middle" font-size="12.5">4. Reload and repeat</text>' +
          '</svg>' +
          '<figcaption>The self-review loop: an agent generates the file, you comment inline, Copy all hands the notes back, and you reload the updated file until none remain.</figcaption>' +
        '</figure>' +
        '<p><strong>Just want to leave a comment?</strong> If someone shared this file with you to review, you do not need an agent or an account - everything you need is in the file itself. Select any text and an <em>Add Comment</em> popup appears; type a note and Save. Your comments live in the panel on the right and persist in this browser. Hand your review back with <strong>Copy all</strong> (paste it to an agent) or <strong>Export as Portable</strong> (one file to send to a person, with your comments baked in).</p>' +
        '<p>Every topic below is collapsible; use the search box above to jump straight to an answer.</p>', true) +
      T('Leaving a comment',
        '<ul>' +
          '<li><strong>Text and code:</strong> select the words to comment on; the <em>Add Comment</em> popup appears (right-click a selection also works). Re-selecting the exact same range re-opens that comment; a different range starts a new one. Triple-click and block selections that spill onto section chrome still anchor to the real text.</li>' +
          '<li><strong>Headings:</strong> hover a heading and click the <em>Add Comment</em> button that appears just after the title.</li>' +
          '<li><strong>Tables:</strong> select text inside any cell like normal prose.</li>' +
          '<li><strong>Images:</strong> hover an image (or focus it and press <kbd>Enter</kbd>) and click <em>Add Comment</em> at its corner.</li>' +
          '<li><strong>Charts:</strong> a Chart.js canvas is commentable like an image.</li>' +
          '<li><strong>Mermaid diagrams:</strong> hover a node, edge label, gantt bar or sequence message and click <em>Add Comment</em>; hover an empty part of the diagram to comment on the whole diagram.</li>' +
          '<li><strong>Code-review diffs:</strong> select text inside a diff line for that snippet, or hover a line and click <em>Add Comment</em> to comment the whole line.</li>' +
          '<li><strong>Widgets and SVG nodes:</strong> in a document that marks parts with <code>data-cm-part</code> (a triage card, a diagram node), hover the part (or focus it and press <kbd>Enter</kbd>) and click <em>Add Comment</em>.</li>' +
          '<li><strong>Whole document:</strong> right-click an empty area and choose <em>Comment on document</em> for a note not tied to any element.</li>' +
        '</ul>') +
      T('Managing comments',
        '<ul>' +
          '<li><strong>Edit</strong> or <strong>Delete</strong> a comment from its card in the panel.</li>' +
          '<li><strong>Jump</strong> from a card to its highlight (collapsed sections auto-expand first).</li>' +
          '<li><strong>Sort</strong> the cards oldest-first or newest-first with the arrows, or click again for document order.</li>' +
          '<li><strong>Clear</strong> deletes every comment and always asks for confirmation first (Cancel is the default).</li>' +
        '</ul>') +
      T('The panel and toolbar',
        '<ul>' +
          '<li><strong>Copy all</strong> copies every comment as a Markdown bundle to paste back to the agent.</li>' +
          '<li>The <strong>count bubble</strong> shows how many open comments there are.</li>' +
          '<li><strong>Hide</strong> collapses the panel; a small floating toolbar stays to bring it back. The overflow <kbd>...</kbd> menu holds the export actions and <strong>Help &amp; About</strong>.</li>' +
          '<li>The <strong>Help &amp; About</strong> and <strong>Hide</strong> controls sit together at the top of the panel; <strong>Help &amp; About</strong> opens this dialog.</li>' +
        '</ul>') +
      T('Portable or Not portable',
        '<p>A bubble at the top of the panel shows whether this file is safe to share as-is:</p>' +
        '<ul>' +
          '<li><strong>Portable</strong> - self-contained: assets are embedded and every comment is embedded in the file, so a recipient sees exactly what you see.</li>' +
          '<li><strong>Offline</strong> - portable plus rendered mermaid diagrams and chart snapshots embedded, with remote loaders removed for no-network review.</li>' +
          '<li><strong>Not portable</strong> - the file references external companion resources, or has comments that are not embedded yet, or has embedded comments you deleted this session that are still in the file until you re-export. Hover the bubble for the exact reason.</li>' +
        '</ul>' +
          '<p>Use <em>Export as Portable</em> to produce a portable copy. Use <em>Export Offline</em> when rendered mermaid diagrams and charts must also work with no network.</p>') +
      T('Exporting and sharing',
        '<ul>' +
          '<li><strong>Export as Portable</strong> downloads one self-contained HTML (named with a <code>-portable</code> suffix) with the comments, and any external assets, embedded so the review travels with the file.</li>' +
          '<li><strong>Export Offline</strong> downloads a <code>-offline</code> HTML copy that first builds the portable file, then saves rendered mermaid diagrams as inline SVG and chart canvases as PNG images, with remote loaders removed.</li>' +
          '<li><strong>Export to Plain HTML</strong> downloads a copy with the commenting layer removed but all of your content and styling intact.</li>' +
          '<li><strong>Export to Markdown</strong> downloads a <code>.md</code> file; each block maps to a fixed Markdown form and your comments are appended as a section.</li>' +
          '<li>In <strong>NonPortable mode</strong> the layer loads from companion files; <em>Export as Portable</em> rebuilds a single combined file.</li>' +
          '</ul>') +
      T('Sending comments to an agent',
        '<ul>' +
          '<li><strong>Copy all</strong> emits an ordered Markdown bundle with each comment\'s location, quoted text, and note, ending in a machine-readable <code>HANDLED_IDS_JSON</code> line.</li>' +
          '<li>Drag-and-drop changes to a commentable widget are captured as a <em>Widget layout changes</em> section in the bundle, so the agent can reformat the source to match.</li>' +
          '<li>On a triage board, click <strong>Reset moves</strong> on the board to undo every drag move at once, or click <strong>Reset changes</strong> on the board-moves comment card to revert to the layout as of that comment.</li>' +
          '<li>The agent addresses the comments and marks them handled in this same file; handled comments are pruned on the next load and never reappear in the bundle.</li>' +
        '</ul>') +
      T('Navigation',
        '<ul>' +
          '<li>On wide screens a <strong>section menu</strong> appears on the left, highlights the section you are reading, and collapses to <em>Navigation &raquo;</em>.</li>' +
          '<li>Every section title has a caret to <strong>collapse or expand</strong> that section; <strong>Expand All</strong> / <strong>Collapse All</strong> act on every section at once.</li>' +
          '<li><strong>Scroll to Top</strong> / <strong>Scroll to Bottom</strong> jump the document, and a small bubble shows your scroll position.</li>' +
        '</ul>') +
      T('Reading aids',
        '<ul>' +
          '<li><strong>Sortable tables:</strong> click a column header to sort (numeric-aware), cycling ascending, descending, original.</li>' +
          '<li><strong>Code, KQL and charts</strong> are framed for readability; every code block has an always-visible <em>Copy</em> button, and a KQL caption title copies the cluster name.</li>' +
          '<li><strong>Diffs</strong> are syntax-highlighted with a per-document <em>Syntax</em> toggle (green when on, red when off).</li>' +
          '<li>Long content wraps inside its box and never overflows.</li>' +
        '</ul>') +
      T('Tips and shortcuts',
        '<p>Faster ways to work once you know the basics:</p>' +
        '<ul>' +
          '<li><strong>Right-click</strong> a selection to add a comment without waiting for the popup.</li>' +
          '<li><strong>Re-select the exact same text</strong> to reopen its comment; select a different range to start a new one.</li>' +
          '<li><strong>Comment on several things at once:</strong> each <em>Add Comment</em> opens its own composer, so you can leave notes side by side. Drag a composer by its grip if it covers the text.</li>' +
          '<li><strong>Sort</strong> the panel oldest- or newest-first with the arrows; click the active arrow again to return to document order.</li>' +
          '<li><strong>Expand All</strong> / <strong>Collapse All</strong> open or close every section at once, and the per-document <em>Syntax</em> toggle turns diff highlighting on or off.</li>' +
          '<li><strong>Diffs</strong> switch between side-by-side and inline from the header button; your comments stay attached either way.</li>' +
          '<li>See <strong>Keyboard and accessibility</strong> for the keyboard shortcuts (<kbd>Ctrl</kbd>+<kbd>Enter</kbd> to save, <kbd>Esc</kbd> to close).</li>' +
        '</ul>') +
      T('Keyboard and accessibility',
        '<ul>' +
          '<li><kbd>Ctrl</kbd>+<kbd>Enter</kbd> saves a comment in the composer; <kbd>Esc</kbd> cancels a composer or dialog.</li>' +
          '<li>Images and diff lines are focusable with <kbd>Tab</kbd>; press <kbd>Enter</kbd> to reveal their <em>Add Comment</em> button.</li>' +
          '<li>Controls carry hover and focus tooltips; this dialog traps focus and restores it to the control that opened it.</li>' +
        '</ul>') +
      T('Self-contained and privacy',
        '<p>Your comments are stored in this browser&#39;s <strong>localStorage</strong>, private to you: nothing is uploaded, there is no account, and no server ever sees them. They persist across reloads until you clear them, and they leave this browser only when you choose to - when you click <strong>Copy all</strong> or run an export.</p>' +
        '<p>Whether the review layer itself travels inside the file depends on the mode shown in the panel bubble: a <strong>Portable</strong> file has the review layer and your comments embedded, so it is safe to send as-is; a <strong>Not portable</strong> file references small companion resources instead. Use <em>Export as Portable</em> to bundle everything into one file. Optional host features (mermaid, Chart.js) can load from a CDN; if they cannot, mermaid stays readable source text and charts stay a blank canvas. Use <em>Export Offline</em> after those features render to snapshot them into a zero-network file.</p>') +
      '<div class="cm-help-about"><h3>About</h3>' +
        '<p>' + CMH_ICON_SVG + ' Commentable HTML <strong>v' + CMH_VERSION + '</strong>, authored by <a class="cm-brand-link" href="https://github.com/urikanonov" target="_blank" rel="noopener noreferrer">Uri Kanonov</a>.</p>' +
        '<ul>' +
          '<li><a href="https://urikanonov.github.io/ai-marketplace/commentable-html/" target="_blank" rel="noopener noreferrer">Website and live demo</a></li>' +
          '<li><a href="https://github.com/urikanonov/ai-marketplace" target="_blank" rel="noopener noreferrer">Source on GitHub</a></li>' +
          '<li><a href="https://github.com/urikanonov/ai-marketplace/issues/new?template=plugin-issue.yml" target="_blank" rel="noopener noreferrer">Report an issue</a></li>' +
          '<li><a href="https://github.com/urikanonov/ai-marketplace/issues/new?template=feature-request.yml" target="_blank" rel="noopener noreferrer">Request a feature</a></li>' +
          '<li><a href="https://github.com/urikanonov/ai-marketplace/blob/main/CONTRIBUTING.md" target="_blank" rel="noopener noreferrer">Contribute</a></li>' +
        '</ul>' +
      '</div>' +
      '<p class="cm-help-noresults" hidden>No help matches that search. Try another word.</p>' +
    '</div>';
  overlay.appendChild(box);
  document.body.appendChild(overlay);
  function close() {
    document.removeEventListener("keydown", onKey, true);
    overlay.remove();
    if (prevFocus && typeof prevFocus.focus === "function") prevFocus.focus();
  }
  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); return; }
    // Trap Tab inside the modal, cycling through its focusable elements (close button
    // and the About links) so focus cannot reach the page behind it.
    if (e.key === "Tab") {
      const f = Array.prototype.slice.call(box.querySelectorAll('button, a[href], input, summary'))
        .filter(function (el) { return el.offsetParent !== null || el === document.activeElement; });
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1], active = document.activeElement;
      if (e.shiftKey) {
        if (active === first || !box.contains(active)) { e.preventDefault(); last.focus(); }
      } else {
        if (active === last || !box.contains(active)) { e.preventDefault(); first.focus(); }
      }
    }
  }
  box.querySelector(".cm-help-close").addEventListener("click", close);
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  document.addEventListener("keydown", onKey, true);
  // Live search: filter topics and their entries; open matches, hide the rest, and
  // reset to the default (first topic open) when the query is cleared.
  const search = box.querySelector(".cm-help-search-input");
  function helpFilter(q) {
    q = (q || "").trim().toLowerCase();
    let anyVisible = false;
    box.querySelectorAll(".cm-help-topic").forEach(function (t) {
      const entries = t.querySelectorAll(".cm-help-topic-body li, .cm-help-topic-body p");
      if (!q) {
        t.style.display = ""; t.open = t.classList.contains("cm-help-default-open");
        entries.forEach(function (el) { el.style.display = ""; });
        anyVisible = true; return;
      }
      const summaryMatch = (t.querySelector("summary").textContent || "").toLowerCase().indexOf(q) !== -1;
      let entryMatch = false;
      entries.forEach(function (el) {
        const hit = (el.textContent || "").toLowerCase().indexOf(q) !== -1;
        el.style.display = (summaryMatch || hit) ? "" : "none";
        if (hit) entryMatch = true;
      });
      const show = summaryMatch || entryMatch;
      t.style.display = show ? "" : "none";
      if (show) { t.open = true; anyVisible = true; }
    });
    const nores = box.querySelector(".cm-help-noresults");
    if (nores) nores.hidden = anyVisible;
  }
  if (search) search.addEventListener("input", function () { helpFilter(search.value); });
  (search || box.querySelector(".cm-help-close")).focus();
}
["btnHelp", "btnHelpTop"].forEach(function (id) {
  const b = document.getElementById(id);
  if (b) b.addEventListener("click", function () {
    const menu = document.getElementById("toolbarMenu");
    // The overflow menu (and btnHelpTop) is hidden before the modal opens, so restore
    // focus to the still-visible menu button rather than the now-hidden item.
    const restore = (id === "btnHelpTop") ? document.getElementById("btnToolbarMenu") : b;
    if (menu) menu.hidden = true;
    showHelp(restore);
  });
});

/* ---------- Sort comments by time ---------- */
// The two arrow buttons toggle time-ascending / time-descending order; clicking the
// active one again returns to document (anchor position) order. The choice persists.
["btnSortAsc", "btnSortDesc"].forEach(function (id) {
  const b = document.getElementById(id);
  if (!b) return;
  b.addEventListener("click", function () {
    const mode = (id === "btnSortAsc") ? "time-asc" : "time-desc";
    commentSort = (commentSort === mode) ? "pos" : mode;
    try { localStorage.setItem(COMMENT_KEY + "::commentSort", commentSort); } catch (e) { /* private mode */ }
    renderComments();
  });
});

/* ---------- Table-of-contents side menu (wide screens) ---------- */
// When the document carries a table of contents (an author `.cm-toc`, else h2/h3
// ids), render a fixed, collapsible section menu on the left with scroll-spy and a
// back-to-top button. It is a runtime-only aid (never in the base HTML, so plain /
// standalone exports and the startup snapshot never include it) and is cm-skip so it
// is not itself commentable. CSS gates it to wide viewports.
function _cmSlugify(text) {
  const s = String(text).toLowerCase().trim()
    .replace(/[^\w\s-]/g, "").replace(/[\s_]+/g, "-").replace(/-+/g, "-").replace(/^-+|-+$/g, "");
  return s || "section";
}
// Every heading inside #commentRoot gets a stable id and becomes a deep-link: a plain
// click (no text selection, not on a link or highlight) updates the URL to #<id> and
// scrolls to it, so a reader can copy a link straight to any section.
function setupHeadingAnchors() {
  const seen = {};
  const headingAddBtn = document.getElementById("headingAddBtn");
  let headingHoverEl = null, headingHideTimer = null;
  function positionHeadingAdd(h) {
    const r = h.getBoundingClientRect();
    const bw = headingAddBtn.offsetWidth || 110, bh = headingAddBtn.offsetHeight || 26;
    // Place the button just after the heading TEXT (not at the far right of the full
    // block): measure where the rendered text actually ends via a contents range, then
    // sit a small gap to its right, vertically centered on that line.
    let anchorRight = r.left, anchorTop = r.top, anchorH = r.height;
    try {
      const range = document.createRange();
      range.selectNodeContents(h);
      const rects = [...range.getClientRects()].filter((x) => x.width > 0.5 && x.height > 0.5);
      if (rects.length) {
        const end = rects.reduce((a, b) => (b.right > a.right ? b : a));
        anchorRight = end.right; anchorTop = end.top; anchorH = end.height;
      }
    } catch (e) { /* fall back to the block box */ }
    const gap = 10;
    let left = anchorRight + gap;
    let top = anchorTop + (anchorH - bh) / 2;
    // If the label would run off the right edge, tuck it back against the block right.
    if (left + bw + 8 > window.innerWidth) left = r.right - bw - 6;
    headingAddBtn.style.left = Math.max(8, Math.min(left, window.innerWidth - bw - 8)) + "px";
    headingAddBtn.style.top = Math.max(8, Math.min(top, window.innerHeight - bh - 8)) + "px";
    // Return anchor visibility (not button fit) so repositionActiveAdd only hides the
    // button when the heading scrolls out of view, not when it sits near an edge.
    return _rectInViewport(r);
  }
  function showHeadingAdd(h) {
    if (!headingAddBtn) return;
    headingHoverEl = h;
    if (headingHideTimer) { clearTimeout(headingHideTimer); headingHideTimer = null; }
    headingAddBtn.hidden = false;
    positionHeadingAdd(h);
    _activeAdd = { el: h, btn: headingAddBtn, position: () => positionHeadingAdd(h), clear: () => {} };
  }
  function scheduleHideHeadingAdd() {
    if (headingHideTimer) clearTimeout(headingHideTimer);
    headingHideTimer = setTimeout(function () {
      if (headingAddBtn && !headingAddBtn.matches(":hover")) { headingAddBtn.hidden = true; headingHoverEl = null; }
    }, 220);
  }
  // Comment on a whole heading by selecting its text and opening the text composer, so
  // headings stay commentable even though a plain click deep-links them.
  function commentOnHeading(h) {
    const first = firstTextNodeIn(h), last = lastTextNodeIn(h);
    if (!first || !last) return;
    const r = document.createRange();
    r.setStart(first, 0); r.setEnd(last, last.nodeValue.length);
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
    const s = offsetWithin(first, 0), e = offsetWithin(last, last.nodeValue.length);
    if (s >= 0 && e > s) {
      const existing = comments.find(function (c) { return !c.anchorType && c.start === s && c.end === e; });
      if (existing) { openComposerForEdit(existing); return; }
    }
    pendingDiffSel = null;
    pendingRange = r.cloneRange();
    pendingQuote = sel.toString();
    openComposer(pendingRange, pendingQuote);
  }
  if (headingAddBtn && !headingAddBtn._cmWired) {
    headingAddBtn._cmWired = true;
    headingAddBtn.addEventListener("mouseenter", function () { if (headingHideTimer) { clearTimeout(headingHideTimer); headingHideTimer = null; } });
    headingAddBtn.addEventListener("mouseleave", scheduleHideHeadingAdd);
    headingAddBtn.addEventListener("click", function () {
      const h = headingHoverEl;
      headingAddBtn.hidden = true;
      if (h) commentOnHeading(h);
    });
  }
  root.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach(function (h) {
    if (h.closest(".cm-skip")) return;
    if (!h.id) {
      const base = _cmSlugify(h.textContent || "section");
      let id = base, n = 2;
      while (document.getElementById(id) || seen[id]) { id = base + "-" + n; n++; }
      h.id = id;
    }
    seen[h.id] = true;
    h.classList.add("cm-anchored");
    if (!h.title) h.title = "Click or press Enter to link to this section (hover or focus to comment on it)";
    // Keyboard parity: the heading is a deep-link affordance, so make it focusable and
    // activate the link on Enter/Space just like a click (a visible :focus-visible outline
    // is defined in CSS). Focusing it also reveals the add-comment button, which is itself
    // a real focusable button reachable by Tab.
    if (!h.hasAttribute("tabindex")) h.setAttribute("tabindex", "0");
    function deepLink() {
      if (window.history && history.pushState) history.pushState(null, "", "#" + h.id);
      else location.hash = h.id;
      h.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    h.addEventListener("click", function (e) {
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed) return;              // selecting text to comment
      if (e.target.closest("a, mark.cm-hl")) return;    // let links / highlight-clicks win
      deepLink();
    });
    h.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
      if (e.target !== h) return;                       // let a focused child (link) act
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed) return;
      e.preventDefault();
      deepLink();
    });
    h.addEventListener("mouseenter", function () { showHeadingAdd(h); });
    h.addEventListener("mouseleave", scheduleHideHeadingAdd);
    h.addEventListener("focus", function () { showHeadingAdd(h); });
    h.addEventListener("blur", scheduleHideHeadingAdd);
  });
}
// Every authored <section> with a heading becomes collapsible: a caret on the heading
// toggles it, and the side TOC gets Expand All / Collapse All. Collapsing sets a class
// (display:none via CSS) - it never removes or reorders nodes, so comment text offsets
// stay valid. The caret is a text-free cm-skip element (pseudo-element glyph) so it does
// not pollute heading text or offsets.
const _cmSectionToggles = [];
function setupCollapsibleSections() {
  _cmSectionToggles.length = 0;
  root.querySelectorAll("section").forEach(function (sec) {
    if (sec.closest(".cm-skip")) return;
    const heading = sec.querySelector(":scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > h5, :scope > h6");
    if (!heading || heading.closest(".cm-skip")) return;
    if (heading.querySelector(".cmh-sec-caret")) return;
    heading.classList.add("cmh-section-heading");
    const caret = document.createElement("button");
    caret.type = "button";
    caret.className = "cmh-sec-caret cm-skip";
    caret.setAttribute("aria-expanded", "true");
    caret.setAttribute("aria-label", "Collapse section");
    caret.title = "Collapse section";
    heading.insertBefore(caret, heading.firstChild);
    function setState(collapsed) {
      sec.classList.toggle("cmh-section-collapsed", collapsed);
      caret.setAttribute("aria-expanded", String(!collapsed));
      caret.title = collapsed ? "Expand section" : "Collapse section";
      caret.setAttribute("aria-label", collapsed ? "Expand section" : "Collapse section");
    }
    caret.addEventListener("click", function (e) {
      e.stopPropagation();
      setState(!sec.classList.contains("cmh-section-collapsed"));
    });
    // Clicking a collapsed section's title (anywhere but the caret) expands it too - a
    // collapsed section shows only its heading, so a plain click is the natural gesture.
    // Ignore clicks that are part of a text selection so commenting on an expanded heading
    // is unaffected.
    heading.addEventListener("click", function (e) {
      if (e.target.closest(".cmh-sec-caret")) return;
      if (!sec.classList.contains("cmh-section-collapsed")) return;
      const sel = window.getSelection();
      if (sel && sel.toString().trim()) return;
      setState(false);
    });
    _cmSectionToggles.push(setState);
  });
}
function setupSideToc() {
  const root = document.getElementById("commentRoot") || document.body;
  const items = [];
  const tocLinks = root.querySelectorAll(".cm-toc a[href^='#']");
  if (tocLinks.length) {
    tocLinks.forEach(function (a) {
      let id = (a.getAttribute("href") || "").slice(1);
      try { id = decodeURIComponent(id); } catch (e) { /* malformed %-encoding: keep the raw id */ }
      const el = id && document.getElementById(id);
      if (el) items.push({ id: id, label: (a.textContent || "").trim(), el: el, level: 1 });
    });
  } else {
    root.querySelectorAll("h2[id], h3[id]").forEach(function (h) {
      items.push({ id: h.id, label: (h.textContent || "").trim(), el: h, level: h.tagName === "H3" ? 2 : 1 });
    });
  }
  if (items.length < 2) return; // not worth a side menu
  const nav = document.createElement("nav");
  nav.className = "cm-side-toc cm-skip";
  nav.id = "cmSideToc";
  nav.setAttribute("aria-label", "Section navigation");
  const head = document.createElement("div");
  head.className = "cm-side-toc-head";
  const title = document.createElement("span");
  title.className = "cm-side-toc-title";
  title.textContent = "Navigation";
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "cm-side-toc-toggle";
  toggle.title = "Collapse the section menu";
  toggle.setAttribute("aria-expanded", "true");
  toggle.setAttribute("aria-label", "Collapse section menu");
  toggle.innerHTML = "&laquo;";
  head.append(title, toggle);
  const list = document.createElement("ul");
  list.className = "cm-side-toc-list";
  const links = [];
  // If the author already numbered their headings (e.g. "1. Summary", "3.1 Goals"), do NOT
  // add a second computed number - show the label as-is so there is a single number.
  const _numRe = /^(?:\d+(?:\.\d+)*[.)]|\d+\.\d+(?:\.\d+)*)\s+/;
  const authorNumbered = items.some(function (it) { return _numRe.test(it.label); });
  let n1 = 0, n2 = 0;
  items.forEach(function (it) {
    const li = document.createElement("li");
    if (it.level === 2) li.className = "is-sub";
    const a = document.createElement("a");
    a.href = "#" + it.id;
    if (authorNumbered) {
      a.textContent = it.label;
    } else {
      // Section numbers: top-level items count 1, 2, 3...; sub-items count 1.1, 1.2...
      let num;
      if (it.level === 2) { n2++; num = (n1 || 1) + "." + n2; }
      else { n1++; n2 = 0; num = String(n1); }
      a.innerHTML = '<span class="cm-toc-num">' + num + '</span> ' + escapeHtml(it.label);
    }
    li.appendChild(a);
    list.appendChild(li);
    links.push(a);
  });
  const scrollBtns = document.createElement("div");
  scrollBtns.className = "cm-side-toc-scroll";
  let expandGrp = null;
  if (_cmSectionToggles.length) {
    const expandAll = document.createElement("button");
    expandAll.type = "button";
    expandAll.className = "cm-side-toc-top";
    expandAll.title = "Expand all sections";
    expandAll.innerHTML = _cmIco("expand") + "<span>Expand All</span>";
    expandAll.addEventListener("click", function () { _cmSectionToggles.forEach(function (t) { t(false); }); });
    const collapseAll = document.createElement("button");
    collapseAll.type = "button";
    collapseAll.className = "cm-side-toc-top";
    collapseAll.title = "Collapse all sections";
    collapseAll.innerHTML = _cmIco("collapse") + "<span>Collapse All</span>";
    collapseAll.addEventListener("click", function () { _cmSectionToggles.forEach(function (t) { t(true); }); });
    expandGrp = document.createElement("div");
    expandGrp.className = "cm-side-toc-scroll";
    expandGrp.append(expandAll, collapseAll);
  }
  const top = document.createElement("button");
  top.type = "button";
  top.className = "cm-side-toc-top";
  top.title = "Scroll to the top of the document";
  top.innerHTML = _cmIco("top") + "<span>Scroll to Top</span>";
  const bottom = document.createElement("button");
  bottom.type = "button";
  bottom.className = "cm-side-toc-top cm-side-toc-bottom";
  bottom.title = "Scroll to the bottom of the document";
  bottom.innerHTML = _cmIco("bottom") + "<span>Scroll to Bottom</span>";
  scrollBtns.append(top, bottom);
  if (expandGrp) nav.append(head, list, expandGrp, scrollBtns);
  else nav.append(head, list, scrollBtns);
  document.body.appendChild(nav);
  document.body.classList.add("cm-side-toc-on");
  toggle.addEventListener("click", function () {
    const collapsed = nav.classList.toggle("is-collapsed");
    document.body.classList.toggle("cm-side-toc-collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    // Collapsed shows a "Navigation" label + >> expand chevron; open shows << collapse.
    toggle.innerHTML = collapsed ? "Navigation &raquo;" : "&laquo;";
    toggle.setAttribute("aria-label", collapsed ? "Expand section menu" : "Collapse section menu");
    toggle.title = collapsed ? "Expand the section menu" : "Collapse the section menu";
  });
  top.addEventListener("click", function () {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  bottom.addEventListener("click", function () {
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
  });
  function onScroll() {
    // Activate the section nearest above the threshold by GEOMETRY (greatest top that is
    // still <= 120), so it is correct even if the author TOC links are not in document order.
    let activeIdx = 0;
    let bestTop = -Infinity;
    for (let i = 0; i < items.length; i++) {
      const top = items[i].el.getBoundingClientRect().top;
      if (top <= 120 && top > bestTop) { bestTop = top; activeIdx = i; }
    }
    // At the page bottom a short trailing section never reaches the 120px threshold, so the
    // final item would never light up. Force it active once the document is fully scrolled.
    const doc = document.documentElement;
    if (window.innerHeight + window.scrollY >= doc.scrollHeight - 2) activeIdx = items.length - 1;
    for (let i = 0; i < links.length; i++) links[i].classList.toggle("is-active", i === activeIdx);
  }
  let raf = 0;
  function schedule() {
    if (raf) return;
    if (typeof requestAnimationFrame !== "function") { onScroll(); return; }
    raf = requestAnimationFrame(function () { raf = 0; onScroll(); });
  }
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  onScroll();
}

// A small bottom-right bubble showing how far through the document the reader has
// scrolled. cm-skip and runtime-created, so it never appears in a Plain export.
function setupScrollProgress() {
  if (document.getElementById("cmScrollProgress")) return;
  const el = document.createElement("div");
  el.className = "cm-scroll-progress cm-skip";
  el.id = "cmScrollProgress";
  el.setAttribute("aria-hidden", "true");
  el.title = "Scroll position in the document";
  document.body.appendChild(el);
  function update() {
    const doc = document.documentElement;
    const max = doc.scrollHeight - window.innerHeight;
    const pct = max > 4 ? Math.round((window.scrollY / max) * 100) : 100;
    el.textContent = Math.max(0, Math.min(100, pct)) + "%";
  }
  let raf = 0;
  function schedule() {
    if (raf) return;
    if (typeof requestAnimationFrame !== "function") { update(); return; }
    raf = requestAnimationFrame(function () { raf = 0; update(); });
  }
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  update();
}

/* ---------- Toast ---------- */
let toastTimer = null;
function showToast(msg, opts) {
  opts = opts || {};
  toast.textContent = msg;
  // Screen readers: errors are announced assertively as an alert, normal status politely.
  if (opts.alert) { toast.setAttribute("role", "alert"); toast.setAttribute("aria-live", "assertive"); }
  else { toast.setAttribute("role", "status"); toast.setAttribute("aria-live", "polite"); }
  toast.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), opts.duration || 3000);
}

/* ---------- Handled-id pruning + startup ---------- */
function getHandledIds() {
  const el = document.getElementById("handledCommentIds");
  if (!el) return new Set();
  try {
    const arr = JSON.parse((el.textContent || "").trim() || "[]");
    return new Set(arr);
  } catch (e) { console.warn("Could not parse handledCommentIds JSON:", e); return new Set(); }
}
function pruneHandled() {
  const handled = getHandledIds();
  const before = comments.length;
  comments = comments.filter(c => !handled.has(c.id));
  const removed = before - comments.length;
  saveComments();
  return removed;
}
function withoutHandled(arr) {
  const handled = getHandledIds();
  if (!handled.size) return arr;
  return arr.filter(c => !handled.has(c.id));
}
function restoreHighlights() {
  const textComments = comments.filter(c => c.anchorType !== "mermaid" && c.anchorType !== "diff"
    && c.anchorType !== "image" && c.anchorType !== "widget" && c.anchorType !== "document");
  const sorted = [...textComments].sort((a, b) => a.start - b.start);
  sorted.forEach(c => {
    const r = rangeFromOffsets(c.start, c.end);
    if (r) {
      try { wrapRangeWithMark(r, c.id); }
      catch (e) { console.warn("Could not restore highlight for", c.id, e); }
    } else {
      console.warn("Lost anchor for comment", c.id, "- offsets", c.start, c.end);
    }
  });
}


function setupChartContainment() {
  root.querySelectorAll("figure.chart > .chart-wrap").forEach(function (wrap) {
    if (!wrap.style.position) wrap.style.position = "relative";
  });
  if (window.Chart && window.Chart.defaults) {
    window.Chart.defaults.responsive = true;
    window.Chart.defaults.maintainAspectRatio = false;
  }
}

function setupFooter() {
  if (document.getElementById("cmFooter")) return;
  const f = document.createElement("footer");
  f.id = "cmFooter";
  f.className = "cm-skip cm-footer";
  f.setAttribute("aria-label", "About Commentable HTML");
  let gen = root.getAttribute("data-generated");
  if (!gen) { const lm = Date.parse(document.lastModified); if (!isNaN(lm)) gen = new Date(lm).toISOString(); }
  const genStr = gen ? formatTime(gen) : "unknown";
  f.innerHTML =
    cmBrandLink(CMH_ICON_SVG
      + '<span class="cm-footer-name">Commentable HTML <span class="cm-footer-ver">v' + CMH_VERSION + '</span></span>')
    + '<span class="cm-footer-sep" aria-hidden="true">\u00b7</span>'
    + '<span class="cm-footer-gen">Generated ' + escapeHtml(genStr) + '</span>'
    + '<span class="cm-footer-sep" aria-hidden="true">\u00b7</span>'
    + '<button type="button" class="cm-footer-help">Help &amp; about</button>';
  document.body.appendChild(f);
  document.body.classList.add("cm-has-footer");
  const hb = f.querySelector(".cm-footer-help");
  if (hb) hb.addEventListener("click", function () { showHelp(hb); });
}

// Lightweight, dependency-free tooltip layer. It upgrades the native `title` on chrome
// controls into a styled hover/focus bubble. On first hover the title is moved to
// data-cmh-tip (so the browser's own delayed tooltip never double-shows) and mirrored
// to aria-label ONLY when the control has no other accessible name, so visible-text
// buttons keep their name. Delegated at the document, so controls created later
// (composers, add buttons, carets, copy buttons) are covered with no re-init.
let _cmTipEl = null, _cmTipTimer = null, _cmTipFor = null, _cmTipPending = null;
function _cmTipTarget(node) {
  let el = node;
  while (el && el.nodeType === 1) {
    if ((el.hasAttribute("data-cmh-tip") || el.hasAttribute("title")) && el.closest(".cm-skip")) return el;
    el = el.parentElement;
  }
  return null;
}
function _cmTipText(el) {
  const t = el.getAttribute("title");
  if (t != null) {
    // A freshly-set title (including a runtime `.title =` update) wins over any cached
    // value, and is moved out of `title` so the browser's own tooltip never doubles up.
    el.setAttribute("data-cmh-tip", t);
    el.removeAttribute("title");
    if (!el.getAttribute("aria-label") && !el.getAttribute("aria-labelledby") && !(el.textContent || "").trim())
      el.setAttribute("aria-label", t);
    return t;
  }
  return el.getAttribute("data-cmh-tip") || "";
}
function _cmTipShow(el) {
  if (_cmTipTimer) { clearTimeout(_cmTipTimer); _cmTipTimer = null; }
  _cmTipPending = null;
  if (!el.isConnected) return;
  const text = _cmTipText(el);
  if (!text) return;
  if (!_cmTipEl) {
    _cmTipEl = document.createElement("div");
    _cmTipEl.className = "cm-tooltip cm-skip";
    _cmTipEl.setAttribute("role", "tooltip");
    document.body.appendChild(_cmTipEl);
  }
  _cmTipFor = el;
  _cmTipEl.textContent = text;
  _cmTipEl.classList.remove("below");
  _cmTipEl.style.visibility = "hidden";
  _cmTipEl.classList.add("is-visible");
  const r = el.getBoundingClientRect();
  const tw = _cmTipEl.offsetWidth, th = _cmTipEl.offsetHeight;
  let left = r.left + r.width / 2 - tw / 2;
  let top = r.top - th - 8;
  if (top < 6) { top = r.bottom + 8; _cmTipEl.classList.add("below"); }
  left = Math.max(6, Math.min(left, window.innerWidth - tw - 6));
  _cmTipEl.style.left = left + "px";
  _cmTipEl.style.top = top + "px";
  const cx = r.left + r.width / 2 - left;
  _cmTipEl.style.setProperty("--cm-tip-arrow", Math.max(10, Math.min(tw - 10, cx)) + "px");
  _cmTipEl.style.visibility = "";
}
function _cmTipHide() {
  if (_cmTipTimer) { clearTimeout(_cmTipTimer); _cmTipTimer = null; }
  _cmTipPending = null; _cmTipFor = null;
  if (_cmTipEl) _cmTipEl.classList.remove("is-visible");
}
function _cmTipSchedule(el) {
  if (el === _cmTipFor) { if (_cmTipTimer) { clearTimeout(_cmTipTimer); _cmTipTimer = null; } return; }
  if (el === _cmTipPending) return;
  if (_cmTipTimer) clearTimeout(_cmTipTimer);
  _cmTipText(el); // strip the native title now so the browser tooltip cannot show during the delay
  _cmTipPending = el;
  _cmTipTimer = setTimeout(function () {
    _cmTipTimer = null; _cmTipPending = null;
    if (el.isConnected) _cmTipShow(el);
  }, 350);
}
function setupTooltips() {
  if (setupTooltips._done) return; // idempotent - never double-bind the document listeners
  setupTooltips._done = true;
  const hoverCapable = !(window.matchMedia && window.matchMedia("(hover: none)").matches);
  if (hoverCapable) {
    document.addEventListener("mouseover", function (e) {
      if (_cmTipFor && !_cmTipFor.isConnected) _cmTipHide(); // heal a bubble whose control was removed
      const el = _cmTipTarget(e.target);
      if (el) _cmTipSchedule(el); else if (!_cmTipTarget(e.relatedTarget)) _cmTipHide();
    }, true);
    document.addEventListener("mouseout", function (e) {
      const from = _cmTipTarget(e.target);
      if (from && from !== _cmTipTarget(e.relatedTarget)) _cmTipHide();
    }, true);
  }
  // Focus tooltips work for keyboard users on every device, including touch/hybrid, so
  // they are wired even when hover is unavailable.
  document.addEventListener("focusin", function (e) {
    const el = _cmTipTarget(e.target);
    if (el) _cmTipShow(el); else _cmTipHide();
  }, true);
  document.addEventListener("focusout", _cmTipHide, true);
  window.addEventListener("scroll", _cmTipHide, true);
  document.addEventListener("mousedown", _cmTipHide, true);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") _cmTipHide(); }, true);
}
loadComments();
const prunedCount = pruneHandled();
// setupDiffLayer must run BEFORE any text-offset computation: it wraps each
// authored <pre class="cmh-diff"> in a .cm-skip host, removing the diff text from
// the offset coordinate system. Running it before backfillContext/restoreHighlights
// keeps text-comment offsets consistent between save time and reload.
setupDiffLayer();
applyPersistedTableSorts();
backfillContext();
restoreHighlights();
setupMermaidLayer();
setupImageLayer();
setupWidgetLayer();
setupChecklistLayer();
setupChartContainment();
setupCodeCopy();
setupSortableTables();
setupModeUi();
setupSidebarResize();
setupCommentSearch();
function setupDeck() {
  if (window.__cmhDeck) return;  // idempotent: never install the deck chrome twice
  const stage = root.querySelector(".deck-stage");
  const viewport = root.querySelector(".deck-viewport") || stage && stage.parentNode;
  const slides = stage ? Array.prototype.slice.call(stage.querySelectorAll(".slide")) : [];
  if (!stage || !slides.length) return;

  let current = slides.findIndex((s) => s.classList.contains("active"));
  if (current < 0) current = 0;
  let commentMode = false;
  let counter = null, prevBtn = null, nextBtn = null;
  // Start clean: a stale comment-mode class (e.g. from a serialized live DOM) must not fight
  // the present-mode default applied below.
  root.classList.remove("cmh-deck-comment-mode");

  function fitStage() {
    const host = viewport || document.documentElement;
    const vw = host.clientWidth || window.innerWidth;
    const vh = host.clientHeight || window.innerHeight;
    const scale = Math.min(vw / 1920, vh / 1080);
    const x = (vw - 1920 * scale) / 2;
    const y = (vh - 1080 * scale) / 2;
    stage.style.transform = "translate(" + x + "px, " + y + "px) scale(" + scale + ")";
  }

  function show(index) {
    if (!Number.isInteger(index) || index < 0 || index >= slides.length) return false;
    const changed = index !== current;
    slides.forEach((s, i) => {
      s.classList.toggle("active", i === index);
      s.classList.toggle("visible", i === index);
    });
    current = index;
    if (counter) {
      counter.textContent = (index + 1) + " / " + slides.length;
      // Screen readers announce the live region's text; a bare "2 / 4" reads as "2 slash 4",
      // so expose a spoken form via the label.
      counter.setAttribute("aria-label", "Slide " + (index + 1) + " of " + slides.length);
    }
    if (prevBtn) prevBtn.disabled = index === 0;
    if (nextBtn) nextBtn.disabled = index === slides.length - 1;
    // Fire only on a real move (a changed active slide), never for the initial render or a
    // re-selection of the already-active slide.
    if (changed) {
      document.dispatchEvent(new CustomEvent("cmh:slidechange", {
        detail: { slideId: slides[index].getAttribute("data-slide-id"), index },
      }));
    }
    return true;
  }
  function showById(id) {
    if (!id) return false;
    const i = slides.findIndex((s) => s.getAttribute("data-slide-id") === id);
    return i >= 0 ? show(i) : false;
  }

  window.__cmhDeck = {
    showSlide: show,
    showSlideById: showById,
    activeSlideId: () => slides[current] && slides[current].getAttribute("data-slide-id"),
    slideCount: () => slides.length,
  };

  show(current);
  fitStage();
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(fitStage).observe(viewport || document.documentElement);
  } else {
    window.addEventListener("resize", fitStage);
  }
  // Default to a clean full-screen presentation: hide the comment sidebar/toolbar until the
  // user enters comment mode (see the cmh-deck-present CSS).
  document.body.classList.add("cmh-deck-present");

  function isEditableTarget(t) {
    if (!t) return false;
    if (t.isContentEditable) return true;
    const tag = t.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
    return !!(t.closest && t.closest(".cm-skip"));
  }
  document.addEventListener("keydown", (e) => {
    if (commentMode || e.defaultPrevented || isEditableTarget(e.target)) return;
    if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") {
      if (show(current + 1)) e.preventDefault();
    } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
      if (show(current - 1)) e.preventDefault();
    } else if (e.key === "Home") {
      if (show(0)) e.preventDefault();
    } else if (e.key === "End") {
      if (show(slides.length - 1)) e.preventDefault();
    }
  });

  // Deck-aware jump: activating a comment card navigates to its owning slide before the
  // layer's own scrollIntoView (which cannot reveal a hidden slide) runs.
  document.addEventListener("click", (e) => {
    const card = e.target.closest && e.target.closest(".cm-card[data-cid]");
    if (!card) return;
    const cid = card.getAttribute("data-cid");
    if (!cid) return;
    const q = (window.CSS && CSS.escape) ? CSS.escape(cid) : cid;
    const anchor = root.querySelector(
      'mark.cm-hl[data-cid="' + q + '"], [data-cids~="' + q + '"], [data-cid="' + q + '"]');
    const slide = anchor && anchor.closest(".slide");
    if (slide) showById(slide.getAttribute("data-slide-id"));
  }, true);

  function setCommentMode(on) {
    commentMode = on;
    root.classList.toggle("cmh-deck-comment-mode", on);
    document.body.classList.toggle("cmh-deck-present", !on);
    try { if (on) openSidebar(); else closeSidebar(); } catch (e) { /* sidebar helpers are optional */ }
    toggle.setAttribute("aria-pressed", String(on));
    toggle.classList.toggle("cmh-deck-mode-on", on);
    // Comment mode narrows the stage (the sidebar takes width); refit after layout settles.
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(fitStage); else fitStage();
  }
  const toggle = document.createElement("button");
  toggle.className = "cm-skip cmh-deck-mode-toggle";
  toggle.type = "button";
  // Stable accessible name; state is conveyed by aria-pressed + the on-colour, per the ARIA
  // toggle-button pattern (a name that flips to "Present" would read "Present, pressed").
  toggle.textContent = "Comment mode";
  toggle.setAttribute("aria-pressed", "false");
  toggle.addEventListener("click", () => { setCommentMode(!commentMode); toggle.blur(); });
  document.body.prepend(toggle);

  const nav = document.createElement("div");
  nav.className = "cm-skip cmh-deck-nav";
  const prev = document.createElement("button");
  prev.type = "button"; prev.textContent = "Prev"; prev.setAttribute("aria-label", "Prev slide");
  prev.addEventListener("click", () => { show(current - 1); prev.blur(); });
  prevBtn = prev;
  counter = document.createElement("span");
  counter.className = "cmh-deck-count";
  counter.setAttribute("aria-live", "polite");
  counter.textContent = (current + 1) + " / " + slides.length;
  counter.setAttribute("aria-label", "Slide " + (current + 1) + " of " + slides.length);
  const next = document.createElement("button");
  next.type = "button"; next.textContent = "Next"; next.setAttribute("aria-label", "Next slide");
  next.addEventListener("click", () => { show(current + 1); next.blur(); });
  nextBtn = next;
  prev.disabled = current === 0;
  next.disabled = current === slides.length - 1;
  nav.appendChild(prev); nav.appendChild(counter); nav.appendChild(next);
  // Focus order: the toggle sits at the top of the DOM (top-right visually), the nav bar at the
  // end (bottom visually), so keyboard focus flows toggle -> slide content -> navigation.
  document.body.appendChild(nav);
}
if (IS_DECK) {
  setupDeck();
} else {
  setupHeadingAnchors();
  setupCollapsibleSections();
  setupSideToc();
  setupFooter();
  setupScrollProgress();
}
setupTooltips();
// Capture the layer chrome injected above while the host content that follows the layer
// <script> is still unparsed, so an export tail can exclude it (see _snapshotWithTail).
for (let cur = CMH_LAYER_SCRIPT; cur && cur.parentNode; cur = cur.parentNode) {
  for (let s = cur.nextSibling; s; s = s.nextSibling) {
    if (s.nodeType === 1) CMH_INJECTED_CHROME.add(s);
  }
  if (cur.parentNode === document.body) break;
}
renderComments();
if (prunedCount > 0) {
  showToast(`${prunedCount} previously-handled comment${prunedCount === 1 ? "" : "s"} cleared by the agent.`);
}
if (comments.length || (typeof checklistChanges === "function" && checklistChanges().length)) openSidebar();
else closeSidebar();
// Signals the nonportable-mode bootstrap that the external runtime initialized, so
// the missing-companion-assets banner stays hidden.
window.__commentableHtmlReady = true;
window.__commentableHtmlVersion = CMH_VERSION;
})();
