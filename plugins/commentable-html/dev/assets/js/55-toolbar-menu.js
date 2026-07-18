/* ---------- Toolbar overflow menu (declutters the save/export actions) ---------- */
(function () {
  const btn = document.getElementById("btnToolbarMenu");
  const menu = document.getElementById("toolbarMenu");
  if (!btn || !menu) return;
  const badge = document.getElementById("cmhModeBadge");
  if (badge && !menu.querySelector(".cm-toolbar-menu-head")) {
    const head = document.createElement("div");
    head.className = "cm-toolbar-menu-head";
    badge.parentNode.insertBefore(head, badge);
    head.appendChild(badge);
    const brand = document.createElement("span");
    brand.className = "cm-toolbar-menu-brand";
    brand.setAttribute("aria-hidden", "true");
    brand.innerHTML = CMH_ICON_SVG;
    const svg = brand.querySelector("svg");
    if (svg) {
      svg.setAttribute("aria-hidden", "true");
      svg.setAttribute("focusable", "false");
      svg.removeAttribute("role");
      svg.removeAttribute("aria-label");
      svg.removeAttribute("data-cmh-tip");
    }
    head.appendChild(brand);
  }
  function setOpen(open) {
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  }
  btn.addEventListener("click", (e) => { e.stopPropagation(); setOpen(menu.hidden); });
  menu.addEventListener("click", () => setOpen(false));
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target) && !btn.contains(e.target)) setOpen(false);
  });
  // Escape is handled centrally (toolbar menu has priority) in the global keydown
  // listener above, so it is not duplicated here.
})();

/* ---------- Sidebar export menu ---------- */
(function () {
  const btn = document.getElementById("btnSidebarExportMenu");
  const menu = document.getElementById("sidebarExportMenu");
  if (!btn || !menu) return;
  function setOpen(open) {
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  }
  btn.addEventListener("click", (e) => { e.stopPropagation(); setOpen(menu.hidden); });
  menu.addEventListener("click", () => setOpen(false));
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target) && !btn.contains(e.target)) setOpen(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || menu.hidden) return;
    e.preventDefault();
    setOpen(false);
    btn.focus();
  });
})();
