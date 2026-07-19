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
  // Require finite start/end in addition to excluding the known non-text anchor types: a
  // malformed comment with neither (no real anchorType and no offsets - not something any
  // composer path produces) must not be treated as a text anchor, or rangeFromOffsets()
  // would still run its full-document text-node walk for it despite mergeCommentSets()
  // treating an offsetless entry as trivially sane. This keeps the per-comment restore
  // work bounded to comments that can actually resolve to a range.
  const textComments = comments.filter(c => c.anchorType !== "mermaid" && c.anchorType !== "diff"
    && c.anchorType !== "image" && c.anchorType !== "widget" && c.anchorType !== "document"
    && c.anchorType !== "slide"
    && Number.isFinite(c.start) && Number.isFinite(c.end));
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
  // Deck comment model (3 states): commentMode mirrors the pane-open state so the existing
  // navigation/focus/edge-nav gates keep working. deckMode is the persisted selection:
  //   "closed" - comments enabled, side panel closed (DEFAULT)
  //   "open"   - comments enabled, side panel open (review)
  //   "off"    - comments disabled (present-only), only selectable at zero comments
  let commentMode = false;
  let deckMode = "closed";
  let modeMenu = null, modeToggle = null, modeRadioItems = [];
  let counter = null, prevBtn = null, nextBtn = null;
  let edgePrevBtn = null, edgeNextBtn = null;
  let overview = null, overviewGrid = null, overviewBtn = null, overviewDismiss = null;
  let overviewSearch = null, overviewCount = null;
  const stageFocusTarget = viewport || stage;
  const slideTitles = slides.map((slide, i) => slideTitle(slide, i));
  // Start clean: a stale comment-mode class (e.g. from a serialized live DOM) must not fight
  // the present-mode default applied below.
  root.classList.remove("cmh-deck-comment-mode");
  if (stageFocusTarget && stageFocusTarget.setAttribute) {
    stageFocusTarget.tabIndex = -1;
    if (!stageFocusTarget.getAttribute("aria-label")) stageFocusTarget.setAttribute("aria-label", "Slide stage");
  }
  makeLandscapeHint();

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

  function makeLandscapeHint() {
    if (!window.matchMedia) return null;
    const mq = window.matchMedia("(max-width: 600px) and (orientation: portrait)");
    const hint = document.createElement("div");
    hint.className = "cm-skip cmh-deck-landscape-hint";
    hint.setAttribute("role", "note");
    hint.setAttribute("aria-label", "Deck viewing hint");
    hint.setAttribute("aria-live", "polite");
    hint.innerHTML = '<span>Best viewed in landscape. Rotate your device for larger slide text.</span>'
      + '<button type="button" aria-label="Dismiss landscape hint">Dismiss</button>';
    document.body.appendChild(hint);
    CMH_INJECTED_CHROME.add(hint);
    let dismissed = false;
    const sync = () => { hint.hidden = dismissed || !mq.matches; };
    const close = hint.querySelector("button");
    if (close) close.addEventListener("click", () => { dismissed = true; sync(); });
    if (mq.addEventListener) mq.addEventListener("change", sync);
    else if (mq.addListener) mq.addListener(sync);
    window.addEventListener("resize", sync);
    sync();
    return hint;
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
      || (modeMenu && !modeMenu.hidden)
      || _commentMenuOpen()
      || document.querySelector(".cm-composer, .cm-modal-overlay, .cm-comment-popover")
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
    edgePrevBtn.style.left = Math.max(12, rect.left + 20) + "px";
    edgeNextBtn.style.left = Math.max(12, rect.right - 76) + "px";
  }

  function hideEdgeNav() {
    [edgePrevBtn, edgeNextBtn].forEach((btn) => {
      if (!btn) return;
      btn.classList.remove("is-active");
      btn.style.removeProperty("--cmh-deck-edge-opacity");
    });
  }

  function syncEdgeNavButton(btn, active, enabled) {
    if (!btn) return;
    const on = enabled && active;
    btn.classList.toggle("is-active", on);
    // A fixed, comfortably-visible opacity so the arrow is reliably readable anywhere in the
    // hover band (not a proximity fade that is near-invisible until the very edge); the button's
    // own :hover/:focus rule takes it to full opacity.
    if (on) btn.style.setProperty("--cmh-deck-edge-opacity", "0.92");
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
    // A generous left/right hover band (about a quarter of the stage, floored/capped to a
    // usable pixel range) so the arrow appears well before the mouse reaches the very edge and
    // is easy to hit quickly; the center stays clear so it never blocks slide content.
    const band = Math.min(320, Math.max(160, rect.width * 0.25));
    const nearPrev = (clientX - rect.left) <= band;
    const nearNext = (rect.right - clientX) <= band;
    syncEdgeNavButton(edgePrevBtn, nearPrev, current > 0);
    syncEdgeNavButton(edgeNextBtn, nearNext, current < slides.length - 1);
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

  // A click on EMPTY slide space (the stage margins, the gaps between blocks, a layout wrapper's
  // padding) has no content of its own, so it advances the deck - the natural "click to go forward"
  // a presenter expects. A click on slide TEXT (a heading, paragraph, list item, table cell, or any
  // inline run) never advances, because the reader may be selecting it to comment; the same holds
  // for interactive/effect targets (links, buttons, form controls, ARIA widgets, focusable custom
  // controls, draggable board parts, comment anchors, deck chrome, or anything the author marks
  // [data-cmh-no-advance]), which keep their own click. This one rule applies in BOTH present mode
  // and the open review panel, so a reviewer can still page through by clicking empty space.
  const _CLICK_ADVANCE_SKIP = "a[href], area[href], button, input, textarea, select, option,"
    + " label, summary, details, audio, video, iframe, embed, object, svg, canvas,"
    + " [role='button'], [role='link'], [role='checkbox'], [role='radio'], [role='switch'],"
    + " [role='tab'], [role='menuitem'], [role='menuitemradio'], [role='menuitemcheckbox'],"
    + " [role='slider'], [role='spinbutton'], [role='textbox'], [role='combobox'], [role='option'],"
    + " [data-cm-part], [data-cids], mark.cm-hl, [contenteditable], [onclick], [tabindex]:not([tabindex='-1']),"
    + " [data-cmh-no-advance], .cm-skip";
  // A click ADVANCES only when it lands on empty slide space. Whether a click is on "text" is
  // decided by the POINT it lands on, not by element ancestry: hit-test the client rects of the
  // slide's text nodes against the pointer coordinates. This is robust where an ancestry walk is
  // not - a wrapper (or the `.slide` itself) that carries loose text no longer taints a click on
  // genuine empty space, and clicking the empty tail of a paragraph's last line still advances.
  function _pointOnText(slide, x, y) {
    if (!slide) return false;
    const walker = document.createTreeWalker(slide, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        return (n.nodeValue && n.nodeValue.trim()) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    const range = document.createRange();
    let node;
    while ((node = walker.nextNode())) {
      range.selectNodeContents(node);
      const rects = range.getClientRects();
      for (let i = 0; i < rects.length; i++) {
        const r = rects[i];
        if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return true;
      }
    }
    return false;
  }
  // The advance decision must reflect the state when the click GESTURE began, not when the click
  // event fires: the browser collapses a text selection and other document click listeners hide
  // the deck comment menu on `mousedown`, so a `click`-time check would see them already gone and
  // wrongly advance when the user was only dismissing a selection or that menu. Snapshot the
  // suppressing state at mousedown (capture phase, before those listeners run) and consult it.
  let _advanceSuppressed = false;
  function _liveSelection() {
    const sel = window.getSelection();
    return !!(sel && !sel.isCollapsed && String(sel).trim());
  }
  function _commentMenuOpen() {
    const menuEl = document.getElementById("contextMenu");
    return !!(menuEl && !menuEl.hidden);
  }
  // A visible hover bubble (raised by hovering a saved highlight) is transient chrome: an empty
  // click that dismisses it must not also advance the deck, like the context menu and popover.
  function _hlBubbleOpen() {
    const b = document.getElementById("hlBubble");
    return !!(b && !b.hidden);
  }
  // A point suppresses advance when it is off any slide, on an interactive/effect target, or on
  // rendered text. `el` is the element under the point (from elementFromPoint at click time, which
  // sees the true release target even when a press-on-empty / release-on-control gesture retargets
  // the `click` event to the common .slide ancestor).
  function _pointSuppresses(el, x, y) {
    if (!el || !el.closest) return true;
    const slide = el.closest(".slide");
    if (!slide || !stage.contains(slide)) return true;
    if (el.closest(_CLICK_ADVANCE_SKIP)) return true;
    return _pointOnText(slide, x, y);
  }
  function installClickAdvance() {
    // `pointerdown` (not `mousedown`) fires at the very start of a touch, before the browser
    // collapses a text selection during the touch sequence, so the snapshot sees the real state.
    const downEvt = window.PointerEvent ? "pointerdown" : "mousedown";
    document.addEventListener(downEvt, (e) => {
      _advanceSuppressed = hasBlockingDeckChrome() || _commentMenuOpen() || _hlBubbleOpen()
        || _liveSelection() || _pointSuppresses(e.target, e.clientX, e.clientY);
    }, true);
    document.addEventListener("click", (e) => {
      const suppressed = _advanceSuppressed;
      _advanceSuppressed = false;
      // Only a real, plain, unmodified primary click advances; a synthetic/programmatic click, a
      // modified click, or the macOS Ctrl-click contextmenu gesture is never a "next slide" intent.
      if (!e.isTrusted || e.defaultPrevented || e.button
        || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
      if (suppressed) return;
      if (hasBlockingDeckChrome() || _commentMenuOpen() || _hlBubbleOpen() || _liveSelection()) return;
      const x = e.clientX, y = e.clientY;
      const el = (typeof document.elementFromPoint === "function"
        ? document.elementFromPoint(x, y) : null) || e.target;
      if (_pointSuppresses(el, x, y)) return;
      if (show(current + 1)) focusStage();
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
    const target = cards[Math.max(0, Math.min(cards.length - 1, index))];
    if (target && !target.hidden) { target.focus(); return; }
    const visible = cards.filter((c) => !c.hidden);
    if (visible.length) visible[0].focus();
  }

  // Filter the overview cards by a title substring (used by the search box). Non-matching
  // cards are hidden so keyboard navigation and the visible count follow the filter.
  function filterOverview(query) {
    const needle = String(query || "").trim().toLowerCase();
    let visible = 0;
    overviewCards().forEach((card, i) => {
      const hit = !needle || (slideTitles[i] || "").toLowerCase().indexOf(needle) >= 0;
      card.hidden = !hit;
      if (hit) visible++;
    });
    if (overviewCount) {
      overviewCount.textContent = needle
        ? visible + " of " + slides.length
        : slides.length + (slides.length === 1 ? " slide" : " slides");
    }
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
    count.setAttribute("aria-live", "polite");
    count.setAttribute("aria-atomic", "true");
    count.textContent = slides.length + (slides.length === 1 ? " slide" : " slides");
    overviewCount = count;
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

    // A search box at the top narrows the slide list by title as the presenter types.
    const searchWrap = document.createElement("div");
    searchWrap.className = "cmh-deck-overview-searchwrap";
    overviewSearch = document.createElement("input");
    overviewSearch.type = "search";
    overviewSearch.className = "cmh-deck-overview-search cm-skip";
    overviewSearch.placeholder = "Filter slides...";
    overviewSearch.setAttribute("aria-label", "Filter slides by title");
    overviewSearch.addEventListener("input", () => filterOverview(overviewSearch.value));
    overviewSearch.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        if (overviewSearch.value) { overviewSearch.value = ""; filterOverview(""); }
        else closeOverview();
        return;
      }
      if (e.key === "ArrowDown" || e.key === "Enter") {
        const visible = overviewCards().filter((c) => !c.hidden);
        if (visible.length) { e.preventDefault(); visible[0].focus(); }
      }
    });
    searchWrap.appendChild(overviewSearch);

    overviewGrid = document.createElement("div");
    overviewGrid.className = "cmh-deck-overview-grid";
    overviewGrid.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeOverview();
        return;
      }
      const cards = overviewCards().filter((c) => !c.hidden);
      if (!cards.length) return;
      const at = cards.indexOf(document.activeElement);
      if (e.key === "Tab") {
        e.preventDefault();
        const base = at < 0 ? 0 : at;
        // Shift+Tab off the top of the list returns to the filter box, so the search is
        // reachable by keyboard without breaking the arrow-key roving over the cards.
        if (e.shiftKey && base === 0 && overviewSearch) { overviewSearch.focus(); return; }
        const next = (base + (e.shiftKey ? -1 : 1) + cards.length) % cards.length;
        cards[next].focus();
        return;
      }
      let next = at;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") next = at < 0 ? 0 : at + 1;
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = at < 0 ? 0 : at - 1;
      else if (e.key === "Home") next = 0;
      else if (e.key === "End") next = cards.length - 1;
      else return;
      e.preventDefault();
      cards[Math.max(0, Math.min(cards.length - 1, next))].focus();
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

      // A readable numbered title row (thumbnails of a 1920x1080 stage scaled to a chip were
      // unreadable and rendered canvas/hero content as black blocks); the title is the reliable
      // slide identifier for navigation.
      const num = document.createElement("span");
      num.className = "cmh-deck-overview-card-num";
      num.textContent = (i + 1);
      const label = document.createElement("span");
      label.className = "cmh-deck-overview-card-label";
      label.textContent = titleText;
      card.appendChild(num);
      card.appendChild(label);
      card.addEventListener("click", () => {
        if (show(i)) closeOverview();
      });
      overviewGrid.appendChild(card);
    });

    overview.appendChild(head);
    overview.appendChild(searchWrap);
    overview.appendChild(overviewGrid);
    document.body.appendChild(overview);
    CMH_INJECTED_CHROME.add(overview);
    syncOverview();
  }

  function openOverview() {
    makeOverview();
    overview.hidden = false;
    // Reset any prior filter so reopening lists every slide.
    if (overviewSearch) overviewSearch.value = "";
    filterOverview("");
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
    deckMode: () => deckMode,
    setDeckMode: (m) => setDeckMode(m),
    refreshMode: () => updateModeMenu(),
  };

  show(current);
  fitStage();
  makeEdgeNav();
  installClickAdvance();
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(fitStage).observe(viewport || document.documentElement);
  } else {
    window.addEventListener("resize", fitStage);
  }
  // The comment-model default (present, panel closed) is applied by applyDeckMode() below,
  // which reads the persisted per-deck selection and sets the deck body classes.

  function isEditableTarget(t) {
    if (!t) return false;
    if (t.isContentEditable) return true;
    const tag = t.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
    return !!(t.closest && t.closest(".cm-skip"));
  }
  document.addEventListener("keydown", (e) => {
    if (!e.defaultPrevented && overview && !overview.hidden) {
      if (e.key === "Escape") {
        e.preventDefault();
        closeOverview();
        return;
      }
      if (e.key && e.key.toLowerCase() === "o"
        && !e.altKey && !e.ctrlKey && !e.metaKey
        && !(e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.isContentEditable))) {
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

  // ---- 3-state comment model (persisted per-deck) ---------------------------------
  const DECK_MODE_KEY = COMMENT_KEY + "::deckMode";
  function commentCount() { return (typeof comments !== "undefined" && comments) ? comments.length : 0; }
  // Disabling comments is only offered when the deck carries no comments, so a reviewer can never
  // strand existing feedback behind a present-only lock.
  function canDisableComments() { return commentCount() === 0; }
  function normalizeDeckMode(v) {
    if (v !== "open" && v !== "off" && v !== "closed") return "closed";
    if (v === "off" && !canDisableComments()) return "closed";
    return v;
  }
  function saveDeckMode() { try { localStorage.setItem(DECK_MODE_KEY, deckMode); } catch (e) { /* private mode */ } }

  function applyDeckMode(persist) {
    const paneOpen = deckMode === "open";
    const off = deckMode === "off";
    commentMode = paneOpen;   // gates keyboard nav, edge-nav, and stage focus below
    root.classList.toggle("cmh-deck-comment-mode", paneOpen);
    document.body.classList.toggle("cmh-deck-present", !paneOpen);
    document.body.classList.toggle("cmh-deck-comments-off", off);
    try { if (paneOpen) openSidebar(); else closeSidebar(); } catch (e) { /* sidebar helpers optional */ }
    if (persist !== false) saveDeckMode();
    updateModeMenu();
    hideEdgeNav();
    // Opening the panel narrows the stage (the sidebar takes width); refit after layout settles.
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(() => { fitStage(); if (!paneOpen) focusStage(); });
    } else {
      fitStage();
      if (!paneOpen) focusStage();
    }
  }
  function setDeckMode(mode) {
    deckMode = normalizeDeckMode(mode);
    applyDeckMode(true);
  }

  function updateModeMenu() {
    const paneOpen = deckMode === "open";
    const off = deckMode === "off";
    if (modeToggle) {
      modeToggle.classList.toggle("cmh-deck-comments-off", off);
      modeToggle.classList.toggle("cmh-deck-pane-open", paneOpen);
      modeToggle.setAttribute("aria-label", off
        ? "Comment options (commenting disabled)"
        : (paneOpen ? "Comment options (review panel open)" : "Comment options"));
    }
    modeRadioItems.forEach((item) => {
      const m = item.getAttribute("data-deck-mode");
      const on = m === deckMode;
      item.setAttribute("aria-checked", on ? "true" : "false");
      item.classList.toggle("cmh-deck-mode-item-current", on);
      // The three states are mutually exclusive (exactly one selected). "Comments off" is only
      // selectable while no comment exists, so existing feedback is never stranded behind a
      // present-only lock.
      const allow = m !== "off" ? true : (off || canDisableComments());
      item.disabled = !allow;
      item.setAttribute("aria-disabled", allow ? "false" : "true");
      item.title = (m === "off" && !allow)
        ? "Delete every comment before you can disable commenting"
        : "";
    });
  }

  function openModeMenu() {
    if (!modeMenu) return;
    updateModeMenu();
    modeMenu.hidden = false;
    modeToggle.setAttribute("aria-expanded", "true");
    document.addEventListener("click", onModeMenuOutside, true);
    document.addEventListener("keydown", onModeMenuKey, true);
    const first = modeMenu.querySelector('.cmh-deck-mode-radio[aria-checked="true"]:not([disabled])')
      || modeMenu.querySelector(".cmh-deck-mode-item:not([disabled])");
    if (first) setTimeout(() => { try { first.focus(); } catch (e) {} }, 0);
  }
  function closeModeMenu(focusToggle) {
    if (!modeMenu || modeMenu.hidden) return;
    modeMenu.hidden = true;
    modeToggle.setAttribute("aria-expanded", "false");
    document.removeEventListener("click", onModeMenuOutside, true);
    document.removeEventListener("keydown", onModeMenuKey, true);
    if (focusToggle) { try { modeToggle.focus(); } catch (e) {} }
  }
  function toggleModeMenu() { if (modeMenu.hidden) openModeMenu(); else closeModeMenu(true); }
  function onModeMenuOutside(e) {
    if (modeMenu.contains(e.target) || modeToggle.contains(e.target)) return;
    closeModeMenu(false);
  }
  function modeMenuItems() {
    return Array.prototype.slice.call(
      modeMenu.querySelectorAll(".cmh-deck-mode-item:not([disabled])"));
  }
  function focusModeItem(index) {
    const items = modeMenuItems();
    if (!items.length) return;
    const i = (index + items.length) % items.length;
    try { items[i].focus(); } catch (e) {}
  }
  function onModeMenuKey(e) {
    if (e.key === "Escape") { e.preventDefault(); closeModeMenu(true); return; }
    // Tab moves focus out of the menu and closes it (standard menu behaviour); let the browser
    // do the default focus move so the menu does not trap the keyboard.
    if (e.key === "Tab") { closeModeMenu(false); return; }
    const items = modeMenuItems();
    if (!items.length) return;
    const cur = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); focusModeItem(cur < 0 ? 0 : cur + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); focusModeItem(cur < 0 ? items.length - 1 : cur - 1); }
    else if (e.key === "Home") { e.preventDefault(); focusModeItem(0); }
    else if (e.key === "End") { e.preventDefault(); focusModeItem(items.length - 1); }
  }

  const modeCtl = document.createElement("div");
  modeCtl.className = "cm-skip cmh-deck-mode-ctl";
  const toggle = document.createElement("button");
  modeToggle = toggle;
  toggle.className = "cm-skip cmh-deck-mode-toggle";
  toggle.type = "button";
  toggle.innerHTML = CMH_ICON_SVG + '<span class="cmh-deck-mode-caret" aria-hidden="true"></span>';
  const toggleIcon = toggle.querySelector("svg");
  if (toggleIcon) {
    toggleIcon.setAttribute("aria-hidden", "true");
    toggleIcon.setAttribute("focusable", "false");
    toggleIcon.removeAttribute("role");
    toggleIcon.removeAttribute("aria-label");
    toggleIcon.removeAttribute("data-cmh-tip");
  }
  toggle.title = "Comment options";
  toggle.setAttribute("aria-label", "Comment options");
  toggle.setAttribute("aria-haspopup", "menu");
  toggle.setAttribute("aria-expanded", "false");
  toggle.addEventListener("click", (e) => { e.preventDefault(); toggleModeMenu(); });

  modeMenu = document.createElement("div");
  modeMenu.className = "cm-skip cmh-deck-mode-menu";
  modeMenu.id = "cmhDeckModeMenu";
  modeMenu.setAttribute("role", "menu");
  modeMenu.setAttribute("aria-label", "Comment options");
  modeMenu.hidden = true;
  toggle.setAttribute("aria-controls", modeMenu.id);

  const DECK_MODE_OPTIONS = [
    { mode: "off", label: "Comments off", cls: "cmh-deck-mode-off-item" },
    { mode: "closed", label: "Comments on, panel closed", cls: "cmh-deck-mode-closed-item" },
    { mode: "open", label: "Comments on, panel open", cls: "cmh-deck-mode-open-item" },
  ];
  // A radio group: the three deck states are mutually exclusive, so exactly one is selected at a
  // time (menuitemradio). Selecting an option applies it; "Comments off" is disabled while any
  // comment exists (see updateModeMenu).
  modeRadioItems = DECK_MODE_OPTIONS.map((opt) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "cmh-deck-mode-item cmh-deck-mode-radio " + opt.cls;
    item.setAttribute("role", "menuitemradio");
    item.setAttribute("data-deck-mode", opt.mode);
    item.textContent = opt.label;
    item.addEventListener("click", () => {
      if (item.disabled) return;
      setDeckMode(opt.mode);
      closeModeMenu(false);
      // Keep keyboard focus sensible after the menu closes: opening the review panel hides the
      // trigger, so move focus into the panel; otherwise return focus to the trigger.
      if (opt.mode === "open") {
        const panelBtn = document.getElementById("btnCloseSidebar");
        if (panelBtn && panelBtn.focus) { try { panelBtn.focus(); } catch (e) {} }
      } else if (modeToggle && modeToggle.focus) {
        try { modeToggle.focus(); } catch (e) {}
      }
    });
    modeMenu.appendChild(item);
    return item;
  });

  const modeSep = document.createElement("span");
  modeSep.className = "cmh-deck-mode-sep";
  modeSep.setAttribute("role", "separator");

  const siteItem = document.createElement("a");
  siteItem.className = "cmh-deck-mode-item cmh-deck-mode-site cm-brand-link";
  siteItem.setAttribute("role", "menuitem");
  siteItem.href = CMH_SITE_URL;
  siteItem.target = "_blank";
  siteItem.rel = "noopener noreferrer";
  siteItem.textContent = "Commentable HTML site";
  siteItem.addEventListener("click", () => closeModeMenu(false));

  modeMenu.appendChild(modeSep);
  modeMenu.appendChild(siteItem);
  modeCtl.appendChild(toggle);
  modeCtl.appendChild(modeMenu);
  document.body.prepend(modeCtl);

  // Keep deckMode in step with any OTHER code path that opens or closes the panel (adding a
  // comment opens the sidebar; the sidebar header Close button closes it). applyDeckMode leaves
  // body.sidebar-open consistent with deckMode, so this observer never fights its own writes.
  if (typeof MutationObserver === "function") {
    new MutationObserver(() => {
      const open = document.body.classList.contains("sidebar-open");
      if (open && deckMode !== "open") setDeckMode("open");
      else if (!open && deckMode === "open") setDeckMode("closed");
    }).observe(document.body, { attributes: true, attributeFilter: ["class"] });
  }

  // Apply the persisted selection (default "closed": comments on, panel shut).
  try { deckMode = normalizeDeckMode(localStorage.getItem(DECK_MODE_KEY)); } catch (e) { deckMode = "closed"; }
  applyDeckMode(false);

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
  setupSectionReview();
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
// A deck manages its own panel state from the persisted comment-model selection (applyDeckMode);
// the document-flow auto-open below must not override it (that would force every deck with a
// comment to open the panel, ignoring the reviewer's "panel closed" choice).
if (!IS_DECK) {
  if (comments.length || (typeof checklistChanges === "function" && checklistChanges().length) || (typeof notesChanges === "function" && notesChanges().length)) openSidebar();
  else closeSidebar();
}
// Signals the nonportable-mode bootstrap that the external runtime initialized, so
// the missing-companion-assets banner stays hidden.
window.__commentableHtmlReady = true;
window.__commentableHtmlVersion = CMH_VERSION;
})();
