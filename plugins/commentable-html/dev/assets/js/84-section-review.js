/* ---------- Section review tracking ---------- */
// Mark a document section (any h1-h6 inside #commentRoot) reviewed. A cm-skip badge to the
// right of the heading text shows one of four states, recomputed on every render from the
// stored marker plus the live DOM (never baked as a static label):
//   commented  - one or more OPEN comments are anchored in the section (overlay, highest
//                precedence; reverts to the underlying state when the comments clear)
//   unreviewed - no marker
//   changed    - a marker exists but the section content hash no longer matches
//   reviewed   - a marker exists and the hash matches
// Markers live in a dedicated store (localStorage COMMENT_KEY::reviews + an embedded
// reviewedSections JSON block), separate from comments, so they never enter the
// Copy-all bundle yet still survive Shareable/Offline export. It is runtime-only chrome:
// the badge/button are cm-skip and never enter a Plain/standalone snapshot or shift offsets.
const REVIEW_KEY = COMMENT_KEY + "::reviews";
const REVIEW_WS_RE = /[ \t\n\r\f\v\u00a0]+/g;
const SAFE_HASH_RE = /^[0-9a-z]{1,16}$/;
let reviewMarkers = {};
let _cmReviewFilter = "all";
let _reviewReady = false;

// Deterministic FNV-1a (32-bit) over the section text, whitespace-collapsed. Kept simple and
// non-crypto so the Python helper (tools/authoring/section_hash.py) reproduces it byte for byte
// - the JS and Python hashers are pinned equal by tests/test_section_hash_golden.py. The char
// codes are UTF-16 code units (String.charCodeAt), which the Python side mirrors via utf-16-le.
function cmhSectionHash(text) {
  const s = String(text == null ? "" : text).replace(REVIEW_WS_RE, " ").replace(/^ | $/g, "");
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(36);
}

// Walk #commentRoot once (skipping every cm-skip subtree, so the review badge, section caret,
// and any injected chrome are excluded) and return the concatenated text plus each heading with
// its element and text offset. Both the hash range and the section boundaries derive from this.
function _cmhScanSections() {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
    acceptNode(n) {
      if (n.nodeType === 1) {
        // Exclude cm-skip chrome, script/style/template inert text, AND runtime-transformed blocks
        // (rendered diffs, KQL, mermaid, chart canvases, editable notes) whose text the runtime
        // rewrites at load - so the hash covers the section's STABLE prose and matches the Python
        // extractor (section_hash.py) for every content type, not just plain prose.
        if (n.closest(".cm-skip, script, style, template, noscript, .cmh-diff, .cmh-kql, .mermaid, canvas, [data-cmh-note]")) return NodeFilter.FILTER_REJECT;
        return /^H[1-6]$/i.test(n.tagName) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
      }
      if (n.parentElement && n.parentElement.closest(".cm-skip, script, style, template, noscript, .cmh-diff, .cmh-kql, .mermaid, canvas, [data-cmh-note]")) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  let full = "", total = 0;
  const heads = [];
  let n;
  while ((n = walker.nextNode())) {
    if (n.nodeType === 1) { heads.push({ el: n, level: parseInt(n.tagName.slice(1), 10), offset: total }); }
    else { full += n.nodeValue; total += n.nodeValue.length; }
  }
  return { full, heads };
}
// End offset of a section: the next heading whose level is the same or higher (<=), else EOF.
function _cmhSectionEnd(heads, i, fullLen) {
  for (let j = i + 1; j < heads.length; j++) {
    if (heads[j].level <= heads[i].level) return heads[j].offset;
  }
  return fullLen;
}
function _cmhHashForHeadingEl(el, scan) {
  scan = scan || _cmhScanSections();
  const i = scan.heads.findIndex(function (h) { return h.el === el; });
  if (i < 0) return cmhSectionHash("");
  const end = _cmhSectionEnd(scan.heads, i, scan.full.length);
  return cmhSectionHash(scan.full.slice(scan.heads[i].offset, end));
}

// Whole-document content signature: the entire content-root text (the same cm-skip / script /
// style / template / noscript / diff / KQL / mermaid / canvas / note-excluded text the section
// hashes derive from) hashed once. The validation banner (38-validation-banner.js) compares it to
// the stamped commentable-html-validated-hash to tell a genuinely validated document from one that
// was validated and THEN manually edited. The Python side (tools/authoring/section_hash.py
// document_content_hash, written by doc_stamp when validate/finalize stamp) reproduces this byte
// for byte, so the two agree (pinned by tests/64-validation-banner.spec.js end to end).
//
// It hashes the CANONICAL (authored source-order) content: a reader's PERSISTED table sort is a
// runtime-only DOM reorder that the stamp (hashed from the source file) never saw, so source row
// order is temporarily restored before hashing and the sorted view re-applied afterwards (mirrors
// the export canonicalizer in 62-sortable-tables.js). Without this a merely sorted-but-unedited
// document would falsely raise the "not validated" banner on reload.
//
// Only TABLE SORT (a pure view of the same rows) is canonicalized. A draggable-widget/triage-board
// rearrangement is deliberately NOT: moving a card changes the board's meaning (the arrangement IS
// the content), so it legitimately re-stamps/invalidates. It is also not a live-reload
// false-positive - widget moves are not persisted to localStorage (they reset on reload), only
// baked into an explicit Shareable/Offline export, and re-validating that export re-stamps it.
function cmhDocContentHash() {
  const canSort = typeof _tableSortState !== "undefined" && _tableSortState
    && Object.keys(_tableSortState).length > 0
    && typeof _sortableTables === "function" && typeof _unsortRows === "function"
    && typeof _sortRows === "function" && typeof _tableBody === "function"
    && typeof _tableKey === "function";
  if (!canSort) return cmhSectionHash(_cmhScanSections().full);
  const saved = JSON.parse(JSON.stringify(_tableSortState));
  _sortableTables().forEach(function (t) { _unsortRows(_tableBody(t)); });
  try {
    return cmhSectionHash(_cmhScanSections().full);
  } finally {
    // Always restore the reader's sorted view, even if hashing threw, so a transient hash never
    // leaves the visible table order corrupted.
    _sortableTables().forEach(function (t, i) {
      const st = saved[_tableKey(t, i)];
      if (st) _sortRows(_tableBody(t), st.col, st.dir);
    });
  }
}

function _cmhReviewHeadings() {
  return Array.prototype.filter.call(
    root.querySelectorAll("h1, h2, h3, h4, h5, h6"),
    function (h) { return !h.closest(".cm-skip"); });
}
function _cmhAnchorElFor(c) {
  if (!c) return null;
  if (!c.anchorType) return root.querySelector('mark.cm-hl[data-cid="' + c.id + '"]');
  if (c.anchorType === "mermaid" && typeof findMermaidNode === "function") return findMermaidNode(c.diagramIndex, c.nodeKey);
  if (c.anchorType === "diff" && typeof findDiffLineEls === "function") return (findDiffLineEls(c.diffIndex, c.lineKey) || [])[0] || null;
  if (c.anchorType === "image" && typeof resolveImageEl === "function") return resolveImageEl(c);
  if (c.anchorType === "link" && typeof resolveLinkEl === "function") return resolveLinkEl(c);
  if (c.anchorType === "widget" && typeof findWidgetPart === "function") return findWidgetPart(c.widget, c.part);
  return null; // document-wide comments belong to no section
}
function _elBefore(a, b) {
  return !!(a && b && (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
}
// The set of headings (by element) that have at least one OPEN comment anchored inside their
// section span. A comment inside a nested subsection also counts for every ancestor section that
// contains it, so both the h2 and the h3 light up Commented. Handled comments are already pruned
// from `comments` at load, so every entry here is an open comment.
function _cmhCommentedHeadings(heads) {
  const set = new Set();
  const anchors = [];
  for (const c of comments) {
    const el = _cmhAnchorElFor(c);
    if (el) anchors.push(el);
  }
  if (!anchors.length) return set;
  for (let i = 0; i < heads.length; i++) {
    const startEl = heads[i].el;
    let endEl = null;
    for (let j = i + 1; j < heads.length; j++) {
      if (heads[j].level <= heads[i].level) { endEl = heads[j].el; break; }
    }
    for (const a of anchors) {
      if (_elBefore(startEl, a) && (!endEl || _elBefore(a, endEl))) { set.add(startEl); break; }
    }
  }
  return set;
}

// Compute the state of every reviewable heading in one pass (shared scan + commented set),
// returning a Map(headingEl -> {state, hash}). `state` is one of the four names above.
function computeSectionStates() {
  const scan = _cmhScanSections();
  const commented = _cmhCommentedHeadings(scan.heads);
  const out = new Map();
  for (let i = 0; i < scan.heads.length; i++) {
    const h = scan.heads[i];
    const end = _cmhSectionEnd(scan.heads, i, scan.full.length);
    const hash = cmhSectionHash(scan.full.slice(h.offset, end));
    const marker = h.el.id ? reviewMarkers[h.el.id] : null;
    let state;
    if (commented.has(h.el)) state = "commented";
    else if (!marker) state = "unreviewed";
    else if (marker.hash !== hash) state = "changed";
    else state = "reviewed";
    out.set(h.el, { state, hash });
  }
  return out;
}

/* ----- persistence ----- */
// Review state is user data, so the block it lives in is resolved by the region that OWNS it, never
// by getElementById() (which binds the FIRST match in document order). A decoy element carrying the
// same id ahead of the real one - in a hand-authored file, or after a botched edit - would otherwise
// be read on load and written on export, while the region-owned block silently kept its stale
// contents. validate.py rejects the duplicate id; this keeps the runtime correct on a document that
// never met the validator.
const REVIEW_BLOCK_ID = "reviewedSections";
const REVIEW_REGION = "EMBEDDED COMMENTS";
function _cmhRegionCommentRe(kind, name) {
  return new RegExp("^[ \\t]*(?:=+[ \\t]*)?" + kind + ": commentable-html - " + name + "[ \\t]*(?:=+[ \\t]*)?$", "m");
}
// Compiled once: the marker is a LINE inside the region's banner comment (which also carries prose),
// which is how the exporter's raw-text scan and the Python validator read it too.
const REVIEW_REGION_BEGIN_RE = _cmhRegionCommentRe("BEGIN", REVIEW_REGION);
const REVIEW_REGION_END_RE = _cmhRegionCommentRe("END", REVIEW_REGION);
// DOMParser parses with scripting DISABLED, so it sees <noscript> contents as real elements and
// comments while the live document keeps the same bytes as inert text. Skipping them keeps the
// export's view of a document identical to the reader's, so nothing can hide in a <noscript> and be
// written into (where it would turn back into text, losing the state, on the next open).
function _cmhInInertHost(node) {
  const el = node.nodeType === 1 ? node : node.parentElement;
  return !!(el && el.closest && el.closest("noscript"));
}
// Where the region called `name` begins and ends: `{state: "ok", begin, end}`, `"absent"` (the
// document carries no such marker at all - for example a file from before the regions existed), or
// `"malformed"` (markers exist but not as exactly one ordered pair, so nothing in the document can
// be attributed to the region and callers must refuse rather than guess).
function _cmhRegionCommentBounds(doc, name) {
  const beginRe = name === REVIEW_REGION ? REVIEW_REGION_BEGIN_RE : _cmhRegionCommentRe("BEGIN", name);
  const endRe = name === REVIEW_REGION ? REVIEW_REGION_END_RE : _cmhRegionCommentRe("END", name);
  const begins = [], ends = [];
  let walker;
  try { walker = doc.createTreeWalker(doc, NodeFilter.SHOW_COMMENT); } catch (e) { return { state: "malformed" }; }
  let node;
  while ((node = walker.nextNode())) {
    if (_cmhInInertHost(node)) continue;
    const data = node.data || "";
    if (beginRe.test(data)) begins.push(node);
    if (endRe.test(data)) ends.push(node);
  }
  if (!begins.length && !ends.length) return { state: "absent" };
  if (begins.length !== 1 || ends.length !== 1) return { state: "malformed" };
  if (!(begins[0].compareDocumentPosition(ends[0]) & Node.DOCUMENT_POSITION_FOLLOWING)) return { state: "malformed" };
  return { state: "ok", begin: begins[0], end: ends[0] };
}
function _cmhNodeInRegion(el, bounds) {
  return !!(bounds.begin.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)
    && !!(bounds.end.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_PRECEDING);
}
// Every SCRIPT carrying `id`, not just the first one getElementById would return. Restricting the
// lookup to scripts keeps the runtime exactly as wide as the validator's own shape check (which only
// ever accepts a <script>), so an element of another type carrying the id cannot become the block
// one of them reads while the other ignores it. `id` is always one of this file's own constants, so
// it needs no selector escaping.
function _cmhElementsWithId(doc, id) {
  return Array.prototype.slice.call(doc.querySelectorAll('script[id="' + id + '"]'))
    .filter(function (el) { return !_cmhInInertHost(el); });
}
// The element the region delimited by `bounds` owns for `id`, or null when it cannot be resolved
// unambiguously. A LONE match still resolves when the region markers are ABSENT (a document
// upgraded from before the feature existed keeps working); malformed markers and a duplicated id
// never resolve.
function _cmhOwnedById(doc, id, bounds) {
  const all = _cmhElementsWithId(doc, id);
  if (!all.length) return null;
  if (!bounds || bounds.state === "malformed") return null;
  if (bounds.state === "absent") return all.length === 1 ? all[0] : null;
  const owned = all.filter(function (el) { return _cmhNodeInRegion(el, bounds); });
  return owned.length === 1 ? owned[0] : null;
}
function _cmhOwnedStateBlock(doc, id) {
  return _cmhOwnedById(doc, id, _cmhRegionCommentBounds(doc, REVIEW_REGION));
}
// A null-prototype object so a heading id like "__proto__" or "constructor" becomes an ordinary
// own key instead of mutating a real prototype (which would silently drop that section's marker).
function _sanitizeMarkers(obj) {
  const clean = Object.create(null);
  if (!obj || typeof obj !== "object") return clean;
  Object.keys(obj).forEach(function (id) {
    const m = obj[id];
    if (!m || typeof m !== "object") return;
    if (typeof m.hash !== "string" || !SAFE_HASH_RE.test(m.hash)) return;
    clean[id] = {
      hash: m.hash,
      headingText: typeof m.headingText === "string" ? m.headingText : "",
      level: (typeof m.level === "number" && m.level >= 1 && m.level <= 6) ? m.level : 0,
      reviewedAt: typeof m.reviewedAt === "string" ? m.reviewedAt : "",
    };
  });
  return clean;
}
// A document whose reviewedSections block cannot be attributed to its region is reported ONCE, in
// the console and to the reader: every section shows as unreviewed on a file that plainly carries
// baked markers, and a reader who opened a shared HTML has no console to look at. The export path
// reports the same condition in its own download toast.
let _reviewBlockWarned = false;
function _cmhWarnUnownedReviewBlock() {
  if (_reviewBlockWarned) return;
  _reviewBlockWarned = true;
  const msg = "This file carries a " + REVIEW_BLOCK_ID + " block that its " + REVIEW_REGION
    + " region does not own (a duplicated id, a block outside the region, or broken region markers),"
    + " so its saved section-review marks are ignored. Run validate.py on the file.";
  try { console.warn("commentable-html: " + msg); } catch (e) { /* console is optional */ }
  if (typeof showToast === "function") showToast(msg, { alert: true, duration: 8000 });
}
function getEmbeddedReviewMarkers() {
  const el = _cmhOwnedStateBlock(document, REVIEW_BLOCK_ID);
  if (!el) {
    if (_cmhElementsWithId(document, REVIEW_BLOCK_ID).length) _cmhWarnUnownedReviewBlock();
    return Object.create(null);
  }
  try {
    const raw = JSON.parse((el.textContent || "").trim() || "{}");
    return _sanitizeMarkers(raw);
  } catch (e) { return Object.create(null); }
}
// Ids the reader explicitly UN-reviewed. On an exported doc the reviewedSections block is baked in,
// so a plain delete would resurrect on reload; a tombstone keeps a cleared baked marker cleared
// (mirrors the embedded-comment tombstone pattern in 05-persistence.js).
const REVIEW_DELETED_KEY = COMMENT_KEY + "::reviews::deleted";
function _deletedReviewIds() {
  try {
    const a = JSON.parse(localStorage.getItem(REVIEW_DELETED_KEY) || "[]");
    return new Set(Array.isArray(a) ? a.filter(function (id) { return typeof id === "string"; }) : []);
  } catch (e) { return new Set(); }
}
function _saveDeletedReviewIds(set) {
  return cmhTrySetItem(REVIEW_DELETED_KEY, function () { return JSON.stringify([...set]); }, "Review state");
}
function loadReviewMarkers() {
  let local = Object.create(null);
  try {
    const raw = localStorage.getItem(REVIEW_KEY);
    local = raw ? _sanitizeMarkers(JSON.parse(raw)) : Object.create(null);
  } catch (e) { local = Object.create(null); }
  const embedded = getEmbeddedReviewMarkers();
  // Drop any baked marker the reader tombstoned (explicitly cleared), so it does not resurrect.
  const tomb = _deletedReviewIds();
  tomb.forEach(function (id) { delete embedded[id]; });
  // localStorage wins over the baked block for the same heading id (the reader's latest action),
  // but a heading only present in the exported block is still picked up on a fresh browser.
  reviewMarkers = Object.assign(Object.create(null), embedded, local);
}
function saveReviewMarkers() {
  // The section-review callers below own the user-facing message (they add the "Manage storage"
  // action via cmhStorageAction), so this low-level writer does not toast - avoiding a double toast.
  return cmhTrySetItem(REVIEW_KEY, function () { return JSON.stringify(reviewMarkers); }, "Section review state");
}
// A heading's own text with cm-skip chrome (the injected badge/caret) removed, so the baked
// headingText matches the Python tool's value and is not polluted by "Mark reviewed" etc.
function _cmhHeadingText(heading) {
  const clone = heading.cloneNode(true);
  clone.querySelectorAll(".cm-skip, script, style, template").forEach(function (e) { e.remove(); });
  return (clone.textContent || "").trim().replace(REVIEW_WS_RE, " ").slice(0, 200);
}

/* ----- mark / unmark ----- */
function markSectionReviewed(heading) {
  if (!heading || !heading.id) return;
  reviewMarkers[heading.id] = {
    hash: _cmhHashForHeadingEl(heading),
    headingText: _cmhHeadingText(heading),
    level: parseInt(heading.tagName.slice(1), 10),
    reviewedAt: new Date().toISOString(),
  };
  // Re-reviewing lifts any prior tombstone for this id.
  const tomb = _deletedReviewIds();
  if (tomb.delete(heading.id)) _saveDeletedReviewIds(tomb);
  const savedOk = saveReviewMarkers();
  // A mark that could not be persisted would silently revert on reload; warn the reader (storage
  // full/blocked), matching clearSectionReviewed()'s un-review warning and saveComments()'s alert.
  if (!savedOk && typeof showToast === "function") {
    showToast("Could not persist reviewing this section (browser storage full or blocked) - it "
      + "may not stick on reload. Use Export as Shareable to keep the change.",
      { alert: true, duration: 8000, action: cmhStorageAction(REVIEW_KEY) });
  }
  refreshReviewUI();
}
function clearSectionReviewed(heading) {
  if (!heading || !heading.id) return;
  delete reviewMarkers[heading.id];
  // If the marker was baked into the document, tombstone it so a reload does not resurrect it.
  const embedded = getEmbeddedReviewMarkers();
  const wasBaked = Object.prototype.hasOwnProperty.call(embedded, heading.id);
  let tombOk = true;
  if (wasBaked) {
    const tomb = _deletedReviewIds();
    tomb.add(heading.id);
    tombOk = _saveDeletedReviewIds(tomb);
  }
  const savedOk = saveReviewMarkers();
  // A baked marker cleared without a durable tombstone/marker write would silently resurrect on
  // reload; warn the reader (storage full/blocked), matching saveComments()'s persistence alert.
  if (wasBaked && (!tombOk || !savedOk) && typeof showToast === "function") {
    showToast("Could not persist un-reviewing this section (browser storage full or blocked) - it "
      + "may come back on reload. Use Export as Shareable to keep the change.",
      { alert: true, duration: 8000, action: cmhStorageAction(REVIEW_DELETED_KEY) || cmhStorageAction(REVIEW_KEY) });
  }
  refreshReviewUI();
}
// The badge is the single control: a click marks an unreviewed section reviewed, clears a
// reviewed one, and RE-reviews a changed/commented one (one-click re-review, re-stamping the hash).
function _onReviewBadgeClick(heading, state) {
  if (state === "reviewed") clearSectionReviewed(heading);
  else markSectionReviewed(heading);
}

/* ----- badge rendering ----- */
const _REVIEW_LABELS = {
  unreviewed: "Mark reviewed",
  reviewed: "Reviewed",
  changed: "Changed - re-review",
  commented: "Commented",
};
function _ensureBadge(heading) {
  let badge = heading.querySelector(":scope > .cmh-review-badge");
  if (!badge) {
    badge = document.createElement("button");
    badge.type = "button";
    badge.className = "cmh-review-badge cm-skip";
    heading.appendChild(badge);
    badge.addEventListener("click", function (e) {
      e.stopPropagation();
      e.preventDefault();
      _onReviewBadgeClick(heading, badge.dataset.cmhState || "unreviewed");
    });
  }
  return badge;
}
function refreshReviewUI() {
  if (IS_DECK || !_reviewReady) return;
  const states = computeSectionStates();
  const active = _reviewActive(states);
  _cmhReviewHeadings().forEach(function (heading) {
    const info = states.get(heading) || { state: "unreviewed" };
    const badge = _ensureBadge(heading);
    badge.dataset.cmhState = info.state;
    badge.className = "cmh-review-badge cm-skip cmh-review-" + info.state;
    const label = _REVIEW_LABELS[info.state] || _REVIEW_LABELS.unreviewed;
    // Render the label via a CSS ::after (content: attr(data-cmh-label)) rather than a text node, so
    // the injected badge never pollutes heading.textContent (which the TOC, deep-link ids, and other
    // code read) - the same "text-free chrome inside a heading" rule the section caret follows.
    badge.dataset.cmhLabel = label;
    const action = info.state === "reviewed" ? "clear the reviewed mark"
      : info.state === "unreviewed" ? "mark this section reviewed"
      : "re-review this section";
    badge.setAttribute("aria-label", label + " - click to " + action);
    badge.title = badge.getAttribute("aria-label");
  });
  if (typeof updateTocReviewMarks === "function") updateTocReviewMarks(states, active);
  if (active && _cmReviewFilter !== "all" && typeof applyReviewFilter === "function") applyReviewFilter(_cmReviewFilter, states);
}

// The review UI stays dormant until the reviewer actually starts: it activates once the document has
// at least one comment OR at least one CURRENT section carries a non-unreviewed state (reviewed,
// changed, or commented). Deriving activation from the computed states - not the raw marker map -
// means a stale marker for a heading that no longer exists cannot leave the UI stuck active with no
// way to clear it. Until active, only the hover "Mark reviewed" affordance shows, so a first-time
// reader sees a clean, un-chromed document.
function _reviewActive(states) {
  if (typeof comments !== "undefined" && !!comments && comments.length > 0) return true;
  const map = states || computeSectionStates();
  for (const info of map.values()) {
    if (info && info.state !== "unreviewed") return true;
  }
  return false;
}

function setupSectionReview() {
  if (IS_DECK) return;
  loadReviewMarkers();
  _reviewReady = true;
  refreshReviewUI();
}

// Test/automation hook: expose the section hasher and a state reader so the Playwright golden
// (tests/90-section-review.spec.js) can pin the runtime hash to the shared JS/Python fixture and
// assert per-section state. cm-skip runtime chrome only; never used by the document itself.
if (typeof window !== "undefined") {
  window.__cmhReview = {
    hash: cmhSectionHash,
    markers: function () { return reviewMarkers; },
    refresh: function () { refreshReviewUI(); },
    active: function () { return _reviewReady && !IS_DECK ? _reviewActive() : false; },
    stateOf: function (id) {
      const el = document.getElementById(id);
      if (!el) return null;
      const info = computeSectionStates().get(el);
      return info ? info.state : null;
    },
    applyFilter: function (mode) { if (typeof applyReviewFilter === "function") applyReviewFilter(mode); },
    sectionHashOf: function (id) {
      const el = document.getElementById(id);
      return el ? _cmhHashForHeadingEl(el) : null;
    },
    docHash: function () { return cmhDocContentHash(); },
  };
}

// Bake the current markers into an exported file's reviewedSections block so a Shareable/Offline
// copy carries the review state (Plain export strips the whole EMBEDDED COMMENTS region, dropping
// this block with it). "<" is escaped as \u003c like the embedded-comments block. The document is
// round-tripped through DOMParser (not a string regex) so the reviewedSections id is matched only
// as a real DOM element, never as tag text that appears inside the inlined layer JS (a self-
// contained Shareable/Offline copy inlines this runtime, whose comments mention the block by name),
// and the element written is the one the EMBEDDED COMMENTS region owns, never the first id match.
// Returns {html, note}: when nothing can be attributed to the region the state is left out rather
// than written to a guess, and `note` says why. showToast REPLACES the visible message, so the
// caller (which owns the single "Downloaded ..." toast) appends the note to it rather than this
// raising a toast of its own that the download toast would immediately wipe. The note travels with
// the call, not in module state, so a concurrent or failed export cannot lose or inherit it.
function _applyReviewStateToHtml(html) {
  const src = String(html || "");
  const kept = { html: html, note: "" };
  const markers = _sanitizeMarkers(reviewMarkers);
  // Bake only markers whose heading still exists in the current document, so a stale marker for a
  // deleted section cannot leak its old headingText/reviewedAt/hash into a shared Shareable/Offline
  // copy. Orphan markers already cannot activate the UI (see _reviewActive); this keeps them out of
  // the exported artifact as well.
  const present = Object.create(null);
  _cmhReviewHeadings().forEach(function (h) { if (h && h.id) present[h.id] = true; });
  const live = Object.create(null);
  Object.keys(markers).forEach(function (id) { if (present[id]) live[id] = markers[id]; });
  const json = JSON.stringify(live, null, 2).replace(/</g, "\\u003c");
  let doc;
  try { doc = new DOMParser().parseFromString(src, "text/html"); } catch (e) { return kept; }
  if (!doc || !doc.documentElement) return kept;
  const bounds = _cmhRegionCommentBounds(doc, REVIEW_REGION);
  let block = _cmhOwnedById(doc, REVIEW_BLOCK_ID, bounds);
  if (block && String(block.textContent || "").trim() === json.trim()) return kept;
  if (!block) {
    // A block carries the id but no single one can be attributed to the EMBEDDED COMMENTS region:
    // writing would overwrite a decoy and leave the real block stale, and inserting would add a
    // THIRD contender. Decline, and hand the reason to the caller's download toast - the reader's
    // markers stay in localStorage, they just do not travel with this copy.
    const carriers = _cmhElementsWithId(doc, REVIEW_BLOCK_ID).length;
    if (carriers) {
      const lead = " Section-review state was left out: this file ";
      if (carriers > 1) kept.note = lead + "carries " + carriers + " " + REVIEW_BLOCK_ID + " blocks.";
      else if (bounds.state === "malformed") kept.note = lead + "does not have exactly one ordered pair of "
        + REVIEW_REGION + " region markers.";
      else kept.note = lead + "keeps its " + REVIEW_BLOCK_ID + " block outside its " + REVIEW_REGION + " region.";
      kept.note += " Run validate.py.";
      return kept;
    }
    // No block at all (an older document): insert one right after the region-owned embeddedComments
    // block so it sits inside the EMBEDDED COMMENTS region and Plain export strips it for free. A
    // document that carries MORE than one embeddedComments block is refused rather than anchored on
    // a guess: the comments themselves are rewritten into the FIRST such block (65-export-shareable),
    // so anchoring elsewhere would split the state of one file across two blocks.
    const ec = _cmhElementsWithId(doc, "embeddedComments").length === 1
      ? _cmhOwnedById(doc, "embeddedComments", bounds) : null;
    if (!ec || !ec.parentNode) {
      kept.note = " Section-review state was left out: this file has no " + REVIEW_BLOCK_ID
        + " block and no single embeddedComments block inside its " + REVIEW_REGION
        + " region to put one after. Run validate.py.";
      return kept;
    }
    block = doc.createElement("script");
    block.setAttribute("type", "application/json");
    block.id = REVIEW_BLOCK_ID;
    ec.parentNode.insertBefore(block, ec.nextSibling);
  }
  block.textContent = json;
  const doctype = /^\s*<!doctype/i.test(src) ? "<!DOCTYPE html>\n" : "";
  return { html: doctype + doc.documentElement.outerHTML, note: "" };
}
