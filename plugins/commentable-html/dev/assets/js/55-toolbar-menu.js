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
    const ver = document.createElement("span");
    ver.className = "cm-version cm-menu-version";
    ver.title = "commentable-html version that generated this file";
    ver.textContent = "v" + CMH_VERSION;
    head.appendChild(ver);
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
    if (open && window.__cmhPrioritizeEscapePopup) window.__cmhPrioritizeEscapePopup(popup);
  }
  const popup = {
    isOpen: () => !menu.hidden,
    close: () => {
      setOpen(false);
      btn.focus();
    },
  };
  if (window.__cmhRegisterEscapePopup) window.__cmhRegisterEscapePopup(popup);
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
    if (open) {
      const other = document.getElementById("sidebarMoreMenu");
      if (other) other.hidden = true;
      const otherBtn = document.getElementById("btnMoreMenu");
      if (otherBtn) otherBtn.setAttribute("aria-expanded", "false");
      if (window.__cmhPrioritizeEscapePopup) window.__cmhPrioritizeEscapePopup(popup);
    }
  }
  const popup = {
    isOpen: () => !menu.hidden,
    close: () => {
      setOpen(false);
      btn.focus();
    },
  };
  if (window.__cmhRegisterEscapePopup) window.__cmhRegisterEscapePopup(popup);
  btn.addEventListener("click", (e) => { e.stopPropagation(); setOpen(menu.hidden); });
  menu.addEventListener("click", () => setOpen(false));
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target) && !btn.contains(e.target)) setOpen(false);
  });
})();

/* ---------- Sidebar More menu (preferences + manage storage + clear) ---------- */
(function () {
  const btn = document.getElementById("btnMoreMenu");
  const menu = document.getElementById("sidebarMoreMenu");
  if (!btn || !menu) return;
  function setOpen(open) {
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      const other = document.getElementById("sidebarExportMenu");
      if (other) other.hidden = true;
      const otherBtn = document.getElementById("btnSidebarExportMenu");
      if (otherBtn) otherBtn.setAttribute("aria-expanded", "false");
      syncPrefRows();
      if (window.__cmhPrioritizeEscapePopup) window.__cmhPrioritizeEscapePopup(popup);
    }
  }
  const popup = {
    isOpen: () => !menu.hidden,
    close: () => {
      setOpen(false);
      btn.focus();
    },
  };
  if (window.__cmhRegisterEscapePopup) window.__cmhRegisterEscapePopup(popup);
  btn.addEventListener("click", (e) => { e.stopPropagation(); setOpen(menu.hidden); });
  menu.addEventListener("click", () => setOpen(false));
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target) && !btn.contains(e.target)) setOpen(false);
  });

  /* Preferences group: "Auto-open panel on comment" is the CROSS-DOCUMENT default, and the nested
     "Override for this document" row decides the scope. Unchecked, this document follows the row
     above it; checked, it pins the value that DIFFERS from the default (the only override a
     reviewer can act on) and its label carries that document-local state, while the default row
     keeps showing the untouched default. Both rows are role=menuitemcheckbox, so activation
     toggles in place and the menu stays open for the second scope. Older files carry a More menu
     without these rows, so every lookup is guarded. */
  const prefDefault = document.getElementById("btnAutoOpenPanel");
  const prefOverride = document.getElementById("btnAutoOpenPanelOverride");
  function syncPrefRows() {
    if (prefDefault) prefDefault.setAttribute("aria-checked", autoOpenPanelDefault() ? "true" : "false");
    if (!prefOverride) return;
    const pinned = autoOpenPanelOverride();
    prefOverride.setAttribute("aria-checked", pinned === null ? "false" : "true");
    const label = prefOverride.querySelector(".cm-menu-check-label");
    if (label) {
      label.textContent = pinned === null
        ? "Override for this document"
        : ("Override for this document: " + (pinned ? "On" : "Off"));
    }
  }
  function wirePrefRow(el, toggle) {
    if (!el) return;
    el.addEventListener("click", (e) => {
      // Keep the menu open: a reviewer often sets the default and the override in one visit.
      e.stopPropagation();
      toggle();
      syncPrefRows();
    });
  }
  wirePrefRow(prefDefault, () => setAutoOpenPanelDefault(!autoOpenPanelDefault()));
  wirePrefRow(prefOverride, () => {
    setAutoOpenPanelOverride(autoOpenPanelOverride() === null ? !autoOpenPanelDefault() : null);
  });
  syncPrefRows();

  // Roving focus across the menu's items (Up/Down/Home/End), the arrow behavior a menu is expected
  // to have once it holds checkable rows. Tab order is untouched, so every item stays tabbable too.
  function items() {
    return Array.prototype.slice.call(menu.querySelectorAll("button:not([disabled])"))
      .filter((el) => el.offsetParent !== null || el === document.activeElement);
  }
  function focusItem(list, index) {
    if (!list.length) return;
    const el = list[(index + list.length) % list.length];
    try { el.focus(); } catch (e) { /* focus can be refused while the menu is closing */ }
  }
  menu.addEventListener("keydown", (e) => {
    if (menu.hidden) return;
    const list = items();
    if (!list.length) return;
    const cur = list.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); focusItem(list, cur < 0 ? 0 : cur + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); focusItem(list, cur < 0 ? list.length - 1 : cur - 1); }
    else if (e.key === "Home") { e.preventDefault(); focusItem(list, 0); }
    else if (e.key === "End") { e.preventDefault(); focusItem(list, list.length - 1); }
  });
})();
