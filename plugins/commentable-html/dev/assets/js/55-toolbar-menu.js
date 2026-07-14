/* ---------- Toolbar overflow menu (declutters the save/export actions) ---------- */
(function () {
  const btn = document.getElementById("btnToolbarMenu");
  const menu = document.getElementById("toolbarMenu");
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
  // Escape is handled centrally (toolbar menu has priority) in the global keydown
  // listener above, so it is not duplicated here.
})();

