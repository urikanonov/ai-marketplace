/* ---------- Inline comment dialog (opened from the hover bubble) ----------
   Clicking the hover bubble opens a small on-screen dialog next to the highlight showing the
   comment note and an Edit button (which opens the composer for that comment). A click anywhere
   else closes the dialog and is swallowed, so the outside click performs no other action (for
   example it does not follow a link the highlight sits on). The sidebar jump still runs alongside
   this from 52-hover-bubble.js. */
let commentPopover = null;
let _popoverAnchorMark = null;
let _popoverOpener = null;
let _popoverDismiss = null;
let _popoverKeydown = null;

function _positionCommentPopover(mark) {
  if (!commentPopover || !mark) return false;
  const rect = mark.getClientRects()[0] || mark.getBoundingClientRect();
  // Close instead of clamping when the anchor is scrolled/clipped out of view, matching the
  // hover bubble and the other floating affordances (they all use _clipAwareRect).
  const visible = (typeof _clipAwareRect === "function") ? _clipAwareRect(mark, rect) : rect;
  if (!visible) return false;
  const w = commentPopover.offsetWidth || 320;
  const h = commentPopover.offsetHeight || 160;
  const margin = 8;
  let left = visible.left;
  let top = visible.bottom + margin;
  if (top + h > window.innerHeight) top = Math.max(margin, visible.top - h - margin);
  left = Math.min(Math.max(margin, left), Math.max(margin, window.innerWidth - w - margin));
  top = Math.min(Math.max(margin, top), Math.max(margin, window.innerHeight - h - margin));
  commentPopover.style.left = left + "px";
  commentPopover.style.top = top + "px";
  return true;
}

function closeCommentPopover() {
  if (!commentPopover) return;
  if (_popoverDismiss) { document.removeEventListener("click", _popoverDismiss, true); _popoverDismiss = null; }
  if (_popoverKeydown) { document.removeEventListener("keydown", _popoverKeydown, true); _popoverKeydown = null; }
  commentPopover.remove();
  commentPopover = null;
  _popoverAnchorMark = null;
  // Return focus to whatever had it before the dialog opened, if still connected.
  const opener = _popoverOpener;
  _popoverOpener = null;
  if (opener && opener.isConnected) { try { opener.focus(); } catch (e) {} }
}

function openCommentPopover(id, mark) {
  closeCommentPopover();
  const c = comments.find((x) => x.id === id);
  if (!c) return;
  _popoverAnchorMark = mark && root.contains(mark) ? mark : root.querySelector(`mark.cm-hl[data-cid="${id}"]`);
  if (!_popoverAnchorMark) return;
  _popoverOpener = (document.activeElement && document.activeElement !== document.body
    && root.contains(document.activeElement)) ? document.activeElement : null;

  const el = document.createElement("div");
  el.className = "cm-comment-popover cm-skip";
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-label", "Comment");
  const noteId = "cmh-pop-note-" + Math.random().toString(36).slice(2, 9);
  el.setAttribute("aria-describedby", noteId);
  el.innerHTML =
    '<div class="cm-comment-popover-note" id="' + noteId + '"></div>'
    + '<div class="cm-comment-popover-meta"></div>'
    + '<div class="cm-comment-popover-acts">'
    + '<button type="button" data-act="close">Close</button>'
    + '<button type="button" class="primary" data-act="edit">Edit</button>'
    + "</div>";
  el.querySelector(".cm-comment-popover-note").textContent = c.note;
  el.querySelector(".cm-comment-popover-meta").textContent =
    formatTime(c.updatedAt || c.createdAt) + (c.updatedAt ? " (edited)" : "");
  document.body.appendChild(el);
  commentPopover = el;
  if (!_positionCommentPopover(_popoverAnchorMark)) { closeCommentPopover(); return; }

  el.querySelector('[data-act="edit"]').addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    closeCommentPopover();
    openComposerForEdit(c);
  });
  el.querySelector('[data-act="close"]').addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    closeCommentPopover();
  });

  // A click outside the dialog closes it. A pointer click (detail > 0) is also swallowed
  // (capture-phase preventDefault + stopPropagation) so it performs no other action - for
  // example it does not follow a link the highlight sits on. A keyboard-activated click
  // (Enter/Space, detail 0) closes the dialog but is allowed to proceed, so a keyboard user
  // is never blocked from activating an outside control. Clicks inside pass through.
  _popoverDismiss = (e) => {
    if (!commentPopover) return;
    if (e.target && e.target.closest && e.target.closest(".cm-comment-popover")) return;
    if (e.detail > 0) { e.preventDefault(); e.stopPropagation(); }
    closeCommentPopover();
  };
  _popoverKeydown = (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeCommentPopover(); }
  };
  // Register on the next tick so the opening click (on the bubble) does not immediately close it.
  setTimeout(() => {
    if (!commentPopover) return;
    document.addEventListener("click", _popoverDismiss, true);
    document.addEventListener("keydown", _popoverKeydown, true);
  }, 0);

  const editBtn = el.querySelector('[data-act="edit"]');
  if (editBtn) editBtn.focus();
}

// Keep the dialog pinned to its highlight while scrolling / resizing; close it if the anchor goes
// away or scrolls out of view (matching the hover bubble's clip-aware behavior).
window.addEventListener("scroll", () => {
  if (!commentPopover) return;
  if (!(_popoverAnchorMark && root.contains(_popoverAnchorMark) && _positionCommentPopover(_popoverAnchorMark))) closeCommentPopover();
}, true);
window.addEventListener("resize", () => {
  if (!commentPopover) return;
  if (!(_popoverAnchorMark && root.contains(_popoverAnchorMark) && _positionCommentPopover(_popoverAnchorMark))) closeCommentPopover();
});
