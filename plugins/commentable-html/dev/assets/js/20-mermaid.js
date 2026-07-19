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
// The floating add-comment buttons (image / mermaid / diff) are position:fixed and
// positioned once at hover time. `_activeAdd` remembers the currently-shown one and
// how to re-run its positioning, so a scroll/resize can keep it pinned to its target
// (or hide it when the target scrolls out of view) instead of letting it drift.
let _activeAdd = null;
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
  return el && el.closest ? el.closest("pre.mermaid, figure.chart, table, .cmh-diff-raw") : null;
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
  const viewBox = (svg.getAttribute("viewBox") || "").trim().split(/\s+/).map(Number);
  if (viewBox.length === 4 && isFinite(viewBox[2]) && viewBox[2] > 0) return viewBox[2];
  const widthAttr = parseFloat(svg.getAttribute("width") || "");
  if (isFinite(widthAttr) && widthAttr > 0) return widthAttr;
  try {
    const box = svg.getBBox && svg.getBBox();
    if (box && isFinite(box.width) && box.width > 0) return box.width;
  } catch (e) {}
  return svg.getBoundingClientRect().width || 0;
}
function updateMermaidWidthClass(host) {
  if (!host) return;
  const container = host.clientWidth || host.getBoundingClientRect().width || window.innerWidth || 0;
  const natural = mermaidIntrinsicWidth(host);
  const wide = natural > Math.max(container + 80, 520);
  host.classList.toggle("cmh-diagram-wide", wide);
  const syncFade = () => {
    host.classList.toggle("cmh-diagram-scroll-fade", wide && host.scrollWidth > host.clientWidth + 1);
  };
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(syncFade);
  else setTimeout(syncFade, 0);
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
  _activeAdd = { el: node, btn: mermaidAddBtn, position: () => positionMermaidAdd(node), clear: () => { pendingMermaid = null; } };
}
function mermaidDiagramLabel(host) {
  const t = host.querySelector(".titleText, text.title, .title, .cmh-diagram-title");
  const s = t && (t.textContent || "").trim().replace(/\s+/g, " ");
  return s ? ("diagram: " + s) : "entire diagram";
}
// Whole-diagram affordance: shown when hovering the diagram's empty area (e.g. the
// middle of a gantt timeline) so the ENTIRE graph is commentable, not only nodes.
function showMermaidWholeFor(host) {
  const svg = host.querySelector("svg");
  const rect = (svg || host).getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return false;
  pendingMermaid = {
    diagramIndex: parseInt(host.dataset.cmMermaidIndex, 10) || 0,
    nodeKey: "__diagram__",
    nodeLabel: mermaidDiagramLabel(host),
  };
  if (mermaidAddHideTimer) { clearTimeout(mermaidAddHideTimer); mermaidAddHideTimer = null; }
  mermaidAddBtn.hidden = false;
  mermaidAddBtn.textContent = "Comment on diagram";
  const bw = mermaidAddBtn.offsetWidth || 160, bh = mermaidAddBtn.offsetHeight || 28;
  const left = rect.right - bw - 6, top = rect.top + 6;
  mermaidAddBtn.style.left = Math.max(8, Math.min(left, window.innerWidth - bw - 8)) + "px";
  mermaidAddBtn.style.top = Math.max(8, Math.min(top, window.innerHeight - bh - 8)) + "px";
  _activeAdd = { el: host, btn: mermaidAddBtn, position: () => showMermaidWholeFor(host), clear: () => { pendingMermaid = null; } };
  return _rectInViewport(rect);
}
function scheduleHideMermaidAdd() {
  if (mermaidAddHideTimer) clearTimeout(mermaidAddHideTimer);
  mermaidAddHideTimer = setTimeout(() => {
    if (!mermaidAddBtn.matches(":hover")) { mermaidAddBtn.hidden = true; mermaidActiveNode = null; pendingMermaid = null; }
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
      mermaidDiagrams.forEach(updateMermaidWidthClass);
    });
  }
  // A diagram rendered while its section was collapsed had its wide/scroll-fade class computed against
  // a zero-size (window-fallback) container; recompute it when the host gains its real size on reveal.
  if (typeof ResizeObserver === "function") {
    if (setupMermaidLayer._widthObs) setupMermaidLayer._widthObs.disconnect();
    const widthObs = new ResizeObserver(function (entries) {
      entries.forEach(function (e) { updateMermaidWidthClass(e.target); });
    });
    mermaidDiagrams.forEach(function (host) { widthObs.observe(host); });
    setupMermaidLayer._widthObs = widthObs;
  }
}
