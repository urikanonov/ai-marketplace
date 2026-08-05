/* ---------- Sidebar rendering ---------- */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
function formatTime(iso) {
  try {
    // A date-only value (YYYY-MM-DD, e.g. a data-generated build/authoring date) is a CALENDAR
    // date, not an instant: parse it in LOCAL time and render it without a time, so it shows the
    // same day in every timezone. new Date("2026-07-25") parses as UTC midnight, which slides to
    // the previous evening for viewers west of UTC (the "Jul 24 ... 17:00" artifact), so a bare
    // date must not go through the datetime path below.
    const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso).trim());
    if (dateOnly) {
      const d = new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]));
      return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
    }
    // Month name (not a number) so the date is unambiguous across M/D/Y and D/M/Y
    // locales (e.g. "Jul 9, 2026, 13:07"). 24-hour time, no AM/PM.
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", hour12: false
    });
  }
  catch (e) { return iso; }
}
let commentSort = "pos";
try { commentSort = localStorage.getItem(COMMENT_KEY + "::commentSort") || "pos"; } catch (e) { /* private mode */ }
function commentTimeValue(c) {
  const t = Date.parse((c && (c.updatedAt || c.createdAt)) || "");
  return isNaN(t) ? 0 : t;
}
// The sidebar shows a "Generated on" / "Last comment" info line. "Generated on" comes
// from a data-generated attribute on #commentRoot when the author set one (deterministic),
// else the file's own last-modified time; "Last comment" is the newest comment timestamp.
function updateSideInfo() {
  const gen = document.getElementById("cmGenerated");
  const last = document.getElementById("cmLastComment");
  if (gen) {
    let g = root.getAttribute("data-generated");
    if (!g) { const lm = Date.parse(document.lastModified); if (!isNaN(lm)) g = new Date(lm).toISOString(); }
    gen.textContent = "Generated on: " + (g ? formatTime(g) : "unknown");
  }
  if (last) {
    if (comments.length) {
      const t = Math.max.apply(null, comments.map(commentTimeValue));
      last.textContent = "Last comment: " + (t ? formatTime(new Date(t).toISOString()) : "-");
    } else {
      last.textContent = "Last comment: none yet";
    }
  }
}
function updateSortUi() {
  const b = document.getElementById("btnSort");
  if (!b) return;
  const state = (commentSort === "time-desc" || commentSort === "time-asc") ? commentSort : "pos";
  const svg = 'viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"'
    + ' fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
  const ICONS = {
    "pos": '<svg class="cm-ui-ico" ' + svg + '><path d="M7 4v16M7 4l-3 3M7 4l3 3M17 20V4M17 20l-3-3M17 20l3-3"/></svg>',
    "time-desc": '<svg class="cm-ui-ico" ' + svg + '><path d="M4 6h11M4 12h7M4 18h4M18 7v10M15 14l3 3 3-3"/></svg>',
    "time-asc": '<svg class="cm-ui-ico" ' + svg + '><path d="M4 6h4M4 12h7M4 18h11M18 17V7M15 10l3-3 3 3"/></svg>',
  };
  const TITLES = {
    "pos": "Sorted by document position. Click to sort newest first.",
    "time-desc": "Sorted newest first. Click to sort oldest first.",
    "time-asc": "Sorted oldest first. Click to return to document order.",
  };
  // This is a 3-state cycle, not a binary toggle, so it exposes state via data-sort + a dynamic
  // aria-label rather than aria-pressed (which screen readers would announce ambiguously).
  b.setAttribute("data-sort", state);
  // Adopt-aware tooltip (mirrors 70-mode-badge.js): once the shared tooltip layer has taken the
  // title into data-cmh-tip it removes title so the native browser tooltip cannot also fire; keep
  // whichever attribute it is using current, and never re-add title after adoption.
  if (b.hasAttribute("data-cmh-tip")) { b.setAttribute("data-cmh-tip", TITLES[state]); b.removeAttribute("title"); }
  else b.setAttribute("title", TITLES[state]);
  const ARIA = { "pos": "document order", "time-desc": "newest first", "time-asc": "oldest first" };
  b.setAttribute("aria-label", "Sort comments (currently: " + ARIA[state] + ")");
  const icon = document.getElementById("cmSortIcon");
  if (icon && ICONS[state]) icon.innerHTML = ICONS[state];
  // If the shared tooltip bubble is currently showing for this button (a keyboard user focuses it,
  // then presses Enter to cycle the state), refresh it in place so it does not describe the old
  // state until focus moves.
  if (window.__cmhRefreshTip) window.__cmhRefreshTip(b);
}
function renderComments() {
  // Test/perf hook: renderComments runs two full-document tree walks, so a spec pins that the
  // note-typing path COALESCES a keystroke burst into a single render rather than one per key
  // (issue #505). Only counts when a test has pre-seeded the counter; production never creates it.
  if (typeof window !== "undefined" && window.__cmhPerf) window.__cmhPerf.renders = (window.__cmhPerf.renders || 0) + 1;
  // The rebuild also destroys whatever LIST CONTROL the reviewer was on, which used to drop them on
  // <body> (issue #897). Note where focus was before anything changes, and hand it back once the
  // list is rebuilt. An editor's own focus is carried by the draft snapshot below, so it is
  // excluded here, and focus outside the list is not this function's business at all.
  const _listFocus = _captureListFocus();
  // An aria-modal dialog (Manage storage, the clear-all confirm, Help) puts the SIDE PANE BEHIND its
  // overlay, so a re-render that lands while one is up must not hand focus to the rebuilt inline
  // editor: that focus escapes the dialog's trap into a control the reviewer can neither see nor
  // reach. Ownership is recorded as false for the whole rebuild while a modal is open, and the tail
  // hands a focus the rebuild ORPHANED back to the dialog instead of leaving it stranded on <body>.
  const _openModal = _cmhOpenModalBox();
  // A full re-render replaces the list DOM, wiping any open inline reply editor. Snapshot an in-progress
  // draft first (a re-render can be triggered by sorting, a note debounce, a checklist change, etc.) and
  // re-open the editor with the same text AND selection once the list is rebuilt, so the draft is
  // preserved instead of dropped.
  let _inlineDraft = null;
  if (_activeInlineEditor) {
    const _del = _activeInlineEditor.el;
    const _dta = _del && _del.querySelector("textarea");
    const _act = document.activeElement;
    // A deferred focus the open path has QUEUED but not yet delivered counts as ownership:
    // openInlineReply hides the Reply button it was launched from (dropping activeElement to
    // <body>) and only then queues _focus(), so a re-render landing in that window would otherwise
    // cancel a focus the reviewer explicitly asked for. It counts only while nothing else holds
    // focus, so a live timer can never outrank the control the reviewer is actually on.
    const _pending = !!(_del && _del.__focusTimer && (!_act || _act === document.body));
    _inlineDraft = {
      kind: _activeInlineEditor.kind, targetId: _activeInlineEditor.targetId,
      value: _dta ? _dta.value : "",
      // The caret/selection is part of the draft: the side pane carries the formatting toolbar, so a
      // re-render that lands between "select a word" and "click Bold" must not collapse the range
      // (that would append bare markers instead of wrapping the word).
      selStart: _dta ? _dta.selectionStart : null, selEnd: _dta ? _dta.selectionEnd : null,
      selDir: _dta ? _dta.selectionDirection : null,
      // Carry the editor's height across the rebuild: a height the reviewer dragged by hand must
      // survive (or an unrelated re-render would quietly snap it back to autogrow), and even an
      // autogrown one is worth restoring, since a rebuilt editor can land in a card the search
      // filter is hiding, where it cannot measure itself.
      height: _dta ? (_dta.style.height || null) : null,
      manual: !!(_dta && cmhAutogrowManualHeight(_dta)),
      // ...but FOCUS is not. A re-render is often triggered from somewhere the reviewer is not
      // looking (a note-typing debounce, a checklist tick, the Sort button), so the re-opened editor
      // is only re-focused when it owned focus beforehand; otherwise the caret would jump out of the
      // control actually being used (issue #844). A modal vetoes ownership outright: the pane is
      // behind its overlay, so no re-render may deliver focus there (issue #884).
      hadFocus: !_openModal && !!(_del && (_del.contains(_act) || _pending)),
      // Which of the editor's own controls held it, so a reviewer parked on the formatting toolbar
      // or Save/Cancel is handed back to THAT control in the rebuilt editor instead of being dropped
      // into the textarea - the same disorienting jump, one control over.
      focusIdx: _editorFocusIndex(_del, _dta, _act),
    };
  }
  _activeInlineEditor = null;
  const roots = (typeof threadRoots === "function") ? threadRoots(comments) : comments;
  const stateChanges = (typeof widgetStateChanges === "function") ? widgetStateChanges() : [];
  const clPieces = (typeof checklistCardPieces === "function") ? checklistCardPieces() : [];
  const notePieces = (typeof notesCardPieces === "function") ? notesCardPieces() : [];
  // The count badge reflects the pending note and checklist changes shown in the panel, not just
  // comment threads: a changed note and a changed checklist each render their own card and are now
  // counted too. Otherwise a reviewer who only edited a note or ticked a checklist saw the count
  // stay at 0, as if nothing had been captured (issue #643). Notes are one card each; a checklist is
  // one card regardless of how many of its items changed. Widget/layout state changes are
  // deliberately NOT counted here - that stays a non-comment signal (see CMH-STATE-01).
  const changeCardCount = notePieces.length + clPieces.length;
  const pendingCount = roots.length + changeCardCount;
  toolbarCount.textContent = pendingCount;
  sidebarCount.textContent = pendingCount;
  // Keep the deck comment-options menu in step with the live comment count (the "Disable
  // commenting" item is only available when the deck has zero comments).
  if (window.__cmhDeck && typeof window.__cmhDeck.refreshMode === "function") window.__cmhDeck.refreshMode();
  if (typeof updateDocTypeUi === "function") updateDocTypeUi();
  updateSideInfo();
  updateSortUi();
  const stateHtml = stateChanges.length ? _renderWidgetStateCard(stateChanges) : "";
  if (!roots.length && !stateChanges.length && !clPieces.length && !notePieces.length) {
    const deckHint = IS_DECK
      ? "<p><strong>On this deck:</strong> in comment mode, select text on the current slide and choose <em>Add Comment</em>, or right-click empty slide space for a whole-slide comment. Move between slides with Prev / Next or the arrow keys.</p>"
      : "";
    listEl.innerHTML = `
      <div class="cm-empty">
        <p><strong>No comments yet.</strong></p>
        ${deckHint}
        <p>Select any text in the document, then right-click and choose <em>Add Comment</em>. Mermaid nodes, diff lines, images, and widget parts: hover (or keyboard-focus) and click <em>Add Comment</em>. Right-click empty space for a document-wide comment. Comments stay here until the agent processes them. Click <kbd>Copy all</kbd> to send the bundle to the clipboard; the agent then marks them handled in this HTML file, and they are pruned automatically on the next reload.</p>
      </div>`;
    if (typeof applyCommentSearch === "function") applyCommentSearch();
    if (typeof refreshReviewUI === "function") refreshReviewUI();
    // With a dialog up the pane is behind its overlay, so the list-focus hand-back must stand down
    // too and the focus goes back to the dialog instead.
    if (_openModal) _keepModalFocus(_openModal);
    else _restoreListFocus(_listFocus);
    return;
  }
  const sortKey = _anchorSortKey;
  const sorted = (commentSort === "time-asc")
    ? [...roots].sort((a, b) => (commentTimeValue(a) - commentTimeValue(b)) || (sortKey(a) - sortKey(b)))
    : (commentSort === "time-desc")
    ? [...roots].sort((a, b) => (commentTimeValue(b) - commentTimeValue(a)) || (sortKey(a) - sortKey(b)))
    : [...roots].sort((a, b) => sortKey(a) - sortKey(b));
  const commentHtml = sorted.map((c, i) => {
    const isMermaid = c.anchorType === "mermaid";
    const isDiff = c.anchorType === "diff";
    const isImage = c.anchorType === "image";
    const isLink = c.anchorType === "link";
    const isWidget = c.anchorType === "widget";
    const isDocument = c.anchorType === "document";
    const isSlide = c.anchorType === "slide";
    const path = (c.headingPath && c.headingPath.length)
      ? c.headingPath.map(h => escapeHtml(h.text)).join(" &rsaquo; ")
      : (c.section ? escapeHtml(c.section) : "");
    const sectionHtml = path ? `<div class="section">in: <strong>${path}</strong></div>` : "";
    let quoteHtml;
    if (isMermaid) {
      quoteHtml = `<div class="quote"><span class="ctx">${c.nodeKey === "__diagram__" ? "mermaid diagram: " : "mermaid node: "}</span><span class="quoted">"${escapeHtml(c.nodeLabel || c.nodeKey || "")}"</span></div>`;
    } else if (isImage) {
      const mediaLbl = c.imageKind === "chart" ? "chart: " : "image: ";
      quoteHtml = `<div class="quote"><span class="ctx">${mediaLbl}</span><span class="quoted">${escapeHtml(c.imageAlt || c.quote || c.imageSrc || "")}</span></div>`;
    } else if (isLink) {
      quoteHtml = `<div class="quote"><span class="ctx">link: </span><span class="quoted">${escapeHtml(c.linkText || c.quote || c.linkHref || "")}</span></div>`;
    } else if (isWidget) {
      quoteHtml = `<div class="quote"><span class="ctx">${escapeHtml(c.widget || "widget")}: </span><span class="quoted">"${escapeHtml(c.partLabel || c.part || "")}"</span></div>`;
    } else if (isDocument) {
      quoteHtml = `<div class="quote"><span class="quoted">(document-wide comment)</span></div>`;
    } else if (isSlide) {
      quoteHtml = `<div class="quote"><span class="ctx">slide: </span><span class="quoted">"${escapeHtml(c.slideTitle || c.slideId || "")}"</span></div>`;
    } else if (c.isCode) {
      // Code-block quotes are rendered as a single preformatted block (no before/after
      // ctx) because surrounding code lines look misleading when collapsed to one line.
      quoteHtml = `<div class="quote cm-quote-code">${escapeHtml(c.quote)}</div>`;
    } else if (c.before || c.after) {
      quoteHtml = `<div class="quote"><span class="ctx">${escapeHtml(c.before || "")}</span><span class="quoted">"${escapeHtml(c.quote)}"</span><span class="ctx">${escapeHtml(c.after || "")}</span></div>`;
    } else {
      quoteHtml = `<div class="quote"><span class="quoted">"${escapeHtml(c.quote)}"</span></div>`;
    }
    const pinBits = [];
    if (isMermaid) {
      pinBits.push(`mermaid diagram ${(Number(c.diagramIndex) || 0) + 1}`);
      if (c.nodeKey && c.nodeKey !== "__diagram__") pinBits.push(`node ${escapeHtml(c.nodeKey)}`);
      else pinBits.push("whole diagram");
    } else if (isDiff) {
      pinBits.push(`diff${c.diffLabel ? " " + escapeHtml(c.diffLabel) : ""}`);
      pinBits.push(escapeHtml(diffLineLocator(c)));
    } else if (isImage) {
      pinBits.push(`${c.imageKind === "chart" ? "chart" : "image"} ${(Number(c.imageIndex) || 0) + 1}`);
      const src = String(c.imageSrc == null ? "" : c.imageSrc);
      if (src) pinBits.push(escapeHtml(src.length > 60 ? src.slice(0, 57) + "..." : src));
    } else if (isLink) {
      pinBits.push(`link ${(Number(c.linkIndex) || 0) + 1}`);
      const href = String(c.linkHref == null ? "" : c.linkHref);
      if (href) pinBits.push(escapeHtml(href.length > 60 ? href.slice(0, 57) + "..." : href));
    } else if (isWidget) {
      pinBits.push(`widget "${escapeHtml(c.widget || "")}"`);
      pinBits.push(`part "${escapeHtml(c.partLabel || c.part || "")}"`);
    } else if (isDocument) {
      pinBits.push("document-wide");
    } else if (isSlide) {
      pinBits.push(`slide "${escapeHtml(c.slideTitle || c.slideId || "")}"`);
    } else {
      if (c.isCode) {
        pinBits.push(c.codeLanguage ? `code (${escapeHtml(c.codeLanguage)})` : "code block");
      }
      // The prose pinpoint ("in <li> - match 2 of 4") is internal grep-help for the
      // agent; it is still emitted in the Copy bundle's Pinpoint line but is not shown
      // on the sidebar card, which only surfaces reader-facing anchor info.
    }
    const pinHtml = pinBits.length ? `<div class="pin">${pinBits.join(" - ")}</div>` : "";
    const jumpTarget = isMermaid ? "node" : isDiff ? "diff line" : isImage ? (c.imageKind === "chart" ? "chart" : "image") : isLink ? "link" : isWidget ? "element" : isSlide ? "slide" : "text";
    const cardClass = isDocument ? "cm-card cm-card-doc" : isSlide ? "cm-card cm-card-doc cm-card-slide" : "cm-card";
    // Slide comments have no text highlight but DO navigate to their owning slide, so they keep a
    // jump button (unlike deck-wide/document comments, which have nowhere specific to jump).
    const jumpBtn = isDocument ? "" : isSlide
      ? `<button type="button" data-act="jump" title="Go to this slide">jump</button>`
      : `<button type="button" data-act="jump" title="Scroll to highlighted ${jumpTarget}">jump</button>`;
    const rootPill = (typeof authorPillHtml === "function") ? authorPillHtml(c.author) : "";
    const replies = (typeof repliesOf === "function") ? repliesOf(c.id, comments) : [];
    const delTitle = replies.length ? "Delete this comment and its replies" : "Delete this comment";
    const repliesHtml = replies.map((r) => {
      const rp = (typeof authorPillHtml === "function") ? authorPillHtml(r.author) : "";
      return `
      <div class="cm-entry cm-reply" data-reply-cid="${r.id}">
        <div class="note cmh-rich">${rp}${renderRichNote(r.note)}</div>
        <div class="cmh-note-raw" hidden>${escapeHtml(r.note == null ? "" : r.note)}</div>
        <div class="meta">
          <span><bdi>${escapeHtml(formatTime(r.updatedAt || r.createdAt))}</bdi>${r.updatedAt ? " (edited)" : ""}</span>
          <span class="acts">
            <button type="button" data-act="reply-edit" title="Edit reply">edit</button>
            <button type="button" class="del" data-act="reply-del" title="Delete reply">delete</button>
          </span>
        </div>
      </div>`;
    }).join("");
    return `
    <article class="${cardClass}" data-cid="${c.id}">
      ${sectionHtml}
      ${quoteHtml}
      ${pinHtml}
      <div class="cm-entry cm-entry-root">
        <div class="note cmh-rich">${rootPill}${renderRichNote(c.note)}</div>
        <div class="cmh-note-raw" hidden>${escapeHtml(c.note == null ? "" : c.note)}</div>
        <div class="meta">
          <span>#${i + 1} - <bdi>${escapeHtml(formatTime(c.updatedAt || c.createdAt))}</bdi>${c.updatedAt ? " (edited)" : ""}</span>
          <span class="acts">
            ${jumpBtn}
            <button type="button" data-act="edit" title="Edit comment">edit</button>
            <button type="button" class="del" data-act="del" title="${delTitle}">delete</button>
          </span>
        </div>
      </div>
      ${repliesHtml ? `<div class="cm-replies">${repliesHtml}</div>` : ""}
      <div class="cm-reply-row"><button type="button" class="cm-reply-btn" data-act="reply" title="Reply to this comment">Reply</button></div>
    </article>`;
  });
  const commentPieces = commentHtml.map((html, i) => ({ pos: sortKey(sorted[i]), html }));
  // Insert each checklist and note change card by document position while preserving the
  // comments' current (position or time) sort order, so a time sort is not overridden and no
  // card is dropped.
  const cls = clPieces.concat(notePieces).sort((a, b) => a.pos - b.pos);
  const parts = [];
  let ci = 0;
  commentPieces.forEach((cp) => {
    while (ci < cls.length && cls[ci].pos <= cp.pos) parts.push(cls[ci++].html);
    parts.push(cp.html);
  });
  while (ci < cls.length) parts.push(cls[ci++].html);
  listEl.innerHTML = stateHtml + parts.join("");
  if (typeof applyCommentSearch === "function") applyCommentSearch();
  if (typeof refreshReviewUI === "function") refreshReviewUI();
  if (_inlineDraft) _reopenInlineDraft(_inlineDraft);
  if (_openModal) _keepModalFocus(_openModal);
  else _restoreListFocus(_listFocus);
}
// The topmost open modal dialog, or null. Only a real focus-trapping overlay counts: the deck
// overview marks itself aria-modal="false", and the composer/in-document dialog are not modal at
// all, so neither may suppress the side pane's focus handling. A DOM query rather than a state flag
// on purpose: only the storage manager keeps such a flag, while the clear-all confirm and the Help
// panel build their own aria-modal overlays with none, so a flag-based check would miss them (and
// every modal added later). It costs one selector match against the 0-1 aria-modal nodes in the
// document, next to the two full-document tree walks renderComments already runs.
function _cmhOpenModalBox() {
  const boxes = document.querySelectorAll('.cm-modal-overlay [aria-modal="true"]');
  return boxes.length ? boxes[boxes.length - 1] : null;
}
// Whether the side pane may take focus at all right now. With an aria-modal dialog up, the pane is
// behind its overlay, so EVERY path that would focus something in it has to stand down - not just
// the re-render's own restore, or the next Save/Cancel would hand the caret straight back.
function _cmhFocusBlockedByModal() {
  return !!_cmhOpenModalBox();
}
// The surfaces the overlay demonstrably COVERS: the side pane and the document. Focus found in one
// of them while a dialog is up is focus the reviewer can neither see nor reach, so it is reclaimed.
// Focus anywhere else is left alone on purpose - the deck's own chrome and a toast paint ABOVE the
// overlay, so pulling focus off one of those would be the very yank this guard exists to prevent.
function _cmhBehindOverlay(a) {
  if (!a || a === document.body || a === document.documentElement) return true;
  return !!(a.closest && a.closest(".cm-sidebar, #commentRoot"));
}
// Focus that is behind the open dialog belongs back in it. Rebuilding the list can destroy whatever
// held focus (the inline editor, a card button), dropping activeElement to <body>, and a delete run
// FROM the dialog can first restore focus to a composer's opener out in the document - either way
// the dialog's Tab trap is silently broken while a reviewer sees a modal.
function _keepModalFocus(modal) {
  // The snapshot was taken before the rebuild, which can outlive the dialog it named.
  if (modal && !modal.isConnected) modal = _cmhOpenModalBox();
  if (!modal) return;
  const a = document.activeElement;
  if (modal.contains(a) || !_cmhBehindOverlay(a)) return;
  // Prefer the dialog's own declared safe default (showConfirm marks Cancel `.cm-modal-default` so
  // Enter cannot confirm a destructive action) over raw DOM order, which would hand back the danger
  // button that precedes it. focus() is SILENT when its target cannot take focus (hidden, disabled,
  // inert), so each candidate is tried until one actually lands rather than stranding focus again;
  // the dialogs whose first focusable IS their on-open target need no marker.
  const marked = modal.querySelector(".cm-modal-default, [autofocus]");
  const rest = modal.querySelectorAll('button, [href], input, select, textarea, summary, [contenteditable="true"], [tabindex]:not([tabindex="-1"])');
  const candidates = marked ? [marked].concat(Array.prototype.slice.call(rest)) : Array.prototype.slice.call(rest);
  for (let i = 0; i < candidates.length; i++) {
    const c = candidates[i];
    try { c.focus({ preventScroll: true }); } catch (e) { try { c.focus(); } catch (e2) {} }
    if (document.activeElement === c) return;
  }
  // Last resort: park focus on the dialog itself rather than leave it stranded outside the trap.
  if (!modal.hasAttribute("tabindex")) modal.setAttribute("tabindex", "-1");
  try { modal.focus({ preventScroll: true }); } catch (e) { try { modal.focus(); } catch (e2) {} }
}
// Re-open an inline reply/edit editor after a re-render and restore the reviewer's in-progress text
// AND selection, so a re-render (sort, note debounce, ...) never silently drops a draft or collapses
// the range the formatting toolbar is about to wrap. Focus follows the snapshot: it is only handed
// back to the editor that already had it, never stolen from wherever the reviewer actually is.
function _reopenInlineDraft(snap) {
  if (snap.kind === "reply") {
    const card = listEl.querySelector('.cm-card[data-cid="' + snap.targetId + '"]');
    if (card) openInlineReply(card, snap.targetId);
  } else if (snap.kind === "edit") {
    const entry = listEl.querySelector('[data-reply-cid="' + snap.targetId + '"]');
    if (entry) openInlineNoteEdit(entry, snap.targetId);
  } else if (snap.kind === "edit-root") {
    const entry = listEl.querySelector('.cm-card[data-cid="' + snap.targetId + '"] .cm-entry-root');
    if (entry) openInlineNoteEdit(entry, snap.targetId);
  }
  if (_activeInlineEditor && _activeInlineEditor.el) {
    const el = _activeInlineEditor.el;
    const ta = el.querySelector("textarea");
    let r = null;
    if (ta) {
      ta.value = snap.value;
      if (snap.height) {
        ta.style.height = snap.height;
        // A hand-dragged height latches as manual; an autogrown one is only a starting point, so
        // record it as this layer's own so the manual detector is not fooled by it.
        if (snap.manual) ta._cmhAutogrowManual = true;
        else { ta._cmhAutogrowH = ta.style.height; cmhAutogrowResize(ta); }
      } else cmhAutogrowResize(ta);
      r = _clampSelRange(snap, ta.value.length);
      // Set the range synchronously as well as through the deferred focus below: a toolbar click that
      // lands before the timer runs reads the selection straight off the textarea. setSelectionRange
      // does not move focus, so this half of the restore is safe even for an unfocused editor.
      try { ta.setSelectionRange(r[0], r[1], snap.selDir || "none"); }
      catch (e) { try { ta.setSelectionRange(r[0], r[1]); } catch (e2) {} }
    }
    if (!snap.hadFocus) {
      // The reviewer was working elsewhere when the re-render fired, so drop the focus the open
      // path queued rather than pulling the caret into the sidebar (issue #844).
      _cancelEditorFocus(el);
      return;
    }
    const controls = (snap.focusIdx >= 0) ? el.querySelectorAll(_EDITOR_FOCUSABLE) : null;
    const back = (controls && snap.focusIdx < controls.length && controls[snap.focusIdx] !== ta)
      ? controls[snap.focusIdx] : null;
    if (back) {
      // Focus was on a toolbar or Save/Cancel control, whose element the re-render destroyed: hand
      // it back to the rebuilt equivalent instead of jumping the caret into the text. preventScroll
      // for the same reason _focusInList uses it - refocusing a rebuilt panel control must never
      // scroll the document out from under the reader.
      _cancelEditorFocus(el);
      try { back.focus({ preventScroll: true }); } catch (e) { try { back.focus(); } catch (e2) {} }
    }
    // focus() is SILENT when its target cannot take focus (hidden, disabled, inert), which would
    // strand the reviewer on <body> - worse than the bug being fixed - so the textarea is the
    // fallback whenever the hand-back did not land, as well as the normal path for the textarea
    // itself. openInlineReply/openInlineNoteEdit already queued a deferred focus that would put the
    // caret at the end; re-arm it with the restored range (_focus cancels its pending timer, so the
    // restore replaces that one rather than racing it).
    if (!el.contains(document.activeElement) && el._focus) {
      el._focus(r ? r[0] : null, r ? r[1] : null, snap.selDir);
    }
  }
}
// The editor's own focusable controls, in DOM order. The rebuilt editor is assembled by the same
// builder and is therefore structurally identical, so an INDEX into this list survives a re-render -
// and, unlike an allow-list of known selectors, it keeps handing focus back correctly when a control
// is added to _buildInlineReplyEditor later.
const _EDITOR_FOCUSABLE = "button, textarea, input, select, [tabindex]";
// Where the focused control sits in that list. The textarea (and "focus is not in this editor")
// report -1, since the textarea's restore carries the caret range instead.
function _editorFocusIndex(el, ta, a) {
  if (!el || !a || a === el || a === ta || !el.contains(a)) return -1;
  return Array.prototype.indexOf.call(el.querySelectorAll(_EDITOR_FOCUSABLE), a);
}
// Drop an editor's pending deferred focus so it cannot fire against the rebuilt DOM.
function _cancelEditorFocus(el) {
  if (el && el.__focusTimer) { clearTimeout(el.__focusTimer); el.__focusTimer = 0; }
}
// Clamp a selection to a value of `len` characters and normalize its order. The two offsets are one
// range, so a snapshot missing EITHER of them falls back to the end-of-text caret rather than
// selecting from the surviving offset to the end.
function _clampSelRange(sel, len) {
  const a = sel ? sel.selStart : null;
  const b = sel ? sel.selEnd : null;
  const usable = function (n) { return typeof n === "number" && isFinite(n); };
  if (!usable(a) || !usable(b)) return [len, len];
  const clamp = function (n) { return Math.min(Math.max(n, 0), len); };
  return [Math.min(clamp(a), clamp(b)), Math.max(clamp(a), clamp(b))];
}
function _widgetOrderKey(c) {
  const o = _widgetOrder.get(partKey(c.widget, c.part));
  return o == null ? 1e9 : o;
}
// Order key that groups comments by anchor family (text by document position, then the non-text
// anchor bands) so the sidebar list and the Copy-all bundle sort identically. Kept in one place
// so a new anchor type is added once, not in every renderer that sorts comments.
function _anchorSortKey(c) {
  return (c.anchorType === "document")
    ? -1
    : (c.anchorType === "mermaid")
    ? (1e12 + (c.diagramIndex || 0) * 1000)
    : (c.anchorType === "diff")
    ? (2e12 + (c.diffIndex || 0) * 1e6 + (parseInt(c.lineKey, 10) || 0))
    : (c.anchorType === "image")
    ? (3e12 + (c.imageIndex || 0))
    : (c.anchorType === "link")
    ? (3.5e12 + (Number.isFinite(Number(c.linkIndex)) ? Number(c.linkIndex) : 0))
    : (c.anchorType === "widget")
    ? (4e12 + _widgetOrderKey(c))
    : (c.anchorType === "slide")
    ? (5e12 + (typeof c.slideIndex === "number" && c.slideIndex >= 0 ? c.slideIndex : 0))
    : (typeof c.start === "number" ? c.start : 0);
}
// The display name for a board in the sidebar: its author-supplied aria-label if present,
// else the raw data-cm-widget name.
function _widgetDisplayName(name) {
  try {
    const el = root.querySelector('[data-cm-widget="' + _cssEsc(name) + '"]');
    if (el) { const al = el.getAttribute("aria-label"); if (al && al.trim()) return al.trim(); }
  } catch (e) { /* invalid selector from an exotic name - fall through */ }
  return name;
}
// Scroll a board into view and flash it, so a state card's "jump" behaves like a comment card.
function _jumpToWidget(name) {
  if (!name) return;
  let el = null;
  try { el = root.querySelector('[data-cm-widget="' + _cssEsc(name) + '"]'); } catch (e) { /* invalid selector */ }
  if (!el) return;
  expandCollapsedAncestors(el);
  el.scrollIntoView({ behavior: cmScrollBehavior(), block: "center" });
  el.classList.add("cm-widget-flash");
  setTimeout(() => el.classList.remove("cm-widget-flash"), 2200);
}
// One state card PER changed board, shaped like a regular comment card: an "in: <board>"
// title, a jump button that focuses that board, the moved-part list, and a meta line with the
// first-change time plus a "Reset changes" button that restores that board only.
function _renderWidgetStateCard(changes) {
  const groups = new Map();
  changes.forEach((ch) => {
    if (!groups.has(ch.widget)) groups.set(ch.widget, []);
    groups.get(ch.widget).push(ch);
  });
  const first = (typeof widgetFirstChangeAt === "function") ? widgetFirstChangeAt() : null;
  const timeHtml = first ? `<bdi>${escapeHtml(formatTime(first))}</bdi>` : "";
  let html = "";
  groups.forEach((list, name) => {
    const items = list.map((ch) =>
      `<li>"${escapeHtml(ch.label || ch.part)}" moved from <strong>${escapeHtml(ch.from)}</strong> to <strong>${escapeHtml(ch.to)}</strong></li>`
    ).join("");
    html += `
    <article class="cm-card cm-card-state" data-cm-state="1" data-cm-widget-name="${escapeHtml(name)}">
      <div class="section">in: <strong>${escapeHtml(_widgetDisplayName(name))}</strong></div>
      <div class="cm-card-state-title">Layout change - ${list.length} item${list.length === 1 ? "" : "s"} moved</div>
      <ul>${items}</ul>
      <div class="note">Auto-tracked from the current layout. Included in Copy all so the agent can reformat the source; the file stays Not shareable until re-exported.</div>
      <div class="meta">
        <span>${timeHtml}</span>
        <span class="acts">
          <button type="button" data-act="state-jump" data-cm-widget-name="${escapeHtml(name)}" title="Scroll to this board">jump</button>
          <button type="button" data-act="state-reset" data-cm-widget-name="${escapeHtml(name)}" title="Return cards to their original positions">Reset changes</button>
        </span>
      </div>
    </article>`;
  });
  return html;
}
// Scroll the anchored content (text highlight, mermaid node, diff line, or image) into
// view and flash it. Shared by the jump button and by edit/delete (so the user sees which
// comment is affected before the composer opens or the confirm dialog appears).
function scrollToAnchor(c) {
  if (!c) return;
  let el = null;
  if (c.anchorType === "mermaid") el = findMermaidNode(c.diagramIndex, c.nodeKey);
  else if (c.anchorType === "diff") el = findDiffLineEls(c.diffIndex, c.lineKey)[0];
  else if (c.anchorType === "image") el = resolveImageEl(c);
  else if (c.anchorType === "link") { el = resolveLinkEl(c); if (el) flashLink(c.id); }
  else if (c.anchorType === "widget") el = findWidgetPart(c.widget, c.part);
  else if (c.anchorType === "document") {
    // On a fixed-stage deck, window.scrollTo is a no-op; jump to the first slide (the natural
    // document start) so a document-wide comment card does not strand the presenter.
    if (window.__cmhDeck) window.__cmhDeck.showSlide(0);
    else window.scrollTo({ top: 0, behavior: cmScrollBehavior() });
    flashActive(c.id);
    return;
  }
  else if (c.anchorType === "slide") {
    // A slide-scoped comment navigates the deck to its owning slide.
    if (window.__cmhDeck) {
      if (!(c.slideId && window.__cmhDeck.showSlideById(c.slideId))
        && typeof c.slideIndex === "number" && c.slideIndex >= 0) {
        window.__cmhDeck.showSlide(c.slideIndex);
      }
    }
    flashActive(c.id);
    return;
  }
  else el = root.querySelector(`mark.cm-hl[data-cid="${c.id}"]`);
  if (el) { expandCollapsedAncestors(el); el.scrollIntoView({ behavior: cmScrollBehavior(), block: "center" }); flashActive(c.id); }
}
// A comment can live inside a collapsed section (display:none = no layout box), so
// expand every collapsed ancestor section before scrolling to it.
function expandCollapsedAncestors(el) {
  // A comment can also live inside a section hidden by the side-TOC filter; clear the filter so the
  // jump target gets a layout box (scrollIntoView is a no-op on a display:none element).
  if (el && el.closest && el.closest("section.cm-toc-filtered")) {
    const _s = document.querySelector(".cm-side-toc-search");
    if (_s && _s.value) { _s.value = ""; _s.dispatchEvent(new Event("input")); }
  }
  let sec = el && el.closest && el.closest("section.cmh-section-collapsed");
  while (sec) {
    sec.classList.remove("cmh-section-collapsed");
    const caret = cmhOwnChrome(sec, ":scope > .cmh-section-heading .cmh-sec-caret");
    if (caret) {
      caret.setAttribute("aria-expanded", "true");
      caret.title = "Collapse section";
      caret.setAttribute("aria-label", "Collapse section");
    }
    sec = sec.parentElement && sec.parentElement.closest && sec.parentElement.closest("section.cmh-section-collapsed");
  }
}
// ---- Inline reply composing (issue #644) and inline note editing (issue #703) ----
// Replies AND comment notes are composed and edited IN the sidebar thread card (Word-style), not in
// a floating popup: editing never scrolls the document to the anchor. A NEW reply box starts EMPTY -
// it never prepopulates with the comment being replied to. Editing an existing note (a thread root or
// a reply) prefills with that entry's OWN text. renderComments() rebuilds the list, so these
// transient editors are naturally cleared on save.
let _activeInlineEditor = null;
function _buildInlineReplyEditor(initialText, saveLabel, onSave, onCancel, opts) {
  const o = opts || {};
  const wrap = document.createElement("div");
  wrap.className = "cm-reply-compose";
  const ta = document.createElement("textarea");
  ta.className = "cm-reply-input";
  ta.setAttribute("rows", "2");
  ta.setAttribute("aria-label", o.label || "Write a reply");
  ta.placeholder = o.placeholder || "Write a reply...";
  ta.value = initialText || "";
  // The side pane offers the same rich-text editing as the new-comment composer (issue #774): the
  // shared toolbar above the textarea plus the Ctrl/Cmd formatting shortcuts.
  const formatBar = noteFormatBarElement();
  wireNoteFormatBar(formatBar, ta);
  const actions = document.createElement("div");
  actions.className = "cm-reply-compose-actions";
  const cancel = document.createElement("button");
  cancel.type = "button"; cancel.className = "cm-reply-cancel"; cancel.textContent = "Cancel";
  const save = document.createElement("button");
  save.type = "button"; save.className = "cm-reply-save"; save.textContent = saveLabel;
  actions.appendChild(cancel); actions.appendChild(save);
  wrap.appendChild(formatBar); wrap.appendChild(ta); wrap.appendChild(actions);
  function doSave() {
    const val = ta.value.trim();
    if (!val) { ta.setAttribute("aria-invalid", "true"); ta.classList.add("cm-invalid"); ta.focus(); return; }
    onSave(val);
  }
  cancel.addEventListener("click", function () { onCancel(); });
  save.addEventListener("click", doSave);
  // Clear the blank-note invalid state as soon as the reviewer types or formats, matching the
  // floating composer (a toolbar action dispatches its own `input` event).
  ta.addEventListener("input", function () { ta.removeAttribute("aria-invalid"); ta.classList.remove("cm-invalid"); });
  cmhAutogrow(ta);
  // The editor now holds seven toolbar buttons plus Cancel/Save, so bind the keys on the WRAPPER,
  // not the textarea: Escape from a focused button must cancel THIS editor rather than bubbling to
  // the document handler, which would discard an unrelated floating composer's draft.
  wrap.addEventListener("keydown", function (e) {
    // Ignore shortcuts mid-IME composition so Escape/Enter cannot discard a draft the composer is
    // still assembling (e.g. a CJK candidate window).
    if (e.isComposing || isNoteComposing(ta)) return;
    if (handleNoteFormatShortcut(e, ta)) return;
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); e.stopPropagation(); doSave(); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onCancel(); }
  });
  // Focus the textarea, selecting [selStart, selEnd] when given (a draft restored across a re-render
  // keeps its range). With no range it keeps whatever the textarea holds AT THE MOMENT OF THE CALL -
  // captured here rather than when the timer fires, since a blur in between can move it - so
  // re-focusing an OPEN editor (re-clicking Reply/edit, or a hand-back from another surface) never
  // collapses or re-anchors the reviewer's live selection; a freshly built editor already sits at the
  // end of its value. The pending timer is cancelled first, so the last caller wins outright rather
  // than by queue order.
  wrap._focus = function (selStart, selEnd, selDir) {
    // "Exactly one offset" is not a usable range, so it takes the keep-current path rather than
    // silently jumping the caret to the end.
    const keep = (selStart == null || selEnd == null);
    const wantStart = keep ? ta.selectionStart : selStart;
    const wantEnd = keep ? ta.selectionEnd : selEnd;
    const wantDir = (keep && selDir == null) ? ta.selectionDirection : selDir;
    if (wrap.__focusTimer) clearTimeout(wrap.__focusTimer);
    // Deferred while a modal is up rather than DROPPED: the reviewer asked for this caret, so the
    // intent is held until the dialog closes instead of leaving the re-opened editor focus-less.
    let held = false;
    const fire = function () {
      wrap.__focusTimer = 0;
      if (ta.isConnected === false) return;
      // Checked at DELIVERY, not only when the timer was armed: a modal can open in between (the
      // quota recovery opens the storage manager from a microtask, which runs BEFORE this
      // macrotask), and landing the caret in a pane behind that overlay is exactly the escape the
      // render-time veto closes. The selection restore stands either way; only focus waits.
      if (_cmhFocusBlockedByModal()) { held = true; wrap.__focusTimer = setTimeout(fire, 150); return; }
      // A held focus only lands where nothing else has claimed one, so re-delivering it can never
      // fight the dialog's own restore-to-opener on close.
      const act = document.activeElement;
      if (held && act && act !== document.body && act !== document.documentElement) return;
      try {
        ta.focus();
        const r = _clampSelRange({ selStart: wantStart, selEnd: wantEnd }, ta.value.length);
        try { ta.setSelectionRange(r[0], r[1], wantDir || "none"); }
        catch (err2) { ta.setSelectionRange(r[0], r[1]); }
      } catch (err) {}
    };
    wrap.__focusTimer = setTimeout(fire, 0);
  };
  return wrap;
}
// Exactly one inline reply editor is open at a time (opening another, or a full re-render, first
// closes the current one) so a transient editor can never silently drop another card's draft.
function _closeActiveInlineEditor() {
  const a = _activeInlineEditor;
  _activeInlineEditor = null;
  // The editor is about to go away, so drop its pending deferred focus rather than leaving a timer
  // to fire against a detached textarea.
  if (a) _cancelEditorFocus(a.el);
  if (a && typeof a.restore === "function") { try { a.restore(); } catch (e) {} }
}
// Cross-surface edit coordination: the in-document comment dialog can edit the same note in place,
// so each surface asks the other whether it already owns this comment's edit. Reports the active
// sidebar editor for `cid`, whether it holds unsaved text, and how to focus or drop it, so exactly
// one editor exists per comment and a dirty draft is never silently overwritten.
function cmhSidebarNoteEditor(cid) {
  const a = _activeInlineEditor;
  if (!a || a.targetId !== cid || (a.kind !== "edit" && a.kind !== "edit-root")) return null;
  const ta = a.el && a.el.querySelector("textarea");
  const c = comments.find(function (x) { return x.id === cid; });
  const original = (c && c.note != null) ? String(c.note) : "";
  return {
    dirty: !!ta && ta.value.trim() !== original.trim(),
    focus: function () { if (a.el && a.el._focus) a.el._focus(); },
    close: function () { _closeActiveInlineEditor(); },
  };
}
function _focusInList(sel) {
  // Same rule as the re-render's restore: with a modal up the pane is behind its overlay, so a
  // post-save hand-back must not reach into it (that would undo _keepModalFocus in the same tick).
  if (_cmhFocusBlockedByModal()) return;
  _focusListEl(listEl.querySelector(sel));
}
// Hand focus back to a side-pane control an editor just vacated - unless a modal is up, in which
// case the pane is behind its overlay and the focus the closing editor released belongs to the
// dialog instead (doing nothing would leave it stranded on <body> outside the dialog's Tab trap).
function _restoreFocusTo(el) {
  const modal = _cmhOpenModalBox();
  if (modal) { _keepModalFocus(modal); return; }
  if (el) { try { el.focus(); } catch (e) {} }
}
// preventScroll: refocusing a rebuilt panel control must never scroll the DOCUMENT (inline editing
// and the panel's own housekeeping deliberately leave the reader's place in the page alone).
function _focusListEl(el) {
  if (el) { try { el.focus({ preventScroll: true }); } catch (e) { try { el.focus(); } catch (e2) {} } }
}
// ---- Focus across a re-render of the list (issue #897) ----
// renderComments() replaces the whole list, destroying whatever control the reviewer was on. The
// controls that re-render from INSIDE the list - the checklist/note/board Reset cards and the
// comment/reply delete confirms - therefore used to leave document.activeElement on <body>, so a
// keyboard or screen-reader user lost their place entirely. Every render captures where focus was
// before it rebuilds and hands it back afterwards, so this holds however the render was reached
// (synchronously from the click, a frame later through the board's mutation observer, or twice over
// when two renders are queued) rather than depending on each handler to remember.
const _LIST_FOCUSABLE = "button, a[href], input, select, textarea, [tabindex]";
// The identity a rebuilt card is found by, most specific first: a reply entry, then the four card
// kinds (comment, checklist, note, board).
const _LIST_ID_ATTRS = ["data-reply-cid", "data-cid", "data-cmh-checklist-name", "data-cmh-note-name", "data-cm-widget-name"];
function _captureListFocus() {
  const a = document.activeElement;
  // Only focus INSIDE the list is this function's business: a render triggered from a note the
  // reviewer is typing into, a checklist ticked in the document, or the Sort button must leave the
  // caret exactly where it is (the CMH-THREAD-09 rule). The container itself survives the rebuild,
  // and an editor's focus is carried by the draft snapshot instead - including on the save paths,
  // which null the editor before rendering and then focus the right rebuilt control themselves, so
  // an intermediate landing here would only make focus move twice.
  if (!a || a === listEl || !listEl.contains(a)) return null;
  if (a.closest && a.closest(".cm-reply-compose")) return null;
  if (_activeInlineEditor && _activeInlineEditor.el && _activeInlineEditor.el.contains(a)) return null;
  const act = (a.dataset && a.dataset.act) || "";
  const holder = a.closest("[data-reply-cid]") || a.closest(".cm-card");
  let sel = "";
  if (act && holder) {
    for (let i = 0; i < _LIST_ID_ATTRS.length && !sel; i++) {
      const v = holder.getAttribute(_LIST_ID_ATTRS[i]);
      if (v) sel = "[" + _LIST_ID_ATTRS[i] + '="' + _cssEsc(v) + '"] [data-act="' + _cssEsc(act) + '"]';
    }
  }
  // The index is taken over the SAME filtered sequence the restore searches, so a card the comment
  // filter is hiding cannot shift the two apart and land the reviewer on a distant control.
  return { sel: sel, idx: Array.prototype.indexOf.call(_listFocusables(), a) };
}
// A control the reviewer can actually land on. focus() is SILENT on a hidden, disabled, or inert
// element, which would strand them on <body> after all - and the comment search hides non-matching
// cards outright, so the rebuilt list routinely holds controls that cannot take focus.
function _listCtlFocusable(el) {
  if (!el || el.disabled || el.hidden) return false;
  if (el.closest && el.closest("[inert]")) return false;
  return typeof el.getClientRects !== "function" || el.getClientRects().length > 0;
}
function _listFocusables() {
  return Array.prototype.filter.call(listEl.querySelectorAll(_LIST_FOCUSABLE), _listCtlFocusable);
}
function _restoreListFocus(plan) {
  if (!plan) return;
  // Step in only where the rebuild actually STRANDED the reviewer. Anything else holding focus - a
  // control the render itself focused, an overlay, a re-opened inline editor (whose own focus is
  // deferred, so its pending timer counts) - keeps it.
  const a = document.activeElement;
  if (a && a !== document.body) return;
  const ed = _activeInlineEditor && _activeInlineEditor.el;
  if (ed && ed.__focusTimer) return;
  const ctls = _listFocusables();
  let match = null;
  if (plan.sel) { try { match = listEl.querySelector(plan.sel); } catch (e) { /* exotic identity */ } }
  // The equivalent rebuilt control first; else whichever control took its index in the rebuilt list,
  // then outwards from there, so a candidate that still refuses focus hands off to its NEIGHBOUR
  // rather than to the top of a long list; and finally the list container itself (tabindex="-1"),
  // so an emptied list still takes focus rather than <body>.
  const order = [];
  if (match && _listCtlFocusable(match)) order.push(match);
  if (ctls.length) {
    const at = Math.min(Math.max(plan.idx, 0), ctls.length - 1);
    for (let d = 0; d < ctls.length; d++) {
      if (at + d < ctls.length) order.push(ctls[at + d]);
      if (d && at - d >= 0) order.push(ctls[at - d]);
    }
  }
  order.push(listEl);
  for (let i = 0; i < order.length; i++) {
    _focusListEl(order[i]);
    if (document.activeElement === order[i]) return;
  }
}
// First-reply identity prompt (issue #645), tracked separately from the first-COMMENT nudge so that a
// reviewer whose first attributable action is a reply is still prompted even if an earlier comment
// composer already consumed the shared comment nudge. Non-blocking - revealing the sidebar identity
// editor once; the reply still saves unattributed if declined.
let _cmReplyIdentityNudged = false;
function _nudgeIdentityOnReply() {
  if (_cmReplyIdentityNudged) return;
  if (typeof getAuthorName === "function" && getAuthorName()) return;
  if (!document.getElementById("cmIdentity")) return;
  _cmReplyIdentityNudged = true;
  if (typeof beginEditIdentity === "function") beginEditIdentity(false);
}
// Mirror the composer's quota recovery: on a quota failure the write is stashed by saveComments(), so
// open the storage manager (deferred) to let the reviewer free space and have the pending write
// retried; fall back to a toast if the manager cannot open. A non-quota (blocked/private) failure
// already surfaces saveComments()'s own recovery toast, so nothing extra is shown for it.
function _afterInlineSaveQuota(saved, label) {
  if (saved || !_cmhLastSaveQuota) return;
  queueMicrotask(function () {
    const opened = (typeof openStorageManager === "function") && openStorageManager({ reason: "quota" });
    if (!opened) {
      showToast("The " + label + " is shown but this browser's storage is full - free space from Manage storage.",
        { alert: true, duration: 8000, action: (typeof cmhStorageAction === "function") ? cmhStorageAction(CMH_STORE_KEY) : null });
    }
  });
}
function openInlineReply(card, rootId) {
  if (!card) return;
  const row = card.querySelector(".cm-reply-row");
  if (!row) return;
  if (!comments.some(function (x) { return x.id === rootId && !isReply(x); })) return;
  // Re-clicking Reply on a card whose editor is already open just refocuses it (never discards the draft).
  if (_activeInlineEditor && _activeInlineEditor.kind === "reply" && _activeInlineEditor.targetId === rootId) {
    if (_activeInlineEditor.el && _activeInlineEditor.el._focus) _activeInlineEditor.el._focus();
    return;
  }
  _closeActiveInlineEditor();
  const btn = row.querySelector(".cm-reply-btn");
  const editor = _buildInlineReplyEditor("", "Save reply",
    function (val) {
      if (!comments.some(function (x) { return x.id === rootId && !isReply(x); })) {
        showToast("The comment you were replying to was deleted - your reply was not saved.", { alert: true, duration: 6000 });
        return;
      }
      const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
      comments.push(stampAuthor({ id: id, parentId: rootId, note: val, createdAt: new Date().toISOString() }));
      const ok = saveComments();
      _activeInlineEditor = null;
      renderComments();
      _focusInList('.cm-card[data-cid="' + rootId + '"] .cm-reply-btn');
      _afterInlineSaveQuota(ok, "reply");
    },
    function () { _closeActiveInlineEditor(); });
  if (btn) btn.hidden = true;
  row.appendChild(editor);
  cmhAutogrowResize(editor.querySelector("textarea"));
  _activeInlineEditor = { el: editor, kind: "reply", targetId: rootId, restore: function () { editor.remove(); if (btn) { btn.hidden = false; _restoreFocusTo(btn); } } };
  editor._focus();
  // First-reply identity prompt (issue #645).
  _nudgeIdentityOnReply();
}
function openInlineNoteEdit(entry, cid) {
  if (!entry) return;
  const rc = comments.find(function (x) { return x.id === cid; });
  if (!rc) return;
  const noteEl = entry.querySelector(".note");
  if (!noteEl) return;
  const isRootNote = (typeof isReply === "function") ? !isReply(rc) : !rc.parentId;
  // A floating edit composer for this same note may already be open (re-selecting the highlighted
  // text opens one). Reuse it rather than editing the same note in two places at once.
  if (typeof openEditComposers !== "undefined" && openEditComposers.get(cid)) {
    if (typeof openComposerForEdit === "function") openComposerForEdit(rc);
    return;
  }
  // Same rule across surfaces: the in-document dialog may already be editing this note. Hand a
  // dirty draft back to it (never open a second editor whose save would silently overwrite it);
  // an untouched one is simply closed so editing continues here.
  if (typeof cmhPopoverNoteEditor === "function") {
    const pop = cmhPopoverNoteEditor(cid);
    if (pop) {
      if (pop.dirty) {
        pop.focus();
        showToast("This comment is already open for editing on the page - finish or cancel that edit first.", { duration: 5000 });
        return;
      }
      pop.close();
    }
  }
  const kind = isRootNote ? "edit-root" : "edit";
  const editBtnSel = isRootNote ? '[data-act="edit"]' : '[data-act="reply-edit"]';
  const focusSel = isRootNote
    ? '.cm-card[data-cid="' + cid + '"] .cm-entry-root [data-act="edit"]'
    : '[data-reply-cid="' + cid + '"] [data-act="reply-edit"]';
  // Re-clicking edit on a note already being edited just refocuses it (never resets the draft).
  if (_activeInlineEditor && _activeInlineEditor.kind === kind && _activeInlineEditor.targetId === cid) {
    if (_activeInlineEditor.el && _activeInlineEditor.el._focus) _activeInlineEditor.el._focus();
    return;
  }
  _closeActiveInlineEditor();
  const editor = _buildInlineReplyEditor(rc.note == null ? "" : rc.note, "Save",
    function (val) {
      const c = comments.find(function (x) { return x.id === cid; });
      if (!c) {
        showToast("The " + (isRootNote ? "comment" : "reply") + " you were editing was deleted - your change was not saved.",
          { alert: true, duration: 6000 });
        _activeInlineEditor = null;
        renderComments();
        return;
      }
      c.note = val; c.updatedAt = new Date().toISOString();
      const ok = saveComments();
      _activeInlineEditor = null;
      renderComments();
      _focusInList(focusSel);
      _afterInlineSaveQuota(ok, "edit");
    },
    function () { _closeActiveInlineEditor(); },
    { label: isRootNote ? "Edit comment" : "Write a reply",
      placeholder: isRootNote ? "Edit this comment..." : "Write a reply..." });
  entry.classList.add("cm-reply-editing");
  noteEl.hidden = true;
  noteEl.insertAdjacentElement("afterend", editor);
  cmhAutogrowResize(editor.querySelector("textarea"));
  _activeInlineEditor = { el: editor, kind: kind, targetId: cid, restore: function () {
    editor.remove();
    noteEl.hidden = false;
    entry.classList.remove("cm-reply-editing");
    const eb = entry.querySelector(editBtnSel);
    if (eb) _restoreFocusTo(eb);
  } };
  editor._focus();
}
// ---- One delete path for a comment thread, shared by every surface (issue #1031) ----
// The sidebar card and the in-document comment dialog delete the SAME way: confirm (naming the
// replies that go with the root), tombstone the embedded copy, close any editor or dialog left
// showing a removed id, drop the highlight, save, and re-render. Keeping it in one function is what
// makes the two surfaces impossible to drift apart.
function cmhConfirmDeleteThread(id, opts) {
  const c = comments.find((x) => x.id === id);
  if (!c) return false;
  const o = opts || {};
  if (o.scrollFirst !== false) scrollToAnchor(c);   // jump to the anchor first, then confirm
  // Deleting a thread root removes the whole thread (root + replies); a reply is deleted
  // through its own reply-del button.
  const ids = (typeof threadIds === "function") ? threadIds(id) : [id];
  const nReplies = ids.length - 1;
  const msg = nReplies > 0
    ? ("Delete this comment and its " + nReplies + " repl" + (nReplies === 1 ? "y" : "ies") + "?")
    : "Delete this comment?";
  if (!confirm(msg)) return false;
  const tombstoneOk = _tombstoneEmbedded(ids);
  const drop = new Set(ids);
  ids.forEach((tid) => { const oc = openEditComposers.get(tid); if (oc) closeComposerElement(oc); });
  if (typeof cmhClosePopoverForIds === "function") cmhClosePopoverForIds(ids);
  comments = comments.filter((x) => !drop.has(x.id));
  removeHighlight(c);
  const commentsOk = saveComments();
  _ensureTombstoneEmbedded(ids, tombstoneOk, commentsOk);
  renderComments();
  return true;
}
listEl.addEventListener("click", (e) => {
  // A click inside an inline reply/edit editor belongs to that editor (its textarea and its
  // Save/Cancel buttons); it must never also fire the card's jump-to-anchor fall-through, which
  // would scroll the document away while the reviewer is editing in the panel.
  if (e.target.closest && e.target.closest(".cm-reply-compose")) return;
  // Checklist change cards are not comments: jump focuses the checklist, Reset reverts it to
  // the authored state. Handle before the .cm-card comment path (a checklist card is a .cm-card).
  const clCard = e.target.closest(".cm-card-checklist");
  if (clCard) {
    const cid = e.target.getAttribute("data-cmh-checklist-name") || clCard.getAttribute("data-cmh-checklist-name");
    if (e.target.dataset.act === "cl-reset") { if (typeof resetChecklist === "function") resetChecklist(cid); }
    else if (typeof jumpToChecklist === "function") jumpToChecklist(cid);
    return;
  }
  // Note change cards are not comments: jump focuses the note field, reset reverts it to the
  // authored text. Handle before the .cm-card comment path (a note card is a .cm-card).
  const noteCard = e.target.closest(".cm-card-note");
  if (noteCard) {
    const nid = e.target.getAttribute("data-cmh-note-name") || noteCard.getAttribute("data-cmh-note-name");
    if (e.target.dataset.act === "note-reset") { if (typeof resetNote === "function") resetNote(nid); }
    else if (typeof jumpToNote === "function") jumpToNote(nid);
    return;
  }
  // Widget state cards are not comments: their jump focuses the board and their Reset
  // restores that board's layout. Handle them before the comment-id path below.
  const stateCard = e.target.closest(".cm-card-state");
  if (stateCard) {
    const name = e.target.getAttribute("data-cm-widget-name") || stateCard.getAttribute("data-cm-widget-name");
    if (e.target.dataset.act === "state-reset") {
      let wel = null;
      try { wel = root.querySelector('[data-cm-widget="' + _cssEsc(name) + '"]'); } catch (err) { /* invalid selector */ }
      if (wel && typeof resetWidgetMoves === "function") resetWidgetMoves(wel);
    } else {
      _jumpToWidget(name);
    }
    return;
  }
  const card = e.target.closest(".cm-card");
  if (!card) return;
  // A rendered link inside a comment note is clickable; let it navigate without also firing the
  // card's jump/scroll handler.
  if (e.target.closest("a")) return;
  const id = card.dataset.cid;
  const act = e.target.dataset.act;
  if (act === "reply") {
    if (comments.some(x => x.id === id && !isReply(x))) openInlineReply(card, id);
    return;
  }
  if (act === "reply-del") {
    const entry = e.target.closest("[data-reply-cid]");
    const rid = entry && entry.getAttribute("data-reply-cid");
    const rc = comments.find(x => x.id === rid);
    if (rc && confirm("Delete this reply?")) {
      const oc = openEditComposers.get(rid);
      if (oc) closeComposerElement(oc);          // an open edit of this reply would silently lose its text
      const tombstoneOk = _tombstoneEmbedded([rid]);
      comments = comments.filter(x => x.id !== rid);
      const commentsOk = saveComments();
      _ensureTombstoneEmbedded([rid], tombstoneOk, commentsOk);
      renderComments();
    }
    return;
  }
  if (act === "reply-edit") {
    const entry = e.target.closest("[data-reply-cid]");
    const rid = entry && entry.getAttribute("data-reply-cid");
    openInlineNoteEdit(entry, rid);
    return;
  }
  if (act === "del") {
    cmhConfirmDeleteThread(id);
    return;
  }
  if (act === "edit") {
    // Edit the note IN the card (issue #703): no scroll to the anchor, no floating composer.
    const entry = e.target.closest(".cm-entry-root") || card.querySelector(".cm-entry-root");
    openInlineNoteEdit(entry, id);
    return;
  }
  const c = comments.find(x => x.id === id);
  scrollToAnchor(c);
});
function flashActive(id) {
  root.querySelectorAll("mark.cm-hl.active").forEach(m => m.classList.remove("active"));
  listEl.querySelectorAll(".cm-card.active").forEach(c => c.classList.remove("active"));
  root.querySelectorAll(`mark.cm-hl[data-cid="${id}"]`).forEach(m => m.classList.add("active"));
  flashMermaid(id);
  flashDiff(id);
  flashImage(id);
  flashWidget(id);
  const card = listEl.querySelector(`.cm-card[data-cid="${id}"]`);
  if (card) card.classList.add("active");
  setTimeout(() => {
    root.querySelectorAll(`mark.cm-hl[data-cid="${id}"]`).forEach(m => m.classList.remove("active"));
  }, 2200);
}
root.addEventListener("click", (e) => {
  const m = e.target.closest("mark.cm-hl");
  if (!m) return;
  const id = m.dataset.cid;
  openSidebar();
  const card = listEl.querySelector(`.cm-card[data-cid="${id}"]`);
  if (card) { card.scrollIntoView({ behavior: cmScrollBehavior(), block: "center" }); flashActive(id); }
});
