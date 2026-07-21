/* ---------- Export to Markdown (deterministic content -> Markdown) ----------
   Walks #commentRoot structure (never rendered layout) and maps each block kind to one
   fixed Markdown construct, so the output is byte-stable and idempotent. cm-skip subtrees
   are excluded EXCEPT a mermaid <pre> (its source is content) and a diff host (its raw
   source is recovered). Sortable tables emit in original row order. */
const _MD_SKIP_TAGS = { SCRIPT: 1, STYLE: 1, NAV: 1, NOSCRIPT: 1, TEMPLATE: 1 };
const _MD_ALERT = { info: "NOTE", success: "TIP", warning: "WARNING", danger: "CAUTION" };
function _mdCollapse(s) { return String(s == null ? "" : s).replace(/\s+/g, " ").trim(); }
function _mdSkip(el) {
  if (!el || el.nodeType !== 1) return false;
  if (_MD_SKIP_TAGS[el.tagName]) return true;
  // A mermaid host (pre.mermaid or div.mermaid) and a diff host carry content we export
  // from a stashed source, so they are never skipped even though they are cm-skip.
  if (el.classList && el.classList.contains("mermaid")) return false;
  if (el.classList && el.classList.contains("cmh-diff-host")) return false;
  if (el.hasAttribute && el.hasAttribute("data-cm-widget")) return false;
  return !!(el.classList && (el.classList.contains("cm-skip") || el.classList.contains("cm-toc")));
}
function _mdDedent(text) {
  const arr = String(text).replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  while (arr.length && arr[0].trim() === "") arr.shift();
  while (arr.length && arr[arr.length - 1].trim() === "") arr.pop();
  let indent = null;
  arr.forEach((ln) => { if (!ln.trim()) return; const m = ln.match(/^[ \t]*/)[0].length; indent = indent === null ? m : Math.min(indent, m); });
  indent = indent || 0;
  return arr.map((ln) => ln.slice(indent)).join("\n");
}
function _mdFence(lang, text) {
  const body = _mdDedent(text);
  let maxRun = 0; const re = /`+/g; let m;
  while ((m = re.exec(body)) !== null) { if (m[0].length > maxRun) maxRun = m[0].length; }
  const bar = "`".repeat(Math.max(3, maxRun + 1));
  // Sanitize the info string: a backtick or space in a derived language class would void a
  // backtick fence (CommonMark forbids backticks in the info string), so keep it to a safe set.
  const info = String(lang == null ? "" : lang).replace(/[^A-Za-z0-9_.+-]/g, "");
  return bar + info + "\n" + body + "\n" + bar;
}
// Inline code span with a backtick run longer than any run inside the content (CommonMark
// requires the fence to exceed the longest inner run), padded with a space when the content
// starts or ends with a backtick. Newlines are collapsed so a code span stays one line.
function _mdInlineCode(text) {
  const s = String(text == null ? "" : text).replace(/\r?\n/g, " ");
  let maxRun = 0; const re = /`+/g; let m;
  while ((m = re.exec(s)) !== null) { if (m[0].length > maxRun) maxRun = m[0].length; }
  const ticks = "`".repeat(maxRun + 1);
  // Pad with a space when the content starts/ends with a backtick or space, so CommonMark's
  // one-space strip leaves the original content intact.
  const pad = (s === "" || /^[`\s]/.test(s) || /[`\s]$/.test(s)) ? " " : "";
  return ticks + pad + s + pad + ticks;
}
// Escape a raw attribute-derived label (image alt, appendix widget/part/node names) with the
// same set as text nodes, so a value like `<img onerror=...>` cannot become live HTML when the
// exported Markdown is rendered by an HTML-permissive renderer, and brackets/backslash cannot
// break the [..] syntax. (Anchor label text rides _mdText via _mdInlineText and is not passed here.)
function _mdLinkLabel(text) { return _mdText(text); }
// A link/image destination: strip control chars, and wrap in angle brackets (encoding any
// literal '<'/'>') when it contains characters that would otherwise break the (..) destination.
function _mdUrl(url) {
  const u = String(url == null ? "" : url).replace(/[\x00-\x1f\x7f]+/g, "").trim();
  // Neutralize executable schemes that have no legitimate use in an exported document; leave
  // http/https/mailto/tel and relative/anchor destinations untouched.
  if (/^(?:javascript|vbscript):/i.test(u)) return "about:blank";
  // Allow only image data URLs; a bare data: URL (data:text/html, data:application/..., etc.)
  // is an inline-payload vector with no place in exported prose, so drop it.
  if (/^data:/i.test(u) && !/^data:image\//i.test(u)) return "about:blank";
  if (/[()\s<>]/.test(u)) return "<" + u.replace(/</g, "%3C").replace(/>/g, "%3E") + ">";
  return u;
}
// Escape a plain text node so its characters cannot open a code span, link, or raw-HTML tag
// in the exported Markdown (block-leading triggers are handled by _mdEscapeLeading).
function _mdText(s) { return String(s == null ? "" : s).replace(/[\\`<\[\]*_~]/g, "\\$&"); }
// Escape GFM table-cell pipes without disturbing pipes that are already escaped (an odd run of
// preceding backslashes), so a code span like `a\|b` inside a table cell keeps its pipe escaped
// rather than forging a column boundary, and a backslash before a pipe cannot cancel the escape.
function _mdEscapePipes(s) { return String(s == null ? "" : s).replace(/(\\*)\|/g, function (m, bs) { return bs.length % 2 ? m : bs + "\\|"; }); }
// Escape a leading block trigger (heading, blockquote, list, ordered list, thematic break)
// so ordinary prose cannot forge document structure in the exported Markdown.
function _mdEscapeLeading(s) {
  // Setext heading underline: a line of only '=' or only '-' turns the preceding line into a
  // heading. This is reachable where raw newlines are preserved (comment notes); a bare '-' or
  // one/two dashes also slips past the 3+-run thematic-break check below.
  if (/^\s{0,3}=+\s*$/.test(s)) return s.replace(/=/, "\\=");
  if (/^\s{0,3}-+\s*$/.test(s)) return s.replace(/-/, "\\-");
  if (/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(s)) return s.replace(/(\\|[-*_])/g, "\\$1");
  return s.replace(/^(\s*)(#{1,6}(?=\s|$)|>|[-+*](?=\s)|\d+[.)](?=\s))/, function (mm, ws, tok) {
    if (/^\d/.test(tok)) return ws + tok.replace(/([.)])$/, "\\$1");
    return ws + "\\" + tok;
  });
}
function _mdInlineOne(ch) {
  if (ch.nodeType === 3) return _mdText(ch.nodeValue);
  if (ch.nodeType !== 1 || _mdSkip(ch)) return "";
  const t = ch.tagName;
  if (t === "STRONG" || t === "B") return "**" + _mdCollapse(_mdInlineText(ch)) + "**";
  if (t === "EM" || t === "I") return "*" + _mdCollapse(_mdInlineText(ch)) + "*";
  if (t === "CODE") return _mdInlineCode(ch.textContent || "");
  if (t === "A") return "[" + _mdCollapse(_mdInlineText(ch)) + "](" + _mdUrl(ch.getAttribute("href") || "") + ")";
  if (t === "IMG") return "![" + _mdLinkLabel(ch.getAttribute("alt") || "") + "](" + _mdUrl(ch.getAttribute("src") || "") + ")";
  if (t === "BR") return " ";
  if (t === "SPAN" && ch.classList.contains("badge")) return _mdInlineCode(ch.textContent || "");
  return _mdInlineText(ch);
}
// Append one child's inline serialization to acc, escaping a trailing "!" so an <a> that
// follows a literal "!" cannot forge image syntax.
function _mdAppendInline(acc, ch) {
  const piece = _mdInlineOne(ch);
  if (!piece) return acc;
  if (piece[0] === "[" && acc.slice(-1) === "!") acc = acc.slice(0, -1) + "\\!";
  return acc + piece;
}
function _mdInlineText(node) {
  let out = "";
  const kids = node.childNodes;
  for (let i = 0; i < kids.length; i++) {
    out = _mdAppendInline(out, kids[i]);
  }
  return out;
}
function _mdTableRows(el) {
  const cells = (tr, sel) => Array.prototype.map.call(tr.querySelectorAll(sel), (c) => _mdEscapePipes(_mdCollapse(_mdInlineText(c))));
  const head = el.querySelector("thead tr") || el.querySelector("tr");
  if (!head) return "";
  const headers = cells(head, "th,td");
  let bodyRows = Array.prototype.slice.call(el.querySelectorAll("tbody tr"));
  if (!bodyRows.length) bodyRows = Array.prototype.filter.call(el.querySelectorAll("tr"), (tr) => tr !== head);
  if (bodyRows.some((r) => r.dataset && r.dataset.cmhRow != null)) {
    bodyRows = bodyRows.slice().sort((a, b) => (parseInt(a.dataset.cmhRow, 10) || 0) - (parseInt(b.dataset.cmhRow, 10) || 0));
  }
  const rows = bodyRows.map((tr) => cells(tr, "td,th"));
  const out = [];
  out.push("| " + headers.join(" | ") + " |");
  out.push("| " + headers.map(() => "---").join(" | ") + " |");
  rows.forEach((r) => out.push("| " + r.join(" | ") + " |"));
  return out.join("\n");
}
function _mdFigure(el) {
  const cap = el.querySelector("figcaption");
  const caption = cap ? _mdCollapse(_mdInlineText(cap)) : "";
  if (el.classList.contains("cmh-kql")) {
    const code = el.querySelector("pre code, code");
    const run = el.querySelector("a.cmh-kql-run, a[href]");
    const parts = [];
    if (code) parts.push(_mdFence("kusto", code.textContent || ""));
    if (run && run.getAttribute("href")) parts.push("[Run in Azure Data Explorer](" + _mdUrl(run.getAttribute("href")) + ")");
    if (caption) parts.push("_" + caption + "_");
    return parts.join("\n\n");
  }
  const offlineChart = el.querySelector("img[data-cm-offline-chart]");
  if (offlineChart) {
    // Offline chart snapshots can carry large data: URLs; Markdown keeps only the human label.
    const label = caption || _mdCollapse(_mdText(offlineChart.getAttribute("alt") || "Chart snapshot"));
    return "_[Chart snapshot: " + label + "]_";
  }
  if (el.classList.contains("chart") || el.querySelector("canvas")) return "_[Chart: " + caption + "]_";
  const img = el.querySelector("img");
  if (img) {
    // The alt attribute is raw; when it is empty, fall back to the caption's raw text (not the
    // already-escaped `caption`) so _mdLinkLabel applies exactly one escape pass.
    const alt = img.getAttribute("alt") || (cap ? _mdCollapse(cap.textContent || "") : "");
    return "![" + _mdLinkLabel(alt) + "](" + _mdUrl(img.getAttribute("src") || "") + ")";
  }
  if (el.querySelector("svg")) return "_[Figure: " + caption + "]_";
  return caption ? "_[Figure: " + caption + "]_" : _mdChildren(el);
}
function _mdList(el, indent) {
  const ordered = el.tagName === "OL";
  const out = [];
  let n = 0;
  const BLOCK = /^(P|PRE|BLOCKQUOTE|TABLE|FIGURE|H[1-6]|DIV|SECTION)$/;
  Array.prototype.forEach.call(el.children, (li) => {
    if (li.tagName !== "LI") return;
    n++;
    const marker = ordered ? n + ". " : "- ";
    const cont = indent + " ".repeat(marker.length);   // continuation indent = marker width
    const segs = [];   // ordered runs: {t:"inline"|"block", v} in DOM order
    let inline = "";
    const flush = () => { const c = _mdCollapse(inline); inline = ""; if (c) segs.push({ t: "inline", v: c }); };
    Array.prototype.forEach.call(li.childNodes, (ch) => {
      if (ch.nodeType === 1 && (ch.tagName === "UL" || ch.tagName === "OL")) { flush(); segs.push({ t: "block", v: _mdList(ch, cont) }); }
      else if (ch.nodeType === 1 && BLOCK.test(ch.tagName) && !_mdSkip(ch)) {
        flush();
        const md = _mdBlock(ch);
        if (md && md.trim()) segs.push({ t: "block", v: md.split("\n").map((l) => cont + l).join("\n") });
      } else if (ch.nodeType === 3) inline = _mdAppendInline(inline, ch);
      else if (ch.nodeType === 1 && !_mdSkip(ch)) inline = _mdAppendInline(inline, ch);
    });
    flush();
    const lines = [];
    if (!segs.length) { lines.push(indent + marker.replace(/\s+$/, "")); }
    segs.forEach((s, i) => {
      if (i === 0) {
        if (s.t === "inline") lines.push(indent + marker + _mdEscapeLeading(s.v));
        else { lines.push(indent + marker.replace(/\s+$/, "")); lines.push(s.v); }
      } else {
        lines.push(s.t === "inline" ? cont + _mdEscapeLeading(s.v) : s.v);
      }
    });
    out.push(lines.join("\n"));
  });
  return out.join("\n");
}
function _mdCallout(el) {
  let variant = "";
  el.classList.forEach((c) => { const m = c.match(/^cmh-callout-(info|success|warning|danger)$/); if (m) variant = m[1]; });
  const out = [];
  if (variant) out.push("> [!" + _MD_ALERT[variant] + "]");
  out.push("> " + _mdEscapeLeading(_mdCollapse(_mdInlineText(el))));
  return out.join("\n");
}
function _mdDiff(el) {
  const src = el.querySelector("script.cmh-diff-src");
  let raw = "";
  if (src) {
    try { raw = src.getAttribute("data-enc") === "base64" ? _b64DecodeUtf8(src.textContent) : (src.textContent || ""); }
    catch (e) { raw = ""; }
  }
  if (!raw) {
    // Never silently drop content: fall back to the rendered diff text, but strip the
    // encoded source <script> first so its base64 payload is not exported.
    const clone = el.cloneNode(true);
    Array.prototype.forEach.call(clone.querySelectorAll("script"), (s) => s.remove());
    raw = (clone.textContent || "").replace(/\u00a0/g, " ").replace(/[ \t]+$/gm, "").trim();
    if (raw) { try { console.warn("commentable-html: diff source unavailable; exported rendered text"); } catch (e) { /* no-op */ } }
  }
  return _mdFence("diff", raw || "");
}
function _mdPartLabel(el) {
  return _mdEscapePipes(_mdCollapse(_mdText(el.getAttribute("data-cm-part-label") || el.textContent || "")));
}
function _mdWidget(el) {
  const title = _mdCollapse(_mdText(el.getAttribute("aria-label") || el.getAttribute("data-cm-widget") || "Widget"));
  const slots = Array.prototype.filter.call(el.querySelectorAll("[data-cm-slot]"), (slot) =>
    slot.closest("[data-cm-widget]") === el);
  if (slots.length) {
    const headers = slots.map((slot) =>
      _mdEscapePipes(_mdCollapse(_mdText(slot.getAttribute("data-cm-slot") || slot.getAttribute("aria-label") || "Slot"))));
    const columns = slots.map((slot) =>
      Array.prototype.filter.call(slot.querySelectorAll("[data-cm-part]"), (part) =>
        part !== slot && part.closest("[data-cm-widget]") === el && part.closest("[data-cm-slot]") === slot)
        .map(_mdPartLabel));
    const rows = [];
    const height = Math.max.apply(null, columns.map((col) => col.length).concat([0]));
    rows.push("| " + headers.join(" | ") + " |");
    rows.push("| " + headers.map(() => "---").join(" | ") + " |");
    for (let r = 0; r < height; r++) {
      rows.push("| " + columns.map((col) => col[r] || "").join(" | ") + " |");
    }
    return "_[Widget: " + title + "]_\n\n" + rows.join("\n");
  }
  const parts = Array.prototype.filter.call(el.querySelectorAll("[data-cm-part]"), (part) =>
    part.closest("[data-cm-widget]") === el).map((part) => "- " + _mdPartLabel(part));
  return parts.length ? "_[Widget: " + title + "]_\n\n" + parts.join("\n") : "";
}
function _mdBlock(el) {
  const t = el.tagName;
  if (el.classList && el.classList.contains("mermaid")) return _mdFence("mermaid", el.getAttribute("data-cmh-md-src") || el.textContent || "");
  if (el.hasAttribute && el.hasAttribute("data-cm-widget")) return _mdWidget(el);
  if (/^H[1-6]$/.test(t)) return "#".repeat(+t[1]) + " " + _mdCollapse(_mdInlineText(el));
  if (t === "P") return _mdEscapeLeading(_mdCollapse(_mdInlineText(el)));
  if (t === "UL" || t === "OL") return _mdList(el, "");
  if (t === "TABLE") return _mdTableRows(el);
  if (t === "FIGURE") return _mdFigure(el);
  if (t === "IMG") return "![" + _mdLinkLabel(el.getAttribute("alt") || "") + "](" + _mdUrl(el.getAttribute("src") || "") + ")";
  if (el.classList && el.classList.contains("cmh-diff-host")) return _mdDiff(el);
  if (t === "PRE") {
    const code = el.querySelector("code");
    let lang = "";
    (((code || el).className) || "").split(/\s+/).forEach((c) => { const m = c.match(/^language-(.+)$/); if (m) lang = m[1]; });
    return _mdFence(lang, (code || el).textContent || "");
  }
  if (t === "BLOCKQUOTE") return "> " + _mdEscapeLeading(_mdCollapse(_mdInlineText(el)));
  if (el.classList && el.classList.contains("cmh-callout")) return _mdCallout(el);
  return _mdChildren(el);
}
function _mdChildren(el) {
  const out = [];
  Array.prototype.forEach.call(el.childNodes, (ch) => {
    if (ch.nodeType === 3) {
      // Direct text under a container (div/section/#commentRoot) is escaped like any prose,
      // so a bare "# x" or link/HTML syntax cannot forge structure in the export.
      const t = _mdEscapeLeading(_mdCollapse(_mdText(ch.nodeValue)));
      if (t) out.push(t);
      return;
    }
    if (ch.nodeType !== 1 || _mdSkip(ch)) return;
    const md = _mdBlock(ch);
    if (md && md.trim()) out.push(md);
  });
  return out.join("\n\n");
}
function htmlToMarkdown(rootEl) {
  if (!rootEl) return "";
  return _mdChildren(rootEl).replace(/\n{3,}/g, "\n\n").trim() + "\n";
}
function _mdCommentsAppendix() {
  const live = withoutHandled(comments);
  const roots = (typeof threadRoots === "function") ? threadRoots(live) : live;
  if (!roots.length) return "";
  const oneLine = (s) => String(s == null ? "" : s).replace(/\s+/g, " ").trim();
  const esc = (s) => _mdLinkLabel(oneLine(s));   // bracket/backslash-escape so a crafted label cannot inject a link into the heading
  const _mdNoteLines = (note) => {
    // Normalize the Unicode line/paragraph separators to a real newline BEFORE splitting so each
    // becomes its own escaped + blockquoted line - otherwise a note like "safe\u2028# forged" could
    // render its second half as a heading OUTSIDE the blockquote for a consumer that honors U+2028.
    String(note == null ? "" : note).replace(/[\u0085\u2028\u2029]/g, "\n").split(/\r?\n/).forEach((ln) => {
      const e = _mdEscapePipes(_mdEscapeLeading(_mdText(ln)));
      out.push(e.trim() ? "> " + e : ">");
    });
  };
  const _mdBy = (c) => (c && c.author) ? (" - by " + esc(c.author)) : "";
  const out = ["## Review comments (" + roots.length + ")"];
  roots.forEach((c, i) => {
    let where = "";
    if (c.anchorType === "document") where = "document-wide";
    else if (c.anchorType === "slide") where = 'slide "' + esc(c.slideTitle || c.slideId || "") + '"';
    else if (c.anchorType === "widget") where = 'widget "' + esc(c.widget) + '" / ' + esc(c.partLabel || c.part);
    else if (c.anchorType === "mermaid") where = "mermaid " + esc(c.nodeLabel || c.nodeKey);
    else if (c.anchorType === "diff") where = "diff line";
    else if (c.anchorType === "image") where = (c.imageKind === "chart" ? "chart" : "image") + " " + ((c.imageIndex || 0) + 1);
    else if (c.anchorType === "link") where = "link " + ((Number(c.linkIndex) || 0) + 1);
    else if (c.quote) where = '"' + esc(oneLine(c.quote).slice(0, 80)) + '"';
    out.push("");
    out.push("### " + (i + 1) + ". " + (oneLine(where) || "comment") + _mdBy(c));
    out.push("");
    // Escape each preserved note line like prose (raw HTML, inline markup, leading structural
    // markers including setext underlines) and neutralize pipes so a multi-line note cannot
    // forge a GFM table either.
    _mdNoteLines(c.note);
    const replies = (typeof repliesOf === "function") ? repliesOf(c.id, live) : [];
    replies.forEach((r, k) => {
      out.push("");
      out.push("_Reply " + (k + 1) + _mdBy(r) + ":_");
      _mdNoteLines(r.note);
    });
  });
  return out.join("\n") + "\n";
}
function buildMarkdownDoc() {
  let md = htmlToMarkdown(root);
  const appendix = _mdCommentsAppendix();
  if (appendix) md += "\n" + appendix;
  return md;
}
function _downloadTextFile(text, filename, mime) {
  const blob = new Blob([text], { type: (mime || "text/plain") + ";charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => { try { URL.revokeObjectURL(url); } catch (e) {} }, 1000);
}
function _mdFilename() {
  let stem = "document";
  try {
    const p = (DOC_SOURCE || location.pathname || "document").split(/[\\/]/).pop() || "document";
    stem = p.replace(/\.[^.]+$/, "") || "document";
  } catch (e) { /* keep default */ }
  return stem + ".md";
}
async function exportMarkdown() {
  const md = buildMarkdownDoc();
  const filename = _mdFilename();
  _downloadTextFile(md, filename, "text/markdown");
  showToast(`Markdown downloaded as ${filename}.`);
}
["btnExportMd", "btnExportMdTop"].forEach((id) => {
  const b = document.getElementById(id);
  if (b) b.addEventListener("click", exportMarkdown);
});
// Exposed for deterministic tests and programmatic use.
window.__cmhToMarkdown = function () { return buildMarkdownDoc(); };

// Copy arbitrary text to the clipboard (navigator.clipboard with an execCommand
// fallback), then show a toast. Returns a promise. Used by the per-code-block Copy
// button and the Kusto cluster-name copy affordance.
async function copyPlain(text, toastMsg) {
  let copied = false;
  try { await navigator.clipboard.writeText(text); copied = true; }
  catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.left = "-9999px";
    document.body.appendChild(ta); ta.select();
    try { copied = document.execCommand("copy"); } catch (err) { copied = false; }
    document.body.removeChild(ta);
  }
  showToast(copied ? (toastMsg || "Copied to clipboard.") : "Copy failed.");
  return copied;
}

// A persistent per-code-block Copy button. Each commentable code block is wrapped in a
// position:relative .cmh-code-wrap and gets an always-visible cm-skip Copy button in the
// top-right (so it never moves on hover and is excluded from the text-offset system).
function isCommentableCodeBlock(pre) {
  return pre && pre.tagName === "PRE" && root.contains(pre)
    && !pre.classList.contains("mermaid") && !pre.classList.contains("cmh-diff")
    && !pre.closest(".cm-skip")
    && !pre.closest(".cmh-diff") && !pre.closest(".cmh-diff-host");
}
var _CODE_LANG_LABELS = {
  python: "Python", py: "Python", javascript: "JavaScript", js: "JavaScript",
  typescript: "TypeScript", ts: "TypeScript", csharp: "C#", cs: "C#", json: "JSON",
  bash: "Bash", sh: "Bash", shell: "Bash", sql: "SQL", go: "Go", golang: "Go",
  yaml: "YAML", yml: "YAML", kql: "KQL", kusto: "KQL", html: "HTML", xml: "XML",
  css: "CSS", java: "Java", cpp: "C++", c: "C", rust: "Rust", rs: "Rust",
  ruby: "Ruby", rb: "Ruby", php: "PHP", diff: "Diff", text: "Text", plaintext: "Text",
};
function _codeLangLabel(lang) {
  if (!lang) return "";
  var k = String(lang).toLowerCase();
  if (_CODE_LANG_LABELS[k]) return _CODE_LANG_LABELS[k];
  return k.charAt(0).toUpperCase() + k.slice(1);
}
function setupCodeCopy() {
  root.querySelectorAll("pre").forEach(function (pre) {
    if (!isCommentableCodeBlock(pre)) return;
    if (pre.parentElement && pre.parentElement.classList.contains("cmh-code-wrap")) return;
    const wrap = document.createElement("div");
    wrap.className = "cmh-code-wrap";
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    // Optional author caption/filename line (data-code-caption on the <pre>): a cm-skip bar
    // above the code, so it names the block's source without entering selection, text
    // offsets, or the copy payload. Reopen is idempotent (a wrapped <pre> returns early
    // above), so the caption is not duplicated on an exported file (exports serialize the
    // pristine document, so the caption re-renders from the surviving attribute). A KQL
    // figure already carries its own caption bar (.cmh-kql-cap), so it never gets a second.
    const captionText = (pre.getAttribute("data-code-caption") || "").trim();
    let caption = null;
    if (captionText && !pre.closest("figure.cmh-kql")) {
      caption = document.createElement("div");
      caption.className = "cmh-code-caption cm-skip";
      const captionLabel = document.createElement("span");
      captionLabel.className = "cmh-code-caption-text";
      captionLabel.textContent = captionText;
      captionLabel.title = captionText;
      caption.appendChild(captionLabel);
      wrap.classList.add("cmh-has-caption");
      wrap.insertBefore(caption, pre);
    }
    const tools = document.createElement("div");
    tools.className = "cm-code-tools cm-skip";
    // A small language pill (Python, C#, KQL, ...) sits next to the Copy button.
    const codeEl = pre.querySelector("code");
    const lm = /(?:^|\s)language-([\w#+.-]+)/i.exec(codeEl ? (codeEl.className || "") : "");
    const label = lm ? _codeLangLabel(lm[1]) : "";
    if (label) {
      const pill = document.createElement("span");
      pill.className = "cm-code-lang";
      pill.textContent = label;
      pill.title = label + " code block";
      tools.appendChild(pill);
    }
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "cm-code-copy cm-skip";
    btn.textContent = "Copy";
    btn.title = "Copy this code block to the clipboard";
    btn.addEventListener("click", function () {
      const code = pre.querySelector("code") || pre;
      copyPlain(code.textContent.replace(/\n$/, ""), "Code copied to clipboard.");
    });
    tools.appendChild(btn);
    // With a caption, the pill + Copy live INSIDE the caption bar as flex items (like the KQL
    // caption's Run link), so they never overlap the filename for any language-label width;
    // otherwise they float over the code block's top-right corner as before.
    (caption || wrap).appendChild(tools);
  });
}

// Generic click-to-copy affordance: any element carrying data-cmh-copy copies that
// value to the clipboard and shows a toast. Used by the Kusto cluster-name title.
root.addEventListener("click", function (e) {
  const el = e.target.closest("[data-cmh-copy]");
  if (!el || !root.contains(el)) return;
  e.preventDefault();
  copyPlain(el.getAttribute("data-cmh-copy") || el.textContent, "Cluster copied to clipboard.");
});

