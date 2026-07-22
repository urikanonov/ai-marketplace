/* ---------- Rich-text rendering for comment notes ----------
   Reviewer notes are stored as a plain-text markdown-ish SOURCE string; this module renders that
   source to SAFE html at display time (sidebar card, inline popover, print appendix). Supported:
   **bold**, *italic*, __underline__, ~~strike~~, `code`, "- " bullet lists, [label](url) links, and
   bare http(s) auto-links. A single-pass recursive-descent tokenizer builds output only from escaped
   text runs plus fixed tags, so no user string is ever placed unescaped; a depth cap and an
   operation budget keep it O(n) and crash-proof on hostile input. */

var RICH_MAX_DEPTH = 12;

function renderRichNote(source) {
  if (source == null) return "";
  var text = String(source);
  try {
    // Drop C0 control chars (keep \n and \t) so nothing can break the parser or reach the DOM.
    text = text.replace(/[\u0000-\u0008\u000B-\u001F\u007F]/g, "");
    var ctx = { ops: 0, budget: 50000 + text.length * 50 };
    var lines = text.split(/\r?\n/);
    var blocks = [];
    var i = 0;
    while (i < lines.length) {
      if (/^- /.test(lines[i])) {
        var items = [];
        while (i < lines.length && /^- /.test(lines[i])) {
          items.push("<li>" + renderRichInline(lines[i].slice(2), 0, true, ctx) + "</li>");
          i++;
        }
        blocks.push({ list: true, html: '<ul class="cmh-rich-list">' + items.join("") + "</ul>" });
      } else {
        blocks.push({ list: false, html: renderRichInline(lines[i], 0, true, ctx) });
        i++;
      }
    }
    // Text lines are separated by a literal "\n" (the note containers keep white-space: pre-wrap, so
    // the newline renders as a break); a block-level list needs no surrounding newline of its own.
    var out = "";
    for (var j = 0; j < blocks.length; j++) {
      if (j > 0 && !blocks[j].list && !blocks[j - 1].list) out += "\n";
      out += blocks[j].html;
    }
    return out;
  } catch (e) {
    return escapeHtml(text);
  }
}

function renderRichInline(text, depth, allowLinks, ctx) {
  if (depth > RICH_MAX_DEPTH) return escapeHtml(text);
  var out = "";
  var i = 0;
  var n = text.length;
  while (i < n) {
    if (ctx.ops > ctx.budget) { out += escapeHtml(text.slice(i)); break; }
    var ch = text.charAt(i);
    var two = text.substr(i, 2);

    // inline code: `...` (contents are literal, never re-parsed)
    if (ch === "`") {
      var cEnd = text.indexOf("`", i + 1);
      ctx.ops += cEnd < 0 ? (n - i) : (cEnd - i);
      if (cEnd > i + 1) {
        out += "<code>" + escapeHtml(text.slice(i + 1, cEnd)) + "</code>";
        i = cEnd + 1;
        continue;
      }
    }
    // link: [label](url) - only when links are allowed (never inside a link label)
    if (ch === "[" && allowLinks) {
      var link = richMatchLink(text, i, ctx);
      if (link && /^(?:https?|mailto):/i.test(link.url)) {
        var labelHtml = link.label.trim() ? renderRichInline(link.label, depth + 1, false, ctx) : escapeHtml(link.url);
        out += '<a href="' + escapeHtml(link.url) + '" target="_blank" rel="noopener noreferrer nofollow">'
          + labelHtml + "</a>";
        i = link.end;
        continue;
      }
    }
    // emphasis: ** (bold), __ (underline), ~~ (strike). Like italics, the opening pair must not be
    // followed by whitespace and the closing pair must not be preceded by whitespace, so `** x **`
    // stays literal.
    if ((two === "**" || two === "__" || two === "~~") && text.charAt(i + 2) !== " " && text.charAt(i + 2) !== "\t") {
      var tag = two === "**" ? "strong" : (two === "__" ? "u" : "s");
      var eEnd = text.indexOf(two, i + 2);
      ctx.ops += eEnd < 0 ? (n - i) : (eEnd - i);
      if (eEnd > i + 2 && text.charAt(eEnd - 1) !== " " && text.charAt(eEnd - 1) !== "\t") {
        out += "<" + tag + ">" + renderRichInline(text.slice(i + 2, eEnd), depth + 1, allowLinks, ctx) + "</" + tag + ">";
        i = eEnd + 2;
        continue;
      }
    }
    // emphasis: * (italic). The opening "*" must not be followed by whitespace and the closing "*"
    // must not be preceded by whitespace (so `a * b` stays literal), and a "*" that is part of a "**"
    // run is skipped (so `*a **b** c*` closes on the final lone "*", not the inner bold marker).
    if (ch === "*" && text.charAt(i + 1) !== " " && text.charAt(i + 1) !== "\t") {
      var iEnd = -1;
      for (var q = i + 1; q < n; q++) {
        ctx.ops++;
        if (ctx.ops > ctx.budget) break;
        if (text.charAt(q) === "*" && text.charAt(q + 1) !== "*" && text.charAt(q - 1) !== "*"
            && text.charAt(q - 1) !== " " && text.charAt(q - 1) !== "\t") { iEnd = q; break; }
      }
      if (iEnd > i + 1) {
        out += "<em>" + renderRichInline(text.slice(i + 1, iEnd), depth + 1, allowLinks, ctx) + "</em>";
        i = iEnd + 1;
        continue;
      }
    }
    // bare URL: http(s):// at a word boundary (start or a non-alphanumeric before it)
    if (allowLinks && (ch === "h" || ch === "H") && /^https?:\/\//i.test(text.substr(i, 8))) {
      var prev = i > 0 ? text.charAt(i - 1) : "";
      if (i === 0 || !/[A-Za-z0-9]/.test(prev)) {
        var bare = richConsumeUrl(text, i, ctx);
        if (bare) {
          out += '<a href="' + escapeHtml(bare.href) + '" target="_blank" rel="noopener noreferrer nofollow">'
            + escapeHtml(bare.href) + "</a>";
          i = bare.end;
          continue;
        }
      }
    }
    out += escapeHtml(ch);
    i++;
  }
  return out;
}

// Match a [label](url) starting at text[i] === "[", with balanced brackets in the label and balanced
// parentheses in the URL, so a link whose URL contains "(" ")" (e.g. a wikipedia article) is kept
// whole. Returns { label, url, end } or null. The URL is returned exactly as written (no trim/decode)
// so the scheme allowlist sees the real value.
function richMatchLink(text, i, ctx) {
  var n = text.length;
  var depth = 0;
  var labelEnd = -1;
  var j;
  for (j = i; j < n; j++) {
    ctx.ops++;
    if (ctx.ops > ctx.budget) return null;
    var c = text.charAt(j);
    if (c === "[") depth++;
    else if (c === "]") { depth--; if (depth === 0) { labelEnd = j; break; } }
  }
  if (labelEnd < 0 || text.charAt(labelEnd + 1) !== "(") return null;
  var pd = 1;
  var urlEnd = -1;
  for (var k = labelEnd + 2; k < n; k++) {
    ctx.ops++;
    if (ctx.ops > ctx.budget) return null;
    var ch = text.charAt(k);
    if (ch === "(") pd++;
    else if (ch === ")") { pd--; if (pd === 0) { urlEnd = k; break; } }
    else if (ch === " " || ch === "\t" || ch === "\r" || ch === "\n") return null; // whitespace means it is not a well-formed link
  }
  if (urlEnd < 0) return null;
  return { label: text.slice(i + 1, labelEnd), url: text.slice(labelEnd + 2, urlEnd), end: urlEnd + 1 };
}

// Consume a bare http(s) URL from text[i], keeping balanced trailing ")" and stripping trailing
// sentence punctuation, so "(see https://a.com)." links "https://a.com" and drops the ")." .
function richConsumeUrl(text, i, ctx) {
  var n = text.length;
  var j = i;
  var opens = 0, closes = 0;
  while (j < n) {
    ctx.ops++;
    var c = text.charAt(j);
    if (/\s/.test(c) || c === "<" || c === ">") break;
    if (c === "(") opens++;
    else if (c === ")") closes++;
    j++;
  }
  var url = text.slice(i, j);
  // Trim trailing sentence punctuation and any UNMATCHED closing parens in a SINGLE pass (compute the
  // final length, then slice once) so this stays O(n) on every engine - repeated `url.slice(0,-1)` is
  // O(1) amortized in V8 but can be O(n) per call in SpiderMonkey/JavaScriptCore.
  var trimEnd = url.length;
  var trimming = true;
  while (trimEnd > 0 && trimming) {
    trimming = false;
    var last = url.charAt(trimEnd - 1);
    if (".,;:!?\"']".indexOf(last) >= 0) { trimEnd--; trimming = true; continue; }
    if (last === ")" && closes > opens) { trimEnd--; closes--; trimming = true; }
  }
  if (trimEnd < url.length) url = url.slice(0, trimEnd);
  // Require a non-empty host after the scheme (so `http://a` links but a bare `https://` does not).
  if (!/^https?:\/\/[^\/?#]/i.test(url)) return null;
  return { href: url, end: i + url.length };
}

/* ---------- Composer formatting helpers ---------- */
// Marker pairs the wrap buttons/shortcuts insert around the selection.
var NOTE_FORMAT_WRAP = { bold: ["**", "**"], italic: ["*", "*"], underline: ["__", "__"], strike: ["~~", "~~"], code: ["`", "`"] };

// Replace [start,end) in the textarea with text using execCommand("insertText") so the browser's
// native undo/redo stack is preserved (setRangeText does NOT preserve undo in Chromium); fall back
// to setRangeText when execCommand is unavailable.
function richInsertText(ta, start, end, text) {
  ta.focus();
  ta.setSelectionRange(start, end);
  var ok = false;
  try { ok = document.execCommand("insertText", false, text); } catch (e) { ok = false; }
  if (!ok) {
    if (typeof ta.setRangeText === "function") ta.setRangeText(text, start, end, "end");
    else ta.value = ta.value.slice(0, start) + text + ta.value.slice(end);
  }
}

// Apply a formatting action to the composer textarea's current selection.
function applyNoteFormat(ta, kind) {
  if (!ta) return;
  var start = ta.selectionStart;
  var end = ta.selectionEnd;
  var value = ta.value;
  var sel = value.slice(start, end);

  if (kind === "link") {
    var label = sel || "text";
    var url = "url";
    var inserted = "[" + label + "](" + url + ")";
    richInsertText(ta, start, end, inserted);
    var urlStart = start + ("[" + label + "](").length;
    ta.setSelectionRange(urlStart, urlStart + url.length);
  } else if (kind === "list") {
    var lineStart = value.lastIndexOf("\n", start - 1) + 1;
    var block = value.slice(lineStart, end);
    // A selection that ends right after a "\n" would otherwise bullet the start of the next line;
    // keep that trailing newline out of the prefixing and re-add it.
    var trailingNL = block.charAt(block.length - 1) === "\n";
    var body = trailingNL ? block.slice(0, -1) : block;
    var prefixed = body.split("\n").map(function (ln) { return "- " + ln; }).join("\n") + (trailingNL ? "\n" : "");
    richInsertText(ta, lineStart, end, prefixed);
    // With a bare caret keep it a caret (shifted past the inserted "- "), so the next keystroke
    // does not overwrite the just-bulleted line; with a real selection reselect the prefixed block.
    if (start === end) ta.setSelectionRange(start + 2, start + 2);
    else ta.setSelectionRange(lineStart, lineStart + prefixed.length);
  } else {
    var w = NOTE_FORMAT_WRAP[kind];
    if (!w) return;
    var wrapped = w[0] + sel + w[1];
    richInsertText(ta, start, end, wrapped);
    if (sel) ta.setSelectionRange(start + w[0].length, end + w[0].length);
    else ta.setSelectionRange(start + w[0].length, start + w[0].length);
  }
  ta.dispatchEvent(new Event("input", { bubbles: true }));
  ta.focus();
}
