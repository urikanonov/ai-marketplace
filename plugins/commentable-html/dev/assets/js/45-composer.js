/* ---------- Composer (per-instance, parallel-safe) ---------- */
function bringToFront(el) { el.style.zIndex = ++composerZ; }

function positionComposerNear(el, anchorRect) {
  const w = el.offsetWidth || 380;
  const h = el.offsetHeight || 220;
  const margin = 8;
  let left = Math.min(anchorRect.left, window.innerWidth - w - margin);
  let top  = anchorRect.bottom + margin;
  if (top + h > window.innerHeight) top = Math.max(margin, anchorRect.top - h - margin);
  const step = 28;
  for (let i = 0; i < 8; i++) {
    const collision = [...openComposers].some(other => {
      if (other === el) return false;
      const r = other.getBoundingClientRect();
      return Math.abs(r.left - left) < 8 && Math.abs(r.top - top) < 8;
    });
    if (!collision) break;
    left += step; top += step;
    if (left + w > window.innerWidth - margin || top + h > window.innerHeight - margin) {
      left = margin; top = margin;
      break;
    }
  }
  // Final clamp: keep the whole composer within the viewport even when the anchor
  // itself is off-screen (e.g. a selection below the fold), so its Save button is
  // always reachable.
  left = Math.min(Math.max(margin, left), Math.max(margin, window.innerWidth - w - margin));
  top = Math.min(Math.max(margin, top), Math.max(margin, window.innerHeight - h - margin));
  el.style.left = left + "px";
  el.style.top  = top + "px";
}

function createComposerElement({ mode, range, quote, comment, mermaid, diff, image, widget, slide, link }) {
  // When deck commenting is disabled ("off" present-only state) every "new-*" entry point
  // (selection, document, mermaid, image, diff, widget, heading) must be inert, not just the
  // text-selection popup. Editing is unreachable in off (it is only offered at zero comments),
  // so gate every new-comment composer here at the single choke point.
  if (String(mode || "").indexOf("new") === 0
      && document.body.classList.contains("cmh-deck-comments-off")) {
    return null;
  }
  const el = document.createElement("div");
  // Remember what had focus so keyboard users return to the diagram node / diff
  // line / image (not <body>) after the composer closes.
  el._opener = (document.activeElement && document.activeElement !== document.body
    && root.contains(document.activeElement)) ? document.activeElement : null;
  el.className = "cm-composer cm-skip";
  el.setAttribute("role", "group");
  el.setAttribute("aria-label", "Review comment composer");
  el.innerHTML = `
    <div class="cm-composer-handle" title="Drag to move">
      <span class="grip" aria-hidden="true">&#x22EE;&#x22EE;</span>
      <span class="label">drag to move</span>
    </div>
    <div class="quote"></div>
    <div class="cm-format-bar" role="group" aria-label="Comment formatting">
      <button type="button" data-fmt="bold" title="Bold (Ctrl+B)" aria-label="Bold"><strong>B</strong></button>
      <button type="button" data-fmt="italic" title="Italic (Ctrl+I)" aria-label="Italic"><em>I</em></button>
      <button type="button" data-fmt="underline" title="Underline (Ctrl+U)" aria-label="Underline"><span style="text-decoration:underline">U</span></button>
      <button type="button" data-fmt="strike" title="Strikethrough" aria-label="Strikethrough"><s>S</s></button>
      <button type="button" data-fmt="code" title="Inline code" aria-label="Inline code">&lt;/&gt;</button>
      <button type="button" data-fmt="link" title="Link (Ctrl+K)" aria-label="Insert link">&#128279;</button>
      <button type="button" data-fmt="list" title="Bullet list" aria-label="Bullet list">&#8226;</button>
    </div>
    <textarea aria-label="Review comment" placeholder="Write your review comment... (**bold** *italic* __underline__, Ctrl/Cmd+Enter to save, Esc to cancel)"></textarea>
    <div class="row">
      <button type="button" data-act="cancel">Cancel</button>
      <button type="button" class="primary" data-act="save">Save comment</button>
    </div>`;
  const handle = el.querySelector(".cm-composer-handle");
  const quoteEl = el.querySelector(".quote");
  const ta = el.querySelector("textarea");
  const cancelBtn = el.querySelector('[data-act="cancel"]');
  const saveBtn = el.querySelector('[data-act="save"]');
  // Associate the quoted anchor with the textarea for screen readers, and clear the
  // invalid state as soon as the reviewer starts typing.
  const _quoteId = "cm-quote-" + Math.random().toString(36).slice(2, 9);
  quoteEl.id = _quoteId;
  ta.setAttribute("aria-describedby", _quoteId);
  ta.addEventListener("input", () => { ta.removeAttribute("aria-invalid"); ta.classList.remove("cm-invalid"); });

  el._mode = mode;
  el._editingId = (comment && mode === "edit") ? comment.id : null;
  el._parentId = null;
  let isCodeQuote = false;
  if (mode === "new") {
    const start = offsetWithin(range.startContainer, range.startOffset);
    const end   = offsetWithin(range.endContainer,   range.endOffset);
    if (start < 0 || end < 0 || start >= end) {
      showToast("Could not anchor that selection. Try again with a single contiguous text range.");
      return null;
    }
    el._start = start;
    el._end = end;
    el._quote = quote;
    let anc = range.startContainer;
    if (anc && anc.nodeType !== 1) anc = anc.parentElement;
    isCodeQuote = !!(anc && anc.closest("code, pre"));
  } else if (mode === "new-mermaid") {
    el._mermaid = mermaid;
    el._quote = mermaid.nodeLabel || mermaid.nodeKey;
  } else if (mode === "new-diff") {
    el._diff = diff;
    el._quote = diff.subStart != null ? diff.quote : ((diff.sign || " ") + diff.text);
    isCodeQuote = true;
  } else if (mode === "new-image") {
    el._image = image;
    el._quote = image.quote;
  } else if (mode === "new-link") {
    el._link = link;
    el._quote = link.quote;
  } else if (mode === "new-widget") {
    el._widget = widget;
    el._quote = widget.quote || widget.label || widget.part || widget.widget;
  } else if (mode === "new-document") {
    el._quote = "(document-wide comment)";
  } else if (mode === "new-slide") {
    el._slide = slide;
    el._quote = slide && slide.slideTitle ? ("slide: " + slide.slideTitle) : "(comment on slide)";
  } else if (mode === "new-reply") {
    // A reply refines its thread root; it has no independent anchor. `comment` here is the
    // root, used only for context display and to inherit the anchor position.
    el._parentId = comment.id;
    el._replyRoot = comment;
    const rq = comment.quote || comment.note || "";
    el._quote = "reply to: " + String(rq).replace(/\s+/g, " ").trim().slice(0, 80);
  } else {
    el._quote = (comment.quote != null) ? comment.quote : (comment.parentId ? "(reply)" : "");
    isCodeQuote = !!comment.isCode;
  }

  if (isCodeQuote) quoteEl.classList.add("cm-quote-code");
  quoteEl.textContent = el._quote;
  ta.value = comment ? comment.note : "";

  document.body.appendChild(el);
  bringToFront(el);

  let anchorRect;
  if (mode === "new") {
    anchorRect = range.getBoundingClientRect();
  } else if (mode === "new-mermaid") {
    const node = findMermaidNode(mermaid.diagramIndex, mermaid.nodeKey);
    anchorRect = node ? node.getBoundingClientRect() : { left: 100, top: 100, bottom: 130, right: 200 };
  } else if (mode === "new-diff") {
    const el2 = findDiffLineEls(diff.diffIndex, diff.lineKey)[0];
    anchorRect = el2 ? el2.getBoundingClientRect() : { left: 100, top: 100, bottom: 130, right: 200 };
  } else if (mode === "new-image") {
    const imgEl = findImageEl(image.imageIndex);
    anchorRect = imgEl ? imgEl.getBoundingClientRect() : { left: 100, top: 100, bottom: 130, right: 200 };
  } else if (mode === "new-link") {
    const aEl = findLinkEl(link.linkIndex);
    anchorRect = aEl ? aEl.getBoundingClientRect() : { left: 100, top: 100, bottom: 130, right: 200 };
  } else if (mode === "new-widget") {
    const p = findWidgetPart(widget.widget, widget.part);
    anchorRect = p ? p.getBoundingClientRect() : { left: 120, top: 100, bottom: 130, right: 320 };
  } else if (mode === "new-document") {
    const cx = Math.max(20, Math.round(window.innerWidth / 2) - 190);
    anchorRect = { left: cx, top: 90, bottom: 120, right: cx + 380 };
  } else if (mode === "new-slide") {
    const cx = Math.max(20, Math.round(window.innerWidth / 2) - 190);
    anchorRect = { left: cx, top: 90, bottom: 120, right: cx + 380 };
  } else {
    // A reply inherits its thread root's anchor (it has no anchorType of its own), so resolve
    // the root and dispatch on ITS anchor type; a text root still resolves by the mark cid.
    const anchorSrc = comment.parentId
      ? (comments.find((x) => x.id === comment.parentId) || comment)
      : comment;
    let anchorEl = null;
    if (anchorSrc.anchorType === "mermaid") {
      anchorEl = findMermaidNode(anchorSrc.diagramIndex, anchorSrc.nodeKey);
    } else if (anchorSrc.anchorType === "diff") {
      anchorEl = findDiffLineEls(anchorSrc.diffIndex, anchorSrc.lineKey)[0];
    } else if (anchorSrc.anchorType === "image") {
      anchorEl = resolveImageEl(anchorSrc);
    } else if (anchorSrc.anchorType === "link") {
      anchorEl = resolveLinkEl(anchorSrc);
    } else if (anchorSrc.anchorType === "widget") {
      anchorEl = findWidgetPart(anchorSrc.widget, anchorSrc.part);
    } else {
      anchorEl = root.querySelector(`mark.cm-hl[data-cid="${anchorSrc.id}"]`);
    }
    anchorRect = anchorEl ? anchorEl.getBoundingClientRect() : { left: 100, top: 100, bottom: 130, right: 200 };
  }
  positionComposerNear(el, anchorRect);
  if (mode === "new") applyComposerPreview(el);

  const cleanups = [];
  cleanups.push(addListener(cancelBtn, "click", () => closeComposerElement(el)));
  cleanups.push(addListener(saveBtn, "click", () => saveComposerElement(el)));
  const formatBar = el.querySelector(".cm-format-bar");
  if (formatBar) {
    formatBar.querySelectorAll("button[data-fmt]").forEach((btn) => {
      // preventDefault on pointer/mouse down keeps the textarea's selection from collapsing when the
      // button takes focus (mousedown for desktop, pointerdown so touch devices are covered too); the
      // action runs on click.
      cleanups.push(addListener(btn, "pointerdown", (e) => e.preventDefault()));
      cleanups.push(addListener(btn, "mousedown", (e) => e.preventDefault()));
      cleanups.push(addListener(btn, "click", (e) => { e.preventDefault(); applyNoteFormat(ta, btn.getAttribute("data-fmt")); }));
    });
  }
  cleanups.push(addListener(ta, "keydown", (e) => {
    if (e.isComposing) return;
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey) {
      const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      const fmt = k === "b" ? "bold" : k === "i" ? "italic" : k === "u" ? "underline" : k === "k" ? "link" : null;
      if (fmt) { e.preventDefault(); e.stopPropagation(); applyNoteFormat(ta, fmt); return; }
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); saveComposerElement(el); }
    else if (e.key === "Escape") { e.preventDefault(); closeComposerElement(el); }
  }));
  cleanups.push(addListener(el, "focusin", () => { lastFocusedComposer = el; bringToFront(el); }));
  cleanups.push(addListener(el, "mousedown", () => { lastFocusedComposer = el; bringToFront(el); }));

  attachDrag(el, handle, cleanups);

  el._cleanup = () => { while (cleanups.length) { try { cleanups.pop()(); } catch (e) {} } };

  openComposers.add(el);
  if (el._editingId) openEditComposers.set(el._editingId, el);
  lastFocusedComposer = el;
  setTimeout(() => ta.focus(), 0);
  if (String(mode || "").indexOf("new") === 0 && typeof maybeNudgeIdentity === "function") maybeNudgeIdentity();
  return el;
}

function addListener(target, type, fn, opts) {
  target.addEventListener(type, fn, opts);
  return () => target.removeEventListener(type, fn, opts);
}

function attachDrag(el, handle, cleanups) {
  let dragging = false, offX = 0, offY = 0;
  function clamp() {
    const margin = 4;
    const rect = el.getBoundingClientRect();
    const maxLeft = window.innerWidth - rect.width - margin;
    const maxTop = window.innerHeight - rect.height - margin;
    let left = parseFloat(el.style.left) || rect.left;
    let top = parseFloat(el.style.top) || rect.top;
    left = Math.max(margin, Math.min(left, Math.max(margin, maxLeft)));
    top = Math.max(margin, Math.min(top, Math.max(margin, maxTop)));
    el.style.left = left + "px";
    el.style.top = top + "px";
  }
  function onDown(e) {
    const pt = e.touches ? e.touches[0] : e;
    const rect = el.getBoundingClientRect();
    offX = pt.clientX - rect.left;
    offY = pt.clientY - rect.top;
    dragging = true;
    el.classList.add("dragging");
    lastFocusedComposer = el;
    bringToFront(el);
    e.preventDefault();
  }
  function onMove(e) {
    if (!dragging) return;
    const pt = e.touches ? e.touches[0] : e;
    el.style.left = (pt.clientX - offX) + "px";
    el.style.top  = (pt.clientY - offY) + "px";
    clamp();
    e.preventDefault();
  }
  function onUp() {
    if (!dragging) return;
    dragging = false;
    el.classList.remove("dragging");
  }
  cleanups.push(addListener(handle, "mousedown", onDown));
  cleanups.push(addListener(document, "mousemove", onMove));
  cleanups.push(addListener(document, "mouseup", onUp));
  cleanups.push(addListener(handle, "touchstart", onDown, { passive: false }));
  cleanups.push(addListener(document, "touchmove", onMove, { passive: false }));
  cleanups.push(addListener(document, "touchend", onUp));
}

// Preview highlight while composing a NEW text comment. The moment the composer opens,
// wrap the pending range in a transient mark.cm-preview so the reviewer sees exactly what
// the comment will anchor to. The preview carries NO data-cid (so the hover bubble, the
// highlight click handler, and the popover all treat it as inert - none of them act on a
// mark without a cid) and is NOT .cm-skip (so it stays counted in the text-offset space,
// keeping any concurrent composer's stored offsets correct). It is removed on cancel and
// converted into the real highlight on save. Whitespace-only gap nodes are left unwrapped:
// the saved highlight paints those transparently anyway (mark.cm-hl.cm-hl-gap), so the
// preview matches its appearance. File exports rebuild highlights from the embedded
// comments array over a pristine snapshot, so a live preview never leaks into a saved file.
function applyComposerPreview(el) {
  if (!el || el._mode !== "new") return;
  if (typeof el._start !== "number" || typeof el._end !== "number") return;
  const r = rangeFromOffsets(el._start, el._end);
  if (!r) return;
  // Track the created marks on the composer up front (the array is mutated in place), so a
  // mid-loop throw is still fully cleanable by the catch below - otherwise a partially
  // wrapped set of preview marks would leak into the live DOM with no reference.
  const marks = [];
  el._previewMarks = marks;
  try {
    getTextNodes().filter(n => r.intersectsNode(n)).forEach(tn => {
      let s = 0, e = tn.nodeValue.length;
      if (tn === r.startContainer) s = r.startOffset;
      if (tn === r.endContainer)   e = r.endOffset;
      if (s >= e) return;
      // Skip a whitespace-only span BEFORE splitting the node, so a gap between inline
      // elements never leaves a fragmented (but unwrapped, untracked) text node behind.
      if (!tn.nodeValue.slice(s, e).trim()) return;
      if (e < tn.nodeValue.length) tn.splitText(e);
      let target = tn;
      if (s > 0) target = tn.splitText(s);
      const m = document.createElement("mark");
      m.className = "cm-preview";
      target.parentNode.insertBefore(m, target);
      m.appendChild(target);
      marks.push(m);
    });
  } catch (e2) { clearComposerPreview(el); return; }
  // Drop the native selection so the amber preview reads exactly like a saved highlight
  // (the browser's own selection tint would otherwise double up over it), but only once an
  // amber preview actually stands in for it.
  if (marks.length) {
    try { window.getSelection().removeAllRanges(); } catch (e3) { /* headless / detached */ }
  }
}

function clearComposerPreview(el) {
  const marks = el && el._previewMarks;
  if (el) el._previewMarks = null;
  if (!marks || !marks.length) return;
  marks.forEach(m => {
    const parent = m.parentNode;
    if (!parent) return;
    while (m.firstChild) parent.insertBefore(m.firstChild, m);
    parent.removeChild(m);
    parent.normalize();
  });
}

function flashComposer(el) {
  el.classList.remove("flash");
  void el.offsetWidth;
  el.classList.add("flash");
  setTimeout(() => el.classList.remove("flash"), 700);
}

function openComposer(range, quote) {
  return createComposerElement({ mode: "new", range, quote });
}

function openComposerForReply(rootComment) {
  if (!rootComment || isReply(rootComment)) return null;
  return createComposerElement({ mode: "new-reply", comment: rootComment });
}

function openComposerForEdit(comment) {
  const existing = openEditComposers.get(comment.id);
  if (existing) {
    bringToFront(existing);
    flashComposer(existing);
    const r = existing.getBoundingClientRect();
    const outOfView = r.bottom < 0 || r.top > window.innerHeight || r.right < 0 || r.left > window.innerWidth;
    if (outOfView) {
      const anchorSrc = comment.parentId
        ? (comments.find((x) => x.id === comment.parentId) || comment)
        : comment;
      let anchorEl = null;
      if (anchorSrc.anchorType === "mermaid") anchorEl = findMermaidNode(anchorSrc.diagramIndex, anchorSrc.nodeKey);
      else if (anchorSrc.anchorType === "diff") anchorEl = findDiffLineEls(anchorSrc.diffIndex, anchorSrc.lineKey)[0];
      else if (anchorSrc.anchorType === "image") anchorEl = resolveImageEl(anchorSrc);
      else if (anchorSrc.anchorType === "link") anchorEl = resolveLinkEl(anchorSrc);
      else if (anchorSrc.anchorType === "widget") anchorEl = findWidgetPart(anchorSrc.widget, anchorSrc.part);
      else anchorEl = root.querySelector(`mark.cm-hl[data-cid="${anchorSrc.id}"]`);
      if (anchorEl) positionComposerNear(existing, anchorEl.getBoundingClientRect());
    }
    existing.querySelector("textarea").focus();
    return existing;
  }
  return createComposerElement({ mode: "edit", comment });
}

function closeComposerElement(el) {
  if (!el || !openComposers.has(el)) return;
  clearComposerPreview(el);
  openComposers.delete(el);
  if (el._editingId) openEditComposers.delete(el._editingId);
  if (lastFocusedComposer === el) lastFocusedComposer = null;
  if (typeof el._cleanup === "function") el._cleanup();
  const opener = el._opener;
  el.remove();
  // Return focus to whatever opened the composer (e.g. a keyboard-focused diff
  // line or image) if it is still connected, so keyboard users keep their place.
  if (opener && opener.isConnected && root.contains(opener)) {
    try { opener.focus(); } catch (e) {}
  }
}

function saveComposerElement(el) {
  const ta = el.querySelector("textarea");
  const note = ta.value.trim();
  if (!note) {
    // Blank note: mark the field invalid (announced to screen readers) instead of
    // silently doing nothing, then return focus for the reviewer to type.
    ta.setAttribute("aria-invalid", "true");
    ta.classList.add("cm-invalid");
    ta.focus();
    return;
  }
  ta.removeAttribute("aria-invalid");
  ta.classList.remove("cm-invalid");
  if (el._editingId) {
    const c = comments.find(c => c.id === el._editingId);
    if (c) { c.note = note; c.updatedAt = new Date().toISOString(); }
  } else if (el._parentId) {
    // The thread root may have been deleted while this reply composer was open. Do not append
    // an orphan (it would be hidden now and pruned on reload, silently losing the text): warn
    // and keep the composer open so the reviewer can recover their draft.
    if (!comments.some((x) => x.id === el._parentId && !isReply(x))) {
      showToast("The comment you were replying to was deleted - your reply was not saved. "
        + "Copy your text before closing.", { alert: true, duration: 8000 });
      return;
    }
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const comment = {
      id,
      parentId: el._parentId,
      note,
      createdAt: new Date().toISOString(),
    };
    comments.push(stampAuthor(comment));
  } else if (el._mode === "new-mermaid") {
    const info = el._mermaid;
    const host = mermaidHostForIndex(info.diagramIndex);
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const ctx = host ? captureMermaidContext(host) : { section: null, headingPath: [] };
    const comment = {
      id,
      anchorType: "mermaid",
      diagramIndex: info.diagramIndex,
      nodeKey: info.nodeKey,
      nodeLabel: info.nodeLabel,
      quote: info.nodeLabel || info.nodeKey,
      note,
      createdAt: new Date().toISOString(),
      ...ctx,
    };
    comments.push(stampAuthor(comment));
    if (!applyMermaidHighlight(comment)) {
      showToast("Comment saved, but the mermaid node could not be highlighted (the diagram may have re-rendered).");
    }
  } else if (el._mode === "new-diff") {
    const info = el._diff;
    const block = diffBlockForIndex(info.diffIndex);
    const host = block ? block.host : null;
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const ctx = host ? captureMermaidContext(host) : { section: null, headingPath: [] };
    const comment = {
      id,
      anchorType: "diff",
      diffIndex: info.diffIndex,
      lineKey: info.lineKey,
      side: info.side,
      lineType: info.lineType,
      oldNo: info.oldNo,
      newNo: info.newNo,
      diffLabel: info.label,
      subStart: info.subStart != null ? info.subStart : null,
      subEnd: info.subEnd != null ? info.subEnd : null,
      quote: info.subStart != null ? info.quote : ((info.sign || " ") + info.text),
      isCode: true,
      note,
      createdAt: new Date().toISOString(),
      ...ctx,
    };
    comments.push(stampAuthor(comment));
    if (!applyDiffHighlight(comment)) {
      showToast("Comment saved, but the diff line could not be highlighted (the diff may have re-rendered).");
    }
  } else if (el._mode === "new-image") {
    const info = el._image;
    const img = findImageEl(info.imageIndex);
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const ctx = img ? captureMermaidContext(img) : { section: null, headingPath: [] };
    const comment = {
      id,
      anchorType: "image",
      imageIndex: info.imageIndex,
      imageSrc: info.src,
      imageAlt: info.alt,
      imageKind: info.kind || "image",
      quote: info.quote,
      note,
      createdAt: new Date().toISOString(),
      ...ctx,
    };
    comments.push(stampAuthor(comment));
    if (!applyImageHighlight(comment)) {
      showToast("Comment saved, but the image could not be highlighted.");
    }
  } else if (el._mode === "new-link") {
    const info = el._link;
    const a = findLinkEl(info.linkIndex);
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const ctx = a ? captureMermaidContext(a) : { section: null, headingPath: [] };
    const comment = {
      id,
      anchorType: "link",
      linkIndex: info.linkIndex,
      linkHref: info.href,
      linkText: info.text,
      quote: info.quote,
      note,
      createdAt: new Date().toISOString(),
      ...ctx,
    };
    comments.push(stampAuthor(comment));
    if (!applyLinkHighlight(comment)) {
      showToast("Comment saved, but the link could not be highlighted.");
    }
  } else if (el._mode === "new-widget") {
    const info = el._widget;
    const partEl = findWidgetPart(info.widget, info.part);
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const ctx = partEl ? captureMermaidContext(partEl) : { section: null, headingPath: [] };
    const comment = {
      id,
      anchorType: "widget",
      widget: info.widget,
      part: info.part,
      partLabel: info.label,
      slot: info.slot != null ? info.slot : null,
      quote: info.quote,
      note,
      createdAt: new Date().toISOString(),
      ...ctx,
    };
    comments.push(stampAuthor(comment));
    if (!applyWidgetHighlight(comment)) {
      showToast("Comment saved, but the widget part could not be highlighted.");
    }
  } else if (el._mode === "new-document") {
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const comment = {
      id,
      anchorType: "document",
      quote: "(document-wide)",
      note,
      createdAt: new Date().toISOString(),
      section: null,
      headingPath: [],
    };
    comments.push(stampAuthor(comment));
  } else if (el._mode === "new-slide") {
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const s = el._slide || {};
    const comment = {
      id,
      anchorType: "slide",
      slideId: s.slideId || null,
      slideTitle: s.slideTitle || "",
      slideIndex: (typeof s.slideIndex === "number") ? s.slideIndex : -1,
      quote: "(comment on slide)",
      note,
      createdAt: new Date().toISOString(),
      section: null,
      headingPath: [],
    };
    comments.push(stampAuthor(comment));
  } else {
    // Convert the composing preview into the real highlight. First confirm the stored
    // offsets still anchor while the preview is up, so a failed re-anchor leaves the preview
    // (and its anchor cue) intact rather than stripping it from a still-open composer. Then
    // drop the preview marks so wrapRangeWithMark re-wraps the original text with the
    // comment's cid rather than nesting inside a preview mark.
    if (!rangeFromOffsets(el._start, el._end)) {
      showToast("Could not re-anchor that selection (the text may have changed). Try again.");
      return;
    }
    // Reject a selection that overlaps an existing text highlight while the preview is still up (so
    // the still-open composer keeps its anchor cue): wrapping it would nest a mark.cm-hl inside
    // another and make the outer highlight unclickable (CMH-CORE-11). The check derives each
    // highlight's LIVE interval from a text-node walk, so it is correct even when stored offsets are
    // stale (e.g. a multi-row highlight left discontiguous by a table sort). Editing the same range
    // reopens the existing comment (CMH-CORE-10, the _editingId branch above), so this only fires
    // for a genuinely new overlapping selection.
    if (rangeOverlapsHighlight(el._start, el._end)) {
      showToast("Could not highlight that range (it may overlap an existing comment). Comment was not saved.");
      return;
    }
    clearComposerPreview(el);
    const r = rangeFromOffsets(el._start, el._end);
    if (!r) {
      // Unreachable in practice (the preflight above just resolved it and unwrapping the
      // preview does not change character offsets); guard defensively without a no-op re-apply.
      showToast("Could not re-anchor that selection (the text may have changed). Try again.");
      return;
    }
    const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const ctx = captureContext(el._start, el._end, r);
    const comment = {
      id, quote: el._quote, note,
      start: el._start, end: el._end,
      createdAt: new Date().toISOString(),
      ...ctx,
    };
    comments.push(stampAuthor(comment));
    try {
      wrapRangeWithMark(r, id);
    } catch (e) {
      comments.pop();
      // Roll back any partial mark.cm-hl the wrap created before throwing, so the failed
      // save leaves no orphan highlight and the re-applied preview does not nest over one.
      unwrapMarks(id);
      showToast("Could not highlight that range (it may overlap an existing comment). Comment was not saved.");
      applyComposerPreview(el);
      return;
    }
    window.getSelection().removeAllRanges();
  }
  saveComments();
  renderComments();
  closeComposerElement(el);
  openSidebar();
}


