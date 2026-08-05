(() => {
// Pristine snapshot of the document, captured before any DOM mutation
// (mermaid render, restored highlights, dynamic composers, etc). Used as a
// fallback by "Export as Shareable" when fetch() of the page URL is unavailable
// (e.g., file://, blocked fetch, or CSP). The snapshot is taken on the very first line
// of the IIFE so it predates every runtime change this script makes.
const SNAPSHOT_HTML = "<!DOCTYPE html>\n" + cmhSerializeElement(document.documentElement);
function cmhSerializableOpenShadowRoots(rootEl) {
  const roots = [];
  const visit = function (scope) {
    scope.querySelectorAll("*").forEach(function (el) {
      if (!el.shadowRoot) return;
      roots.push(el.shadowRoot);
      visit(el.shadowRoot);
    });
  };
  if (rootEl.shadowRoot) {
    roots.push(rootEl.shadowRoot);
    visit(rootEl.shadowRoot);
  }
  visit(rootEl);
  return roots;
}
function cmhSerializeElement(el) {
  if (!el || typeof el.getHTML !== "function") return el ? el.outerHTML : "";
  const inner = el.getHTML({
    serializableShadowRoots: true,
    shadowRoots: cmhSerializableOpenShadowRoots(el),
  });
  const shell = el.cloneNode(false).outerHTML;
  const close = "</" + el.tagName.toLowerCase() + ">";
  return shell.toLowerCase().endsWith(close)
    ? shell.slice(0, shell.length - close.length) + inner + close
    : shell;
}
// The layer runs synchronously during parse, so SNAPSHOT_HTML stops at THIS <script>:
// host content placed after the layer (per charts-embedding.md, chart data + init scripts land
// after the "END: commentable-html - JS" marker, before the final </body>) has not been
// parsed yet and is absent from the snapshot. Capture the script element now, while
// document.currentScript is still valid, so an export can recover that tail from the
// fully-parsed DOM (see _snapshotWithTail).
const CMH_LAYER_SCRIPT = document.currentScript;
// Layer chrome injected during init (footer, side-TOC, scroll progress) is captured in
// this set at the end of the IIFE - before the browser parses any host content that
// follows the layer <script> - so a file:// export tail can exclude it while keeping
// host content (which may itself be cm-skip, e.g. a chart <canvas>). See _snapshotWithTail.
const CMH_INJECTED_CHROME = new Set();

// Layer chrome that must not count as DOCUMENT TEXT. Deliberately SEPARATE from
// CMH_INJECTED_CHROME above: that set is populated partly by a heuristic sweep (every element
// sibling following the layer script, in 95-startup.js), which is fine for its job - trimming an
// export tail - because an over-capture there costs a stale tail. Membership HERE subtracts text
// from the document content hash, where an over-capture is silent and produces the exact false
// "not validated" banner the hash exists to prevent, so this set is populated only where the layer
// CREATES the node, by construction. Today that is the print appendix (83-print.js), the one pass
// that appends real prose into the content root; every other in-root control is cm-skip.
const CMH_HASH_EXCLUDED = new Set();

// The layer's OWN interactive chrome, held by IDENTITY. Some of it is injected INSIDE the content
// root (a sortable-table sort control, a widget "Reset moves", a checklist box), where containment
// cannot tell it from author content and a class match would let author content spoof its way past
// a guard. Registering each control where the layer CREATES it is the only test a document cannot
// fake. Register the interactive CONTROL itself, never a container that also holds inert or author
// content (a toolbar's label, the code wrap around an author `<pre>`, an author `[data-cmh-note]`
// container): membership below covers the whole subtree, so a container registration hands away the
// dismiss click on dead space for no functional gain. Consumed by the comment dialog's
// outside-click swallow (53-comment-popover.js).
const CMH_LAYER_CHROME = new WeakSet();
function cmhMarkLayerChrome(el) {
  if (!el || el.nodeType !== 1) return el;
  // Enforce the invariant rather than only documenting it: registering a node that IS or CONTAINS
  // the annotated document would exempt the whole document from the swallow, which is the one
  // mistake a future call site could make that silently disables the guard entirely.
  try {
    if (el === document.documentElement || el === document.body) return el;
    if (root && el.contains(root)) return el;
  } catch (e) { return el; }
  CMH_LAYER_CHROME.add(el);
  return el;
}
// Resolve the layer's OWN control inside `scope`, by IDENTITY rather than by class name. Every
// "does a control already exist here?" guard must go through this: an author element wearing a
// control's class would otherwise make the layer skip creating (or, worse, remove) the real
// control, silently denying the reviewer the affordance. The spoof gains nothing either way - it
// is never registered, so the dialog's outside-click swallow still treats it as document content.
function cmhOwnChrome(scope, selector) {
  if (!scope || typeof scope.querySelectorAll !== "function") return null;
  try {
    const list = scope.querySelectorAll(selector);
    for (let i = 0; i < list.length; i++) if (CMH_LAYER_CHROME.has(list[i])) return list[i];
  } catch (e) { return null; }
  return null;
}

// True when a click landed on, or inside, a registered chrome subtree. Prefers the EVENT's
// propagation path (fixed at dispatch) so a control another listener detaches mid-dispatch is still
// recognized, and falls back to the live ancestor chain where `composedPath` is unavailable.
function cmhClickHitsLayerChrome(target, path) {
  if (path) {
    for (let i = 0; i < path.length; i++) if (CMH_LAYER_CHROME.has(path[i])) return true;
    return false;
  }
  let el = target && target.nodeType === 1 ? target : (target && target.parentElement) || null;
  while (el) {
    if (CMH_LAYER_CHROME.has(el)) return true;
    el = el.parentElement;
  }
  return false;
}

// Scroll behavior that respects prefers-reduced-motion: JS scrollIntoView/scrollTo take a
// `behavior` option that OVERRIDES the CSS `scroll-behavior` reset, so every programmatic
// smooth scroll must consult this so motion-sensitive readers get an instant jump instead.
// Fails closed to "auto" (less motion) when the preference cannot be determined, since this is
// an accessibility affordance and an instant jump is never worse than an unwanted animation.
function cmScrollBehavior() {
  try {
    if (typeof window.matchMedia !== "function") return "auto";
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  } catch (e) { return "auto"; }
}

// ---- Authored-text preservation: permute children through the slots they ALREADY occupy ----
// Reordering elements by APPENDING them strands the whitespace text nodes an author leaves between
// them: the elements end up textually adjacent and the stranded whitespace piles up ahead of them.
// That is a text change no later "unsort" can undo (unsorting restores element ORDER, not the moved
// whitespace), so it silently drifted the document and section content hashes and made the same
// file show the "not validated" banner on one machine and not another (#952). Every reorder inside
// the content root goes through these helpers instead, so the class cannot reappear in a third copy
// of the slot math (#977): `ordered` is dropped into the slots its OWN members already occupy and
// every other child node stays exactly where the author put it.
//
// Both fail SAFE. Given anything that is not a permutation of nodes currently parented by `parent`
// (a foreign node, a duplicate) they decline, because an untouched DOM is always text-neutral while
// a partial rearrangement is not.
function _cmhSlotPlan(parent, ordered) {
  if (!parent || !ordered || ordered.length < 2) return null;
  const kids = Array.prototype.slice.call(parent.childNodes);
  const pos = new Map();
  for (let i = 0; i < kids.length; i++) pos.set(kids[i], i);
  const slots = [];
  for (let i = 0; i < ordered.length; i++) {
    if (!pos.has(ordered[i])) return null;
    slots.push(pos.get(ordered[i]));
  }
  if (new Set(slots).size !== slots.length) return null;
  slots.sort(function (a, b) { return a - b; });
  return { kids: kids, slots: slots };
}
// Pure READ: a copy of `parent`'s child nodes with `ordered` placed into its members' slots.
// Returns null when the input is not such a permutation, so a caller can fall back to the live
// order. Used by the canonical-hash scan, which must never touch the DOM.
function cmhPermutedChildNodes(parent, ordered) {
  const plan = _cmhSlotPlan(parent, ordered);
  if (!plan) return null;
  const out = plan.kids.slice();
  for (let i = 0; i < plan.slots.length; i++) out[plan.slots[i]] = ordered[i];
  return out;
}
// WRITE: apply that permutation to the DOM by swapping each member out for a placeholder comment
// and each placeholder back for the node that belongs in it. Returns true when the DOM changed;
// an identity reorder returns false without touching anything (the canonical-hash and export passes
// unsort EVERY sortable table, including ones the reader never sorted).
function cmhPermuteChildrenInSlots(parent, ordered) {
  const plan = _cmhSlotPlan(parent, ordered);
  if (!plan) return false;
  const members = plan.slots.map(function (s) { return plan.kids[s]; });
  let same = true;
  for (let i = 0; i < members.length; i++) if (members[i] !== ordered[i]) { same = false; break; }
  if (same) return false;
  const marks = members.map(function () { return document.createComment(""); });
  members.forEach(function (n, i) { parent.replaceChild(marks[i], n); });
  marks.forEach(function (m, i) { parent.replaceChild(ordered[i], m); });
  return true;
}
