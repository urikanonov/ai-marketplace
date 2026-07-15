/* ---------- Save as plain HTML (strip the comment layer) ---------- */
// Produces a standalone copy of the document with the commenting *ability* removed but
// its appearance intact: the HTML-comment regions (HANDLED IDS, EMBEDDED COMMENTS,
// COMMENT UI) and the runtime JS are deleted, while every stylesheet is kept - the
// inline CSS region (or the nonportable companion <link>) carries the document's own
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
  const layerDescriptorScript = new RegExp("[ \\t]*<scr" + "ipt\\b[^>]*\\sid\\s*=\\s*([\"'])"
    + "commentableHtmlLayer\\1[^>]*>[\\s\\S]*?<\\/scr" + "ipt>\\s*", "i");
  t = t.replace(layerDescriptorScript, "");
  t = t.replace(/<!--\s*BEGIN: commentable-html - NONPORTABLE BOOTSTRAP[\s\S]*?END: commentable-html - NONPORTABLE BOOTSTRAP\s*-->\s*/i, "");
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
  // NonPortable mode loads the runtime from a companion <script src> file; drop only the
  // JS companion (the CSS companion <link> stays so the content keeps its styling).
  t = t.replace(/[ \t]*<!--\s*commentable-html - layer loaded[^\n]*-->\s*/i, "");
  t = t.replace(_cmhScriptTagPattern("[^>]*commentable-html[^>]*\\.js[^>]*", "\\s*", "ig"), "");
  t = t.replace(/[ \t]*<!--\s*END: commentable-html - JS\s*-->\s*/i, "");
  t = _stripTransientBodyClasses(t);
  // Data-safety net: the comment-data scripts must be gone. If a malformed or hand-edited
  // marker made a region strip miss, fail loudly instead of downloading a plain file that
  // still leaks the comments.
  if (/id\s*=\s*["'](?:handledCommentIds|embeddedComments)["']/.test(t)) {
    throw new Error("Plain export aborted: the comment regions could not be fully removed (malformed markers?).");
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
  showToast("Downloaded " + filename + " (plain HTML, comment layer removed).");
}
const _btnSaveHtml = document.getElementById("btnSaveHtml");
const _btnSaveHtmlTop = document.getElementById("btnSaveHtmlTop");
// "Export as Portable" always downloads ONE combined/standalone file
// with the current comments embedded: saveStandalone() rebuilds an inline file in
// nonportable mode and falls back to the in-file embed for inline documents.
if (_btnSaveHtml) _btnSaveHtml.addEventListener("click", saveStandalone);
if (_btnSaveHtmlTop) _btnSaveHtmlTop.addEventListener("click", saveStandalone);
const _btnSavePlain = document.getElementById("btnSavePlain");
const _btnSavePlainTop = document.getElementById("btnSavePlainTop");
if (_btnSavePlain) _btnSavePlain.addEventListener("click", saveAsPlain);
if (_btnSavePlainTop) _btnSavePlainTop.addEventListener("click", saveAsPlain);

