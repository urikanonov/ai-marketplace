/* ---------- Sidebar rendering ---------- */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
function formatTime(iso) {
  try {
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
  const a = document.getElementById("btnSortAsc"), d = document.getElementById("btnSortDesc");
  if (a) a.setAttribute("aria-pressed", commentSort === "time-asc" ? "true" : "false");
  if (d) d.setAttribute("aria-pressed", commentSort === "time-desc" ? "true" : "false");
}
function renderComments() {
  toolbarCount.textContent = comments.length;
  sidebarCount.textContent = comments.length;
  if (typeof updateDocTypeUi === "function") updateDocTypeUi();
  updateSideInfo();
  updateSortUi();
  const stateChanges = (typeof widgetStateChanges === "function") ? widgetStateChanges() : [];
  const stateHtml = stateChanges.length ? _renderWidgetStateCard(stateChanges) : "";
  const clPieces = (typeof checklistCardPieces === "function") ? checklistCardPieces() : [];
  if (!comments.length && !stateChanges.length && !clPieces.length) {
    const deckHint = IS_DECK
      ? "<p><strong>On this deck:</strong> in comment mode, select text on the current slide and choose <em>Add Comment</em>, or right-click empty slide space for a whole-slide comment. Move between slides with Prev / Next or the arrow keys.</p>"
      : "";
    listEl.innerHTML = `
      <div class="cm-empty">
        <p><strong>No comments yet.</strong></p>
        ${deckHint}
        <p>Select any text in the document, then right-click and choose <em>Add Comment</em>. Mermaid nodes, diff lines, images, and widget parts: hover (or keyboard-focus) and click <em>Add Comment</em>. Right-click empty space for a document-wide comment. Comments stay here until the agent processes them. Click <kbd>Copy all</kbd> to send the bundle to the clipboard; the agent then marks them handled in this HTML file, and they are pruned automatically on the next reload.</p>
      </div>`;
    return;
  }
  const sortKey = (c) => (c.anchorType === "document")
    ? -1
    : (c.anchorType === "mermaid")
    ? (1e12 + (c.diagramIndex || 0) * 1000)
    : (c.anchorType === "diff")
    ? (2e12 + (c.diffIndex || 0) * 1e6 + (parseInt(c.lineKey, 10) || 0))
    : (c.anchorType === "image")
    ? (3e12 + (c.imageIndex || 0))
    : (c.anchorType === "widget")
    ? (4e12 + _widgetOrderKey(c))
    : (typeof c.start === "number" ? c.start : 0);
  const sorted = (commentSort === "time-asc")
    ? [...comments].sort((a, b) => (commentTimeValue(a) - commentTimeValue(b)) || (sortKey(a) - sortKey(b)))
    : (commentSort === "time-desc")
    ? [...comments].sort((a, b) => (commentTimeValue(b) - commentTimeValue(a)) || (sortKey(a) - sortKey(b)))
    : [...comments].sort((a, b) => sortKey(a) - sortKey(b));
  const commentHtml = sorted.map((c, i) => {
    const isMermaid = c.anchorType === "mermaid";
    const isDiff = c.anchorType === "diff";
    const isImage = c.anchorType === "image";
    const isWidget = c.anchorType === "widget";
    const isDocument = c.anchorType === "document";
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
    } else if (isWidget) {
      quoteHtml = `<div class="quote"><span class="ctx">${escapeHtml(c.widget || "widget")}: </span><span class="quoted">"${escapeHtml(c.partLabel || c.part || "")}"</span></div>`;
    } else if (isDocument) {
      quoteHtml = `<div class="quote"><span class="quoted">(document-wide comment)</span></div>`;
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
    } else if (isWidget) {
      pinBits.push(`widget "${escapeHtml(c.widget || "")}"`);
      pinBits.push(`part "${escapeHtml(c.partLabel || c.part || "")}"`);
    } else if (isDocument) {
      pinBits.push("document-wide");
    } else {
      if (c.isCode) {
        pinBits.push(c.codeLanguage ? `code (${escapeHtml(c.codeLanguage)})` : "code block");
      }
      // The prose pinpoint ("in <li> - match 2 of 4") is internal grep-help for the
      // agent; it is still emitted in the Copy bundle's Pinpoint line but is not shown
      // on the sidebar card, which only surfaces reader-facing anchor info.
    }
    const pinHtml = pinBits.length ? `<div class="pin">${pinBits.join(" - ")}</div>` : "";
    const jumpTarget = isMermaid ? "node" : isDiff ? "diff line" : isImage ? (c.imageKind === "chart" ? "chart" : "image") : isWidget ? "element" : "text";
    const cardClass = isDocument ? "cm-card cm-card-doc" : "cm-card";
    const jumpBtn = isDocument ? "" : `<button type="button" data-act="jump" title="Scroll to highlighted ${jumpTarget}">jump</button>`;
    return `
    <article class="${cardClass}" data-cid="${c.id}">
      ${sectionHtml}
      ${quoteHtml}
      ${pinHtml}
      <div class="note">${escapeHtml(c.note)}</div>
      <div class="meta">
        <span>#${i + 1} - ${escapeHtml(formatTime(c.updatedAt || c.createdAt))}${c.updatedAt ? " (edited)" : ""}</span>
        <span class="acts">
          ${jumpBtn}
          <button type="button" data-act="edit" title="Edit comment">edit</button>
          <button type="button" class="del" data-act="del" title="Delete comment">delete</button>
        </span>
      </div>
    </article>`;
  });
  const commentPieces = commentHtml.map((html, i) => ({ pos: sortKey(sorted[i]), html }));
  // Insert each checklist card by document position while preserving the comments' current
  // (position or time) sort order, so a time sort is not overridden and no card is dropped.
  const cls = clPieces.slice().sort((a, b) => a.pos - b.pos);
  const parts = [];
  let ci = 0;
  commentPieces.forEach((cp) => {
    while (ci < cls.length && cls[ci].pos <= cp.pos) parts.push(cls[ci++].html);
    parts.push(cp.html);
  });
  while (ci < cls.length) parts.push(cls[ci++].html);
  listEl.innerHTML = stateHtml + parts.join("");
}
function _widgetOrderKey(c) {
  const o = _widgetOrder.get(partKey(c.widget, c.part));
  return o == null ? 1e9 : o;
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
  el.scrollIntoView({ behavior: "smooth", block: "center" });
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
  const timeHtml = first ? escapeHtml(formatTime(first)) : "";
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
      <div class="note">Auto-tracked from the current layout. Included in Copy all so the agent can reformat the source; the file stays Not portable until re-exported.</div>
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
  else if (c.anchorType === "image") el = findImageEl(c.imageIndex);
  else if (c.anchorType === "widget") el = findWidgetPart(c.widget, c.part);
  else if (c.anchorType === "document") {
    // On a fixed-stage deck, window.scrollTo is a no-op; jump to the first slide (the natural
    // document start) so a document-wide comment card does not strand the presenter.
    if (window.__cmhDeck) window.__cmhDeck.showSlide(0);
    else window.scrollTo({ top: 0, behavior: "smooth" });
    flashActive(c.id);
    return;
  }
  else el = root.querySelector(`mark.cm-hl[data-cid="${c.id}"]`);
  if (el) { expandCollapsedAncestors(el); el.scrollIntoView({ behavior: "smooth", block: "center" }); flashActive(c.id); }
}
// A comment can live inside a collapsed section (display:none = no layout box), so
// expand every collapsed ancestor section before scrolling to it.
function expandCollapsedAncestors(el) {
  let sec = el && el.closest && el.closest("section.cmh-section-collapsed");
  while (sec) {
    sec.classList.remove("cmh-section-collapsed");
    const caret = sec.querySelector(":scope > .cmh-section-heading .cmh-sec-caret");
    if (caret) { caret.setAttribute("aria-expanded", "true"); caret.title = "Collapse section"; }
    sec = sec.parentElement && sec.parentElement.closest && sec.parentElement.closest("section.cmh-section-collapsed");
  }
}
listEl.addEventListener("click", (e) => {
  // Checklist change cards are not comments: jump focuses the checklist, Reset reverts it to
  // the authored state. Handle before the .cm-card comment path (a checklist card is a .cm-card).
  const clCard = e.target.closest(".cm-card-checklist");
  if (clCard) {
    const cid = e.target.getAttribute("data-cmh-checklist-name") || clCard.getAttribute("data-cmh-checklist-name");
    if (e.target.dataset.act === "cl-reset") { if (typeof resetChecklist === "function") resetChecklist(cid); }
    else if (typeof jumpToChecklist === "function") jumpToChecklist(cid);
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
  const id = card.dataset.cid;
  const act = e.target.dataset.act;
  if (act === "del") {
    const c = comments.find(x => x.id === id);
    scrollToAnchor(c);                       // jump to the anchor first, then confirm
    if (confirm("Delete this comment?")) {
      _tombstoneEmbedded([id]);
      comments = comments.filter(x => x.id !== id);
      removeHighlight(c);
      saveComments();
      renderComments();
    }
    return;
  }
  if (act === "edit") {
    const c = comments.find(c => c.id === id);
    if (c) { scrollToAnchor(c); openComposerForEdit(c); }   // jump first, then edit
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
  if (card) { card.scrollIntoView({ behavior: "smooth", block: "center" }); flashActive(id); }
});

