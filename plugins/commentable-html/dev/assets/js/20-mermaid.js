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
  return left >= 8 && left <= window.innerWidth - w - 8 &&
         top >= 8 && top <= window.innerHeight - h - 8;
}
// Whether an anchor rect is at least partially within the viewport. Used to decide
// whether a floating add button should stay (anchor visible) or hide (anchor scrolled
// away). The button position itself is clamped on-screen separately, so an anchor near
// a viewport edge must NOT be treated as "gone".
function _rectInViewport(r) {
  return r.width > 0 && r.height > 0 &&
    r.bottom > 4 && r.top < window.innerHeight - 4 &&
    r.right > 4 && r.left < window.innerWidth - 4;
}
function _clipContainerFor(node) {
  const el = node && (node.nodeType === 1 ? node : node.parentElement);
  if (!el || !el.closest) return null;
  // Prefer the gallery CARD (a direct child of .cmh-diagram-gallery) FIRST, then fall back to the
  // generic clip containers. Otherwise, for a supported `<figure><pre class="mermaid">...</pre></figure>`
  // card, `closest()` starting at the svg would match the inner `pre.mermaid` (the nearer ancestor)
  // before the outer figure, and clamp the button to the non-scrolling pre instead of the figure's
  // scroll card - so the whole-diagram button could detach while the figure scrolls.
  return el.closest(".cmh-diagram-gallery > pre.mermaid, .cmh-diagram-gallery > div.mermaid, .cmh-diagram-gallery > figure")
    || el.closest("pre.mermaid, figure.chart, table, .cmh-diff-raw");
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
  let visible = _intersectRects(rect, {
    left: 4, right: window.innerWidth - 4, top: 4, bottom: window.innerHeight - 4,
  });
  if (!visible) return null;
  const clip = _clipContainerFor(node);
  if (clip) visible = _intersectRects(visible, clip.getBoundingClientRect());
  return visible;
}
function _floatingBounds(node) {
  const clip = _clipContainerFor(node);
  const viewport = { left: 8, right: window.innerWidth - 8, top: 8, bottom: window.innerHeight - 8 };
  if (!clip) return viewport;
  const clipped = _intersectRects(viewport, clip.getBoundingClientRect());
  return clipped || viewport;
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
  const hosts = root.querySelectorAll("pre.mermaid, div.mermaid");
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
// (overflow-x:auto). A bare overflow container is not keyboard-focusable in every browser, so make an
// OVERFLOWING card keyboard-focusable (WCAG 2.1.1) so a sighted keyboard-only user can scroll to the
// clipped content. Only a card that actually overflows gets a tab stop - a card that fits, and the
// frameless mobile single-column flow, do not - and the state is re-synced on resize/ResizeObserver so
// it clears when a widened viewport lets the card fit. This sets ONLY a11y attributes, never a size.
// Ownership is explicit: we adopt a card ONLY when the author set none of tabindex/role/aria-label, we
// mark it with `data-cmh-scroll-a11y` (which survives export so a reloaded card is re-adopted),
// idempotently re-assert the trio (healing a sanitizer that stripped tabindex/role but kept the
// marker), and remove ONLY the values we set. `host` is a mermaid host; the actual gallery CARD is
// resolved with closest over the exact card selectors, so a mermaid host in a figure marks the figure.
var GALLERY_SCROLL_LABEL = "Scrollable diagram - use the arrow keys to scroll";
var GALLERY_CARD_SEL = ".cmh-diagram-gallery > pre.mermaid, .cmh-diagram-gallery > div.mermaid, .cmh-diagram-gallery > figure";
function markGalleryCardScrollable(host) {
  const card = host && host.closest && host.closest(GALLERY_CARD_SEL);
  if (!card) return;
  // Only the framed (>=481px) gallery is a bounded scroll card; below the mobile breakpoint the helper
  // is a frameless full-height flow (a wide diagram uses the layer's own horizontal scroll,
  // CMH-RESP-01/09), so a mobile card gets no tab stop. A desktop->mobile resize makes `overflows`
  // false, so the else-branch clears any marking we added.
  const framed = typeof window.matchMedia !== "function" || window.matchMedia("screen and (min-width: 481px)").matches;
  // A gallery card only ever scrolls HORIZONTALLY (overflow-x:auto; overflow-y:hidden, and the svg is
  // pinned to a fixed 15rem height), so overflow == the diagram being wider than the card. (Checking
  // scrollHeight too would be dead under this design and could mislead a future regression that added a
  // card height into marking a card focusable for a direction it cannot scroll.)
  const overflows = framed && card.scrollWidth > card.clientWidth + 1;
  const owned = card.getAttribute("data-cmh-scroll-a11y") === "1";
  if (overflows) {
    if (!owned && (card.hasAttribute("tabindex") || card.hasAttribute("role") || card.hasAttribute("aria-label") || card.hasAttribute("aria-description"))) return;
    if (!card.hasAttribute("tabindex")) card.setAttribute("tabindex", "0");
    const isFigure = card.tagName === "FIGURE";
    // A <figure> is already a figure landmark; only a pre/div card needs an explicit role. Use `group`
    // (a scrollable group of diagram content) rather than a spurious landmark.
    if (!isFigure && !card.hasAttribute("role")) card.setAttribute("role", "group");
    // The scroll hint: use aria-label when the card has no other name; a captioned <figure> is already
    // named by its <figcaption>, so attach the hint as aria-description (progressive - ignored by a
    // screen reader that does not support it) instead of clobbering the caption name.
    if (!card.hasAttribute("aria-label") && !card.querySelector("figcaption")) {
      card.setAttribute("aria-label", GALLERY_SCROLL_LABEL);
    } else if (isFigure && card.querySelector("figcaption") && !card.hasAttribute("aria-description")) {
      card.setAttribute("aria-description", GALLERY_SCROLL_LABEL);
    }
    card.setAttribute("data-cmh-scroll-a11y", "1");
  } else if (owned) {
    if (card.getAttribute("tabindex") === "0") card.removeAttribute("tabindex");
    if (card.getAttribute("role") === "group") card.removeAttribute("role");
    if (card.getAttribute("aria-label") === GALLERY_SCROLL_LABEL) card.removeAttribute("aria-label");
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
  const diagrams = slide.querySelectorAll("pre.mermaid, div.mermaid");
  const hasCols = !!slide.querySelector(".cmh-cols-2");
  let hasOther = false;
  slide.querySelectorAll(DECK_RICH_OTHER_SEL).forEach((el) => {
    // Skip the diagram's own rendered content and any wrapper that CONTAINS the host (e.g. a
    // <figure> around the diagram) - only a genuine SIBLING rich block is disqualifying.
    if (host.contains(el) || el.contains(host) || el.closest("pre.mermaid, div.mermaid")) return;
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
function attachMermaidHostHandlers(host) {
  if (host._cmAttached) return;
  host._cmAttached = true;
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
mermaidAddBtn.addEventListener("mouseleave", scheduleHideMermaidAdd);
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
      entries.forEach(function (e) { updateMermaidWidthClass(e.target); refreshDeckDiagram(e.target); });
    });
    mermaidDiagrams.forEach(function (host) { widthObs.observe(host); });
    setupMermaidLayer._widthObs = widthObs;
  }
}


