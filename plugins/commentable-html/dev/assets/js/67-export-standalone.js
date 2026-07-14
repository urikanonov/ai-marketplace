/* ---------- Export standalone (nonportable -> single self-contained file) ---------- */
// In nonportable mode the live page only references companion files via <link> and
// <script src>. To produce ONE portable file we must inline those assets. We do
// NOT fetch() them (blocked from file://); instead we read the string payloads
// from window.__COMMENTABLE_ASSETS__, which loaded as a classic <script src> and
// therefore works even when the document is opened by double-click (file://).
function _escClose(s) { return String(s).replace(/<\/(script|style)>/gi, "<\\/$1>"); }
function _cmhScriptClosePattern() { return String.fromCharCode(60) + "\\/" + "script>"; }
function _cmhScriptTagPattern(attrs, tail, flags) {
  return new RegExp("[ \\t]*" + String.fromCharCode(60) + "script\\b" + attrs + ">\\s*"
    + _cmhScriptClosePattern() + (tail || ""), flags);
}
function _cmhEscapeRegExp(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
function _cmhAdvanceCommentState(line, state) {
  let i = 0;
  while (i < line.length) {
    if (state === "html") {
      const close = line.indexOf("-->", i);
      if (close < 0) return "html";
      state = "";
      i = close + 3;
      continue;
    }
    if (state === "css") {
      const close = line.indexOf("*/", i);
      if (close < 0) return "css";
      state = "";
      i = close + 2;
      continue;
    }
    const htmlOpen = line.indexOf("<!--", i);
    const cssOpen = line.indexOf("/*", i);
    let open = -1, next = "";
    if (htmlOpen >= 0 && (cssOpen < 0 || htmlOpen < cssOpen)) {
      open = htmlOpen;
      next = "html";
    } else if (cssOpen >= 0) {
      open = cssOpen;
      next = "css";
    }
    if (open < 0) return "";
    state = next;
    i = open + (next === "html" ? 4 : 2);
  }
  return state;
}
function _cmhRegionMarkerMatches(html, kind, name) {
  const marker = kind + ": commentable-html - " + name;
  const markerSource = _cmhEscapeRegExp(marker);
  const bare = new RegExp("^[ \\t]*(?:=+[ \\t]*)?(" + markerSource + ")[ \\t]*(?:=+[ \\t]*)?$");
  const inline = new RegExp("^[ \\t]*(?:<!--[ \\t]*|/\\*[ \\t]*)(?:=+[ \\t]*)?(" + markerSource + ")[ \\t]*(?:=+[ \\t]*)?(?:-->|\\*/)[ \\t]*$");
  const out = [];
  const lines = String(html || "").match(/[^\n]*(?:\n|$)/g) || [];
  let offset = 0, state = "";
  lines.forEach(function (line) {
    if (!line) return;
    const body = line.replace(/\r?\n$/, "");
    const inlineMatch = body.match(inline);
    const bareMatch = body.match(bare);
    const match = inlineMatch || ((state === "html" || state === "css") ? bareMatch : null);
    if (match) {
      const markerOffset = body.indexOf(match[1]);
      out.push({ index: offset + markerOffset });
    }
    state = _cmhAdvanceCommentState(body, state);
    offset += line.length;
  });
  return out;
}
function _assertSingleRegionMarkers(html, name) {
  const begins = _cmhRegionMarkerMatches(html, "BEGIN", name);
  const ends = _cmhRegionMarkerMatches(html, "END", name);
  if (begins.length !== 1 || ends.length !== 1) {
    throw new Error("Export aborted: malformed commentable-html region markers for " + name + ".");
  }
  if (begins[0].index >= ends[0].index) {
    throw new Error("Export aborted: commentable-html region " + name + " ends before it begins.");
  }
}
function _assertSingleLayerRegions(html) {
  CMH_REGION_NAMES.forEach(function (name) { _assertSingleRegionMarkers(html, name); });
}
// Insert `insertion` immediately before the LAST occurrence of </tag>. The real
// closing tag of a well-formed document is the last one; earlier matches can sit
// inside the pre-<html> documentation comment (whose prose literally mentions
// "</body>" and "<head>") or inside an inlined script string. A naive first-match
// replace would splice the payload into that comment and corrupt the file. This
// only bites when the base HTML is the raw on-disk file (fetched over http); a DOM
// snapshot drops the pre-<html> comment, which is why file:// exports were unaffected.
function _insertBeforeLastTag(html, tag, insertion) {
  const rx = new RegExp("</" + tag + "\\s*>", "gi");
  let idx = -1, m;
  while ((m = rx.exec(html))) idx = m.index;
  if (idx < 0) throw new Error("Could not find </" + tag + "> to inline into.");
  return html.slice(0, idx) + insertion + html.slice(idx);
}
function _inlineNonPortableAssets(baseHtml) {
  if (!CMH_ASSETS || !CMH_ASSETS.css || !CMH_ASSETS.js) {
    throw new Error("Cannot export standalone: the commentable-html assets file "
      + "(__COMMENTABLE_ASSETS__) did not load. Keep the companion .assets.js next "
      + "to this HTML, or keep the companion files alongside it.");
  }
  if (CMH_ASSETS.version && CMH_VERSION && CMH_ASSETS.version !== CMH_VERSION) {
    // Inlining a companion whose CSS/JS is a different version than the running layer
    // would bake a mismatched runtime into the portable file. Abort with guidance
    // rather than emit a document that silently disagrees with itself.
    throw new Error("Cannot export standalone: the companion assets file is version "
      + CMH_ASSETS.version + " but this document's runtime is " + CMH_VERSION
      + ". Refresh the companion .assets.js (or regenerate the document) so both match, then export again.");
  }
  let t = baseHtml;
  if (!/<link\b[^>]*commentable-html[^>]*\.css/i.test(t)) {
    throw new Error("Could not find the commentable-html stylesheet <link> to inline.");
  }
  _assertSingleLayerRegions(t);
  // 1) Strip every piece of nonportable scaffolding BEFORE inlining the payloads, so
  //    the marker-like strings inside the runtime source can never be matched and
  //    no leftover companion reference survives. _getBaseHtml() may hand us a
  //    file:// DOM snapshot whose whitespace around trailing markers is collapsed,
  //    so we re-emit the CSS/JS regions from scratch with their own newlines
  //    rather than trusting the snapshot's line breaks.
  t = _retargetLayerDescriptor(t, "portable");
  t = t.replace(/[ \t]*<!--\s*BEGIN: commentable-html - NONPORTABLE BOOTSTRAP[\s\S]*?END: commentable-html - NONPORTABLE BOOTSTRAP\s*-->[ \t]*/i, "");
  const cssRegion = /[ \t]*<!--\s*=*\s*BEGIN: commentable-html - CSS[\s\S]*?<!--\s*=*\s*END: commentable-html - CSS\s*=*\s*-->[ \t]*\n?/i;
  const jsRegion = /[ \t]*<!--\s*=*\s*BEGIN: commentable-html - JS[\s\S]*?<!--\s*=*\s*END: commentable-html - JS\s*=*\s*-->[ \t]*\n?/i;
  if (cssRegion.test(t)) {
    t = t.replace(cssRegion, "");
  } else {
    t = t.replace(/[ \t]*<link\b[^>]*commentable-html[^>]*\.css[^>]*>[ \t]*\n?/ig, "");
  }
  if (jsRegion.test(t)) {
    t = t.replace(jsRegion, "");
  } else {
    const companionScript = new RegExp("[ \\t]*<scr" + "ipt\\b[^>]*commentable-html[^>]*\\.js[^>]*>"
      + "\\s*<\\/scr" + "ipt>[ \\t]*\\n?", "ig");
    t = t.replace(/[ \t]*<!--\s*commentable-html - layer loaded[\s\S]*?-->[ \t]*\n?/i, "");
    t = t.replace(companionScript, "");
    t = t.replace(/[ \t]*<!--\s*END: commentable-html - JS\s*-->[ \t]*\n?/ig, "");
  }

  // 2) Inline the CSS in place of the removed <link>, and the runtime just before
  //    </body>. Each block carries its own region markers on their own lines.
  const styleBlock = "\n<style>\n"
    + "/* ============================================================\n"
    + "   BEGIN: commentable-html - CSS\n"
    + "   ============================================================ */\n"
    + _escClose(CMH_ASSETS.css) + "\n"
    + "/* ============================================================\n"
    + "   END: commentable-html - CSS\n"
    + "   ============================================================ */\n"
    + "</style>\n";
  const jsBlock = "\n<!-- ============================================================\n"
    + "     BEGIN: commentable-html - JS\n"
    + "     ============================================================ -->\n"
    + "<script>\n" + _escClose(CMH_ASSETS.js) + "\n</scr" + "ipt>\n"
    + "<!-- END: commentable-html - JS -->\n";
  if (!/<\/head>/i.test(t)) throw new Error("Could not find </head> to inline the stylesheet.");
  if (!/<\/body>/i.test(t)) throw new Error("Could not find </body> to inline the runtime.");
  // Insert the CSS before the LAST </head> and the runtime before the LAST </body>,
  // then re-collapse blank runs. Head first, so the runtime's own "</head>" string
  // literals cannot be mistaken for the document's real head.
  t = _insertBeforeLastTag(t, "head", styleBlock);
  t = _insertBeforeLastTag(t, "body", jsBlock);
  return t.replace(/\n{3,}/g, "\n\n");
}
function _buildStandaloneHtml(baseHtml, commentArr) {
  return _inlineNonPortableAssets(_buildSavedHtml(baseHtml, commentArr));
}
async function saveStandalone() {
  // "Export as Portable" always yields ONE combined file with the
  // comments embedded. An inline document is already self-contained, so the plain
  // in-file embed (saveHtml) IS the combined file there; only nonportable documents
  // need the CSS/JS inlined to become portable.
  if (!NONPORTABLE_MODE) return saveHtml();
  let baseHtml;
  try { baseHtml = await _getBaseHtml(); }
  catch (e) { showToast("Could not load base HTML."); return; }
  baseHtml = _applyWidgetLayoutToHtml(baseHtml);
  baseHtml = _applyChecklistStateToHtml(baseHtml);
  const exportComments = _exportableComments();
  let text;
  try { text = _buildStandaloneHtml(baseHtml, exportComments); }
  catch (e) { showToast(e.message); return; }
  const filename = _suggestedFilename();
  const n = exportComments.length;
  _downloadHtml(text, filename);
  showToast(`Downloaded ${filename} - one portable file, ${n} comment${n === 1 ? "" : "s"} embedded, no companion files needed.`);
}

