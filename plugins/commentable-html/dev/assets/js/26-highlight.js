/* ---------- Diff syntax highlighting (runtime, self-contained, default ON) ----------
   A compact tokenizer emitting the same .cmh-code-* classes as the author-time
   tools/highlight_code.py, applied to each diff line's code. Diff comments anchor
   structurally (diffIndex + lineKey + side), never by text offset, and the diff
   host is cm-skip, so wrapping tokens in spans is anchor-safe. Each line is
   highlighted independently (no cross-line block comments). A per-document toggle
   (default ON) is persisted. */
const CMH_DIFF_HL_KEY = COMMENT_KEY + "::diffSyntax";
let _diffSyntaxMem = null; // in-memory fallback when localStorage is unavailable
function diffSyntaxOn() {
  try {
    const v = localStorage.getItem(CMH_DIFF_HL_KEY);
    if (v !== null) return v !== "off";
  } catch (e) { /* storage blocked - use memory */ }
  return _diffSyntaxMem === null ? true : _diffSyntaxMem;
}
function setDiffSyntaxOn(on) {
  _diffSyntaxMem = !!on; // remember in-session even if storage throws
  try { localStorage.setItem(CMH_DIFF_HL_KEY, on ? "on" : "off"); } catch (e) { /* non-persistent */ }
}
const _HL_FAMILY = {
  javascript: "c", js: "c", jsx: "c", typescript: "c", ts: "c", tsx: "c", java: "c", c: "c", cpp: "c",
  "c++": "c", cs: "c", csharp: "c", go: "c", golang: "c", rust: "c", rs: "c", php: "c", swift: "c",
  kotlin: "c", kt: "c", scala: "c", dart: "c", json: "c", groovy: "c", objectivec: "c", objc: "c",
  python: "hash", py: "hash", ruby: "hash", rb: "hash", shell: "hash", bash: "hash", sh: "hash",
  yaml: "hash", yml: "hash", toml: "hash", perl: "hash", pl: "hash", r: "hash", elixir: "hash", ex: "hash", exs: "hash",
  sql: "sql",
  css: "css", lua: "lua", haskell: "haskell", hs: "haskell",
  powershell: "powershell", ps1: "powershell", ps: "powershell",
  batch: "batch", bat: "batch", cmd: "batch",
  html: "markup", xml: "markup",
};
const _EXT_LANG = {
  py: "python", js: "javascript", jsx: "javascript", mjs: "javascript", ts: "typescript", tsx: "typescript",
  java: "java", c: "c", h: "c", cpp: "cpp", cc: "cpp", hpp: "cpp", cs: "csharp", go: "go", rs: "rust",
  rb: "ruby", php: "php", swift: "swift", kt: "kotlin", scala: "scala", sql: "sql", sh: "shell",
  bash: "shell", yml: "yaml", yaml: "yaml", toml: "toml", json: "json", css: "css", lua: "lua",
  hs: "haskell", ex: "elixir", exs: "elixir", ps1: "powershell", bat: "batch", cmd: "batch",
  groovy: "groovy", gradle: "groovy", pl: "perl", r: "r", m: "objectivec", mm: "objectivec",
};
function inferDiffLang(el, label) {
  const explicit = (el.getAttribute("data-diff-lang") || "").trim().toLowerCase();
  if (explicit) return explicit;
  const m = /\.([A-Za-z0-9]+)\s*$/.exec(label || "");
  return m ? (_EXT_LANG[m[1].toLowerCase()] || "") : "";
}
function diffLangKnown(lang) { return !!(lang && _HL_FAMILY[String(lang).toLowerCase()]); }
const _HL_KW_SET = new Set(("abstract as async await base bool boolean break byte case catch char class const continue "
  + "def default defer del delete do double elif else enum event export extends final finally float fn for foreach from "
  + "func function global go goto if impl implements import in include instanceof int interface is lambda let long match "
  + "module mut namespace new nil none not null object or override package pass private protected public raise readonly "
  + "ref return self short static struct super switch synchronized template this throw throws trait try type typedef "
  + "typeof union unsafe use using var virtual void volatile when where while with yield true false and "
  + "cond defmacro defmodule defp defstruct deriving elseif newtype quote unquote receive rescue repeat until").split(" "));
// Markup (html/xml) tag/keyword set - mirrors the author-time highlighter's html+xml keyword lists
// (tools/blocks/highlight_code.py) so a runtime-highlighted markup block colors tag names the same
// way a baked one does, instead of using the C-family keyword set (where words like `class` collide).
const _HL_MARKUP_KW = new Set(("a article body button code div footer h1 h2 h3 head header html img "
  + "input label li link main meta nav ol option p pre script section select span style table tbody "
  + "td template textarea th thead title tr ul xml version encoding root item node element").split(" "));
const _hlCache = {};
function _hlTokenRe(fam) {
  if (_hlCache[fam]) { _hlCache[fam].lastIndex = 0; return _hlCache[fam]; }
  // Unrolled, linear-time string forms (a failed/unterminated match resolves in one pass instead of
  // rescanning from every later quote). Double/backtick may omit the closer (unterminated highlights
  // to end of line); the single-quote form REQUIRES its closer so a lone ' (Rust lifetime, apostrophe,
  // digit separator) is not swallowed as a string. Block comments fall back to end-of-line ($).
  const dq = "\"[^\"\\\\]*(?:\\\\[\\s\\S][^\"\\\\]*)*\"?";
  const sq = "'[^'\\\\]*(?:\\\\[\\s\\S][^'\\\\]*)*'";
  const bt = "`[^`\\\\]*(?:\\\\[\\s\\S][^`\\\\]*)*`?";
  let com, str, flags = "g";
  if (fam === "hash") { com = "#[^\\n]*"; str = dq + "|" + sq; }
  else if (fam === "sql") { com = "/\\*[\\s\\S]*?(?:\\*/|$)|--[^\\n]*"; str = "'[^']*(?:''[^']*)*'"; flags = "gi"; }
  else if (fam === "css") { com = "/\\*[\\s\\S]*?(?:\\*/|$)"; str = dq + "|" + sq; }
  else if (fam === "lua") { com = "--\\[\\[[\\s\\S]*?(?:\\]\\]|$)|--[^\\n]*"; str = dq + "|" + sq; }
  else if (fam === "haskell") { com = "\\{-[\\s\\S]*?(?:-\\}|$)|--[^\\n]*"; str = dq; }
  else if (fam === "powershell") { com = "<#[\\s\\S]*?(?:#>|$)|#[^\\n]*"; str = dq + "|" + sq; flags = "gi"; }
  else if (fam === "batch") { com = "(?:rem\\b|::)[^\\n]*"; str = dq; flags = "gi"; }
  else if (fam === "markup") { com = "<!--[\\s\\S]*?(?:-->|$)"; str = dq + "|" + sq; flags = "gi"; }
  else { com = "/\\*[\\s\\S]*?(?:\\*/|$)|//[^\\n]*"; str = dq + "|" + sq + "|" + bt; }
  const num = "0[xX][0-9a-fA-F]+|\\d[\\d_]*(?:\\.\\d+)?(?:[eE][+-]?\\d+)?";
  const id = "[A-Za-z_$][A-Za-z0-9_$]*";
  const op = "[+\\-*/%=<>!&|^~?:.,;(){}\\[\\]]";
  const re = new RegExp("(?<com>" + com + ")|(?<str>" + str + ")|(?<num>" + num + ")|(?<id>" + id + ")|(?<op>" + op + ")", flags);
  _hlCache[fam] = re;
  return re;
}
function cmhHighlightCode(text, lang) {
  const fam = _HL_FAMILY[String(lang || "").toLowerCase()] || "c";
  const re = _hlTokenRe(fam);
  let out = "", last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out += escapeHtml(text.slice(last, m.index));
    const t = m[0], g = m.groups;
    let cls = null;
    if (g.com) cls = "com";
    else if (g.str) cls = "str";
    else if (g.num) cls = "num";
    else if (g.id) cls = (fam === "markup" ? _HL_MARKUP_KW : _HL_KW_SET).has(re.ignoreCase ? t.toLowerCase() : t) ? "kw" : (text[re.lastIndex] === "(" ? "fn" : null);
    else if (g.op) cls = "op";
    out += cls ? ('<span class="cmh-code-' + cls + '">' + escapeHtml(t) + "</span>") : escapeHtml(t);
    last = re.lastIndex;
    if (m.index === re.lastIndex) re.lastIndex++;
  }
  if (last < text.length) out += escapeHtml(text.slice(last));
  return out;
}
function rerenderAllDiffs() {
  diffBlocks.forEach(b => { renderDiffBlock(b); applyDiffHighlightsForIndex(b.index); });
}

// Parse a unified diff into logical lines. Each carries a stable key (its index)
// so a comment keyed by (diffIndex, key) re-attaches regardless of layout.
function parseUnifiedDiff(src) {
  const out = [];
  let oldNo = 1, newNo = 1, k = 0, oldRem = 0, newRem = 0;
  const raw = String(src == null ? "" : src).replace(/\r\n?/g, "\n").split("\n");
  if (raw.length && raw[raw.length - 1] === "") raw.pop();
  const push = (type, text, o, n) => out.push({ key: String(k++), type: type, text: text, oldNo: o, newNo: n });
  // Unambiguous file-section headers. A real hunk BODY line always carries a
  // +/-/space prefix, so a line beginning at column 0 with one of these tokens
  // can only be a header (never a content line). `--- ` / `+++ ` are handled
  // separately because they collide with del/add prefixes INSIDE a hunk.
  const FILE_HDR = /^(diff |index |new file|deleted file|rename |copy |similarity |dissimilarity |old mode|new mode|Index: |={3,}$|Binary files )/;
  for (let i = 0; i < raw.length; i++) {
    const line = raw[i];
    if (/^@@ /.test(line)) {
      // The hunk header declares exactly how many old-side and new-side lines the
      // hunk contains. Tracking that budget is what makes `--- x` / `+++ x` body
      // lines unambiguous: inside a hunk they are del/add; only once the budget is
      // spent does a following `--- ` become the next file's header.
      const m = line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
      if (m) {
        oldNo = parseInt(m[1], 10); newNo = parseInt(m[3], 10);
        oldRem = m[2] == null ? 1 : parseInt(m[2], 10);
        newRem = m[4] == null ? 1 : parseInt(m[4], 10);
      } else { oldRem = 0; newRem = 0; }
      push("hunk", line, null, null);
      continue;
    }
    if (FILE_HDR.test(line)) { oldRem = 0; newRem = 0; push("file", line, null, null); continue; }
    const inHunk = oldRem > 0 || newRem > 0;
    if (!inHunk && (/^--- /.test(line) || /^\+\+\+ /.test(line))) {
      // Between hunks (or before the first one) `--- ` / `+++ ` are file headers.
      push("file", line, null, null);
      continue;
    }
    const c = line[0];
    if (c === "\\") { push("meta", line.slice(1).trim(), null, null); continue; }
    if (c === "+") { push("add", line.slice(1), null, newNo++); if (newRem > 0) newRem--; continue; }
    if (c === "-") { push("del", line.slice(1), oldNo++, null); if (oldRem > 0) oldRem--; continue; }
    push("ctx", c === " " ? line.slice(1) : line, oldNo++, newNo++);
    if (oldRem > 0) oldRem--;
    if (newRem > 0) newRem--;
  }
  return out;
}

function diffLineCommentable(ln) {
  return ln && (ln.type === "add" || ln.type === "del" || ln.type === "ctx");
}

// Build one rendered diff-line element for a logical line on a given side
// ("old" | "new" | "both"). data-line-key ties it back to the logical line.
function makeDiffLineEl(block, ln, side) {
  const row = document.createElement("div");
  row.className = "cmh-dl cmh-dl-" + ln.type;
  row.dataset.diffIndex = String(block.index);
  row.dataset.lineKey = ln.key;
  row.dataset.side = side;
  if (ln.type === "hunk" || ln.type === "file" || ln.type === "meta") {
    const code = document.createElement("span");
    code.className = "cmh-dl-code";
    code.textContent = ln.text;
    row.appendChild(code);
    row.classList.add("cmh-dl-full");
    return row;
  }
  const gutter = document.createElement("span");
  gutter.className = "cmh-dl-gutter";
  gutter.setAttribute("aria-hidden", "true");
  gutter.textContent = side === "old" ? (ln.oldNo == null ? "" : ln.oldNo)
    : side === "new" ? (ln.newNo == null ? "" : ln.newNo)
    : (ln.newNo != null ? ln.newNo : (ln.oldNo != null ? ln.oldNo : ""));
  const sign = document.createElement("span");
  sign.className = "cmh-dl-sign";
  sign.setAttribute("aria-hidden", "true");
  sign.textContent = ln.type === "add" ? "+" : ln.type === "del" ? "-" : " ";
  const code = document.createElement("span");
  code.className = "cmh-dl-code";
  if (ln.text.length && diffSyntaxOn() && diffLangKnown(block.lang)) {
    code.innerHTML = cmhHighlightCode(ln.text, block.lang);
  } else {
    code.textContent = ln.text.length ? ln.text : "\u00a0";
  }
  row.appendChild(gutter);
  row.appendChild(sign);
  row.appendChild(code);
  // Keyboard access: a changed/context line is focusable and Enter opens the
  // composer (see attachDiffHostHandlers), so commenting is not mouse-only.
  row.tabIndex = 0;
  row.setAttribute("role", "button");
  row.setAttribute("aria-label",
    (ln.type === "add" ? "Added" : ln.type === "del" ? "Removed" : "Context")
    + " line" + (ln.newNo != null ? " " + ln.newNo : ln.oldNo != null ? " " + ln.oldNo : "")
    + ": " + (ln.text || "") + ". Press Enter to comment.");
  return row;
}

function renderDiffInline(body, block) {
  const pane = document.createElement("div");
  pane.className = "cmh-diff-pane cmh-diff-pane-unified";
  block.lines.forEach(ln => pane.appendChild(makeDiffLineEl(block, ln, "both")));
  body.appendChild(pane);
}

// Side-by-side: deletions on the left, additions on the right, aligned by
// zipping each del/add run; context lines appear on both sides sharing one key.
// Rows are appended DIRECTLY into the 1fr-1fr grid body (old cell, then new cell)
// so each grid row stretches to the taller of its two cells - keeping the two
// columns aligned even when a long line wraps. Full-width rows span both columns.
function renderDiffSplit(body, block) {
  const spacer = (side) => {
    const s = document.createElement("div");
    s.className = "cmh-dl cmh-dl-spacer";
    s.dataset.side = side;
    s.setAttribute("aria-hidden", "true");
    return s;
  };
  const lines = block.lines;
  let i = 0;
  while (i < lines.length) {
    const ln = lines[i];
    if (ln.type === "hunk" || ln.type === "file" || ln.type === "meta") {
      body.appendChild(makeDiffLineEl(block, ln, "both")); // cmh-dl-full spans both cols
      i++; continue;
    }
    if (ln.type === "ctx") {
      body.appendChild(makeDiffLineEl(block, ln, "old"));
      body.appendChild(makeDiffLineEl(block, ln, "new"));
      i++; continue;
    }
    // Collect a contiguous del/add run, tolerating interspersed `\ No newline`
    // meta lines (git emits them between the -/+ lines at EOF) so the deletion and
    // addition still pair side by side; the meta lines render full-width below.
    const dels = [], adds = [], metas = [];
    while (i < lines.length && (lines[i].type === "del" || lines[i].type === "meta")) {
      (lines[i].type === "meta" ? metas : dels).push(lines[i]); i++;
    }
    while (i < lines.length && (lines[i].type === "add" || lines[i].type === "meta")) {
      (lines[i].type === "meta" ? metas : adds).push(lines[i]); i++;
    }
    if (!dels.length && !adds.length && !metas.length) { i++; continue; }
    const n = Math.max(dels.length, adds.length);
    for (let j = 0; j < n; j++) {
      body.appendChild(dels[j] ? makeDiffLineEl(block, dels[j], "old") : spacer("old"));
      body.appendChild(adds[j] ? makeDiffLineEl(block, adds[j], "new") : spacer("new"));
    }
    metas.forEach(m => body.appendChild(makeDiffLineEl(block, m, "both")));
  }
}

// Above this many logical lines, a diff renders as inert raw text (no per-line
// rows / commenting) so a pathologically large authored diff cannot freeze the
// page on open. The raw source is still preserved for export.
const CMH_DIFF_MAX_LINES = 2000;
// Bound the two per-code-block DOM allocations so a pathologically large authored code block cannot
// freeze the page on open (mirrors CMH_DIFF_MAX_LINES for diffs): above CMH_CODE_MAX_LINES lines the
// per-line gutter is skipped, and above CMH_CODE_MAX_CHARS characters the runtime highlighter leaves
// the block plain. The block's text is untouched either way, so it stays readable and commentable.
const CMH_CODE_MAX_LINES = 5000;
const CMH_CODE_MAX_CHARS = 200000;
function renderDiffRaw(body, block) {
  const notice = document.createElement("div");
  notice.className = "cmh-diff-toobig";
  notice.textContent = "Large diff (" + (block.rawLineCount || block.lines.length) + " lines) shown as raw text; "
    + "per-line commenting is disabled above " + CMH_DIFF_MAX_LINES + " lines.";
  const pre = document.createElement("pre");
  pre.className = "cmh-diff-raw";
  pre.textContent = block.rawSrc;
  body.appendChild(notice);
  body.appendChild(pre);
}

function renderDiffBlock(block) {
  const tooBig = !!block.tooBig;
  const layout = block.layout === "split" ? "split" : "inline";
  const view = document.createElement("div");
  view.className = "cmh-diff-view cmh-diff-" + (tooBig ? "raw" : layout);
  view.dataset.diffIndex = String(block.index);

  const bar = document.createElement("div");
  bar.className = "cmh-diff-bar";
  const label = document.createElement("span");
  label.className = "cmh-diff-label";
  label.textContent = block.label || "diff";
  bar.appendChild(label);
  let toggle = null;
  if (!tooBig) {
    toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "cmh-diff-toggle";
    toggle.textContent = layout === "split" ? "To inline view" : "To side-by-side view";
    toggle.title = "Switch between side-by-side and inline diff";
    bar.appendChild(toggle);
  }
  let hlToggle = null;
  if (!tooBig && diffLangKnown(block.lang)) {
    hlToggle = document.createElement("button");
    hlToggle.type = "button";
    hlToggle.className = "cmh-diff-hltoggle";
    const on = diffSyntaxOn();
    hlToggle.textContent = on ? "Syntax: on" : "Syntax: off";
    hlToggle.title = "Toggle syntax highlighting in diffs";
    hlToggle.setAttribute("aria-pressed", String(on));
    bar.appendChild(hlToggle);
  }
  view.appendChild(bar);

  const bodyEl = document.createElement("div");
  bodyEl.className = "cmh-diff-body";
  if (tooBig) renderDiffRaw(bodyEl, block);
  else if (layout === "split") renderDiffSplit(bodyEl, block);
  else renderDiffInline(bodyEl, block);
  view.appendChild(bodyEl);

  const src = document.createElement("script");
  src.type = "text/plain";
  src.className = "cmh-diff-src";
  src.setAttribute("data-enc", "base64");
  src.textContent = _b64EncodeUtf8(block.rawSrc);
  view.appendChild(src);

  block.host.replaceChildren(view);
  if (toggle) {
    toggle.addEventListener("click", () => {
      block.layout = block.layout === "split" ? "inline" : "split";
      setDefaultDiffLayout(block.layout);
      renderDiffBlock(block);
      applyDiffHighlightsForIndex(block.index);
    });
  }
  if (hlToggle) {
    hlToggle.addEventListener("click", () => {
      setDiffSyntaxOn(!diffSyntaxOn());
      rerenderAllDiffs();
    });
  }
  attachDiffHostHandlers(block);
}

function findDiffLineEls(diffIndex, lineKey) {
  // diffIndex / lineKey are always code-generated non-negative integers. Guard
  // against a hand-edited / poisoned persisted comment whose values could
  // otherwise inject into (and throw from) the querySelectorAll string.
  if (!/^\d+$/.test(String(diffIndex)) || !/^\d+$/.test(String(lineKey))) return [];
  return root.querySelectorAll(
    `.cmh-dl[data-diff-index="${diffIndex}"][data-line-key="${lineKey}"]`);
}
// Build a Range spanning [start,end] character offsets within el.textContent
// (walks text nodes, including those inside existing marks, so offsets stay
// stable as more sub-line marks are added to the same line).
function rangeInEl(el, start, end) {
  const r = document.createRange();
  let acc = 0, state = 0;
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
  let n;
  while ((n = walker.nextNode())) {
    const len = n.data.length;
    // Use `<` for the start so a boundary that sits at the end of one text node
    // resolves to the NEXT node - avoids an empty mark fragment when a new region
    // is adjacent to an existing mark.
    if (state === 0 && start < acc + len) { r.setStart(n, start - acc); state = 1; }
    if (state === 1 && end <= acc + len) { r.setEnd(n, end - acc); state = 2; break; }
    acc += len;
  }
  return state === 2 ? r : null;
}
function wrapDiffSubRange(lineEl, comment) {
  const codeEl = lineEl.querySelector(".cmh-dl-code");
  if (!codeEl) return false;
  const s = comment.subStart, e = comment.subEnd;
  // Guard against a poisoned persisted comment: the offsets must be sane integers
  // within the line's own text, or building the Range throws and breaks init.
  if (!Number.isInteger(s) || !Number.isInteger(e) || s < 0 || e <= s || e > codeEl.textContent.length) return false;
  try {
    if (codeEl.querySelector(`mark.cmh-dl-mark[data-cid="${comment.id}"]`)) return true; // already applied
    const r = rangeInEl(codeEl, s, e);
    if (!r) return false;
    // Apply-time overlap defense: never wrap a range that intersects an existing
    // (foreign) region mark - nesting marks corrupts the DOM. This also guards a
    // crafted/legacy persisted set that contains overlapping regions (the create-
    // time guard only covers new selections). Overlapping regions stay listed but
    // only the first-applied one is highlighted.
    for (const m of codeEl.querySelectorAll("mark.cmh-dl-mark")) {
      if (r.intersectsNode(m)) return false;
    }
    const mark = document.createElement("mark");
    mark.className = "cmh-dl-mark";
    mark.setAttribute("data-cid", comment.id);
    mark.appendChild(r.extractContents());
    r.insertNode(mark);
    codeEl.normalize();
    return true;
  } catch (e2) { return false; }
}
function _addRowCid(el, id) {
  const cids = (el.getAttribute("data-cids") || "").split(/\s+/).filter(Boolean);
  if (!cids.includes(id)) cids.push(id);
  el.setAttribute("data-cids", cids.join(" "));
  el.setAttribute("data-cid", cids[0]);
}
function applyDiffHighlight(comment) {
  const els = findDiffLineEls(comment.diffIndex, comment.lineKey);
  if (!els.length) return false;
  // Sub-line comment: wrap the selected range in each rendered copy of the line.
  if (comment.subStart != null && comment.subEnd != null) {
    let ok = false;
    els.forEach(el => { if (wrapDiffSubRange(el, comment)) ok = true; });
    return ok;
  }
  // Whole-line comment: highlight the row. Several comments can share a line.
  els.forEach(el => { el.classList.add("cmh-dl-hl"); _addRowCid(el, comment.id); });
  return true;
}
function clearDiffHighlight(id) {
  // Sub-line marks for this id: unwrap, keeping the text.
  root.querySelectorAll(`mark.cmh-dl-mark[data-cid="${id}"]`).forEach(mk => {
    const parent = mk.parentNode;
    while (mk.firstChild) parent.insertBefore(mk.firstChild, mk);
    parent.removeChild(mk);
    parent.normalize();
  });
  // Whole-line rows: drop this id; remove the row highlight only if it was the last.
  root.querySelectorAll(".cmh-dl-hl").forEach(el => {
    const cids = (el.getAttribute("data-cids") || el.getAttribute("data-cid") || "").split(/\s+/).filter(Boolean);
    const rest = cids.filter(c => c !== id);
    if (rest.length === cids.length) return;
    if (rest.length) { el.setAttribute("data-cids", rest.join(" ")); el.setAttribute("data-cid", rest[0]); }
    else { el.classList.remove("cmh-dl-hl", "cmh-dl-active"); el.removeAttribute("data-cid"); el.removeAttribute("data-cids"); }
  });
}
function flashDiff(id) {
  root.querySelectorAll(".cmh-dl-hl").forEach(el => {
    if ((el.getAttribute("data-cids") || el.getAttribute("data-cid") || "").split(/\s+/).includes(id)) {
      el.classList.add("cmh-dl-active");
      setTimeout(() => el.classList.remove("cmh-dl-active"), 2200);
    }
  });
  root.querySelectorAll(`mark.cmh-dl-mark[data-cid="${id}"]`).forEach(mk => {
    mk.classList.add("cmh-dl-mark-active");
    setTimeout(() => mk.classList.remove("cmh-dl-mark-active"), 2200);
  });
}
function applyDiffHighlightsForIndex(index) {
  comments.forEach(c => {
    if (c.anchorType === "diff" && c.diffIndex === index) applyDiffHighlight(c);
  });
}

function diffLineInfo(block, el) {
  const key = el.dataset.lineKey;
  const ln = block.lines.find(l => l.key === key);
  if (!ln) return null;
  return {
    diffIndex: block.index,
    lineKey: key,
    side: el.dataset.side || "both",
    lineType: ln.type,
    oldNo: ln.oldNo,
    newNo: ln.newNo,
    text: ln.text,
    sign: ln.type === "add" ? "+" : ln.type === "del" ? "-" : " ",
    label: block.label || "",
  };
}
function _closestDiffCode(node) {
  const el = node && (node.nodeType === 1 ? node : node.parentElement);
  return el && el.closest ? el.closest(".cmh-dl-code") : null;
}
// If the current selection is inside a single diff line's code, return its line
// info plus the sub-range (subStart, subEnd) and quoted substring; else null.
function diffSelectionInfo(block) {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
  const r = sel.getRangeAt(0);
  const codeEl = _closestDiffCode(r.startContainer);
  if (!codeEl || codeEl !== _closestDiffCode(r.endContainer)) return null; // one line only
  if (!block.host.contains(codeEl)) return null;
  const lineEl = codeEl.closest(".cmh-dl");
  if (!lineEl || lineEl.classList.contains("cmh-dl-full") || lineEl.classList.contains("cmh-dl-spacer")) return null;
  const info = diffLineInfo(block, lineEl);
  if (!info || !diffLineCommentable({ type: info.lineType })) return null;
  const full = codeEl.textContent;
  const pre = document.createRange();
  pre.selectNodeContents(codeEl);
  let subStart, subEnd;
  try { pre.setEnd(r.startContainer, r.startOffset); subStart = pre.toString().length; } catch (e) { return null; }
  try { pre.setEnd(r.endContainer, r.endOffset); subEnd = pre.toString().length; } catch (e) { return null; }
  if (subStart > subEnd) { const t = subStart; subStart = subEnd; subEnd = t; }
  const quote = full.slice(subStart, subEnd);
  if (subStart >= subEnd || !quote.trim()) return null;
  return Object.assign({}, info, { subStart, subEnd, quote, rect: r.getBoundingClientRect() });
}
function positionDiffAdd(el) {
  const rect = el.getBoundingClientRect();
  const visible = _clipAwareRect(el, rect);
  if (!visible) return false;
  const btnW = diffAddBtn.offsetWidth || 96;
  const btnH = diffAddBtn.offsetHeight || 26;
  const bounds = _floatingBounds(el);
  const left = visible.right - btnW;
  const lineCenter = rect.top + ((rect.bottom - rect.top) / 2);
  const top = lineCenter - (btnH / 2);
  diffAddBtn.style.left = _clamp(left, bounds.left, bounds.right - btnW) + "px";
  diffAddBtn.style.top = top + "px";
  return true;
}
function showDiffAddFor(el, info) {
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return;
  pendingDiff = info;
  if (diffAddHideTimer) { clearTimeout(diffAddHideTimer); diffAddHideTimer = null; }
  diffAddBtn.hidden = false;
  if (!positionDiffAdd(el)) { diffAddBtn.hidden = true; pendingDiff = null; return; }
  setActiveAdd({ el, btn: diffAddBtn, position: () => positionDiffAdd(el), clear: () => { pendingDiff = null; diffActiveLineEl = null; } });
}
function scheduleHideDiffAdd() {
  if (diffAddHideTimer) clearTimeout(diffAddHideTimer);
  diffAddHideTimer = setTimeout(() => {
    if (!diffAddBtn.matches(":hover")) { diffAddBtn.hidden = true; diffActiveLineEl = null; pendingDiff = null; clearActiveAdd(diffAddBtn); }
  }, 220);
}
function attachDiffHostHandlers(block) {
  const host = block.host;
  if (host._cmDiffAttached) return;
  host._cmDiffAttached = true;
  host.addEventListener("mousemove", (e) => {
    const el = e.target.closest && e.target.closest(".cmh-dl");
    if (!el || !host.contains(el) || el.classList.contains("cmh-dl-full") || el.classList.contains("cmh-dl-spacer")) return;
    // A cross-layer setActiveAdd() (an adjacent anchor winning) hides diffAddBtn and, via this
    // entry's clear() callback, resets diffActiveLineEl, so a pointer returning to the same line
    // falls through here and re-reveals the button. The guard stays UNCONDITIONAL (no
    // `!diffAddBtn.hidden` companion) on purpose: the sub-line text-selection path hides diffAddBtn
    // WITHOUT going through setActiveAdd (so diffActiveLineEl is retained), and a `!hidden` guard
    // would then re-show the whole-line button beside the open selection menu on the next mousemove.
    if (el === diffActiveLineEl) return;
    const info = diffLineInfo(block, el);
    if (!info || !diffLineCommentable({ type: info.lineType })) return;
    diffActiveLineEl = el;
    showDiffAddFor(el, info);
  });
  host.addEventListener("mouseleave", scheduleHideDiffAdd);
  // Selecting text inside a diff line's code opens the "Add comment" popup, so a
  // reviewer can comment a specific region of a line just like regular prose.
  host.addEventListener("mouseup", () => {
    setTimeout(() => {
      const info = diffSelectionInfo(block);
      if (!info) return;
      pendingDiffSel = info;
      pendingRange = null;
      pendingQuote = "";
      diffAddBtn.hidden = true;
      _setMenuMode("text");
      const r = info.rect;
      showMenu(r.left + Math.min(40, r.width / 2), r.bottom);
    }, 0);
  });
  host.addEventListener("click", (e) => {
    // A sub-line mark takes precedence over the row (a line can carry both).
    const mk = e.target.closest && e.target.closest("mark.cmh-dl-mark");
    const hl = e.target.closest && e.target.closest(".cmh-dl-hl");
    const id = mk ? mk.getAttribute("data-cid") : (hl ? hl.getAttribute("data-cid") : null);
    if (!id) return;
    openSidebar();
    const card = listEl.querySelector(`.cm-card[data-cid="${id}"]`);
    if (card) { card.scrollIntoView({ behavior: cmScrollBehavior(), block: "center" }); flashActive(id); }
    flashDiff(id);
  });
  // Keyboard: focusing a commentable line reveals the + button; Enter opens the
  // composer directly, so diff commenting works without a mouse.
  host.addEventListener("focusin", (e) => {
    const el = e.target.closest && e.target.closest(".cmh-dl");
    if (!el || !host.contains(el) || el.classList.contains("cmh-dl-full") || el.classList.contains("cmh-dl-spacer")) return;
    const info = diffLineInfo(block, el);
    if (!info || !diffLineCommentable({ type: info.lineType })) return;
    diffActiveLineEl = el;
    showDiffAddFor(el, info);
  });
  host.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const el = e.target.closest && e.target.closest(".cmh-dl");
    if (!el || !host.contains(el) || el.classList.contains("cmh-dl-full") || el.classList.contains("cmh-dl-spacer")) return;
    const info = diffLineInfo(block, el);
    if (!info || !diffLineCommentable({ type: info.lineType })) return;
    e.preventDefault();
    pendingDiff = null;
    diffAddBtn.hidden = true;
    diffActiveLineEl = null;
    createComposerElement({ mode: "new-diff", diff: info });
  });
}
if (diffAddBtn) {
  diffAddBtn.addEventListener("mouseenter", () => {
    if (diffAddHideTimer) { clearTimeout(diffAddHideTimer); diffAddHideTimer = null; }
  });
  diffAddBtn.addEventListener("mouseleave", scheduleHideDiffAdd);
  diffAddBtn.addEventListener("click", () => {
    if (!pendingDiff) return;
    const info = pendingDiff;
    pendingDiff = null;
    diffAddBtn.hidden = true;
    diffActiveLineEl = null;
    createComposerElement({ mode: "new-diff", diff: info });
  });
}
function diffBlockForIndex(index) {
  return diffBlocks.find(b => b.index === index) || null;
}
// Human-readable pinpoint for a diff comment: "+42" / "-17" / "line 30".
function diffLineLocator(c) {
  if (c.lineType === "add") return "+" + (c.newNo != null ? c.newNo : "?");
  if (c.lineType === "del") return "-" + (c.oldNo != null ? c.oldNo : "?");
  return "line " + (c.newNo != null ? c.newNo : (c.oldNo != null ? c.oldNo : "?"));
}
function isNumberedCodeBlock(pre) {
  if (!pre || pre.tagName !== "PRE" || !root.contains(pre)) return false;
  if (typeof isCommentableCodeBlock === "function") return isCommentableCodeBlock(pre);
  return !pre.classList.contains("mermaid") && !pre.classList.contains("cmh-diff")
    && !pre.closest(".cm-skip")
    && !pre.closest(".cmh-diff") && !pre.closest(".cmh-diff-host");
}
function ensureCodeLineGutter(target, extraClass) {
  if (!target || target.dataset.cmhLineNumbers === "1") return;
  const raw = String(target.textContent || "");
  // Guard the allocation itself: a pathologically large block skips the per-line gutter BEFORE the
  // split/array allocation (a hostile million-line block is a million-plus-char string), so it can
  // never allocate one array entry / one span per line and freeze the page on open.
  if (raw.length > CMH_CODE_MAX_CHARS) {
    target.dataset.cmhLineNumbers = "1";
    return;
  }
  const lines = raw.replace(/\r\n?/g, "\n").split("\n");
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  const gutter = document.createElement("span");
  gutter.className = "cmh-code-gutter cm-skip";
  gutter.setAttribute("aria-hidden", "true");
  const count = Math.max(1, lines.length);
  // Above CMH_CODE_MAX_LINES lines the per-line gutter is skipped too so it cannot allocate one span
  // per line. Mark it processed so a later pass does not retry it.
  if (count > CMH_CODE_MAX_LINES) {
    target.dataset.cmhLineNumbers = "1";
    return;
  }
  const lh = parseFloat(getComputedStyle(target).lineHeight) || 20;
  gutter.style.height = (count * lh) + "px";
  for (let i = 0; i < count; i++) {
    const line = document.createElement("span");
    line.className = "cmh-code-line" + (extraClass ? (" " + extraClass) : "");
    line.style.top = (i * lh) + "px";
    line.style.height = lh + "px";
    gutter.appendChild(line);
  }
  target.classList.add("cmh-code-lined");
  target.dataset.cmhLineNumbers = "1";
  target.insertBefore(gutter, target.firstChild);
}
// Fallback highlighting: if a commentable <pre><code class="language-XXX"> block was authored with a
// language label but never run through tools/highlight_code.py (no cmh-code-* token spans), and the
// language is one this tokenizer knows, highlight it in place so it never renders as plain monochrome
// text. Runs before setupCodeLineNumbers (which prepends a line gutter) and, via setupDiffLayer,
// before comment restoration - so line numbers and text-offset anchoring stay consistent.
function highlightCodeBlocks() {
  root.querySelectorAll("pre code[class*=\"language-\"]").forEach((code) => {
    const pre = code.closest("pre");
    if (!isNumberedCodeBlock(pre)) return;
    if (code.innerHTML.indexOf("cmh-code-") !== -1) return; // already highlighted (baked or a prior pass)
    const m = /(?:^|\s)language-([\w#+.-]+)/i.exec(code.className || "");
    const lang = m ? m[1].toLowerCase() : "";
    if (!diffLangKnown(lang)) return; // an unknown / non-tokenizable label (text, kusto, ...) stays plain
    const text = code.textContent;
    if (!text.trim()) return;
    if (text.length > CMH_CODE_MAX_CHARS) return; // too large to tokenize; leave plain (still readable)
    code.innerHTML = cmhHighlightCode(text, lang);
  });
}
function setupCodeLineNumbers() {
  root.querySelectorAll("pre").forEach((pre) => {
    if (!isNumberedCodeBlock(pre)) return;
    const code = pre.querySelector("code");
    const target = code || pre;
    const isKql = !!pre.closest("figure.cmh-kql");
    ensureCodeLineGutter(target, isKql ? "cmh-kql-line" : "");
  });
}
function setupDiffLayer() {
  diffBlocks.length = 0;
  const hosts = root.querySelectorAll("pre.cmh-diff, div.cmh-diff");
  hosts.forEach((el, i) => {
    const srcScript = el.querySelector ? el.querySelector("script.cmh-diff-src") : null;
    const rawSrc = srcScript
      ? (srcScript.getAttribute("data-enc") === "base64"
          ? _b64DecodeUtf8(srcScript.textContent)
          : srcScript.textContent)
      : el.textContent;
    // Collapse newlines/tabs so a crafted data-diff-label cannot inject extra
    // lines into the copied review bundle (the label goes into a one-line field).
    const label = (el.getAttribute("data-diff-label") || "").replace(/[\r\n\t]+/g, " ").trim();
    const host = document.createElement("div");
    host.className = "cmh-diff cmh-diff-host cm-skip";
    host.dataset.cmDiffIndex = String(i);
    host.setAttribute("data-diff-index", String(i));
    if (label) host.setAttribute("data-diff-label", label);
    const lang = inferDiffLang(el, label);
    if (lang) host.setAttribute("data-diff-lang", lang);
    el.replaceWith(host);
    // Pre-count raw lines and SKIP the full parse when the diff is pathologically
    // large, so a huge authored diff cannot allocate one object per line (and
    // freeze the page) before the cap is checked. rawSrc is identical across save
    // and reload, so this tooBig verdict is deterministic on both paths.
    const rawLineCount = rawSrc ? String(rawSrc).replace(/\r\n?/g, "\n").split("\n").length : 0;
    const tooBig = rawLineCount > CMH_DIFF_MAX_LINES;
    const block = { host, index: i, label, rawSrc, tooBig, rawLineCount, lang,
      lines: tooBig ? [] : parseUnifiedDiff(rawSrc), layout: defaultDiffLayout() };
    diffBlocks.push(block);
    renderDiffBlock(block);
    applyDiffHighlightsForIndex(i);
  });
  highlightCodeBlocks();
  setupCodeLineNumbers();
}
