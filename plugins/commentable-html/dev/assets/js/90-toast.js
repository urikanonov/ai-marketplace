/* ---------- Toast ---------- */
let toastTimer = null;
const _cmhStartupDiagnostics = [];
let _cmhStartupDiagnosticFlushPending = false;
function hideToast() {
  toast.classList.remove("show");
  // Remove any inline action button when the toast is dismissed/times out so an invisible, faded-out
  // control cannot intercept clicks or receive Tab focus while it lingers in the DOM until the next
  // toast replaces the content.
  const b = toast.querySelector(".cm-toast-action");
  if (b) b.remove();
}
// Only the layer's OWN dialogs count as a modal. Every runtime modal is appended in exactly one
// shape - body > .cm-modal-overlay > [aria-modal="true"] - so the query is anchored to it: the
// annotated document is untrusted author content, and an authored lookalike nested in the page must
// not be able to suppress the recovery action or make the click guard refuse a real one. The CSS
// rule that hides the action is scoped to the same shape.
function _cmhOwnModalBox() {
  const boxes = document.querySelectorAll('body > .cm-modal-overlay > [aria-modal="true"]');
  return boxes.length ? boxes[boxes.length - 1] : null;
}
// A control that can really take focus right now: connected, enabled, not inert, and actually ON
// SCREEN. The rect must INTERSECT the viewport, not merely be non-empty: the side pane is hidden by
// `transform: translateX(100%)`, so a control inside a closed pane keeps its size and would pass a
// bare width/height test while sitting entirely off screen - and that pane is marked `inert` while
// closed, so focus() on anything inside it is a silent no-op even mid-transition. The toast's own
// button is excluded - it is removed the moment its action runs.
function _cmhFocusableControl(el) {
  if (!el || el === document.body || el === document.documentElement) return null;
  if (!el.isConnected || typeof el.focus !== "function" || el.disabled || el.hidden) return null;
  if (el.closest && (el.closest(".cm-toast") || el.closest("[inert]"))) return null;
  if (typeof el.getClientRects === "function" && !el.getClientRects().length) return null;
  const r = el.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  const vw = window.innerWidth || document.documentElement.clientWidth || 0;
  const vh = window.innerHeight || document.documentElement.clientHeight || 0;
  if (r.right <= 0 || r.bottom <= 0 || r.left >= vw || r.top >= vh) return null;
  return el;
}
// The ordered controls focus may be handed back to, best first: the caller's preferred target, then
// the stable chrome triggers that carry "Manage storage" in the first place. The on-screen test
// above is what picks the RIGHT one of the two menu triggers - exactly one of the side pane's More
// button and the floating toolbar's is on screen in either pane state.
function _cmhRestoreCandidates(el) {
  const out = [];
  const first = _cmhFocusableControl(el);
  if (first) out.push(first);
  const fallbacks = ["#btnMoreMenu", "#btnToolbarMenu", "#btnToggleSidebar"];
  for (let i = 0; i < fallbacks.length; i++) {
    const cand = _cmhFocusableControl(document.querySelector(fallbacks[i]));
    if (cand && out.indexOf(cand) === -1) out.push(cand);
  }
  return out;
}
// Where focus belongs when a dialog that a toast action opened closes again. hideToast() removes the
// action button BEFORE the handler runs, so a dialog snapshotting document.activeElement would
// snapshot <body> and its restore-on-close would be a no-op (issue #939).
function cmhFocusRestoreTarget(el) {
  const cands = _cmhRestoreCandidates(el);
  return cands.length ? cands[0] : null;
}
// Hand focus back, CONFIRMING it landed: focus() is silent when its target cannot take it (hidden,
// inert, or removed since it was chosen), so a candidate that turns out to be unfocusable falls
// through to the next rather than stranding a keyboard reviewer on <body>.
function cmhRestoreFocusTo(el) {
  const cands = _cmhRestoreCandidates(el);
  for (let i = 0; i < cands.length; i++) {
    try { cands[i].focus({ preventScroll: true }); } catch (e) { try { cands[i].focus(); } catch (e2) {} }
    if (document.activeElement === cands[i]) return true;
  }
  return false;
}
function _cmhFlushStartupDiagnostics() {
  _cmhStartupDiagnosticFlushPending = false;
  const diagnostics = _cmhStartupDiagnostics.splice(0, _cmhStartupDiagnostics.length);
  if (!diagnostics.length || typeof toast === "undefined" || !toast || toast.nodeType !== 1) return;
  if (diagnostics.length === 1) {
    showToast(diagnostics[0].msg, diagnostics[0].opts);
    return;
  }
  const combined = diagnostics.map(function (item, i) {
    return (i + 1) + ". " + item.msg;
  }).join(" ");
  const combinedOpts = {
    alert: true,
    duration: diagnostics.reduce(function (longest, item) {
      return Math.max(longest, item.opts.duration || 3000);
    }, 3000),
  };
  const actionItem = diagnostics.find(function (item) { return !!item.opts.action; });
  if (actionItem) combinedOpts.action = actionItem.opts.action;
  showToast("Startup diagnostics: " + combined, combinedOpts);
}
function showStartupDiagnostic(msg, opts) {
  opts = opts || {};
  if (!_cmhStartupDiagnostics.some(function (item) { return item.msg === msg; })) {
    _cmhStartupDiagnostics.push({ msg: msg, opts: opts });
  }
  if (_cmhStartupDiagnosticFlushPending) return;
  _cmhStartupDiagnosticFlushPending = true;
  // The reserved-block audit registers its DOMContentLoaded listener before this module. Deferring
  // one turn after that event lets its timer join the synchronous startup diagnostics regardless of
  // how long parsing the document tail takes.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      setTimeout(_cmhFlushStartupDiagnostics, 0);
    }, { once: true });
  } else {
    setTimeout(_cmhFlushStartupDiagnostics, 0);
  }
}
function showToast(msg, opts) {
  opts = opts || {};
  // Focus as it stood BEFORE the toast, for the action handler's restore target below.
  const priorFocus = document.activeElement;
  // Set the live-region role/politeness BEFORE mutating the text so the announcement fires. The
  // #toast element also ships as a polite live region (see template.shell.html) so the FIRST toast
  // of the session is announced - a live region added in the same tick as its first text change is
  // not announced by most screen readers. Errors upgrade to an assertive alert.
  if (opts.alert) { toast.setAttribute("role", "alert"); toast.setAttribute("aria-live", "assertive"); }
  else { toast.setAttribute("role", "status"); toast.setAttribute("aria-live", "polite"); }
  // A centered toast is used for export confirmations so it is impossible to miss.
  if (opts.center) toast.classList.add("cm-toast-center");
  else toast.classList.remove("cm-toast-center");
  toast.textContent = "";
  const span = document.createElement("span");
  span.textContent = msg;
  toast.appendChild(span);
  // Optional inline action button (e.g. "Manage storage" on a storage-full toast). Clicking it
  // dismisses the toast and runs the handler.
  if (opts.action && opts.action.label && typeof opts.action.onClick === "function") {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "cm-toast-action";
    btn.textContent = opts.action.label;
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      // An aria-modal dialog owns focus and hides everything outside it from assistive tech, so the
      // action must not run from out here (the CSS hides it then, and openStorageManager() would
      // refuse anyway while one is already open, leaving focus stranded on <body> outside the
      // dialog's trap). Hand focus back INTO the dialog instead of acting. Blur FIRST: the reclaim
      // helper deliberately leaves focus alone when it is on a surface that paints above the overlay
      // - a toast is exactly that - so with the button still focused it would do nothing.
      const modal = _cmhOwnModalBox();
      if (modal) {
        try { btn.blur(); } catch (err) { /* best-effort */ }
        if (typeof _keepModalFocus === "function") _keepModalFocus(modal);
        return;
      }
      if (toastTimer) clearTimeout(toastTimer);
      // Resolve the restore target while focus is still meaningful: hideToast() removes this button
      // and drops document.activeElement to <body>.
      const restore = cmhFocusRestoreTarget(_cmhFocusableControl(document.activeElement) || priorFocus);
      hideToast();
      opts.action.onClick(restore);
    });
    toast.appendChild(btn);
  }
  toast.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, opts.duration || 3000);
}

// Announce each export with a centered toast so it is obvious which export is running. A single
// capture-phase listener covers every export code path (both the sidebar Export menu and the
// collapsed toolbar overflow menu), and fires before the export handler so the toast is visible
// even for the synchronous print dialog.
(function () {
  const EXPORT_LABELS = {
    btnSaveHtml: "Shareable", btnSaveHtmlTop: "Shareable",
    btnExportOffline: "Offline", btnExportOfflineTop: "Offline",
    btnExportMd: "Markdown", btnExportMdTop: "Markdown",
    btnSavePlain: "Plain HTML", btnSavePlainTop: "Plain HTML",
    btnPrint: "PDF", btnPrintTop: "PDF",
  };
  // Resolve the controls by IDENTITY once at startup - the very elements the layer's own export
  // handlers bound themselves to, resolved the same way (`getElementById`) at the same point in the
  // bundle. The annotated document is untrusted author content, so keying the announcement on the
  // clicked button's ID instead would let a content `<button id="btnPrint">` announce an export that
  // never runs, telling a reviewer the document was exported when nothing was. An element that is
  // not one of these is not an export control, whatever id it carries.
  const EXPORT_CONTROLS = new Map();
  Object.keys(EXPORT_LABELS).forEach(function (id) {
    const el = cmhEl(id);
    if (el) EXPORT_CONTROLS.set(el, EXPORT_LABELS[id]);
  });
  document.addEventListener("click", function (e) {
    const btn = e.target && e.target.closest ? e.target.closest("button") : null;
    if (!btn) return;
    const label = EXPORT_CONTROLS.get(btn);
    if (!label) return;
    // An open comment dialog swallows an outside pointer click to close itself, so the export
    // handler never runs. Ask the dialog's OWN predicate rather than re-deriving the condition
    // here, so the toast can never announce an export that will not happen - nor suppress one
    // that will. A keyboard-activated click (detail 0) is never swallowed, so it still announces.
    if (cmhPopoverWouldSwallowClick(e)) return;
    showToast("Exporting as " + label + "...", { center: true, duration: 2500 });
  }, true);
})();
