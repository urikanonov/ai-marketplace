/* ---------- Layered checklist (four-state items, aggregation, minimal persistence) ----------
   A container marked data-cmh-checklist is a checklist. Any descendant carrying data-cmh-state
   (or data-cmh-item) is an item; an item with child items is a branch (its checkbox aggregates
   over its DIRECT children), otherwise a leaf. Hierarchy comes from DOM nesting (lists) or an
   explicit data-cmh-parent reference to a parent's data-cmh-item id (tables, which cannot nest
   rows and may be sorted). Leaf state cycles blank -> check -> cross -> question -> blank; a
   branch click propagates its next state to every descendant leaf. Only leaves whose state
   differs from their authored data-cmh-state baseline are stored, as one-character codes under
   COMMENT_KEY + "::cl", so a large checklist with a few edits costs a few bytes. Changes surface
   as one per-list card (jump + reset) in the sidebar and a Copy-all section the agent can cement
   back into the source with tools/checklist_apply.py; export bakes current states into
   data-cmh-state. */
const CMH_CHECK_STATES = ["blank", "check", "cross", "question"];
const CMH_CHECK_CODE = { blank: "b", check: "v", cross: "x", question: "q" };
const CMH_CHECK_TOKEN = { b: "blank", v: "check", x: "cross", q: "question" };
const CMH_CL_KEY = COMMENT_KEY + "::cl";
const checklists = [];
// Object.create(null) at every assignment/reset site below: a checklist id or item key of
// "__proto__"/"constructor" is ordinary author data, and a plain {} would let it resolve to
// Object.prototype and write through it (see CMH-SEC-02).
let _clOverrides = Object.create(null);   // { [checklistId]: { [itemKey]: token } } - current leaf states (any value)
let _clHadChanges = false;

function _clToken(v) {
  const s = (v == null ? "" : String(v)).trim().toLowerCase();
  return CMH_CHECK_STATES.indexOf(s) >= 0 ? s : "blank";
}
function _clNextState(s) {
  const i = CMH_CHECK_STATES.indexOf(s);
  return i < 0 ? "check" : CMH_CHECK_STATES[(i + 1) % CMH_CHECK_STATES.length];  // mixed/unknown -> check
}
function _clSvg(state, size) {
  const s = size || 20;
  const box = '<rect x="2.5" y="2.5" width="15" height="15" rx="4" ';
  let inner;
  if (state === "check") inner = box + 'fill="#1f8f4e" stroke="#1f8f4e" stroke-width="1.6"/><path d="M6 10.5 L9 13.3 L14.5 6.8" fill="none" stroke="#fff" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>';
  else if (state === "cross") inner = box + 'fill="#c8402c" stroke="#c8402c" stroke-width="1.6"/><path d="M6.6 6.6 L13.4 13.4 M13.4 6.6 L6.6 13.4" stroke="#fff" stroke-width="2.1" stroke-linecap="round"/>';
  else if (state === "question") inner = box + 'fill="#d98a1f" stroke="#d98a1f" stroke-width="1.6"/><text x="10" y="15" text-anchor="middle" font-size="13" font-weight="700" fill="#fff" font-family="Segoe UI, Arial, sans-serif">?</text>';
  else if (state === "mixed") inner = box + 'fill="none" stroke="#8a94a6" stroke-width="1.6"/><path d="M6 10 H14" stroke="#8a94a6" stroke-width="2" stroke-linecap="round"/>';
  else inner = box + 'fill="none" stroke="#8a94a6" stroke-width="1.6"/>';
  return '<svg viewBox="0 0 20 20" width="' + s + '" height="' + s + '" aria-hidden="true" focusable="false">' + inner + '</svg>';
}
// The item's own label: for a table row, the cells other than the state cell; for a list item,
// its direct text (excluding any nested list / nested items / the injected control).
function _clLabel(el) {
  if (el.tagName === "TR") {
    const cells = Array.prototype.filter.call(el.children, (c) => c.tagName === "TD" || c.tagName === "TH");
    const stateCell = el.querySelector("[data-cmh-state-cell]") || cells[0];
    const labelCell = cells.find((c) => c !== stateCell);
    const txt = labelCell ? (labelCell.textContent || "").replace(/\s+/g, " ").trim() : "";
    return txt || (el.textContent || "").replace(/\s+/g, " ").trim();
  }
  let s = "";
  Array.prototype.forEach.call(el.childNodes, (n) => {
    if (n.nodeType === 3) s += n.nodeValue;
    else if (n.nodeType === 1 && !n.matches("ul,ol,table,[data-cmh-checklist],[data-cmh-state],[data-cmh-item],.cmh-check")) s += n.textContent;
  });
  s = s.replace(/\s+/g, " ").trim();
  return s || (el.getAttribute("data-cmh-item") || "");
}
// Where the state control lives: a table row's state cell (or first cell), else the item itself.
function _clSlot(el) {
  if (el.tagName === "TR") return el.querySelector("[data-cmh-state-cell]") || el.querySelector("td, th") || el;
  return el;
}
function _clParentEl(el, setEls, container) {
  let p = el.parentElement;
  while (p && p !== container && p !== root) {
    if (setEls.has(p)) return p;
    p = p.parentElement;
  }
  return null;
}
function _clLeafState(item) {
  const m = _clOverrides[item.checklist];
  const ov = m ? m[item.key] : null;
  return ov || item.baseline;
}
function _clItemState(item, cache) {
  if (cache.has(item)) return cache.get(item);
  let s;
  if (item.isBranch) {
    const kids = item.children.map((c) => _clItemState(c, cache));
    if (!kids.length) s = "blank";
    else if (kids.some((k) => k === "mixed")) s = "mixed";
    else s = kids.every((k) => k === kids[0]) ? kids[0] : "mixed";
  } else {
    s = _clLeafState(item);
  }
  cache.set(item, s);
  return s;
}
function _clDescendantLeaves(item) {
  const out = [];
  (function walk(it) {
    if (!it.isBranch) { out.push(it); return; }
    it.children.forEach(walk);
  })(item);
  return out;
}
function _clSetLeaf(item, token) {
  const cid = item.checklist;
  if (token === item.baseline) { if (_clOverrides[cid]) delete _clOverrides[cid][item.key]; }
  else { if (!_clOverrides[cid]) _clOverrides[cid] = Object.create(null); _clOverrides[cid][item.key] = token; }
  if (_clOverrides[cid] && !Object.keys(_clOverrides[cid]).length) delete _clOverrides[cid];
}
// A JSON.parse'd object still chains to Object.prototype, so a crafted "__proto__" or
// "constructor" own key survives Object.keys() fine, but any direct property read (not just
// the destination writes above) should not be able to fall through to the prototype. Re-home
// every parsed map onto a null-prototype copy before it is read from, per CMH-SEC-02.
function _clNullProto(obj) {
  return obj && typeof obj === "object" ? Object.assign(Object.create(null), obj) : Object.create(null);
}
function _clLoad() {
  _clOverrides = Object.create(null);
  let raw = null;
  try { raw = localStorage.getItem(CMH_CL_KEY); } catch (e) { raw = null; }
  let parsed = {};
  try { parsed = raw ? JSON.parse(raw) : {}; } catch (e) { parsed = {}; }
  if (!parsed || typeof parsed !== "object") return;
  const data = _clNullProto(parsed);
  Object.keys(data).forEach((cid) => {
    if (!data[cid] || typeof data[cid] !== "object") return;
    const m = _clNullProto(data[cid]);
    Object.keys(m).forEach((key) => {
      const token = Object.prototype.hasOwnProperty.call(CMH_CHECK_TOKEN, m[key]) ? CMH_CHECK_TOKEN[m[key]] : null;
      if (token) { if (!_clOverrides[cid]) _clOverrides[cid] = Object.create(null); _clOverrides[cid][key] = token; }
    });
  });
}
function _clSave() {
  const out = Object.create(null);
  checklists.forEach((cl) => {
    cl.leaves.forEach((item) => {
      const cur = _clLeafState(item);
      if (cur !== item.baseline) { if (!out[item.checklist]) out[item.checklist] = Object.create(null); out[item.checklist][item.key] = CMH_CHECK_CODE[cur]; }
    });
  });
  const ok = cmhTrySetItem(CMH_CL_KEY, function () {
    return Object.keys(out).length ? JSON.stringify(out) : null;
  }, "Checklist state");
  if (!ok) cmhStorageFullToast(CMH_CL_KEY, "Checklist state");
  return ok;
}
function _clRefresh() {
  const cache = new Map();
  checklists.forEach((cl) => {
    cl.items.forEach((item) => {
      if (!item.btn) return;
      const s = _clItemState(item, cache);
      item.btn.setAttribute("data-cmh-check-state", s);
      item.btn.innerHTML = _clSvg(s, 20);
      const lbl = (item.label || item.key || "item") + ": " + s + ". Activate to change.";
      item.btn.setAttribute("aria-label", lbl);
      item.btn.title = "State: " + s;
    });
  });
}
function _clAfterChange() {
  _clSave();
  _clRefresh();
  if (typeof renderComments === "function") renderComments();
  if (typeof updateDocTypeUi === "function") updateDocTypeUi();
  // Surface a newly-detected change: open the panel once on the 0 -> >0 transition so the
  // per-list card (which is not a comment) is not missed, matching the widget state card.
  const has = checklistChanges().length > 0;
  if (has && !_clHadChanges && typeof openSidebar === "function") openSidebar();
  _clHadChanges = has;
}
function _clCycleItem(item) {
  const cache = new Map();
  const next = _clNextState(_clItemState(item, cache));
  if (item.isBranch) _clDescendantLeaves(item).forEach((l) => _clSetLeaf(l, next));
  else _clSetLeaf(item, next);
  _clAfterChange();
}
function _clMakeBtn(item) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "cmh-check cm-skip";
  b.setAttribute("data-cmh-check-btn", "");
  b.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); _clCycleItem(item); });
  b.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") { e.preventDefault(); _clCycleItem(item); }
  });
  return b;
}
// Leaves whose current state differs from their authored baseline, one record per change.
function checklistChanges() {
  const out = [];
  checklists.forEach((cl) => {
    cl.leaves.forEach((item) => {
      const cur = _clLeafState(item);
      if (cur !== item.baseline) out.push({ checklist: cl.id, checklistLabel: cl.label, key: item.key, label: item.label, from: item.baseline, to: cur });
    });
  });
  return out;
}
function _clMini(token) { return '<span class="cmh-cl-mini">' + _clSvg(token, 14) + "</span>"; }
function _renderOneChecklistCard(cl, list) {
  const items = list.map((ch) =>
    "<li>" + _clMini(ch.from) + ' <span class="cmh-cl-arrow">&rarr;</span> ' + _clMini(ch.to)
    + " " + escapeHtml(ch.label || ch.key) + "</li>"
  ).join("");
  return `
    <article class="cm-card cm-card-checklist" data-cmh-checklist-name="${escapeHtml(cl.id)}">
      <div class="section">checklist: <strong>${escapeHtml(cl.label)}</strong></div>
      <div class="cm-card-state-title">${list.length} item${list.length === 1 ? "" : "s"} changed</div>
      <ul class="cmh-cl-changes">${items}</ul>
      <div class="note">Auto-tracked from the current checklist state. Included in Copy all so the agent can cement it into the source; the file stays Not portable until re-exported.</div>
      <div class="meta">
        <span></span>
        <span class="acts">
          <button type="button" data-act="cl-jump" data-cmh-checklist-name="${escapeHtml(cl.id)}" title="Scroll to this checklist">jump</button>
          <button type="button" data-act="cl-reset" data-cmh-checklist-name="${escapeHtml(cl.id)}" title="Revert this checklist to its authored state">reset</button>
        </span>
      </div>
    </article>`;
}
// Sidebar cards for changed checklists, each tagged with a document-order position so the
// sidebar can interleave them with the comment cards instead of pinning them on top.
function checklistCardPieces() {
  const changes = checklistChanges();
  if (!changes.length) return [];
  const byCl = new Map();
  changes.forEach((ch) => { if (!byCl.has(ch.checklist)) byCl.set(ch.checklist, []); byCl.get(ch.checklist).push(ch); });
  const pieces = [];
  checklists.forEach((cl) => {
    const list = byCl.get(cl.id);
    if (!list || !list.length) return;
    let pos = 1e15;
    try { const o = offsetWithin(cl.container, 0); if (typeof o === "number" && o >= 0) pos = o; } catch (e) { /* no text position */ }
    pieces.push({ pos, html: _renderOneChecklistCard(cl, list) });
  });
  return pieces;
}
function resetChecklist(cid) {
  if (!_clOverrides[cid]) return;
  delete _clOverrides[cid];
  _clAfterChange();
}
function resetAllChecklists() {
  if (!checklistChanges().length) return false;
  _clOverrides = Object.create(null);
  _clAfterChange();
  return true;
}
function jumpToChecklist(cid) {
  const cl = checklists.find((c) => c.id === cid);
  if (!cl || !cl.container) return;
  if (typeof expandCollapsedAncestors === "function") expandCollapsedAncestors(cl.container);
  cl.container.scrollIntoView({ behavior: cmScrollBehavior(), block: "center" });
  cl.container.classList.add("cmh-check-flash");
  setTimeout(() => cl.container.classList.remove("cmh-check-flash"), 2200);
}
// Bake current leaf states into data-cmh-state so an exported file reflects them and opens
// with no pending changes (mirrors _applyWidgetLayoutToHtml for the layout case).
function _clDocItemMap(container) {
  const els = Array.prototype.filter.call(
    container.querySelectorAll("[data-cmh-state], [data-cmh-item]"),
    (el) => el.closest("[data-cmh-checklist]") === container);
  const map = new Map();
  els.forEach((el, idx) => { const key = el.getAttribute("data-cmh-item") || String(idx + 1); if (!map.has(key)) map.set(key, el); });
  return map;
}
function _applyChecklistStateToHtml(html) {
  if (!checklists.length || !checklistChanges().length) return html;
  const doc = new DOMParser().parseFromString(String(html || ""), "text/html");
  checklists.forEach((cl) => {
    let container = null;
    try { container = doc.querySelector('[data-cmh-checklist="' + _cssEsc(cl.id) + '"]'); } catch (e) { container = null; }
    if (!container) return;
    const map = _clDocItemMap(container);
    cl.leaves.forEach((item) => {
      const el = map.get(item.key);
      if (el) el.setAttribute("data-cmh-state", _clLeafState(item));
    });
  });
  const doctype = /^\s*<!doctype/i.test(String(html || "")) ? "<!DOCTYPE html>\n" : "";
  return doctype + doc.documentElement.outerHTML;
}
function setupChecklistLayer() {
  checklists.length = 0;
  _clLoad();
  root.querySelectorAll("[data-cmh-checklist]").forEach((container) => {
    const id = container.getAttribute("data-cmh-checklist") || "";
    if (!id) return;
    const itemEls = Array.prototype.filter.call(
      container.querySelectorAll("[data-cmh-state], [data-cmh-item]"),
      (el) => el.closest("[data-cmh-checklist]") === container);
    if (!itemEls.length) return;
    const setEls = new Set(itemEls);
    const items = [];
    const byKey = new Map();
    const elItem = new Map();
    itemEls.forEach((el, idx) => {
      const key = el.getAttribute("data-cmh-item") || String(idx + 1);
      const item = { checklist: id, key, el, label: _clLabel(el), parentKey: null, children: [], isBranch: false, baseline: _clToken(el.getAttribute("data-cmh-state")), btn: null };
      items.push(item);
      elItem.set(el, item);
      if (!byKey.has(key)) byKey.set(key, item);
    });
    items.forEach((item) => {
      const explicit = item.el.getAttribute("data-cmh-parent");
      if (explicit && byKey.has(explicit)) { item.parentKey = explicit; return; }
      const pEl = _clParentEl(item.el, setEls, container);
      if (pEl && elItem.get(pEl)) item.parentKey = elItem.get(pEl).key;
    });
    items.forEach((item) => { if (item.parentKey && byKey.has(item.parentKey) && byKey.get(item.parentKey) !== item) byKey.get(item.parentKey).children.push(item); });
    items.forEach((item) => { item.isBranch = item.children.length > 0; });
    items.forEach((item) => {
      item.el.classList.add("cmh-check-item");
      item.el.setAttribute("data-cmh-check-role", item.isBranch ? "branch" : "leaf");
      const btn = _clMakeBtn(item);
      item.btn = btn;
      const slot = _clSlot(item.el);
      slot.insertBefore(btn, slot.firstChild);
    });
    container.classList.add("cmh-checklist-ready");
    checklists.push({ id, label: container.getAttribute("data-cmh-checklist-label") || id, container, items, byKey, leaves: items.filter((i) => !i.isBranch) });
  });
  if (checklists.length) _clRefresh();
  _clHadChanges = checklistChanges().length > 0;
}
