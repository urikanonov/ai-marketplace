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

