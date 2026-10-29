/* Editable tables own their model; sorting and runtime editors never become authored data. */
const CMH_TABLES_KEY = COMMENT_KEY + "::tables";
const editableTables = [];
const _ET_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/;
let _etTimer = 0;
let _etHadChanges = false;
let _etUnreadable = null;
let _etUnmatched = [];
function _etClone(value) { return JSON.parse(JSON.stringify(value)); }
function _etEqual(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
function _etText(value) { return String(value).replace(/\r\n?/g, "\n"); }
function _etValidModel(m) {
  if (!m || !Array.isArray(m.columns) || !m.columns.length || !Array.isArray(m.rows)) return false;
  const cols = new Set(), rows = new Set();
  for (const c of m.columns) {
    if (!c || typeof c.id !== "string" || !_ET_ID.test(c.id) || cols.has(c.id)
      || typeof c.label !== "string" || !c.label.trim() || !["text", "choice"].includes(c.type)
      || !Array.isArray(c.options) || typeof c.default !== "string") return false;
    cols.add(c.id);
    if (c.type === "text") {
      if (c.options.length || c.default !== "") return false;
    } else if (!c.options.length || c.options.some(v => typeof v !== "string" || !v.trim())
      || new Set(c.options).size !== c.options.length || (c.default !== "" && !c.options.includes(c.default))) return false;
  }
  for (const r of m.rows) {
    if (!r || typeof r.id !== "string" || !_ET_ID.test(r.id) || rows.has(r.id)
      || !Array.isArray(r.cells) || r.cells.length !== m.columns.length) return false;
    rows.add(r.id);
    if (r.cells.some((v, i) => typeof v !== "string"
      || (m.columns[i].type === "choice" && v !== "" && !m.columns[i].options.includes(v)))) return false;
  }
  return true;
}
function _etRead(table) {
  if (table.tagName !== "TABLE" || !table.tHead || table.tHead.rows.length !== 1
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
      return {
        id: el.getAttribute("data-cmh-column") || "", label: _etText(el.textContent), type,
        options: type === "choice" ? JSON.parse(el.getAttribute("data-cmh-options") || "null") : [],
        default: type === "choice" ? (el.getAttribute("data-cmh-default") || "") : "",
      };
    }),
    rows: [...table.tBodies[0].rows].map(row => {
      if ([...row.cells].some(el => el.tagName !== "TD" || nonText(el))) throw new Error("Cells must contain plain text");
      return { id: row.getAttribute("data-cmh-row") || "", cells: [...row.cells].map(el => _etText(el.textContent)) };
    }),
  };
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
  t.undo.disabled = !t.history.length;
  t.redo.disabled = !t.future.length;
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
  t.editBase = null;
  t.undo.disabled = !t.history.length; t.redo.disabled = !t.future.length;
}
function _etMutate(t, change, focus) {
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
  if (!el) el = t.table.querySelector("textarea, select") || t.addRow;
  el.focus();
}
function _etBtn(text, fn) {
  const b = document.createElement("button");
  b.type = "button"; b.textContent = text;
  cmhMarkLayerChrome(b);
  b.addEventListener("click", fn);
  return b;
}
function _etId(t, kind) {
  const taken = new Set(t.model[kind].map(v => v.id));
  let id;
  do { id = "new-" + (++t.seq); } while (taken.has(id));
  return id;
}
function _etAddRow(t) {
  const row = { id: _etId(t, "rows"), cells: t.model.columns.map(c => c.default) };
  // Reveal the new row rather than leaving it buried in a sorted view.
  t.sort = null;
  _etMutate(t, () => t.model.rows.push(row), '[data-cmh-row="' + _cssEsc(row.id) + '"] textarea, [data-cmh-row="' + _cssEsc(row.id) + '"] select');
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
  const nextId = displayed[number] || displayed[number - 2];
  const focus = nextId ? '[data-cmh-row="' + _cssEsc(nextId) + '"] textarea, [data-cmh-row="' + _cssEsc(nextId) + '"] select' : null;
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
  }, '[data-cmh-column="' + _cssEsc(nextId) + '"] button');
}
function _etColumnDialog(t, renameId, afterId) {
  const existing = renameId && t.model.columns.find(c => c.id === renameId);
  const dialog = document.createElement("dialog");
  dialog.className = "cmh-table-dialog cm-skip";
  dialog.setAttribute("aria-label", existing ? "Rename column" : "Add column");
  const form = document.createElement("form");
  const heading = document.createElement("h2");
  heading.textContent = existing ? "Rename column" : "Add column";
  form.append(heading);
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
  ["text", "choice"].forEach(value => {
    const option = document.createElement("option"); option.value = value;
    option.textContent = value === "text" ? "Text" : "Single choice"; type.append(option);
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
  const save = document.createElement("button"); save.type = "submit"; save.textContent = "Save";
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
        const index = afterId ? t.model.columns.findIndex(c => c.id === afterId) + 1 : t.model.columns.length;
        t.model.columns.splice(index, 0, column);
        t.model.rows.forEach(r => r.cells.splice(index, 0, column.default));
      }
    }, existing || !t.model.rows.length
      ? '[data-cmh-column="' + _cssEsc(column.id) + '"] button'
      : '[data-cmh-edit-column="' + _cssEsc(column.id) + '"]');
  });
  document.body.append(dialog); dialog.showModal(); name.focus();
}
function _etGrow(el) {
  el.style.height = "auto";
  el.style.height = Math.min(280, Math.max(40, el.scrollHeight)) + "px";
}
function _etRender(t) {
  const doc = document;
  const head = doc.createElement("thead"), hr = doc.createElement("tr");
  const number = doc.createElement("th"); number.textContent = "#"; number.scope = "col"; hr.append(number);
  t.model.columns.forEach(c => {
    const th = doc.createElement("th"); th.scope = "col"; th.setAttribute("data-cmh-column", c.id);
    const label = doc.createElement("span"); label.textContent = c.label; th.append(label);
    const sort = _etBtn("Sort", () => {
      const dir = t.sort && t.sort.id === c.id ? (t.sort.dir === "asc" ? "desc" : null) : "asc";
      t.sort = dir ? { id: c.id, dir } : null;
      _etRender(t);
      t.table.querySelector('[data-cmh-column="' + _cssEsc(c.id) + '"] button').focus();
    });
    sort.setAttribute("aria-label", "Sort by " + c.label);
    th.setAttribute("aria-sort", t.sort && t.sort.id === c.id ? (t.sort.dir === "asc" ? "ascending" : "descending") : "none");
    sort.textContent = t.sort && t.sort.id === c.id ? (t.sort.dir === "asc" ? "Sort ascending" : "Sort descending") : "Sort";
    const menu = doc.createElement("details");
    const summary = doc.createElement("summary"); summary.textContent = "Column";
    summary.setAttribute("aria-label", "Actions for " + c.label);
    cmhMarkLayerChrome(summary);
    menu.append(summary, _etBtn("Rename column", () => { menu.open = false; _etColumnDialog(t, c.id); }),
      _etBtn("Insert column after", () => { menu.open = false; _etColumnDialog(t, null, c.id); }));
    const remove = _etBtn("Remove column", () => { menu.open = false; _etRemoveColumn(t, c.id); });
    remove.disabled = t.model.columns.length === 1;
    if (remove.disabled) remove.title = "Keep at least one data column.";
    menu.append(remove);
    menu.addEventListener("keydown", e => { if (e.key === "Escape") { menu.open = false; summary.focus(); e.stopPropagation(); } });
    th.append(sort, menu); hr.append(th);
  });
  const actions = doc.createElement("th"); actions.textContent = "Actions"; actions.scope = "col"; hr.append(actions);
  head.append(hr);
  const body = doc.createElement("tbody");
  const displayed = t.model.rows.slice();
  if (t.sort) {
    const ci = t.model.columns.findIndex(c => c.id === t.sort.id);
    displayed.sort((a, b) => a.cells[ci].localeCompare(b.cells[ci], undefined, { numeric: true }) * (t.sort.dir === "asc" ? 1 : -1));
  }
  displayed.forEach((row, ri) => {
    const tr = doc.createElement("tr"); tr.setAttribute("data-cmh-row", row.id);
    const rn = doc.createElement("th"); rn.scope = "row"; rn.textContent = String(ri + 1); tr.append(rn);
    t.model.columns.forEach((c, ci) => {
      const td = doc.createElement("td");
      const input = doc.createElement(c.type === "choice" ? "select" : "textarea");
      if (c.type === "choice") {
        ["", ...c.options].forEach(value => {
          const option = doc.createElement("option"); option.value = value;
          option.textContent = value === "" ? "(empty)" : value; input.append(option);
        });
      } else input.rows = 1;
      input.value = row.cells[ci];
      const print = doc.createElement("span"); print.className = "cmh-table-print-value"; print.textContent = row.cells[ci];
      input.setAttribute("data-cmh-edit-column", c.id);
      input.setAttribute("aria-label", c.label + ", column " + (ci + 1) + ", row " + (ri + 1));
      cmhMarkLayerChrome(input);
      input.addEventListener("focus", () => { if (!t.editBase) t.editBase = _etClone(t.model); });
      const onInput = () => {
        if (!t.editBase) t.editBase = _etClone(t.model);
        row.cells[ci] = _etText(input.value);
        print.textContent = row.cells[ci];
        if (input.tagName === "TEXTAREA") _etGrow(input);
        _etChanged(t, true);
      };
      input.addEventListener("input", onInput);
      input.addEventListener("change", () => { onInput(); _etCommitEditor(t); });
      input.addEventListener("blur", () => _etCommitEditor(t));
      td.append(input, print); tr.append(td);
    });
    const td = doc.createElement("td"), remove = _etBtn("Remove", () => _etRemoveRow(t, row, ri + 1));
    remove.setAttribute("aria-label", "Remove row " + (ri + 1)); td.append(remove); tr.append(td); body.append(tr);
  });
  if (t.table.tHead) t.table.tHead.remove();
  [...t.table.tBodies].forEach(b => b.remove());
  t.table.append(head, body);
  t.empty.hidden = !!t.model.rows.length;
  t.undo.disabled = !t.history.length; t.redo.disabled = !t.future.length;
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
  });
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
    return { pos, html: '<article class="cm-card cm-card-table"><div class="section">table: <strong>'
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
  const head = doc.createElement("thead"), hr = doc.createElement("tr"), body = doc.createElement("tbody");
  model.columns.forEach(c => {
    const th = doc.createElement("th"); th.setAttribute("data-cmh-column", c.id); th.scope = "col"; th.textContent = c.label;
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
}
function _applyTableStateToHtml(html) {
  if (!tableChanges().length) return html;
  const doc = new DOMParser().parseFromString(html, "text/html");
  editableTables.forEach(t => {
    const tables = [...doc.querySelectorAll("table[data-cmh-table]")].filter(el => el.getAttribute("data-cmh-table") === t.id);
    if (tables.length !== 1) throw new Error("Cannot resolve editable table " + t.id);
    _etBake(doc, tables[0], t.model);
  });
  return (/^\s*<!doctype/i.test(html) ? "<!DOCTYPE html>\n" : "") + cmhSerializeElement(doc.documentElement);
}
function setupEditableTables() {
  let saved = [];
  try {
    const raw = localStorage.getItem(CMH_TABLES_KEY);
    if (raw) {
      try {
        const value = JSON.parse(raw);
        if (!value || value.version !== 1 || !Array.isArray(value.tables)
          || value.tables.some(v => !v || typeof v.id !== "string" || !_ET_ID.test(v.id)
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
    const label = table.getAttribute("data-cmh-table-label");
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
    shell.append(t.empty, t.status);
    const entry = saved.find(v => v.id === id);
    if (entry && !_etEqual(entry.to, baseline)) {
      if (_etEqual(entry.from, baseline)) t.model = _etClone(entry.to);
      else t.stale = entry;
    }
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
      table.querySelectorAll("textarea, select, button, summary").forEach(el => {
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
  _etHadChanges = tableChanges().length > 0;
}
