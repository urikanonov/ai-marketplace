/* ---------- Context capture (section + surrounding text) ---------- */
const CTX_PAD = 80;
const BLOCK_TAG_RE = /^(P|LI|TD|TH|H[1-6]|BLOCKQUOTE|PRE|DD|DT|FIGCAPTION|CAPTION|ARTICLE|SECTION|ASIDE)$/;
const MAX_BLOCK_LEN = 280;
function captureContext(start, end, range) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
    acceptNode(n) {
      if (n.nodeType === 1) {
        if (n.closest(".cm-skip")) return NodeFilter.FILTER_REJECT;
        return /^H[1-6]$/i.test(n.tagName) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
      }
      if (n.parentElement && n.parentElement.closest(".cm-skip")) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  let total = 0, full = "";
  const headings = [];
  let n;
  while ((n = walker.nextNode())) {
    if (n.nodeType === 1) {
      headings.push({
        offset: total,
        level: parseInt(n.tagName.slice(1), 10),
        text: n.textContent.trim().replace(/\s+/g, " "),
      });
      continue;
    }
    full += n.nodeValue;
    total += n.nodeValue.length;
  }
  const beforeRaw = full.slice(Math.max(0, start - CTX_PAD), start);
  const afterRaw  = full.slice(end, Math.min(full.length, end + CTX_PAD));
  const before = (start > CTX_PAD ? "..." : "") + beforeRaw.replace(/\s+/g, " ").trimStart();
  const after  = afterRaw.replace(/\s+/g, " ").trimEnd() + (end + CTX_PAD < full.length ? "..." : "");

  const headingPath = [];
  let curOffset = 0;
  for (const h of headings) {
    if (h.offset > start) break;
    while (headingPath.length && headingPath[headingPath.length - 1].level >= h.level) headingPath.pop();
    headingPath.push(h);
    curOffset = h.offset;
  }
  const section = headingPath.length ? headingPath[headingPath.length - 1].text : null;
  const curLevel = headingPath.length ? headingPath[headingPath.length - 1].level : 0;
  let sectionEnd = full.length;
  for (const h of headings) {
    if (h.offset <= curOffset) continue;
    if (h.level <= curLevel) { sectionEnd = h.offset; break; }
  }
  const quote = full.slice(start, end);
  let occurrence = 0, occurrenceTotal = 0;
  if (quote.length > 0) {
    const sectionText = full.slice(curOffset, sectionEnd);
    const localStart = start - curOffset;
    let idx = 0;
    while ((idx = sectionText.indexOf(quote, idx)) !== -1) {
      occurrenceTotal++;
      if (idx <= localStart) occurrence++;
      idx += Math.max(1, quote.length);
    }
  }
  let blockTag = null, blockText = null, isCode = false, codeLanguage = null;
  if (range) {
    let el = range.startContainer;
    if (el && el.nodeType !== 1) el = el.parentElement;
    // Treat the selection as "code" only when it is inside a <pre> block (optionally
    // wrapping an inner <code>). Inline <code> in prose must NOT flip isCode, otherwise
    // we lose prose context (In context / Containing <p>) and emit a fenced code block
    // for a normal sentence that just happened to mention `foo`.
    const preAnc = el ? el.closest("pre") : null;
    if (preAnc) {
      isCode = true;
      const inlineCodeEl = el ? el.closest("code") : null;
      const codeEl = (inlineCodeEl && preAnc.contains(inlineCodeEl))
        ? inlineCodeEl
        : preAnc.querySelector("code");
      if (codeEl) {
        for (const cls of codeEl.classList) {
          const m = /^language-(.+)$/i.exec(cls);
          if (m) { codeLanguage = m[1].toLowerCase(); break; }
        }
      }
    }
    while (el && el !== root && !BLOCK_TAG_RE.test(el.tagName)) el = el.parentElement;
    if (el && el !== root) {
      blockTag = el.tagName.toLowerCase();
      const raw = (el.textContent || "").trim().replace(/\s+/g, " ");
      blockText = raw.length > MAX_BLOCK_LEN ? raw.slice(0, MAX_BLOCK_LEN) + "..." : raw;
    }
  }
  return {
    section,
    headingPath: headingPath.map(h => ({ level: h.level, text: h.text })),
    before, after,
    occurrence, occurrenceTotal,
    blockTag, blockText,
    isCode, codeLanguage,
  };
}
function backfillContext() {
  let changed = false;
  for (const c of comments) {
    const hasAll = c.section !== undefined && c.before !== undefined && c.after !== undefined &&
                   c.headingPath !== undefined && c.occurrence !== undefined && c.blockTag !== undefined &&
                   c.isCode !== undefined;
    if (hasAll) continue;
    if (typeof c.start !== "number" || typeof c.end !== "number") continue;
    const range = rangeFromOffsets(c.start, c.end);
    const ctx = captureContext(c.start, c.end, range);
    Object.assign(c, ctx);
    changed = true;
  }
  if (changed) saveComments();
}
function wrapRangeWithMark(range, id) {
  const nodes = getTextNodes();
  const toWrap = nodes.filter(n => range.intersectsNode(n));
  toWrap.forEach(tn => {
    let s = 0, e = tn.nodeValue.length;
    if (tn === range.startContainer) s = range.startOffset;
    if (tn === range.endContainer)   e = range.endOffset;
    if (s >= e) return;
    if (e < tn.nodeValue.length) tn.splitText(e);
    let target = tn;
    if (s > 0) target = tn.splitText(s);
    const m = document.createElement("mark");
    m.className = "cm-hl";
    if (!(target.nodeValue || "").trim()) m.classList.add("cm-hl-gap");
    m.dataset.cid = id;
    target.parentNode.insertBefore(m, target);
    m.appendChild(target);
  });
}
function unwrapMarks(id) {
  root.querySelectorAll(`mark.cm-hl[data-cid="${id}"]`).forEach(m => {
    const parent = m.parentNode;
    while (m.firstChild) parent.insertBefore(m.firstChild, m);
    parent.removeChild(m);
    parent.normalize();
  });
}
function removeHighlight(comment) {
  if (!comment) return;
  if (comment.anchorType === "mermaid") clearMermaidHighlight(comment.id);
  else if (comment.anchorType === "diff") clearDiffHighlight(comment.id);
  else if (comment.anchorType === "image") clearImageHighlight(comment.id);
  else if (comment.anchorType === "widget") clearWidgetHighlight(comment.id);
  else if (comment.anchorType === "document") { /* no anchored highlight to remove */ }
  else unwrapMarks(comment.id);
}
