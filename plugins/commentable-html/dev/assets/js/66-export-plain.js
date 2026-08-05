/* ---------- Save as plain HTML (strip the comment layer) ---------- */
// The layer's own data blocks, judged by the CONTENT-ROOT BOUNDARY rather than by a document-wide
// text scan: a script inside the content root that borrows a reserved id is authored content
// (CMH-EXP-19), which no region strip can remove and which must not make a legitimate export
// abort. The descriptor is in the list because an export that declares a mode maintains ADDITIONAL
// descriptor copies in the layer's region (CMH-EXP-18), and a "plain" copy that still declares
// itself a commentable-html document with a mode would be a silent leak.
const _CMH_PLAIN_DATA_IDS = ["handledCommentIds", "embeddedComments", "reviewedSections", "commentableHtmlLayer"];
// The region whose strip is supposed to take each block with it. The descriptor has none: it sits
// outside every region and is removed by its own strip, so "outside the region" is not a fault for
// it and the diagnosis below says so instead.
const _CMH_PLAIN_BLOCK_REGION = {
  handledCommentIds: "HANDLED IDS",
  embeddedComments: "EMBEDDED COMMENTS",
  reviewedSections: "EMBEDDED COMMENTS",
  commentableHtmlLayer: "",
};
// Where a surviving block sits relative to the region that should have carried it away, judged on
// the SOURCE document rather than the stripped copy: a strip that worked leaves no markers behind,
// so the copy itself can no longer answer the question. "inside" (every block the layer owns for
// that id was between the markers, so the region TEXT could not be matched), "outside" (at least
// one sits beyond the region, where no region strip can reach it), or "unresolved" (the source does
// not carry exactly one ordered pair of that region's markers as HTML comments, so nothing can be
// attributed to the region at all). The DESCRIPTOR has no region of its own, so it is asked the
// same question against EVERY region rather than being declared region-less on trust: an extra
// descriptor copy the layer maintains may legitimately sit inside one (CMH-EXP-18), and only the
// EMBEDDED COMMENTS / HANDLED IDS / COMMENT UI / JS regions are stripped.
function _cmhPlainLeakSite(sourceHtml, id, region) {
  // The trusted document string, in the same shape every other round-trip uses (CMH-EXP-14): no
  // comment or state data ever enters this parse.
  const src = String(sourceHtml == null ? "" : sourceHtml);
  let doc;
  try { doc = new DOMParser().parseFromString(src, "text/html"); }
  catch (e) { return { site: "unattributable", region: region, sole: false }; }
  const owners = cmhLayerBlocks(doc, id);
  if (!region) {
    // SOME copy inside a region, not every copy: an export that declares a mode maintains extra
    // descriptor copies, so a document can legitimately hold one inside a region and one outside,
    // and claiming "outside every region" of that document would be false.
    let held = "";
    CMH_REGION_NAMES.forEach(function (name) {
      if (held) return;
      const bounds = _cmhRegionCommentBounds(doc, name);
      if (!bounds || bounds.state !== "ok") return;
      if (owners.some(function (el) { return _cmhNodeInRegion(el, bounds); })) held = name;
    });
    return held
      ? { site: "descriptor-inside", region: held, sole: owners.length === 1 }
      : { site: "descriptor", region: "", sole: owners.length === 1 };
  }
  const bounds = _cmhRegionCommentBounds(doc, region);
  if (!bounds || bounds.state !== "ok") return { site: "unresolved", region: region, sole: false };
  // No block the boundary accepts in the SOURCE, yet one survived in the copy: the two documents
  // disagree about their own boundary (a second content root inside a region the strip removed, for
  // example), which is not a marker problem and must not be reported as one.
  if (!owners.length) return { site: "unattributable", region: region, sole: false };
  return {
    site: owners.every(function (el) { return _cmhNodeInRegion(el, bounds); }) ? "inside" : "outside",
    region: region,
    sole: owners.length === 1,
  };
}
function _cmhPlainLeakedBlocks(html, sourceHtml) {
  const src = String(html == null ? "" : html);
  // Cheap probe on the bare ids (not a quoted-attribute pattern, which an unquoted `id=...` would
  // slip past), so the ordinary export never pays for a second parse.
  if (!/handledCommentIds|embeddedComments|reviewedSections|commentableHtmlLayer/.test(src)) {
    return { leak: null, contested: false };
  }
  const doc = new DOMParser().parseFromString(src, "text/html");
  const state = cmhContentRootState(doc);
  let leak = null;
  _CMH_PLAIN_DATA_IDS.forEach(function (id) {
    if (leak) return;
    const owners = cmhLayerIdOwners(doc, id);
    // A contested boundary cannot tell the layer's blocks from content, so every owner counts:
    // fail closed rather than ship comment data in a copy that claims to carry none.
    const leaked = state.contested ? owners : owners.filter(function (node) {
      return !(state.root && state.root.contains(node));
    });
    if (!leaked.length) return;
    // A contested boundary has its own wording, so do not pay for the placement parse there.
    if (state.contested) { leak = { id: id, region: "", site: "contested", sole: false }; return; }
    const placed = _cmhPlainLeakSite(sourceHtml, id, _CMH_PLAIN_BLOCK_REGION[id] || "");
    leak = { id: id, region: placed.region, site: placed.site, sole: placed.sole };
  });
  return { leak: leak, contested: state.contested };
}
// Name the block that survived and WHERE it survived. "Malformed markers?" was a guess that sent
// the author after the one cause the layer had not checked, and misnamed the commonest one: a
// block that was never inside the region at all, which no region strip could ever remove.
function _cmhPlainLeakMessage(leak) {
  const quoted = '"' + leak.id + '"';
  if (leak.site === "descriptor") {
    return "Plain export aborted: the layer descriptor block " + quoted + " is still in the copy. It"
      + " sits outside every commentable-html region, so only the descriptor strip could remove it;"
      + " run validate.py on the document, then export again.";
  }
  if (leak.site === "descriptor-inside") {
    return "Plain export aborted: the layer descriptor block " + quoted + " is still in the copy, and"
      + " this document keeps a descriptor copy inside its " + leak.region + " region. The descriptor"
      + " is removed by its own strip rather than by a region strip, and that strip could not resolve"
      + " this copy; run validate.py on the document, then export again.";
  }
  if (leak.site === "inside") {
    return "Plain export aborted: the reserved block " + quoted + " is still in the copy, INSIDE the "
      + leak.region + " region. That region's markers resolve, so the region text itself could not be"
      + " matched - each marker must be the only thing in its own HTML comment (apart from `=`"
      + " padding), with no prose before or after it. Repair the region markers, then export again.";
  }
  if (leak.site === "outside") {
    // The remedy depends on whether this document has another block of the same id. Telling the
    // author to MOVE a duplicate into the region could put it AHEAD of the real block, which would
    // hand the reader and the next export that stale copy - the very swap this rule exists to stop.
    return "Plain export aborted: the reserved block " + quoted + " is still in the copy, OUTSIDE the "
      + leak.region + " region, where no region strip can remove it. "
      + (leak.sole
        ? "Move it into the " + leak.region + " region (or give that element a different id), then export again."
        : "This document already has another " + leak.id + " block, so remove this one (or give that"
          + " element a different id) rather than moving it, then export again.");
  }
  if (leak.site === "unattributable") {
    return "Plain export aborted: the reserved block " + quoted + " is still in the copy, and this"
      + " document does not expose it as one of the layer's own blocks (the content-root boundary"
      + " disagrees between the document and the copy the strip produced), so it cannot be attributed"
      + " to the " + leak.region + " region. Run validate.py on the document, then export again.";
  }
  return "Plain export aborted: the reserved block " + quoted + " is still in the copy, and this"
    + " document does not carry exactly one ordered pair of " + leak.region + " region markers as HTML"
    + " comments, so nothing can be attributed to that region. Repair the markers, then export again.";
}
// Remove every descriptor copy the layer owns, by verified OFFSETS rather than a first-match text
// replace: an export that declares a mode may leave more than one, and a text replace would either
// stop at the first or reach into authored content. Returns null when nothing resolves, so the
// caller can fall back to the historical single-match strip.
function _cmhStripLayerDescriptors(html) {
  const src = String(html == null ? "" : html);
  const found = _cmhVerifiedScriptRanges(src, "commentableHtmlLayer");
  if (!found.ranges.length) return null;
  const ordered = found.ranges.slice().sort(function (a, b) { return b.start - a.start; });
  let out = src;
  let limit = out.length;
  for (let i = 0; i < ordered.length; i += 1) {
    const range = ordered[i];
    if (range.end > limit) return null;
    let end = range.end;
    while (end < out.length && /\s/.test(out.charAt(end))) end += 1;
    let start = range.start;
    while (start > 0 && (out.charAt(start - 1) === " " || out.charAt(start - 1) === "\t")) start -= 1;
    out = out.slice(0, start) + out.slice(end);
    limit = start;
  }
  return out;
}
// Produces a standalone copy of the document with the commenting *ability* removed but
// its appearance intact: the HTML-comment regions (HANDLED IDS, EMBEDDED COMMENTS,
// COMMENT UI) and the runtime JS are deleted, while every stylesheet is kept - the
// inline CSS region (or the nonshareable companion <link>) carries the document's own
// content styling (tables, sections, code, diff, KQL, images), so the plain copy looks
// the same. The now-unused .cm-* UI rules are inert because their elements are gone.
//
// The base HTML here is the on-disk file or the IIFE-start snapshot (see SNAPSHOT_HTML),
// which never carries runtime comment artifacts (highlight marks, rings, data-cid) -
// those are added later by the layer - so there is nothing to sanitize out of the host
// content, and attempting to do so with document-wide regexes would risk corrupting
// legitimate host markup (code samples, host data-cid attributes, script literals).
function _buildPlainHtml(baseHtml) {
  let t = baseHtml;
  _assertSingleLayerRegions(t);
  // Every descriptor copy the layer owns, resolved by the boundary; the historical single-match
  // text strip stays as the fallback for a document the resolver cannot verify.
  const withoutDescriptors = _cmhStripLayerDescriptors(t);
  if (withoutDescriptors != null) {
    t = withoutDescriptors;
  } else {
    const layerDescriptorScript = new RegExp("[ \\t]*<scr" + "ipt\\b[^>]*\\sid\\s*=\\s*([\"'])"
      + "commentableHtmlLayer\\1[^>]*>[\\s\\S]*?<\\/scr" + "ipt>\\s*", "i");
    t = t.replace(layerDescriptorScript, "");
  }
  // The companion bootstrap block, in either spelling - a document produced before the
  // Portable -> Shareable rename carries the legacy anchor. The two anchors must use the SAME
  // spelling (a backreference), so a mixed pair can never make the match span from a real
  // bootstrap into an authored quotation of the other spelling. The strip runs only in companion
  // mode: a self-contained document has no real bootstrap, so there is nothing to remove and a
  // literal anchor pair inside authored CONTENT must be left alone.
  if (NONSHAREABLE_MODE) {
    t = t.replace(/<!--\s*BEGIN: commentable-html - NON(SHAREABLE|PORTABLE) BOOTSTRAP[\s\S]*?END: commentable-html - NON\1 BOOTSTRAP\s*-->\s*/i, "");
  }
  // Remove the HTML-comment regions. The END anchor requires its own "<!-- ... END ... -->"
  // comment: embedded comment notes escape every "<" as \u003c, so a note can never forge
  // a "<!--". That prevents note text like "END: commentable-html - EMBEDDED COMMENTS -->"
  // from terminating the region early and leaking the comments that follow it.
  ["HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI"].forEach(function (name) {
    t = t.replace(new RegExp("<!--\\s*=*\\s*BEGIN: commentable-html - " + name +
      "[\\s\\S]*?<!--\\s*=*\\s*END: commentable-html - " + name + "\\s*=*\\s*-->"), "");
  });
  // The JS region sits last. Opened from file://, fetch() is blocked so
  // _getBaseHtml() returns a DOM snapshot taken while THIS script runs - the
  // parser has not reached the trailing "END ... JS" comment yet, so anchor on
  // the script's own closing tag instead (eat a trailing END marker if present).
  t = t.replace(new RegExp("<!--\\s*=*\\s*BEGIN: commentable-html - JS[\\s\\S]*?"
    + _cmhScriptClosePattern() + "\\s*(?:<!--\\s*=*\\s*END: commentable-html - JS\\s*-->)?"), "");
  // NonShareable mode loads the runtime from a companion <script src> file; drop only the
  // JS companion (the CSS companion <link> stays so the content keeps its styling).
  t = t.replace(/[ \t]*<!--\s*commentable-html - layer loaded[^\n]*-->\s*/i, "");
  t = t.replace(_cmhScriptTagPattern("[^>]*commentable-html[^>]*\\.js[^>]*", "\\s*", "ig"), "");
  t = t.replace(/[ \t]*<!--\s*END: commentable-html - JS\s*-->\s*/i, "");
  t = _stripTransientBodyClasses(t);
  // Data-safety net: the layer's own comment-data blocks must be gone. Judge that against the
  // CONTENT-ROOT BOUNDARY rather than the document text: a script inside the content root that
  // borrows a reserved id is authored content (CMH-EXP-19), which no region strip can remove and
  // which must not make a legitimate export abort.
  const leak = _cmhPlainLeakedBlocks(t, baseHtml);
  if (leak.leak) {
    // Name the actual cause: which block survived, and where it sits relative to the region that
    // was supposed to carry it away (CMH-EXP-21). A contested boundary is not a marker problem
    // either, and sending the author after malformed markers when the fix is a duplicate id (or a
    // block that was never in the region) wastes their time.
    throw new Error(leak.contested ? _CMH_CONTESTED_ROOT_ERROR : _cmhPlainLeakMessage(leak.leak));
  }
  return t.replace(/\n{3,}/g, "\n\n");
}
function _suggestedPlainFilename() {
  const p = location.pathname;
  let name = p.substring(p.lastIndexOf("/") + 1);
  try { name = decodeURIComponent(name); } catch (e) { /* keep raw */ }
  if (!name || !/\.html?$/i.test(name)) name = "document.html";
  const m = name.match(/^(.*?)(\.html?)$/i);
  return m[1].replace(/-comments$/i, "") + ".plain" + m[2];
}
async function saveAsPlain() {
  let baseHtml;
  try { baseHtml = await _getBaseHtml(); }
  catch (e) { _reportExportFailure(e, _EXPORT_FAILURE_LOAD); return; }
  try {
    baseHtml = _applyChecklistStateToHtml(baseHtml);
    baseHtml = _applyNoteStateToHtml(baseHtml);
  } catch (e) { _reportExportFailure(e, _EXPORT_FAILURE_PREPARE); return; }
  let text;
  try { text = _buildPlainHtml(baseHtml); }
  catch (e) { _reportExportBuildFailure(e); return; }
  const filename = _suggestedPlainFilename();
  try { _downloadHtml(text, filename); }
  catch (e) { _reportExportFailure(e, _EXPORT_FAILURE_DOWNLOAD); return; }
  showToast("Downloaded " + filename + " (plain HTML, comment layer removed).", { center: true });
}
const _btnSaveHtml = document.getElementById("btnSaveHtml");
const _btnSaveHtmlTop = document.getElementById("btnSaveHtmlTop");
// "Export as Shareable" always downloads ONE combined/standalone file
// with the current comments embedded: saveStandalone() rebuilds an inline file in
// nonshareable mode and falls back to the in-file embed for inline documents.
if (_btnSaveHtml) _btnSaveHtml.addEventListener("click", saveStandalone);
if (_btnSaveHtmlTop) _btnSaveHtmlTop.addEventListener("click", saveStandalone);
const _btnSavePlain = document.getElementById("btnSavePlain");
const _btnSavePlainTop = document.getElementById("btnSavePlainTop");
if (_btnSavePlain) _btnSavePlain.addEventListener("click", saveAsPlain);
if (_btnSavePlainTop) _btnSavePlainTop.addEventListener("click", saveAsPlain);
