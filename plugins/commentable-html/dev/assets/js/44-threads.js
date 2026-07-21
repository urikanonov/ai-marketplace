/* ---------- Comment threads (replies) ---------- */
// Single-level threading: a thread is one ROOT comment (no parentId) plus a flat,
// chronological list of REPLIES whose parentId is the root's id. A reply carries no
// independent anchor - it inherits the root's - only id/parentId/author/note/createdAt.
// This keeps the delete rules unambiguous: deleting a root removes the whole thread;
// deleting a reply removes only that reply.
function isReply(c) { return !!(c && c.parentId); }

// The set of ids that are valid thread roots (top-level comments) in the given list.
function _rootIdSet(list) {
  const s = new Set();
  (list || comments).forEach((c) => { if (c && c.id && !isReply(c)) s.add(c.id); });
  return s;
}

// Top-level comments (thread roots) in the given list, preserving array order.
function threadRoots(list) {
  return (list || comments).filter((c) => c && !isReply(c));
}

function _createdMs(c) {
  const t = Date.parse((c && c.createdAt) || "");
  return isNaN(t) ? 0 : t;
}

// Replies to a given root, oldest first (a stable createdAt sort so a thread always reads
// initial-comment-then-refinements). Falls back to array order when timestamps tie.
function repliesOf(rootId, list) {
  const src = (list || comments);
  const reps = [];
  for (let i = 0; i < src.length; i++) {
    if (src[i] && src[i].parentId === rootId) reps.push({ c: src[i], i: i });
  }
  reps.sort((a, b) => (_createdMs(a.c) - _createdMs(b.c)) || (a.i - b.i));
  return reps.map((r) => r.c);
}

// Every id in a thread (root + its replies), for tombstoning and handled-id bundling so a
// whole thread is deleted/pruned together.
function threadIds(rootId) {
  const ids = [rootId];
  comments.forEach((c) => { if (c && c.parentId === rootId) ids.push(c.id); });
  return ids;
}

// A reply is an ORPHAN when its parentId does not resolve to a present thread root (the
// root was deleted, was never embedded, or the reply points at another reply - single-level
// only). Orphans are pruned and tombstoned at load so a dangling reply can never render or
// resurrect from the embedded block.
function pruneOrphanReplies() {
  const roots = _rootIdSet(comments);
  const emb = (typeof _embeddedCommentSig === "function") ? _embeddedCommentSig() : null;
  const orphanIds = [];
  const tombstonable = [];
  for (let i = 0; i < comments.length; i++) {
    const c = comments[i];
    if (isReply(c) && !roots.has(c.parentId)) {
      orphanIds.push(c.id);
      // Only permanently tombstone an orphan whose parent is genuinely absent from the embedded
      // block. If the parent IS embedded but was crowded out this session (e.g. the CMH_MAX_COMMENTS
      // merge cap), do not tombstone - a later load with more headroom can legitimately re-admit it.
      if (!(emb && emb.has(c.parentId))) tombstonable.push(c.id);
    }
  }
  if (!orphanIds.length) return 0;
  if (tombstonable.length) _tombstoneEmbedded(tombstonable);
  const drop = new Set(orphanIds);
  comments = comments.filter((c) => !drop.has(c.id));
  return orphanIds.length;
}
