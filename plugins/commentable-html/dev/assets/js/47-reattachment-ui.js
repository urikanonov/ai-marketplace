/* ---------- Explicit reattachment of a Detached text thread ---------- */
let _cmhReattachId = null;
let _cmhReattachPrompt = null;
let _cmhReattachOpener = null;
function cmhPendingReattachment() { return _cmhReattachId; }
function cmhCancelReattachment(restoreFocus) {
  const opener = _cmhReattachOpener;
  _cmhReattachId = null;
  _cmhReattachOpener = null;
  if (_cmhReattachPrompt) _cmhReattachPrompt.remove();
  _cmhReattachPrompt = null;
  hideMenu();
  const button = cmhEl("menuComment");
  if (button) button.textContent = "Add Comment";
  if (restoreFocus && opener && opener.isConnected) {
    try { opener.focus({ preventScroll: true }); } catch (e) { opener.focus(); }
  }
}
function cmhBeginReattachment(c, opener) {
  if (!c || !cmhIsTextAnchor(c) || !cmhIsDetached(c) || _cmhFocusBlockedByModal()) return;
  cmhCancelReattachment(false);
  _cmhReattachId = c.id;
  _cmhReattachOpener = opener;
  const box = document.createElement("div");
  box.className = "cm-reattach-prompt cm-skip";
  box.setAttribute("role", "status");
  box.setAttribute("aria-live", "polite");
  const message = document.createElement("span");
  message.textContent = "Reattaching a Detached comment. Select its new text, then choose Attach comment.";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.textContent = "Cancel";
  cancel.setAttribute("aria-label", "Cancel reattachment");
  cancel.addEventListener("click", () => cmhCancelReattachment(true));
  box.append(message, cancel);
  document.body.appendChild(box);
  _cmhReattachPrompt = box;
  window.__cmhPrioritizeEscapePopup(_cmhReattachPopup);
}
function cmhFinishReattachment(range) {
  if (_cmhFocusBlockedByModal()) return;
  const c = comments.find(item => item.id === _cmhReattachId);
  if (!c || !cmhIsTextAnchor(c) || !cmhIsDetached(c)) {
    cmhCancelReattachment(false);
    return;
  }
  const start = offsetWithin(range.startContainer, range.startOffset);
  const end = offsetWithin(range.endContainer, range.endOffset);
  const resolved = start >= 0 && end > start && rangeFromOffsets(start, end);
  if (!resolved || !resolved.toString().trim() || rangeOverlapsHighlight(start, end)) {
    showToast("Could not attach that selection. Choose non-overlapping commentable text.", { alert: true });
    return;
  }
  // Wrap before changing the comment: a failed DOM operation must not destroy its recovery data.
  try { wrapRangeWithMark(resolved, c.id); }
  catch (e) {
    unwrapMarks(c.id);
    showToast("Could not attach that selection. The Detached comment is unchanged.", { alert: true });
    return;
  }
  const previous = Object.assign({}, c);
  try {
    if (c.cmAnchor && !cmhAnchorMetadataValid(c.cmAnchor)) {
      c.cmAnchor = { v: 1, original: c.cmAnchor.original || cmhAnchorOriginal(c),
        previousSelector: c.cmAnchor };
    }
    c.start = start;
    c.end = end;
    c.quote = rangeFromOffsets(start, end).toString();
    Object.assign(c, captureContext(start, end, rangeFromOffsets(start, end)));
    c.detached = false;
    if (!cmhCaptureTextAnchor(c)) throw new Error("Unsupported or over-budget attachment evidence");
  } catch (e) {
    unwrapMarks(c.id);
    Object.keys(c).forEach(key => { delete c[key]; });
    Object.assign(c, previous);
    showToast("Could not attach that selection. The Detached comment is unchanged.", { alert: true });
    return;
  }
  const saved = saveComments();
  cmhCancelReattachment(false);
  window.getSelection().removeAllRanges();
  renderComments();
  const card = listEl.querySelector('.cm-card[data-cid="' + c.id + '"]');
  const jump = card && card.querySelector('[data-act="jump"]');
  if (jump) { try { jump.focus({ preventScroll: true }); } catch (e) { jump.focus(); } }
  if (saved) showToast("Comment reattached.");
  else showToast("Comment reattached in this session but NOT saved to this browser. Export as Shareable to keep it.",
    { alert: true, duration: 8000, action: cmhStorageAction(CMH_STORE_KEY) });
}
const _cmhReattachPopup = {
  isOpen: () => !!_cmhReattachId,
  close: () => cmhCancelReattachment(true),
};
window.__cmhRegisterEscapePopup(_cmhReattachPopup);
