/* ---------- Sortable tables ----------
   Every column of an authored table (one with a real <thead>) gets up/down chevrons.
   Sorting reorders the <tbody> rows for display; numeric columns sort numerically.
   Reordering rows shifts the text-offset coordinate system, so after each sort we
   recompute every text comment's offsets from its live <mark>s and persist both the
   comments and the applied sort. The sort is re-applied on load BEFORE restore so the
   stored offsets always match the displayed order. */
const CMH_TABLE_SORT_KEY = COMMENT_KEY + "::tableSort";
// Null-prototype at every assignment site, matching the checklist/notes convention (CMH-SEC-02):
// a JSON.parse'd map still chains to Object.prototype, so a crafted "<key>::tableSort" payload
// keyed "__proto__"/"constructor" would let a plain property READ fall through to the prototype.
// The live keys here are "<idx>::<header-sig>", so this is defense in depth rather than a hole -
// the point is that the runtime has ONE convention for a document-reachable state map, not two.
let _tableSortState = Object.create(null);
function _tsNullProto(obj) {
  return (obj && typeof obj === "object" && !Array.isArray(obj))
    ? Object.assign(Object.create(null), obj) : Object.create(null);
}
function _loadTableSortState() {
  let parsed = null;
  try { parsed = JSON.parse(localStorage.getItem(CMH_TABLE_SORT_KEY) || "{}"); }
  catch (e) { parsed = null; }
  _tableSortState = _tsNullProto(parsed);
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
// `_tableKey` numbers the sortable tables in DOCUMENT order, and a sortable table nested in another
// table's cell CHANGES that number whenever the outer table's rows move. The three call sites
// therefore saw three different orders: `applyPersistedTableSorts` reads the UNSORTED startup DOM,
// `setupSortableTables` runs AFTER the persisted sorts are applied (so an already-sorted one), and
// the export pass re-derives keys around its own unsort. A reader who sorted a nested table then
// persisted it under a key neither reload nor export looked it up by (#976). So bind each table's
// key ONCE, on the unsorted startup DOM, and look it up by ELEMENT from then on. For a document
// with no nested sortable table the bound value is exactly what every call site computed anyway,
// so no reader loses a persisted sort.
const _tableKeyBinding = new WeakMap();
function _bindTableKeys() {
  // Never re-key a table that is already bound: a later pass would see the SORTED document order
  // and overwrite the canonical key this binding exists to hold still.
  _sortableTables().forEach(function (t, i) {
    if (!_tableKeyBinding.has(t)) _tableKeyBinding.set(t, _tableKey(t, i));
  });
}
// The bound key, falling back to the positional one for a table the binding never saw (a table
// added after startup, or a caller that runs before `applyPersistedTableSorts`).
function _tableKeyFor(t, idx) {
  const bound = _tableKeyBinding.get(t);
  return bound === undefined ? _tableKey(t, idx) : bound;
}
// Persisted sort state is reader-owned `localStorage` and can be absent, stale, or corrupt, so
// every consumer accepts only a state it can actually apply: the load pass, and the control setup
// that reflects the active direction on the chevron. A state one of them applied while the other
// ignored it would show a "sorted" column that is not sorted. The upper column bound is left to
// `_sortRows`, which reads a missing cell as empty text and so cannot scramble a table.
function _validSortState(st) {
  return !!st && Number.isInteger(st.col) && st.col >= 0 && (st.dir === "asc" || st.dir === "desc");
}
function _parseNum(s) {
  if (s == null) return null;
  const t = String(s).replace(/[\s,$%]/g, "");
  if (t === "" || !/^[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?$/.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}
// Permute the rows through their EXISTING SLOTS instead of appending them. A tbody authored with
// newlines carries whitespace text nodes BETWEEN its rows; appending every row to the end strands
// that whitespace ahead of them and leaves the rows textually adjacent - a text change no later
// unsort can undo (unsorting restores row ORDER, not the stranded whitespace). That silently drifted
// the document/section content hashes the moment a reader sorted a table, and because the sort is
// persisted per browser profile the same file then showed the "not validated" banner on one machine
// and not another (#952). The slot swap itself now lives in ONE place - cmhPermuteChildrenInSlots in
// 00-preamble.js, shared with the canonical-hash reader - so the append class cannot come back in a
// third copy of the math (#977).
//
// The rows a caller passes must be exactly this body's row set. A caller that ever breaks that (a
// different length, a duplicate, or a row that is not currently a child of this body) gets a no-op
// rather than the append that caused #952: leaving the DOM untouched is always text-neutral, while
// re-appending would silently revive the bug.
function _reorderBody(body, rows) {
  if (!body || !rows || body.rows.length !== rows.length) return;
  cmhPermuteChildrenInSlots(body, rows);
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
// The runtime OWNS this index: every sortable row is stamped with its position in the FILE, before
// any persisted sort is applied, and re-stamped on every pass. An authored (or stale) data-cmh-row
// must not be able to define a different "canonical" order, because the hashers read that order back
// as the authored one while the Python side reads the source file (#952).
function _indexTableRows() {
  _sortableTables().forEach(function (t) {
    const body = _tableBody(t);
    [...body.rows].forEach(function (r, ri) { r.dataset.cmhRow = String(ri); });
  });
}
function recomputeTextOffsets(persist) {
  if (persist === undefined) persist = true;
  let changed = false;
  function dropOffsets(c) {
    if (c.start !== undefined || c.end !== undefined) {
      delete c.start; delete c.end; changed = true;
    }
  }
  function markedTextNode(markList, reverse) {
    const list = reverse ? [...markList].reverse() : markList;
    for (const mark of list) {
      const nodes = [];
      const w = document.createTreeWalker(mark, NodeFilter.SHOW_TEXT, {
        acceptNode(n) { return (n.nodeValue || "").trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT; },
      });
      let n;
      while ((n = w.nextNode())) {
        if (!reverse) return n;
        nodes.push(n);
      }
      if (nodes.length) return nodes[nodes.length - 1];
    }
    return null;
  }
  const allNodes = getTextNodes();
  comments.forEach(function (c) {
    if (c.anchorType === "mermaid" || c.anchorType === "diff" || c.anchorType === "image" || c.anchorType === "link") return;
    const sel = 'mark.cm-hl[data-cid="' + c.id + '"]';
    const marks = [...root.querySelectorAll(sel)];
    if (!marks.length) return;
    const fT = markedTextNode(marks, false);
    const lT = markedTextNode(marks, true);
    if (!fT || !lT) { dropOffsets(c); return; }
    // Contiguity guard: a text comment's marks must form ONE contiguous run. After a sort
    // scatters a multi-row selection, marks[0]..marks[last] can straddle unrelated rows;
    // collapsing that to a single [start,end] span would over-wrap them on reload. If the
    // run is discontiguous, drop the offset anchor so reload keeps the comment listed but
    // cannot restore it onto unrelated intervening rows. A later sort that makes the live
    // marks contiguous again recomputes and persists fresh offsets.
    const si = allNodes.indexOf(fT), ei = allNodes.indexOf(lT);
    if (si < 0 || ei < 0 || ei < si) { dropOffsets(c); return; }
    let contiguous = true;
    for (let i = si; i <= ei; i++) {
      if (!(allNodes[i].nodeValue || "").trim()) continue;
      const p = allNodes[i].parentElement;
      if (!p || !p.closest(sel)) { contiguous = false; break; }
    }
    if (!contiguous) { dropOffsets(c); return; }
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
// reverted here because Shareable and Offline exports save the moved widget DOM.
function _canonicalCommentsForExport() {
  // The recompute below rewrites live comment offsets into AUTHORED-row coordinates. Snapshot them
  // so a throw part-way through cannot leave the reader holding offsets that no longer describe the
  // restored view: the next ordinary save would persist that mismatch and the reload after it would
  // land the highlight on an unrelated row.
  const liveOffsets = comments.map(function (c) { return { c: c, start: c.start, end: c.end }; });
  let completed = false;
  // Capture each table's LIVE row order BEFORE the first unsort, and put exactly that order back
  // afterwards. Re-deriving it by re-sorting is NOT an inverse of the unsort: `_sortRows` breaks
  // ties on a row's CURRENT index, and an outer table sorted on a column whose cells hold a nested
  // table compares that cell's live text - so a re-sort could hand the reader an order they never
  // had, and on a failed pass one the restored offsets no longer describe. Capturing the rows also
  // means the restore needs no persisted state and cannot fail: `_reorderBody` no-ops unless it is
  // handed exactly this body's own rows.
  const sorts = (!_tableSortState || Object.keys(_tableSortState).length === 0) ? [] :
    _sortableTables().map(function (t) {
      const body = _tableBody(t);
      return { body: body, rows: Array.prototype.slice.call(body.rows), unsorted: false };
    });
  function restoreRows() {
    sorts.forEach(function (s) {
      if (!s.unsorted) return;
      s.unsorted = false;
      _reorderBody(s.body, s.rows);
    });
  }
  function revertOffsets() {
    liveOffsets.forEach(function (o) {
      if (o.start === undefined) delete o.c.start; else o.c.start = o.start;
      if (o.end === undefined) delete o.c.end; else o.c.end = o.end;
    });
  }
  try {
    sorts.forEach(function (s) { _unsortRows(s.body); s.unsorted = true; });
    recomputeTextOffsets(false);
    const snap = comments.map(function (c) { return Object.assign({}, c); });
    restoreRows();
    if (sorts.length) recomputeTextOffsets(false);
    completed = true;
    return snap;
  } finally {
    // A throw above must never leave the reader looking at a permanently unsorted document, nor
    // holding the canonical pass's offsets. On the happy path both are no-ops: every table was put
    // back already and the recompute above realigned the offsets with it. The offsets are RESTORED
    // from the snapshot rather than recomputed, so unwinding cannot throw a second time and replace
    // the failure the caller is about to report.
    restoreRows();
    if (!completed) revertOffsets();
  }
}
function _exportableComments() {
  return withoutHandled(_canonicalCommentsForExport());
}
// Runs BEFORE backfillContext/restoreHighlights: re-applies the last persisted sort so
// the DOM order matches the persisted comment offsets.
function applyPersistedTableSorts() {
  _loadTableSortState();
  _indexTableRows();
  _bindTableKeys();
  // Innermost-first (document order reversed, since a nested table always follows its ancestor):
  // an outer table sorted on a column whose cells HOLD a nested table compares that cell's text,
  // so the nested table has to be in its own persisted order first or the outer table comes back
  // in a different order than the reader left it.
  const pending = _sortableTables().map(function (t, i) {
    return { body: _tableBody(t), state: _tableSortState[_tableKeyFor(t, i)] };
  });
  pending.reverse().forEach(function (p) {
    if (!_validSortState(p.state)) return;
    // One table that cannot be sorted must not abort the rest of startup: this runs as a bare
    // statement, so a throw here would take backfillContext, restoreHighlights and the whole UI
    // setup with it and leave a document with no comments and no chrome.
    try { _sortRows(p.body, p.state.col, p.state.dir); } catch (e) { /* sort the rest */ }
  });
}
function _reflectSortIco(btn, dir) {
  btn.dataset.dir = dir || "";
  btn.setAttribute("aria-pressed", dir ? "true" : "false");
  const cell = btn.closest("th, td") || btn.parentElement;
  if (cell) {
    if (dir === "asc") cell.setAttribute("aria-sort", "ascending");
    else if (dir === "desc") cell.setAttribute("aria-sort", "descending");
    else cell.removeAttribute("aria-sort");
  }
}
function setupSortableTables() {
  _sortableTables().forEach(function (t, i) {
    const key = _tableKeyFor(t, i);
    const hdr = _tableHeaderRow(t);
    const body = _tableBody(t);
    t.classList.add("cmh-sortable");
    const cur = _validSortState(_tableSortState[key]) ? _tableSortState[key] : null;
    [...hdr.cells].forEach(function (th, ci) {
      if (cmhOwnChrome(th, ":scope > .cmh-sort-ctrl")) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cmh-sort-ctrl cm-skip";
      cmhMarkLayerChrome(btn);
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
          const b2 = cmhOwnChrome(h2, ":scope > .cmh-sort-ctrl");
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
    const prevFocus = opts.restoreFocus || document.activeElement;
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
// The post-confirmation clear-all steps, factored out so the storage manager's current-document
// "Clear all comments" can reuse them after its own inline confirm (without nesting showConfirm).
function performClearAll() {
  // Close any open edit composer first: after the array is cleared its Save would find nothing
  // and the common tail would close it silently, losing the reviewer's in-progress edit.
  if (typeof openEditComposers !== "undefined") {
    Array.from(openEditComposers.values()).forEach((elc) => closeComposerElement(elc));
  }
  const tombstoneIds = comments.map(c => c.id);
  if (typeof cmhClosePopoverForIds === "function") cmhClosePopoverForIds(tombstoneIds);
  const tombstoneOk = _tombstoneEmbedded(tombstoneIds);
  comments.forEach(c => removeHighlight(c));
  comments = [];
  const commentsOk = saveComments();
  _ensureTombstoneEmbedded(tombstoneIds, tombstoneOk, commentsOk);
  if (typeof resetAllChecklists === "function") resetAllChecklists();
  if (typeof resetAllWidgetMoves === "function") resetAllWidgetMoves();
  if (typeof resetAllNotes === "function") resetAllNotes();
  renderComments();
}
// Clear all comments has TWO entry points - the sidebar More menu and the toolbar overflow menu
// (the only chrome a reviewer has while the panel is hidden). Both bind to this one handler, so
// the confirmation text, the nothing-to-clear guard, and the reset semantics can never disagree;
// only the focus-restore target differs, because each item lives in a menu that closes on click
// and focus must land on the still-visible trigger of the menu the user actually opened.
const CMH_CLEAR_ALL_TITLE = "Delete every comment (asks for confirmation first)";
const CMH_CLEAR_ALL_EMPTY_TIP = "Nothing to clear - there are no comments, note, checklist, or layout changes yet";
function _clearAllPending() {
  const stateChanges = (typeof widgetStateChanges === "function") ? widgetStateChanges() : [];
  const clChanges = (typeof checklistChanges === "function") ? checklistChanges() : [];
  const noteChanges = (typeof notesChanges === "function") ? notesChanges() : [];
  return comments.length + stateChanges.length + clChanges.length + noteChanges.length;
}
function _setClearAllTip(btn, text) {
  // Mirror the copy-all tip handling: once the tooltip layer has adopted a control (title moved to
  // data-cmh-tip) the managed attribute is the one to refresh, or the native tooltip reappears.
  if (btn.hasAttribute("title") || !btn.hasAttribute("data-cmh-tip")) btn.setAttribute("title", text);
  else btn.setAttribute("data-cmh-tip", text);
}
// Keep BOTH clear items showing the same empty state, so the two entry points never disagree about
// whether there is anything to clear (the same contract Copy all uses). The caller passes the
// already-computed copy-all state so this adds no extra document scan on a typing burst.
function updateClearAllState(state) {
  const s = state || (typeof _copyAllState === "function" ? _copyAllState() : null);
  const disabled = s
    ? !(comments.length || s.changes.length || s.clCh.length || s.noteCh.length)
    : _clearAllPending() === 0;
  ["btnClearAll", "btnClearAllTop"].forEach(function (id) {
    const btn = document.getElementById(id);
    if (!btn) return;
    btn.setAttribute("aria-disabled", disabled ? "true" : "false");
    btn.classList.toggle("cm-clear-disabled", disabled);
    _setClearAllTip(btn, disabled ? CMH_CLEAR_ALL_EMPTY_TIP : CMH_CLEAR_ALL_TITLE);
  });
}
updateClearAllState();
async function _confirmClearAll(restoreId) {
  // A confirm dialog is already up: do NOT touch focus - moving it to the menu trigger would pull
  // the caret outside the aria-modal dialog and behind its overlay.
  if (_clearAllBusy) return;
  const restore = document.getElementById(restoreId);
  if (_clearAllPending() === 0) {
    // Nothing to clear: no dialog opens, so no restoreFocus fires - but the owning menu still
    // closes on this click, which would drop focus to <body>. Put it back on the menu's trigger.
    if (restore && typeof restore.focus === "function") restore.focus();
    return;
  }
  _clearAllBusy = true;
  try {
    const ok = await showConfirm({
      message: comments.length
        ? `Delete all ${(typeof threadRoots === "function" ? threadRoots(comments).length : comments.length)} comment(s) and reset any tracked widget, checklist, and note changes? This cannot be undone.`
        : `Reset any tracked widget, checklist, and note changes? This cannot be undone.`,
      confirmLabel: "OK",
      cancelLabel: "Cancel",
      danger: true,
      restoreFocus: restore || undefined,
    });
    if (!ok) return;
    performClearAll();
  } finally {
    _clearAllBusy = false;
  }
}
[["btnClearAll", "btnMoreMenu"], ["btnClearAllTop", "btnToolbarMenu"]].forEach(function (pair) {
  const b = document.getElementById(pair[0]);
  if (b) {
    b.addEventListener("click", function () {
      // The listener cannot await, so surface a failure instead of leaving a floating rejection.
      _confirmClearAll(pair[1]).catch(function (e) {
        try { console.warn("commentable-html: clear all comments failed:", e); } catch (e2) { /* no-op */ }
      });
    });
  }
});
