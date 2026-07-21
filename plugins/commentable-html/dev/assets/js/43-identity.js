/* ---------- Reviewer identity (author attribution) ---------- */
// The browser cannot reveal the OS/system user to a page, so the reviewer's display name
// is a per-browser value the reader sets once. It is stored in localStorage and can be
// seeded by the author with data-cm-author on #commentRoot (e.g. a document generated
// "for Bob"). Editing the name affects only FUTURE comments; past comments keep the
// author stamped when they were written.
const CMH_AUTHOR_KEY = "cmh::author";
const CMH_MAX_AUTHOR_LEN = 60;
// Author names are UNTRUSTED (they can travel embedded in a shared file). Strip control
// characters/newlines and cap the length so a name can never inject a line into the DOM,
// the Copy-all bundle, or a Markdown/print export. The value is additionally escapeHtml'd
// at every DOM sink and neutralized again in the Copy-all label lines.
function _sanitizeAuthor(name) {
  return String(name == null ? "" : name)
    .replace(/[\r\n\t\f\v\u0000-\u001f\u007f\u0085\u2028\u2029]+/g, " ")
    .trim().slice(0, CMH_MAX_AUTHOR_LEN);
}
let _cmAuthorName = null;
function getAuthorName() {
  if (_cmAuthorName != null) return _cmAuthorName;
  let stored = null;
  try { stored = localStorage.getItem(CMH_AUTHOR_KEY); } catch (e) { /* private mode */ }
  // A stored value - INCLUDING an explicitly-cleared "" - wins over the data-cm-author seed, so
  // clearing your name stays cleared across reload instead of the author seed resurrecting it.
  const n = (stored !== null) ? stored
    : ((root && root.getAttribute) ? (root.getAttribute("data-cm-author") || "") : "");
  _cmAuthorName = _sanitizeAuthor(n);
  return _cmAuthorName;
}
function setAuthorName(name) {
  _cmAuthorName = _sanitizeAuthor(name);
  try { localStorage.setItem(CMH_AUTHOR_KEY, _cmAuthorName); } catch (e) { /* private mode */ }
  if (typeof updateIdentityUi === "function") updateIdentityUi();
  return _cmAuthorName;
}
// Stamp the current reviewer name onto a freshly-created comment or reply. Only sets the
// field when a name exists, so migrated/legacy comments stay unattributed and the pill is
// simply omitted for them.
function stampAuthor(comment) {
  const a = getAuthorName();
  if (a) comment.author = a;
  return comment;
}
// A stable hue (0-359) derived from the name, so each reviewer gets a consistent pill
// color and two different names are visually distinguishable. Same name -> same color.
function _authorHue(name) {
  const s = String(name || "");
  let h = 0;
  for (let i = 0; i < s.length; i++) { h = (h * 31 + s.charCodeAt(i)) >>> 0; }
  return h % 360;
}
// The author pill markup (escaped). Returns "" for an empty/unset name so unattributed
// comments render without a pill.
function authorPillHtml(name) {
  const nm = _sanitizeAuthor(name);
  if (!nm) return "";
  return '<span class="cm-author-pill" style="--cm-author-hue:' + _authorHue(nm) + '"'
    + ' title="Comment author">' + escapeHtml(nm) + "</span>";
}

// ---- Identity control (sidebar) ----
function _identityEls() {
  return {
    row: document.getElementById("cmIdentity"),
    nameEl: document.getElementById("cmIdentityName"),
    editBtn: document.getElementById("btnEditIdentity"),
    editBox: document.getElementById("cmIdentityEdit"),
    input: document.getElementById("cmIdentityInput"),
    saveBtn: document.getElementById("btnSaveIdentity"),
    cancelBtn: document.getElementById("btnCancelIdentity"),
  };
}
function updateIdentityUi() {
  const els = _identityEls();
  if (!els.nameEl) return;
  const nm = getAuthorName();
  if (nm) {
    els.nameEl.innerHTML = authorPillHtml(nm);
    els.nameEl.classList.remove("cm-identity-unset");
    if (els.editBtn) els.editBtn.textContent = "change";
  } else {
    els.nameEl.textContent = "set your name";
    els.nameEl.classList.add("cm-identity-unset");
    if (els.editBtn) els.editBtn.textContent = "set name";
  }
}
function _identityEditing(on) {
  const els = _identityEls();
  if (!els.editBox) return;
  // When leaving edit mode, if focus is still inside the (about-to-hide) editor, return it to the
  // control that opened the editor so keyboard focus is never dropped to <body>.
  const returnFocus = !on && els.editBox.contains(document.activeElement);
  els.editBox.hidden = !on;
  if (els.nameEl) els.nameEl.hidden = on;
  if (els.editBtn) els.editBtn.hidden = on;
  if (returnFocus && els.editBtn) { try { els.editBtn.focus(); } catch (e) {} }
}
function beginEditIdentity(focus) {
  const els = _identityEls();
  if (!els.input) return;
  els.input.value = getAuthorName();
  _identityEditing(true);
  if (focus !== false) setTimeout(() => { try { els.input.focus(); els.input.select(); } catch (e) {} }, 0);
}
function commitEditIdentity() {
  const els = _identityEls();
  if (!els.input) return;
  const nm = setAuthorName(els.input.value);
  _identityEditing(false);
  updateIdentityUi();
  showToast(nm ? ("You are commenting as \"" + nm + "\". This applies to new comments only.")
                : "Name cleared. New comments will be unattributed.");
}
function cancelEditIdentity() {
  _identityEditing(false);
}
function setupIdentityControl() {
  const els = _identityEls();
  if (!els.row) return;
  if (els.editBtn) addListener(els.editBtn, "click", beginEditIdentity);
  if (els.saveBtn) addListener(els.saveBtn, "click", commitEditIdentity);
  if (els.cancelBtn) addListener(els.cancelBtn, "click", cancelEditIdentity);
  if (els.input) {
    addListener(els.input, "keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); commitEditIdentity(); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancelEditIdentity(); }
    });
  }
  updateIdentityUi();
}
// First-comment nudge: the first time a reader opens a new-comment composer without a name
// set, reveal the identity editor so they can attribute their comments. Non-blocking - the
// comment can still be saved unattributed, and later comments pick up the name.
let _cmIdentityNudged = false;
function maybeNudgeIdentity() {
  if (_cmIdentityNudged) return;
  if (getAuthorName()) return;
  if (!document.getElementById("cmIdentity")) return;
  _cmIdentityNudged = true;
  // Reveal the identity editor so it is visible once the sidebar opens (adding a comment
  // opens it). Do not steal focus, open the sidebar, or toast - that would disrupt an
  // in-progress composer draft. The comment can still be saved unattributed.
  beginEditIdentity(false);
}
