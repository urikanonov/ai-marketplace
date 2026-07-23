/* ---------- Storage manager (cross-document localStorage) ---------- */
// On file:// every commentable-html document shares one origin, so all documents' comments and
// review data compete for a single localStorage budget. This manager lists every document's stored
// data across the origin and lets the reviewer delete other documents' data to reclaim space; it
// also opens automatically when a comment save fails because storage is full.

const CMH_INDEX_MAX = 200;
const CMH_BANNER_PREFIX = "commentable-html::assetBannerDismissed::";
// Deletable keys in the commentable-html namespace that are NOT tied to one document (shared
// preferences). The shared registry index (CMH_INDEX_KEY) is deliberately EXCLUDED: it is internal
// ownership metadata, not a user preference, and deleting it would strand custom-key documents
// whose only ownership proof is the index (see CMH-STORE-10). It is skipped entirely in the grouping.
const CMH_GLOBAL_KEYS = [SIDEBAR_WIDTH_KEY, CMH_AUTHOR_KEY];

function _cmhReadIndex() {
  // A null-prototype map, with own properties copied from the parsed blob, so a document whose
  // custom data-comment-key is literally "__proto__"/"constructor"/etc. is stored and looked up as
  // an ordinary entry instead of mutating Object.prototype (registry values are same-origin data).
  const out = Object.create(null);
  try {
    const raw = localStorage.getItem(CMH_INDEX_KEY);
    const obj = raw ? JSON.parse(raw) : null;
    if (obj && typeof obj === "object" && !Array.isArray(obj)) {
      Object.keys(obj).forEach(function (k) { out[k] = obj[k]; });
    }
  } catch (e) { /* ignore corrupt/blocked index */ }
  return out;
}
function _cmhWriteIndex(idx) {
  try {
    let keys = Object.keys(idx);
    if (keys.length > CMH_INDEX_MAX) {
      // LRU-ish cap so the shared index cannot itself become a quota bomb: keep the most recently
      // touched entries (a numeric "t" is stored only for this eviction).
      keys.sort(function (a, b) { return (Number(idx[b] && idx[b].t) || 0) - (Number(idx[a] && idx[a].t) || 0); });
      // Null-prototype (like _cmhReadIndex) so a retained entry whose key is literally "__proto__"
      // is copied as an own property instead of mutating Object.prototype (which would drop it).
      const keep = Object.create(null);
      keys.slice(0, CMH_INDEX_MAX).forEach(function (k) { keep[k] = idx[k]; });
      idx = keep;
    }
    localStorage.setItem(CMH_INDEX_KEY, JSON.stringify(idx));
  } catch (e) { /* index is best-effort presentation metadata; ignore quota/blocked */ }
}
// Record the current document in the shared index (label + source) for the manager's listing. Only
// writes when the entry is missing or changed, to avoid rewriting the shared blob on every load.
function cmhRegisterDocument() {
  const label = String(DOC_LABEL || "").slice(0, 300);
  const source = String((root.dataset && root.dataset.docSource) || location.pathname || "").slice(0, 600);
  const idx = _cmhReadIndex();
  const prev = idx[COMMENT_KEY];
  if (prev && prev.label === label && prev.source === source) return;
  idx[COMMENT_KEY] = { label: label, source: source, t: Date.now() };
  _cmhWriteIndex(idx);
}
function _cmhRemoveIndexEntry(key) {
  const idx = _cmhReadIndex();
  if (Object.prototype.hasOwnProperty.call(idx, key)) { delete idx[key]; _cmhWriteIndex(idx); }
}

function _cmhKeyBytes(key, value) {
  return (key.length + (value == null ? 0 : value.length)) * 2; // localStorage stores UTF-16
}
function _cmhHumanSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}
// Assumed localStorage budget for a file:// document. Browsers typically allow ~5 MB and the exact
// limit varies, so the usage summary presents this as an approximate percentage, not a hard number.
const CMH_ASSUMED_QUOTA = 5 * 1024 * 1024;
function _cmhPct(part, whole) { return whole > 0 ? Math.round((part / whole) * 100) : 0; }
function _cmhAllKeys() {
  const out = [];
  try {
    for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k != null) out.push(k); }
  } catch (e) { /* blocked / private mode */ }
  return out;
}
// Longest-suffix-first so "::reviews::deleted" is matched before "::deleted"/"::reviews".
const _CMH_SUFFIXES_BY_LEN = CMH_SUBKEY_SUFFIXES.slice().sort(function (a, b) { return b.length - a.length; });
function _cmhBaseOf(key) {
  // Never suffix-split the current document's own key (a custom data-comment-key could itself end
  // in a known suffix, e.g. "foo::note"); it is always its own base.
  if (key === COMMENT_KEY) return { base: key, suffix: "" };
  for (const suf of _CMH_SUFFIXES_BY_LEN) {
    if (key.length > suf.length && key.slice(-suf.length) === suf) {
      return { base: key.slice(0, key.length - suf.length), suffix: suf };
    }
  }
  return { base: key, suffix: "" };
}
// True only when a stored value is (very likely) OUR comment store: a framed lz-string payload
// (only this runtime writes those), or a non-empty JSON array whose first item is a comment object
// with a SAFE_ID_RE id. A bare "[]" or an unrelated app's array does NOT qualify, so the manager
// never surfaces or deletes another application's same-origin data.
function _cmhLooksLikeCommentArray(raw) {
  if (raw == null) return false;
  const dec = cmhDecodeStore(raw);
  if (!dec.ok || dec.json == null) return false;
  if (raw.charCodeAt(0) === 1) return true; // framed -> our own compressed payload
  try {
    const a = JSON.parse(dec.json);
    return Array.isArray(a) && a.length > 0 && a[0] && typeof a[0] === "object"
      && typeof a[0].id === "string" && SAFE_ID_RE.test(a[0].id);
  } catch (e) { return false; }
}
// Best-effort comment count for a group (null = unknown/unreadable). Decode is bounded by
// cmhDecodeStore (CMH_MAX_STORE_CHARS), so this can never be a decompression-bomb vector.
function _cmhCountComments(g) {
  const raw = g._zValue != null ? g._zValue : g._baseValue;
  if (raw == null) return 0;
  const dec = cmhDecodeStore(raw);
  if (!dec.ok || dec.json == null) return null;
  try { const a = JSON.parse(dec.json); return Array.isArray(a) ? a.length : null; } catch (e) { return null; }
}
// A group is a deletable commentable-html document only with ownership PROOF: it is the current
// document, in the default "commentable-html:" namespace, present in OUR registry (which only ever
// records this runtime's own COMMENT_KEY, so a stale entry is still our doc), or its comment slot
// decodes to a real comment array. A bare foreign array or an unrelated app's key never qualifies.
// (A malicious same-origin document could forge the registry, but such a document can already
// removeItem any key directly, so this grants no new capability.)
function _cmhIsOwnedDoc(g, idx) {
  if (g.base === COMMENT_KEY) return true;
  if (g.base.indexOf("commentable-html:") === 0) return true;
  if (idx && Object.prototype.hasOwnProperty.call(idx, g.base)) return true;
  return _cmhLooksLikeCommentArray(g._zValue != null ? g._zValue : g._baseValue);
}
// Group every localStorage key into commentable-html documents (owned) + a global/other bucket.
function cmhStorageGroups() {
  const idx = _cmhReadIndex();
  const groups = new Map();
  const globals = [];
  const bannerKeys = [];
  function ensureGroup(base) {
    if (!groups.has(base)) groups.set(base, { base: base, keys: [], bytes: 0, _zValue: null, _baseValue: null });
    return groups.get(base);
  }
  // Always list the current document, even with nothing stored yet (so "This document" + Clear all
  // are reachable).
  ensureGroup(COMMENT_KEY);
  // Prototype-free membership test: a foreign same-origin key literally named "constructor",
  // "toString", "__proto__", etc. must NOT satisfy this via Object.prototype (a plain {} lookup
  // would, sweeping unrelated data into the deletable "shared data" bucket).
  const globalSet = new Set(CMH_GLOBAL_KEYS);
  // Known document bases (the registry + the current key) resolved LONGEST-first, so a subkey of a
  // custom key that itself ends in a reserved suffix (e.g. base "foo::note", subkey "foo::note::z")
  // is grouped under its real base rather than mis-split by the generic suffix matcher.
  const knownBases = Object.keys(idx).concat([COMMENT_KEY]).sort(function (a, b) { return b.length - a.length; });
  function baseOf(key) {
    for (const kb of knownBases) {
      if (key === kb) return { base: kb, suffix: "" };
      // Only a RECOGNIZED subkey suffix belongs to a known base - never an arbitrary "kb::*", so a
      // foreign key that merely shares the prefix (kb + "::" + something-unknown) is not swept in.
      for (const suf of _CMH_SUFFIXES_BY_LEN) {
        if (key === kb + suf) return { base: kb, suffix: suf };
      }
    }
    return _cmhBaseOf(key);
  }
  _cmhAllKeys().forEach(function (key) {
    // The shared registry index is internal ownership metadata - never a document and never a
    // deletable preference; skip it so it is neither listed nor removable (CMH-STORE-10).
    if (key === CMH_INDEX_KEY) return;
    let value = null;
    try { value = localStorage.getItem(key); } catch (e) { /* ignore */ }
    const bytes = _cmhKeyBytes(key, value);
    if (key.indexOf(CMH_BANNER_PREFIX) === 0) { bannerKeys.push({ key: key, bytes: bytes }); return; }
    if (globalSet.has(key)) { globals.push({ key: key, bytes: bytes }); return; }
    const split = baseOf(key);
    const g = ensureGroup(split.base);
    g.keys.push(key); g.bytes += bytes;
    if (split.suffix === "::z") g._zValue = value;
    else if (split.suffix === "") g._baseValue = value;
  });
  // Decide ownership, then attribute dismissed-banner keys to an owned document by EXACT base
  // segment (banner key = PREFIX + COMMENT_KEY + "::" + pageVer + "::" + runtimeVer), matching the
  // LONGEST owned base first so an overlapping base (k0 vs k0::x0) cannot steal the other's banner.
  const ownedBases = [];
  groups.forEach(function (g) { g._owned = _cmhIsOwnedDoc(g, idx); if (g._owned) ownedBases.push(g.base); });
  ownedBases.sort(function (a, b) { return b.length - a.length; });
  bannerKeys.forEach(function (bk) {
    let matched = null;
    for (const base of ownedBases) {
      if (bk.key.indexOf(CMH_BANNER_PREFIX + base + "::") === 0) { matched = base; break; }
    }
    if (matched) { const g = groups.get(matched); g.keys.push(bk.key); g.bytes += bk.bytes; }
    else globals.push({ key: bk.key, bytes: bk.bytes });
  });
  const docs = [];
  groups.forEach(function (g) {
    if (g._owned) {
      g.current = (g.base === COMMENT_KEY);
      const meta = idx[g.base] || {};
      g.label = meta.label || "";
      g.source = meta.source || "";
      g.count = _cmhCountComments(g);
      docs.push(g);
    } else {
      // Not a recognized document: only surface keys in the commentable-html namespace (the exact
      // "commentable-html:" prefix, so a foreign key like "commentable-html-app-state" is untouched).
      g.keys.forEach(function (k) {
        if (k.indexOf("commentable-html:") === 0) {
          let v = null; try { v = localStorage.getItem(k); } catch (e) { /* ignore */ }
          globals.push({ key: k, bytes: _cmhKeyBytes(k, v) });
        }
      });
    }
  });
  docs.sort(function (a, b) { return b.bytes - a.bytes; });
  return { docs: docs, globals: globals };
}
function _cmhDocDisplayName(g) {
  if (g.source) return _docSourceBasename(g.source);
  if (g.label) return g.label;
  const m = /(?:^|[\\/])([^\\/]+)$/.exec(g.base.replace(/^commentable-html:/, ""));
  return (m && m[1]) || g.base;
}
function _cmhDeleteKeys(keys) {
  let ok = true;
  keys.forEach(function (k) { try { localStorage.removeItem(k); } catch (e) { ok = false; } });
  return ok;
}

// Total bytes used by EVERY key in this origin's localStorage (commentable-html and foreign apps
// alike), for the usage summary. Bounded by the key count; it never decodes a value.
function _cmhOriginBytes() {
  let total = 0;
  _cmhAllKeys().forEach(function (k) {
    let v = null; try { v = localStorage.getItem(k); } catch (e) { /* ignore */ }
    total += _cmhKeyBytes(k, v);
  });
  return total;
}
// Storage-usage split for the summary: the whole origin, the commentable-html share (all documents
// plus shared/other CMH data), the non-CMH remainder, the current document, and the assumed budget.
function cmhStorageUsage() {
  const data = cmhStorageGroups();
  let cmhBytes = 0, currentBytes = 0;
  data.docs.forEach(function (g) { cmhBytes += g.bytes; if (g.current) currentBytes = g.bytes; });
  data.globals.forEach(function (x) { cmhBytes += x.bytes; });
  const originBytes = _cmhOriginBytes();
  return {
    originBytes: originBytes, cmhBytes: cmhBytes, otherBytes: Math.max(0, originBytes - cmhBytes),
    currentBytes: currentBytes, assumedQuota: CMH_ASSUMED_QUOTA,
  };
}
// The anchor text shown for one comment in the per-document browse list (a reply inherits its root's
// anchor, so it has none of its own). Every field is document-derived and rendered via textContent.
function _cmhCommentQuote(c) {
  if (!c) return "";
  if (c.parentId) return "(reply)";
  return c.imageAlt || c.linkText || c.nodeLabel || c.partLabel || c.quote || c.imageSrc || c.linkHref || "";
}
// Approximate per-comment footprint: the UTF-16 byte length of this comment's own JSON. The stored
// payload may be compressed, so this is an UNCOMPRESSED estimate (shown with a leading "~").
function _cmhCommentApproxBytes(c) {
  try { return JSON.stringify(c).length * 2; } catch (e) { return 0; }
}
// The comment array browsed for a group: the LIVE in-memory array for the current document (so a
// delete reflects at once and stays in sync with the sidebar), or the decoded stored array for any
// other document. Returns [] when the stored value is missing or unreadable.
function _cmhDocComments(g) {
  if (g.current) return Array.isArray(comments) ? comments.slice() : [];
  const raw = g._zValue != null ? g._zValue : g._baseValue;
  const dec = cmhDecodeStore(raw);
  if (!dec.ok || dec.json == null) return [];
  try { const a = JSON.parse(dec.json); return Array.isArray(a) ? a : []; } catch (e) { return []; }
}
// Delete one comment (and any replies pointing at it) from the CURRENT document through the live
// path: tombstone the embedded ids, drop from the in-memory array, remove highlights, persist, and
// re-render the sidebar - mirroring the sidebar's own delete so nothing resurrects on reload.
function _cmhDeleteCommentFromCurrent(id) {
  const dropIds = comments.filter(function (c) { return c && (c.id === id || c.parentId === id); })
    .map(function (c) { return c.id; });
  if (!dropIds.length) return;
  const tombstoneOk = _tombstoneEmbedded(dropIds);
  const drop = new Set(dropIds);
  dropIds.forEach(function (tid) { const oc = openEditComposers.get(tid); if (oc) closeComposerElement(oc); });
  const dropped = comments.filter(function (c) { return drop.has(c.id); });
  comments = comments.filter(function (c) { return !drop.has(c.id); });
  dropped.forEach(function (c) { try { removeHighlight(c); } catch (e) { /* anchor may already be gone */ } });
  const commentsOk = saveComments();
  _ensureTombstoneEmbedded(dropIds, tombstoneOk, commentsOk);
  if (typeof renderComments === "function") renderComments();
}
// Delete one comment (and any replies pointing at it) from ANOTHER document's stored slot: decode,
// filter, and re-encode to the modern ::z slot (or remove it when empty), clearing any legacy value.
// The removed ids are also tombstoned in that document's ::deleted set so a comment that was baked
// into its embedded block does not resurrect when it is next opened (we cannot read a foreign file's
// embedded signature from here, so every removed id is recorded; a non-embedded id is inert).
function _cmhDeleteCommentFromStore(base, id) {
  const zKey = base + "::z";
  let raw = null;
  try { raw = localStorage.getItem(zKey); } catch (e) { /* ignore */ }
  if (raw == null) { try { raw = localStorage.getItem(base); } catch (e) { /* ignore */ } }
  const dec = cmhDecodeStore(raw);
  if (!dec.ok || dec.json == null) return false;
  let arr;
  try { arr = JSON.parse(dec.json); } catch (e) { return false; }
  if (!Array.isArray(arr)) return false;
  const removedIds = arr.filter(function (c) { return c && (c.id === id || c.parentId === id); })
    .map(function (c) { return c.id; })
    .filter(function (x) { return typeof x === "string" && SAFE_ID_RE.test(x); });
  const next = arr.filter(function (c) { return c && c.id !== id && c.parentId !== id; });
  try {
    // Rewrite (or clear) the comment slot FIRST - a net space-freeing write - so the tiny tombstone
    // write below is far more likely to fit under quota pressure than if it ran first.
    if (next.length) localStorage.setItem(zKey, cmhEncodeStore(JSON.stringify(next)));
    else localStorage.removeItem(zKey);
    localStorage.removeItem(base); // never leave a stale legacy value behind
    _cmhTombstoneForeign(base, removedIds);
    return true;
  } catch (e) { return false; }
}
// Merge ids into another document's ::deleted tombstone set (SAFE_ID_RE-filtered, deduped, capped),
// mirroring 05-persistence.js's _tombstoneEmbedded but for a base other than the current document's.
function _cmhTombstoneForeign(base, ids) {
  if (!ids || !ids.length) return;
  const delKey = base + "::deleted";
  try {
    let existing = [];
    try { const v = JSON.parse(localStorage.getItem(delKey) || "[]"); existing = Array.isArray(v) ? v : []; } catch (e) { existing = []; }
    const cleanExisting = existing.filter(function (x) { return typeof x === "string" && SAFE_ID_RE.test(x); });
    // New ids FIRST so the cap can only ever evict OLD tombstones, never the just-deleted id.
    const merged = Array.from(new Set(ids.concat(cleanExisting))).slice(0, CMH_MAX_COMMENTS);
    localStorage.setItem(delKey, JSON.stringify(merged));
  } catch (e) { /* best-effort tombstone; ignore quota/blocked */ }
}

// ---------- Dialog ----------
let _cmhStorageOpen = false;
let _cmhQuotaEpisode = false; // guards against re-opening on every failed save within one episode
let _cmhConfirmSeq = 0; // unique-id counter for inline-confirm messages (aria-describedby)
// Re-arm the quota auto-open (called after any successful persistence), so a fresh full -> free ->
// full cycle re-opens the manager instead of the first episode blocking it forever.
function _cmhResetQuotaEpisode() { _cmhQuotaEpisode = false; }
function openStorageManager(opts) {
  opts = opts || {};
  if (_cmhStorageOpen) return false;
  const quota = opts.reason === "quota";
  if (quota && _cmhQuotaEpisode) return false;
  const prevFocus = opts.restoreFocus || document.activeElement;
  let _unregisterEscape = null;
  const overlay = document.createElement("div");
  overlay.className = "cm-modal-overlay cm-storage-overlay cm-skip";
  const box = document.createElement("div");
  box.className = "cm-modal cm-storage-manager";
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-label", "Manage storage");
  overlay.appendChild(box);
  document.body.appendChild(overlay);

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text; // ALWAYS textContent: labels/paths are untrusted
    return e;
  }

  function close() {
    document.removeEventListener("keydown", onKey, true);
    if (_unregisterEscape) { _unregisterEscape(); _unregisterEscape = null; }
    overlay.remove();
    _cmhStorageOpen = false;
    // The COMMENT quota episode is over once the comment slot's pending write is resolved; re-arm the
    // auto-open for the next full -> free -> full cycle.
    if (!_cmhPendingWrites.has(CMH_STORE_KEY)) _cmhQuotaEpisode = false;
    // If ANY write is still pending (the reviewer closed without freeing enough space), warn with the
    // recovery action so nothing unsaved - a comment OR a note/checklist/section-review edit that
    // routed the reviewer here via its own "Manage storage" toast - is lost silently on reload.
    // cmhRetryPendingWrites re-saves every pending key together, so one recovery action covers all.
    if (_cmhPendingWrites.size && typeof cmhStorageAction === "function") {
      let anyKey;
      _cmhPendingWrites.forEach(function (rec, key) { if (anyKey === undefined) anyKey = key; });
      const onlyComment = _cmhPendingWrites.size === 1 && _cmhPendingWrites.has(CMH_STORE_KEY);
      showToast((onlyComment ? "Your comment is" : "Your edits are")
        + " still not saved - this browser's storage is full. Free space from Manage storage, or use "
        + "Copy all / Export as Portable to keep it.",
        { alert: true, duration: 8000, action: cmhStorageAction(anyKey) });
    }
    if (prevFocus && typeof prevFocus.focus === "function") prevFocus.focus();
  }
  const popup = { isOpen: function () { return _cmhStorageOpen; }, close: close };
  if (window.__cmhRegisterEscapePopup) _unregisterEscape = window.__cmhRegisterEscapePopup(popup);
  if (window.__cmhPrioritizeEscapePopup) window.__cmhPrioritizeEscapePopup(popup);

  // Header
  const head = el("div", "cm-storage-head");
  const h2 = el("h2", null);
  h2.innerHTML = CMH_ICON_SVG; // trusted, static
  h2.appendChild(document.createTextNode(" Manage storage"));
  head.appendChild(h2);
  const closeBtn = el("button", "cm-storage-close", "\u00d7");
  closeBtn.type = "button";
  closeBtn.title = "Close";
  closeBtn.setAttribute("aria-label", "Close Manage storage");
  closeBtn.addEventListener("click", close);
  head.appendChild(closeBtn);
  box.appendChild(head);

  const intro = el("p", "cm-storage-intro",
    "Comments and review data for every commentable-html document open in this browser share one "
    + "storage budget. Delete another document's data below to free space. Nothing here is uploaded.");
  box.appendChild(intro);

  const banner = el("div", "cm-storage-banner", "");
  banner.id = "cmStorageBanner";
  banner.setAttribute("role", quota ? "alert" : "status");
  banner.setAttribute("aria-live", quota ? "assertive" : "polite");
  banner.hidden = true;
  box.appendChild(banner);
  // On a quota auto-open the banner explains WHY the dialog appeared; describe the dialog by it so a
  // screen reader announces the reason when focus enters (a synchronously-mutated role=alert alone is
  // often missed).
  if (quota) box.setAttribute("aria-describedby", "cmStorageBanner");

  const totalLine = el("p", "cm-storage-total", "");
  totalLine.setAttribute("aria-live", "polite");
  box.appendChild(totalLine);

  const usageWrap = el("div", "cm-storage-usage");
  usageWrap.setAttribute("aria-live", "polite");
  box.appendChild(usageWrap);

  const listWrap = el("div", "cm-storage-list");
  box.appendChild(listWrap);

  const emptyNote = el("div", "cm-storage-empty", "");
  emptyNote.hidden = true;
  box.appendChild(emptyNote);

  // Footer with a Close button (mirrors the header close, so a close control stays reachable at the
  // bottom of a long list).
  const foot = el("div", "cm-storage-foot");
  const footClose = el("button", "cm-storage-btn cm-storage-foot-close", "Close");
  footClose.type = "button";
  footClose.addEventListener("click", close);
  foot.appendChild(footClose);
  box.appendChild(foot);

  // Bases whose per-comment list is currently expanded. Kept across re-renders so a per-comment
  // delete does not collapse the list the reviewer is working in.
  const expanded = new Set();

  // Retry any pending (quota-failed) writes after space is freed, regardless of how the manager was
  // opened, so a manually-opened dialog (or a secondary-writer toast action) also persists the
  // stashed write. The banner update is quota-only; the retry and the "Saved" confirmation are not.
  function announceRetry() {
    const done = (typeof cmhRetryPendingWrites === "function") ? cmhRetryPendingWrites() : [];
    if (done.length) {
      showToast("Saved.", { duration: 2500 });
      if (quota) {
        banner.className = "cm-storage-banner cm-storage-banner-ok";
        banner.textContent = "Space freed - your " + done.join(", ") + " was saved.";
      }
    }
    // Re-arm the comment auto-open once the comment slot's pending write is resolved.
    if (!_cmhPendingWrites.has(CMH_STORE_KEY)) _cmhQuotaEpisode = false;
  }

  function render(focusSel) {
    const data = cmhStorageGroups();
    let total = 0;
    data.docs.forEach(function (g) { total += g.bytes; });
    data.globals.forEach(function (x) { total += x.bytes; });
    totalLine.textContent = "About " + _cmhHumanSize(total) + " used across "
      + data.docs.length + " document" + (data.docs.length === 1 ? "" : "s")
      + " (browsers typically allow ~5 MB for local files; the exact limit varies).";

    renderUsageSummary();

    if (quota) {
      banner.hidden = false;
      if (banner.className.indexOf("cm-storage-banner-ok") === -1) {
        banner.className = "cm-storage-banner cm-storage-banner-warn";
        banner.textContent = "Storage is full. Delete data from another document to free space - "
          + "your comment saves automatically once there is room.";
      }
    }

    listWrap.textContent = "";
    const otherDocs = data.docs.filter(function (g) { return !g.current; });
    const cmhTotalBytes = total;
    const table = el("table", "cm-storage-table");
    const thead = document.createElement("thead");
    const htr = document.createElement("tr");
    ["Document", "Comments", "Size", "Share", ""].forEach(function (h, i) {
      const th = document.createElement("th");
      th.textContent = h;
      if (i === 3) th.title = "Share of commentable-html storage";
      if (i === 4) th.setAttribute("aria-label", "Actions");
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    data.docs.forEach(function (g) { appendDocRows(tbody, g, cmhTotalBytes); });
    if (data.globals.length) appendGlobalsRow(tbody, data.globals, cmhTotalBytes);
    table.appendChild(tbody);
    listWrap.appendChild(table);

    // Empty state: nothing reclaimable from OTHER documents. Gate on other-document rows only (not
    // shared-preference globals): the quota Export/Clear escape hatch must show whenever there is no
    // other document's data to delete, even if some shared preferences remain (deleting those frees
    // little). The globals row, if any, still renders above for its own deletion.
    if (!otherDocs.length) {
      emptyNote.hidden = false;
      emptyNote.textContent = "";
      const p = el("p", null, quota
        ? "There is no other document's data to delete - this document (or other site data) is using the space. Save your review to a file, then clear this document's comments to free room:"
        : "No other commentable-html documents have stored data in this browser yet.");
      emptyNote.appendChild(p);
      if (quota) {
        const actions = el("div", "cm-storage-empty-actions");
        const exp = el("button", "cm-storage-btn", "Export as Portable");
        exp.type = "button";
        exp.addEventListener("click", function () {
          const b = document.getElementById("btnSaveHtmlTop") || document.getElementById("btnSaveHtml");
          if (b) b.click();
        });
        actions.appendChild(exp);
        actions.appendChild(clearCurrentButton());
        emptyNote.appendChild(actions);
      }
    } else {
      emptyNote.hidden = true;
    }

    // Focus management after a re-render (e.g. a row was deleted).
    let target = null;
    if (typeof focusSel === "function") target = focusSel(box);
    else if (focusSel) target = box.querySelector(focusSel);
    if (!target) target = closeBtn;
    if (target && typeof target.focus === "function") target.focus();
  }

  function clearCurrentButton() {
    const btn = el("button", "cm-storage-btn cm-storage-danger", "Clear all comments");
    btn.type = "button";
    btn.setAttribute("aria-label", "Clear all comments for this document");
    btn.addEventListener("click", function () {
      inlineConfirm(btn, "Clear all comments and reset tracked widget, checklist, and note changes for this document?", function () {
        if (typeof performClearAll === "function") performClearAll();
        // Do NOT drop this document's index entry: it is the CURRENT document (still open and
        // re-registered on every load), and clearing its comments leaves residual keys (dismissed
        // banners, and note/checklist sidecars if any). Removing the entry would strip the ownership
        // proof those residuals need to stay listed/reclaimable from another document (CMH-STORE-10).
        announceRetry();
        render();
        showToast("Comments cleared.", { duration: 2500 });
      });
    });
    return btn;
  }

  function renderUsageSummary() {
    const usage = cmhStorageUsage();
    usageWrap.textContent = "";
    const originPct = _cmhPct(usage.originBytes, usage.assumedQuota);
    const cmhPctOfOrigin = _cmhPct(usage.cmhBytes, usage.originBytes);
    const docPctOfCmh = _cmhPct(usage.currentBytes, usage.cmhBytes);
    const bar = el("div", "cm-storage-bar");
    const fill = el("div", "cm-storage-bar-fill");
    fill.style.width = Math.min(100, originPct) + "%";
    bar.appendChild(fill);
    usageWrap.appendChild(bar);
    usageWrap.appendChild(el("div", "cm-storage-usage-line",
      "Local storage in use: " + _cmhHumanSize(usage.originBytes) + " - about " + originPct
      + "% of the ~5 MB a browser typically allows (the exact limit varies)."));
    usageWrap.appendChild(el("div", "cm-storage-usage-line",
      "commentable-html: " + _cmhHumanSize(usage.cmhBytes) + " - " + cmhPctOfOrigin
      + "% of the storage in use."));
    usageWrap.appendChild(el("div", "cm-storage-usage-line",
      "This document: " + _cmhHumanSize(usage.currentBytes) + " - " + docPctOfCmh
      + "% of commentable-html storage."));
  }

  // Build a document's table row (and, when expanded, its per-comment list row) and append both.
  function appendDocRows(tbody, g, cmhTotalBytes) {
    const row = el("tr", "cm-storage-row" + (g.current ? " cm-storage-current" : ""));
    const nameTd = el("td", "cm-storage-cell-name");
    const nameLine = el("div", "cm-storage-name-line");
    nameLine.appendChild(el("span", "cm-storage-name", _cmhDocDisplayName(g)));
    if (g.current) nameLine.appendChild(el("span", "cm-storage-badge", "This document"));
    nameTd.appendChild(nameLine);
    if (g.source) nameTd.appendChild(el("div", "cm-storage-source", g.source));
    // For the current document the LIVE count is authoritative (a just-deleted comment is reflected
    // before the store is re-read); other documents use the decoded stored count.
    const count = g.current ? (Array.isArray(comments) ? comments.length : 0) : g.count;
    if (count) nameTd.appendChild(showCommentsToggle(g));
    row.appendChild(nameTd);
    row.appendChild(el("td", "cm-storage-count", count == null ? "?" : String(count)));
    row.appendChild(el("td", "cm-storage-size", _cmhHumanSize(g.bytes)));
    row.appendChild(el("td", "cm-storage-share", _cmhPct(g.bytes, cmhTotalBytes) + "%"));
    const actTd = el("td", "cm-storage-actions");
    if (g.current) actTd.appendChild(clearCurrentButton());
    else actTd.appendChild(deleteDocButton(g));
    row.appendChild(actTd);
    tbody.appendChild(row);
    if (expanded.has(g.base)) {
      // Re-append the expanded comment list, but drop the expansion when nothing remains: the
      // "Show comments" toggle is suppressed at zero, so an empty list would otherwise be stuck open.
      if (count) tbody.appendChild(commentsRowFor(g));
      else expanded.delete(g.base);
    }
  }

  function deleteDocButton(g) {
    const del = el("button", "cm-storage-btn cm-storage-danger", "Delete");
    del.type = "button";
    del.setAttribute("aria-label", "Delete stored data for " + _cmhDocDisplayName(g));
    del.addEventListener("click", function () {
      inlineConfirm(del, "Delete this document's data?", function () {
        // Remember this row's position among the other-document rows so focus lands near it (not
        // jumping to the top) after the list re-renders.
        const others = Array.prototype.slice.call(
          box.querySelectorAll(".cm-storage-row:not(.cm-storage-current):not(.cm-storage-global)"));
        const idx = others.findIndex(function (r) { return r.querySelector(".cm-storage-confirm"); });
        _cmhDeleteKeys(g.keys);
        _cmhRemoveIndexEntry(g.base);
        expanded.delete(g.base);
        announceRetry();
        render(function (b) {
          const dels = b.querySelectorAll(
            ".cm-storage-row:not(.cm-storage-current):not(.cm-storage-global) .cm-storage-danger");
          if (!dels.length) return null;
          return dels[Math.min(Math.max(idx, 0), dels.length - 1)] || null;
        });
      });
    });
    return del;
  }

  // Lazy per-document "Show comments" toggle: inserts/removes the comment-list row in place (no full
  // re-render), so focus stays on the toggle and the list is only decoded when opened.
  function showCommentsToggle(g) {
    const isOpen = expanded.has(g.base);
    const btn = el("button", "cm-storage-btn cm-storage-show-comments", isOpen ? "Hide comments" : "Show comments");
    btn.type = "button";
    btn.setAttribute("aria-expanded", isOpen ? "true" : "false");
    btn.setAttribute("aria-label", (isOpen ? "Hide" : "Show") + " comments for " + _cmhDocDisplayName(g));
    btn.addEventListener("click", function () {
      const rowEl = btn.closest("tr");
      if (expanded.has(g.base)) {
        expanded.delete(g.base);
        const next = rowEl && rowEl.nextElementSibling;
        if (next && next.classList.contains("cm-storage-comments-row")) next.remove();
        btn.textContent = "Show comments";
        btn.setAttribute("aria-expanded", "false");
        btn.setAttribute("aria-label", "Show comments for " + _cmhDocDisplayName(g));
      } else {
        expanded.add(g.base);
        const cr = commentsRowFor(g);
        if (rowEl && rowEl.parentNode) rowEl.parentNode.insertBefore(cr, rowEl.nextElementSibling);
        btn.textContent = "Hide comments";
        btn.setAttribute("aria-expanded", "true");
        btn.setAttribute("aria-label", "Hide comments for " + _cmhDocDisplayName(g));
      }
    });
    return btn;
  }

  function commentsRowFor(g) {
    const tr = el("tr", "cm-storage-comments-row");
    const td = document.createElement("td");
    td.setAttribute("colspan", "5");
    const wrap = el("div", "cm-storage-comments");
    const list = _cmhDocComments(g);
    if (!list.length) {
      wrap.appendChild(el("div", "cm-storage-comment-empty", "No stored comments to show."));
    } else {
      list.forEach(function (c) { wrap.appendChild(commentEntry(g, c)); });
    }
    td.appendChild(wrap);
    tr.appendChild(td);
    return tr;
  }

  function commentEntry(g, c) {
    const item = el("div", "cm-storage-comment");
    const info = el("div", "cm-storage-comment-info");
    const q = _cmhCommentQuote(c);
    if (q) info.appendChild(el("div", "cm-storage-comment-quote", q));
    if (c && c.note) info.appendChild(el("div", "cm-storage-comment-note", String(c.note)));
    const meta = el("div", "cm-storage-comment-meta");
    if (c && c.author) meta.appendChild(el("span", "cm-storage-comment-author", String(c.author)));
    meta.appendChild(el("span", "cm-storage-comment-size", "~" + _cmhHumanSize(_cmhCommentApproxBytes(c))));
    info.appendChild(meta);
    item.appendChild(info);
    const actions = el("div", "cm-storage-actions");
    const del = el("button", "cm-storage-btn cm-storage-danger", "Delete");
    del.type = "button";
    del.setAttribute("aria-label", "Delete this comment");
    del.addEventListener("click", function () {
      inlineConfirm(del, "Delete this comment?", function () {
        if (g.current) _cmhDeleteCommentFromCurrent(c.id);
        else _cmhDeleteCommentFromStore(g.base, c.id);
        announceRetry();
        // Keep keyboard focus in the comment list the reviewer is working in (falls back to the
        // dialog's close button when no comment remains).
        render(function (b) {
          const dels = b.querySelectorAll(".cm-storage-comment .cm-storage-danger");
          return dels.length ? dels[0] : null;
        });
      });
    });
    actions.appendChild(del);
    item.appendChild(actions);
    return item;
  }

  function appendGlobalsRow(tbody, globals, cmhTotalBytes) {
    let bytes = 0;
    const keys = globals.map(function (x) { bytes += x.bytes; return x.key; });
    const row = el("tr", "cm-storage-row cm-storage-global");
    const nameTd = el("td", "cm-storage-cell-name");
    nameTd.appendChild(el("div", "cm-storage-name", "Other / shared data"));
    nameTd.appendChild(el("div", "cm-storage-source", "Preferences and dismissed banners not tied to one document"));
    row.appendChild(nameTd);
    row.appendChild(el("td", "cm-storage-count", String(globals.length)));
    row.appendChild(el("td", "cm-storage-size", _cmhHumanSize(bytes)));
    row.appendChild(el("td", "cm-storage-share", _cmhPct(bytes, cmhTotalBytes) + "%"));
    const actTd = el("td", "cm-storage-actions");
    const del = el("button", "cm-storage-btn", "Delete");
    del.type = "button";
    del.setAttribute("aria-label", "Delete shared preferences and dismissed banners");
    del.addEventListener("click", function () {
      inlineConfirm(del, "Delete shared preferences?", function () {
        _cmhDeleteKeys(keys);
        announceRetry();
        render();
      });
    });
    actTd.appendChild(del);
    row.appendChild(actTd);
    tbody.appendChild(row);
  }

  // Inline row confirmation: swap the trigger for Confirm/Cancel in place (avoids nesting a second
  // modal + focus-trap conflict). Focus moves to Confirm; Cancel restores and refocuses the trigger.
  function inlineConfirm(triggerBtn, message, onConfirm) {
    const parent = triggerBtn.parentNode;
    if (!parent) return;
    const wrap = el("div", "cm-storage-confirm");
    const msg = el("span", "cm-storage-confirm-msg", message);
    const msgId = "cmStorageConfirmMsg" + (++_cmhConfirmSeq);
    msg.id = msgId;
    wrap.appendChild(msg);
    const yes = el("button", "cm-storage-btn cm-storage-danger", "Confirm");
    yes.type = "button";
    yes.setAttribute("aria-describedby", msgId); // announce the full warning alongside the label
    const trigLabel = triggerBtn.getAttribute("aria-label");
    if (trigLabel) yes.setAttribute("aria-label", "Confirm - " + trigLabel);
    const no = el("button", "cm-storage-btn", "Cancel");
    no.type = "button";
    if (trigLabel) no.setAttribute("aria-label", "Cancel - " + trigLabel);
    wrap.appendChild(yes);
    wrap.appendChild(no);
    parent.replaceChild(wrap, triggerBtn);
    no.addEventListener("click", function () {
      parent.replaceChild(triggerBtn, wrap);
      triggerBtn.focus();
    });
    yes.addEventListener("click", function () { onConfirm(); });
    yes.focus();
  }

  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); return; }
    if (e.key === "Tab") {
      const f = Array.prototype.slice.call(box.querySelectorAll("button, a[href], input"))
        .filter(function (n) { return n.offsetParent !== null || n === document.activeElement; });
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1], active = document.activeElement;
      if (e.shiftKey) { if (active === first || !box.contains(active)) { e.preventDefault(); last.focus(); } }
      else { if (active === last || !box.contains(active)) { e.preventDefault(); first.focus(); } }
    }
  }
  overlay.addEventListener("mousedown", function (e) { if (e.target === overlay) close(); });
  document.addEventListener("keydown", onKey, true);
  render();
  // Mark open only AFTER the setup+first render succeed, so a throw mid-build can never leave the
  // manager permanently un-openable or the quota episode latched (it just returns falsy and the
  // caller falls back to a toast).
  _cmhStorageOpen = true;
  if (quota) _cmhQuotaEpisode = true;
  closeBtn.focus();
  return true;
}

// Wire the toolbar/sidebar Manage-storage menu items. Both ids are in the validator's REQUIRED_IDS
// (the current shell always emits them exactly once), so the null-guard here is defensive only.
// Focus is restored to the still-visible menu button (the clicked item lives in a menu that closes),
// mirroring the help dialog.
(function () {
  const wiring = [
    { id: "btnStorageTop", menu: "toolbarMenu", restore: "btnToolbarMenu" },
    { id: "btnStorage", menu: "sidebarExportMenu", restore: "btnSidebarExportMenu" },
  ];
  wiring.forEach(function (w) {
    const b = document.getElementById(w.id);
    if (!b) return;
    b.addEventListener("click", function () {
      const menu = document.getElementById(w.menu);
      if (menu) menu.hidden = true;
      openStorageManager({ restoreFocus: document.getElementById(w.restore) || undefined });
    });
  });
})();

// Test hook (follows the existing __cmh* baked-hook convention): lets specs exercise the codec and
// the grouping directly, and read/write the current document's persisted comments through the modern
// slot (so a spec that injects/patches comments stays in sync with where the runtime loads from).
// Harmless read-only helpers plus a store writer; the validator does not scan window globals.
window.__cmhStorageCodec = {
  encode: cmhEncodeStore,
  decode: cmhDecodeStore,
  groups: cmhStorageGroups,
  usage: cmhStorageUsage,
  open: openStorageManager,
  read: function () { return cmhLoadStored().arr; },
  write: function (arr) {
    localStorage.setItem(CMH_STORE_KEY, cmhEncodeStore(JSON.stringify(arr)));
    try { localStorage.removeItem(COMMENT_KEY); } catch (e) { /* best-effort */ }
  },
};

// Register this document in the shared index on load so the manager can list it by name even before
// the first comment is saved.
try { cmhRegisterDocument(); } catch (e) { /* best-effort */ }
