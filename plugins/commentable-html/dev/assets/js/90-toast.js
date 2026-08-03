/* ---------- Toast ---------- */
let toastTimer = null;
function hideToast() {
  toast.classList.remove("show");
  // Remove any inline action button when the toast is dismissed/times out so an invisible, faded-out
  // control cannot intercept clicks or receive Tab focus while it lingers in the DOM until the next
  // toast replaces the content.
  const b = toast.querySelector(".cm-toast-action");
  if (b) b.remove();
}
function showToast(msg, opts) {
  opts = opts || {};
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
      if (toastTimer) clearTimeout(toastTimer);
      hideToast();
      opts.action.onClick();
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
    const el = document.getElementById(id);
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

