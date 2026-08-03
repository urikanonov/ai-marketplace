/* ---------- Inline comment dialog (opened from the hover bubble) ----------
   Clicking the hover bubble opens a small on-screen dialog next to the highlight showing the
   comment note and an Edit button. Edit turns the dialog itself into an editor IN PLACE, so the
   reviewer edits exactly where they clicked instead of being sent to a floating composer. A click
   anywhere else closes the dialog; a pointer click in the ANNOTATED DOCUMENT is also swallowed so
   it performs no other action (for example it does not follow a link the highlight sits on), while
   a keyboard-activated click, and a click on the layer's own surfaces (its chrome, and the editors
   it has open), still reach their target.
   While the dialog is being edited it stays open (an outside click
   or the anchor scrolling away would discard the draft). The sidebar jump still runs alongside this
   from 52-hover-bubble.js. */
let commentPopover = null;
let _popoverAnchorMark = null;
let _popoverDismiss = null;
// Set only once the dismiss listener is actually REGISTERED (a tick after the dialog opens), so the
// swallow predicate never claims a click will be swallowed while nothing is listening yet.
let _popoverArmed = false;
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
// The last position the layer WROTE, so the unanchored re-fit clamps its own previous output rather
// than a measured rect: a fixed element inside a transformed host ancestor measures at a different
// offset than it was written to, and feeding that back in would walk the dialog across the screen.
let _popoverLeft = null;
let _popoverTop = null;
// Watches the dialog's own box, so content that grows AFTER it was positioned (the reviewer drags
// the textarea's resize handle) is re-fitted instead of pushing the actions row past the bottom.
let _popoverResizeObs = null;
let _popoverRefitting = false;

function _releasePopoverFormatBar() {
  if (!_popoverFormatOff) return;
  const off = _popoverFormatOff;
  _popoverFormatOff = null;
  try { off(); } catch (e) {}
}

// The margin the dialog keeps from every viewport edge, and the height cap derived from it.
const _POPOVER_MARGIN = 8;

// Nothing else constrains the dialog's height, so on a short viewport the edit form's Save/Cancel
// row could sit past the bottom edge with no way to scroll to it (issue #825). Cap it to the
// MEASURED viewport - which follows a dynamic mobile browser toolbar, unlike a `vh` unit - and let
// the content scroll inside. No floor: a cap that exceeded the viewport would reintroduce the very
// overflow this prevents.
function _capCommentPopoverToViewport() {
  if (!commentPopover) return;
  commentPopover.style.maxHeight = Math.max(0, window.innerHeight - _POPOVER_MARGIN * 2) + "px";
}

// Re-fit the dialog to the viewport WITHOUT re-anchoring it. An in-progress edit deliberately
// survives its anchor scrolling out of view, and on that path there is no anchor to position
// against - but a viewport shrink must still not strand Save/Cancel off screen.
function _clampCommentPopoverIntoViewport() {
  if (!commentPopover) return;
  _capCommentPopoverToViewport();
  const margin = _POPOVER_MARGIN;
  const w = commentPopover.offsetWidth || 320;
  const h = commentPopover.offsetHeight || 160;
  const cur = (_popoverLeft == null || _popoverTop == null)
    ? commentPopover.getBoundingClientRect()
    : { left: _popoverLeft, top: _popoverTop };
  const left = Math.min(Math.max(margin, cur.left), Math.max(margin, window.innerWidth - w - margin));
  const top = Math.min(Math.max(margin, cur.top), Math.max(margin, window.innerHeight - h - margin));
  _writeCommentPopoverPosition(left, top);
}

function _writeCommentPopoverPosition(left, top) {
  _popoverLeft = left;
  _popoverTop = top;
  commentPopover.style.left = left + "px";
  commentPopover.style.top = top + "px";
}

// Re-fit after the dialog's own content changed size. Guarded against re-entry because writing the
// cap can itself change the box the observer is watching.
function _refitCommentPopover() {
  if (!commentPopover || _popoverRefitting) return;
  _popoverRefitting = true;
  try { _syncCommentPopoverToAnchor(); } finally { _popoverRefitting = false; }
}

function _positionCommentPopover(mark) {
  if (!commentPopover || !mark) return false;
  // Cap BEFORE anything can return early, so the height cap is never skipped on a path that leaves
  // the dialog open, and before measuring, so the clamp below sees the capped height.
  _capCommentPopoverToViewport();
  const rect = mark.getClientRects()[0] || mark.getBoundingClientRect();
  // Close instead of clamping when the anchor is scrolled/clipped out of view, matching the
  // hover bubble and the other floating affordances (they all use _clipAwareRect).
  const visible = (typeof _clipAwareRect === "function") ? _clipAwareRect(mark, rect) : rect;
  if (!visible) return false;
  const margin = _POPOVER_MARGIN;
  const w = commentPopover.offsetWidth || 320;
  const h = commentPopover.offsetHeight || 160;
  let left = visible.left;
  let top = visible.bottom + margin;
  if (top + h > window.innerHeight) top = Math.max(margin, visible.top - h - margin);
  left = Math.min(Math.max(margin, left), Math.max(margin, window.innerWidth - w - margin));
  top = Math.min(Math.max(margin, top), Math.max(margin, window.innerHeight - h - margin));
  _writeCommentPopoverPosition(left, top);
  return true;
}

// The element a click landed on, normalized to an Element so the containment checks below work for
// a synthetic click dispatched at a text node too.
function _cmhClickElement(target) {
  if (!target) return null;
  return target.nodeType === 1 ? target : (target.parentElement || null);
}

// The propagation path an event took, fixed at DISPATCH time. Every membership test below prefers
// it over the live tree: a node another capture-phase listener detached in the same tick is still
// classified by where it was clicked, and the path sees through a shadow root. Null where the
// engine does not implement `composedPath`, and each caller then falls back to live containment.
function _cmhEventPath(e) {
  const path = e && typeof e.composedPath === "function" ? e.composedPath() : null;
  return path && path.length ? path : null;
}

// True when the click landed inside the LIVE dialog. Identity, never a class match: the annotated
// document is author content, and an element there carrying `cm-comment-popover` would otherwise be
// mistaken for the dialog - leaving the real one open AND letting the click act.
function _cmhClickIsInPopover(target, path) {
  if (!commentPopover) return false;
  if (path) return path.indexOf(commentPopover) !== -1;
  const el = _cmhClickElement(target);
  return !!(el && commentPopover.contains(el));
}

// The editors the dialog must never steal a click from: the side pane's inline reply/edit editor
// and the floating composer. Both are resolved by IDENTITY against the layer's own state - the one
// active inline editor, and the set of composers the layer opened - never by a bare class match,
// which document content could spoof to defeat the outside-click swallow below. They are still
// resolved separately from the containment test below because they can live INSIDE `root` (and do,
// wholesale, in the CMH-CORE-15 `<body>` fallback), which is also the only mode where this decides
// anything.
function _cmhClickIsInLayerEditor(target, path) {
  const pane = _activeInlineEditor && _activeInlineEditor.el;
  if (path) {
    for (let i = 0; i < path.length; i++) {
      const node = path[i];
      if (pane && node === pane) return true;
      if (openComposers.has(node)) return true;
    }
    return false;
  }
  const el = _cmhClickElement(target);
  if (!el) return false;
  if (pane && pane.contains(el)) return true;
  const composer = el.closest ? el.closest(".cm-composer") : null;
  return !!(composer && openComposers.has(composer));
}

// True when the click landed in the ANNOTATED DOCUMENT, which is the only thing the swallow exists
// to stop acting. Stating it that way rather than enumerating carve-outs means layer chrome OUTSIDE
// that root - the hover bubble, an overlay or toast the dialog's own Save raised, and any chrome
// added outside it later - keeps its first click for free.
function _cmhClickIsInAnnotatedDocument(e, path) {
  // Where `#commentRoot` is absent the layer anchors to `<body>` (CMH-CORE-15) and the whole page IS
  // the annotated document - chrome included, since containment cannot separate the two there. Answer
  // true for EVERY click in that mode (`<html>` and a non-element target too, which a containment
  // test would let through) so its swallow stays exactly what it was before this rule was inverted;
  // the identity-resolved editor carve-out above is what keeps that mode's editors working, as before.
  if (root === document.body) return true;
  if (path) return path.indexOf(root) !== -1;
  const el = _cmhClickElement(e.target);
  // Without a path, a target that resolves to no element - or to one already detached, which
  // containment would call "outside" - cannot be classified, so keep this guard's fail-CLOSED
  // default and swallow it, exactly as the rule did before it was inverted.
  return el && el.isConnected ? root.contains(el) : true;
}

// True when the open dialog will swallow this click (capture-phase preventDefault +
// stopPropagation), so the click never reaches its target. 90-toast.js asks THIS predicate rather
// than re-deriving the condition, so the two can never drift apart. It keys on the dismiss listener
// being ARMED, not merely on the dialog existing: the listener is registered a tick after the dialog
// opens, and in that window nothing swallows anything.
function cmhPopoverWouldSwallowClick(e) {
  if (!commentPopover || !_popoverArmed || !e || !(e.detail > 0)) return false;
  if (_popoverEditing) return false;
  const path = _cmhEventPath(e);
  if (_cmhClickIsInPopover(e.target, path)) return false;
  if (!_cmhClickIsInAnnotatedDocument(e, path)) return false;
  return !_cmhClickIsInLayerEditor(e.target, path);
}

function closeCommentPopover() {
  if (!commentPopover) return;
  if (_popoverDismiss) { document.removeEventListener("click", _popoverDismiss, true); _popoverDismiss = null; }
  if (_popoverKeydown) { document.removeEventListener("keydown", _popoverKeydown, true); _popoverKeydown = null; }
  _popoverArmed = false;
  _releasePopoverFormatBar();
  if (_popoverResizeObs) { try { _popoverResizeObs.disconnect(); } catch (e) {} _popoverResizeObs = null; }
  cmhForgetAutogrow(commentPopover.querySelector("textarea"));
  commentPopover.remove();
  commentPopover = null;
  _popoverAnchorMark = null;
  _popoverEditing = false;
  _popoverCid = null;
  _popoverNoteId = null;
  _popoverLeft = null;
  _popoverTop = null;
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
  if (!_positionCommentPopover(_popoverAnchorMark)) _clampCommentPopoverIntoViewport();
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
  // The dialog already owns its placement (it caps itself to the viewport and re-clamps against a
  // tracked left/top), so growth is routed through that refit rather than moved from here - writing
  // the measured rect directly would leave those tracked coordinates stale.
  cmhAutogrow(ta, function () { _refitCommentPopover(); });
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
  // The edit form is much taller than the note view, so if the anchor cannot be resolved right now
  // (it scrolled out of view, or its highlight was re-rendered) the dialog is re-fitted on its own
  // rather than left at the shorter view's position with the taller form in it.
  if (!_positionCommentPopover(_popoverAnchorMark)) _clampCommentPopoverIntoViewport();
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
  // Content that grows AFTER the dialog was positioned (the reviewer drags the textarea's resize
  // handle) would otherwise push the actions row past the bottom edge, where `overflow: hidden`
  // clips it with no way to scroll back - the same class of bug as the missing height cap.
  if (typeof ResizeObserver === "function") {
    try {
      _popoverResizeObs = new ResizeObserver(() => _refitCommentPopover());
      _popoverResizeObs.observe(el);
    } catch (e) { _popoverResizeObs = null; }
  }

  // A click outside the dialog closes it. A pointer click (detail > 0) in the annotated document is
  // also swallowed (capture-phase preventDefault + stopPropagation) so it performs no other action -
  // for example it does not follow a link the highlight sits on. A keyboard-activated click
  // (Enter/Space, detail 0) closes the dialog but is allowed to proceed, so a keyboard user
  // is never blocked from activating an outside control. Clicks inside pass through.
  _popoverDismiss = (e) => {
    if (!commentPopover) return;
    if (_cmhClickIsInPopover(e.target)) return;
    // Mid-edit the dialog stays open (closing it would silently discard the draft) and the click
    // is left alone, so the rest of the page keeps working while the editor is up.
    if (_popoverEditing) return;
    // A click that did not land in the annotated document belongs to whatever it hit - the layer's
    // own chrome (another highlight's hover bubble, an overlay or toast this dialog's own Save
    // raised), one of the layer's editors, or the browser. Swallowing it would make the reviewer's
    // FIRST click there do nothing but close the dialog, so the dialog closes and the click
    // proceeds. `cmhPopoverWouldSwallowClick` resolves the dialog and those editors through the
    // layer's own state, so document content cannot spoof its way out of the swallow.
    if (cmhPopoverWouldSwallowClick(e)) { e.preventDefault(); e.stopPropagation(); }
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
      if (!_cmhClickIsInPopover(e.target)) return;
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
    _popoverArmed = true;
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
  if (!pinned && !_popoverEditing) { closeCommentPopover(); return; }
  // An edit outlives its anchor scrolling away, so re-fit it to the viewport on its own: without
  // this, a viewport shrink mid-edit would keep the stale cap and position and put Save/Cancel back
  // out of reach (issue #825).
  if (!pinned) _clampCommentPopoverIntoViewport();
}
window.addEventListener("scroll", _syncCommentPopoverToAnchor, true);
window.addEventListener("resize", _syncCommentPopoverToAnchor);
