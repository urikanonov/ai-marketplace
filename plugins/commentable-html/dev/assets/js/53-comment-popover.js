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
// The dialog's identity is kept in JS state, never re-read from its own DOM attributes: the note id
// is interpolated into the dialog markup, and a value that round-trips through the DOM is both a
// needless trust boundary and an injection sink.
let _popoverCid = null;
let _popoverNoteId = null;
// Removes the formatting toolbar's listeners; the toolbar itself dies with the editor markup, so
// this only has to run when the editor is replaced or the dialog closes.
let _popoverFormatOff = null;

function _releasePopoverFormatBar() {
  if (!_popoverFormatOff) return;
  const off = _popoverFormatOff;
  _popoverFormatOff = null;
  try { off(); } catch (e) {}
}

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
  _releasePopoverFormatBar();
  commentPopover.remove();
  commentPopover = null;
  _popoverAnchorMark = null;
  _popoverEditing = false;
  _popoverCid = null;
  _popoverNoteId = null;
}

// The comment the open dialog is showing, re-read from the live array so a delete or an edit made
// elsewhere is never written back from a stale copy.
function _popoverComment() {
  return _popoverCid ? comments.find((x) => x.id === _popoverCid) : null;
}

// A deleted comment's dialog must not linger (its Save would have nothing to write), so a delete or
// a clear-all closes the dialog when it shows one of the removed comments.
function cmhClosePopoverForIds(ids) {
  if (!commentPopover || !ids) return;
  const list = Array.isArray(ids) ? ids : [ids];
  if (_popoverCid && list.indexOf(_popoverCid) !== -1) closeCommentPopover();
}

// Cross-surface edit coordination (see cmhSidebarNoteEditor): reports the dialog's own in-place
// editor for `cid`, whether it holds unsaved text, and how to focus or cancel it.
function cmhPopoverNoteEditor(cid) {
  if (!commentPopover || !_popoverEditing) return null;
  if (_popoverCid !== cid) return null;
  const ta = commentPopover.querySelector("textarea");
  const c = _popoverComment();
  const original = (c && c.note != null) ? String(c.note) : "";
  return {
    dirty: !!ta && ta.value.trim() !== original.trim(),
    focus: function () { if (ta) { try { ta.focus(); } catch (e) {} } },
    // Yielding ownership CLOSES the dialog rather than dropping back to its note view: a lingering
    // view-mode dialog would re-arm the capture-phase outside-click swallow and eat the reader's
    // first click on the editor that just took over.
    close: function () { closeCommentPopover(); },
  };
}

function _renderCommentPopoverView(c) {
  const el = commentPopover;
  if (!el) return;
  _popoverEditing = false;
  _releasePopoverFormatBar();
  el.classList.remove("is-editing");
  const noteId = _popoverNoteId;
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
    if (!cur) return;
    // A floating edit composer for this note may already be open (re-selecting the highlighted text
    // opens one); reuse it rather than editing the same note in two places.
    if (typeof openEditComposers !== "undefined" && openEditComposers.get(cur.id)) {
      closeCommentPopover();
      if (typeof openComposerForEdit === "function") openComposerForEdit(cur);
      return;
    }
    // The comments panel may already be editing this note (see cmhSidebarNoteEditor): hand a dirty
    // draft back to it rather than opening a second editor whose save would overwrite it.
    if (typeof cmhSidebarNoteEditor === "function") {
      const side = cmhSidebarNoteEditor(cur.id);
      if (side) {
        if (side.dirty) {
          // Nothing left for the dialog to do: point the reader at the panel's draft and get out of
          // the way (a dialog left open would swallow their next click).
          closeCommentPopover();
          side.focus();
          showToast("This comment is already open for editing in the comments panel - finish or cancel that edit first.", { duration: 5000 });
          return;
        }
        side.close();
      }
    }
    _renderCommentPopoverEdit(cur);
  });
  el.querySelector('[data-act="close"]').addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    closeCommentPopover();
  });
  _positionCommentPopover(_popoverAnchorMark);
}

// Cancel an in-progress edit: back to the note view with focus on Edit, dialog left open (unless
// its anchor scrolled away meanwhile, in which case the normal clip-aware close applies again).
function _cancelCommentPopoverEdit() {
  const cur = _popoverComment();
  if (!cur) { closeCommentPopover(); return; }
  _renderCommentPopoverView(cur);
  _syncCommentPopoverToAnchor();
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
  const wrap = el.querySelector(".cm-comment-popover-edit");
  const ta = el.querySelector("textarea");
  // The dialog offers the same rich-text editing as the floating composer and the side pane
  // (issue #776): the shared toolbar above the textarea plus the Ctrl/Cmd formatting shortcuts.
  const formatBar = noteFormatBarElement();
  wrap.insertBefore(formatBar, ta);
  _releasePopoverFormatBar();
  _popoverFormatOff = wireNoteFormatBar(formatBar, ta);
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
    // Editing suspended the clip-aware close; with the edit done, re-apply it (the anchor may have
    // scrolled out of view meanwhile) so the dialog is never stranded away from its highlight.
    _syncCommentPopoverToAnchor();
    _focusPopoverEditButton();
    if (typeof _afterInlineSaveQuota === "function") _afterInlineSaveQuota(ok, "edit");
  }
  const acts = el.querySelector(".cm-comment-popover-acts");
  // A pointer press on Save/Cancel ends an IME composition before the click arrives, so the click
  // alone cannot tell it began mid-composition. Latch the state at press time (and swallow that
  // press so it does not end the composition), so an accidental activation during a candidate
  // window neither commits nor discards the draft. A keyboard activation has no press, so the live
  // composition state answers for it.
  let _pressedComposing = false;
  const actsDown = (e) => {
    _pressedComposing = isNoteComposing(ta);
    if (_pressedComposing) { e.preventDefault(); e.stopPropagation(); }
  };
  acts.addEventListener("pointerdown", actsDown);
  acts.addEventListener("mousedown", actsDown);
  function actsComposing() {
    const was = _pressedComposing || isNoteComposing(ta);
    _pressedComposing = false;
    return was;
  }
  el.querySelector('[data-act="edit-save"]').addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    if (actsComposing()) return;
    doSave();
  });
  el.querySelector('[data-act="edit-cancel"]').addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    if (actsComposing()) return;
    _cancelCommentPopoverEdit();
  });
  // Clear the blank-note invalid state as soon as the reviewer types or formats, matching the
  // other editors (a toolbar action dispatches its own `input` event).
  ta.addEventListener("input", () => { ta.removeAttribute("aria-invalid"); ta.classList.remove("cm-invalid"); });
  // Bind on the CONTAINERS, not the textarea, so the shortcuts and Ctrl/Cmd+Enter also work from a
  // focused toolbar, Cancel, or Save button (they would otherwise be dead keyboard ends). The
  // dialog's Escape stays with the capture-phase document handler, which already scopes it to the
  // dialog; the acts row is a sibling of the editor, so both get the handler.
  const onEditorKeydown = (e) => {
    if (e.isComposing || isNoteComposing(ta)) return;
    if (handleNoteFormatShortcut(e, ta)) return;
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); e.stopPropagation(); doSave(); }
  };
  wrap.addEventListener("keydown", onEditorKeydown);
  acts.addEventListener("keydown", onEditorKeydown);
  _positionCommentPopover(_popoverAnchorMark);
  setTimeout(() => { try { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); } catch (e) {} }, 0);
}

function openCommentPopover(id, mark) {
  // Never discard an in-progress edit because another highlight was clicked: a dirty dialog keeps
  // its draft and its focus, and the reader finishes or cancels it first.
  const openEditor = commentPopover ? cmhPopoverNoteEditor(commentPopover.getAttribute("data-cid")) : null;
  if (openEditor && openEditor.dirty) {
    openEditor.focus();
    showToast("Finish or cancel the comment you are editing first.", { duration: 5000 });
    return;
  }
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
  document.body.appendChild(el);
  commentPopover = el;
  _popoverCid = id;
  _popoverNoteId = "cmh-pop-note-" + Math.random().toString(36).slice(2, 9);
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
    // Mid-IME-composition Escape dismisses the candidate window; it must not cancel the edit
    // (the sidebar and composer editors ignore composition for the same reason). The tracked
    // composition state covers engines that report the keydown with `isComposing` already false.
    if (e.isComposing) return;
    if (_popoverEditing) {
      const ta = commentPopover && commentPopover.querySelector("textarea");
      if (isNoteComposing(ta)) return;
      // Escape belongs to the editor only while focus is inside it: another overlay's Escape (a
      // Help panel, a confirm dialog) must not silently discard the draft sitting behind it.
      if (!(e.target && e.target.closest && e.target.closest(".cm-comment-popover"))) return;
      e.preventDefault(); e.stopPropagation();
      // Escape cancels an in-progress edit first (back to the note); a second Escape closes.
      _cancelCommentPopoverEdit();
      return;
    }
    e.preventDefault(); e.stopPropagation();
    closeCommentPopover();
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
