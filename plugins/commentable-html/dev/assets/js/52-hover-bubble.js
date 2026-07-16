/* ---------- Hover bubble to open a comment ----------
   A highlighted region can itself be a link (or other clickable element), so a plain
   click there navigates instead of opening the comment. Hovering any highlight shows
   this small bubble; clicking it opens the comment regardless of what the text links to. */
const hlBubble = document.getElementById("hlBubble");
let hlBubbleCid = null, hlBubbleMark = null, hlBubbleHideTimer = null;
function positionHlBubble(mark) {
  const rect = mark.getClientRects()[0] || mark.getBoundingClientRect();
  const visible = _clipAwareRect(mark, rect);
  if (!visible) {
    hlBubble.hidden = true; hlBubbleCid = null; hlBubbleMark = null; return;
  }
  const bw = hlBubble.offsetWidth || 22, bh = hlBubble.offsetHeight || 22;
  const bounds = _floatingBounds(mark);
  let left = visible.right - bw / 2;
  let top  = visible.top - bh + 4;
  if (top < bounds.top) top = visible.bottom - 4;
  left = _clamp(left, bounds.left, bounds.right - bw);
  top  = _clamp(top, bounds.top, bounds.bottom - bh);
  hlBubble.style.left = left + "px";
  hlBubble.style.top  = top  + "px";
}
function showHlBubbleFor(mark) {
  if (!mark.dataset.cid) return;
  if (hlBubbleHideTimer) { clearTimeout(hlBubbleHideTimer); hlBubbleHideTimer = null; }
  hlBubbleCid = mark.dataset.cid;
  hlBubbleMark = mark;
  hlBubble.hidden = false;
  positionHlBubble(mark);
}
function scheduleHideHlBubble() {
  if (hlBubbleHideTimer) clearTimeout(hlBubbleHideTimer);
  hlBubbleHideTimer = setTimeout(() => {
    if (!hlBubble.matches(":hover")) { hlBubble.hidden = true; hlBubbleCid = null; hlBubbleMark = null; }
  }, 240);
}
root.addEventListener("mouseover", (e) => {
  if (e.buttons) return; // mid-drag: user is selecting text, don't pop the bubble
  const mark = e.target.closest && e.target.closest("mark.cm-hl");
  if (!mark || !root.contains(mark)) return;
  if (mark === hlBubbleMark && !hlBubble.hidden) {
    if (hlBubbleHideTimer) { clearTimeout(hlBubbleHideTimer); hlBubbleHideTimer = null; }
    return;
  }
  showHlBubbleFor(mark);
});
root.addEventListener("mouseout", (e) => {
  if (!(e.target.closest && e.target.closest("mark.cm-hl"))) return;
  const to = e.relatedTarget;
  if (to && to.closest && (to.closest("mark.cm-hl") || to.closest(".cm-hl-bubble"))) return;
  scheduleHideHlBubble();
});
hlBubble.addEventListener("mouseenter", () => {
  if (hlBubbleHideTimer) { clearTimeout(hlBubbleHideTimer); hlBubbleHideTimer = null; }
});
hlBubble.addEventListener("mouseleave", scheduleHideHlBubble);
hlBubble.addEventListener("click", (e) => {
  e.preventDefault(); e.stopPropagation();
  const id = hlBubbleCid;
  hlBubble.hidden = true; hlBubbleCid = null; hlBubbleMark = null;
  if (!id) return;
  openSidebar();
  const card = listEl.querySelector(`.cm-card[data-cid="${id}"]`);
  if (card) card.scrollIntoView({ behavior: cmScrollBehavior(), block: "center" });
  flashActive(id);
});
window.addEventListener("scroll", () => {
  if (hlBubble.hidden) return;
  if (hlBubbleMark && root.contains(hlBubbleMark)) positionHlBubble(hlBubbleMark);
  else { hlBubble.hidden = true; hlBubbleCid = null; hlBubbleMark = null; }
}, true);
// Keep the floating add-comment buttons (image / mermaid / diff) pinned to their
// target while scrolling or resizing, instead of leaving them at a stale fixed
// position. If the target scrolls out of view, hide the button rather than clamp
// it to a viewport edge (detached from what it points at).
function repositionActiveAdd() {
  if (!_activeAdd || !_activeAdd.btn || _activeAdd.btn.hidden) return;
  const el = _activeAdd.el;
  // Re-run positioning only (never show*AddFor), so a scroll cannot cancel the
  // mouseleave hide-timer and leave a stuck button. position() returns false when
  // the target scrolled out of view or collapsed to zero size; hide and clear then.
  if (!el || !root.contains(el) || !_activeAdd.position()) {
    _activeAdd.btn.hidden = true;
    if (_activeAdd.clear) _activeAdd.clear();
    _activeAdd = null;
  }
}
let _repositionAddRaf = 0;
function scheduleRepositionActiveAdd() {
  if (_repositionAddRaf) return;
  if (typeof requestAnimationFrame !== "function") { repositionActiveAdd(); return; }
  _repositionAddRaf = requestAnimationFrame(() => { _repositionAddRaf = 0; repositionActiveAdd(); });
}
window.addEventListener("scroll", scheduleRepositionActiveAdd, true);
window.addEventListener("resize", scheduleRepositionActiveAdd);
window.addEventListener("resize", () => {
  if (hlBubble.hidden) return;
  if (hlBubbleMark && root.contains(hlBubbleMark)) positionHlBubble(hlBubbleMark);
  else { hlBubble.hidden = true; hlBubbleCid = null; hlBubbleMark = null; }
});
// A mousedown that is not on the bubble means a click or selection is starting; drop the
// bubble so it can never act on a stale highlight (e.g. a drag-select that began on another mark).
document.addEventListener("mousedown", (e) => {
  if (hlBubble.hidden) return;
  if (e.target.closest && e.target.closest(".cm-hl-bubble")) return;
  if (hlBubbleHideTimer) { clearTimeout(hlBubbleHideTimer); hlBubbleHideTimer = null; }
  hlBubble.hidden = true; hlBubbleCid = null; hlBubbleMark = null;
});


let _sidebarWidthPx = 0;
function _sidebarWidthBounds() {
  const vw = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0, 1);
  const narrow = vw < 700;
  // Legible floor: below ~240px the two-per-row export button labels ("Portable",
  // "Plain HTML", ...) and the search placeholder start to clip. 256px (16rem) keeps every
  // panel control fully shown with a small cross-platform buffer; the CSS min-width matches.
  // Still clamped to the viewport so a very small screen keeps a usable pane.
  const min = Math.min(256, Math.max(108, vw - 48));
  const max = Math.max(min, Math.min(narrow ? Math.round(vw * 0.82) : 720, vw - 24));
  return { min: min, max: max, defaultWidth: Math.max(min, Math.min(400, max)) };
}
function _clampSidebarWidth(value) {
  const b = _sidebarWidthBounds();
  const n = Number(value);
  if (!Number.isFinite(n)) return b.defaultWidth;
  return Math.max(b.min, Math.min(b.max, Math.round(n)));
}
function _setSidebarWidth(value, persist) {
  const b = _sidebarWidthBounds();
  const w = _clampSidebarWidth(value);
  _sidebarWidthPx = w;
  document.documentElement.style.setProperty("--cm-sidebar-w", w + "px");
  if (sidebar) sidebar.classList.toggle("is-narrow", w <= 340);
  const handle = document.getElementById("sidebarResizeHandle");
  if (handle) {
    handle.setAttribute("aria-valuemin", String(b.min));
    handle.setAttribute("aria-valuemax", String(b.max));
    handle.setAttribute("aria-valuenow", String(w));
    handle.setAttribute("aria-valuetext", w + " pixels");
  }
  if (persist) {
    try { localStorage.setItem(SIDEBAR_WIDTH_KEY, String(w)); } catch (e) { /* private mode */ }
  }
  _syncFloatingAfterLayoutShift();
  return w;
}
function setupSidebarResize() {
  if (!sidebar) return;
  let saved = null;
  try { saved = localStorage.getItem(SIDEBAR_WIDTH_KEY); } catch (e) { saved = null; }
  _setSidebarWidth(saved == null ? _sidebarWidthBounds().defaultWidth : Number(saved), false);
  window.addEventListener("resize", function () { _setSidebarWidth(_sidebarWidthPx || _sidebarWidthBounds().defaultWidth, false); });
  const handle = document.getElementById("sidebarResizeHandle");
  if (!handle || handle._cmWired) return;
  handle._cmWired = true;
  let dragging = false;
  function widthFromEvent(e) { return (window.innerWidth || document.documentElement.clientWidth || 0) - e.clientX; }
  function onDrag(e) {
    if (!dragging) return;
    _setSidebarWidth(widthFromEvent(e), false);
    e.preventDefault();
  }
  function finish(e) {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove("cm-sidebar-resizing");
    document.removeEventListener("pointermove", onDrag, true);
    document.removeEventListener("pointerup", finish, true);
    document.removeEventListener("pointercancel", finish, true);
    try { handle.releasePointerCapture(e.pointerId); } catch (err) { /* pointer may already be released */ }
    _setSidebarWidth(_sidebarWidthPx, true);
  }
  handle.addEventListener("pointerdown", beginPointerResize);
  handle.addEventListener("pointermove", onDrag);
  handle.addEventListener("pointerup", finish);
  handle.addEventListener("pointercancel", finish);
  function onMouseDrag(e) {
    if (!dragging) return;
    _setSidebarWidth(widthFromEvent(e), false);
    e.preventDefault();
  }
  function finishMouse(e) {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove("cm-sidebar-resizing");
    document.removeEventListener("mousemove", onMouseDrag, true);
    document.removeEventListener("mouseup", finishMouse, true);
    _setSidebarWidth(_sidebarWidthPx, true);
    e.preventDefault();
  }
  function beginMouseResize(e) {
    if (dragging || (e.button != null && e.button !== 0)) return false;
    dragging = true;
    handle.focus({ preventScroll: true });
    document.body.classList.add("cm-sidebar-resizing");
    document.addEventListener("mousemove", onMouseDrag, true);
    document.addEventListener("mouseup", finishMouse, true);
    _setSidebarWidth(widthFromEvent(e), false);
    e.preventDefault();
    return true;
  }
  function beginPointerResize(e) {
    if (dragging || (e.button != null && e.button !== 0)) return false;
    dragging = true;
    handle.focus({ preventScroll: true });
    document.body.classList.add("cm-sidebar-resizing");
    try { handle.setPointerCapture(e.pointerId); } catch (err) { /* capture is best effort */ }
    document.addEventListener("pointermove", onDrag, true);
    document.addEventListener("pointerup", finish, true);
    document.addEventListener("pointercancel", finish, true);
    _setSidebarWidth(widthFromEvent(e), false);
    e.preventDefault();
    return true;
  }
  handle.addEventListener("mousedown", beginMouseResize);
  if (sidebar) {
    sidebar.addEventListener("mousedown", function (e) {
      const r = sidebar.getBoundingClientRect();
      if (e.clientX <= r.left + 12) beginMouseResize(e);
    });
    sidebar.addEventListener("pointerdown", function (e) {
      const r = sidebar.getBoundingClientRect();
      if (e.clientX <= r.left + 12) beginPointerResize(e);
    });
  }
  handle.addEventListener("dblclick", function () { _setSidebarWidth(_sidebarWidthBounds().defaultWidth, true); });
  handle.addEventListener("keydown", function (e) {
    const b = _sidebarWidthBounds();
    const step = e.shiftKey ? 60 : 20;
    let next = null;
    if (e.key === "ArrowLeft") next = (_sidebarWidthPx || b.defaultWidth) + step;
    else if (e.key === "ArrowRight") next = (_sidebarWidthPx || b.defaultWidth) - step;
    else if (e.key === "Home") next = b.min;
    else if (e.key === "End") next = b.max;
    if (next != null) {
      _setSidebarWidth(next, true);
      e.preventDefault();
    }
  });
}

