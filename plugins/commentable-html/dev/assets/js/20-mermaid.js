/* ---------- Mermaid commenting layer ----------
   Lets the user click rendered diagram nodes inside
   pre.mermaid / div.mermaid blocks and attach a comment.
   Anchors by (diagramIndex, nodeKey) rather than text
   offsets. mermaid renders asynchronously, so a per-host
   MutationObserver waits for SVG insertion before
   attaching handlers and restoring highlights. */
const mermaidAddBtn = document.getElementById("mermaidAddBtn");
const mermaidDiagrams = [];
let pendingMermaid = null;
let mermaidAddHideTimer = null;
let mermaidActiveNode = null;
// The floating structural-anchor add-comment buttons (image / mermaid / diff / link /
// widget / heading) are position:fixed and positioned once at hover time. `_activeAdd`
// remembers the currently-shown one and how to re-run its positioning, so a
// scroll/resize can keep it pinned to its target (or hide it when the target scrolls out
// of view) instead of letting it drift.
let _activeAdd = null;
// Only ONE structural-anchor "Add Comment" affordance is shown at a time. Each layer owns
// its own floating button but shares `_activeAdd`; every layer reveals its button through
// setActiveAdd(), which hides and clears whichever OTHER layer's button was showing, so
// overlapping targets never leave two buttons up at once. For NESTED targets - the common
// clickable-thumbnail/logo <a><img></a>, where the image layer's <img> lives inside the
// link layer's <a> and hovering fires both - the INNERMOST element owns the affordance (so
// the image wins over the wrapping link), deterministically and regardless of hover-event
// order, so the reader ever sees exactly one button.
function setActiveAdd(entry) {
  const prev = _activeAdd;
  if (prev && prev.btn && prev.btn !== (entry && entry.btn)) {
    // The incoming target is an ANCESTOR of the active one AND that inner affordance is still
    // showing -> keep the inner (already-active) one and drop this outer one; _activeAdd is
    // unchanged. The `!prev.btn.hidden` gate is load-bearing: a layer's own hide timer hides
    // its button WITHOUT reassigning _activeAdd, so a stale (hidden) inner entry must not keep
    // winning the contains() check and suppress the enclosing layer forever (for example a link
    // inside a heading, once the link has been hovered and left).
    if (!prev.btn.hidden && prev.el && entry && entry.el && prev.el !== entry.el && entry.el.contains(prev.el)) {
      if (entry.btn) entry.btn.hidden = true;
      if (entry.clear) entry.clear();
      return;
    }
    // Otherwise the new affordance wins (a sibling target, the new one is the inner element, or
    // the previously-active button is already hidden): hide and clear that button first.
    prev.btn.hidden = true;
    if (prev.clear) prev.clear();
  }
  _activeAdd = entry;
}
// Clear the shared sentinel when a layer hides ITS OWN button on its hover/focus hide timer, so
// _activeAdd never points at a stale hidden button (the `btn === _activeAdd.btn` check makes this a
// no-op once the sentinel has moved on to another layer). This keeps the setActiveAdd() ancestor
// tie-break above, and the scroll repositioner in 52-hover-bubble.js, from consulting a
// no-longer-visible entry. The composer-open (click/keydown) paths also hide their button but do not
// call this; the `!prev.btn.hidden` guard in setActiveAdd() and the hidden-check in the repositioner
// already make any such briefly-stale entry harmless.
function clearActiveAdd(btn) {
  if (_activeAdd && _activeAdd.btn === btn) _activeAdd = null;
}
// True when the button's natural (unclamped) anchor sits comfortably on-screen. A
// scroll reposition hides a button whose target scrolled (partly) out of view rather
// than clamping it to a viewport edge, where it would look detached from its target.
function _addFits(left, top, w, h) {
  const vp = cmhViewportRect(8);
  return left >= vp.left && left <= vp.right - w &&
         top >= vp.top && top <= vp.bottom - h;
}
// Whether an anchor rect is at least partially within the viewport. Used to decide
// whether a floating add button should stay (anchor visible) or hide (anchor scrolled
// away). The button position itself is clamped on-screen separately, so an anchor near
// a viewport edge must NOT be treated as "gone".
function _rectInViewport(r) {
  const vp = cmhViewportRect(4);
  return r.width > 0 && r.height > 0 &&
    r.bottom > vp.top && r.top < vp.bottom &&
    r.right > vp.left && r.left < vp.right;
}
// The diagram-host shapes, normalized ONCE from the shared vocabulary (CMH_MERMAID_SEL,
// 03-selectors.js) rather than re-typed, so the clip layer cannot drift from the vocabulary the rest
// of the runtime indexes by. Empty tokens are dropped and a non-string vocabulary degrades to an
// empty list, matching `_printMermaidCapSel()`'s contract in 83-print.js: these tokens are spliced
// into selector LISTS, and one invalid selector makes a browser drop the whole list - here that
// means `closest()` THROWS and every floating control in the document dies at once. The comma split
// assumes CMH_MERMAID_SEL stays a list of simple compound selectors, which it is (a future entry
// with a comma inside `:is(...)` would need a real parser).
var MERMAID_HOST_TOKENS = (typeof CMH_MERMAID_SEL === "string" ? CMH_MERMAID_SEL : "")
  .split(",").map(function (s) { return s.trim(); }).filter(Boolean);
// The `.cmh-diagram-gallery` CARD shapes: a direct-child diagram host, or a direct-child <figure>
// wrapper.
var GALLERY_CARD_SEL = MERMAID_HOST_TOKENS.map(function (s) {
  return ".cmh-diagram-gallery > " + s;
}).concat([".cmh-diagram-gallery > figure"]).join(", ");
// The generic clip/scroll containers a floating control is clamped to, outside a gallery card. Built
// from the same normalized tokens: a literal `pre.mermaid` here left a standalone `div.mermaid` host
// unrecognised, and its Add button escaped the host's box (issue #769).
var CLIP_CONTAINER_SEL = MERMAID_HOST_TOKENS
  .concat([CMH_CHART_FIGURE_SEL, "table", ".cmh-diff-raw"]).filter(Boolean).join(", ");
// Both container vocabularies in one selector, so one walk finds every recognised box: the gallery
// CARD shapes (a direct child of `.cmh-diagram-gallery`, which includes a plain `<figure>` wrapper
// that the generic list does not name) and the generic clip/scroll containers. Every list is
// `filter(Boolean)`ed before it is joined: an absent vocabulary would otherwise leave an empty token
// (`", table, ..."`), and one invalid selector makes `closest()` THROW for every floating control in
// the document.
var CLIP_CHAIN_SEL = [GALLERY_CARD_SEL, CLIP_CONTAINER_SEL].filter(Boolean).join(", ");
// A recognised container only BOUNDS a control if it actually CLIPS. Everything the layer ships does
// (`overflow-x:auto` on both diagram hosts and `figure.chart`, the scrolling table wrapper, the
// gallery card), but a gallery card's inner `pre.mermaid` deliberately ships `overflow:visible` and
// grows to the diagram it holds, and an author can set `overflow:visible` on any of them. Bounding a
// control by a box its content legitimately spills out of would clip a control anchored to something
// the reader can plainly see - a risk that grew the moment the WHOLE chain started to count rather
// than only the nearest box. `display:contents` generates no box at all, so its empty rect would
// hide every control inside it.
function _clipsItsContent(el) {
  if (typeof getComputedStyle !== "function") return true;
  const cs = getComputedStyle(el);
  if (!cs) return true;
  if (cs.display === "contents") return false;
  return cs.overflowX !== "visible" || cs.overflowY !== "visible";
}
// EVERY recognised clip container around `node`, nearest first - not just the nearest one. Clipping
// composes: a diagram host can sit inside a scrolling table wrapper, a `figure.chart`, or a
// `.cmh-diff-raw`, and the OUTER box clips the inner one just as the inner box clips its content. A
// single `closest()` let the inner box SHADOW the outer scroller, so a control anchored to a target
// the outer box had scrolled out of view stayed visible over unrelated content (issue #823) - the
// defect issue #769 fixed, in reverse. Callers intersect the whole chain, which also subsumes the
// gallery-card case the old resolver hard-preferred: for a `<figure><pre class="mermaid">...</pre></figure>`
// card the button is now bounded by the figure's scroll card, so it can no longer detach while the
// figure scrolls.
function _clipContainersFor(node) {
  const el = node && (node.nodeType === 1 ? node : node.parentElement);
  if (!el || !el.closest) return [];
  const chain = [];
  let cur = el;
  while (cur) {
    const hit = cur.closest(CLIP_CHAIN_SEL);
    if (!hit) break;
    // A table is rendered inside a `.cmh-table-scroll` wrapper (61-table-scroll.js), and it is the
    // WRAPPER that scrolls and clips - the table itself can be wider than its visible box, so the
    // wrapper stands in for it. A bubble anchored to a cell scrolled out of view is then clipped
    // instead of being clamped to the full (over-wide) table rect. `closest` (not the immediate
    // parent) because an INNER table of a nested pair sits in a `td`, several levels below the
    // wrapper that actually clips it.
    const box = hit.tagName === "TABLE" ? (hit.closest(".cmh-table-scroll") || hit) : hit;
    if (chain.indexOf(box) === -1 && _clipsItsContent(box)) chain.push(box);
    cur = hit.parentElement;
  }
  return chain;
}
function _intersectRects(a, b) {
  const left = Math.max(a.left, b.left);
  const right = Math.min(a.right, b.right);
  const top = Math.max(a.top, b.top);
  const bottom = Math.min(a.bottom, b.bottom);
  if (right <= left || bottom <= top) return null;
  return { left, right, top, bottom, width: right - left, height: bottom - top };
}
function _clipAwareRect(node, rect) {
  let visible = _intersectRects(rect, cmhViewportRect(4));
  if (!visible) return null;
  const clips = _clipContainersFor(node);
  for (let i = 0; i < clips.length && visible; i++) {
    visible = _intersectRects(visible, clips[i].getBoundingClientRect());
  }
  return visible;
}
function _floatingBounds(node) {
  const viewport = cmhViewportRect(8);
  let bounds = viewport;
  const clips = _clipContainersFor(node);
  for (let i = 0; i < clips.length; i++) {
    // An empty intersection means the box is off-screen (or the chain does not overlap at all); the
    // control is already hidden by `_clipAwareRect()` in that case, so fall back to the viewport
    // rather than clamping to nothing.
    const next = _intersectRects(bounds, clips[i].getBoundingClientRect());
    if (!next) return viewport;
    bounds = next;
  }
  return bounds;
}
function _clamp(v, min, max) {
  if (max < min) return min;
  return Math.max(min, Math.min(v, max));
}
function cmRectContains(outer, inner) {
  return inner.left >= outer.left - 1 && inner.right <= outer.right + 1 &&
         inner.top >= outer.top - 1 && inner.bottom <= outer.bottom + 1;
}

// Commentable mermaid elements across diagram types. Flowchart uses g.node/g.cluster/
// g.edgeLabel; gantt/sequence expose text-bearing elements (task labels, messages,
// notes) which give stable, descriptive anchor keys. MERMAID_RENDERED_SEL is the wider
// "the diagram has painted meaningful content" probe used for readiness (a gantt has no
// g.node, so the flowchart-only probe never fired for it).
var MERMAID_NODE_SEL = "g.node, g.cluster, g.edgeLabel, .task, .taskText, .taskTextOutsideRight, .taskTextOutsideLeft, .taskTextOutsideCenter, .messageText, .noteText, .loopText, .actor";
// Readiness probe: every node-commentable element (svg-scoped) PLUS a couple of markers
// that only signal "rendered" (pie slices are paths that fall through to whole-diagram).
// Derived from MERMAID_NODE_SEL so the two can never drift.
var MERMAID_RENDERED_SEL = MERMAID_NODE_SEL.split(", ").map(function (s) { return "svg " + s; }).join(", ") + ", svg .pieCircle";

function indexMermaidDiagrams() {
  mermaidDiagrams.length = 0;
  const hosts = root.querySelectorAll(CMH_MERMAID_SEL);
  hosts.forEach((host, i) => {
    host.classList.add("cm-mermaid-host");
    host.dataset.cmMermaidIndex = String(i);
    // Preserve the diagram source for Markdown export before mermaid replaces the element
    // content with rendered SVG (after which textContent would be SVG text, not the source).
    if (!host.hasAttribute("data-cmh-md-src") && !host.querySelector("svg") && !host.hasAttribute("data-processed")) {
      host.setAttribute("data-cmh-md-src", host.textContent || "");
    }
    mermaidDiagrams.push(host);
  });
}
function mermaidHostForIndex(i) { return mermaidDiagrams[i] || null; }
function mermaidIntrinsicWidth(host) {
  const svg = host && host.querySelector && host.querySelector("svg");
  if (!svg) return 0;
  const viewBox = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
  if (viewBox.length === 4 && isFinite(viewBox[2]) && viewBox[2] > 0) return viewBox[2];
  const widthAttr = parseFloat(svg.getAttribute("width") || "");
  if (isFinite(widthAttr) && widthAttr > 0) return widthAttr;
  try {
    const box = svg.getBBox && svg.getBBox();
    if (box && isFinite(box.width) && box.width > 0) return box.width;
  } catch (e) {}
  return svg.getBoundingClientRect().width || 0;
}
// Narrow-diagram scale-up thresholds (#516). Only a diagram whose intrinsic width is BELOW
// NARROW_ENTER of the column is scaled up; once narrow it stays narrow until it exceeds NARROW_EXIT
// (hysteresis) so that scaling a diagram taller - which can toggle a document scrollbar and shrink
// the container by a scrollbar width on the reveal/resize ResizeObserver - cannot flip a diagram
// sitting near the boundary back and forth. NARROW_CAP bounds the scale so a tiny diagram never balloons.
const NARROW_ENTER = 0.82, NARROW_EXIT = 0.90, NARROW_CAP = 1.4;
function updateMermaidWidthClass(host) {
  if (!host) return;
  // A diagram inside a .cmh-diagram-gallery card is sized by CSS (fixed height + aspect-derived width;
  // the card hugs it). Match the EXACT card hosts the CSS sizes (a direct-child mermaid, or a mermaid
  // inside a direct-child figure), not any descendant, so a mermaid in a stray wrapper keeps normal
  // handling.
  const isGalleryHost = host.matches && host.matches(".cmh-diagram-gallery > .mermaid, .cmh-diagram-gallery > figure > .mermaid");
  if (isGalleryHost) {
    // A11y: keep the OVERFLOWING-card tab stop in sync on EVERY call, including a desktop<->mobile
    // resize. `markGalleryCardScrollable` checks the `min-width:481px` `framed` state itself: it makes
    // an overflowing framed card keyboard-focusable (WCAG 2.1.1, a bare overflow container is not
    // focusable in every browser) and CLEARS that marking on a card that fits OR on mobile. Calling it
    // here unconditionally (not only inside the desktop branch below) is what lets a desktop->mobile
    // resize clean up a leaked tabindex. It only sets a11y attributes, never a size.
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => markGalleryCardScrollable(host));
    else setTimeout(() => markGalleryCardScrollable(host), 0);
    // Above the mobile breakpoint the CSS sizes the card, so the layer's own narrow/wide/scroll-fade
    // SIZING affordances must NOT apply - the narrow scale-up in particular is measurement-timing
    // dependent and rendered diagrams tiny in a real browser. Clear the sizing classes and bail. Gated
    // to `screen and (min-width:481px)` to mirror the card CSS's media query exactly: below it the
    // gallery is a frameless flow where a wide diagram must keep the layer's wide/scroll handling
    // (CMH-RESP-01/09) - so fall through - and in print the card CSS is inactive too.
    if (typeof window.matchMedia !== "function" || window.matchMedia("screen and (min-width: 481px)").matches) {
      host.classList.remove("cmh-diagram-wide", "cmh-diagram-scroll-fade", "cmh-diagram-narrow");
      host.style.removeProperty("--cmh-diagram-cap");
      return;
    }
  }
  // A diagram-fit slide sizes the SVG to contain-fit (see fitDeckDiagram); the wide/scroll-fade
  // affordance (and its narrow-viewport min-width rule) would fight that, so never apply it there.
  // Only relevant in a deck: outside deck mode the classes drive horizontal scroll for wide diagrams.
  if (IS_DECK && host.closest && host.closest(".slide.cmh-deck-diagram-slide, .slide.cmh-slide-diagram")) {
    host.classList.remove("cmh-diagram-wide", "cmh-diagram-scroll-fade", "cmh-diagram-narrow");
    host.style.removeProperty("--cmh-diagram-cap");
    return;
  }
  const container = host.clientWidth || host.getBoundingClientRect().width || window.innerWidth || 0;
  const natural = mermaidIntrinsicWidth(host);
  const wide = natural > Math.max(container + 80, 520);
  host.classList.toggle("cmh-diagram-wide", wide);
  // A diagram whose natural width is well under the column would otherwise stay pinned to that
  // intrinsic width by mermaid's inline max-width, marooned with dead space (#516). Mark it narrow
  // and expose a capped target width so the CSS scales it up toward the column without ballooning a
  // tiny one. Report-only - deck slides have their own contain-fit sizing. `natural` is the viewBox
  // width (stable, not the CSS-grown rendered width), so scaling can never feed back into `natural`.
  const ratio = (natural > 0 && container > 0) ? natural / container : 1;
  const wasNarrow = host.classList.contains("cmh-diagram-narrow");
  const narrow = !wide && !IS_DECK && natural > 0 && container > 0 &&
    ratio < (wasNarrow ? NARROW_EXIT : NARROW_ENTER);
  host.classList.toggle("cmh-diagram-narrow", narrow);
  if (narrow) host.style.setProperty("--cmh-diagram-cap", Math.round(natural * NARROW_CAP) + "px");
  else host.style.removeProperty("--cmh-diagram-cap");
  const syncFade = () => {
    host.classList.toggle("cmh-diagram-scroll-fade", wide && host.scrollWidth > host.clientWidth + 1);
  };
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(syncFade);
  else setTimeout(syncFade, 0);
}
// A .cmh-diagram-gallery card whose diagram is WIDER than the card overflows into a horizontal scroll
// (overflow-x:auto) - a gallery card's SCROLL affordance (WCAG 2.1.1): when a diagram overflows its framed card into the
// horizontal scroll, tell an assistive-tech user it scrolls. This is layered ON TOP of the comment tab
// stop that attachMermaidKeyboardCommenting always gives every gallery card: that helper owns
// `tabindex`, the accessible NAME (aria-label), and `data-cmh-comment-a11y`; THIS helper owns only the
// scroll `role` (for a bare pre/div) and the scroll hint as `aria-description` (NOT aria-label, so it
// never clobbers the comment name), marked with `data-cmh-scroll-a11y`. Below the mobile breakpoint the
// gallery is a frameless full-height flow (a wide diagram uses the layer's own horizontal scroll,
// CMH-RESP-01/09), so a mobile card is not a scroll container - the else-branch clears ONLY the scroll
// attributes there and on a desktop->mobile resize, leaving the comment tab stop intact. `host` is a
// mermaid host; the actual gallery CARD is resolved with closest over the exact card selectors.
var GALLERY_SCROLL_LABEL = "Scrollable diagram - use the arrow keys to scroll";
function markGalleryCardScrollable(host) {
  const card = host && host.closest && host.closest(GALLERY_CARD_SEL);
  if (!card) return;
  // Only the framed (>=481px) gallery is a bounded scroll card; below the mobile breakpoint the helper
  // is a frameless full-height flow (a wide diagram uses the layer's own horizontal scroll,
  // CMH-RESP-01/09), so a mobile card gets no scroll marking. A desktop->mobile resize makes `overflows`
  // false, so the else-branch clears any scroll marking we added.
  const framed = typeof window.matchMedia !== "function" || window.matchMedia("screen and (min-width: 481px)").matches;
  // A gallery card only ever scrolls HORIZONTALLY (overflow-x:auto; overflow-y:hidden, and the svg is
  // pinned to a fixed 15rem height), so overflow == the diagram being wider than the card.
  const overflows = framed && card.scrollWidth > card.clientWidth + 1;
  const owned = card.getAttribute("data-cmh-scroll-a11y") === "1";
  const isFigure = card.tagName === "FIGURE";
  if (overflows) {
    // Respect an author who set their own scroll role/description; tabindex and the accessible name are
    // owned by the comment helper, so we never inspect or touch them here.
    if (!owned && ((!isFigure && card.hasAttribute("role")) || card.hasAttribute("aria-description"))) return;
    // A <figure> is already a figure landmark; only a pre/div card needs an explicit `group` role.
    if (!isFigure && !card.hasAttribute("role")) card.setAttribute("role", "group");
    // The scroll hint always rides aria-description so it never clobbers the comment name (aria-label).
    if (!card.hasAttribute("aria-description")) card.setAttribute("aria-description", GALLERY_SCROLL_LABEL);
    card.setAttribute("data-cmh-scroll-a11y", "1");
  } else if (owned) {
    // Clear ONLY the scroll attributes we set; the comment tab stop (tabindex + aria-label +
    // data-cmh-comment-a11y) stays, so every gallery diagram remains keyboard-commentable on mobile too.
    if (card.getAttribute("role") === "group") card.removeAttribute("role");
    if (card.getAttribute("aria-description") === GALLERY_SCROLL_LABEL) card.removeAttribute("aria-description");
    card.removeAttribute("data-cmh-scroll-a11y");
  }
}
// The rendered SVG's design-space dimensions from its viewBox (the intrinsic aspect ratio used to
// scale a deck diagram). Returns null when no positive viewBox is present.
function mermaidViewBoxDims(svg) {
  const vb = ((svg && svg.getAttribute("viewBox")) || "").trim().split(/[\s,]+/).map(Number);
  if (vb.length === 4 && isFinite(vb[2]) && isFinite(vb[3]) && vb[2] > 0 && vb[3] > 0) {
    return { w: vb[2], h: vb[3] };
  }
  return null;
}

/* ---------- Render self-check (CMH-MMD-12) ----------
   A report diagram is rendered with HTML node labels inside a <foreignObject>, whose content the
   browser re-lays-out against whatever context the SVG ends up in. When that goes wrong the node
   boxes are too small for their labels (clipped mid-word) and the viewBox is much larger than what
   was actually drawn (the diagram sits small in a corner with the rest blank). Both are measurable
   after the fact, so the layer measures them once per diagram and repairs a bad render instead of
   laying it out faithfully. */

// Slack on a label box, in SVG user units. mermaid sizes each box from its own text measurement, so
// a healthy render overflows by exactly 0 (measured across every shipped example); the allowance
// only absorbs sub-pixel rounding.
var MMD_LABEL_SLACK = 4;
// The drawn content must fill at least this fraction of the viewBox. Only an UNDER-fill in BOTH
// dimensions counts as broken: over-filling is normal (a gantt draws grid lines well past its
// viewBox) and one small dimension is a legitimate aspect ratio. The worst healthy fill across the
// shipped examples is 0.88; the reported failure sat near 0.5 in both dimensions.
var MMD_FILL_MIN = 0.7;
// Absolute allowance for the diagram's own padding (mermaid insets its content by 8 user units per
// side), so a small diagram is not judged broken by its own margins.
var MMD_FILL_PAD = 24;
// Re-measure a host only when its rendered scale has moved by more than this fraction. The fault is
// scale-dependent (an HTML label re-flows against the SCALED context), so a diagram that was healthy
// at load can break when the column - and with it the diagram's CSS scale - changes on a resize,
// rotation or reveal. Re-measuring on every ResizeObserver callback would be wasteful, and
// re-measuring never would miss exactly the case this feature exists for.
var MMD_RESCALE_MIN = 0.05;
// Applied-repair count, for automation and the regression suite (a healthy document stays at 0).
window.__cmhMermaidRepairs = 0;
// Settles once every audit the layer has RESERVED has finished, including any repair render. The
// slot for a diagram's first audit is reserved SYNCHRONOUSLY the moment its render is observed
// (before the deferred measurement runs), so `await __cmhMermaidReady` then
// `await __cmhMermaidAuditsSettled` genuinely covers the verification - awaiting the render promise
// alone does not, because the audit is queued after it settles.
window.__cmhMermaidAuditsSettled = Promise.resolve();
function trackMermaidAudit(promise) {
  window.__cmhMermaidAuditsSettled = Promise.all([window.__cmhMermaidAuditsSettled, promise])
    .then(function () {}, function () {});
  return promise;
}

// Client px per SVG user unit, so a CSS-scaled diagram is measured in its own design units.
function mermaidUserScale(svg) {
  try {
    const ctm = svg.getScreenCTM && svg.getScreenCTM();
    if (ctm && isFinite(ctm.a) && ctm.a > 0) return ctm.a;
  } catch (e) {}
  const vb = mermaidViewBoxDims(svg);
  const w = svg.getBoundingClientRect ? svg.getBoundingClientRect().width : 0;
  if (vb && w > 0) return w / vb.w;
  return 1;
}
// Worst amount (SVG user units) by which a laid-out label sticks out of the box that was sized for
// it, plus how many boxes were actually compared. An HTML label is measured against its
// <foreignObject>, an SVG <text> label against its node shape; measuring BOTH modes is what keeps a
// post-repair comparison honest, since an htmlLabels:false render has no <foreignObject> at all. The
// COUNT matters because a worst of 0 means either "everything fits" or "nothing was measurable", and
// only the caller can tell those apart.
function mermaidLabelOverflow(svg) {
  const out = { worst: 0, boxes: 0 };
  if (!svg || !svg.querySelectorAll) return out;
  const scale = mermaidUserScale(svg);
  svg.querySelectorAll("foreignObject").forEach(function (fo) {
    const bw = fo.width && fo.width.baseVal ? fo.width.baseVal.value : parseFloat(fo.getAttribute("width"));
    const bh = fo.height && fo.height.baseVal ? fo.height.baseVal.value : parseFloat(fo.getAttribute("height"));
    const kid = fo.firstElementChild;
    if (!kid || !(bw > 0) || !(bh > 0)) return;
    const r = kid.getBoundingClientRect();
    if (!(r.width > 0) && !(r.height > 0)) return;
    out.boxes += 1;
    out.worst = Math.max(out.worst, r.width / scale - bw, r.height / scale - bh);
  });
  // SVG <text> labels are already in user units, so the shape and the label are compared directly.
  // Deliberately narrow: only a `g.node` that owns BOTH a direct-child shape and mermaid's
  // direct-child `g.label` wrapper is measured. Diagram families that lay text out against a
  // composite or path-backed shape (class, requirement) or that place free text with no owning
  // shape at all (sequence, gantt, pie) match neither and are left unmeasured, so they can never be
  // repaired on this signal - measuring them would risk a FALSE POSITIVE, which would re-render a
  // healthy diagram, and a missed clip is the safer error.
  svg.querySelectorAll("g.node").forEach(function (node) {
    if (node.querySelector("foreignObject")) return;
    const label = node.querySelector(":scope > g.label text");
    const shape = node.querySelector(":scope > rect, :scope > polygon, :scope > circle, :scope > ellipse");
    if (!label || !shape || !label.getBBox || !shape.getBBox) return;
    let lb, sb;
    try { lb = label.getBBox(); sb = shape.getBBox(); } catch (e) { return; }
    if (!(sb.width > 0) || !(sb.height > 0) || !(lb.width > 0)) return;
    out.boxes += 1;
    out.worst = Math.max(out.worst, lb.width - sb.width, lb.height - sb.height);
  });
  out.worst = Math.max(0, out.worst);
  return out;
}
// How much of the viewBox the drawn content covers, per axis, plus the viewBox and the intersection
// rectangle. The coverage is the INTERSECTION of the content bbox with the viewBox, not the raw bbox
// size, so content drawn off to one side is judged by what actually lands inside the box - a raw
// size comparison would pass a diagram whose content sits entirely outside its viewBox. null when
// unmeasurable (no viewBox, or a host with no layout box).
function mermaidContentFill(svg) {
  const vb = ((svg && svg.getAttribute("viewBox")) || "").trim().split(/[\s,]+/).map(Number);
  if (vb.length !== 4 || !vb.every(isFinite) || !(vb[2] > 0) || !(vb[3] > 0)) return null;
  if (!svg.getBBox) return null;
  let box;
  try { box = svg.getBBox(); } catch (e) { return null; }
  if (!box || !(box.width > 0) || !(box.height > 0)) return null;
  const x = Math.max(box.x, vb[0]), y = Math.max(box.y, vb[1]);
  const overlapW = Math.max(0, Math.min(box.x + box.width, vb[0] + vb[2]) - x);
  const overlapH = Math.max(0, Math.min(box.y + box.height, vb[1] + vb[3]) - y);
  return {
    w: (overlapW + MMD_FILL_PAD) / vb[2],
    h: (overlapH + MMD_FILL_PAD) / vb[3],
    vb: vb,
    inner: { x: x, y: y, w: overlapW, h: overlapH },
  };
}
// The two invariants as one verdict; `bad` is what triggers a repair.
function mermaidRenderFaults(svg) {
  const labels = mermaidLabelOverflow(svg);
  const fill = mermaidContentFill(svg);
  const underfilled = !!fill && fill.w < MMD_FILL_MIN && fill.h < MMD_FILL_MIN;
  return {
    overflow: labels.worst,
    labelBoxes: labels.boxes,
    fill: fill,
    bad: labels.worst > MMD_LABEL_SLACK || underfilled,
  };
}
// The tighter of the two fill ratios. Unmeasurable bounds score 0, NOT 1: this value only ever
// feeds a "did the repair improve things" comparison, so losing measurable bounds has to read as a
// downgrade (roll back) and gaining them as an upgrade (keep), never the reverse.
function mermaidFillFloor(faults) {
  return faults && faults.fill ? Math.min(faults.fill.w, faults.fill.h) : 0;
}
// A presentation size mermaid wrote as a literal length (not the responsive `width="100%"` that
// pairs with an inline max-width, which must be left alone).
function mermaidPxAttr(value) {
  return typeof value === "string" && /^\s*\d*\.?\d+(px)?\s*$/.test(value);
}
// Re-fit an over-sized viewBox to the content that was actually drawn, so the diagram is not laid
// out small inside a box of blank space. SHRINK-ONLY and clamped to the content that lands INSIDE
// the current viewBox: the fault being repaired is "the box is bigger than the drawing", so a
// rewrite that would enlarge the box (which a diagram drawing far outside its viewBox - a gantt's
// grid lines, say - would otherwise produce) is refused outright rather than shrinking the diagram
// to a speck. Returns true when it rewrote the viewBox, and rolls the rewrite back unless the
// re-measured render is strictly better on the bounds and no worse on the labels.
function refitMermaidViewBox(svg) {
  const before = mermaidRenderFaults(svg);
  const fill = before.fill;
  if (!fill || !(fill.w < MMD_FILL_MIN && fill.h < MMD_FILL_MIN)) return false;
  if (!(fill.inner.w > 0) || !(fill.inner.h > 0)) return false;
  const pad = 8;
  const w = fill.inner.w + pad * 2, h = fill.inner.h + pad * 2;
  if (!(w < fill.vb[2]) || !(h < fill.vb[3])) return false;
  const beforeFill = mermaidFillFloor(before);
  const prevViewBox = svg.getAttribute("viewBox");
  const hadMaxWidth = !!(svg.style && svg.style.maxWidth);
  const prevMaxWidth = svg.style ? svg.style.maxWidth : "";
  const prevWidthAttr = svg.getAttribute("width"), prevHeightAttr = svg.getAttribute("height");
  svg.setAttribute("viewBox", (fill.inner.x - pad) + " " + (fill.inner.y - pad) + " " + w + " " + h);
  // mermaid pins the presentation size from the OLD viewBox: an inline max-width when useMaxWidth is
  // on, and literal px width/height ATTRIBUTES when the author turned it off. Re-derive whichever is
  // in use, or the diagram keeps reserving the stale (too wide) box.
  if (hadMaxWidth) svg.style.maxWidth = w + "px";
  if (mermaidPxAttr(prevWidthAttr) && mermaidPxAttr(prevHeightAttr)) {
    svg.setAttribute("width", String(w));
    svg.setAttribute("height", String(h));
  }
  const after = mermaidRenderFaults(svg);
  if (mermaidFillFloor(after) > beforeFill && after.overflow <= before.overflow + 0.5) return true;
  if (prevViewBox === null) svg.removeAttribute("viewBox"); else svg.setAttribute("viewBox", prevViewBox);
  if (hadMaxWidth) svg.style.maxWidth = prevMaxWidth;
  if (prevWidthAttr === null) svg.removeAttribute("width"); else svg.setAttribute("width", prevWidthAttr);
  if (prevHeightAttr === null) svg.removeAttribute("height"); else svg.setAttribute("height", prevHeightAttr);
  return false;
}
// Verify one rendered report diagram and repair it at most once. The repair is the deck-proven path
// (CMH-MMD-08): re-render THIS host with SVG <text> labels, which scale with the diagram and cannot
// re-flow, then re-fit the viewBox if the bounds are still wrong. The original SVG is kept aside and
// put back whenever the re-render loses content or does not improve either measurement, so a
// diagram is never left worse than it rendered. Resolves true when a repair was applied.
function auditMermaidRender(host) {
  // A deck already renders every label as SVG <text> (CMH-MMD-08) and owns its own contain-fit
  // sizing, so there is nothing here to repair.
  if (!host || !host.querySelector || IS_DECK) return Promise.resolve(false);
  if (host._cmhMmdRepairTried) return Promise.resolve(false);
  const svg = host.querySelector("svg");
  if (!svg) return Promise.resolve(false);
  // Nothing is measurable while the host has no layout box (a collapsed section); the reveal
  // ResizeObserver runs the audit again once it has one.
  if (!(host.offsetWidth || host.offsetHeight || (host.getClientRects && host.getClientRects().length))) {
    return Promise.resolve(false);
  }
  host._cmhMmdAuditScale = mermaidUserScale(svg);
  const before = mermaidRenderFaults(svg);
  if (!before.bad) return Promise.resolve(false);
  const beforeNodes = host.querySelectorAll(MERMAID_RENDERED_SEL).length;
  const beforeFill = mermaidFillFloor(before);
  const finish = (repaired) => {
    if (!repaired) return false;
    window.__cmhMermaidRepairs += 1;
    // A replaced SVG carries no comment rings and needs its width class recomputed against the
    // corrected intrinsic width. Never let a re-attach failure turn a successful repair into a
    // rejected promise.
    try {
      const i = parseInt(host.dataset.cmMermaidIndex, 10) || 0;
      comments.forEach(function (c) {
        if (c.anchorType === "mermaid" && c.diagramIndex === i) applyMermaidHighlight(c);
      });
      refreshDeckDiagram(host);
      updateMermaidWidthClass(host);
      attachMermaidHostHandlers(host);
      const fixed = host.querySelector("svg");
      if (fixed) host._cmhMmdAuditScale = mermaidUserScale(fixed);
    } catch (e) {}
    return true;
  };
  const rerender = window.__cmhMermaidRerender;
  if (typeof rerender !== "function") {
    // No re-render hook (for example a hand-vendored loader that predates it): the bounds can still
    // be re-fitted in place, which only rewrites this host's own viewBox and rolls itself back
    // unless the whole re-measured render improved.
    host._cmhMmdRepairTried = true;
    return Promise.resolve(finish(refitMermaidViewBox(svg)));
  }
  host._cmhMmdRepairTried = true;
  return Promise.resolve(rerender(host, { htmlLabels: false })).then(function (ok) {
    const fresh = ok && host.querySelector("svg");
    // The hook could not act (no pristine snapshot, or its render failed). Degrade exactly like the
    // no-hook path rather than leaving the diagram broken: an in-place bounds re-fit is still
    // available and only ever rewrites this host's own viewBox.
    if (!fresh || fresh === svg) return refitMermaidViewBox(svg);
    refitMermaidViewBox(fresh);
    const after = mermaidRenderFaults(fresh);
    const afterFill = mermaidFillFloor(after);
    // A worst overflow of 0 means either "every label fits" or "no label box was measurable", so the
    // label arm only votes when the fresh render actually compared boxes; otherwise the fill is the
    // only evidence there is, and it has to be a strict improvement.
    const labelsComparable = after.labelBoxes > 0;
    const notWorse = host.querySelectorAll(MERMAID_RENDERED_SEL).length >= beforeNodes &&
      (!labelsComparable || after.overflow <= before.overflow + 0.5) &&
      afterFill >= beforeFill - 0.01;
    const strictlyBetter = (labelsComparable && after.overflow < before.overflow - 0.5) ||
      afterFill > beforeFill + 0.01;
    // Keep the replacement only when it is no worse AND it actually achieved something: a
    // re-render that comes back just as broken must not be presented (or counted) as a repair.
    if (notWorse && (!after.bad || strictlyBetter) && (labelsComparable || strictlyBetter)) return true;
    host.textContent = "";
    host.appendChild(svg);
    return false;
  }, function () { return false; }).then(finish, function () { return false; });
}
// The automatic (render / reveal / resize) call sites measure a host once, and then again only when
// its rendered scale has moved materially - the fault is scale-dependent, so a diagram that was
// healthy at load can break when the column width changes, and re-measuring on every callback would
// be wasteful. A host whose one repair attempt is spent is never re-measured at all. Returns the
// audit promise so the caller can fold it into the settled-audits signal.
function maybeAuditMermaidRender(host) {
  if (!host || host._cmhMmdRepairTried) return Promise.resolve(false);
  const prev = host._cmhMmdAuditScale;
  if (typeof prev === "number") {
    const svg = host.querySelector && host.querySelector("svg");
    if (!svg) return Promise.resolve(false);
    const now = mermaidUserScale(svg);
    if (!(prev > 0) || Math.abs(now - prev) / prev < MMD_RESCALE_MIN) return Promise.resolve(false);
  }
  return trackMermaidAudit(auditMermaidRender(host));
}
window.__cmhMermaidAudit = auditMermaidRender;

// Rich (non-text) blocks other than a mermaid diagram. A deck slide carrying one of these beside a
// diagram is a mixed layout and is left alone; a slide whose only non-text content is a single
// diagram is a "diagram slide" that should hand the diagram the whole slide.
var DECK_RICH_OTHER_SEL = "img, canvas, table, figure, pre:not(.mermaid), iframe, video, audio, object, embed, svg, .cmh-diff-view, .cmh-chart";
// Auto-detect a diagram-dominant deck slide: exactly one mermaid host, no other rich block, and no
// author-authored .cmh-cols-2 (bullets, headings, prose, and a reference row are text, so they do
// not disqualify it). A slide that HAS a .cmh-cols-2 keeps its explicit two-column layout unless the
// author opts in with .cmh-slide-diagram (which forces the fill and flattens the column) - so the
// automatic path never silently destroys a deliberate side-by-side layout. The matched slide is
// switched to the flex-column diagram-fit layout (see 90-deck.css) so fitDeckDiagram can grow the
// diagram to fill the slide's height as well as its width, instead of leaving it at its small
// intrinsic size beside empty space.
function classifyDeckDiagramSlide(host) {
  if (!IS_DECK || !host || !host.closest) return;
  const slide = host.closest(".slide");
  if (!slide) return;
  if (slide.classList.contains("cmh-slide-diagram")) { slide.classList.add("cmh-deck-diagram-slide"); return; }
  const diagrams = slide.querySelectorAll(CMH_MERMAID_SEL);
  const hasCols = !!slide.querySelector(".cmh-cols-2");
  let hasOther = false;
  slide.querySelectorAll(DECK_RICH_OTHER_SEL).forEach((el) => {
    // Skip the diagram's own rendered content and any wrapper that CONTAINS the host (e.g. a
    // <figure> around the diagram) - only a genuine SIBLING rich block is disqualifying.
    if (host.contains(el) || el.contains(host) || el.closest(CMH_MERMAID_SEL)) return;
    hasOther = true;
  });
  slide.classList.toggle("cmh-deck-diagram-slide", diagrams.length === 1 && !hasOther && !hasCols);
}
// The available box (layout px) a diagram-fit slide gives its diagram. Width is the host's own
// content width (its full-width column or the slide). Height is measured from the host's top down to
// the bottom of the slide's fixed content box, so a diagram nested in non-flex wrappers (where the
// host's own height is content-driven, not space-driven) is still bounded to the slide and can never
// overflow / clip; where the host IS the flex-grown item its measured height (which also reserves
// room for a trailing refs row) is used when smaller. Uses offset/client + a de-scaled rect so the
// reading is independent of the stage's CSS transform.
function deckDiagramAvailBox(host, slide) {
  const hcs = getComputedStyle(host);
  const hPadX = (parseFloat(hcs.paddingLeft) || 0) + (parseFloat(hcs.paddingRight) || 0);
  const hPadY = (parseFloat(hcs.paddingTop) || 0) + (parseFloat(hcs.paddingBottom) || 0);
  // Size to the host's CONTENT box: client{Width,Height} include the host's own padding, so a padded
  // mermaid host (the showcase gives pre.mermaid 26px) would otherwise clip the SVG by 2x the padding.
  const availW = Math.max(0, host.clientWidth - hPadX);
  if (!slide) return { w: availW, h: Math.max(0, host.clientHeight - hPadY) };
  const scs = getComputedStyle(slide);
  const padT = parseFloat(scs.paddingTop) || 0;
  const padB = parseFloat(scs.paddingBottom) || 0;
  const contentH = slide.clientHeight - padT - padB;
  const slideRect = slide.getBoundingClientRect();
  const hostRect = host.getBoundingClientRect();
  const scale = slide.offsetHeight ? slideRect.height / slide.offsetHeight : 1;
  const hostTop = scale > 0 ? (hostRect.top - slideRect.top) / scale - padT : 0;
  const slideAvailH = contentH - Math.max(0, hostTop);
  const rawH = host.clientHeight > 0 ? Math.min(host.clientHeight, slideAvailH) : slideAvailH;
  return { w: availW, h: Math.max(0, rawH - hPadY) };
}
// Scale a deck diagram to fill (contain-fit) the space its diagram-fit slide gives it, using BOTH
// width and height so a wide-short or a lone diagram is as large as the slide allows without overflow
// or clipping. Collapse the SVG first so the reading is the available box (not a size the current SVG
// is inflating), then size the SVG to the largest aspect-preserving box that fits. On a non-fit slide
// (or a diagram with no viewBox) any explicit sizing is cleared so the width-fill fallback applies.
// Composes with CMH-MMD-08 (htmlLabels:false): the SVG scales as a whole, so labels stay crisp.
function fitDeckDiagram(host) {
  if (!IS_DECK || !host || !host.querySelector) return;
  const svg = host.querySelector("svg");
  if (!svg) return;
  const slide = host.closest && host.closest(".slide");
  const fit = !!slide && (slide.classList.contains("cmh-deck-diagram-slide") ||
    slide.classList.contains("cmh-slide-diagram"));
  const clear = () => { if (svg.style.width || svg.style.height) { svg.style.width = ""; svg.style.height = ""; } };
  if (!fit) { clear(); return; }
  const dims = mermaidViewBoxDims(svg);
  if (!dims) { clear(); return; }
  svg.style.width = "0px";
  svg.style.height = "0px";
  const box = deckDiagramAvailBox(host, slide);
  if (box.w > 0 && box.h > 0) {
    const scale = Math.min(box.w / dims.w, box.h / dims.h);
    svg.style.width = (dims.w * scale) + "px";
    svg.style.height = (dims.h * scale) + "px";
  } else {
    svg.style.width = "";
    svg.style.height = "";
  }
}
function refreshDeckDiagram(host) {
  if (!IS_DECK) return;
  classifyDeckDiagramSlide(host);
  fitDeckDiagram(host);
}
function mermaidNodeKey(nodeEl) {
  const ds = nodeEl.dataset && nodeEl.dataset.id;
  if (ds) return ds;
  const rawId = nodeEl.id || "";
  const m = rawId.match(/^(?:flowchart|class|state|er|gantt|sequence|mindmap|timeline)[-_](.+?)(?:[-_]\d+)?$/);
  if (m && m[1]) return m[1];
  const label = mermaidNodeLabel(nodeEl);
  if (label) return "label:" + label.slice(0, 200);
  if (rawId) return "id:" + rawId;   // e.g. gantt task bars (rect id) with no own text
  return "label:";
}
function mermaidNodeLabel(nodeEl) {
  // Mermaid SVG <text> labels (htmlLabels:false, used for decks) split a wrapped label into per-line
  // `tspan.text-outer-tspan` rows with NO separator between them, so a plain textContent read drops the
  // space at each wrap point ("exact spot" -> "exactspot"). Rejoin the rows with a space so the label
  // used for the anchor key, the comment quote, and Copy all matches the rendered words. HTML labels
  // (reports) have no such rows and fall through to textContent unchanged.
  const rows = nodeEl.querySelectorAll ? nodeEl.querySelectorAll("tspan.text-outer-tspan") : null;
  if (rows && rows.length > 1) {
    return Array.from(rows).map(r => (r.textContent || "").trim()).filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
  }
  return (nodeEl.textContent || "").trim().replace(/\s+/g, " ");
}
function findMermaidNode(diagramIndex, nodeKey) {
  const host = mermaidHostForIndex(diagramIndex);
  if (!host) return null;
  if (nodeKey === "__diagram__") return host; // whole-diagram anchor
  const candidates = host.querySelectorAll(MERMAID_NODE_SEL);
  for (const n of candidates) {
    if (mermaidNodeKey(n) === nodeKey) return n;
  }
  if (nodeKey && nodeKey.startsWith("label:")) {
    const want = nodeKey.slice(6);
    for (const n of candidates) {
      if (mermaidNodeLabel(n) === want) return n;
    }
    // Whitespace-insensitive fallback: an anchor saved before a diagram switched between HTML labels
    // (report) and SVG <text> labels (deck) can differ ONLY in wrap-point spacing (for example an old
    // "You comment on the exact spot" vs a rendered "exactspot", or the reverse). Match on the
    // space-stripped label so such comments still re-anchor and keep their ring/jump across the change.
    const wantStripped = want.replace(/\s+/g, "");
    if (wantStripped) {
      for (const n of candidates) {
        if (mermaidNodeLabel(n).replace(/\s+/g, "") === wantStripped) return n;
      }
    }
  }
  if (nodeKey && nodeKey.startsWith("id:")) {
    const want = nodeKey.slice(3);
    for (const n of candidates) {
      if ((n.id || "") === want) return n;
    }
  }
  return null;
}
function applyMermaidHighlight(comment) {
  const node = findMermaidNode(comment.diagramIndex, comment.nodeKey);
  if (!node) return false;
  // A node can carry several comments; track them all in data-cids (first in
  // data-cid for legacy selectors), like the diff-row and image layers.
  node.classList.add("cm-mermaid-hl");
  const cids = (node.getAttribute("data-cids") || "").split(/\s+/).filter(Boolean);
  if (!cids.includes(comment.id)) cids.push(comment.id);
  node.setAttribute("data-cids", cids.join(" "));
  node.setAttribute("data-cid", cids[0]);
  return true;
}
function clearMermaidHighlight(id) {
  root.querySelectorAll(".cm-mermaid-hl").forEach(n => {
    const cids = (n.getAttribute("data-cids") || n.getAttribute("data-cid") || "").split(/\s+/).filter(Boolean);
    const rest = cids.filter(c => c !== id);
    if (rest.length === cids.length) return;
    if (rest.length) {
      n.setAttribute("data-cids", rest.join(" "));
      n.setAttribute("data-cid", rest[0]);
    } else {
      n.classList.remove("cm-mermaid-hl", "cm-mermaid-active");
      n.removeAttribute("data-cid");
      n.removeAttribute("data-cids");
    }
  });
}
function flashMermaid(id) {
  const node = [...root.querySelectorAll(".cm-mermaid-hl")].find(n =>
    (n.getAttribute("data-cids") || n.getAttribute("data-cid") || "").split(/\s+/).includes(id));
  if (!node) return;
  node.classList.add("cm-mermaid-active");
  setTimeout(() => node.classList.remove("cm-mermaid-active"), 2200);
}
function captureMermaidContext(host) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, {
    acceptNode(n) {
      if (n.closest(".cm-skip") && !host.contains(n)) return NodeFilter.FILTER_REJECT;
      return /^H[1-6]$/i.test(n.tagName) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    },
  });
  const headings = [];
  let n;
  while ((n = walker.nextNode())) {
    if (host.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING) break;
    headings.push({ level: parseInt(n.tagName.slice(1), 10), text: n.textContent.trim().replace(/\s+/g, " ") });
  }
  const headingPath = [];
  for (const h of headings) {
    while (headingPath.length && headingPath[headingPath.length - 1].level >= h.level) headingPath.pop();
    headingPath.push(h);
  }
  return {
    section: headingPath.length ? headingPath[headingPath.length - 1].text : null,
    headingPath,
  };
}
function positionMermaidAdd(node) {
  const rect = node.getBoundingClientRect();
  const visible = _clipAwareRect(node, rect);
  if (!visible) return false;
  const btnW = mermaidAddBtn.offsetWidth || 120;
  const btnH = mermaidAddBtn.offsetHeight || 28;
  const bounds = _floatingBounds(node);
  const left = visible.right - btnW;
  let top  = visible.top - btnH - 4;
  if (top < bounds.top) top = visible.bottom + 4;
  mermaidAddBtn.style.left = _clamp(left, bounds.left, bounds.right - btnW) + "px";
  mermaidAddBtn.style.top  = _clamp(top, bounds.top, bounds.bottom - btnH) + "px";
  return true;
}
function showMermaidAddFor(node, host) {
  const rect = node.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return;
  pendingMermaid = {
    diagramIndex: parseInt(host.dataset.cmMermaidIndex, 10) || 0,
    nodeKey: mermaidNodeKey(node),
    nodeLabel: mermaidNodeLabel(node),
  };
  if (mermaidAddHideTimer) { clearTimeout(mermaidAddHideTimer); mermaidAddHideTimer = null; }
  mermaidAddBtn.hidden = false;
  mermaidAddBtn.textContent = "Add Comment";
  if (!positionMermaidAdd(node)) { mermaidAddBtn.hidden = true; pendingMermaid = null; return; }
  setActiveAdd({ el: node, btn: mermaidAddBtn, position: () => positionMermaidAdd(node), clear: () => { pendingMermaid = null; } });
}
function mermaidDiagramLabel(host) {
  const t = host.querySelector(".titleText, text.title, .title, .cmh-diagram-title");
  const s = t && (t.textContent || "").trim().replace(/\s+/g, " ");
  return s ? ("diagram: " + s) : "entire diagram";
}
// Whole-diagram affordance: shown when hovering the diagram's empty area (e.g. the
// middle of a gantt timeline) so the ENTIRE graph is commentable, not only nodes.
// Pure positioner (mirrors positionMermaidAdd): computes the clip-aware placement and returns
// whether the button is visible. NO state/timer/setActiveAdd side effects, so a scroll/resize
// reposition can call it safely without cancelling a pending mouseleave hide.
function positionMermaidWhole(host) {
  const svg = host.querySelector("svg");
  const target = svg || host;
  const rect = target.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return false;
  // Clip to any scroll/overflow ancestor (e.g. a bounded .cmh-diagram-gallery card): when a tall
  // diagram is scrolled inside its card the raw svg rect extends past the card, so anchor the button
  // to the VISIBLE intersection and hide it when the diagram is scrolled out of view - mirroring
  // positionMermaidAdd for node buttons.
  const visible = _clipAwareRect(target, rect);
  if (!visible) return false;
  const bw = mermaidAddBtn.offsetWidth || 160, bh = mermaidAddBtn.offsetHeight || 28;
  const bounds = _floatingBounds(host);
  const left = visible.right - bw - 6, top = visible.top + 6;
  mermaidAddBtn.style.left = _clamp(left, bounds.left, bounds.right - bw) + "px";
  mermaidAddBtn.style.top = _clamp(top, bounds.top, bounds.bottom - bh) + "px";
  return true;
}
function showMermaidWholeFor(host) {
  pendingMermaid = {
    diagramIndex: parseInt(host.dataset.cmMermaidIndex, 10) || 0,
    nodeKey: "__diagram__",
    nodeLabel: mermaidDiagramLabel(host),
  };
  if (mermaidAddHideTimer) { clearTimeout(mermaidAddHideTimer); mermaidAddHideTimer = null; }
  mermaidAddBtn.hidden = false;
  mermaidAddBtn.textContent = "Comment on diagram";
  if (!positionMermaidWhole(host)) { mermaidAddBtn.hidden = true; pendingMermaid = null; return false; }
  setActiveAdd({ el: host, btn: mermaidAddBtn, position: () => positionMermaidWhole(host), clear: () => { pendingMermaid = null; } });
  return true;
}
function scheduleHideMermaidAdd() {
  if (mermaidAddHideTimer) clearTimeout(mermaidAddHideTimer);
  mermaidAddHideTimer = setTimeout(() => {
    if (!mermaidAddBtn.matches(":hover")) { mermaidAddBtn.hidden = true; mermaidActiveNode = null; pendingMermaid = null; clearActiveAdd(mermaidAddBtn); }
  }, 220);
}
// Keyboard commenting a11y: a rendered diagram is a commentable target, so - like an image
// (30-images.js) - it must be a keyboard focus target whose focus reveals the whole-diagram
// "Comment on diagram" button and whose Enter opens the composer, so a keyboard-only user never has to
// tab to the floating (end-of-DOM) add button. `el` is the focus TARGET (a standalone host, or a
// gallery CARD); `host` is the mermaid host used for the diagram title/index. This owns tabindex, the
// accessible NAME, and `data-cmh-comment-a11y` (the focus-ring marker) - the scroll helper
// (markGalleryCardScrollable) owns the separate scroll role/aria-description and never touches these.
function makeMermaidCommentFocusable(el, host) {
  // Exactly one comment tab stop per diagram; setting tabindex is idempotent, so it never creates a
  // second focusable element even if the scroll helper already ran.
  if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
  el.setAttribute("data-cmh-comment-a11y", "1");
  // Never clobber an author-provided accessible name.
  if (el.hasAttribute("aria-label") || el.hasAttribute("aria-labelledby")) return;
  // A <figure> whose <figcaption> is a DESCENDANT (a gallery figure card is the focus target) is
  // already named by that caption - leave it as the name and add no aria-label.
  if (el.querySelector && el.querySelector(":scope > figcaption")) return;
  // A pre/div host inside a <figure> has the caption as a SIBLING (host.querySelector misses it), so
  // borrow the caption text as the host's accessible name and keep the caption as the single source.
  const fig = el.closest && el.closest("figure");
  const sibCaption = fig && fig.querySelector(":scope > figcaption");
  const capText = sibCaption && (sibCaption.textContent || "").trim().replace(/\s+/g, " ");
  if (capText) { el.setAttribute("aria-label", capText); return; }
  el.setAttribute("aria-label", mermaidDiagramLabel(host) + " - press Enter to comment");
}
// Wire focus/blur/keydown so a focused diagram reveals the whole-diagram button and Enter opens the
// composer. The focus TARGET is the standalone host, but for a gallery diagram it is the CARD
// (figure/pre/div) - the element the scroll-a11y helper (markGalleryCardScrollable, CMH-CONTENT-19)
// may also mark - so a keyboard user gets ONE sane tab stop, not a disjointed host+float pair. EVERY
// rendered diagram gets a comment tab stop here, gallery or not, fitting or overflowing, desktop or
// mobile (issue #638: keyboard-commentable like an image) - focusability is NOT delegated to the
// scroll helper, which only ever adopts an OVERFLOWING framed card.
function attachMermaidKeyboardCommenting(host) {
  const galleryCard = host.closest && host.closest(GALLERY_CARD_SEL);
  const target = galleryCard || host;
  if (target._cmKbdCommentAttached) return;
  target._cmKbdCommentAttached = true;
  makeMermaidCommentFocusable(target, host);
  target.addEventListener("focus", () => { mermaidActiveNode = host; showMermaidWholeFor(host); });
  target.addEventListener("blur", scheduleHideMermaidAdd);
  target.addEventListener("keydown", (e) => {
    // Only the tab stop ITSELF activates: a bubbled Enter/Space from a descendant control (e.g. a link
    // or button inside a <figcaption>) must keep its native action, not open the diagram composer.
    if (e.target !== target) return;
    const isEnter = e.key === "Enter";
    const isSpace = e.key === " ";
    if (!isEnter && !isSpace) return;
    // On an OVERFLOWING (horizontally scrollable) gallery card, leave Space (and the arrow keys) to
    // native scrolling so a keyboard user can reach the clipped diagram (WCAG 2.1.1); Enter is the
    // universal activator. A fitting card / standalone host keeps Space-to-comment (like the image path).
    if (isSpace && target.getAttribute("data-cmh-scroll-a11y") === "1") return;
    e.preventDefault();
    pendingMermaid = null;
    mermaidAddBtn.hidden = true;
    mermaidActiveNode = null;
    openMermaidComposer({
      diagramIndex: parseInt(host.dataset.cmMermaidIndex, 10) || 0,
      nodeKey: "__diagram__",
      nodeLabel: mermaidDiagramLabel(host),
    });
  });
}
function attachMermaidHostHandlers(host) {
  if (host._cmAttached) return;
  host._cmAttached = true;
  attachMermaidKeyboardCommenting(host);
  host.addEventListener("mousemove", (e) => {
    const node = e.target.closest && e.target.closest(MERMAID_NODE_SEL);
    if (node && host.contains(node)) {
      // Re-show even if the sentinel still points here but the button was hidden
      // (e.g. after a prior comment add/delete hid it).
      if (node === mermaidActiveNode && !mermaidAddBtn.hidden) return;
      // While the button is showing for a node, moving toward it crosses the
      // surrounding subgraph cluster. Don't let that ancestor cluster hijack the
      // button (it would jump to the cluster corner). Keep the current node.
      if (!mermaidAddBtn.hidden && mermaidActiveNode && mermaidActiveNode.classList &&
          node.classList && node.classList.contains("cluster") &&
          cmRectContains(node.getBoundingClientRect(), mermaidActiveNode.getBoundingClientRect())) {
        return;
      }
      mermaidActiveNode = node;
      showMermaidAddFor(node, host);
      return;
    }
    // Empty diagram area (e.g. the middle of a gantt): offer commenting on the whole graph.
    if (!host.querySelector("svg")) return;
    // Don't let a stray empty-area mousemove clobber an active NODE affordance while the
    // pointer is heading to the (fixed) Add button - that would swap a node comment for a
    // whole-diagram comment on click. Only offer whole-diagram when no node button shows.
    if (mermaidActiveNode && mermaidActiveNode !== host && !mermaidAddBtn.hidden) return;
    if (mermaidActiveNode === host && !mermaidAddBtn.hidden) return;
    mermaidActiveNode = host;
    showMermaidWholeFor(host);
  });
  host.addEventListener("mouseleave", scheduleHideMermaidAdd);
  host.addEventListener("click", (e) => {
    const hl = e.target.closest && e.target.closest(".cm-mermaid-hl");
    if (!hl) return;
    const id = hl.getAttribute("data-cid");
    if (!id) return;
    openSidebar();
    const card = listEl.querySelector(`.cm-card[data-cid="${id}"]`);
    if (card) { card.scrollIntoView({ behavior: cmScrollBehavior(), block: "center" }); flashActive(id); }
    flashMermaid(id);
  });
}
mermaidAddBtn.addEventListener("mouseenter", () => {
  if (mermaidAddHideTimer) { clearTimeout(mermaidAddHideTimer); mermaidAddHideTimer = null; }
});
mermaidAddBtn.addEventListener("focus", () => {
  if (mermaidAddHideTimer) { clearTimeout(mermaidAddHideTimer); mermaidAddHideTimer = null; }
});
mermaidAddBtn.addEventListener("mouseleave", scheduleHideMermaidAdd);
mermaidAddBtn.addEventListener("blur", scheduleHideMermaidAdd);
mermaidAddBtn.addEventListener("click", () => {
  if (!pendingMermaid) return;
  const info = pendingMermaid;
  pendingMermaid = null;
  mermaidAddBtn.hidden = true;
  mermaidActiveNode = null;
  openMermaidComposer(info);
});
function openMermaidComposer(info) {
  return createComposerElement({ mode: "new-mermaid", mermaid: info });
}
function setupMermaidLayer() {
  indexMermaidDiagrams();
  if (!mermaidDiagrams.length) return;
  // Readiness signal: mermaid v9+ stamps data-processed="true" on the host
  // once it has finished rendering the SVG. Falls back to checking for
  // populated nodes in case a different renderer is in use.
  const isReady = (host) =>
    host.dataset.processed === "true" ||
    !!host.querySelector(MERMAID_RENDERED_SEL);
  const restoreForHost = (host) => {
    // Reserve this host's audit slot NOW, synchronously, so `__cmhMermaidAuditsSettled` is already
    // pending by the time the render promise settles; the measurement itself has to wait a frame
    // (below), and a slot reserved only then would let an automation pipeline read an
    // already-settled signal and capture the unverified diagram (CMH-MMD-12).
    let settleAudit;
    trackMermaidAudit(new Promise(function (resolve) { settleAudit = resolve; }));
    // Defer one frame: mermaid stamps data-processed before the SVG nodes
    // are actually in the DOM in some versions, so highlight application
    // must wait until the painted nodes exist.
    const apply = () => {
      const i = parseInt(host.dataset.cmMermaidIndex, 10) || 0;
      comments.forEach(c => {
        if (c.anchorType === "mermaid" && c.diagramIndex === i) applyMermaidHighlight(c);
      });
      // Classify + fit BEFORE the width-class pass so, on an auto-classified slide, the fit-slide
      // guard in updateMermaidWidthClass sees the class on the first paint (no transient wide flash).
      refreshDeckDiagram(host);
      updateMermaidWidthClass(host);
      attachMermaidHostHandlers(host);
      // Verify what mermaid actually drew and repair a bad render (CMH-MMD-12).
      maybeAuditMermaidRender(host).then(settleAudit, settleAudit);
    };
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(apply);
    else setTimeout(apply, 0);
  };
  mermaidDiagrams.forEach(host => {
    if (isReady(host) && host.querySelector(MERMAID_RENDERED_SEL)) {
      restoreForHost(host);
      return;
    }
    const obs = new MutationObserver((_m, observer) => {
      if (isReady(host) && host.querySelector(MERMAID_RENDERED_SEL)) {
        observer.disconnect();
        restoreForHost(host);
      }
    });
    obs.observe(host, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-processed"] });
  });
  if (!setupMermaidLayer._widthResizeBound) {
    setupMermaidLayer._widthResizeBound = true;
    window.addEventListener("resize", function () {
      mermaidDiagrams.forEach(function (host) { updateMermaidWidthClass(host); refreshDeckDiagram(host); });
    });
    // A deck slide that was inactive (zero-influence layout) when its diagram first rendered is
    // re-fit when it becomes active, so the diagram fills the slide the first time it is shown. Only
    // the now-active slide's diagram(s) are refreshed, not every diagram on the deck.
    if (IS_DECK) {
      document.addEventListener("cmh:slidechange", function () {
        const active = root.querySelector(".slide.active");
        mermaidDiagrams.forEach(function (host) {
          if (!active || (host.closest && host.closest(".slide") === active)) refreshDeckDiagram(host);
        });
      });
    }
  }
  // A diagram rendered while its section was collapsed had its wide/scroll-fade class computed against
  // a zero-size (window-fallback) container; recompute it when the host gains its real size on reveal.
  if (typeof ResizeObserver === "function") {
    if (setupMermaidLayer._widthObs) setupMermaidLayer._widthObs.disconnect();
    const widthObs = new ResizeObserver(function (entries) {
      entries.forEach(function (e) {
        updateMermaidWidthClass(e.target);
        refreshDeckDiagram(e.target);
        // A diagram rendered while its section was collapsed was unmeasurable then; audit it the
        // first time it has a real layout box (CMH-MMD-12).
        maybeAuditMermaidRender(e.target);
      });
    });
    mermaidDiagrams.forEach(function (host) { widthObs.observe(host); });
    setupMermaidLayer._widthObs = widthObs;
  }
}


