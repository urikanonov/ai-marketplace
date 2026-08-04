/* ---------- Config (auto-discovered, never edit per-doc) ---------- */
const root = document.getElementById("commentRoot") || document.body;
// The layer's own data blocks - the CMH-FWDCOMPAT-01 descriptor and the embedded-comments,
// handled-ids and reviewed-sections blocks - are INFRASTRUCTURE: they live OUTSIDE the content
// root. An element inside the content root that borrows one of those reserved ids is authored
// CONTENT and is never the layer's block, so resolving one by document POSITION
// (`getElementById`, or the first match in the source text) lets a decoy displace it. Resolve
// against the boundary instead, and do it on the READ side and the WRITE side alike: an exporter
// that scoped only its writes would update the real block while the runtime still read the decoy
// back, which is worse than agreeing on the wrong one.
//
// The boundary has three states, and the difference matters:
//   unique    - exactly one content root; the ordinary case.
//   none      - the document never delimited a content region, so nothing is inside one and the
//               plain tree-order answer stands (this is not a weakening: there is no untrusted
//               region to be outside OF).
//   contested - more than one element claims the id. A duplicate id is legal HTML and
//               `getElementById` silently takes the first, so a wrapper planted around the genuine
//               root would re-point the boundary and hand the win straight back to a decoy. There
//               is no safe answer, so resolve NOTHING: an export refuses loudly and a reader
//               admits no block, rather than falling back to the position rule this boundary
//               exists to replace.
function cmhContentRootState(doc) {
  const d = doc || document;
  const roots = Array.prototype.filter.call(d.querySelectorAll("#commentRoot"), function (node) {
    // Same one-scripting-model rule as cmhLayerIdOwners: a root parked in a `<noscript>` exists
    // only in a scripting-disabled parse, so counting it would let an inert block contest a
    // boundary the live runtime never sees contested.
    return !(node.closest && node.closest("noscript"));
  });
  if (roots.length > 1) return { contested: true, root: null };
  return { contested: false, root: roots.length === 1 ? roots[0] : null };
}
function cmhContentRoot(doc) {
  return cmhContentRootState(doc).root;
}
// Every element owning `id`, in tree order, with the boundary NOT applied. The id is compared as
// an ATTRIBUTE VALUE rather than written as an id-selector literal: this source is inlined
// verbatim into every self-contained export, and a literal would make an exported file look like
// it still carries such a block to anything scanning its text.
//
// `<noscript>` descendants are excluded so one scripting model answers everywhere. The layer only
// runs with scripting ENABLED, where a `<noscript>` body is text and holds no elements at all -
// but the standalone parse an export runs over a document STRING has scripting disabled and does
// build them. Counting them would let one inert `<noscript>` block in a document make the export
// disagree with the very runtime that will read the file back.
function cmhLayerIdOwners(doc, id) {
  const d = doc || document;
  return Array.prototype.filter.call(d.querySelectorAll("[id]"), function (node) {
    return node.getAttribute("id") === id && !(node.closest && node.closest("noscript"));
  });
}
// The owners the boundary accepts as the layer's own, in tree order.
function cmhLayerBlocks(doc, id) {
  const d = doc || document;
  const state = cmhContentRootState(d);
  if (state.contested) return [];
  return cmhLayerIdOwners(d, id).filter(function (node) {
    return !(state.root && state.root.contains(node));
  });
}
function cmhLayerBlock(doc, id) {
  const blocks = cmhLayerBlocks(doc, id);
  return blocks.length ? blocks[0] : null;
}
// Say WHY a reserved block resolved to nothing while elements carrying its id exist, once per id.
// Plain absence is normal (a document with no comments yet), but "the block is there and the layer
// ignored it" is a document-shape problem the reader would otherwise experience as review state
// that silently vanished. The exports fail loudly for the same two states; this is the load-time
// half of that diagnosis.
const _CMH_WARNED_BLOCKS = Object.create(null);
function cmhWarnUnresolvedBlock(id) {
  if (_CMH_WARNED_BLOCKS[id]) return;
  const owners = cmhLayerIdOwners(document, id);
  if (!owners.length) return;
  _CMH_WARNED_BLOCKS[id] = true;
  console.warn("commentable-html: ignoring " + owners.length + " element(s) carrying the reserved id "
    + id + " - " + (cmhContentRootState(document).contested
      ? "this document has more than one element with the content-root id, so the layer cannot tell its own blocks from authored content."
      : "they are inside the content root, where authored content lives. Move the block above the content root."));
}
// The other half of that diagnosis: a document carrying MORE THAN ONE block the layer owns for a
// reserved DATA id. The reader reads the first (cmhLayerBlock) and the embedded-comments export
// rewrites that same first one, so the others are stale on load and never updated on save - comment
// data that is half ignored, silently and forever. Reading the first still WORKS (refusing would
// strand the reader's comments and block the export that would save them), so this is a report, not
// a refusal. validate.py rejects the duplicate id outright; this is the runtime half, for a file
// that never met the validator, and the reader is told because someone opening a shared HTML has no
// console. The reader's half is DEFERRED and AGGREGATED into one message: there is a single #toast
// and each call replaces the last, so reporting per id inside startup would have the second id wipe
// the first (and a later startup toast wipe them both).
const _CMH_AMBIGUOUS_BLOCKS = [];
let _cmhAmbiguousFlushQueued = false;
function cmhWarnAmbiguousBlock(id, count) {
  if (_CMH_WARNED_BLOCKS[id]) return;
  _CMH_WARNED_BLOCKS[id] = true;
  try {
    console.warn("commentable-html: this file carries " + count + " " + id + " blocks outside its"
      + " content root; only the first is read, and the rest are ignored.");
  } catch (e) { /* console is optional */ }
  _CMH_AMBIGUOUS_BLOCKS.push(count + " " + id);
  if (_cmhAmbiguousFlushQueued) return;
  _cmhAmbiguousFlushQueued = true;
  setTimeout(function () {
    _cmhAmbiguousFlushQueued = false;
    // Consume the queue, so a later id reports itself rather than re-listing what was shown.
    const found = _CMH_AMBIGUOUS_BLOCKS.splice(0, _CMH_AMBIGUOUS_BLOCKS.length);
    if (typeof showToast !== "function" || !found.length) return;
    // A damaged document is exactly the population this warning targets, and its COMMENT UI region
    // (where the toast element lives) may be part of the damage - so never let the report itself
    // throw out of the timer.
    try {
      showToast("This file carries duplicate commentable-html data blocks outside its content root ("
        + found.join(", ") + "). Only the first of each is read, so the rest are ignored - and the"
        + " comments block the export rewrites is that same first one. Run validate.py on the file.",
      { alert: true, duration: 10000 });
    } catch (e) { /* no toast surface on a damaged document; the console half already reported */ }
  }, 0);
}
// The ids the layer has READ through cmhReadLayerBlock, so they can be asked again once the whole
// document exists.
const _CMH_READ_BLOCK_IDS = [];
// A block that sits AFTER the layer's own script had not been parsed yet when the read happened, so
// the read-time count cannot see it. Ask again once the parser is done, or a duplicate placed in the
// document's tail would be exactly the silent state this rule exists to close.
function _cmhAuditReadBlocks() {
  _CMH_READ_BLOCK_IDS.forEach(function (id) {
    const blocks = cmhLayerBlocks(document, id);
    if (blocks.length > 1) cmhWarnAmbiguousBlock(id, blocks.length);
  });
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", _cmhAuditReadBlocks, { once: true });
} else {
  setTimeout(_cmhAuditReadBlocks, 0);
}
// The block the layer READS for a reserved data id, with both states a reader must be told about
// diagnosed in one place, so no data block can resolve to nothing (or to one of several) in
// silence. The descriptor deliberately does NOT come through here: an export that declares a mode
// maintains additional descriptor copies on purpose (CMH-EXP-18), so more than one is not a fault.
function cmhReadLayerBlock(id) {
  if (_CMH_READ_BLOCK_IDS.indexOf(id) === -1) _CMH_READ_BLOCK_IDS.push(id);
  const blocks = cmhLayerBlocks(document, id);
  if (!blocks.length) { cmhWarnUnresolvedBlock(id); return null; }
  if (blocks.length > 1) cmhWarnAmbiguousBlock(id, blocks.length);
  return blocks[0];
}
function _docSourceBasename(source) {
  const value = String(source == null ? "" : source);
  const withoutSuffix = /^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(value)
    ? value.split(/[?#]/, 1)[0] : value;
  if (/[\\/]$/.test(withoutSuffix)) return "document";
  const parts = withoutSuffix.split(/[\\/]/);
  return (parts[parts.length - 1] || "document").replace(/^[A-Za-z]:/, "") || "document";
}
const COMMENT_KEY = root.dataset.commentKey || ("commentable-html:" + location.pathname);
const DOC_LABEL   = root.dataset.docLabel   || document.title || location.pathname;
const DOC_SOURCE  = _docSourceBasename(root.dataset.docSource || location.pathname);
// Deck profile: a commentable-native slide deck (see references/deck-contract.md). When
// active, the layer replaces the flow-document chrome (heading anchors, collapsible
// sections, side TOC, footer, scroll progress) with slide navigation and commenting.
const IS_DECK = !!(root.getAttribute && root.getAttribute("data-cmh-mode") === "deck");
const CMH_DENSITY = root.dataset.cmDensity || "";
if (CMH_DENSITY === "compact" || CMH_DENSITY === "comfortable") {
  document.body.setAttribute("data-cm-density", CMH_DENSITY);
} else {
  document.body.removeAttribute("data-cm-density");
}
const SIDEBAR_WIDTH_KEY = "commentable-html::sidebarWidth";
// "Auto-open panel on comment": the cross-document DEFAULT (ON when unset, so an existing document
// behaves exactly as it always has) plus an optional per-document override that pins one document
// to its own value. See 06-preferences.js for the accessors. The default key deliberately does NOT
// end in the per-document suffix below: a document whose data-comment-key is literally
// "commentable-html" would otherwise own the cross-document key and reset every other document.
const AUTO_OPEN_PANEL_KEY = "commentable-html::autoOpenPanelDefault";
const AUTO_OPEN_PANEL_DOC_KEY = COMMENT_KEY + "::autoOpenPanel";
// The comment array is persisted in a modern slot COMMENT_KEY + "::z" holding either a compressed
// (framed) payload or plain JSON, whichever is smaller (see 05-persistence.js). COMMENT_KEY itself
// is only READ, as a legacy fallback for files last saved before this slot existed; the modern
// runtime never writes it, so an older runtime opening the same key can never clobber ::z.
const CMH_STORE_KEY = COMMENT_KEY + "::z";
// Frame marker for a compressed comment payload. "\u0001" is < 32, so it can never collide with
// lz-string's compressToUTF16 output (all chars >= 32) or legacy plain JSON (which starts with "[").
const CMH_STORE_FRAME = "\u0001z";
// Upper bound on decoded characters accepted from a stored/compressed comment payload (a
// decompression-bomb guard). Far beyond any real document; a value over this is treated as corrupt.
const CMH_MAX_STORE_CHARS = 8000000;
// Every per-document subkey suffix (EXACT strings). The storage manager (57-storage-manager.js) uses
// this single list to compute a document's owned keys and reclaim its space; a new per-document
// subkey MUST be added here (test_storage.py asserts every COMMENT_KEY + "::" writer suffix is listed).
const CMH_SUBKEY_SUFFIXES = [
  "::z", "::deleted", "::diffLayout", "::diffSyntax", "::cl", "::note",
  "::commentSort", "::tableSort", "::reviews", "::reviews::deleted", "::deckMode",
  "::autoOpenPanel",
];
// Shared registry index of every commentable-html document seen in this browser (best-effort
// presentation metadata only - the storage manager's delete authority is the owned-key shape, never
// this index). Maps a document's COMMENT_KEY to {label, source}.
const CMH_INDEX_KEY = "commentable-html::index";
// Comment ids are generated as "c" + base36 timestamp + 4 base36 chars and are
// later interpolated into HTML attributes (data-cid="...") and CSS selectors.
// Loaded and embedded comment ids must match this format - otherwise a
// malformed id could break out of an attribute or poison a selector.
const SAFE_ID_RE = /^c[a-z0-9]{6,63}$/;

// Version of this runtime, stamped from dev/VERSION by build.py. Do not hand-edit;
// bump dev/VERSION and rebuild.
const CMH_VERSION = "1.663.0";
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
// sidebar action-button icons (Shareable/Plain/Clear) are authored inline in
// template.shell.html and are intentionally not duplicated here.
const _CM_ICONS = {
  expand:   "M8 9l4-4 4 4 M8 15l4 4 4-4",
  collapse: "M8 5l4 4 4-4 M8 19l4-4 4 4",
  top:      "M12 19V6 M6 11l6-6 6 6",
  bottom:   "M12 5v13 M6 13l6 6 6-6",
  search:   "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M20 20l-3.5-3.5",
  clipboard: "M8 6h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z M9 6V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1",
};
function _cmIco(name, size) {
  const d = _CM_ICONS[name];
  if (!d) return "";
  const s = size || 14;
  return '<svg class="cm-ui-ico" viewBox="0 0 24 24" width="' + s + '" height="' + s
    + '" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="2"'
    + ' stroke-linecap="round" stroke-linejoin="round"><path d="' + d + '"/></svg>';
}
// In nonshareable mode the page loads an external commentable-html.assets.js
// that defines window.__COMMENTABLE_ASSETS__ = { version, css, js } - the string
// payloads used to rebuild a fully self-contained file for "Export standalone".
// A separate assets file (never the runtime embedding its own source) avoids any
// self-referential embedding loop. It is absent in inline/standalone documents.
const CMH_ASSETS = (typeof window !== "undefined" && window.__COMMENTABLE_ASSETS__) || null;
// NonShareable = the layer's CSS/JS live in companion files next to this HTML. Detected
// by the presence of the assets registry OR an external commentable-html script.
const NONSHAREABLE_MODE = !!CMH_ASSETS
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


