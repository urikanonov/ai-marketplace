/* ---------- Persistence ---------- */
// True for a storage-quota error across browsers (Chrome/Safari "QuotaExceededError", Firefox
// "NS_ERROR_DOM_QUOTA_REACHED"; legacy numeric codes 22 / 1014). A DOMException raised via the
// name constructor has code 0, so match primarily on the name.
function cmhIsQuotaError(e) {
  if (!e) return false;
  return e.name === "QuotaExceededError"
    || e.name === "NS_ERROR_DOM_QUOTA_REACHED"
    || e.code === 22 || e.code === 1014;
}
// Encode a comments JSON string for the modern slot: a framed lz-string payload when that is
// SMALLER (in UTF-16 code units, which is what localStorage costs), else the plain JSON unchanged.
function cmhEncodeStore(jsonStr) {
  try {
    const framed = CMH_STORE_FRAME + LZString.compressToUTF16(jsonStr);
    return framed.length < jsonStr.length ? framed : jsonStr;
  } catch (e) { return jsonStr; }
}
// Decode a stored value. Returns {ok, json}: ok=false means the value was PRESENT but unreadable
// (corrupt/oversized frame) and MUST NOT be overwritten. A framed value starts with the "\u0001"
// marker; anything else is treated as legacy/plain JSON and returned unchanged.
function cmhDecodeStore(raw) {
  if (raw == null) return { ok: true, json: null };
  if (raw.charCodeAt(0) !== 1) return { ok: true, json: raw };
  if (raw.charAt(1) !== "z") return { ok: false, json: null };
  try {
    const out = LZString.decompressFromUTF16(raw.slice(2), CMH_MAX_STORE_CHARS);
    if (out == null) return { ok: false, json: null };
    return { ok: true, json: out };
  } catch (e) { return { ok: false, json: null }; }
}
// Read the persisted comment array. Prefers the modern slot (::z); falls back to the legacy
// COMMENT_KEY (plain JSON) for files last saved by an older runtime. Returns {arr, unreadable}
// where unreadable=true flags a present-but-corrupt store so loadComments does not clobber it.
function cmhLoadStored() {
  let raw = null;
  let fromModern = true;
  try { raw = localStorage.getItem(CMH_STORE_KEY); } catch (e) { return { arr: [], unreadable: false }; }
  if (raw == null) {
    fromModern = false;
    try { raw = localStorage.getItem(COMMENT_KEY); } catch (e) { return { arr: [], unreadable: false }; }
    if (raw == null) return { arr: [], unreadable: false };
  }
  // ANY unreadable value in the MODERN slot is protected: the ::z slot stores EITHER a framed
  // lz-string payload OR plain JSON (store-the-smaller), so a corrupt/truncated PLAIN ::z value - or
  // a valid-JSON-non-array future/foreign format - must be treated as unreadable too, not just a
  // framed one (else a startup merge diff would call saveComments() and clobber recoverable bytes).
  // A legacy base-key value that fails to parse degrades silently to empty (the pre-existing
  // behavior), so seeding a corrupt legacy value does not raise a scary notice.
  const dec = cmhDecodeStore(raw);
  if (!dec.ok) return { arr: [], unreadable: fromModern };
  if (dec.json == null || dec.json === "") return { arr: [], unreadable: false };
  try {
    const arr = JSON.parse(dec.json);
    if (Array.isArray(arr)) return { arr: arr, unreadable: false };
    return { arr: [], unreadable: fromModern };
  } catch (e) { return { arr: [], unreadable: fromModern }; }
}
// Pending write retries keyed by storage key. A quota failure stashes the exact producer so the
// storage manager can re-run it (recomputing the latest value) once the reviewer frees space.
const _cmhPendingWrites = new Map();
// Set true by saveComments() when its last attempt failed on quota (vs a blocked/private-mode
// error); the comment-composer save reads it to open the storage manager for that specific case.
let _cmhLastSaveQuota = false;
// Set true by loadComments() when the persisted store was present but UNREADABLE (a corrupt or
// newer-format frame). While set, saveComments() does NOT write, so the recoverable bytes are left
// untouched across a reload-without-edit; startup clears it after pruning so a genuine user edit
// still persists (and intentionally replaces the unreadable value).
let _cmhStoreUnreadable = false;
// Persist key <- produce(). produce() returns a string to store or null to removeItem. Returns
// true on immediate success (set or remove). On a quota error it stashes the producer for retry
// and returns false (callers already treat false as "not saved"); other errors return false too.
function cmhTrySetItem(key, produce, label) {
  try {
    const value = produce();
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
    _cmhPendingWrites.delete(key);
    return true;
  } catch (e) {
    if (cmhIsQuotaError(e)) _cmhPendingWrites.set(key, { produce: produce, label: label || "data" });
    return false;
  }
}
// Re-run every pending write (called by the storage manager after space is freed). Returns the
// distinct labels that now succeeded, so the manager can confirm what was saved.
function cmhRetryPendingWrites() {
  const done = [];
  _cmhPendingWrites.forEach(function (rec, key) {
    try {
      const v = rec.produce();
      if (v == null) localStorage.removeItem(key); else localStorage.setItem(key, v);
      _cmhPendingWrites.delete(key);
      // A successful comment-slot retry also reclaims the legacy key (mirrors saveComments).
      if (key === CMH_STORE_KEY) { try { localStorage.removeItem(COMMENT_KEY); } catch (e) { /* best-effort */ } }
      if (done.indexOf(rec.label) === -1) done.push(rec.label);
    } catch (e) {
      // Still full: leave the entry pending for the next delete. A NON-quota failure (blocked/
      // corrupt) will never succeed on retry, so drop it rather than retrying forever.
      if (!cmhIsQuotaError(e)) _cmhPendingWrites.delete(key);
    }
  });
  return done;
}
// Recovery toast for a secondary writer (notes/checklist/reviews) that failed via cmhTrySetItem.
// A quota failure (the write is now pending in _cmhPendingWrites) offers a "Manage storage" action;
// a blocked/private-mode failure just warns. Call only after cmhTrySetItem returned false.
function cmhStorageFullToast(key, what) {
  const quota = _cmhPendingWrites.has(key);
  showToast(quota
    ? what + " could not be saved - this browser's storage is full. Free space from Manage storage."
    : what + " NOT saved to this browser (storage full or blocked) - it will be lost on reload.",
    { alert: true, duration: 8000, action: cmhStorageAction(key) });
}
// The "Manage storage" toast action object for a key whose write is pending after a quota failure
// (else null). Lets a caller with its own message keep the recovery action without double-toasting.
function cmhStorageAction(key) {
  return (_cmhPendingWrites.has(key) && typeof openStorageManager === "function")
    ? { label: "Manage storage", onClick: function () { openStorageManager(); } } : null;
}
function loadComments() {
  const loaded = cmhLoadStored();
  const local = loaded.arr;
  // Exclude embedded comments that were deleted in a prior session (tombstoned), so a
  // baked-in comment stays deleted across reload instead of resurrecting from the file.
  const tomb = _deletedEmbeddedIds();
  const embedded = getEmbeddedComments().filter(function (c) { return !(c && tomb.has(c.id)); });
  comments = mergeCommentSets(local, embedded);
  // Drop (and tombstone) any reply whose thread root is not present, so a dangling reply
  // can never render or resurrect from the embedded block.
  if (typeof pruneOrphanReplies === "function") pruneOrphanReplies();
  // A present-but-unreadable store (corrupt/oversized/newer-format frame) is left UNTOUCHED so
  // the recoverable bytes are not clobbered; only a subsequent edit will replace it.
  if (loaded.unreadable) {
    _cmhStoreUnreadable = true;
    showToast("Saved comments in this browser could not be read (they may be from a newer version) "
      + "- they are left untouched; editing a comment will replace them.", { alert: true, duration: 8000 });
    return;
  }
  // If the merge changed the stored set, persist so reloads converge (compare against the DECODED
  // local array, so a framed store does not look "changed" and re-save on every load).
  try {
    if (JSON.stringify(comments) !== JSON.stringify(local)) saveComments();
  } catch (e) { /* serialization noise, ignore */ }
}
function saveComments() {
  _cmhLastSaveQuota = false;
  // While the store was loaded UNREADABLE, do not overwrite it from an automatic save (startup
  // prune/convergence); the recoverable bytes survive a reload-without-edit. Startup clears the flag
  // after pruning, so a genuine user edit still persists.
  if (_cmhStoreUnreadable) return true;
  try {
    // Always write the modern slot FIRST (an empty array serializes to "[]"); only on success
    // remove the legacy key, so a quota failure never leaves both slots empty (any legacy value
    // stays recoverable).
    localStorage.setItem(CMH_STORE_KEY, cmhEncodeStore(JSON.stringify(comments)));
    _cmhPendingWrites.delete(CMH_STORE_KEY);
    try { localStorage.removeItem(COMMENT_KEY); } catch (e) { /* best-effort legacy reclaim */ }
    if (typeof cmhRegisterDocument === "function") cmhRegisterDocument();
    if (typeof _cmhResetQuotaEpisode === "function") _cmhResetQuotaEpisode();
    return true;
  } catch (e) {
    if (cmhIsQuotaError(e)) {
      _cmhLastSaveQuota = true;
      // The comment is still in memory (visible in the list). Stash the exact write for retry; the
      // composer save opens the storage manager so the reviewer can free space and it is re-saved.
      _cmhPendingWrites.set(CMH_STORE_KEY, {
        produce: function () { return cmhEncodeStore(JSON.stringify(comments)); },
        label: "comment",
      });
      return false;
    }
    // Blocked / private mode: keep the existing recovery-path warning.
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
  if (!changed) return true;
  try { localStorage.setItem(CMH_DELETED_KEY, JSON.stringify([...t])); return true; }
  catch (e) { return false; }
}
function _ensureTombstoneEmbedded(ids, firstWriteOk, commentsWriteOk) {
  if (commentsWriteOk && (firstWriteOk || _tombstoneEmbedded(ids))) return true;
  showToast("Deleted embedded comment was removed in this session, but the browser could not persist its delete marker. It may reappear after reload; use Export as Portable after freeing storage.", { alert: true, duration: 10000 });
  return false;
}
function commentTimestamp(c) {
  return (c && (c.updatedAt || c.createdAt)) || "";
}
// Defense-in-depth bounds for mergeCommentSets(), so an untrusted embeddedComments
// array (or a poisoned localStorage array under a matching data-comment-key) can never
// drive backfillContext()/restoreHighlights() into O(comment_count x document_size) work
// at startup. Both bounds are far beyond anything a real document ever needs, so normal
// documents are unaffected.
const CMH_MAX_COMMENTS = 1000;
const CMH_MAX_OFFSET = 1000000000; // 1e9 chars: no real document approaches this, but an
// orphaned-anchor offset just past a document's end (e.g. a stale reload target) stays sane.
// True for non-text-anchored comments (document/image/widget/mermaid/diff), which never
// carry start/end and so never drive the offset-based context/highlight walk - those
// pass through untouched. A text-anchored comment (start and/or end present) must have
// finite, non-negative, ordered, in-range offsets or it is dropped.
function _offsetAnchorIsSane(c) {
  if (c.start === undefined && c.end === undefined) return true;
  return Number.isFinite(c.start) && Number.isFinite(c.end)
    && c.start >= 0 && c.end >= c.start && c.end <= CMH_MAX_OFFSET;
}
// A reply's parentId must be a SAFE_ID that differs from its own id (a reply cannot parent
// itself). Absent parentId (a top-level comment) is always fine. Rejecting an unsafe
// parentId at the single load/merge choke point keeps a poisoned value from ever reaching a
// selector or the thread-grouping logic; a reply pointing at a missing/non-root id survives
// this gate and is dropped later by pruneOrphanReplies().
function _parentRefIsSane(c) {
  if (c.parentId === undefined || c.parentId === null) return true;
  return typeof c.parentId === "string" && SAFE_ID_RE.test(c.parentId) && c.parentId !== c.id;
}
// Merge two comment arrays by id. For each id present in both, keep the
// entry with the later updatedAt (fallback createdAt). Ids only in one
// side pass through. Order is preserved best-effort (a first, then new
// b entries appended). Entries whose id fails SAFE_ID_RE, or whose start/end
// offsets are not sane, are dropped here (the single load/merge choke point), so
// an unsafe id or a pathological offset from localStorage or the embeddedComments
// block can never reach a data-cid attribute/selector or an unbounded startup walk.
// The merged result is also capped at CMH_MAX_COMMENTS: once the cap is reached, no
// further new ids are admitted (an id already present may still be updated by a
// newer duplicate), degrading gracefully instead of throwing.
function mergeCommentSets(a, b) {
  const map = new Map();
  const order = [];
  for (const c of (a || [])) {
    if (!c || !c.id || !SAFE_ID_RE.test(c.id) || !_offsetAnchorIsSane(c) || !_parentRefIsSane(c)) continue;
    if (typeof c.author === "string") c.author = _sanitizeAuthor(c.author);
    const existing = map.get(c.id);
    if (!existing) {
      if (map.size >= CMH_MAX_COMMENTS) continue;
      map.set(c.id, c);
      order.push(c.id);            // dedupe: an id repeated in the persisted array appears once
    } else if (commentTimestamp(c) > commentTimestamp(existing)) {
      map.set(c.id, c);
    }
  }
  for (const c of (b || [])) {
    if (!c || !c.id || !SAFE_ID_RE.test(c.id) || !_offsetAnchorIsSane(c) || !_parentRefIsSane(c)) continue;
    if (typeof c.author === "string") c.author = _sanitizeAuthor(c.author);
    const existing = map.get(c.id);
    if (!existing) {
      if (map.size >= CMH_MAX_COMMENTS) continue;
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

