function cmhPreferenceMenus() {
  return [
    cmhLayerBlock(document, "toolbarMenu"),
    cmhLayerBlock(document, "sidebarMoreMenu"),
  ].filter(Boolean);
}

function cmhPreferenceRow(menu, kind) {
  const ids = menu.id === "toolbarMenu"
    ? {
        "auto-open": "btnAutoOpenPanelTop",
        "auto-open-override": "btnAutoOpenPanelOverrideTop",
        "utc-times": "btnUtcTimesTop",
      }
    : {
        "auto-open": "btnAutoOpenPanel",
        "auto-open-override": "btnAutoOpenPanelOverride",
        "utc-times": "btnUtcTimes",
      };
  return menu.querySelector('[data-cmh-pref="' + kind + '"]')
    || menu.querySelector("#" + ids[kind]);
}

function cmhSyncPreferenceRows() {
  const pinned = autoOpenPanelOverride();
  cmhPreferenceMenus().forEach((menu) => {
    const prefDefault = cmhPreferenceRow(menu, "auto-open");
    const prefOverride = cmhPreferenceRow(menu, "auto-open-override");
    const prefUtc = cmhPreferenceRow(menu, "utc-times");
    if (prefDefault) prefDefault.setAttribute("aria-checked", autoOpenPanelDefault() ? "true" : "false");
    if (prefUtc) prefUtc.setAttribute("aria-checked", utcTimesEnabled() ? "true" : "false");
    if (!prefOverride) return;
    prefOverride.setAttribute("aria-checked", pinned === null ? "false" : "true");
    const label = prefOverride.querySelector(".cm-menu-check-label");
    if (label) {
      label.textContent = pinned === null
        ? "Override for this document"
        : ("Override for this document: " + (pinned ? "On" : "Off"));
    }
  });
}

function cmhWirePreferenceMenu(menu) {
  if (!menu) return;
  const rows = [
    [cmhPreferenceRow(menu, "auto-open"), () => setAutoOpenPanelDefault(!autoOpenPanelDefault())],
    [cmhPreferenceRow(menu, "auto-open-override"), () => (
      setAutoOpenPanelOverride(autoOpenPanelOverride() === null ? !autoOpenPanelDefault() : null)
    )],
    [cmhPreferenceRow(menu, "utc-times"), () => setUtcTimes(!utcTimesEnabled())],
  ];
  rows.forEach((pair) => {
    const el = pair[0];
    const toggle = pair[1];
    if (!el) return;
    el.addEventListener("click", (e) => {
      e.__cmhKeepMenuOpen = true;
      if (toggle() === false && typeof showToast === "function") {
        showToast("Could not save that preference - this browser's storage is full or blocked.", {
          alert: true,
          duration: 8000,
          action: (typeof openStorageManager === "function")
            ? { label: "Manage storage", onClick: function () { openStorageManager(); } }
            : null,
        });
      }
      cmhSyncPreferenceRows();
    });
  });
}

window.addEventListener("storage", (e) => {
  if (!e || e.key == null || e.key === AUTO_OPEN_PANEL_KEY || e.key === AUTO_OPEN_PANEL_DOC_KEY
    || e.key === UTC_TIMES_KEY) cmhSyncPreferenceRows();
});

/* ---------- Toolbar overflow menu (declutters the save/export actions) ---------- */
(function () {
  const btn = cmhEl("btnToolbarMenu");
  const menu = cmhEl("toolbarMenu");
  if (!btn || !menu) return;
  const badge = cmhEl("cmhModeBadge");
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
    // Activating this link closes the menu it lives in, so hand focus to the still-visible
    // trigger rather than letting the browser drop it on <body> (the CMH-UI-13 contract).
    const headMark = cmBrandSiteMark("cm-toolbar-menu-brand");
    headMark.addEventListener("click", () => { setOpen(false); btn.focus(); });
    head.appendChild(headMark);
  }
  // The same brand link sits in the collapsed toolbar, immediately left of this menu's trigger.
  const more = btn.closest(".cm-toolbar-more");
  const bar = more && more.parentNode;
  if (bar && !bar.querySelector(":scope > a.cm-brand-link")) {
    bar.insertBefore(cmBrandSiteMark("cm-toolbar-brand"), more);
  }
  function setOpen(open) {
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      cmhSyncPreferenceRows();
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
  cmhWirePreferenceMenu(menu);
  btn.addEventListener("click", (e) => { e.stopPropagation(); setOpen(menu.hidden); });
  menu.addEventListener("click", (e) => { if (!e.__cmhKeepMenuOpen) setOpen(false); });
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target) && !btn.contains(e.target)) setOpen(false);
  });
  // Escape is handled centrally (toolbar menu has priority) in the global keydown
  // listener above, so it is not duplicated here.
})();

/* ---------- Sidebar export menu ---------- */
(function () {
  const btn = cmhEl("btnSidebarExportMenu");
  const menu = cmhEl("sidebarExportMenu");
  if (!btn || !menu) return;
  function setOpen(open) {
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      const other = cmhEl("sidebarMoreMenu");
      if (other) other.hidden = true;
      const otherBtn = cmhEl("btnMoreMenu");
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
  const btn = cmhEl("btnMoreMenu");
  const menu = cmhEl("sidebarMoreMenu");
  if (!btn || !menu) return;
  function setOpen(open) {
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      const other = cmhEl("sidebarExportMenu");
      if (other) other.hidden = true;
      const otherBtn = cmhEl("btnSidebarExportMenu");
      if (otherBtn) otherBtn.setAttribute("aria-expanded", "false");
      cmhSyncPreferenceRows();
      setRovingTabStop(null);
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
  cmhWirePreferenceMenu(menu);
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = menu.hidden;
    setOpen(open);
    // The menu-button pattern: opening moves focus INTO the menu, so the arrows and the single tab
    // stop are usable immediately (Escape and focus-out put focus back on the trigger).
    if (open) focusItem(items(), 0);
  });
  // A click on a Preferences row FLAGS itself instead of stopping propagation, so the menu stays
  // open for the second scope without also hiding the click from every other document-level
  // listener (the selection popup, the deck's click-to-advance bookkeeping).
  menu.addEventListener("click", (e) => { if (!e.__cmhKeepMenuOpen) setOpen(false); });
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target) && !btn.contains(e.target)) setOpen(false);
  });

  cmhSyncPreferenceRows();

  // Roving focus across the menu's items (Up/Down/Home/End) with ONE tab stop, the pattern
  // role="menu" implies (and the one #contextMenu already uses): the items carry tabindex="-1" and
  // the currently-focused item is promoted to tabindex="0", so Tab reaches the menu once and the
  // arrows walk it.
  function items() {
    return Array.prototype.slice.call(menu.querySelectorAll("button:not([disabled])"))
      .filter((el) => !el.hidden && (el.getClientRects().length > 0 || el === document.activeElement));
  }
  function setRovingTabStop(target) {
    const list = items();
    const stop = (target && list.indexOf(target) >= 0) ? target : list[0];
    list.forEach((el) => el.setAttribute("tabindex", el === stop ? "0" : "-1"));
  }
  function focusItem(list, index) {
    if (!list.length) return;
    const el = list[(index + list.length) % list.length];
    setRovingTabStop(el);
    try { el.focus(); } catch (e) { /* focus can be refused while the menu is closing */ }
  }
  menu.addEventListener("focusin", (e) => {
    if (e.target && e.target.tagName === "BUTTON") setRovingTabStop(e.target);
  });
  // Tabbing out of an open menu must dismiss it, or focus lands behind a still-open popover. A
  // null relatedTarget is a programmatic blur (or a window blur), which is not a move OUT.
  menu.addEventListener("focusout", (e) => {
    const to = e.relatedTarget;
    if (!to || menu.contains(to) || btn.contains(to)) return;
    setOpen(false);
  });
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
  // Opening the menu leaves focus on the trigger, so the arrows must reach in from there too -
  // otherwise the roving focus is only usable after a Tab.
  btn.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    if (menu.hidden) setOpen(true);
    const list = items();
    if (!list.length) return;
    e.preventDefault();
    focusItem(list, e.key === "ArrowDown" ? 0 : list.length - 1);
  });
})();
