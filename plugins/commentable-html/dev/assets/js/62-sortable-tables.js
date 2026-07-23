/* ---------- Sortable tables ----------
   Every column of an authored table (one with a real <thead>) gets up/down chevrons.
   Sorting reorders the <tbody> rows for display; numeric columns sort numerically.
   Reordering rows shifts the text-offset coordinate system, so after each sort we
   recompute every text comment's offsets from its live <mark>s and persist both the
   comments and the applied sort. The sort is re-applied on load BEFORE restore so the
   stored offsets always match the displayed order. */
const CMH_TABLE_SORT_KEY = COMMENT_KEY + "::tableSort";
let _tableSortState = {};
function _loadTableSortState() {
  try { _tableSortState = JSON.parse(localStorage.getItem(CMH_TABLE_SORT_KEY) || "{}"); }
  catch (e) { _tableSortState = {}; }
  if (!_tableSortState || typeof _tableSortState !== "object") _tableSortState = {};
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
function _parseNum(s) {
  if (s == null) return null;
  const t = String(s).replace(/[\s,$%]/g, "");
  if (t === "" || !/^[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?$/.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}
function _reorderBody(body, rows) {
  const frag = document.createDocumentFragment();
  rows.forEach(r => frag.appendChild(r));
  body.appendChild(frag);
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
function _indexTableRows() {
  _sortableTables().forEach(function (t) {
    const body = _tableBody(t);
    [...body.rows].forEach(function (r, ri) { if (r.dataset.cmhRow == null) r.dataset.cmhRow = String(ri); });
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
// reverted here because Portable and Offline exports save the moved widget DOM.
function _canonicalCommentsForExport() {
  if (!_tableSortState || Object.keys(_tableSortState).length === 0) {
    recomputeTextOffsets(false);
    return comments.map(function (c) { return Object.assign({}, c); });
  }
  const savedState = JSON.parse(JSON.stringify(_tableSortState));
  _sortableTables().forEach(function (t) { _unsortRows(_tableBody(t)); });
  recomputeTextOffsets(false);
  const snap = comments.map(function (c) { return Object.assign({}, c); });
  _sortableTables().forEach(function (t, i) {
    const st = savedState[_tableKey(t, i)];
    if (st) _sortRows(_tableBody(t), st.col, st.dir);
  });
  recomputeTextOffsets(false);
  return snap;
}
function _exportableComments() {
  return withoutHandled(_canonicalCommentsForExport());
}
// Runs BEFORE backfillContext/restoreHighlights: re-applies the last persisted sort so
// the DOM order matches the persisted comment offsets.
function applyPersistedTableSorts() {
  _loadTableSortState();
  _indexTableRows();
  _sortableTables().forEach(function (t, i) {
    const st = _tableSortState[_tableKey(t, i)];
    if (st && typeof st.col === "number" && (st.dir === "asc" || st.dir === "desc")) {
      _sortRows(_tableBody(t), st.col, st.dir);
    }
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
    const key = _tableKey(t, i);
    const hdr = _tableHeaderRow(t);
    const body = _tableBody(t);
    t.classList.add("cmh-sortable");
    const cur = _tableSortState[key] || null;
    [...hdr.cells].forEach(function (th, ci) {
      if (th.querySelector(".cmh-sort-ctrl")) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cmh-sort-ctrl cm-skip";
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
          const b2 = h2.querySelector(".cmh-sort-ctrl");
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
    const prevFocus = document.activeElement;
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
document.getElementById("btnClearAll").addEventListener("click", async () => {
  const stateChanges = (typeof widgetStateChanges === "function") ? widgetStateChanges() : [];
  const clChanges = (typeof checklistChanges === "function") ? checklistChanges() : [];
  const noteChanges = (typeof notesChanges === "function") ? notesChanges() : [];
  if (_clearAllBusy || (!comments.length && !stateChanges.length && !clChanges.length && !noteChanges.length)) return;  // guard re-entrant double-clicks
  _clearAllBusy = true;
  try {
    const ok = await showConfirm({
      message: comments.length
        ? `Delete all ${(typeof threadRoots === "function" ? threadRoots(comments).length : comments.length)} comment(s) and reset any tracked widget, checklist, and note changes? This cannot be undone.`
        : `Reset any tracked widget, checklist, and note changes? This cannot be undone.`,
      confirmLabel: "OK",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok) return;
    performClearAll();
  } finally {
    _clearAllBusy = false;
  }
});
