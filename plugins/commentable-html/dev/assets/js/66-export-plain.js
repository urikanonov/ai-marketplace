/* ---------- Save as plain HTML (strip the comment layer) ---------- */
// The layer's own data blocks, judged by the CONTENT-ROOT BOUNDARY rather than by a document-wide
// text scan: a script inside the content root that borrows a reserved id is authored content
// (CMH-EXP-19), which no region strip can remove and which must not make a legitimate export
// abort. The descriptor is in the list because an export that declares a mode maintains ADDITIONAL
// descriptor copies in the layer's region (CMH-EXP-18), and a "plain" copy that still declares
// itself a commentable-html document with a mode would be a silent leak.
const _CMH_PLAIN_DATA_IDS = ["handledCommentIds", "embeddedComments", "reviewedSections", "commentableHtmlLayer"];
function _cmhPlainLeakedState(html) {
  const src = String(html == null ? "" : html);
  // Cheap probe on the bare ids (not a quoted-attribute pattern, which an unquoted `id=...` would
  // slip past), so the ordinary export never pays for a second parse.
  if (!/handledCommentIds|embeddedComments|reviewedSections|commentableHtmlLayer/.test(src)) {
    return { leaked: false, contested: false };
  }
  const doc = new DOMParser().parseFromString(src, "text/html");
  const state = cmhContentRootState(doc);
  const leaked = _CMH_PLAIN_DATA_IDS.some(function (id) {
    const owners = cmhLayerIdOwners(doc, id);
    // A contested boundary cannot tell the layer's blocks from content, so every owner counts:
    // fail closed rather than ship comment data in a copy that claims to carry none.
    if (state.contested) return owners.length > 0;
    return owners.some(function (node) { return !(state.root && state.root.contains(node)); });
  });
  return { leaked: leaked, contested: state.contested };
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
  const leak = _cmhPlainLeakedState(t);
  if (leak.leaked) {
    // Name the actual cause. A contested boundary is not a marker problem, and sending the author
    // after malformed markers when the fix is a duplicate id wastes their time.
    throw new Error(leak.contested
      ? _CMH_CONTESTED_ROOT_ERROR
      : "Plain export aborted: the comment regions could not be fully removed (malformed markers?).");
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
  catch (e) { showToast("Could not load base HTML."); return; }
  baseHtml = _applyChecklistStateToHtml(baseHtml);
  baseHtml = _applyNoteStateToHtml(baseHtml);
  let text;
  try { text = _buildPlainHtml(baseHtml); }
  catch (e) { showToast(e.message); return; }
  const filename = _suggestedPlainFilename();
  _downloadHtml(text, filename);
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
