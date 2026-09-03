/* ---------- Per-comment selection: Copy selected / Clear selected ---------- */
// A TRANSIENT pick list of comment THREAD ROOTS, so a reviewer can hand back (or delete) only part
// of a review instead of the all-or-nothing Copy all / Clear all. It is deliberately never
// persisted and never embedded: the selection is a view of THIS session, so a reload, an export,
// or a second tab starts from the all-or-nothing default and no reviewer's pick can travel inside
// a shared file. Only roots are pickable - a thread travels together (CMH-THREAD-02/03), so
// picking a root picks its replies with it.
let _cmPicked = new Set();

function _cmPickableIds() {
  const live = (typeof withoutHandled === "function") ? withoutHandled(comments) : comments;
  const roots = (typeof threadRoots === "function") ? threadRoots(live) : live;
  const out = new Set();
  roots.forEach(function (c) { out.add(c.id); });
  return out;
}

// Prune on READ rather than hooking every delete path: a comment can leave the array from its
// card, from the in-document dialog, from Clear all, or from a handled-id prune on load, and a
// stale id left in the set would silently scope a copy to nothing.
function selectedCommentIds() {
  if (!_cmPicked.size) return [];
  const ok = _cmPickableIds();
  const live = [];
  _cmPicked.forEach(function (id) { if (ok.has(id)) live.push(id); });
  if (live.length !== _cmPicked.size) _cmPicked = new Set(live);
  return live;
}

function isCommentPicked(id) { return _cmPicked.has(id); }

function setCommentPicked(id, on) {
  if (on) _cmPicked.add(id); else _cmPicked.delete(id);
  updateCommentPickUi();
}

// Deselect everything WITHOUT deleting anything. The rendered checkboxes are reset in place rather
// than through a re-render, so an open inline reply/edit draft in a card is never disturbed.
function clearCommentPicks() {
  _cmPicked = new Set();
  if (listEl) {
    listEl.querySelectorAll(".cm-card").forEach(function (card) {
      card.classList.remove("cm-card-picked");
      const box = card.querySelector("input.cm-pick-box");
      if (box) box.checked = false;
    });
  }
  updateCommentPickUi();
}

// The selection bar and the More-menu item are the two controls that only exist while something is
// picked. The copy buttons' own label swap lives in updateCopyAllState (56-copy-clear.js), which
// calls this after every render, so the two can never disagree about whether a selection exists.
function cmhSyncSelectionBar() {
  const n = selectedCommentIds().length;
  const bar = cmhEl("cmSelectBar");
  if (bar) bar.hidden = n === 0;
  const count = cmhEl("cmSelectCount");
  if (count) count.textContent = n + " comment" + (n === 1 ? "" : "s") + " selected";
  const item = cmhEl("btnClearSelected");
  if (item) item.hidden = n === 0;
}

function updateCommentPickUi() {
  if (typeof updateCopyAllState === "function") updateCopyAllState();
  else cmhSyncSelectionBar();
}

// Every id the selection names, root then replies, so a picked thread is copied and deleted whole.
function selectedThreadIds() {
  const out = [];
  const seen = new Set();
  selectedCommentIds().forEach(function (id) {
    const ids = (typeof threadIds === "function") ? threadIds(id) : [id];
    ids.forEach(function (x) { if (!seen.has(x)) { seen.add(x); out.push(x); } });
  });
  return out;
}

let _cmClearSelectedBusy = false;
function _cmDeleteSelectedThreads(ids) {
  const drop = new Set(ids);
  if (typeof openEditComposers !== "undefined") {
    ids.forEach(function (id) {
      const oc = openEditComposers.get(id);
      if (oc) closeComposerElement(oc);
    });
  }
  if (typeof cmhClosePopoverForIds === "function") cmhClosePopoverForIds(ids);
  const tombstoneOk = _tombstoneEmbedded(ids);
  comments.forEach(function (c) { if (drop.has(c.id)) removeHighlight(c); });
  comments = comments.filter(function (c) { return !drop.has(c.id); });
  const commentsOk = saveComments();
  _ensureTombstoneEmbedded(ids, tombstoneOk, commentsOk);
  _cmPicked = new Set();
  renderComments();
}

// Same confirm-then-tombstone shape as Clear all (62-sortable-tables.js), scoped to the selection:
// keeping the two in the same shape is what stops the narrow delete from drifting away from the
// wide one on durability.
async function _cmConfirmClearSelected(restoreId) {
  if (_cmClearSelectedBusy) return;
  const restore = cmhEl(restoreId);
  const roots = selectedCommentIds();
  if (!roots.length) {
    // No dialog opens, so no restoreFocus fires - but the owning menu still closes on this click,
    // which would drop focus to <body>. Put it back on the menu's trigger.
    if (restore && typeof restore.focus === "function") restore.focus();
    return;
  }
  _cmClearSelectedBusy = true;
  try {
    const ids = selectedThreadIds();
    const nReplies = ids.length - roots.length;
    const reps = nReplies ? (" and " + nReplies + " repl" + (nReplies === 1 ? "y" : "ies")) : "";
    const ok = await showConfirm({
      message: "Delete the " + roots.length + " selected comment" + (roots.length === 1 ? "" : "s")
        + reps + "? This cannot be undone.",
      confirmLabel: "OK",
      cancelLabel: "Cancel",
      danger: true,
      restoreFocus: restore || undefined,
    });
    if (!ok) return;
    _cmDeleteSelectedThreads(ids);
  } finally {
    _cmClearSelectedBusy = false;
  }
}

(function () {
  const clear = cmhEl("btnClearSelection");
  if (clear) clear.addEventListener("click", function () { clearCommentPicks(); });
  const item = cmhEl("btnClearSelected");
  if (item) {
    item.addEventListener("click", function () {
      // The listener cannot await, so surface a failure instead of leaving a floating rejection.
      _cmConfirmClearSelected("btnMoreMenu").catch(function (e) {
        try { console.warn("commentable-html: clear selected comments failed:", e); } catch (e2) { /* no-op */ }
      });
    });
  }
})();
