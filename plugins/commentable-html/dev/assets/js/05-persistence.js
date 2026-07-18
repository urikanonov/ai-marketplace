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
    if (!c || !c.id || !SAFE_ID_RE.test(c.id) || !_offsetAnchorIsSane(c)) continue;
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
    if (!c || !c.id || !SAFE_ID_RE.test(c.id) || !_offsetAnchorIsSane(c)) continue;
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




