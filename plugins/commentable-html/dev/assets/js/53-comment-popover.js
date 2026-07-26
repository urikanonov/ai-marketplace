/* ---------- Inline comment dialog (opened from the hover bubble) ----------
   Clicking the hover bubble opens a small on-screen dialog next to the highlight showing the
   comment note and an Edit button. Edit turns the dialog itself into an editor IN PLACE, so the
   reviewer edits exactly where they clicked instead of being sent to a floating composer. A click
   anywhere else closes the dialog; a pointer click there is also swallowed so it performs no other
   action (for example it does not follow a link the highlight sits on), while a keyboard-activated
   click still reaches its target. While the dialog is being edited it stays open (an outside click
   or the anchor scrolling away would discard the draft). The sidebar jump still runs alongside this
   from 52-hover-bubble.js. */
let commentPopover = null;
let _popoverAnchorMark = null;
let _popoverDismiss = null;
let _popoverKeydown = null;
let _popoverEditing = false;

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
  _popoverEditing = false;
}

// The comment the open dialog is showing, re-read from the live array so a delete or an edit made
// elsewhere is never written back from a stale copy.
function _popoverComment() {
  const id = commentPopover ? commentPopover.getAttribute("data-cid") : null;
  return id ? comments.find((x) => x.id === id) : null;
}

function _renderCommentPopoverView(c) {
  const el = commentPopover;
  if (!el) return;
  _popoverEditing = false;
  el.classList.remove("is-editing");
  const noteId = el.getAttribute("data-note-id");
  el.innerHTML =
    '<div class="cm-comment-popover-note cmh-rich" id="' + noteId + '"></div>'
    + '<div class="cm-comment-popover-meta"></div>'
    + '<div class="cm-comment-popover-acts">'
    + '<button type="button" data-act="close">Close</button>'
    + '<button type="button" class="primary" data-act="edit">Edit</button>'
    + "</div>";
  el.setAttribute("aria-describedby", noteId);
  el.querySelector(".cm-comment-popover-note").innerHTML = renderRichNote(c.note);
  el.querySelector(".cm-comment-popover-meta").innerHTML =
    "<bdi>" + escapeHtml(formatTime(c.updatedAt || c.createdAt)) + "</bdi>"
    + (c.updatedAt ? " (edited)" : "");
  el.querySelector('[data-act="edit"]').addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    const cur = _popoverComment();
    if (cur) _renderCommentPopoverEdit(cur);
  });
  el.querySelector('[data-act="close"]').addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    closeCommentPopover();
  });
  _positionCommentPopover(_popoverAnchorMark);
}

// Cancel an in-progress edit: back to the note view with focus on Edit, dialog left open.
function _cancelCommentPopoverEdit() {
  const cur = _popoverComment();
  if (!cur) { closeCommentPopover(); return; }
  _renderCommentPopoverView(cur);
  _focusPopoverEditButton();
}

function _focusPopoverEditButton() {
  const eb = commentPopover && commentPopover.querySelector('[data-act="edit"]');
  if (eb) { try { eb.focus(); } catch (e) {} }
}

function _renderCommentPopoverEdit(c) {
  const el = commentPopover;
  if (!el) return;
  _popoverEditing = true;
  el.classList.add("is-editing");
  // The described note element is replaced by the editor, so its description no longer applies.
  el.removeAttribute("aria-describedby");
  el.innerHTML =
    '<div class="cm-comment-popover-edit">'
    + '<textarea class="cm-comment-popover-input" rows="4" aria-label="Edit comment"></textarea>'
    + "</div>"
    + '<div class="cm-comment-popover-acts">'
    + '<button type="button" data-act="edit-cancel">Cancel</button>'
    + '<button type="button" class="primary" data-act="edit-save">Save</button>'
    + "</div>";
  const ta = el.querySelector("textarea");
  ta.value = c.note == null ? "" : c.note;
  function doSave() {
    const val = ta.value.trim();
    if (!val) {
      // Blank note: mark the field invalid (announced to screen readers) instead of silently
      // doing nothing, matching the composer.
      ta.setAttribute("aria-invalid", "true");
      ta.classList.add("cm-invalid");
      ta.focus();
      return;
    }
    const cur = _popoverComment();
    if (!cur) {
      showToast("The comment you were editing was deleted - your change was not saved.", { alert: true, duration: 6000 });
      closeCommentPopover();
      return;
    }
    cur.note = val;
    cur.updatedAt = new Date().toISOString();
    const ok = saveComments();
    renderComments();
    _renderCommentPopoverView(cur);
    _focusPopoverEditButton();
    if (typeof _afterInlineSaveQuota === "function") _afterInlineSaveQuota(ok, "edit");
  }
  el.querySelector('[data-act="edit-save"]').addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    doSave();
  });
  el.querySelector('[data-act="edit-cancel"]').addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    _cancelCommentPopoverEdit();
  });
  ta.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doSave(); }
  });
  _positionCommentPopover(_popoverAnchorMark);
  setTimeout(() => { try { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); } catch (e) {} }, 0);
}

function openCommentPopover(id, mark) {
  closeCommentPopover();
  const c = comments.find((x) => x.id === id);
  if (!c) return;
  _popoverAnchorMark = mark && root.contains(mark) ? mark : root.querySelector(`mark.cm-hl[data-cid="${id}"]`);
  if (!_popoverAnchorMark) return;

  const el = document.createElement("div");
  el.className = "cm-comment-popover cm-skip";
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-label", "Comment");
  el.setAttribute("data-cid", id);
  el.setAttribute("data-note-id", "cmh-pop-note-" + Math.random().toString(36).slice(2, 9));
  document.body.appendChild(el);
  commentPopover = el;
  _renderCommentPopoverView(c);
  if (!_positionCommentPopover(_popoverAnchorMark)) { closeCommentPopover(); return; }

  // A click outside the dialog closes it. A pointer click (detail > 0) is also swallowed
  // (capture-phase preventDefault + stopPropagation) so it performs no other action - for
  // example it does not follow a link the highlight sits on. A keyboard-activated click
  // (Enter/Space, detail 0) closes the dialog but is allowed to proceed, so a keyboard user
  // is never blocked from activating an outside control. Clicks inside pass through.
  _popoverDismiss = (e) => {
    if (!commentPopover) return;
    if (e.target && e.target.closest && e.target.closest(".cm-comment-popover")) return;
    // Mid-edit the dialog stays open (closing it would silently discard the draft) and the click
    // is left alone, so the rest of the page keeps working while the editor is up.
    if (_popoverEditing) return;
    if (e.detail > 0) { e.preventDefault(); e.stopPropagation(); }
    closeCommentPopover();
  };
  _popoverKeydown = (e) => {
    if (e.key !== "Escape") return;
    e.preventDefault(); e.stopPropagation();
    // Escape cancels an in-progress edit first (back to the note); a second Escape closes.
    if (_popoverEditing) _cancelCommentPopoverEdit();
    else closeCommentPopover();
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
// away or scrolls out of view (matching the hover bubble's clip-aware behavior) - unless it is
// being edited, in which case it stays where it is rather than discarding the draft.
function _syncCommentPopoverToAnchor() {
  if (!commentPopover) return;
  const pinned = _popoverAnchorMark && root.contains(_popoverAnchorMark) && _positionCommentPopover(_popoverAnchorMark);
  if (!pinned && !_popoverEditing) closeCommentPopover();
}
window.addEventListener("scroll", _syncCommentPopoverToAnchor, true);
window.addEventListener("resize", _syncCommentPopoverToAnchor);
