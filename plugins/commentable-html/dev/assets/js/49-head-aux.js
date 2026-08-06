/* ---------- Sidebar header scroll region (`.head-aux`) keyboard reachability ---------- */
// The header's transient/meta rows live in a BOUNDED scroll region so the header can never push
// the comment list off the bottom of the pane (CMH-RESP-16). Every CONTROL in it is focusable, so
// tabbing already scrolls a control into view - but `.cm-side-info` (Generated / Last comment) is
// plain text with nothing to focus, which would leave a sighted keyboard-only reviewer unable to
// scroll it into view once the region genuinely scrolls. So the region takes a tab stop and a name
// WHILE it scrolls, and gives them back when it does not, exactly as the table-scroll wrapper does
// (`61-table-scroll.js`, CMH-RESP-11). Unlike that wrapper this element is the layer's own - it
// only ever comes from the shell template - so there is no author attribute to negotiate over.
(function () {
  const aux = document.querySelector(".cm-sidebar .head-aux");
  if (!aux) return;
  const A11Y = [
    ["tabindex", "0"],
    ["role", "group"],
    // Named for what is ALWAYS in it. The search row and the identity editor are both hidden most
    // of the time, so enumerating them would announce a "search" that is not there.
    ["aria-label", "Panel details"],
    ["aria-description", "Scrollable region. Use the arrow keys to scroll."],
  ];
  let on = null;
  function sync() {
    // Observe any row added since the last pass; `observe` on an already-observed element is a
    // no-op, so this stays idempotent.
    if (ro) Array.prototype.forEach.call(aux.children, function (row) { ro.observe(row); });
    const scrolls = aux.scrollHeight > aux.clientHeight + 1;
    if (scrolls === on) return;
    on = scrolls;
    A11Y.forEach(function (pair) {
      if (scrolls) aux.setAttribute(pair[0], pair[1]);
      else aux.removeAttribute(pair[0]);
    });
    if (scrolls) aux.setAttribute("data-cmh-scroll-a11y", "");
    else aux.removeAttribute("data-cmh-scroll-a11y");
  }
  // The region scrolls when its own box shrinks (a short viewport) OR when a transient row opens
  // and grows its content, so watch both the region and each row it holds.
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(sync) : null;
  if (ro) ro.observe(aux);
  sync();
  window.addEventListener("resize", sync);
  // A row is shown/hidden with the `hidden` attribute, which a ResizeObserver reports only once the
  // box actually changes; observing the attribute too makes the toggle synchronous with the click.
  // `childList` covers a row added or removed later, which neither observer would otherwise see.
  if (typeof MutationObserver === "function") {
    new MutationObserver(sync).observe(aux, {
      attributes: true, subtree: true, childList: true,
      attributeFilter: ["hidden", "style", "class"],
    });
  }
})();
