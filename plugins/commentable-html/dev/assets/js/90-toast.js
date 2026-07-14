/* ---------- Toast ---------- */
let toastTimer = null;
function showToast(msg, opts) {
  opts = opts || {};
  toast.textContent = msg;
  // Screen readers: errors are announced assertively as an alert, normal status politely.
  if (opts.alert) { toast.setAttribute("role", "alert"); toast.setAttribute("aria-live", "assertive"); }
  else { toast.setAttribute("role", "status"); toast.setAttribute("aria-live", "polite"); }
  toast.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), opts.duration || 3000);
}

