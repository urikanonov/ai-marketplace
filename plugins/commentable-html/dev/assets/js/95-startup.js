/* ---------- Handled-id pruning + startup ---------- */
function getHandledIds() {
  const el = document.getElementById("handledCommentIds");
  if (!el) return new Set();
  try {
    const arr = JSON.parse((el.textContent || "").trim() || "[]");
    return new Set(arr);
  } catch (e) { console.warn("Could not parse handledCommentIds JSON:", e); return new Set(); }
}
function pruneHandled() {
  const handled = getHandledIds();
  const before = comments.length;
  comments = comments.filter(c => !handled.has(c.id));
  const removed = before - comments.length;
  saveComments();
  return removed;
}
function withoutHandled(arr) {
  const handled = getHandledIds();
  if (!handled.size) return arr;
  return arr.filter(c => !handled.has(c.id));
}
function restoreHighlights() {
  const textComments = comments.filter(c => c.anchorType !== "mermaid" && c.anchorType !== "diff"
    && c.anchorType !== "image" && c.anchorType !== "widget" && c.anchorType !== "document");
  const sorted = [...textComments].sort((a, b) => a.start - b.start);
  sorted.forEach(c => {
    const r = rangeFromOffsets(c.start, c.end);
    if (r) {
      try { wrapRangeWithMark(r, c.id); }
      catch (e) { console.warn("Could not restore highlight for", c.id, e); }
    } else {
      console.warn("Lost anchor for comment", c.id, "- offsets", c.start, c.end);
    }
  });
}


function setupChartContainment() {
  root.querySelectorAll("figure.chart > .chart-wrap").forEach(function (wrap) {
    if (!wrap.style.position) wrap.style.position = "relative";
  });
  if (window.Chart && window.Chart.defaults) {
    window.Chart.defaults.responsive = true;
    window.Chart.defaults.maintainAspectRatio = false;
  }
}

function setupFooter() {
  if (document.getElementById("cmFooter")) return;
  const f = document.createElement("footer");
  f.id = "cmFooter";
  f.className = "cm-skip cm-footer";
  f.setAttribute("aria-label", "About Commentable HTML");
  let gen = root.getAttribute("data-generated");
  if (!gen) { const lm = Date.parse(document.lastModified); if (!isNaN(lm)) gen = new Date(lm).toISOString(); }
  const genStr = gen ? formatTime(gen) : "unknown";
  f.innerHTML =
    cmBrandLink(CMH_ICON_SVG
      + '<span class="cm-footer-name">Commentable HTML <span class="cm-footer-ver">v' + CMH_VERSION + '</span></span>')
    + '<span class="cm-footer-sep" aria-hidden="true">\u00b7</span>'
    + '<span class="cm-footer-gen">Generated ' + escapeHtml(genStr) + '</span>'
    + '<span class="cm-footer-sep" aria-hidden="true">\u00b7</span>'
    + '<button type="button" class="cm-footer-help">Help &amp; about</button>';
  document.body.appendChild(f);
  document.body.classList.add("cm-has-footer");
  const hb = f.querySelector(".cm-footer-help");
  if (hb) hb.addEventListener("click", function () { showHelp(hb); });
  setupFooterSessionCopy(f);
}

// Footer control that copies the creating AI agent's session id (CMH-FOOT-04). It appears only
// when the document carries a `commentable-html-session-id` provenance stamp (written by the
// authoring tools by default; opt out with --no-session-id). The `commentable-html-agent` slug
// names the copy tooltip. Like the rest of the footer it is cm-skip chrome, so it never bakes into
// a Plain HTML export and is re-derived from the meta on load.
function _cmSessionMeta(name) {
  const m = document.querySelector('meta[name="' + name + '"]');
  return m ? (m.getAttribute("content") || "").trim() : "";
}
function _cmAgentLabel(slug) {
  const s = (slug || "").toLowerCase();
  if (s === "copilot") return "Copilot";
  if (s === "claude") return "Claude";
  return slug || "AI";
}
function setupFooterSessionCopy(footer) {
  const sid = _cmSessionMeta("commentable-html-session-id");
  if (!sid) return;
  const label = "Copy " + _cmAgentLabel(_cmSessionMeta("commentable-html-agent")) + " session id";
  const sep = document.createElement("span");
  sep.className = "cm-footer-sep";
  sep.setAttribute("aria-hidden", "true");
  sep.textContent = "\u00b7";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "cm-footer-copy-session";
  btn.setAttribute("aria-label", label);
  btn.setAttribute("data-cmh-tip", label);
  btn.innerHTML = _cmIco("clipboard", 14);
  btn.addEventListener("click", function () { copyPlain(sid, "Session id copied to clipboard."); });
  const help = footer.querySelector(".cm-footer-help");
  if (help) { footer.insertBefore(sep, help); footer.insertBefore(btn, help); }
  else { footer.appendChild(sep); footer.appendChild(btn); }
}

// Lightweight, dependency-free tooltip layer. It upgrades the native `title` on chrome
// controls into a styled hover/focus bubble. On first hover the title is moved to
// data-cmh-tip (so the browser's own delayed tooltip never double-shows) and mirrored
// to aria-label ONLY when the control has no other accessible name, so visible-text
// buttons keep their name. Delegated at the document, so controls created later
// (composers, add buttons, carets, copy buttons) are covered with no re-init.
let _cmTipEl = null, _cmTipTimer = null, _cmTipFor = null, _cmTipPending = null;
function _cmTipTarget(node) {
  let el = node;
  while (el && el.nodeType === 1) {
    if ((el.hasAttribute("data-cmh-tip") || el.hasAttribute("title")) && el.closest(".cm-skip")) return el;
    el = el.parentElement;
  }
  return null;
}
function _cmTipText(el) {
  const t = el.getAttribute("title");
  if (t != null) {
    // A freshly-set title (including a runtime `.title =` update) wins over any cached
    // value, and is moved out of `title` so the browser's own tooltip never doubles up.
    el.setAttribute("data-cmh-tip", t);
    el.removeAttribute("title");
    if (!el.getAttribute("aria-label") && !el.getAttribute("aria-labelledby") && !(el.textContent || "").trim())
      el.setAttribute("aria-label", t);
    return t;
  }
  return el.getAttribute("data-cmh-tip") || "";
}
function _cmTipShow(el) {
  if (_cmTipTimer) { clearTimeout(_cmTipTimer); _cmTipTimer = null; }
  _cmTipPending = null;
  if (!el.isConnected) return;
  const text = _cmTipText(el);
  if (!text) return;
  if (!_cmTipEl) {
    _cmTipEl = document.createElement("div");
    _cmTipEl.className = "cm-tooltip cm-skip";
    _cmTipEl.setAttribute("role", "tooltip");
    document.body.appendChild(_cmTipEl);
  }
  _cmTipFor = el;
  _cmTipEl.textContent = text;
  _cmTipEl.classList.remove("below");
  _cmTipEl.style.visibility = "hidden";
  _cmTipEl.classList.add("is-visible");
  const r = el.getBoundingClientRect();
  const tw = _cmTipEl.offsetWidth, th = _cmTipEl.offsetHeight;
  let left = r.left + r.width / 2 - tw / 2;
  let top = r.top - th - 8;
  if (top < 6) { top = r.bottom + 8; _cmTipEl.classList.add("below"); }
  left = Math.max(6, Math.min(left, window.innerWidth - tw - 6));
  _cmTipEl.style.left = left + "px";
  _cmTipEl.style.top = top + "px";
  const cx = r.left + r.width / 2 - left;
  _cmTipEl.style.setProperty("--cm-tip-arrow", Math.max(10, Math.min(tw - 10, cx)) + "px");
  _cmTipEl.style.visibility = "";
}
function _cmTipHide() {
  if (_cmTipTimer) { clearTimeout(_cmTipTimer); _cmTipTimer = null; }
  _cmTipPending = null; _cmTipFor = null;
  if (_cmTipEl) _cmTipEl.classList.remove("is-visible");
}
function _cmTipSchedule(el) {
  if (el === _cmTipFor) { if (_cmTipTimer) { clearTimeout(_cmTipTimer); _cmTipTimer = null; } return; }
  if (el === _cmTipPending) return;
  if (_cmTipTimer) clearTimeout(_cmTipTimer);
  _cmTipText(el); // strip the native title now so the browser tooltip cannot show during the delay
  _cmTipPending = el;
  _cmTipTimer = setTimeout(function () {
    _cmTipTimer = null; _cmTipPending = null;
    if (el.isConnected) _cmTipShow(el);
  }, 350);
}
function setupTooltips() {
  if (setupTooltips._done) return; // idempotent - never double-bind the document listeners
  setupTooltips._done = true;
  const hoverCapable = !(window.matchMedia && window.matchMedia("(hover: none)").matches);
  if (hoverCapable) {
    document.addEventListener("mouseover", function (e) {
      if (_cmTipFor && !_cmTipFor.isConnected) _cmTipHide(); // heal a bubble whose control was removed
      const el = _cmTipTarget(e.target);
      if (el) _cmTipSchedule(el); else if (!_cmTipTarget(e.relatedTarget)) _cmTipHide();
    }, true);
    document.addEventListener("mouseout", function (e) {
      const from = _cmTipTarget(e.target);
      if (from && from !== _cmTipTarget(e.relatedTarget)) _cmTipHide();
    }, true);
  }
  // Focus tooltips work for keyboard users on every device, including touch/hybrid, so
  // they are wired even when hover is unavailable.
  document.addEventListener("focusin", function (e) {
    const el = _cmTipTarget(e.target);
    if (el) _cmTipShow(el); else _cmTipHide();
  }, true);
  document.addEventListener("focusout", _cmTipHide, true);
  window.addEventListener("scroll", _cmTipHide, true);
  document.addEventListener("mousedown", _cmTipHide, true);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") _cmTipHide(); }, true);
}
loadComments();
const prunedCount = pruneHandled();
// setupDiffLayer must run BEFORE any text-offset computation: it wraps each
// authored <pre class="cmh-diff"> in a .cm-skip host, removing the diff text from
// the offset coordinate system. Running it before backfillContext/restoreHighlights
// keeps text-comment offsets consistent between save time and reload.
setupDiffLayer();
setupNotesLayer();
applyPersistedTableSorts();
backfillContext();
restoreHighlights();
setupMermaidLayer();
setupImageLayer();
setupWidgetLayer();
setupChecklistLayer();
setupChartContainment();
setupCodeCopy();
setupSortableTables();
setupModeUi();
setupSidebarResize();
setupCommentSearch();
setupPrintAppendix();
function setupDeck() {
  if (window.__cmhDeck) return;  // idempotent: never install the deck chrome twice
  const stage = root.querySelector(".deck-stage");
  const viewport = root.querySelector(".deck-viewport") || stage && stage.parentNode;
  const slides = stage ? Array.prototype.slice.call(stage.querySelectorAll(".slide")) : [];
  if (!stage || !slides.length) return;

  let current = slides.findIndex((s) => s.classList.contains("active"));
  if (current < 0) current = 0;
  let commentMode = false;
  let counter = null, prevBtn = null, nextBtn = null;
  let edgePrevBtn = null, edgeNextBtn = null;
  let overview = null, overviewGrid = null, overviewBtn = null, overviewDismiss = null;
  const stageFocusTarget = viewport || stage;
  const slideTitles = slides.map((slide, i) => slideTitle(slide, i));
  // Start clean: a stale comment-mode class (e.g. from a serialized live DOM) must not fight
  // the present-mode default applied below.
  root.classList.remove("cmh-deck-comment-mode");
  if (stageFocusTarget && stageFocusTarget.setAttribute) {
    stageFocusTarget.tabIndex = -1;
    if (!stageFocusTarget.getAttribute("aria-label")) stageFocusTarget.setAttribute("aria-label", "Slide stage");
  }

  function slideTitle(slide, index) {
    const explicit = slide.getAttribute("data-slide-title") || slide.getAttribute("aria-label");
    const heading = slide.querySelector("h1,h2,h3,h4,h5,h6");
    const text = explicit || (heading && heading.textContent) || slide.getAttribute("data-slide-id");
    return (text || ("Slide " + (index + 1))).replace(/\s+/g, " ").trim();
  }

  function fitStage() {
    const host = viewport || document.documentElement;
    const vw = host.clientWidth || window.innerWidth;
    const vh = host.clientHeight || window.innerHeight;
    const scale = Math.min(vw / 1920, vh / 1080);
    const x = (vw - 1920 * scale) / 2;
    const y = (vh - 1080 * scale) / 2;
    stage.style.transform = "translate(" + x + "px, " + y + "px) scale(" + scale + ")";
    syncEdgeNavPosition();
  }

  function focusStage() {
    if (!stageFocusTarget || !stageFocusTarget.focus || commentMode || hasBlockingDeckChrome()) return;
    try { stageFocusTarget.focus({ preventScroll: true }); }
    catch (e) {
      try { stageFocusTarget.focus(); } catch (_e) {}
    }
  }

  function slideIdAt(index) {
    return slides[index] && slides[index].getAttribute("data-slide-id");
  }

  function hashSlideId() {
    const raw = (location.hash || "").slice(1);
    if (!raw) return "";
    try { return decodeURIComponent(raw); } catch (e) { return raw; }
  }

  function hashForSlideId(id) {
    return "#" + encodeURIComponent(id);
  }

  function indexBySlideId(id) {
    if (!id) return -1;
    return slides.findIndex((s) => s.getAttribute("data-slide-id") === id);
  }

  function syncSlideHash() {
    const id = slideIdAt(current);
    if (!id || hashSlideId() === id) return;
    const nextHash = hashForSlideId(id);
    if (window.history && history.replaceState) history.replaceState(null, "", nextHash);
    else location.hash = nextHash;
  }

  function showFromHash() {
    const index = indexBySlideId(hashSlideId());
    return index >= 0 ? show(index) : false;
  }

  const hashIndex = indexBySlideId(hashSlideId());
  if (hashIndex >= 0) current = hashIndex;

  function show(index) {
    if (!Number.isInteger(index) || index < 0 || index >= slides.length) return false;
    const changed = index !== current;
    slides.forEach((s, i) => {
      s.classList.toggle("active", i === index);
      s.classList.toggle("visible", i === index);
    });
    current = index;
    if (counter) {
      counter.textContent = (index + 1) + " / " + slides.length;
      // Screen readers announce the live region's text; a bare "2 / 4" reads as "2 slash 4",
      // so expose a spoken form via the label.
      counter.setAttribute("aria-label", "Slide " + (index + 1) + " of " + slides.length);
    }
    if (prevBtn) prevBtn.disabled = index === 0;
    if (nextBtn) nextBtn.disabled = index === slides.length - 1;
    syncOverview();
    syncSlideHash();
    hideEdgeNav();
    // Fire only on a real move (a changed active slide), never for the initial render or a
    // re-selection of the already-active slide.
    if (changed) {
      document.dispatchEvent(new CustomEvent("cmh:slidechange", {
        detail: { slideId: slideIdAt(index), index },
      }));
    }
    return true;
  }
  function showById(id) {
    const i = indexBySlideId(id);
    return i >= 0 ? show(i) : false;
  }

  function hasBlockingDeckChrome() {
    return !!(
      (overview && !overview.hidden)
      || document.querySelector(".cm-composer, .cm-modal-overlay")
    );
  }

  function stageHasFocus() {
    return !!stageFocusTarget && document.activeElement === stageFocusTarget;
  }

  function syncEdgeNavPosition() {
    if (!edgePrevBtn || !edgeNextBtn || !viewport || !viewport.getBoundingClientRect) return;
    const rect = viewport.getBoundingClientRect();
    const top = Math.max(20, rect.top + rect.height / 2);
    edgePrevBtn.style.top = top + "px";
    edgeNextBtn.style.top = top + "px";
    edgePrevBtn.style.left = Math.max(12, rect.left + 16) + "px";
    edgeNextBtn.style.left = Math.max(12, rect.right - 64) + "px";
  }

  function hideEdgeNav() {
    [edgePrevBtn, edgeNextBtn].forEach((btn) => {
      if (!btn) return;
      btn.classList.remove("is-active");
      btn.style.removeProperty("--cmh-deck-edge-opacity");
    });
  }

  function syncEdgeNavButton(btn, strength, enabled) {
    if (!btn) return;
    const active = enabled && strength > 0;
    btn.classList.toggle("is-active", active);
    if (active) btn.style.setProperty("--cmh-deck-edge-opacity", String((0.2 + strength * 0.75).toFixed(3)));
    else btn.style.removeProperty("--cmh-deck-edge-opacity");
  }

  function updateEdgeNavFromPointer(clientX, clientY) {
    if (!edgePrevBtn || !edgeNextBtn || !viewport || commentMode || hasBlockingDeckChrome()) {
      hideEdgeNav();
      return;
    }
    const rect = viewport.getBoundingClientRect();
    const within = clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
    if (!within) {
      hideEdgeNav();
      return;
    }
    syncEdgeNavPosition();
    const threshold = Math.min(168, Math.max(80, rect.width * 0.12));
    const prevStrength = Math.max(0, Math.min(1, (threshold - (clientX - rect.left)) / threshold));
    const nextStrength = Math.max(0, Math.min(1, (threshold - (rect.right - clientX)) / threshold));
    syncEdgeNavButton(edgePrevBtn, prevStrength, current > 0);
    syncEdgeNavButton(edgeNextBtn, nextStrength, current < slides.length - 1);
  }

  function makeEdgeNav() {
    if (edgePrevBtn && edgeNextBtn) return;
    const prev = document.createElement("button");
    prev.type = "button";
    prev.className = "cm-skip cmh-deck-edge-nav cmh-deck-edge-nav-prev";
    prev.textContent = "<";
    prev.setAttribute("aria-label", "Prev slide");
    prev.title = "Prev slide";
    prev.addEventListener("click", () => {
      if (show(current - 1)) focusStage();
    });
    const next = document.createElement("button");
    next.type = "button";
    next.className = "cm-skip cmh-deck-edge-nav cmh-deck-edge-nav-next";
    next.textContent = ">";
    next.setAttribute("aria-label", "Next slide");
    next.title = "Next slide";
    next.addEventListener("click", () => {
      if (show(current + 1)) focusStage();
    });
    edgePrevBtn = prev;
    edgeNextBtn = next;
    document.body.appendChild(prev);
    document.body.appendChild(next);
    CMH_INJECTED_CHROME.add(prev);
    CMH_INJECTED_CHROME.add(next);
    syncEdgeNavPosition();
    document.addEventListener("mousemove", (e) => updateEdgeNavFromPointer(e.clientX, e.clientY));
    viewport.addEventListener("mouseleave", hideEdgeNav);
    viewport.addEventListener("pointerdown", (e) => {
      if (commentMode || hasBlockingDeckChrome() || isEditableTarget(e.target)) return;
      focusStage();
      updateEdgeNavFromPointer(e.clientX, e.clientY);
    });
  }

  function overviewCards() {
    return overviewGrid ? Array.prototype.slice.call(overviewGrid.querySelectorAll(".cmh-deck-overview-card")) : [];
  }

  function syncOverview() {
    overviewCards().forEach((card, i) => {
      const active = i === current;
      card.classList.toggle("is-current", active);
      if (active) card.setAttribute("aria-current", "true");
      else card.removeAttribute("aria-current");
    });
  }

  function focusOverviewCard(index) {
    const cards = overviewCards();
    if (!cards.length) return;
    const next = Math.max(0, Math.min(cards.length - 1, index));
    cards[next].focus();
  }

  // Namespace every id inside a cloned inline SVG (root included) with a per-clone
  // prefix and rewrite every reference to those ids - url(...) in presentation
  // attributes and inline style, href / xlink:href fragment refs, and the
  // aria-labelledby / aria-describedby idref lists. This keeps each thumbnail's
  // gradient/mask/filter/marker refs resolving to ITS OWN defs while guaranteeing the
  // clones never duplicate an id already in the document (which would let the browser
  // resolve url(#id) to the wrong, first-in-document definition).
  var overviewSvgIdSeq = 0;
  function namespaceSvgIds(svg) {
    var withId = [];
    if (svg.hasAttribute("id")) withId.push(svg);
    svg.querySelectorAll("[id]").forEach(function (el) { withId.push(el); });
    if (!withId.length) return;
    var prefix = "cmhov" + (overviewSvgIdSeq++) + "-";
    var map = Object.create(null);
    withId.forEach(function (el) {
      var old = el.getAttribute("id");
      var neu = prefix + old;
      el.setAttribute("id", neu);
      map[old] = neu;
    });
    var XLINK = "http://www.w3.org/1999/xlink";
    var rewriteUrls = function (v) {
      return v.replace(/url\(\s*(['"]?)#([^'")\s]+)\1\s*\)/g, function (m, q, id) {
        return map[id] ? "url(#" + map[id] + ")" : m;
      });
    };
    var rewriteRef = function (v) {
      return (v && v.charAt(0) === "#" && map[v.slice(1)]) ? "#" + map[v.slice(1)] : v;
    };
    var rewriteIdList = function (v) {
      return v.split(/\s+/).map(function (t) { return map[t] || t; }).join(" ");
    };
    var URL_ATTRS = ["fill", "stroke", "clip-path", "mask", "filter", "marker", "marker-start", "marker-mid", "marker-end"];
    var IDLIST_ATTRS = ["aria-labelledby", "aria-describedby"];
    var els = [svg];
    svg.querySelectorAll("*").forEach(function (el) { els.push(el); });
    els.forEach(function (el) {
      if (el.hasAttribute("style")) el.setAttribute("style", rewriteUrls(el.getAttribute("style")));
      URL_ATTRS.forEach(function (a) { if (el.hasAttribute(a)) el.setAttribute(a, rewriteUrls(el.getAttribute(a))); });
      if (el.hasAttribute("href")) el.setAttribute("href", rewriteRef(el.getAttribute("href")));
      var xh = el.getAttributeNS ? el.getAttributeNS(XLINK, "href") : null;
      if (xh) el.setAttributeNS(XLINK, "href", rewriteRef(xh));
      IDLIST_ATTRS.forEach(function (a) { if (el.hasAttribute(a)) el.setAttribute(a, rewriteIdList(el.getAttribute(a))); });
    });
  }

  function cleanOverviewClone(node) {
    if (node.removeAttribute) node.removeAttribute("id");
    if (node.classList) node.classList.remove("active", "visible");
    node.setAttribute("inert", "");
    node.inert = true;
    node.tabIndex = -1;
    // Strip non-SVG ids so the clones do not duplicate document ids. Ids INSIDE an
    // <svg> are needed (it references its own gradients/masks/filters by url(#id);
    // removing them made the reference fall back to black - the slide-1 logo bug), so
    // instead of leaving them raw (which would duplicate ids across the thumbnails and
    // the live slide and make url(#id) resolve to the wrong def) we namespace each
    // SVG's ids uniquely per clone and rewrite every reference to them.
    node.querySelectorAll("[id]").forEach((el) => { if (!el.closest("svg")) el.removeAttribute("id"); });
    node.querySelectorAll("svg").forEach((svg) => namespaceSvgIds(svg));
    node.querySelectorAll("mark.cm-hl").forEach((mark) => {
      mark.replaceWith(...Array.prototype.slice.call(mark.childNodes));
    });
    node.querySelectorAll("a[href],area[href]").forEach((el) => {
      el.removeAttribute("href");
      el.tabIndex = -1;
    });
    node.querySelectorAll("[data-cid],[data-cids]").forEach((el) => {
      el.removeAttribute("data-cid");
      el.removeAttribute("data-cids");
    });
    node.querySelectorAll(
      "a,area,button,input,select,textarea,summary,iframe,object,embed,audio[controls],video[controls],[tabindex],[contenteditable]"
    ).forEach((el) => {
      el.tabIndex = -1;
      if (el.hasAttribute("contenteditable")) el.setAttribute("contenteditable", "false");
    });
  }

  function makeOverview() {
    if (overview) return;
    overview = document.createElement("section");
    overview.id = "cmhDeckOverview";
    overview.className = "cm-skip cmh-deck-overview";
    overview.hidden = true;
    overview.setAttribute("role", "dialog");
    overview.setAttribute("aria-modal", "false");
    overview.setAttribute("aria-labelledby", "cmhDeckOverviewTitle");

    const head = document.createElement("div");
    head.className = "cmh-deck-overview-head";
    const titleWrap = document.createElement("div");
    titleWrap.className = "cmh-deck-overview-titlewrap";
    const title = document.createElement("h2");
    title.id = "cmhDeckOverviewTitle";
    title.className = "cmh-deck-overview-title";
    title.textContent = "Slide overview";
    const count = document.createElement("span");
    count.className = "cmh-deck-overview-count";
    count.textContent = slides.length + (slides.length === 1 ? " slide" : " slides");
    titleWrap.appendChild(title);
    titleWrap.appendChild(count);
    const close = document.createElement("button");
    close.type = "button";
    close.className = "cmh-deck-overview-close";
    close.textContent = "Close";
    close.setAttribute("aria-label", "Close slide overview");
    close.addEventListener("click", () => closeOverview());
    head.appendChild(titleWrap);
    head.appendChild(close);

    overviewGrid = document.createElement("div");
    overviewGrid.className = "cmh-deck-overview-grid";
    overviewGrid.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeOverview();
        return;
      }
      const cards = overviewCards();
      const at = cards.indexOf(document.activeElement);
      if (e.key === "Tab") {
        e.preventDefault();
        const next = at < 0 ? current : (at + (e.shiftKey ? -1 : 1) + cards.length) % cards.length;
        focusOverviewCard(next);
        return;
      }
      let next = at;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") next = at < 0 ? current : at + 1;
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = at < 0 ? current : at - 1;
      else if (e.key === "Home") next = 0;
      else if (e.key === "End") next = cards.length - 1;
      else return;
      e.preventDefault();
      focusOverviewCard(next);
    });

    slides.forEach((slide, i) => {
      const card = document.createElement("button");
      const id = slide.getAttribute("data-slide-id") || "";
      const titleText = slideTitles[i];
      card.type = "button";
      card.className = "cmh-deck-overview-card";
      card.title = titleText;
      card.setAttribute("aria-label", "Slide " + (i + 1) + ": " + titleText);
      card.setAttribute("data-slide-index", String(i));
      card.setAttribute("data-slide-id", id);

      const thumb = document.createElement("span");
      thumb.className = "cmh-deck-overview-thumb";
      const scale = document.createElement("span");
      scale.className = "cmh-deck-overview-scale";
      const clone = slide.cloneNode(true);
      // The overview clones live outside #commentRoot, so deck-scoped rules like
      // `#commentRoot[data-cmh-mode="deck"] .logo-line { fill: #fff }` do not reach
      // them and SVG shapes fall back to black. Copy each original shape's computed
      // fill/stroke inline onto the clone (done on the fresh clone so the node order
      // still matches the original) so scoped styling survives the move.
      const oAll = slide.querySelectorAll("*");
      const cAll = clone.querySelectorAll("*");
      for (let k = 0; k < oAll.length && k < cAll.length; k++) {
        const o = oAll[k];
        if (o instanceof SVGElement && o.tagName.toLowerCase() !== "svg") {
          const cs = getComputedStyle(o);
          if (cs.fill && cs.fill !== "none") cAll[k].style.fill = cs.fill;
          if (cs.stroke && cs.stroke !== "none") cAll[k].style.stroke = cs.stroke;
        }
      }
      cleanOverviewClone(clone);
      // A cloned <canvas> is blank (the bitmap does not clone), which showed as black
      // bars in the overview. Snapshot each original canvas into an <img> in the clone.
      const origCanvases = slide.querySelectorAll("canvas");
      const cloneCanvases = clone.querySelectorAll("canvas");
      origCanvases.forEach((oc, ci) => {
        const cc = cloneCanvases[ci];
        if (!cc) return;
        let url = null;
        try { url = oc.toDataURL("image/png"); } catch (e) { url = null; }
        if (!url) return;
        const img = document.createElement("img");
        img.src = url;
        img.setAttribute("aria-hidden", "true");
        if (cc.getAttribute("style")) img.setAttribute("style", cc.getAttribute("style"));
        if (cc.className) img.className = cc.className;
        img.width = cc.width || oc.width;
        img.height = cc.height || oc.height;
        cc.replaceWith(img);
      });
      clone.setAttribute("aria-hidden", "true");
      scale.appendChild(clone);
      thumb.appendChild(scale);

      const label = document.createElement("span");
      label.className = "cmh-deck-overview-card-label";
      label.textContent = (i + 1) + ". " + titleText;
      card.appendChild(thumb);
      card.appendChild(label);
      card.addEventListener("click", () => {
        if (show(i)) closeOverview();
      });
      overviewGrid.appendChild(card);
    });

    overview.appendChild(head);
    overview.appendChild(overviewGrid);
    document.body.appendChild(overview);
    CMH_INJECTED_CHROME.add(overview);
    syncOverview();
  }

  function openOverview() {
    makeOverview();
    overview.hidden = false;
    document.body.classList.add("cmh-deck-overview-open");
    if (overviewBtn) {
      overviewBtn.setAttribute("aria-expanded", "true");
      overviewBtn.classList.add("cmh-deck-overview-on");
    }
    // Dismiss on a click in the main deck area (a slide / the stage / the content root), but not
    // on the overview panel, the nav bar, or the mode toggle (those live outside #commentRoot).
    if (!overviewDismiss) {
      overviewDismiss = (e) => {
        if (!overview || overview.hidden) return;
        const t = e.target;
        if (t && t.closest && t.closest(".deck-viewport, #commentRoot")) closeOverview();
      };
    }
    document.addEventListener("click", overviewDismiss);
    syncOverview();
    focusOverviewCard(current);
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => focusOverviewCard(current));
    hideEdgeNav();
  }

  function closeOverview() {
    if (!overview || overview.hidden) return;
    overview.hidden = true;
    document.body.classList.remove("cmh-deck-overview-open");
    if (overviewDismiss) document.removeEventListener("click", overviewDismiss);
    if (overviewBtn) {
      overviewBtn.setAttribute("aria-expanded", "false");
      overviewBtn.classList.remove("cmh-deck-overview-on");
      overviewBtn.focus();
    }
  }

  function toggleOverview() {
    if (overview && !overview.hidden) closeOverview();
    else openOverview();
  }

  window.__cmhDeck = {
    showSlide: show,
    showSlideById: showById,
    activeSlideId: () => slides[current] && slides[current].getAttribute("data-slide-id"),
    slideCount: () => slides.length,
  };

  show(current);
  fitStage();
  makeEdgeNav();
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(fitStage).observe(viewport || document.documentElement);
  } else {
    window.addEventListener("resize", fitStage);
  }
  // Default to a clean full-screen presentation: hide the comment sidebar/toolbar until the
  // user enters comment mode (see the cmh-deck-present CSS).
  document.body.classList.add("cmh-deck-present");

  function isEditableTarget(t) {
    if (!t) return false;
    if (t.isContentEditable) return true;
    const tag = t.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
    return !!(t.closest && t.closest(".cm-skip"));
  }
  document.addEventListener("keydown", (e) => {
    if (!e.defaultPrevented && overview && !overview.hidden) {
      if (e.key === "Escape" || (e.key && e.key.toLowerCase() === "o"
        && !e.altKey && !e.ctrlKey && !e.metaKey)) {
        e.preventDefault();
        closeOverview();
      }
      return;
    }
    const overviewShortcutTarget = e.target === overviewBtn || !isEditableTarget(e.target);
    if (!e.defaultPrevented && overviewShortcutTarget && e.key && e.key.toLowerCase() === "o"
      && !e.altKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      toggleOverview();
      return;
    }
    if (!commentMode && !e.defaultPrevented && !hasBlockingDeckChrome() && stageHasFocus()
      && (e.key === "Enter" || e.key === " " || e.key === "Spacebar")) {
      if (show(current + 1)) e.preventDefault();
      return;
    }
    if (commentMode || e.defaultPrevented || isEditableTarget(e.target) || hasBlockingDeckChrome()) return;
    if (e.key === "ArrowRight" || e.key === "PageDown") {
      if (show(current + 1)) e.preventDefault();
    } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
      if (show(current - 1)) e.preventDefault();
    } else if (e.key === "Home") {
      if (show(0)) e.preventDefault();
    } else if (e.key === "End") {
      if (show(slides.length - 1)) e.preventDefault();
    }
  });
  window.addEventListener("hashchange", showFromHash);

  // Deck-aware jump: activating a comment card navigates to its owning slide before the
  // layer's own scrollIntoView (which cannot reveal a hidden slide) runs.
  document.addEventListener("click", (e) => {
    const card = e.target.closest && e.target.closest(".cm-card[data-cid]");
    if (!card) return;
    const cid = card.getAttribute("data-cid");
    if (!cid) return;
    const q = (window.CSS && CSS.escape) ? CSS.escape(cid) : cid;
    const anchor = root.querySelector(
      'mark.cm-hl[data-cid="' + q + '"], [data-cids~="' + q + '"], [data-cid="' + q + '"]');
    const slide = anchor && anchor.closest(".slide");
    if (slide) showById(slide.getAttribute("data-slide-id"));
  }, true);

  function setCommentMode(on) {
    commentMode = on;
    root.classList.toggle("cmh-deck-comment-mode", on);
    document.body.classList.toggle("cmh-deck-present", !on);
    try { if (on) openSidebar(); else closeSidebar(); } catch (e) { /* sidebar helpers are optional */ }
    toggle.setAttribute("aria-pressed", String(on));
    toggle.classList.toggle("cmh-deck-mode-on", on);
    hideEdgeNav();
    // Comment mode narrows the stage (the sidebar takes width); refit after layout settles.
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(() => {
        fitStage();
        if (!on) focusStage();
      });
    } else {
      fitStage();
      if (!on) focusStage();
    }
  }
  const toggle = document.createElement("button");
  toggle.className = "cm-skip cmh-deck-mode-toggle";
  toggle.type = "button";
  // Stable accessible name; state is conveyed by aria-pressed + the on-colour, per the ARIA
  // toggle-button pattern (a name that flips to "Present" would read "Present, pressed").
  // A distinct annotate (pencil) icon - NOT the brand speech-bubble the site link below uses -
  // so the two top-corner controls are visually distinguishable, not identical bubbles.
  toggle.innerHTML = '<svg class="cmh-deck-mode-icon" viewBox="0 0 24 24" width="20" height="20"'
    + ' fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
    + ' aria-hidden="true" focusable="false"><path d="M12 20h9"/>'
    + '<path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
  const toggleIcon = toggle.querySelector("svg");
  if (toggleIcon) {
    toggleIcon.setAttribute("aria-hidden", "true");
    toggleIcon.setAttribute("focusable", "false");
    toggleIcon.removeAttribute("role");
    toggleIcon.removeAttribute("aria-label");
    toggleIcon.removeAttribute("data-cmh-tip");
  }
  toggle.title = "Comment Mode";
  toggle.setAttribute("aria-label", "Comment Mode");
  toggle.setAttribute("aria-pressed", "false");
  toggle.addEventListener("click", () => { setCommentMode(!commentMode); toggle.blur(); });
  document.body.prepend(toggle);
  const brandLink = document.createElement("a");
  brandLink.className = "cm-skip cm-brand-link cmh-deck-brand-link";
  brandLink.href = CMH_SITE_URL;
  brandLink.target = "_blank";
  brandLink.rel = "noopener noreferrer";
  brandLink.title = "Commentable HTML site";
  brandLink.setAttribute("aria-label", "Commentable HTML site (opens in a new tab)");
  brandLink.innerHTML = CMH_ICON_SVG;
  const brandIcon = brandLink.querySelector("svg");
  if (brandIcon) {
    brandIcon.setAttribute("aria-hidden", "true");
    brandIcon.setAttribute("focusable", "false");
    brandIcon.removeAttribute("role");
    brandIcon.removeAttribute("aria-label");
    brandIcon.removeAttribute("data-cmh-tip");
  }
  toggle.after(brandLink);

  const nav = document.createElement("div");
  nav.className = "cm-skip cmh-deck-nav";
  const prev = document.createElement("button");
  prev.type = "button"; prev.textContent = "Prev"; prev.setAttribute("aria-label", "Prev slide");
  prev.addEventListener("click", () => {
    if (show(current - 1)) focusStage();
    prev.blur();
  });
  prevBtn = prev;
  counter = document.createElement("span");
  counter.className = "cmh-deck-count";
  counter.setAttribute("aria-live", "polite");
  counter.textContent = (current + 1) + " / " + slides.length;
  counter.setAttribute("aria-label", "Slide " + (current + 1) + " of " + slides.length);
  const overviewControl = document.createElement("button");
  overviewControl.className = "cmh-deck-overview-button";
  overviewControl.type = "button";
  overviewControl.textContent = "Overview";
  overviewControl.title = "Slide overview";
  overviewControl.setAttribute("aria-label", "Slide overview");
  overviewControl.setAttribute("aria-controls", "cmhDeckOverview");
  overviewControl.setAttribute("aria-expanded", "false");
  overviewControl.addEventListener("click", toggleOverview);
  overviewBtn = overviewControl;
  const next = document.createElement("button");
  next.type = "button"; next.textContent = "Next"; next.setAttribute("aria-label", "Next slide");
  next.addEventListener("click", () => {
    if (show(current + 1)) focusStage();
    next.blur();
  });
  nextBtn = next;
  prev.disabled = current === 0;
  next.disabled = current === slides.length - 1;
  nav.appendChild(prev); nav.appendChild(counter); nav.appendChild(overviewControl); nav.appendChild(next);
  // Focus order: the toggle sits at the top of the DOM (top-right visually), the nav bar at the
  // end (bottom visually), so keyboard focus flows toggle -> slide content -> navigation.
  document.body.appendChild(nav);
  focusStage();
}
if (IS_DECK) {
  setupDeck();
} else {
  setupHeadingAnchors();
  setupCollapsibleSections();
  setupSideToc();
  setupFooter();
  setupScrollProgress();
}
setupTooltips();
setupValidationBanner();
// Capture the layer chrome injected above while the host content that follows the layer
// <script> is still unparsed, so an export tail can exclude it (see _snapshotWithTail).
for (let cur = CMH_LAYER_SCRIPT; cur && cur.parentNode; cur = cur.parentNode) {
  for (let s = cur.nextSibling; s; s = s.nextSibling) {
    if (s.nodeType === 1) CMH_INJECTED_CHROME.add(s);
  }
  if (cur.parentNode === document.body) break;
}
renderComments();
if (prunedCount > 0) {
  showToast(`${prunedCount} previously-handled comment${prunedCount === 1 ? "" : "s"} cleared by the agent.`);
}
if (comments.length || (typeof checklistChanges === "function" && checklistChanges().length) || (typeof notesChanges === "function" && notesChanges().length)) openSidebar();
else closeSidebar();
// Signals the nonportable-mode bootstrap that the external runtime initialized, so
// the missing-companion-assets banner stays hidden.
window.__commentableHtmlReady = true;
window.__commentableHtmlVersion = CMH_VERSION;
})();
