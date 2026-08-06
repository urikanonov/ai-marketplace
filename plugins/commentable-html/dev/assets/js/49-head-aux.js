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
    ["aria-label", "Panel details: search, document info and your name"],
    ["aria-description", "Scrollable region. Use the arrow keys to scroll."],
  ];
  let on = null;
  function sync() {
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
  sync();
  // The region scrolls when its own box shrinks (a short viewport) OR when a transient row opens
  // and grows its content, so watch both the region and each row it holds.
  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(sync);
    ro.observe(aux);
    Array.prototype.forEach.call(aux.children, function (row) { ro.observe(row); });
  }
  window.addEventListener("resize", sync);
  // A row is shown/hidden with the `hidden` attribute, which a ResizeObserver reports only once the
  // box actually changes; observing the attribute too makes the toggle synchronous with the click.
  if (typeof MutationObserver === "function") {
    new MutationObserver(sync).observe(aux, { attributes: true, subtree: true, attributeFilter: ["hidden", "style", "class"] });
  }
})();
