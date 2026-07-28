/* ---------- Wide-table horizontal scroll containment ---------- */
// Table cells wrap with `overflow-wrap: break-word` rather than `anywhere` (CMH-RESP-10), which is
// what stops a column being collapsed to one character and its text shredded - `break-word` is
// IGNORED for min-content sizing, so a cell keeps its longest-word width. The cost is the other
// half of the same coin: a table whose columns genuinely cannot fit now reports a min-content
// width LARGER than its container, escapes its box, and pushes the whole document sideways.
//
// So every table renders inside its own horizontal scroll box, which is the containment mobile
// already had, now at every width. Two deliberate choices:
//   - A wrapper ELEMENT, not `display:block; overflow-x:auto` on the table itself. `display:block`
//     wraps the rows in an anonymous table box that SHRINK-TO-FITS, collapsing a narrow table's
//     columns to their content width (measured: a 2-column table fell from 400px to 99px). The
//     wrapper leaves the table a real table, so `width:100%` still fills the column.
//   - The wrapper carries the table's margins so margin collapsing against the surrounding blocks
//     is unchanged; `overflow-x:auto` makes the wrapper a BFC, which would otherwise trap the
//     table's own margins inside it and change the spacing around every table.
// It adds no text nodes, so every stored comment offset is untouched (see 10-offsets.js).
const TABLE_SCROLL_CLASS = "cmh-table-scroll";
const TABLE_SCROLL_LABEL = "Scrollable table - use the arrow keys to scroll";

function _tableScrollName(wrap) {
  // Only a caption of a table the wrapper DIRECTLY holds names it: `querySelector("table > caption")`
  // would happily return a NESTED table's caption and label the outer region with it.
  const cap = _tableScrollTables(wrap).map(function (t) {
    return Array.prototype.find.call(t.children, function (c) { return c.tagName === "CAPTION"; });
  }).find(Boolean);
  const text = cap ? cap.textContent.replace(/\s+/g, " ").trim() : "";
  return text ? text + " (table)" : "Table";
}
function _tableScrollTables(wrap) {
  return Array.prototype.filter.call(wrap.children, function (c) { return c.tagName === "TABLE"; });
}
// Keyboard reachability is conditional ON the measurement: a scroll region that cannot be focused is
// unusable without a mouse (WCAG 2.1.1), but a focusable wrapper around a table that fits would be a
// dead tab stop on every ordinary table in the document. This follows the same ownership convention
// as the gallery-card scroll affordance (`markGalleryCardScrollable` in 20-mermaid.js): never clobber
// an attribute the author set, and on the way back out clear ONLY what we added. Ownership is tracked
// PER ATTRIBUTE rather than all-or-nothing, because an author who labels their own wrapper must still
// get the tab stop - refusing to touch the element at all would leave a scrolling region no keyboard
// user can reach, which is exactly the barrier this is here to remove.
var TABLE_SCROLL_A11Y = [
  ["tabindex", function () { return "0"; }],
  ["role", function () { return "group"; }],
  ["aria-label", _tableScrollName],
  ["aria-description", function () { return TABLE_SCROLL_LABEL; }],
];
// The VALUE we last wrote for each attribute we own, so ownership survives a regenerated name. The
// attribute's mere presence cannot decide this: once we set `aria-label`, "is it set?" is true
// forever, so a caption that changes later would leave assistive technology reading the old one, and
// on the way out the stale value would look like an author edit and be preserved permanently.
const _tableScrollOwnedValues = new WeakMap();
function _syncTableScrollState() {
  root.querySelectorAll("." + TABLE_SCROLL_CLASS).forEach(function (wrap) {
    const scrolls = wrap.scrollWidth > wrap.clientWidth + 1;
    const mine = _tableScrollOwnedValues.get(wrap) || {};
    if (scrolls) {
      const owned = [];
      TABLE_SCROLL_A11Y.forEach(function (pair) {
        const name = pair[0];
        const want = pair[1](wrap);
        const has = wrap.hasAttribute(name);
        if (has && !(name in mine)) return;                       // the author's own value, untouched
        if (has && wrap.getAttribute(name) !== mine[name]) {       // the author overwrote ours - relinquish
          delete mine[name];
          return;
        }
        if (!has || wrap.getAttribute(name) !== want) wrap.setAttribute(name, want);
        mine[name] = want;
        owned.push(name);
      });
      _tableScrollOwnedValues.set(wrap, mine);
      // Always stamped while scrolling, even when the author supplied every attribute themselves and
      // the owned list is empty, because the focus-ring rule keys off the attribute's presence.
      wrap.setAttribute("data-cmh-scroll-a11y", owned.join(" "));
    } else if (wrap.hasAttribute("data-cmh-scroll-a11y")) {
      Object.keys(mine).forEach(function (name) {
        // Only take back a value still equal to the one we wrote: an author who overwrote it since
        // owns it now, and clearing theirs would be a silent clobber.
        if (wrap.getAttribute(name) !== mine[name]) return;
        wrap.removeAttribute(name);
        delete mine[name];
      });
      _tableScrollOwnedValues.set(wrap, mine);
      wrap.removeAttribute("data-cmh-scroll-a11y");
    }
  });
}
let _tableScrollSyncPending = false;
function _scheduleTableScrollSync() {
  if (_tableScrollSyncPending) return;
  _tableScrollSyncPending = true;
  const run = function () { _tableScrollSyncPending = false; _syncTableScrollState(); };
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(run); else setTimeout(run, 0);
}
let _tableScrollResizeObserver = null;
// Wrap every author table not already in a scroll box, then (re)observe the boxes. Safe to re-run:
// the guards make it a no-op once everything is wrapped and observing an element twice is a no-op.
function _wrapTablesForScroll() {
  // A wrapper WE created and that has since been emptied (its table was moved away - a table used
  // directly as a draggable widget part, say) is dead weight carrying margins, so it is pruned. Only
  // our own: an author's `<div class="cmh-table-scroll">` may be an intentionally empty mount point
  // that a later author script fills, and deleting it would break them.
  root.querySelectorAll("." + TABLE_SCROLL_CLASS + "[data-cmh-wrap]").forEach(function (wrap) {
    if (!wrap.querySelector("table")) wrap.remove();
  });
  root.querySelectorAll("table").forEach(function (t) {
    // A table already inside a scroll box - authored that way, or the INNER table of a nested pair
    // whose outer table is wrapped - is left alone, so wrappers never nest.
    if (t.closest("." + TABLE_SCROLL_CLASS)) return;
    // A table that IS a draggable widget part is moved between slots by the widget layer; wrapping
    // it would put a box between the part and the slot it is dropped into.
    if (t.hasAttribute("data-cm-part")) return;
    if (!t.parentNode) return;
    const wrap = document.createElement("div");
    wrap.className = TABLE_SCROLL_CLASS;
    wrap.setAttribute("data-cmh-wrap", "1");
    _carryLayoutItemStyles(t, wrap);
    t.parentNode.insertBefore(wrap, t);
    wrap.appendChild(t);
  });
  if (!_tableScrollResizeObserver) return;
  root.querySelectorAll("." + TABLE_SCROLL_CLASS).forEach(function (wrap) {
    // Observe the wrapper (its width changes with the viewport) AND every table it directly holds
    // (their width changes when late content lands - a rendered diagram, a loaded image, a web
    // font). An author-authored wrapper may hold more than one table, so observe them all.
    _tableScrollResizeObserver.observe(wrap);
    _tableScrollTables(wrap).forEach(function (t) { _tableScrollResizeObserver.observe(t); });
  });
}
// In a flex or grid parent the WRAPPER becomes the layout item, so placement the author put on the
// table (`grid-column: 2 / 4`, `order: -1`, `align-self`) would silently stop applying. Carry the
// resolved placement onto the wrapper so the table keeps the position the author asked for.
var TABLE_SCROLL_ITEM_PROPS = [
  "order", "grid-column", "grid-row", "align-self", "justify-self",
  "flex-grow", "flex-shrink", "flex-basis",
];
function _carryLayoutItemStyles(table, wrap) {
  const parent = table.parentElement;
  if (!parent || typeof getComputedStyle !== "function") return;
  const display = getComputedStyle(parent).display;
  if (!/(^|\s)(inline-)?(flex|grid)$/.test(display)) return;
  const cs = getComputedStyle(table);
  TABLE_SCROLL_ITEM_PROPS.forEach(function (prop) {
    const v = cs.getPropertyValue(prop);
    if (v) wrap.style.setProperty(prop, v);
  });
}
// A table can arrive AFTER startup: author content scripts are placed after the layer's JS region
// (see charts-embedding.md), so a document that builds a table at runtime would otherwise keep an
// unwrapped table and push the page sideways again - the original defect. A table can equally be
// REMOVED at runtime, which would strand our wrapper and its margins as a blank gap, so both
// directions re-run the pass. Re-entrancy is not a hazard: wrapping and pruning mutate the DOM and
// re-enter this callback, but the second pass finds nothing left to do and stops.
function _watchForLateTables() {
  if (typeof MutationObserver !== "function") return;
  const holdsTable = function (node) {
    return node.nodeType === 1 &&
      (node.tagName === "TABLE" || !!(node.querySelector && node.querySelector("table")));
  };
  const mo = new MutationObserver(function (records) {
    for (const rec of records) {
      for (const node of rec.addedNodes) {
        if (!holdsTable(node)) continue;
        _wrapTablesForScroll();
        _scheduleTableScrollSync();
        return;
      }
      for (const node of rec.removedNodes) {
        if (!holdsTable(node)) continue;
        _wrapTablesForScroll();
        _scheduleTableScrollSync();
        return;
      }
    }
  });
  mo.observe(root, { childList: true, subtree: true });
}
function setupTableScroll() {
  if (setupTableScroll._done) return;   // idempotent - never install a second observer/listener
  setupTableScroll._done = true;
  if (typeof ResizeObserver === "function") {
    _tableScrollResizeObserver = new ResizeObserver(_scheduleTableScrollSync);
  } else {
    window.addEventListener("resize", _scheduleTableScrollSync);
  }
  _wrapTablesForScroll();
  _watchForLateTables();
  _syncTableScrollState();
}
