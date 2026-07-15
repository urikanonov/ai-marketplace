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
const CMH_VERSION = "1.80.0";
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

