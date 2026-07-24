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
let pendingSlideId = null;
// The element that had focus when the context menu opened, so Escape can hand focus
// back to it (a keyboard reviewer is not stranded on the dismissed menu).
let _menuReturnFocus = null;
// The pending deferred cleanup a left/middle mouseup schedules to tear down a stale menu when a
// click collapses a selection. It is cancelled the instant a menu is (re)opened (showMenu), so a
// right-click that raises the comment menu right after an empty-space advance click is not
// clobbered by that click's still-pending cleanup (CMH-DECK-31 makes empty-space clicks routine).
let _mouseupCleanupTimer = null;
function _menuItems() {
  return menu ? [...menu.querySelectorAll("button:not([hidden])")] : [];
}
function _restoreMenuFocus() {
  const rf = _menuReturnFocus;
  _menuReturnFocus = null;
  if (rf && document.contains(rf)) { try { rf.focus({ preventScroll: true }); } catch (_e) { /* ignore */ } }
}
function _setMenuMode(mode) {
  const mc = document.getElementById("menuComment");
  const ms = document.getElementById("menuSlideComment");
  const md = document.getElementById("menuDocComment");
  // In a deck, an empty right-click offers BOTH a slide-scoped comment and a deck-wide comment;
  // a flat document offers only the single document-wide comment.
  const deckDoc = (mode === "document") && IS_DECK;
  if (mc) mc.hidden = (mode !== "text");
  if (ms) ms.hidden = !deckDoc;
  if (md) {
    md.hidden = (mode !== "document");
    md.textContent = IS_DECK ? "Comment on deck" : "Comment on document";
  }
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
  // In a deck, remember which slide the empty right-click landed on so a slide-scoped comment
  // ties to it; fall back to the active slide when the click was on the stage margin.
  if (IS_DECK) {
    const slideEl = t.closest && t.closest(".slide");
    pendingSlideId = slideEl ? slideEl.getAttribute("data-slide-id")
      : (window.__cmhDeck ? window.__cmhDeck.activeSlideId() : null);
  } else {
    pendingSlideId = null;
  }
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
  if (_mouseupCleanupTimer) clearTimeout(_mouseupCleanupTimer);
  _mouseupCleanupTimer = setTimeout(() => {
    _mouseupCleanupTimer = null;
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
const cmhEscapePopupStack = [];
window.__cmhRegisterEscapePopup = function (popup) {
  if (!popup || typeof popup.isOpen !== "function" || typeof popup.close !== "function") return function () {};
  cmhEscapePopupStack.push(popup);
  return function () {
    const i = cmhEscapePopupStack.indexOf(popup);
    if (i >= 0) cmhEscapePopupStack.splice(i, 1);
  };
};
window.__cmhPrioritizeEscapePopup = function (popup) {
  const i = cmhEscapePopupStack.indexOf(popup);
  if (i >= 0) {
    cmhEscapePopupStack.splice(i, 1);
    cmhEscapePopupStack.push(popup);
  }
};
function cmhClosePriorityPopup() {
  for (let i = cmhEscapePopupStack.length - 1; i >= 0; i--) {
    const popup = cmhEscapePopupStack[i];
    if (popup && popup.isOpen()) {
      popup.close(true);
      return true;
    }
  }
  return false;
}
document.addEventListener("keydown", (e) => {
  if (e.isComposing) return;
  if (e.key === "Escape") {
    // Priority: an open toolbar/sidebar popup closes first and consumes Escape,
    // so the key does not also discard an open composer draft behind it.
    if (cmhClosePriorityPopup()) {
      e.preventDefault();
      return;
    }
    // An open add-comment selection menu closes first and consumes Escape, so the key
    // does not also discard an open composer draft behind it. Closing it restores focus
    // to whatever the reviewer was on when the menu opened.
    if (menu && !menu.hidden) { hideMenu(); _restoreMenuFocus(); return; }
    hideMenu();
    let target = (lastFocusedComposer && openComposers.has(lastFocusedComposer)) ? lastFocusedComposer : null;
    if (!target && openComposers.size) target = [...openComposers].pop();
    if (target) closeComposerElement(target);
  }
});
function showMenu(x, y) {
  // A pending mouseup cleanup (scheduled by a preceding empty-space click that collapsed a
  // selection) would tear this menu down the instant it opens; opening the menu supersedes that
  // cleanup, so cancel it. This keeps a right-click comment menu on non-interactive slide text
  // from being clobbered by the empty-space advance click that came just before it (CMH-DECK-31).
  if (_mouseupCleanupTimer) { clearTimeout(_mouseupCleanupTimer); _mouseupCleanupTimer = null; }
  // Remember where focus was so Escape can return it (but not the menu itself or the body).
  const rf = document.activeElement;
  _menuReturnFocus = (rf && rf !== document.body && menu && !menu.contains(rf)) ? rf : null;
  menu.hidden = false;
  // Keep the selection menu above any open composer (composers raise their z-index as they are
  // focused), so a reviewer can always start another comment on a fresh selection.
  menu.style.zIndex = composerZ + 1;
  // Measure the menu's real footprint (the single "Add Comment" pill) rather than
  // a hardcoded size, so the clamp keeps it snug to the selection near viewport edges.
  const w = menu.offsetWidth || 120;
  const h = menu.offsetHeight || 32;
  menu.style.left = Math.max(8, Math.min(x, window.innerWidth - w - 8)) + "px";
  menu.style.top  = Math.max(8, Math.min(y, window.innerHeight - h - 8)) + "px";
  // Move focus to the first visible menuitem so a keyboard-only reviewer lands on the
  // primary action and can rove with the Arrow keys.
  const first = _menuItems()[0];
  if (first) { try { first.focus({ preventScroll: true }); } catch (_e) { /* ignore */ } }
}
// Arrow keys rove focus among the visible menuitems (wrapping), matching the ARIA menu pattern.
if (menu) {
  menu.addEventListener("keydown", (e) => {
    // Tab (forward or Shift+Tab) leaves the menu: close it and clear the saved opener so a later
    // Escape cannot surprise-restore, then let the browser move focus naturally (no preventDefault),
    // so focus lands on the correct next/previous control. This mirrors the ARIA deck mode menu
    // (95-startup.js) and covers the edge case the focusout backstop cannot: when Tab moves focus
    // to browser chrome, focusout's relatedTarget is null and its null-guard would keep the menu
    // open, leaving a stale opener a later Escape could yank focus back to.
    if (e.key === "Tab") { _menuReturnFocus = null; hideMenu(); return; }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Home" && e.key !== "End") return;
    const items = _menuItems();
    if (!items.length) return;
    e.preventDefault();
    const cur = items.indexOf(document.activeElement);
    let next;
    if (e.key === "Home") next = 0;
    else if (e.key === "End") next = items.length - 1;
    else if (e.key === "ArrowDown") next = cur < 0 ? 0 : (cur + 1) % items.length;
    else next = cur < 0 ? items.length - 1 : (cur - 1 + items.length) % items.length;
    items[next].focus({ preventScroll: true });
  });
  // Dismiss when focus moves to another element OUTSIDE the menu (Tab out, or focusing a control
  // elsewhere). The items carry tabindex="-1", so Tab is never captured to rove between them - it
  // moves focus to the next page control and this handler closes the menu, leaving no stale-open
  // menu behind. Focus has already landed where the user sent it, so this path does NOT restore
  // focus (and clears the saved opener) - a later Escape can no longer surprise-restore. A null
  // relatedTarget (a transient/window blur, or Escape's own hide blurring the item to <body>) is
  // ignored so the menu is not torn down by focus merely being lost to nothing; a click on empty,
  // non-focusable space is still dismissed by the document click handler. Escape's own path closes
  // and restores focus to the opener explicitly.
  menu.addEventListener("focusout", (e) => {
    if (menu.hidden) return;
    const to = e.relatedTarget;
    if (!to || menu.contains(to)) return; // no real outside target, or roving between items
    _menuReturnFocus = null;
    hideMenu();
  });
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
  // If this exact selection already has a text comment, re-open it for editing instead of
  // stacking a duplicate. A disjoint range opens a new composer; an overlapping range also opens
  // one but is rejected when saved (CMH-CORE-11), so no nested mark.cm-hl is ever created.
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
const _menuSlideBtn = document.getElementById("menuSlideComment");
if (_menuSlideBtn) _menuSlideBtn.addEventListener("click", () => { hideMenu(); openSlideComposer(pendingSlideId); });
