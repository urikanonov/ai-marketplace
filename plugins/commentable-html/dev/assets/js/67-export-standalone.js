/* ---------- Export standalone (nonshareable -> single self-contained file) ---------- */
// In nonshareable mode the live page only references companion files via <link> and
// <script src>. To produce ONE shareable file we must inline those assets. We do
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
      // Which comment SYNTAX carries this marker. Not part of the pinned answer (the parity
      // corpus reads offsets only, CMH-VAL-22) - it is what lets a caller ask the narrower
      // question the region strips actually care about: the strips anchor on `<!--`, so only an
      // HTML-comment-syntax marker can ever aim one (CMH-EXP-22).
      const html5 = inlineMatch ? body.trim().charAt(0) === "<" : state === "html";
      out.push({ index: offset + markerOffset, htmlComment: html5 });
    }
    state = _cmhAdvanceCommentState(body, state);
    offset += line.length;
  });
  return out;
}
// Exposed for deterministic tests: locating a region marker is pure, and
// tests/fixtures/region_marker_parity.json pins this answer against the three Python copies of
// the same rule (CMH-VAL-22), which cannot share one helper across the build tool, the shipped
// validator package and the shipped authoring tools.
window.__cmhRegionMarkerMatches = function (html, kind, name) {
  return _cmhRegionMarkerMatches(html, kind, name).map(function (m) { return m.index; });
};
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
// The stem of the probe token stamped over a located marker so the parse can be asked WHERE that
// exact marker landed. Letters and digits only, so substituting it cannot change how anything around
// it is tokenized. The stem is EXTENDED until it does not occur in the source at all (the document
// carries this runtime's own text, and an author may quote anything), so a token can only ever be
// present because this pass put it there - otherwise a document quoting a token in a real comment
// could vouch for a marker that is not in one.
const _CMH_MARKER_PROBE = "cmhMarkerProbe";
function _cmhMarkerProbeStem(src) {
  let stem = _CMH_MARKER_PROBE;
  // The stem grows by one character per collision, so a source can only lengthen it by the run of
  // `x` it actually contains after the stem; the bound is belt-and-braces against a crafted input.
  for (let i = 0; i < 64 && src.indexOf(stem) >= 0; i += 1) stem += "x";
  return src.indexOf(stem) >= 0 ? null : stem;
}
// Which of the located markers a browser really parses INSIDE A COMMENT, by identity rather than by
// count. Each located marker is replaced with its own token in a COPY of the source, the copy is
// parsed once, and the tokens that turn up in a comment node are returned. Counting alone is not
// enough: a region can hold the SAME number of text-located and parsed markers that are not the SAME
// markers - a real `<!-- END ... --!>` comment (the legacy comment-end-bang close, which a browser
// honours and the text locator rejects) paired with an authored `<script>` quotation of the marker
// gives one of each, and the strip - which requires `-->` - would then anchor on the quotation.
// Returns null when the cross-check cannot be taken at all.
function _cmhCommentBorneMarkers(src, probes) {
  const stem = _cmhMarkerProbeStem(src);
  if (!stem) return null;
  const ordered = probes.map(function (p, i) { return { id: i, index: p.index, length: p.length }; })
    .sort(function (a, b) { return a.index - b.index; });
  let stamped = "", cursor = 0;
  for (let i = 0; i < ordered.length; i += 1) {
    const p = ordered[i];
    if (p.index < cursor) return null;
    stamped += src.slice(cursor, p.index) + stem + p.id + "z";
    cursor = p.index + p.length;
  }
  stamped += src.slice(cursor);
  let doc, walker;
  try { doc = new DOMParser().parseFromString(stamped, "text/html"); } catch (e) { return null; }
  if (!doc) return null;
  try { walker = doc.createTreeWalker(doc, NodeFilter.SHOW_COMMENT); } catch (e) { return null; }
  const token = new RegExp(_cmhEscapeRegExp(stem) + "(\\d+)z", "g");
  const seen = {};
  let node;
  while ((node = walker.nextNode())) {
    // Skipped for the reason the rest of the export path skips a <noscript>: DOMParser has
    // scripting disabled, so it reads as markup what the live document keeps as inert text.
    if (_cmhInInertHost(node)) continue;
    const data = node.data || "";
    token.lastIndex = 0;
    let m;
    while ((m = token.exec(data))) seen[m[1]] = true;
  }
  return seen;
}
// Every marker written in HTML-COMMENT syntax must be one a browser really parses as a comment, at
// that exact spot (CMH-EXP-22). The text locator above finds a marker-shaped line wherever it sits,
// including inside a raw-text body (`<script>`, `<textarea>`, `<title>`) or an inert `<template>`,
// where a browser builds no comment at all. While the layer's own marker is intact a quoted one just
// makes the count 2 and the guard above already refuses; the case this closes is a region whose
// marker a browser does not read where the strip thinks it is - a DAMAGED region whose only
// surviving marker is an authored quotation, or a real marker the locator cannot see (the `--!>`
// close) standing beside a quotation it can. Either way the strip anchors on the quotation and cuts
// from the real BEGIN through the author's content. The validator has refused the same shapes since
// CMH-VAL-20 (tools/validate/checks/layer_parts/90-orchestrator.py), positionally; this is the
// runtime giving that same answer.
//
// The test is deliberately scoped to HTML-comment syntax, not to every located marker, because the
// strips anchor on `<!--`: a marker written as a CSS comment cannot aim one, so it is not this
// hazard. That is what leaves the Shareable CSS region's `/* ... */` pair inside a live `<style>`
// alone, and what leaves a stray `/* END: ... */` in the body to the Plain export's own
// region-attribution diagnosis (CMH-EXP-21) rather than pre-empting it with a wrong cause.
//
// The gate proves each LOCATED marker is comment-borne; the strips must additionally have no
// EARLIER place to start. They are wider than the locator in one direction: their `<!--\s*=*\s*`
// prefix is not line-anchored, so an authored `<p>x</p><!-- BEGIN: commentable-html - JS -->` -
// invisible to a LINE locator, and therefore not counted, not probed, and not a duplicate - is a
// perfectly good anchor for the strip, which then cuts from THERE through the real region and takes
// the author's content with it. Only an anchor STRICTLY BEFORE the region's own BEGIN is refused:
// that is the destructive direction. An anchor at the marker is the healthy case, and no anchor at
// all (prose inside the marker's own comment defeats the strip's prefix) only leaves the region
// unstripped, which the Plain export's data-safety net already diagnoses (CMH-EXP-21). END is not
// checked at all - a decoy there can only cut the region SHORT, which again leaves the layer's own
// blocks for that net, and the runtime's own inlined source legitimately contains the literal text
// of an END marker inside a `<script>`, so checking it would refuse every shipped document.
function _cmhFirstStripAnchor(src, kind, name) {
  const anchor = new RegExp("<!--\\s*=*\\s*"
    + _cmhEscapeRegExp(kind + ": commentable-html - " + name), "i");
  const hit = anchor.exec(src);
  return hit ? hit.index + hit[0].length : -1;
}
function _assertSingleLayerRegions(html) {
  const src = String(html == null ? "" : html);
  const probes = [];
  CMH_REGION_NAMES.forEach(function (name) {
    _assertSingleRegionMarkers(src, name);
    ["BEGIN", "END"].forEach(function (kind) {
      const marker = kind + ": commentable-html - " + name;
      _cmhRegionMarkerMatches(src, kind, name).forEach(function (m) {
        if (!m.htmlComment) return;
        probes.push({ index: m.index, length: marker.length, kind: kind, name: name });
        if (kind !== "BEGIN") return;
        // Only an anchor STRICTLY BEFORE the region's own marker is destructive: the strip would
        // start there and delete everything up to the real region. An anchor at the marker is the
        // healthy case, and no anchor at all (prose inside the marker's comment, so the strip's
        // prefix does not match it) only leaves the region unstripped, which the Plain export's
        // data-safety net diagnoses (CMH-EXP-21) rather than losing anything.
        const anchorEnd = _cmhFirstStripAnchor(src, kind, name);
        if (anchorEnd < 0 || anchorEnd >= m.index + marker.length) return;
        throw new Error("Export aborted: this document has an earlier `<!-- " + marker
          + " -->` than the commentable-html " + name + " region's own BEGIN marker, so a region"
          + " strip would start there and delete the content in between. It is not on a line of its"
          + " own, so it reads as a boundary to the strip and not to the region check; write the"
          + " quoted marker with `&lt;!--` (or move it onto its own line) so it cannot be mistaken"
          + " for one, then export again.");
      });
    });
  });
  if (!probes.length) return;
  const seen = _cmhCommentBorneMarkers(src, probes);
  // Fail CLOSED. A cross-check that cannot be taken is not a reason to fall back to the text-only
  // view this exists to correct: refusing costs the reader one export (their comments are safe in
  // storage), while accepting can delete authored content from the copy being written.
  if (!seen) {
    throw new Error("Export aborted: the commentable-html region markers could not be cross-checked "
      + "against this document's own parse, so a region strip cannot be aimed safely. Reload the "
      + "document and export again.");
  }
  for (let i = 0; i < probes.length; i += 1) {
    if (seen[String(i)]) continue;
    const p = probes[i];
    throw new Error("Export aborted: the " + p.kind + " marker for commentable-html region " + p.name
      + " is written as an HTML comment the document does not parse as one - a browser builds no"
      + " comment there, so it is text inside a <script>, <textarea> or <title> body, or markup"
      + " parked in an inert <template>. A region strip would anchor on it and cut from the wrong"
      + " place; write the marker as its own `<!-- " + p.kind + ": commentable-html - " + p.name
      + " -->` comment in the document proper.");
  }
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
function _inlineNonShareableAssets(baseHtml) {
  if (!CMH_ASSETS || !CMH_ASSETS.css || !CMH_ASSETS.js) {
    throw new Error("Cannot export standalone: the commentable-html assets file "
      + "(__COMMENTABLE_ASSETS__) did not load. Keep the companion .assets.js next "
      + "to this HTML, or keep the companion files alongside it.");
  }
  if (CMH_ASSETS.version && CMH_VERSION && CMH_ASSETS.version !== CMH_VERSION) {
    // Inlining a companion whose CSS/JS is a different version than the running layer
    // would bake a mismatched runtime into the shareable file. Abort with guidance
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
  // 1) Strip every piece of nonshareable scaffolding BEFORE inlining the payloads, so
  //    the marker-like strings inside the runtime source can never be matched and
  //    no leftover companion reference survives. _getBaseHtml() may hand us a
  //    file:// DOM snapshot whose whitespace around trailing markers is collapsed,
  //    so we re-emit the CSS/JS regions from scratch with their own newlines
  //    rather than trusting the snapshot's line breaks.
  t = _retargetLayerDescriptor(t, "shareable");
  // Either spelling, but the SAME one at both ends (a backreference): a mixed pair would let the
  // match run from the real bootstrap into an authored quotation of the other spelling and take
  // the content in between with it.
  t = t.replace(/[ \t]*<!--\s*BEGIN: commentable-html - NON(SHAREABLE|PORTABLE) BOOTSTRAP[\s\S]*?END: commentable-html - NON\1 BOOTSTRAP\s*-->[ \t]*/i, "");
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
  return _inlineNonShareableAssets(_buildSavedHtml(baseHtml, commentArr));
}
async function saveStandalone() {
  // "Export as Shareable" always yields ONE combined file with the
  // comments embedded. An inline document is already self-contained, so the plain
  // in-file embed (saveHtml) IS the combined file there; only nonshareable documents
  // need the CSS/JS inlined to become shareable.
  if (!NONSHAREABLE_MODE) return saveHtml();
  let baseHtml;
  try { baseHtml = await _getBaseHtml(); }
  catch (e) { _reportExportFailure(e, _EXPORT_FAILURE_LOAD); return; }
  let review;
  try {
    baseHtml = _applyWidgetLayoutToHtml(baseHtml);
    baseHtml = _applyChecklistStateToHtml(baseHtml);
    baseHtml = _applyNoteStateToHtml(baseHtml);
    review = _applyReviewStateToHtml(baseHtml);
    baseHtml = review.html;
  } catch (e) { _reportExportFailure(e, _EXPORT_FAILURE_PREPARE); return; }
  const canonical = _exportableCommentsOrReport();
  if (!canonical) return;
  const exportComments = canonical.comments;
  let text;
  try { text = _buildStandaloneHtml(baseHtml, exportComments); }
  catch (e) { _reportExportBuildFailure(e); return; }
  const filename = _suggestedFilename();
  const n = exportComments.length;
  try { _downloadHtml(text, filename); }
  catch (e) { _reportExportFailure(e, _EXPORT_FAILURE_DOWNLOAD); return; }
  showToast(`Downloaded ${filename} - one shareable file, ${n} comment${n === 1 ? "" : "s"} embedded, no companion files needed.` + review.note, { center: true });
}
