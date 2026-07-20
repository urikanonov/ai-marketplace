/* ---------- Commentable widgets and SVG nodes (generic opt-in) ----------
   Any element marked data-cm-widget declares a commentable widget. Descendants marked
   data-cm-part (with an optional data-cm-part-label) become individually commentable even
   when the widget itself is cm-skip. A labeled SVG <g data-cm-part> is just a part, so
   commenting on a diagram node uses the same mechanism. Parts inside containers marked
   data-cm-slot also get state-change tracking: their slot at load is the baseline, and any
   later move is surfaced as a synthetic "layout change" record (see widgetStateChanges). */
const widgetAddBtn = document.getElementById("widgetAddBtn");
const widgetParts = [];
let pendingWidget = null;
let widgetAddHideTimer = null;
let _widgetBaseline = null;   // Map partKey -> slot name at load (baseline for state diff)
let _widgetObserver = null;
let _widgetRaf = 0;
let _hadWidgetChanges = false;
let _widgetOrder = new Map(); // Map partKey -> document order (O(1) sort lookup)
let _lastWidgetSig = null;    // last widget state signature, to skip no-op re-renders
let _widgetDrag = null;
let _widgetDomBaseline = null;   // Resettable widgets with each load-time parent child order.
let _widgetFirstChangeAt = null; // ISO time of the 0 -> >0 layout-change transition (null while clean).

function _cssEsc(s) { return (window.CSS && CSS.escape) ? CSS.escape(String(s)) : String(s).replace(/["\\]/g, "\\$&"); }
function widgetName(el) { const w = el.closest("[data-cm-widget]"); return w ? (w.getAttribute("data-cm-widget") || "widget") : "widget"; }
function partId(el) { return el.getAttribute("data-cm-part") || ""; }
function partLabel(el) {
  const l = el.getAttribute("data-cm-part-label");
  return (l != null && l !== "") ? l.replace(/\s+/g, " ").trim() : (el.textContent || "").replace(/\s+/g, " ").trim();
}
function partSlot(el) { const s = el.closest("[data-cm-slot]"); return s ? (s.getAttribute("data-cm-slot") || "") : null; }
function partKey(widget, id) { return widget + "\u0000" + id; }

function _wireWidgetPart(el) {
  if (el._cmWidgetAttached) return;
  el._cmWidgetAttached = true;
  el.addEventListener("mouseenter", () => showWidgetAddFor(el));
  el.addEventListener("mouseleave", scheduleHideWidgetAdd);
  el.addEventListener("focus", () => showWidgetAddFor(el));
  el.addEventListener("blur", scheduleHideWidgetAdd);
  el.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    const info = widgetInfo(el);
    pendingWidget = null; if (widgetAddBtn) widgetAddBtn.hidden = true;
    openWidgetComposer(info);
  });
}
function indexWidgetParts() {
  widgetParts.length = 0;
  _widgetOrder = new Map();
  const seenPerWidget = new Map();
  root.querySelectorAll("[data-cm-widget] [data-cm-part]").forEach((el) => {
    const w = widgetName(el), id = partId(el);
    if (!id) { try { console.warn("commentable-html: ignoring a [data-cm-part] with an empty id in widget", w); } catch (e) { /* no-op */ } return; }
    let seen = seenPerWidget.get(w);
    if (!seen) { seen = new Set(); seenPerWidget.set(w, seen); }
    if (seen.has(id)) { try { console.warn("commentable-html: ignoring a duplicate [data-cm-part] id", id, "in widget", w); } catch (e) { /* no-op */ } return; }
    seen.add(id);
    el.classList.add("cm-part-commentable");
    if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
    if (!el.getAttribute("aria-label")) {
      const label = partLabel(el);
      el.setAttribute("aria-label", (label ? label + " - " : "") + "press Enter to comment");
    }
    _wireWidgetPart(el);
    _widgetOrder.set(partKey(w, id), widgetParts.length);
    widgetParts.push(el);
  });
}
function findWidgetPart(widget, id) {
  try {
    const hit = root.querySelector('[data-cm-widget="' + _cssEsc(widget) + '"] [data-cm-part="' + _cssEsc(id) + '"]');
    if (hit) return hit;
  } catch (e) { /* an invalid selector from exotic attribute values - fall through to the scan */ }
  return widgetParts.find((el) => widgetName(el) === widget && partId(el) === id) || null;
}
function widgetInfo(el) {
  const widget = widgetName(el), id = partId(el), label = partLabel(el);
  return { widget, part: id, label, slot: partSlot(el), quote: label || id || widget };
}
function _widgetDragOptIn(slot, widget) {
  return !!(widget && (widget.hasAttribute("data-cm-draggable") || slot.hasAttribute("data-cm-draggable")));
}
function _widgetResetOptIn(widget) {
  return !!(widget && (widget.hasAttribute("data-cm-draggable") || widget.querySelector("[data-cm-slot][data-cm-draggable]")));
}
function _widgetDragPartFromEvent(e) {
  if (e.button !== 0 || (e.pointerType && e.pointerType !== "mouse")) return null;
  const target = e.target && e.target.closest ? e.target : null;
  if (!target || target.closest("button, input, textarea, select, option, a[href], [contenteditable='true']")) return null;
  const part = target.closest("[data-cm-widget] [data-cm-part]");
  if (!part || !root.contains(part)) return null;
  const slot = part.closest("[data-cm-slot]");
  const widget = part.closest("[data-cm-widget]");
  if (!slot || !widget || part === slot || !_widgetDragOptIn(slot, widget)) return null;
  return { part, slot, widget };
}
function _widgetSlotAtPoint(x, y, widget) {
  const el = document.elementFromPoint(x, y);
  if (!el) return null;
  const slot = el.closest && el.closest("[data-cm-slot]");
  return slot && widget.contains(slot) ? slot : null;
}
function _setWidgetDropSlot(slot) {
  if (_widgetDrag && _widgetDrag.dropSlot === slot) return;
  if (_widgetDrag && _widgetDrag.dropSlot) _widgetDrag.dropSlot.classList.remove("cm-widget-drop-target");
  if (_widgetDrag) _widgetDrag.dropSlot = slot || null;
  if (slot) slot.classList.add("cm-widget-drop-target");
}
function _clearWidgetDrag() {
  if (!_widgetDrag) return;
  if (_widgetDrag.dropSlot) _widgetDrag.dropSlot.classList.remove("cm-widget-drop-target");
  _widgetDrag.part.classList.remove("cm-widget-drag-source");
  document.body.classList.remove("cm-widget-dragging");
  try { _widgetDrag.part.releasePointerCapture(_widgetDrag.pointerId); } catch (e) { /* already released */ }
  document.removeEventListener("pointermove", _onWidgetPointerMove, true);
  document.removeEventListener("pointerup", _onWidgetPointerUp, true);
  document.removeEventListener("pointercancel", _onWidgetPointerCancel, true);
  _widgetDrag = null;
}
function _startWidgetDrag(e, hit) {
  _widgetDrag = {
    pointerId: e.pointerId,
    part: hit.part,
    fromSlot: hit.slot,
    widget: hit.widget,
    startX: e.clientX,
    startY: e.clientY,
    active: false,
    dropSlot: null,
  };
  document.addEventListener("pointermove", _onWidgetPointerMove, true);
  document.addEventListener("pointerup", _onWidgetPointerUp, true);
  document.addEventListener("pointercancel", _onWidgetPointerCancel, true);
}
function _activateWidgetDrag(e) {
  _widgetDrag.active = true;
  _widgetDrag.part.classList.add("cm-widget-drag-source");
  document.body.classList.add("cm-widget-dragging");
  if (widgetAddBtn) { widgetAddBtn.hidden = true; pendingWidget = null; }
  // Draggable cards suppress text selection by design: the whole card is a drag or comment target.
  try { window.getSelection().removeAllRanges(); } catch (err) { /* selection may be unavailable */ }
  try { _widgetDrag.part.setPointerCapture(_widgetDrag.pointerId); } catch (err) { /* capture can fail after cancellation */ }
  _setWidgetDropSlot(_widgetSlotAtPoint(e.clientX, e.clientY, _widgetDrag.widget));
}
function _onWidgetPointerMove(e) {
  if (!_widgetDrag || e.pointerId !== _widgetDrag.pointerId) return;
  const dx = e.clientX - _widgetDrag.startX;
  const dy = e.clientY - _widgetDrag.startY;
  if (!_widgetDrag.active && Math.sqrt(dx * dx + dy * dy) < 6) return;
  if (!_widgetDrag.active) _activateWidgetDrag(e);
  e.preventDefault();
  _setWidgetDropSlot(_widgetSlotAtPoint(e.clientX, e.clientY, _widgetDrag.widget));
}
function _onWidgetPointerUp(e) {
  if (!_widgetDrag || e.pointerId !== _widgetDrag.pointerId) return;
  const drag = _widgetDrag;
  try {
    if (drag.active) {
      e.preventDefault();
      const target = drag.dropSlot;
      if (target && target !== drag.fromSlot && !drag.part.contains(target)) {
        target.appendChild(drag.part);
        _onWidgetMutation();
      }
    }
  } finally {
    _clearWidgetDrag();
  }
}
function _onWidgetPointerCancel(e) {
  if (_widgetDrag && e.pointerId === _widgetDrag.pointerId) _clearWidgetDrag();
}
function setupWidgetDragDrop() {
  if (root._cmWidgetDragAttached) return;
  root._cmWidgetDragAttached = true;
  root.addEventListener("pointerdown", function (e) {
    const hit = _widgetDragPartFromEvent(e);
    if (hit) _startWidgetDrag(e, hit);
  }, true);
}
function applyWidgetHighlight(comment) {
  const el = findWidgetPart(comment.widget, comment.part);
  if (!el) return false;
  el.classList.add("cm-part-hl");
  const cids = (el.getAttribute("data-cids") || "").split(/\s+/).filter(Boolean);
  if (!cids.includes(comment.id)) cids.push(comment.id);
  el.setAttribute("data-cids", cids.join(" "));
  el.setAttribute("data-cid", cids[0]);
  return true;
}
function _partCids(el) { return (el.getAttribute("data-cids") || el.getAttribute("data-cid") || "").split(/\s+/).filter(Boolean); }
function clearWidgetHighlight(id) {
  root.querySelectorAll("[data-cm-part].cm-part-hl").forEach((el) => {
    const cids = _partCids(el);
    const rest = cids.filter((c) => c !== id);
    if (rest.length === cids.length) return;
    if (rest.length) { el.setAttribute("data-cids", rest.join(" ")); el.setAttribute("data-cid", rest[0]); }
    else { el.classList.remove("cm-part-hl", "cm-part-active"); el.removeAttribute("data-cid"); el.removeAttribute("data-cids"); }
  });
}
function flashWidget(id) {
  const el = [...root.querySelectorAll("[data-cm-part].cm-part-hl")].find((x) => _partCids(x).includes(id));
  if (!el) return;
  el.classList.add("cm-part-active");
  setTimeout(() => el.classList.remove("cm-part-active"), 2200);
}
function positionWidgetAdd(el) {
  const rect = el.getBoundingClientRect();
  const visible = _clipAwareRect(el, rect);
  if (!visible) return false;
  const bw = widgetAddBtn.offsetWidth || 96, bh = widgetAddBtn.offsetHeight || 26;
  const bounds = _floatingBounds(el);
  const widget = el.closest("[data-cm-widget]");
  const reset = widget && widget.matches("[data-cm-draggable]") ? widget.querySelector(".cm-widget-reset") : null;
  const resetRect = reset && !reset.hidden ? reset.getBoundingClientRect() : null;
  const candidates = [
    { left: visible.right - bw - 6, top: visible.top + 6 },
    { left: visible.left + 6, top: visible.top + 6 },
    { left: visible.right - bw - 6, top: visible.bottom - bh - 6 },
    { left: visible.left + 6, top: visible.bottom - bh - 6 },
  ].map((pos) => ({
    left: _clamp(pos.left, bounds.left, bounds.right - bw),
    top: _clamp(pos.top, bounds.top, bounds.bottom - bh),
  }));
  const placed = candidates.find((pos) => {
    if (!resetRect) return true;
    return !_intersectRects(
      { left: pos.left, right: pos.left + bw, top: pos.top, bottom: pos.top + bh },
      resetRect,
    );
  }) || candidates[0];
  widgetAddBtn.style.left = placed.left + "px";
  widgetAddBtn.style.top = placed.top + "px";
  return true;
}
function showWidgetAddFor(el) {
  if (!widgetAddBtn) return;
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return;
  pendingWidget = widgetInfo(el);
  widgetAddBtn.title = 'Comment on "' + (pendingWidget.quote || "this element") + '"';
  if (widgetAddHideTimer) { clearTimeout(widgetAddHideTimer); widgetAddHideTimer = null; }
  widgetAddBtn.hidden = false;
  if (!positionWidgetAdd(el)) { widgetAddBtn.hidden = true; pendingWidget = null; return; }
  _activeAdd = { el, btn: widgetAddBtn, position: () => positionWidgetAdd(el), clear: () => { pendingWidget = null; } };
}
function scheduleHideWidgetAdd() {
  if (widgetAddHideTimer) clearTimeout(widgetAddHideTimer);
  widgetAddHideTimer = setTimeout(() => {
    if (widgetAddBtn && !widgetAddBtn.matches(":hover")) { widgetAddBtn.hidden = true; pendingWidget = null; }
  }, 220);
}
function openWidgetComposer(info) { return createComposerElement({ mode: "new-widget", widget: info }); }

// Canonical slot value: a part with no data-cm-slot ancestor reads as "(no slot)", used
// identically by the snapshot, the signature, and the change detector so they never disagree.
function _partSlotCanon(p) { const s = partSlot(p); return s == null ? "(no slot)" : s; }
// State-change tracking: snapshot each part's slot at load, then report moves. Pure
// function of the current DOM, so widgetStateChanges() is deterministic and idempotent.
function _snapshotWidgetState() {
  _widgetBaseline = new Map();
  root.querySelectorAll("[data-cm-widget] [data-cm-part]").forEach((p) => {
    const id = partId(p);
    if (!id) return;
    const key = partKey(widgetName(p), id);
    if (_widgetBaseline.has(key)) return;   // first-seen wins, matching indexWidgetParts dedupe
    _widgetBaseline.set(key, _partSlotCanon(p));
  });
  // A parallel DOM baseline for draggable widgets: each parent that directly held a part
  // at load time, with full child order, so resets preserve interleaved non-part nodes.
  _widgetDomBaseline = [];
  root.querySelectorAll("[data-cm-widget]").forEach((widget) => {
    if (!_widgetResetOptIn(widget)) return;
    const parents = [];
    const seenParents = new Set();
    widget.querySelectorAll("[data-cm-part]").forEach((p) => {
      const parent = p.parentElement;
      if (!parent || seenParents.has(parent)) return;
      seenParents.add(parent);
      parents.push({ parent, children: Array.from(parent.childNodes) });
    });
    if (parents.length) _widgetDomBaseline.push({ widget, name: widget.getAttribute("data-cm-widget") || "widget", parents });
  });
}
// Return the ISO time of the current widget layout change run (null when the layout matches
// its load baseline), so the sidebar can show when a board was first edited.
function widgetFirstChangeAt() { return _widgetFirstChangeAt; }
// Put one widget's recorded parent children back in load order, then re-run the
// mutation pass so the sidebar, badge, and reset buttons resync.
function _restoreWidgetDomBaseline(rec) {
  let restored = false;
  rec.parents.forEach((group) => {
    if (!group.parent || !group.children) return;
    let anchor = null;
    for (let i = group.children.length - 1; i >= 0; i--) {
      const child = group.children[i];
      if (!child) continue;
      group.parent.insertBefore(child, anchor);
      anchor = child;
      restored = true;
    }
  });
  return restored;
}
function resetWidgetMoves(widgetEl) {
  if (!widgetEl || !_widgetDomBaseline) return false;
  const changed = new Set(widgetStateChanges().map((ch) => ch.widget));
  const name = widgetEl.getAttribute("data-cm-widget") || "widget";
  const rec = _widgetDomBaseline.find((item) => item.widget === widgetEl);
  if (!rec || !changed.has(name)) return false;
  const restored = _restoreWidgetDomBaseline(rec);
  if (restored) _onWidgetMutation();
  return restored;
}
function resetAllWidgetMoves() {
  if (!_widgetDomBaseline) return false;
  const changed = new Set(widgetStateChanges().map((ch) => ch.widget));
  if (!changed.size) return false;
  let restored = false;
  _widgetDomBaseline.forEach((rec) => {
    if (!changed.has(rec.name)) return;
    restored = _restoreWidgetDomBaseline(rec) || restored;
  });
  if (restored) _onWidgetMutation();
  return restored;
}
// Show a "Reset moves" button on each draggable widget that currently differs from its load
// baseline, and remove it once the widget is clean again. The button is cm-skip and is not a
// data-cm-part, so it never enters the layout signature and cannot loop the MutationObserver.
function _syncWidgetResetButtons() {
  const changed = new Set(((typeof widgetStateChanges === "function") ? widgetStateChanges() : []).map((ch) => ch.widget));
  root.querySelectorAll("[data-cm-widget]").forEach((w) => {
    if (!_widgetResetOptIn(w)) return;
    const has = changed.has(w.getAttribute("data-cm-widget") || "widget");
    let btn = w.querySelector(":scope > .cm-widget-reset");
    if (has && !btn) {
      btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cm-skip cm-widget-reset";
      btn.textContent = "Reset moves";
      btn.title = "Return cards to their original positions";
      btn.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); resetWidgetMoves(w); });
      w.appendChild(btn);
    } else if (!has && btn) {
      btn.remove();
    }
  });
}
// A stable signature of the current widget layout (part keys + slots), used to skip no-op
// sidebar rebuilds when a mutation did not actually change any part or slot.
function _widgetStateSig() {
  const parts = [];
  const seen = new Set();
  root.querySelectorAll("[data-cm-widget] [data-cm-part]").forEach((p) => {
    const id = partId(p);
    if (!id) return;
    const key = partKey(widgetName(p), id);
    if (seen.has(key)) return;
    seen.add(key);
    parts.push(key + "\u0000" + _partSlotCanon(p));
  });
  return parts.join("\u0001");
}
function widgetStateChanges() {
  // Test/perf hook: widgetStateChanges is the document-wide widget scan that updateDocTypeUi and
  // updateCopyAllState invoke; a spec counts its invocations to prove the note-typing sync UI stays
  // gated on the dirty-state transition rather than scanning per keystroke (issue #505). Only counted
  // when a test pre-seeds the counter; production never creates it.
  if (typeof window !== "undefined" && window.__cmhPerf) window.__cmhPerf.docScans = (window.__cmhPerf.docScans || 0) + 1;
  if (!_widgetBaseline || !_widgetBaseline.size) return [];
  const out = [];
  const seen = new Set();
  root.querySelectorAll("[data-cm-widget] [data-cm-part]").forEach((p) => {
    const id = partId(p);
    if (!id) return;
    const key = partKey(widgetName(p), id);
    if (!_widgetBaseline.has(key) || seen.has(key)) return;
    seen.add(key);
    const to = _partSlotCanon(p);
    const from = _widgetBaseline.get(key);
    if (from !== to) out.push({ widget: widgetName(p), part: id, label: partLabel(p), from, to });
  });
  // A part present at load but now gone from the DOM is a removal.
  _widgetBaseline.forEach((from, key) => {
    if (seen.has(key)) return;
    const sep = key.indexOf("\u0000");
    const part = key.slice(sep + 1);
    out.push({ widget: key.slice(0, sep), part, label: part, from, to: "(removed)" });
  });
  return out;
}
function _onWidgetMutation() {
  if (_widgetRaf) return;
  const run = () => {
    _widgetRaf = 0;
    // Always re-index and reapply widget highlights, so a part node replaced in place (same
    // widget/part/slot, e.g. a framework re-render) regains its listeners and highlight.
    indexWidgetParts();
    comments.forEach((c) => { if (c.anchorType === "widget") applyWidgetHighlight(c); });
    // Only rebuild the sidebar / re-evaluate the state card when the layout actually changed,
    // so cosmetic mutations (class toggles, mermaid attribute churn) do not thrash the panel.
    const sig = _widgetStateSig();
    if (sig === _lastWidgetSig) return;
    _lastWidgetSig = sig;
    // Track when the first layout change happened (0 -> >0 transition) BEFORE rendering, so
    // the state card can show the timestamp on the same pass. Clear it once the layout
    // returns to its baseline.
    const has = widgetStateChanges().length > 0;
    if (has && !_hadWidgetChanges) _widgetFirstChangeAt = new Date().toISOString();
    if (!has) _widgetFirstChangeAt = null;
    renderComments();
    // Surface a newly-detected layout change: open the panel so the state card (which is
    // not counted as a comment) is not missed. Only on the 0 -> >0 transition, so a user
    // who closes the panel is not fought.
    if (has && !_hadWidgetChanges && typeof openSidebar === "function") openSidebar();
    _hadWidgetChanges = has;
    _syncWidgetResetButtons();
  };
  if (typeof requestAnimationFrame !== "function") { run(); return; }
  _widgetRaf = requestAnimationFrame(run);
}
function setupWidgetLayer() {
  if (!widgetAddBtn) return;
  indexWidgetParts();
  setupWidgetDragDrop();
  _snapshotWidgetState();
  _lastWidgetSig = _widgetStateSig();
  _hadWidgetChanges = widgetStateChanges().length > 0;
  _widgetFirstChangeAt = null;
  comments.filter((c) => c.anchorType === "widget").forEach((c) => {
    if (!applyWidgetHighlight(c)) console.warn("Could not restore widget highlight for", c.id);
  });
  if (!widgetAddBtn._cmWired) {
    widgetAddBtn._cmWired = true;
    widgetAddBtn.addEventListener("mouseenter", () => { if (widgetAddHideTimer) { clearTimeout(widgetAddHideTimer); widgetAddHideTimer = null; } });
    widgetAddBtn.addEventListener("mouseleave", scheduleHideWidgetAdd);
    widgetAddBtn.addEventListener("click", () => {
      if (!pendingWidget) return;
      const info = pendingWidget;
      pendingWidget = null; widgetAddBtn.hidden = true;
      openWidgetComposer(info);
    });
  }
  const widgets = root.querySelectorAll("[data-cm-widget]");
  if (widgets.length && "MutationObserver" in window) {
    if (_widgetObserver) _widgetObserver.disconnect();
    _widgetObserver = new MutationObserver(_onWidgetMutation);
    widgets.forEach((w) => _widgetObserver.observe(w, { childList: true, subtree: true }));
  }
  _syncWidgetResetButtons();
}
