/* ---------- Editable notes fields (one free-text field per data-cmh-note) ----------
   A [data-cmh-note] element becomes an editable plain-text field (a <textarea>) whose baseline
   is its authored, normalized textContent. Edits are stored as a minimal per-document delta under
   COMMENT_KEY + "::note" ({id:text}) - only notes whose current text differs from baseline - and
   surface as one per-note change card (jump + reset) in the sidebar, a Copy-all NOTES_STATE_JSON
   line, and an export bake into the element's text. The field is cm-skip so editing never creates a
   highlight, and it is set up before offset restoration so its (excluded) text does not shift
   existing comment offsets. A single/multi-line toggle switches the field height. The normalizer is
   defined identically in tools/notes/notes_apply.py so the browser and the cementing tool agree. */
const CMH_NOTE_KEY = COMMENT_KEY + "::note";
const notes = [];
// Object.create(null) for consistency with the checklist maps (defense-in-depth); a plain
// string-valued map keyed by note id was confirmed not pollutable, but keep the same shape.
let _noteOverrides = Object.create(null);   // { [noteId]: currentText } loaded from storage before setup
let _noteHadChanges = false;
let _noteSeq = 0;

// The one canonical text model, shared with notes_apply.py: normalize newlines to LF and trim the
// outer whitespace; internal newlines and spaces are preserved.
function normalizeNote(s) {
  return String(s == null ? "" : s).replace(/\r\n?/g, "\n").trim();
}
function _noteCurrent(note) {
  return normalizeNote(note.textarea.value);
}
function _noteLoad() {
  _noteOverrides = Object.create(null);
  let raw = null;
  try { raw = localStorage.getItem(CMH_NOTE_KEY); } catch (e) { raw = null; }
  let data = {};
  try { data = raw ? JSON.parse(raw) : {}; } catch (e) { data = {}; }
  if (!data || typeof data !== "object") return;
  Object.keys(data).forEach((id) => { if (typeof data[id] === "string") _noteOverrides[id] = data[id]; });
}
function _noteSave() {
  const out = {};
  notes.forEach((note) => {
    const cur = _noteCurrent(note);
    if (cur !== note.baseline) out[note.id] = cur;
  });
  try {
    if (Object.keys(out).length) localStorage.setItem(CMH_NOTE_KEY, JSON.stringify(out));
    else localStorage.removeItem(CMH_NOTE_KEY);
    return true;
  } catch (e) {
    showToast("Note edits NOT saved to this browser (storage full or blocked) - they will be lost on reload.",
      { alert: true, duration: 8000 });
    return false;
  }
}
// Changed notes only, one record per note (mirrors checklistChanges()).
function notesChanges() {
  const out = [];
  notes.forEach((note) => {
    const cur = _noteCurrent(note);
    if (cur !== note.baseline) out.push({ id: note.id, label: note.label, from: note.baseline, to: cur });
  });
  return out;
}
function _noteApplyMode(note) {
  const ta = note.textarea;
  ta.rows = note.multiline ? 4 : 1;
  note.container.classList.toggle("cmh-note-multiline", note.multiline);
  note.container.classList.toggle("cmh-note-single", !note.multiline);
  if (note.toggleBtn) {
    note.toggleBtn.textContent = note.multiline ? "single line" : "multi line";
    note.toggleBtn.title = note.multiline ? "Switch to a single-line field" : "Switch to a multi-line field";
    note.toggleBtn.setAttribute("aria-pressed", note.multiline ? "true" : "false");
  }
}
// A foldable note collapses to just its header line (the +/- toggle and label); expanding reveals the
// field on the line below. Collapse is session-only presentation, never persisted or exported. A badge
// marks a collapsed note that still holds content, so hidden text is discoverable.
function _noteApplyFold(note) {
  if (!note.foldable || !note.foldBtn) return;
  const collapsed = !!note.collapsed;
  const hasContent = normalizeNote(note.textarea.value) !== "";
  note.container.classList.toggle("cmh-note-collapsed", collapsed);
  note.container.classList.toggle("cmh-note-has-content", collapsed && hasContent);
  note.foldBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  note.foldBtn.setAttribute("aria-label", (collapsed ? "Expand note: " : "Collapse note: ") + note.label);
  note.foldBtn.title = collapsed ? "Show the note field" : "Hide the note field";
}
function _noteAfterChange() {
  _noteSave();
  _noteSyncUi();
  _noteFlushRender();
}
// Lightweight UI that must track a note edit IMMEDIATELY so it never lags the already-persisted
// text: the portability badge, the Copy-all affordance, and the one-time sidebar auto-open. These
// are only touched on the dirty-state TRANSITION (note-clean <-> note-dirty), never on every
// keystroke: updateDocTypeUi() and updateCopyAllState() each recompute widgetStateChanges(), a
// document-wide querySelectorAll, so calling them per keystroke would reintroduce O(document) work
// on a widget-bearing document (issue #505). Between transitions those states do not change, so a
// keystroke burst pays that scan at most once. notesChanges() is O(notes), cheap to check each key.
// Doing the auto-open here (not in the deferred flush) also means a user who closes the sidebar
// within the debounce window is not overridden by a late reopen.
function _noteSyncUi() {
  const has = notesChanges().length > 0;
  if (has === _noteHadChanges) return;
  _noteHadChanges = has;
  if (typeof updateDocTypeUi === "function") updateDocTypeUi();
  if (typeof updateCopyAllState === "function") updateCopyAllState();
  if (has && typeof openSidebar === "function") openSidebar();
}
// The expensive half of a note change: renderComments() runs two full-document tree walks (a
// getTextNodes walk per changed note plus the section-review scan), so it is O(document) and must
// not run on every keystroke. Programmatic changes (reset / clear-all) call it directly; the typing
// path (_noteOnInput) defers it behind a debounce.
function _noteFlushRender() {
  if (_noteRenderTimer) { clearTimeout(_noteRenderTimer); _noteRenderTimer = 0; }
  if (typeof renderComments === "function") renderComments();
}
// Coalesce a keystroke burst into ONE sidebar re-render (issue #505): typing in a note field re-ran
// the full-document scans per keystroke, freezing a large document. A note's document POSITION does
// not move while its text is edited, so the render is safely deferred until the reviewer pauses; the
// delta is persisted and the lightweight UI updated synchronously on every keystroke so no edit is
// lost and the badge/Copy-all affordance never lag.
const _NOTE_RENDER_DEBOUNCE_MS = 150;
let _noteRenderTimer = 0;
function _noteOnInput(note) {
  _noteSave();
  _noteSyncUi();
  if (_noteRenderTimer) clearTimeout(_noteRenderTimer);
  if (typeof setTimeout === "function") _noteRenderTimer = setTimeout(_noteFlushRender, _NOTE_RENDER_DEBOUNCE_MS);
  else _noteFlushRender();
}
function _notePreview(t) {
  const s = (t == null ? "" : String(t)).replace(/\s+/g, " ").trim();
  return s === "" ? "(empty)" : s;
}
// One card per changed note, shaped like a comment card (same .acts/data-act buttons and theme).
function _renderOneNoteCard(ch) {
  return `
    <article class="cm-card cm-card-note" data-cmh-note-name="${escapeHtml(ch.id)}">
      <div class="section">note: <strong>${escapeHtml(ch.label)}</strong></div>
      <div class="note cmh-note-diff">${escapeHtml(_notePreview(ch.from))} <span class="cmh-note-arrow">&rarr;</span> ${escapeHtml(_notePreview(ch.to))}</div>
      <div class="cmh-note-search" hidden>${escapeHtml(ch.label)} ${escapeHtml(ch.from)} ${escapeHtml(ch.to)}</div>
      <div class="note">Auto-tracked from the current note text. Included in Copy all so the agent can cement it into the source; the file stays Not portable until re-exported.</div>
      <div class="meta">
        <span></span>
        <span class="acts">
          <button type="button" data-act="note-jump" data-cmh-note-name="${escapeHtml(ch.id)}" title="Scroll to this note">jump</button>
          <button type="button" data-act="note-reset" data-cmh-note-name="${escapeHtml(ch.id)}" title="Revert this note to its authored text">reset</button>
        </span>
      </div>
    </article>`;
}
// Sidebar pieces for changed notes, tagged with a document-order position so the sidebar can
// interleave them with the comment cards (and the checklist cards) instead of pinning them on top.
function notesCardPieces() {
  const changes = notesChanges();
  if (!changes.length) return [];
  const byId = new Map();
  changes.forEach((ch) => byId.set(ch.id, ch));
  const pieces = [];
  notes.forEach((note) => {
    const ch = byId.get(note.id);
    if (!ch) return;
    let pos = 1e15;
    try { const o = offsetWithin(note.container, 0); if (typeof o === "number" && o >= 0) pos = o; } catch (e) { /* no text position */ }
    pieces.push({ pos, html: _renderOneNoteCard(ch) });
  });
  return pieces;
}
function resetNote(id) {
  const note = notes.find((n) => n.id === id);
  if (!note) return;
  note.textarea.value = note.baseline;
  _noteApplyFold(note);
  _noteAfterChange();
}
// Revert every changed note to its authored baseline (used by the global Clear all comments).
function resetAllNotes() {
  let any = false;
  notes.forEach((note) => {
    if (_noteCurrent(note) !== note.baseline) { note.textarea.value = note.baseline; _noteApplyFold(note); any = true; }
  });
  if (any) _noteAfterChange();
}
function jumpToNote(id) {
  const note = notes.find((n) => n.id === id);
  if (!note || !note.container) return;
  if (note.foldable && note.collapsed) { note.collapsed = false; _noteApplyFold(note); }
  if (typeof expandCollapsedAncestors === "function") expandCollapsedAncestors(note.container);
  note.container.scrollIntoView({ behavior: cmScrollBehavior(), block: "center" });
  note.container.classList.add("cmh-note-flash");
  setTimeout(() => note.container.classList.remove("cmh-note-flash"), 2200);
  try { note.textarea.focus(); } catch (e) { /* focus is best-effort */ }
}
// Bake each note's current text into its element so an exported file reflects the edits and opens
// with no pending change (mirrors _applyChecklistStateToHtml). textContent is used, never innerHTML,
// so reviewer text can never inject markup.
function _applyNoteStateToHtml(html) {
  if (!notes.length || !notesChanges().length) return html;
  const doc = new DOMParser().parseFromString(String(html || ""), "text/html");
  notes.forEach((note) => {
    const cur = _noteCurrent(note);
    if (cur === note.baseline) return;
    let el = null;
    try { el = doc.querySelector('[data-cmh-note="' + _cssEsc(note.id) + '"]'); } catch (e) { el = null; }
    if (el) {
      el.textContent = cur;
      el.removeAttribute("contenteditable");
      el.classList.remove("cmh-note-ready", "cm-skip", "cmh-note-single", "cmh-note-multiline",
        "cmh-note-collapsed", "cmh-note-has-content");
      if (!el.getAttribute("class")) el.removeAttribute("class");
    }
  });
  const doctype = /^\s*<!doctype/i.test(String(html || "")) ? "<!DOCTYPE html>\n" : "";
  return doctype + doc.documentElement.outerHTML;
}
function setupNotesLayer() {
  notes.length = 0;
  _noteLoad();
  root.querySelectorAll("[data-cmh-note]").forEach((el) => {
    const id = el.getAttribute("data-cmh-note") || "";
    if (!id) return;
    const baseline = normalizeNote(el.textContent);
    const label = el.getAttribute("data-cmh-note-label") || id;
    const multiline = String(el.getAttribute("data-cmh-note-multiline") || "").toLowerCase() === "true";
    const foldable = String(el.getAttribute("data-cmh-note-foldable") || "").toLowerCase() === "true";
    let ov = _noteOverrides[id];
    if (ov != null && normalizeNote(ov) === baseline) ov = null;   // reconcile a stale post-apply override
    const current = (ov != null) ? normalizeNote(ov) : baseline;

    el.classList.add("cm-skip", "cmh-note-ready");
    el.setAttribute("data-cmh-note-role", "field");
    el.textContent = "";

    const ta = document.createElement("textarea");
    ta.className = "cmh-note-input cm-skip";
    ta.id = "cmh-note-input-" + (++_noteSeq);
    ta.value = current;
    ta.spellcheck = false;
    ta.setAttribute("aria-label", label + " (editable note)");

    // A foldable note starts collapsed only when it is empty; a note with content (authored or a
    // persisted edit) starts expanded so the text is visible. Fold state is evaluated once here;
    // afterwards only user clicks and jumpToNote change it, so a manual collapse always sticks.
    const note = { id, label, container: el, textarea: ta, baseline, multiline, foldable,
                   collapsed: foldable && current === "", toggleBtn: null, foldBtn: null };

    const header = document.createElement("div");
    header.className = "cmh-note-head cm-skip";
    const chip = document.createElement("span");
    chip.className = "cmh-note-label";
    chip.textContent = label;
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "cmh-note-toggle cm-skip";
    toggle.setAttribute("data-cmh-note-toggle", "");
    toggle.addEventListener("click", (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      note.multiline = !note.multiline;
      _noteApplyMode(note);
      try { ta.focus(); } catch (e) { /* best-effort */ }
    });
    note.toggleBtn = toggle;
    if (foldable) {
      const fold = document.createElement("button");
      fold.type = "button";
      fold.className = "cmh-note-fold cm-skip";
      fold.setAttribute("data-cmh-note-fold", "");
      fold.setAttribute("aria-controls", ta.id);
      fold.addEventListener("click", (ev) => {
        ev.preventDefault(); ev.stopPropagation();
        note.collapsed = !note.collapsed;
        _noteApplyFold(note);
        if (!note.collapsed) { try { ta.focus(); } catch (e) { /* best-effort */ } }
      });
      note.foldBtn = fold;
      header.appendChild(fold);
    }
    header.appendChild(chip);
    header.appendChild(toggle);

    ta.addEventListener("input", () => _noteOnInput(note));

    el.appendChild(header);
    el.appendChild(ta);
    notes.push(note);
    _noteApplyMode(note);
    _noteApplyFold(note);
  });
  if (notes.length) _noteSave();   // prune any stale post-apply overrides that now equal baseline
  _noteHadChanges = notesChanges().length > 0;
}
