/* ---------- Sidebar open/close ---------- */
function updateSidebarToggle() {
  const btn = document.getElementById("btnToggleSidebar");
  if (!btn) return;
  const open = document.body.classList.contains("sidebar-open");
  btn.textContent = open ? "Hide" : "Show";
  btn.setAttribute("aria-expanded", open ? "true" : "false");
}
function _syncSidebarInert() {
  const sb = document.getElementById("sidebar");
  if (sb) sb.inert = !document.body.classList.contains("sidebar-open");
}
function _syncFloatingAfterLayoutShift() {
  // Opening/closing the panel reflows .app (its padding changes), so any floating
  // add-comment button or highlight bubble is now at a stale position. Re-pin them.
  repositionActiveAdd();
  if (!hlBubble.hidden) {
    if (hlBubbleMark && root.contains(hlBubbleMark)) positionHlBubble(hlBubbleMark);
    else { hlBubble.hidden = true; hlBubbleCid = null; hlBubbleMark = null; }
  }
}
function openSidebar()  { document.body.classList.add("sidebar-open"); updateSidebarToggle(); _syncSidebarInert(); _syncFloatingAfterLayoutShift(); }
function closeSidebar() { document.body.classList.remove("sidebar-open"); updateSidebarToggle(); _syncSidebarInert(); _syncFloatingAfterLayoutShift(); }
document.getElementById("btnToggleSidebar").addEventListener("click", () => { document.body.classList.toggle("sidebar-open"); updateSidebarToggle(); _syncSidebarInert(); _syncFloatingAfterLayoutShift(); });
document.getElementById("btnCloseSidebar").addEventListener("click", closeSidebar);
(function () {
  // "Show" entry in the overflow menu reopens the panel (the menu's own click handler
  // closes the menu). Redundant with the toolbar toggle but discoverable from the menu.
  const b = document.getElementById("btnShowTop");
  if (b) b.addEventListener("click", openSidebar);
})();

