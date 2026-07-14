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

