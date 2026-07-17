/* ---------- Selection handling ---------- */
function selectionInRoot() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed) return null;
  const r = sel.getRangeAt(0);
  if (!root.contains(r.commonAncestorContainer)) return null;
  // Ignore whitespace-only selections: they would anchor a highlight to no visible
  // text, producing a phantom comment with an empty quote.
  if (!sel.toString().trim()) return null;
  const anc = r.commonAncestorContainer.nodeType === 1
    ? r.commonAncestorContainer
    : r.commonAncestorContainer.parentElement;
  if (anc && anc.closest(".cm-skip")) return null;
  return { sel, range: r };
}
// Touch / coarse-pointer devices have no separate right-click: a long-press both
// selects text and is the only gesture that opens the browser's native selection
// menu (Copy, Share, Look up...). Hijacking contextmenu there would leave the reader
// unable to copy, so on those devices we let the native menu through and rely on the
// floating "Add comment" popup (raised from the selection/mouseup path) for commenting.
const _coarsePointer = !!(window.matchMedia
  && window.matchMedia("(hover: none), (pointer: coarse)").matches);
function _setMenuMode(mode) {
  const mc = document.getElementById("menuComment");
  const md = document.getElementById("menuDocComment");
  if (mc) mc.hidden = (mode !== "text");
  if (md) md.hidden = (mode !== "document");
}
document.addEventListener("contextmenu", (e) => {
  if (e.target.closest(".cm-skip")) { hideMenu(); return; }
  // Deck with commenting disabled ("off" state): keep the native context menu and do not raise
  // the text/document comment menu. Commenting stays available with the panel merely closed.
  if (document.body.classList.contains("cmh-deck-comments-off")) return;
  if (_coarsePointer) return;
  const got = selectionInRoot();
  if (got) {
    e.preventDefault();
    pendingDiffSel = null;
    pendingRange = got.range.cloneRange();
    pendingQuote = got.sel.toString();
    _setMenuMode("text");
    showMenu(e.clientX, e.clientY);
    return;
  }
  // No selection: offer a document-wide comment on an "empty" right-click inside the
  // document area, but leave the native menu for links, media, form controls, and existing
  // comment anchors so their default actions (open link, comment on a part) still work.
  const t = e.target;
  const inDoc = (root.contains(t) || t === document.body || (t.closest && t.closest(".app")));
  if (!inDoc) { hideMenu(); return; }
  if (t.closest && t.closest("a[href], img, canvas, svg, button, input, textarea, select, [data-cm-part], mark.cm-hl")) { hideMenu(); return; }
  e.preventDefault();
  pendingRange = null; pendingQuote = ""; pendingDiffSel = null;
  _setMenuMode("document");
  showMenu(e.clientX, e.clientY);
});
document.addEventListener("mouseup", (e) => {
  // A right-button release, or a macOS Ctrl-click (a primary-button release with the Control
  // key held, which the platform turns into a contextmenu gesture), belongs to the contextmenu
  // flow that opens the doc-comment or text menu. Running the selection cleanup below on it
  // would queue a hideMenu() that clobbers the just-opened menu, so the menu flickers open then
  // vanishes. Plain left/middle button releases still drive the text-selection popup.
  if (e.button === 2 || e.ctrlKey) return;
  // A release inside the add-comment menu itself (clicking the Add Comment pill) is the
  // menu's own click that opens the composer, not a new selection gesture; reprocessing it
  // would re-show the menu on top of the just-opened composer.
  if (menu && menu.contains && menu.contains(e.target)) return;
  // A release over a cm-skip element (a tall chart canvas below its caption, the Add-Comment
  // pill itself) must NOT bail before the selection is checked: the pointer often lifts over
  // that neighbour while a valid content selection still stands. Remember it so the no-selection
  // cleanup below can skip clobbering an open menu when the release landed on chrome.
  const onSkip = !!(e.target.closest && e.target.closest(".cm-skip"));
  // Deck with commenting disabled: no text-selection comment popup.
  if (document.body.classList.contains("cmh-deck-comments-off")) return;
  setTimeout(() => {
    const got = selectionInRoot();
    if (!got) {
      // A collapsed or whitespace-only selection: drop any menu/pending state left
      // over from a prior selection so "Add comment" cannot fire on stale text - but only
      // when the release was not on cm-skip chrome, so clicking the Add-Comment pill does
      // not tear down the menu it belongs to.
      if (!onSkip) {
        hideMenu();
        pendingRange = null;
        pendingQuote = "";
      }
      return;
    }
    pendingDiffSel = null;
    pendingRange = got.range.cloneRange();
    pendingQuote = got.sel.toString();
    _setMenuMode("text");
    showMenuForRange(got.range);
  }, 0);
});
// Touch / coarse-pointer selection path. On phones a selection is made by dragging the
// native selection handles, which never fires `mouseup`, so the desktop popup path above
// never runs and touch users only get the native long-press menu. A debounced
// `selectionchange` raises the SAME "Add comment" popup once the selection settles, and
// hides it when the selection collapses. Gated to coarse pointers so desktop mouse
// behavior (the mouseup path) is untouched.
if (_coarsePointer) {
  let _touchSelTimer = null;
  const raiseTouchSelectionMenu = () => {
    if (document.body.classList.contains("cmh-deck-comments-off")) { hideMenu(); return; }
    const got = selectionInRoot();
    if (!got) { hideMenu(); pendingRange = null; pendingQuote = ""; return; }
    pendingDiffSel = null;
    pendingRange = got.range.cloneRange();
    pendingQuote = got.sel.toString();
    _setMenuMode("text");
    showMenuForRange(got.range);
  };
  document.addEventListener("selectionchange", () => {
    const sel = window.getSelection();
    // A collapsed selection dismisses the popup immediately (no debounce) so a tap that
    // clears the selection hides it at once.
    if (!sel || sel.isCollapsed) {
      if (_touchSelTimer) { clearTimeout(_touchSelTimer); _touchSelTimer = null; }
      hideMenu();
      pendingRange = null;
      pendingQuote = "";
      return;
    }
    // Debounce so the popup fires after the user finishes dragging the handles, not on
    // every intermediate change.
    if (_touchSelTimer) clearTimeout(_touchSelTimer);
    _touchSelTimer = setTimeout(raiseTouchSelectionMenu, 400);
  });
}
document.addEventListener("click", (e) => {
  if (menu.hidden) return;
  if (!menu.contains(e.target)) hideMenu();
});
document.addEventListener("keydown", (e) => {
  if (e.isComposing) return;
  if (e.key === "Escape") {
    // Priority: an open toolbar overflow menu closes first and consumes the key,
    // so Escape does not also discard an open composer.
    const tmenu = document.getElementById("toolbarMenu");
    if (tmenu && !tmenu.hidden) {
      tmenu.hidden = true;
      const tbtn = document.getElementById("btnToolbarMenu");
      if (tbtn) { tbtn.setAttribute("aria-expanded", "false"); tbtn.focus(); }
      return;
    }
    // An open add-comment selection menu closes first and consumes Escape, so the key
    // does not also discard an open composer draft behind it.
    if (menu && !menu.hidden) { hideMenu(); return; }
    hideMenu();
    let target = (lastFocusedComposer && openComposers.has(lastFocusedComposer)) ? lastFocusedComposer : null;
    if (!target && openComposers.size) target = [...openComposers].pop();
    if (target) closeComposerElement(target);
  }
});
function showMenu(x, y) {
  menu.hidden = false;
  // Measure the menu's real footprint (the single "Add Comment" pill) rather than
  // a hardcoded size, so the clamp keeps it snug to the selection near viewport edges.
  const w = menu.offsetWidth || 120;
  const h = menu.offsetHeight || 32;
  menu.style.left = Math.max(8, Math.min(x, window.innerWidth - w - 8)) + "px";
  menu.style.top  = Math.max(8, Math.min(y, window.innerHeight - h - 8)) + "px";
}
function showMenuForRange(range) {
  const rects = range.getClientRects();
  const last = rects.length ? rects[rects.length - 1] : range.getBoundingClientRect();
  const x = last.right;
  const y = last.bottom + 6;
  showMenu(x, y);
}
function hideMenu() { menu.hidden = true; }
document.getElementById("menuComment").addEventListener("click", () => {
  hideMenu();
  // Diff sub-line selection: comment the selected region of a line; the same
  // region re-opens its existing comment, a different region makes a new one.
  if (pendingDiffSel) {
    const d = pendingDiffSel;
    pendingDiffSel = null;
    const existing = comments.find(c => c.anchorType === "diff" && c.diffIndex === d.diffIndex
      && c.lineKey === d.lineKey && c.subStart === d.subStart && c.subEnd === d.subEnd);
    if (existing) { openComposerForEdit(existing); return; }
    // A partial overlap with another region on the same line would nest the marks;
    // reject it (like the text layer rejects overlapping selections). An exact
    // match re-opens (above); a fully-disjoint region makes a new comment.
    const overlaps = comments.some(c => c.anchorType === "diff" && c.diffIndex === d.diffIndex
      && c.lineKey === d.lineKey && c.subStart != null && c.subEnd != null
      && c.subStart < d.subEnd && d.subStart < c.subEnd);
    if (overlaps) {
      showToast("That region overlaps an existing comment. Pick a non-overlapping region, or select the exact same region to edit it.");
      return;
    }
    createComposerElement({ mode: "new-diff", diff: d });
    return;
  }
  if (!pendingRange) return;
  // If this exact selection already has a text comment, re-open it for editing
  // instead of stacking a duplicate. A different range (even overlapping) still
  // makes a new comment.
  const s = offsetWithin(pendingRange.startContainer, pendingRange.startOffset);
  const e = offsetWithin(pendingRange.endContainer, pendingRange.endOffset);
  if (s >= 0 && e > s) {
    const existing = comments.find(c => !c.anchorType && c.start === s && c.end === e);
    if (existing) { openComposerForEdit(existing); return; }
  }
  openComposer(pendingRange, pendingQuote);
});
const _menuDocBtn = document.getElementById("menuDocComment");
if (_menuDocBtn) _menuDocBtn.addEventListener("click", () => { hideMenu(); openDocumentComposer(); });

