/* Editable tables own their model; sorting and runtime editors never become authored data. */
const CMH_TABLES_KEY = COMMENT_KEY + "::tables";
const editableTables = [];
const _ET_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/;
let _etTimer = 0;
let _etHadChanges = false;
let _etUnreadable = null;
let _etUnmatched = [];
const _etMenuPopup = {
  isOpen: () => !!root.querySelector(".cmh-table-column-actions[open]"),
  close: () => {
    const menu = root.querySelector(".cmh-table-column-actions[open]");
    if (menu) { menu.open = false; menu.querySelector("summary").focus(); }
  },
};
function _etClone(value) { return JSON.parse(JSON.stringify(value)); }
function _etEqual(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
function _etPendingEdit(t) { return !!(t.editBase && !_etEqual(t.editBase, t.model)); }
function _etNumber(value) { return value.trim() === "" || (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value.trim()) && Number.isFinite(Number(value))); }
function _etText(value) { return String(value).replace(/\r\n?/g, "\n"); }
function _etKeys(value, keys) {
  return value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === keys.length && keys.every(key => Object.prototype.hasOwnProperty.call(value, key));
}
function _etNormalizeModel(m) {
  const text = value => typeof value === "string" ? _etText(value) : value;
  if (m && Array.isArray(m.columns)) m.columns.forEach(c => {
    if (!c || typeof c !== "object") return;
    c.label = text(c.label); c.default = text(c.default);
    if (Array.isArray(c.options)) c.options = c.options.map(text);
  });
  if (m && Array.isArray(m.rows)) m.rows.forEach(r => {
    if (r && Array.isArray(r.cells)) r.cells = r.cells.map(text);
  });
  return m;
}
function _etValidModel(m) {
  if (!_etKeys(m, ["columns", "rows"]) || !Array.isArray(m.columns) || !m.columns.length || !Array.isArray(m.rows)) return false;
  const cols = new Set(), rows = new Set();
  for (const c of m.columns) {
    if (!_etKeys(c, ["id", "label", "type", "options", "default"].concat(Object.prototype.hasOwnProperty.call(c, "width") ? ["width"] : [])) || typeof c.id !== "string" || !_ET_ID.test(c.id) || cols.has(c.id)
      || typeof c.label !== "string" || !c.label.trim() || !["text", "number", "choice"].includes(c.type)
      || !Array.isArray(c.options) || typeof c.default !== "string") return false;
    if ("width" in c && (!Number.isInteger(c.width) || c.width < 96 || c.width > 4096)) return false;
    cols.add(c.id);
    if (c.type !== "choice") {
      if (c.options.length || c.default !== "") return false;
    } else if (!c.options.length || c.options.some(v => typeof v !== "string" || !v.trim())
      || new Set(c.options).size !== c.options.length || (c.default !== "" && !c.options.includes(c.default))) return false;
  }
  for (const r of m.rows) {
    if (!_etKeys(r, ["id", "cells"]) || typeof r.id !== "string" || !_ET_ID.test(r.id) || rows.has(r.id)
      || !Array.isArray(r.cells) || r.cells.length !== m.columns.length) return false;
    rows.add(r.id);
    if (r.cells.some((v, i) => typeof v !== "string"
      || (m.columns[i].type === "choice" && v !== "" && !m.columns[i].options.includes(v))
      || (m.columns[i].type === "number" && !_etNumber(v)))) return false;
  }
  return true;
}
function _etRead(table) {
  if (table.tagName !== "TABLE" || [...table.children].filter(el => el.tagName === "THEAD").length !== 1
    || !table.tHead || table.tHead.rows.length !== 1
    || table.tBodies.length !== 1 || table.tFoot || table.querySelector("table, [colspan], [rowspan]")
    || table.matches("[data-cmh-note], [data-cmh-checklist], [data-cm-widget], .cmh-diff")
    || [...table.children].some(el => !["CAPTION", "THEAD", "TBODY"].includes(el.tagName))
    || table.querySelector("[data-cmh-note], [data-cmh-checklist], [data-cm-widget], .cmh-diff")
    || table.parentElement.closest("[data-cmh-table], [data-cmh-note], [data-cmh-checklist], [data-cm-widget], .cmh-diff")) return null;
  const heads = [...table.tHead.rows[0].cells];
  const nonText = el => [...el.childNodes].some(node => node.nodeType !== 3);
  if (heads.some(el => el.tagName !== "TH" || nonText(el))) return null;
  const model = {
    columns: heads.map(el => {
      const type = el.getAttribute("data-cmh-column-type") || "text";
      const column = {
        id: el.getAttribute("data-cmh-column") || "", label: _etText(el.textContent), type,
        options: type === "choice" ? JSON.parse(el.getAttribute("data-cmh-options") || "null") : [],
        default: type === "choice" ? (el.getAttribute("data-cmh-default") || "") : "",
      };
      if (el.hasAttribute("data-cmh-width")) {
        const width = el.getAttribute("data-cmh-width");
        if (!/^[0-9]+$/.test(width)) throw new Error("Column width must be an integer");
        column.width = Number(width);
      }
      return column;
    }),
    rows: [...table.tBodies[0].rows].map(row => {
      if ([...row.cells].some(el => el.tagName !== "TD" || nonText(el))) throw new Error("Cells must contain plain text");
      return { id: row.getAttribute("data-cmh-row") || "", cells: [...row.cells].map(el => _etText(el.textContent)) };
    }),
  };
  _etNormalizeModel(model);
  return _etValidModel(model) ? model : null;
}
function tableChanges() {
  return editableTables.filter(t => !_etEqual(t.baseline, t.model)).map(t => ({
    id: t.id, label: t.label, from: t.baseline, to: t.model,
  }));
}
function _etSave() {
  if (_etUnreadable !== null) return false;
  const entries = tableChanges().concat(editableTables.filter(t => t.stale).map(t => t.stale), _etUnmatched);
  const ok = cmhTrySetItem(CMH_TABLES_KEY, () => entries.length ? JSON.stringify({ version: 1, tables: entries }) : null, "Table edits");
  if (!ok) cmhStorageFullToast(CMH_TABLES_KEY, "Table edits");
  return ok;
}
function _etFlush() {
  clearTimeout(_etTimer); _etTimer = 0;
  renderComments();
}
function _etChanged(t, deferred) {
  const ok = _etSave();
  t.status.textContent = ok ? "Saved in this browser. Export HTML to carry these edits."
    : "Not saved in this browser. Copy all or export HTML before closing.";
  _etHistoryButtons(t);
  const has = tableChanges().length > 0;
  if (has !== _etHadChanges) {
    _etHadChanges = has;
    updateDocTypeUi(); updateCopyAllState();
    if (has && !document.body.classList.contains("cmh-deck-comments-off") && cmhShouldAutoOpenPanel()) openSidebar();
  }
  if (deferred) {
    clearTimeout(_etTimer);
    _etTimer = setTimeout(_etFlush, 150);
  } else _etFlush();
}
function _etRemember(t, before) {
  if (_etEqual(before, t.model)) return;
  t.history.push(_etClone(before));
  if (t.history.length > 50) t.history.shift();
  t.future.length = 0;
}
function _etCommitEditor(t) {
  if (!t.editBase) return;
  _etRemember(t, t.editBase);
  t.editBase = null; t.editFuture = null;
  _etHistoryButtons(t);
}
function _etHistoryButtons(t) {
  const previous = _etPendingEdit(t) ? t.editBase : t.history[t.history.length - 1];
  const next = t.future[t.future.length - 1];
  [[t.undo, previous, t.model, "Undo"], [t.redo, t.model, next, "Redo"]].forEach(([button, from, to, label]) => {
    button.disabled = !from || !to;
    const lines = button.disabled ? [] : _etDiff({ from, to });
    const detail = lines.length ? lines[0].slice(0, 240) + (lines.length > 1 ? " (+" + (lines.length - 1) + " more)" : "") : "Nothing to " + label.toLowerCase();
    button.removeAttribute("title");
    button.setAttribute("data-cmh-tip", label + ": " + detail);
    if (window.__cmhRefreshTip) window.__cmhRefreshTip(button);
  });
}
function _etMutate(t, change, focus) {
  if (t.stale || _etUnreadable !== null) return;
  _etCommitEditor(t);
  const before = _etClone(t.model);
  change();
  _etRemember(t, before);
  _etRender(t);
  _etChanged(t);
  _etFocus(t, focus);
}
function _etFocus(t, target) {
  let el = target && t.table.querySelector(target);
  if (!el) el = t.table.querySelector("textarea, select, input") || t.addRow;
  el.focus();
}
function _etBtn(text, fn) {
  const b = document.createElement("button");
  b.type = "button"; b.textContent = text;
  const icons = {
    "Add row": "M4 3h16v10H4zM4 8h16M12 16v6m-3-3h6",
    "Add column": "M3 4h10v16H3zM8 4v16M16 12h6m-3-3v6",
    Undo: "M9 5 4 10l5 5M4 10h10a6 6 0 0 1 6 6v3",
    Redo: "m15 5 5 5-5 5m5-5H10a6 6 0 0 0-6 6v3",
    "Rename column": "m15 4 5 5M4 20l5-1L21 7l-4-4L5 15z",
    "Insert column before": "M13 3h7v18h-7zM3 12h7m-3.5-3.5v7",
    "Insert column after": "M4 3h7v18H4zM14 12h7m-3.5-3.5v7",
    "Move column left": "m10 5-7 7 7 7M3 12h18",
    "Move column right": "m14 5 7 7-7 7M3 12h18",
    "Remove column": "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7",
    New: "M12 5v14M5 12h14",
    "Autofit width": "M8 5H3v14h5m8-14h5v14h-5M9 9l-3 3 3 3m6-6 3 3-3 3M6 12h12",
    "Comment on cell": "M4 4h16v12H9l-5 4zM8 8h8m-8 4h5",
  };
  if (icons[text]) {
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("viewBox", "0 0 24 24"); icon.setAttribute("width", "16"); icon.setAttribute("height", "16");
    icon.setAttribute("aria-hidden", "true"); icon.setAttribute("focusable", "false");
    icon.setAttribute("fill", "none"); icon.setAttribute("stroke", "currentColor"); icon.setAttribute("stroke-width", "1.7");
    icon.setAttribute("stroke-linecap", "round"); icon.setAttribute("stroke-linejoin", "round");
    const path = document.createElementNS(icon.namespaceURI, "path"); path.setAttribute("d", icons[text]); icon.append(path); b.prepend(icon);
  }
  cmhMarkLayerChrome(b);
  b.addEventListener("click", fn);
  return b;
}
function _etId(t, kind) {
  const taken = t.identities[kind];
  let id;
  do { id = "new-" + (++t.seq); } while (taken.has(id));
  taken.add(id);
  return id;
}
function _etAddRow(t, beforeId) {
  if (t.stale || _etUnreadable !== null) return;
  const row = { id: _etId(t, "rows"), cells: t.model.columns.map(c => c.default) };
  // Reveal the new row rather than leaving it buried in a sorted view.
  t.sort = null;
  const index = beforeId ? t.model.rows.findIndex(r => r.id === beforeId) : t.model.rows.length;
  if (index < 0) return;
  _etMutate(t, () => t.model.rows.splice(index, 0, row), '[data-cmh-row="' + _cssEsc(row.id) + '"] :is(textarea, select, input)');
}
async function _etRemoveRow(t, row, number) {
  const untouchedNew = !t.baseline.rows.some(r => r.id === row.id)
    && row.cells.every((v, i) => v === t.model.columns[i].default);
  if (!untouchedNew && row.cells.some(v => v !== "") && !(await showConfirm({
    message: "Remove row " + number + " and its values? Undo can restore it in this session.", confirmLabel: "Remove", danger: true,
  }))) return;
  const i = t.model.rows.indexOf(row);
  if (i < 0) return;
  const displayed = [...t.table.tBodies[0].rows].map(el => el.getAttribute("data-cmh-row"));
  const position = displayed.indexOf(row.id);
  const nextId = displayed[position + 1] || displayed[position - 1];
  const focus = nextId ? '[data-cmh-row="' + _cssEsc(nextId) + '"] :is(textarea, select, input)' : null;
  _etMutate(t, () => t.model.rows.splice(i, 1), focus);
}
async function _etRemoveColumn(t, id) {
  if (t.model.columns.length === 1) return;
  const index = t.model.columns.findIndex(c => c.id === id);
  if (index < 0) return;
  if (t.model.rows.some(r => r.cells[index] !== "") && !(await showConfirm({
    message: 'Remove column "' + t.model.columns[index].label + '" and all its values? Undo can restore it in this session.',
    confirmLabel: "Remove", danger: true,
  }))) return;
  const nextId = (t.model.columns[index + 1] || t.model.columns[index - 1]).id;
  _etMutate(t, () => {
    t.model.columns.splice(index, 1);
    t.model.rows.forEach(r => r.cells.splice(index, 1));
    if (t.sort && t.sort.id === id) t.sort = null;
  }, '[data-cmh-column="' + _cssEsc(nextId) + '"] .cmh-sort-ctrl');
}
function _etColumnDialog(t, renameId, besideId, before = false) {
  const existing = renameId && t.model.columns.find(c => c.id === renameId);
  const dialog = document.createElement("dialog");
  dialog.className = "cmh-table-dialog cm-skip";
  dialog.addEventListener("keydown", e => { if (e.key === "Escape") e.stopPropagation(); });
  dialog.setAttribute("aria-label", existing ? "Rename column" : "Add column");
  const form = document.createElement("form");
  const heading = document.createElement("h2");
  heading.textContent = existing ? "Rename column" : "Add column";
  const header = document.createElement("div"); header.className = "cmh-table-dialog-head";
  header.append(heading);
  header.insertAdjacentHTML("beforeend", CMH_ICON_SVG);
  header.querySelector("svg").removeAttribute("data-cmh-tip");
  form.append(header);
  function field(text, el) {
    const label = document.createElement("label");
    const caption = document.createElement("span");
    caption.textContent = text;
    label.append(caption, el); form.append(label);
    return el;
  }
  const name = field("Column name", document.createElement("input"));
  name.required = true; name.value = existing ? existing.label : "";
  const type = document.createElement("select");
  ["text", "number", "choice"].forEach(value => {
    const option = document.createElement("option"); option.value = value;
    option.textContent = value === "choice" ? "Single choice" : value === "number" ? "Number" : "Text"; type.append(option);
  });
  const options = document.createElement("textarea");
  options.rows = 4;
  const def = document.createElement("input");
  if (!existing) {
    field("Column type", type);
    field("Choices (one per line)", options);
    field("Default choice (optional)", def);
    const sync = () => {
      options.parentElement.hidden = def.parentElement.hidden = type.value !== "choice";
    };
    type.addEventListener("change", sync); sync();
  }
  const error = document.createElement("p"); error.setAttribute("role", "alert");
  form.append(error);
  const actions = document.createElement("div"); actions.className = "cmh-table-actions";
  const cancel = _etBtn("Cancel", () => dialog.close());
  const save = document.createElement("button"); save.type = "submit"; save.textContent = "Save"; save.className = "cmh-table-save";
  actions.append(save, cancel); form.append(actions); dialog.append(form);
  const previous = document.activeElement;
  let applied = false;
  dialog.addEventListener("close", () => {
    dialog.remove();
    if (applied) return;
    if (previous && previous.isConnected) previous.focus(); else t.addColumn.focus();
  });
  form.addEventListener("submit", e => {
    e.preventDefault();
    const label = name.value.trim();
    if (!label) { error.textContent = "Enter a column name."; return; }
    const column = { id: existing ? existing.id : _etId(t, "columns"), label,
      type: existing ? existing.type : type.value,
      options: existing ? existing.options : type.value === "choice" ? _etText(options.value).split("\n") : [],
      default: existing ? existing.default : type.value === "choice" ? def.value : "" };
    if (!_etValidModel({ columns: [column], rows: [] })) {
      error.textContent = "Enter unique, non-empty choices, and leave the default empty or use an exact choice."; return;
    }
    applied = true;
    dialog.close();
    _etMutate(t, () => {
      if (existing) t.model.columns.find(c => c.id === existing.id).label = label;
      else {
        const index = besideId ? t.model.columns.findIndex(c => c.id === besideId) + (before ? 0 : 1) : t.model.columns.length;
        t.model.columns.splice(index, 0, column);
        t.model.rows.forEach(r => r.cells.splice(index, 0, column.default));
      }
    }, existing || !t.model.rows.length
      ? '[data-cmh-column="' + _cssEsc(column.id) + '"] .cmh-sort-ctrl'
      : '[data-cmh-edit-column="' + _cssEsc(column.id) + '"]');
  });
  document.body.append(dialog); dialog.showModal(); name.focus();
}
function _etGrow(el) {
  el.style.height = "auto";
  el.style.height = Math.min(280, Math.max(40, el.scrollHeight)) + "px";
}
function _etIsAnchor(value) { return value && (value.anchorType === "table-column" || value.anchorType === "table-cell"); }
function findTableColumn(info) {
  const t = editableTables.find(t => t.id === info.tableId);
  if (info.anchorType === "table-cell" || info.rowId !== undefined) {
    return t && typeof info.rowId === "string" && typeof info.columnId === "string"
      ? t.table.querySelector('[data-cmh-row="' + _cssEsc(info.rowId) + '"] [data-cmh-cell-column="' + _cssEsc(info.columnId) + '"]') : null;
  }
  return t && typeof info.columnId === "string"
    ? t.table.querySelector('[data-cmh-column="' + _cssEsc(info.columnId) + '"] .cmh-table-title') : null;
}
function _etAnchorOrder(info) {
  const index = editableTables.findIndex(t => t.id === info.tableId), t = editableTables[index];
  if (!t) return editableTables.length * 1e6;
  const ci = t.model.columns.findIndex(c => c.id === info.columnId);
  const ri = info.anchorType === "table-cell" ? t.model.rows.findIndex(r => r.id === info.rowId) : -1;
  const row = info.anchorType === "table-cell" ? (ri < 0 ? t.model.rows.length + 1 : ri + 1) : 0;
  return (index + (row + ((ci < 0 ? t.model.columns.length : ci) + 1) / (t.model.columns.length + 2))
    / (t.model.rows.length + 3)) * 1e6;
}
function _etTitleHighlights() {
  editableTables.forEach(t => t.table.querySelectorAll(".cmh-table-title, .cmh-table-data-cell").forEach(el => {
    const cell = el.classList.contains("cmh-table-data-cell");
    const columnId = cell ? el.getAttribute("data-cmh-cell-column") : el.closest("th").getAttribute("data-cmh-column");
    const ids = comments.filter(c => !c.parentId && c.anchorType === (cell ? "table-cell" : "table-column")
      && c.tableId === t.id && c.columnId === columnId && (!cell || c.rowId === el.closest("tr").getAttribute("data-cmh-row"))).map(c => c.id);
    if (ids.length) { el.setAttribute("data-cids", ids.join(" ")); el.setAttribute("data-cid", ids[0]); }
    else { el.removeAttribute("data-cids"); el.removeAttribute("data-cid"); }
  }));
}
function clearTableColumnHighlight(comment) {
  const title = findTableColumn(comment);
  if (!title) return;
  const ids = (title.getAttribute("data-cids") || "").split(/\s+/).filter(id => id && id !== comment.id);
  if (ids.length) { title.setAttribute("data-cids", ids.join(" ")); title.setAttribute("data-cid", ids[0]); }
  else { title.removeAttribute("data-cids"); title.removeAttribute("data-cid"); title.classList.remove("cm-active"); }
}
function _etSortButton(t, th, id, label) {
  const sort = _etBtn("", () => {
    const dir = t.sort && t.sort.id === id ? (t.sort.dir === "asc" ? "desc" : null) : "asc";
    t.sort = dir ? { id, dir } : null;
    _etRender(t);
    const header = id === null ? t.table.tHead.rows[0].cells[0]
      : t.table.querySelector('[data-cmh-column="' + _cssEsc(id) + '"]');
    header.querySelector(".cmh-sort-ctrl").focus();
  });
  sort.className = "cmh-sort-ctrl cm-skip";
  sort.title = "Sort by this column"; sort.setAttribute("aria-label", label);
  sort.innerHTML = '<span class="cmh-sort-up" aria-hidden="true"></span><span class="cmh-sort-dn" aria-hidden="true"></span>';
  th.append(sort);
  _reflectSortIco(sort, t.sort && t.sort.id === id ? t.sort.dir : null);
}
function _etMoveColumn(t, id, destination) {
  const source = t.model.columns.findIndex(c => c.id === id);
  if (source < 0 || destination < 0 || destination >= t.model.columns.length || source === destination) return;
  _etMutate(t, () => {
    t.model.columns.splice(destination, 0, t.model.columns.splice(source, 1)[0]);
    t.model.rows.forEach(row => row.cells.splice(destination, 0, row.cells.splice(source, 1)[0]));
  }, '[data-cmh-column="' + _cssEsc(id) + '"] .cmh-table-drag');
}
function _etColumnGrip(t, column, index) {
  const grip = _etBtn("", () => {});
  grip.className = "cmh-table-drag";
  grip.setAttribute("aria-label", "Reorder " + column.label + ", column " + (index + 1));
  grip.title = "Drag to reorder. Use Left/Right arrow keys, or Move column in the column menu.";
  grip.innerHTML = '<svg width="14" height="16" viewBox="0 0 14 16" fill="currentColor" aria-hidden="true"><path d="M3 2h2v2H3zm6 0h2v2H9zM3 7h2v2H3zm6 0h2v2H9zM3 12h2v2H3zm6 0h2v2H9z"/></svg>';
  const rtl = () => getComputedStyle(t.table).direction === "rtl";
  grip.addEventListener("keydown", e => {
    if (grip.disabled || !["ArrowLeft", "ArrowRight"].includes(e.key) || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    const delta = (e.key === "ArrowRight" ? 1 : -1) * (rtl() ? -1 : 1);
    _etMoveColumn(t, column.id, t.model.columns.findIndex(c => c.id === column.id) + delta);
  });
  grip.addEventListener("pointerdown", start => {
    if (grip.disabled || start.button !== 0 || !start.isPrimary) return;
    if (t.cancelDrag) t.cancelDrag();
    start.preventDefault();
    const scroll = t.table.closest(".cmh-table-scroll, .cmh-editable-table-scroll");
    let active = false, x = start.clientX, y = start.clientY, destination = null, frame;
    function clearMarker() {
      t.table.querySelectorAll(".cmh-table-drop-before, .cmh-table-drop-after").forEach(el => el.classList.remove("cmh-table-drop-before", "cmh-table-drop-after"));
    }
    function locate() {
      clearMarker(); destination = null;
      const bounds = scroll.getBoundingClientRect();
      if (x < bounds.left || x > bounds.right || y < bounds.top || y > bounds.bottom) return;
      const header = document.elementFromPoint(x, y)?.closest("th[data-cmh-column]");
      if (!header || !t.table.tHead.contains(header)) return;
      const rect = header.getBoundingClientRect(), before = (x < (rect.left + rect.right) / 2) !== rtl();
      const source = t.model.columns.findIndex(c => c.id === column.id);
      const boundary = t.model.columns.findIndex(c => c.id === header.getAttribute("data-cmh-column")) + (before ? 0 : 1);
      destination = boundary - (source < boundary ? 1 : 0);
      if (destination !== source) header.classList.add(before ? "cmh-table-drop-before" : "cmh-table-drop-after");
    }
    function tick() {
      if (active) {
        const bounds = scroll.getBoundingClientRect();
        if (x >= bounds.left && x <= bounds.right && y >= bounds.top && y <= bounds.bottom) {
          const step = x < bounds.left + 28 ? -12 : x > bounds.right - 28 ? 12 : 0;
          if (step) scroll.scrollBy(step, 0);
        }
        locate();
      }
      frame = requestAnimationFrame(tick);
    }
    function cleanup() {
      cancelAnimationFrame(frame); clearMarker(); grip.classList.remove("cmh-table-drag-active");
      document.removeEventListener("pointermove", move, true);
      document.removeEventListener("pointerup", end, true);
      document.removeEventListener("pointercancel", cancel, true);
      document.removeEventListener("keydown", escape, true);
      grip.removeEventListener("lostpointercapture", cancel);
      t.cancelDrag = null;
      if (grip.hasPointerCapture(start.pointerId)) grip.releasePointerCapture(start.pointerId);
    }
    function move(e) {
      if (e.pointerId !== start.pointerId) return;
      x = e.clientX; y = e.clientY;
      if (!active && Math.hypot(x - start.clientX, y - start.clientY) >= 5) {
        active = true; _cmTipHide(); grip.classList.add("cmh-table-drag-active");
      }
      if (active) { e.preventDefault(); locate(); }
    }
    function end(e) {
      if (e.pointerId !== start.pointerId) return;
      x = e.clientX; y = e.clientY;
      if (active) locate();
      const target = active ? destination : null;
      cleanup();
      if (target !== null) _etMoveColumn(t, column.id, target);
      else grip.focus();
    }
    function cancel(e) { if (e.pointerId === start.pointerId) cleanup(); }
    function escape(e) {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cleanup(); }
    }
    t.cancelDrag = cleanup;
    document.addEventListener("pointermove", move, true);
    document.addEventListener("pointerup", end, true);
    document.addEventListener("pointercancel", cancel, true);
    document.addEventListener("keydown", escape, true);
    grip.addEventListener("lostpointercapture", cancel);
    try { grip.setPointerCapture(start.pointerId); } catch (e) { /* Document listeners also handle uncaptured pointers. */ }
    frame = requestAnimationFrame(tick);
  });
  return grip;
}
function _etWidth(columns, extra, preview) {
  const widths = columns.map(c => preview && preview.id === c.id ? preview.width : c.width);
  const total = widths.reduce((sum, width) => sum + (width === undefined ? 196 : width), extra);
  return widths.includes(undefined) ? "max(100%, " + total + "px)" : total + "px";
}
function _etLayout(t, preview) {
  const sized = preview || t.model.columns.some(c => c.width !== undefined);
  t.table.style.tableLayout = sized ? "fixed" : t.originalSizing.layout;
  t.table.style.width = sized ? _etWidth(t.model.columns, 83, preview) : t.originalSizing.width;
  [...t.table.tHead.rows[0].cells].forEach(th => {
    const column = t.model.columns.find(c => c.id === th.getAttribute("data-cmh-column"));
    const width = column ? (preview && preview.id === column.id ? preview.width : column.width) : 41;
    th.style.boxSizing = "border-box";
    th.style.width = sized && width !== undefined ? width + "px" : "";
  });
  t.table.classList.toggle("cmh-table-sized", !!sized);
  t.table.querySelectorAll(".cmh-table-resize").forEach(handle => {
    handle.setAttribute("aria-valuenow", String(handle.closest("th").offsetWidth));
  });
}
function _etSetWidth(t, id, width) {
  const column = t.model.columns.find(c => c.id === id);
  width = Math.max(96, Math.min(4096, Math.round(width)));
  if (!column || column.width === width) return;
  _etMutate(t, () => { column.width = width; }, '[data-cmh-column="' + _cssEsc(id) + '"] .cmh-table-resize');
}
function _etAutofit(t, id) {
  const index = t.model.columns.findIndex(c => c.id === id), column = t.model.columns[index];
  if (!column) return;
  const context = document.createElement("canvas").getContext("2d");
  const editor = t.table.querySelector("textarea, select, input") || t.table;
  context.font = getComputedStyle(editor).font;
  const values = [column.label, ...column.options, ...t.model.rows.map(r => r.cells[index])];
  let width = 0;
  values.forEach(value => value.split("\n").forEach(line => { width = Math.max(width, context.measureText(line).width); }));
  _etSetWidth(t, id, Math.min(Math.max(240, innerWidth - 80), width + 108));
}
function _etResizeHandle(t, column, index) {
  const handle = document.createElement("span");
  handle.className = "cmh-table-resize"; handle.tabIndex = 0;
  cmhMarkLayerChrome(handle);
  handle.setAttribute("role", "separator"); handle.setAttribute("aria-orientation", "vertical");
  handle.setAttribute("aria-label", "Resize " + column.label + ", column " + (index + 1));
  handle.setAttribute("aria-valuemin", "96"); handle.setAttribute("aria-valuemax", "4096");
  const current = () => handle.closest("th").offsetWidth;
  handle.addEventListener("focus", () => handle.setAttribute("aria-valuenow", String(current())));
  handle.addEventListener("keydown", e => {
    if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    e.preventDefault();
    _etSetWidth(t, column.id, current() + (e.key === "ArrowRight" ? 16 : -16) * (getComputedStyle(t.table).direction === "rtl" ? -1 : 1));
  });
  handle.addEventListener("dblclick", () => _etAutofit(t, column.id));
  handle.addEventListener("pointerdown", start => {
    if (t.stale || _etUnreadable !== null || start.button !== 0 || !start.isPrimary) return;
    if (t.cancelDrag) t.cancelDrag();
    start.preventDefault(); _etCommitEditor(t);
    const th = handle.closest("th"), original = current(), scale = th.getBoundingClientRect().width / original;
    const direction = getComputedStyle(t.table).direction === "rtl" ? -1 : 1;
    let width = original;
    function move(e) {
      if (e.pointerId !== start.pointerId) return;
      width = Math.max(96, Math.min(4096, Math.round(original + (e.clientX - start.clientX) / scale * direction)));
      _etLayout(t, { id: column.id, width });
    }
    function cleanup() {
      document.removeEventListener("pointermove", move, true); document.removeEventListener("pointerup", end, true);
      document.removeEventListener("pointercancel", cancel, true); document.removeEventListener("keydown", escape, true);
      handle.removeEventListener("lostpointercapture", cancel); t.cancelDrag = null;
      if (handle.hasPointerCapture(start.pointerId)) handle.releasePointerCapture(start.pointerId);
      _etLayout(t);
    }
    function end(e) {
      if (e.pointerId !== start.pointerId) return;
      move(e); cleanup();
      if (width !== original) _etSetWidth(t, column.id, width);
    }
    function cancel(e) { if (e.pointerId === start.pointerId) cleanup(); }
    function escape(e) { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cleanup(); } }
    t.cancelDrag = cleanup;
    document.addEventListener("pointermove", move, true); document.addEventListener("pointerup", end, true);
    document.addEventListener("pointercancel", cancel, true); document.addEventListener("keydown", escape, true);
    handle.addEventListener("lostpointercapture", cancel);
    try { handle.setPointerCapture(start.pointerId); } catch (e) { /* Document listeners retain cancellation. */ }
  });
  return handle;
}
function _etRender(t) {
  if (t.cancelDrag) t.cancelDrag();
  if (t.sort && t.sort.id !== null && !t.model.columns.some(c => c.id === t.sort.id)) t.sort = null;
  const doc = document;
  const head = doc.createElement("thead"), hr = doc.createElement("tr");
  const number = doc.createElement("th"); number.textContent = "#"; number.scope = "col";
  number.className = "cmh-table-number"; _etSortButton(t, number, null, "Sort by row number"); hr.append(number);
  t.model.columns.forEach((c, ci) => {
    const th = doc.createElement("th"); th.scope = "col"; th.setAttribute("data-cmh-column", c.id);
    const label = _etBtn(c.label, () => {
      label.focus();
      createComposerElement({ mode: "new-table-column", tableColumn: { tableId: t.id, columnId: c.id, quote: c.label } });
    });
    label.className = "cmh-table-title"; label.title = "Comment on this column title";
    label.setAttribute("aria-label", "Comment on " + c.label + ", column " + (ci + 1));
    const header = doc.createElement("div"); header.className = "cmh-table-header";
    const tools = doc.createElement("span"); tools.className = "cmh-table-header-actions";
    header.append(_etColumnGrip(t, c, ci), label, tools);
    th.append(header, _etResizeHandle(t, c, ci));
    _etSortButton(t, tools, c.id, "Sort by " + c.label + ", column " + (ci + 1));
    const menu = doc.createElement("details"); menu.className = "cmh-table-column-actions";
    const summary = doc.createElement("summary");
    summary.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><circle cx="8" cy="3" r="1.5"/><circle cx="8" cy="8" r="1.5"/><circle cx="8" cy="13" r="1.5"/></svg>';
    summary.setAttribute("aria-label", "Actions for " + c.label + ", column " + (ci + 1));
    summary.title = "Column actions";
    cmhMarkLayerChrome(summary);
    const panel = doc.createElement("div"); panel.className = "cmh-table-column-menu";
    panel.setAttribute("popover", "manual");
    panel.append(_etBtn("Rename column", () => { menu.open = false; summary.focus(); _etColumnDialog(t, c.id); }),
      _etBtn("Insert column before", () => { menu.open = false; summary.focus(); _etColumnDialog(t, null, c.id, true); }),
      _etBtn("Insert column after", () => { menu.open = false; summary.focus(); _etColumnDialog(t, null, c.id); }));
    [["left", -1], ["right", 1]].forEach(([direction, delta]) => {
      const move = _etBtn("Move column " + direction, () => {
        menu.open = false; summary.focus(); _etMoveColumn(t, c.id, ci + delta * (getComputedStyle(t.table).direction === "rtl" ? -1 : 1));
      });
      const target = ci + delta * (getComputedStyle(t.table).direction === "rtl" ? -1 : 1);
      move.disabled = target < 0 || target >= t.model.columns.length;
      panel.append(move);
    });
    const remove = _etBtn("Remove column", () => { menu.open = false; summary.focus(); _etRemoveColumn(t, c.id); });
    remove.disabled = t.model.columns.length === 1;
    if (remove.disabled) remove.title = "Keep at least one data column.";
    panel.append(_etBtn("Autofit width", () => { menu.open = false; summary.focus(); _etAutofit(t, c.id); }), remove); menu.append(summary, panel);
    menu.addEventListener("toggle", () => {
      if (!menu.open) { panel.hidePopover(); return; }
      root.querySelectorAll(".cmh-table-column-actions[open]").forEach(other => { if (other !== menu) other.open = false; });
      panel.showPopover();
      window.__cmhPrioritizeEscapePopup(_etMenuPopup);
      const rect = summary.getBoundingClientRect();
      panel.style.left = Math.max(8, Math.min(rect.right - panel.offsetWidth, innerWidth - panel.offsetWidth - 8)) + "px";
      panel.style.top = Math.max(8, Math.min(rect.bottom + 4, innerHeight - panel.offsetHeight - 8)) + "px";
    });
    menu.addEventListener("focusout", e => {
      if (e.relatedTarget && !menu.contains(e.relatedTarget)) menu.open = false;
    });
    menu.addEventListener("keydown", e => { if (e.key === "Escape") { menu.open = false; summary.focus(); e.stopPropagation(); } });
    tools.append(menu); hr.append(th);
  });
  const actions = doc.createElement("th"); actions.setAttribute("aria-label", "Row actions");
  actions.className = "cmh-table-remove-cell"; actions.scope = "col"; hr.append(actions);
  head.append(hr);
  const body = doc.createElement("tbody");
  const displayed = t.model.rows.slice();
  if (t.sort && t.sort.id === null) {
    if (t.sort.dir === "desc") displayed.reverse();
  } else if (t.sort) {
    const ci = t.model.columns.findIndex(c => c.id === t.sort.id);
    const values = new Map(displayed.map(r => [r.id, r.cells[ci].replace(/\s+/g, " ").trim()]));
    const numeric = [...values.values()].every(value => value === "" || _parseNum(value) !== null)
      && [...values.values()].some(value => value !== "");
    displayed.sort((a, b) => {
      const av = values.get(a.id), bv = values.get(b.id);
      const numberColumn = t.model.columns[ci].type === "number";
      const compared = numeric || numberColumn ? (av === "" ? -1 : bv === "" ? 1 : numberColumn ? Number(av) - Number(bv) : _parseNum(av) - _parseNum(bv))
        : av.localeCompare(bv, undefined, { numeric: true, sensitivity: "base" });
      return (av === bv ? 0 : compared) * (t.sort.dir === "asc" ? 1 : -1);
    });
  }
  displayed.forEach(row => {
    const rowNumber = t.model.rows.indexOf(row) + 1;
    const tr = doc.createElement("tr"); tr.setAttribute("data-cmh-row", row.id);
    const rn = doc.createElement("th"); rn.scope = "row"; rn.className = "cmh-table-number";
    rn.textContent = String(rowNumber);
    const insert = _etBtn("New", () => _etAddRow(t, row.id));
    insert.lastChild.remove();
    insert.className = "cmh-table-row-insert"; insert.setAttribute("aria-label", "Insert row before row " + rowNumber);
    insert.title = "Insert row here"; rn.append(insert); tr.append(rn);
    t.model.columns.forEach((c, ci) => {
      const td = doc.createElement("td"); td.className = "cmh-table-data-cell";
      td.setAttribute("data-cmh-cell-column", c.id);
      const input = doc.createElement(c.type === "choice" ? "select" : c.type === "number" ? "input" : "textarea");
      if (c.type === "choice") {
        const labels = new Set(c.options.map(value => value.replace(/\s+/g, " ").trim()));
        let emptyLabel = "(empty)";
        while (labels.has(emptyLabel)) emptyLabel += " (no value)";
        ["", ...c.options].forEach(value => {
          const option = doc.createElement("option"); option.value = value;
          option.textContent = value === "" ? emptyLabel : value; input.append(option);
        });
      } else if (c.type === "number") { input.type = "text"; input.inputMode = "decimal"; }
      else input.rows = 1;
      input.value = row.cells[ci];
      const print = doc.createElement("span"); print.className = "cmh-table-print-value"; print.textContent = row.cells[ci];
      input.setAttribute("data-cmh-edit-column", c.id);
      input.setAttribute("aria-label", c.label + ", column " + (ci + 1) + ", row " + rowNumber);
      cmhMarkLayerChrome(input);
      const beginEdit = () => {
        if (!t.editBase) { t.editBase = _etClone(t.model); t.editFuture = t.future.slice(); }
      };
      input.addEventListener("focus", beginEdit);
      const onInput = () => {
        beginEdit();
        if (c.type === "number" && !_etNumber(input.value)) {
          row.cells[ci] = t.editBase.rows.find(r => r.id === row.id).cells[ci];
          print.textContent = row.cells[ci];
          t.future = t.editFuture.slice();
          _etChanged(t, true);
          input.setAttribute("aria-invalid", "true");
          t.status.textContent = "Enter a number, such as -2.5 or 1e2. Invalid input is not saved.";
          return;
        }
        input.removeAttribute("aria-invalid");
        row.cells[ci] = _etText(input.value);
        if (_etPendingEdit(t)) t.future.length = 0;
        print.textContent = row.cells[ci];
        if (input.tagName === "TEXTAREA") _etGrow(input);
        _etChanged(t, true);
      };
      input.addEventListener("input", onInput);
      input.addEventListener("change", () => { onInput(); _etCommitEditor(t); });
      input.addEventListener("blur", () => {
        if (input.getAttribute("aria-invalid") === "true") {
          input.value = row.cells[ci]; input.removeAttribute("aria-invalid");
          t.status.textContent = "Enter a number. Previous value restored.";
        }
        _etCommitEditor(t);
      });
      const comment = _etBtn("Comment on cell", () => {
        createComposerElement({ mode: "new-table-column", tableColumn: {
          tableId: t.id, columnId: c.id, rowId: row.id, quote: row.cells[ci],
        } });
      });
      comment.lastChild.remove(); comment.className = "cmh-table-cell-comment";
      comment.setAttribute("aria-label", "Comment on " + c.label + ", column " + (ci + 1) + ", row " + rowNumber);
      comment.title = "Comment on this cell";
      td.append(input, print, comment); tr.append(td);
    });
    const td = doc.createElement("td"), remove = _etBtn("", () => _etRemoveRow(t, row, rowNumber));
    td.className = "cmh-table-remove-cell"; remove.className = "cmh-table-remove";
    remove.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/></svg>';
    remove.title = "Remove row " + rowNumber;
    remove.setAttribute("aria-label", remove.title); td.append(remove); tr.append(td); body.append(tr);
  });
  if (t.table.tHead) t.table.tHead.remove();
  [...t.table.tBodies].forEach(b => b.remove());
  t.table.append(head, body);
  _etLayout(t);
  _etTitleHighlights();
  t.empty.hidden = !!t.model.rows.length;
  _etHistoryButtons(t);
  t.addBottom.disabled = !!t.stale || _etUnreadable !== null;
  t.table.querySelectorAll("textarea").forEach(_etGrow);
}
function _etDiff(change) {
  const before = change.from, after = change.to, lines = [];
  const bc = new Map(before.columns.map((c, i) => [c.id, { c, i }]));
  const ac = new Map(after.columns.map((c, i) => [c.id, { c, i }]));
  const br = new Map(before.rows.map(r => [r.id, r]));
  const ar = new Map(after.rows.map(r => [r.id, r]));
  bc.forEach(({ c }) => { if (!ac.has(c.id)) lines.push('Removed column "' + c.label + '"'); });
  ac.forEach(({ c }) => {
    if (!bc.has(c.id)) lines.push('Added column "' + c.label + '"');
    else if (bc.get(c.id).c.label !== c.label) lines.push('Column "' + bc.get(c.id).c.label + '" renamed to "' + c.label + '"');
    if (bc.has(c.id) && bc.get(c.id).c.width !== c.width) lines.push('Column "' + c.label + '" width: '
      + (bc.get(c.id).c.width === undefined ? "Auto" : bc.get(c.id).c.width + " px") + " -> " + (c.width === undefined ? "Auto" : c.width + " px"));
  });
  const previousOrder = before.columns.filter(c => ac.has(c.id)).map(c => c.id);
  const currentOrder = after.columns.filter(c => bc.has(c.id)).map(c => c.id);
  if (!_etEqual(previousOrder, currentOrder)) lines.push("Column order: " + after.columns.map(c => c.label).join(" | "));
  br.forEach(r => { if (!ar.has(r.id)) lines.push("Removed row " + r.id + ": " + r.cells.join(" | ")); });
  ar.forEach(r => {
    if (!br.has(r.id)) { lines.push("Added row " + r.id + ": " + r.cells.join(" | ")); return; }
    ac.forEach(({ c, i }) => {
      const old = bc.get(c.id);
      const from = old ? br.get(r.id).cells[old.i] : "";
      if (from !== r.cells[i]) lines.push("Row " + r.id + ', "' + c.label + '": ' + JSON.stringify(from) + " -> " + JSON.stringify(r.cells[i]));
    });
  });
  return lines;
}
function tablesCardPieces() {
  return tableChanges().map(ch => {
    const t = editableTables.find(t => t.id === ch.id), lines = _etDiff(ch);
    let pos = 1e15;
    try { pos = offsetWithin(t.shell, 0); } catch (e) { /* Structural-only document. */ }
    return { pos, html: '<article class="cm-card cm-card-table" data-cmh-table-name="' + escapeHtml(ch.id) + '"><div class="section">table: <strong>'
      + escapeHtml(ch.label) + '</strong></div><div class="note">' + lines.length + ' cumulative change(s)</div>'
      + '<details><summary>View changes</summary><ul>' + lines.map(line => "<li>" + escapeHtml(line) + "</li>").join("") + "</ul></details>"
      + '<div class="cmh-note-search" hidden>' + escapeHtml(ch.label + " " + lines.join(" ")) + '</div>'
      + '<div class="note">Auto-tracked. Copy all returns these changes; export HTML to carry the edited table.</div>'
      + '<div class="meta"><span class="acts"><button type="button" data-act="table-jump" data-cmh-table-name="' + escapeHtml(ch.id)
      + '">jump</button><button type="button" data-act="table-reset" data-cmh-table-name="' + escapeHtml(ch.id) + '">reset</button></span></div></article>' };
  });
}
async function resetTable(id) {
  const t = editableTables.find(t => t.id === id);
  if (!t || !(await showConfirm({ message: 'Reset table "' + t.label + '" to its authored values?', confirmLabel: "Reset", danger: true }))) return;
  _etMutate(t, () => { t.model = _etClone(t.baseline); t.sort = null; });
}
function resetAllTables() {
  const active = editableTables.filter(t => !t.stale && _etUnreadable === null);
  active.forEach(t => {
    t.model = _etClone(t.baseline); t.editBase = null; t.history = []; t.future = [];
    _etRender(t);
  });
  if (active.length) {
    _etChanged(active[0]);
    active.forEach(t => { t.status.textContent = active[0].status.textContent; });
  }
}
function jumpToTable(id) {
  const t = editableTables.find(t => t.id === id);
  if (!t) return;
  expandCollapsedAncestors(t.shell);
  const slide = t.shell.closest(".slide[data-slide-id]");
  if (slide && window.__cmhDeck) window.__cmhDeck.showSlideById(slide.getAttribute("data-slide-id"));
  t.shell.scrollIntoView({ behavior: cmScrollBehavior(), block: "center" });
  _etFocus(t);
}
function _etBake(doc, table, model) {
  const hadWidths = !!table.querySelector("th[data-cmh-width]");
  const head = doc.createElement("thead"), hr = doc.createElement("tr"), body = doc.createElement("tbody");
  model.columns.forEach(c => {
    const th = doc.createElement("th"); th.setAttribute("data-cmh-column", c.id); th.scope = "col"; th.textContent = c.label;
    if (c.type === "number") th.setAttribute("data-cmh-column-type", "number");
    if (c.width !== undefined) { th.setAttribute("data-cmh-width", c.width); th.style.width = c.width + "px"; th.style.boxSizing = "border-box"; }
    if (c.type === "choice") {
      th.setAttribute("data-cmh-column-type", "choice"); th.setAttribute("data-cmh-options", JSON.stringify(c.options));
      if (c.default !== "") th.setAttribute("data-cmh-default", c.default);
    }
    hr.append(th);
  });
  head.append(hr);
  model.rows.forEach(r => {
    const tr = doc.createElement("tr"); tr.setAttribute("data-cmh-row", r.id);
    r.cells.forEach(v => { const td = doc.createElement("td"); td.textContent = v; tr.append(td); }); body.append(tr);
  });
  if (table.tHead) table.tHead.remove();
  [...table.tBodies].forEach(b => b.remove());
  table.append(head, body);
  if (model.columns.some(c => c.width !== undefined)) {
    table.style.tableLayout = "fixed"; table.style.width = _etWidth(model.columns, 1);
  } else if (hadWidths) {
    table.style.removeProperty("table-layout"); table.style.removeProperty("width");
    if (!table.getAttribute("style")) table.removeAttribute("style");
  }
}
function _applyTableStateToHtml(html) {
  if (!tableChanges().length) return html;
  const doc = new DOMParser().parseFromString(String(html), "text/html");
  editableTables.forEach(t => {
    const tables = [...doc.querySelectorAll("table[data-cmh-table]")].filter(el => el.getAttribute("data-cmh-table") === t.id);
    if (tables.length !== 1) throw new Error("Cannot resolve editable table " + t.id);
    _etBake(doc, tables[0], t.model);
  });
  return (/^\s*<!doctype/i.test(html) ? "<!DOCTYPE html>\n" : "") + cmhSerializeElement(doc.documentElement);
}
function setupEditableTables() {
  window.__cmhRegisterEscapePopup(_etMenuPopup);
  const closeMenus = () => root.querySelectorAll(".cmh-table-column-actions[open]").forEach(menu => { menu.open = false; });
  document.addEventListener("pointerdown", e => {
    if (!e.target.closest(".cmh-table-column-menu, .cmh-table-column-actions > summary")) closeMenus();
  });
  document.addEventListener("scroll", e => {
    if (!(e.target.closest && e.target.closest(".cmh-table-column-menu"))) closeMenus();
  }, { capture: true, passive: true });
  window.addEventListener("resize", closeMenus);
  let saved = [];
  try {
    const raw = localStorage.getItem(CMH_TABLES_KEY);
    if (raw) {
      try {
        const value = JSON.parse(raw);
        if (!_etKeys(value, ["version", "tables"]) || value.version !== 1 || !Array.isArray(value.tables)) throw new Error("Invalid saved table state");
        value.tables.forEach(v => {
          if (!v || typeof v !== "object") return;
          if (typeof v.label === "string") v.label = _etText(v.label);
          _etNormalizeModel(v.from); _etNormalizeModel(v.to);
        });
        if (value.tables.some(v => !_etKeys(v, ["id", "label", "from", "to"]) || typeof v.id !== "string" || !_ET_ID.test(v.id)
            || typeof v.label !== "string" || !v.label.trim() || !_etValidModel(v.from) || !_etValidModel(v.to))
          || new Set(value.tables.map(v => v.id)).size !== value.tables.length) throw new Error("Invalid saved table state");
        saved = value.tables;
      } catch (e) { _etUnreadable = raw; }
    }
  } catch (e) { /* Storage is optional; the live editor and export remain usable. */ }
  const candidates = [...root.querySelectorAll("[data-cmh-table]")];
  const counts = new Map();
  candidates.forEach(el => { const id = el.getAttribute("data-cmh-table"); counts.set(id, (counts.get(id) || 0) + 1); });
  candidates.forEach(table => {
    const id = table.getAttribute("data-cmh-table");
    const label = _etText(table.getAttribute("data-cmh-table-label") || "");
    let baseline;
    try { baseline = _etRead(table); } catch (e) { baseline = null; }
    if (!_ET_ID.test(id || "") || !label || !label.trim() || counts.get(id) !== 1 || !baseline) {
      console.warn("CMH: editable table left unchanged: invalid schema or duplicate id", id); return;
    }
    const shell = document.createElement("div"); shell.className = "cmh-editable-table cm-skip";
    table.before(shell); shell.append(table); table.classList.add("cm-skip");
    const toolbar = document.createElement("div"); toolbar.className = "cmh-table-actions";
    toolbar.setAttribute("role", "group");
    const t = { id, label, table, shell, baseline,
      model: _etClone(baseline), history: [], future: [], editBase: null, seq: 0, sort: null, stale: null };
    t.originalSizing = baseline.columns.some(c => c.width !== undefined)
      ? { width: "", layout: "" } : { width: table.style.width, layout: table.style.tableLayout };
    toolbar.setAttribute("aria-label", t.label + " table actions");
    t.addRow = _etBtn("Add row", () => _etAddRow(t));
    t.addColumn = _etBtn("Add column", () => _etColumnDialog(t));
    function history(redo) {
      _etCommitEditor(t);
      const from = redo ? t.future : t.history, to = redo ? t.history : t.future;
      if (!from.length) return;
      to.push(_etClone(t.model)); t.model = from.pop(); t.editBase = null;
      _etRender(t); _etChanged(t); _etFocus(t);
    }
    t.undo = _etBtn("Undo", () => history(false)); t.redo = _etBtn("Redo", () => history(true));
    toolbar.append(t.addRow, t.addColumn, t.undo, t.redo); shell.prepend(toolbar);
    const scroll = document.createElement("div"); scroll.className = "cmh-editable-table-scroll";
    table.before(scroll); scroll.append(table);
    t.empty = document.createElement("p"); t.empty.className = "cmh-table-empty"; t.empty.textContent = "No rows yet. Use Add row to begin.";
    t.status = document.createElement("p"); t.status.className = "cmh-table-save-status";
    t.status.setAttribute("role", "status"); t.status.textContent = "Edits save in this browser. Export HTML to share them.";
    t.addBottom = _etBtn("New", () => _etAddRow(t)); t.addBottom.className = "cmh-table-add-bottom";
    t.addBottom.setAttribute("aria-label", "Add row at bottom");
    shell.append(t.addBottom, t.empty, t.status);
    const entry = saved.find(v => v.id === id);
    if (entry && !_etEqual(entry.to, baseline)) {
      if (_etEqual(entry.from, baseline)) t.model = _etClone(entry.to);
      else t.stale = entry;
    }
    t.identities = {
      columns: new Set([...baseline.columns, ...t.model.columns].map(c => c.id).concat(
        comments.filter(c => _etIsAnchor(c) && c.tableId === id && typeof c.columnId === "string").map(c => c.columnId))),
      rows: new Set([...baseline.rows, ...t.model.rows].map(r => r.id).concat(
        comments.filter(c => c.anchorType === "table-cell" && c.tableId === id && typeof c.rowId === "string").map(c => c.rowId))),
    };
    editableTables.push(t);
    _etRender(t);
    if (t.stale || _etUnreadable !== null) {
      const recovery = document.createElement("div"); recovery.className = "cmh-table-recovery"; t.recovery = recovery;
      const text = document.createElement("p"); text.textContent = "Saved table draft could not be applied to this source. Copy it before discarding; editing is paused to protect it.";
      const raw = _etUnreadable !== null ? _etUnreadable : JSON.stringify({ version: 1, tables: [t.stale] });
      recovery.append(text, _etBtn("Copy saved draft", () => _copyBundleToClipboard(raw)), _etBtn("Discard saved draft", async () => {
        if (!(await showConfirm({ message: "Discard this saved draft? Copy it first if you need to keep it.", confirmLabel: "Discard", danger: true }))) return;
        const affected = _etUnreadable !== null ? editableTables : [t];
        _etUnreadable = null;
        affected.forEach(item => {
          item.stale = null;
          if (item.recovery) { item.recovery.remove(); item.recovery = null; }
          [item.addRow, item.addColumn].forEach(b => { b.disabled = false; });
          _etRender(item);
        });
        _etChanged(t);
      }));
      shell.prepend(recovery);
      toolbar.querySelectorAll("button").forEach(b => { b.disabled = true; });
      table.querySelectorAll("textarea, select, input, button, summary, .cmh-table-resize").forEach(el => {
        if (el.classList.contains("cmh-table-resize")) { el.tabIndex = -1; el.setAttribute("aria-disabled", "true"); return; }
        if (el.tagName === "SUMMARY") el.parentElement.hidden = true; else el.disabled = true;
      });
    }
  });
  _etUnmatched = saved.filter(v => !editableTables.some(t => t.id === v.id));
  if (_etUnmatched.length || (_etUnreadable !== null && !editableTables.length)) {
    const recovery = document.createElement("div"); recovery.className = "cmh-table-recovery cm-skip";
    const text = document.createElement("p"); text.textContent = "Saved table drafts do not match an editable table in this document.";
    const raw = _etUnreadable !== null ? _etUnreadable : JSON.stringify({ version: 1, tables: _etUnmatched });
    recovery.append(text, _etBtn("Copy saved draft", () => _copyBundleToClipboard(raw)),
      _etBtn("Discard saved draft", async () => {
        if (!(await showConfirm({ message: "Discard unmatched saved table drafts?", confirmLabel: "Discard", danger: true }))) return;
        _etUnmatched = []; _etUnreadable = null; recovery.remove(); _etSave();
      }));
    root.prepend(recovery);
  }
  if (_etUnreadable === null && saved.length) _etSave();
  _etHadChanges = tableChanges().length > 0;
}
