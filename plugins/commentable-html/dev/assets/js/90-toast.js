/* ---------- Toast ---------- */
let toastTimer = null;
function showToast(msg, opts) {
  opts = opts || {};
  // Set the live-region role/politeness BEFORE mutating the text so the announcement fires. The
  // #toast element also ships as a polite live region (see template.shell.html) so the FIRST toast
  // of the session is announced - a live region added in the same tick as its first text change is
  // not announced by most screen readers. Errors upgrade to an assertive alert.
  if (opts.alert) { toast.setAttribute("role", "alert"); toast.setAttribute("aria-live", "assertive"); }
  else { toast.setAttribute("role", "status"); toast.setAttribute("aria-live", "polite"); }
  toast.textContent = msg;
  toast.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), opts.duration || 3000);
}

