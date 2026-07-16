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
  let overview = null, overviewGrid = null, overviewBtn = null, overviewDismiss = null;
  const slideTitles = slides.map((slide, i) => slideTitle(slide, i));
  // Start clean: a stale comment-mode class (e.g. from a serialized live DOM) must not fight
  // the present-mode default applied below.
  root.classList.remove("cmh-deck-comment-mode");

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
  }

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
    // Fire only on a real move (a changed active slide), never for the initial render or a
    // re-selection of the already-active slide.
    if (changed) {
      document.dispatchEvent(new CustomEvent("cmh:slidechange", {
        detail: { slideId: slides[index].getAttribute("data-slide-id"), index },
      }));
    }
    return true;
  }
  function showById(id) {
    if (!id) return false;
    const i = slides.findIndex((s) => s.getAttribute("data-slide-id") === id);
    return i >= 0 ? show(i) : false;
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

  function cleanOverviewClone(node) {
    if (node.removeAttribute) node.removeAttribute("id");
    if (node.classList) node.classList.remove("active", "visible");
    node.setAttribute("inert", "");
    node.inert = true;
    node.tabIndex = -1;
    node.querySelectorAll("[id]").forEach((el) => el.removeAttribute("id"));
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
      cleanOverviewClone(clone);
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
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => focusOverviewCard(current));
    else focusOverviewCard(current);
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
    if (commentMode || e.defaultPrevented || isEditableTarget(e.target)) return;
    if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") {
      if (show(current + 1)) e.preventDefault();
    } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
      if (show(current - 1)) e.preventDefault();
    } else if (e.key === "Home") {
      if (show(0)) e.preventDefault();
    } else if (e.key === "End") {
      if (show(slides.length - 1)) e.preventDefault();
    }
  });

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
    // Comment mode narrows the stage (the sidebar takes width); refit after layout settles.
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(fitStage); else fitStage();
  }
  const toggle = document.createElement("button");
  toggle.className = "cm-skip cmh-deck-mode-toggle";
  toggle.type = "button";
  // Stable accessible name; state is conveyed by aria-pressed + the on-colour, per the ARIA
  // toggle-button pattern (a name that flips to "Present" would read "Present, pressed").
  toggle.innerHTML = CMH_ICON_SVG;
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

  const nav = document.createElement("div");
  nav.className = "cm-skip cmh-deck-nav";
  const prev = document.createElement("button");
  prev.type = "button"; prev.textContent = "Prev"; prev.setAttribute("aria-label", "Prev slide");
  prev.addEventListener("click", () => { show(current - 1); prev.blur(); });
  prevBtn = prev;
  counter = document.createElement("span");
  counter.className = "cmh-deck-count";
  counter.setAttribute("aria-live", "polite");
  counter.textContent = (current + 1) + " / " + slides.length;
  counter.setAttribute("aria-label", "Slide " + (current + 1) + " of " + slides.length);
  const overviewControl = document.createElement("button");
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
  next.addEventListener("click", () => { show(current + 1); next.blur(); });
  nextBtn = next;
  prev.disabled = current === 0;
  next.disabled = current === slides.length - 1;
  nav.appendChild(prev); nav.appendChild(counter); nav.appendChild(overviewControl); nav.appendChild(next);
  // Focus order: the toggle sits at the top of the DOM (top-right visually), the nav bar at the
  // end (bottom visually), so keyboard focus flows toggle -> slide content -> navigation.
  document.body.appendChild(nav);
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
