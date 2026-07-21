/* ---------- Table-of-contents side menu (wide screens) ---------- */
// When the document carries a table of contents (an author `.cm-toc`, else h2/h3
// ids), render a fixed, collapsible section menu on the left with scroll-spy and a
// back-to-top button. It is a runtime-only aid (never in the base HTML, so plain /
// standalone exports and the startup snapshot never include it) and is cm-skip so it
// is not itself commentable. CSS gates it to wide viewports.
function _cmSlugify(text) {
  const s = String(text).toLowerCase().trim()
    .replace(/[^\w\s-]/g, "").replace(/[\s_]+/g, "-").replace(/-+/g, "-").replace(/^-+|-+$/g, "");
  return s || "section";
}
// Every heading inside #commentRoot gets a stable id and becomes a deep-link: a plain
// click (no text selection, not on a link or highlight) updates the URL to #<id> and
// scrolls to it, so a reader can copy a link straight to any section.
function setupHeadingAnchors() {
  const seen = {};
  const headingAddBtn = document.getElementById("headingAddBtn");
  let headingHoverEl = null, headingHideTimer = null;
  function positionHeadingAdd(h) {
    const r = h.getBoundingClientRect();
    const bw = headingAddBtn.offsetWidth || 110, bh = headingAddBtn.offsetHeight || 26;
    // Place the button just after the heading TEXT (not at the far right of the full
    // block): measure where the rendered text actually ends via a contents range, then
    // sit a small gap to its right, vertically centered on that line.
    let anchorRight = r.left, anchorTop = r.top, anchorH = r.height;
    try {
      const range = document.createRange();
      range.selectNodeContents(h);
      const rects = [...range.getClientRects()].filter((x) => x.width > 0.5 && x.height > 0.5);
      if (rects.length) {
        const end = rects.reduce((a, b) => (b.right > a.right ? b : a));
        anchorRight = end.right; anchorTop = end.top; anchorH = end.height;
      }
    } catch (e) { /* fall back to the block box */ }
    const gap = 10;
    let left = anchorRight + gap;
    let top = anchorTop + (anchorH - bh) / 2;
    // If the label would run off the right edge, tuck it back against the block right.
    if (left + bw + 8 > window.innerWidth) left = r.right - bw - 6;
    headingAddBtn.style.left = Math.max(8, Math.min(left, window.innerWidth - bw - 8)) + "px";
    headingAddBtn.style.top = Math.max(8, Math.min(top, window.innerHeight - bh - 8)) + "px";
    // Return anchor visibility (not button fit) so repositionActiveAdd only hides the
    // button when the heading scrolls out of view, not when it sits near an edge.
    return _rectInViewport(r);
  }
  function showHeadingAdd(h) {
    if (!headingAddBtn) return;
    headingHoverEl = h;
    if (headingHideTimer) { clearTimeout(headingHideTimer); headingHideTimer = null; }
    headingAddBtn.hidden = false;
    positionHeadingAdd(h);
    setActiveAdd({ el: h, btn: headingAddBtn, position: () => positionHeadingAdd(h), clear: () => {} });
  }
  function focusNextAfterHeading(h) {
    const sel = 'a[href], area[href], button, input, textarea, select, summary, iframe, object, embed, video[controls], audio[controls], [contenteditable]:not([contenteditable="false"]), [tabindex]';
    const all = [...document.querySelectorAll(sel)].filter(function (el) {
      return el !== headingAddBtn && !el.hidden && !el.closest("[hidden], [inert]") && !el.matches(":disabled") && el.tabIndex >= 0 && el.getClientRects().length;
    });
    const idx = all.indexOf(h);
    const after = idx >= 0 ? all.slice(idx + 1) : [];
    const next = after.find(function (el) {
      if (el.closest(".cm-skip") && !h.contains(el)) return false;
      el.focus();
      return document.activeElement === el || el.contains(document.activeElement);
    });
    if (!next) return false;
    return true;
  }
  function scheduleHideHeadingAdd() {
    if (headingHideTimer) clearTimeout(headingHideTimer);
    headingHideTimer = setTimeout(function () {
      if (headingAddBtn && !headingAddBtn.matches(":hover") && document.activeElement !== headingAddBtn) { headingAddBtn.hidden = true; headingHoverEl = null; clearActiveAdd(headingAddBtn); }
    }, 220);
  }
  // Comment on a whole heading by selecting its text and opening the text composer, so
  // headings stay commentable even though a plain click deep-links them.
  function commentOnHeading(h) {
    const first = firstTextNodeIn(h), last = lastTextNodeIn(h);
    if (!first || !last) return;
    const r = document.createRange();
    r.setStart(first, 0); r.setEnd(last, last.nodeValue.length);
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
    const s = offsetWithin(first, 0), e = offsetWithin(last, last.nodeValue.length);
    if (s >= 0 && e > s) {
      const existing = comments.find(function (c) { return !c.anchorType && c.start === s && c.end === e; });
      if (existing) { openComposerForEdit(existing); return; }
    }
    pendingDiffSel = null;
    pendingRange = r.cloneRange();
    pendingQuote = sel.toString();
    openComposer(pendingRange, pendingQuote);
  }
  if (headingAddBtn && !headingAddBtn._cmWired) {
    headingAddBtn._cmWired = true;
    headingAddBtn.addEventListener("mouseenter", function () { if (headingHideTimer) { clearTimeout(headingHideTimer); headingHideTimer = null; } });
    headingAddBtn.addEventListener("mouseleave", scheduleHideHeadingAdd);
    headingAddBtn.addEventListener("focus", function () { if (headingHideTimer) { clearTimeout(headingHideTimer); headingHideTimer = null; } });
    headingAddBtn.addEventListener("blur", scheduleHideHeadingAdd);
    headingAddBtn.addEventListener("keydown", function (e) {
      if (e.key !== "Tab" || !headingHoverEl) return;
      if (e.shiftKey) {
        e.preventDefault();
        headingHoverEl.focus();
      } else {
        e.preventDefault();
        if (!focusNextAfterHeading(headingHoverEl)) {
          headingAddBtn.hidden = true;
          clearActiveAdd(headingAddBtn);
          headingAddBtn.blur();
        }
      }
    });
    headingAddBtn.addEventListener("click", function () {
      const h = headingHoverEl;
      headingAddBtn.hidden = true;
      if (h) commentOnHeading(h);
    });
  }
  root.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach(function (h) {
    if (h.closest(".cm-skip")) return;
    if (!h.id) {
      const base = _cmSlugify(h.textContent || "section");
      let id = base, n = 2;
      while (document.getElementById(id) || seen[id]) { id = base + "-" + n; n++; }
      h.id = id;
    }
    seen[h.id] = true;
    h.classList.add("cm-anchored");
    if (!h.title) h.title = "Click or press Enter to link to this section (hover or focus to comment on it)";
    // Keyboard parity: the heading is a deep-link affordance, so make it focusable and
    // activate the link on Enter/Space just like a click (a visible :focus-visible outline
    // is defined in CSS). Focusing it also reveals the add-comment button, which is itself
    // a real focusable button reachable by Tab.
    if (!h.hasAttribute("tabindex")) h.setAttribute("tabindex", "0");
    function deepLink() {
      if (window.history && history.pushState) history.pushState(null, "", "#" + h.id);
      else location.hash = h.id;
      h.scrollIntoView({ behavior: cmScrollBehavior(), block: "start" });
    }
    h.addEventListener("click", function (e) {
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed) return;              // selecting text to comment
      if (e.target.closest("a, mark.cm-hl")) return;    // let links / highlight-clicks win
      deepLink();
    });
    h.addEventListener("keydown", function (e) {
      if (e.key === "Tab" && !e.shiftKey && headingAddBtn && !headingAddBtn.hidden && headingAddBtn.getClientRects().length && document.activeElement === h) {
        e.preventDefault();
        showHeadingAdd(h);
        headingAddBtn.focus();
        return;
      }
      if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
      if (e.target !== h) return;                       // let a focused child (link) act
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed) return;
      e.preventDefault();
      deepLink();
    });
    h.addEventListener("mouseenter", function () { showHeadingAdd(h); });
    h.addEventListener("mouseleave", scheduleHideHeadingAdd);
    h.addEventListener("focus", function () { showHeadingAdd(h); });
    h.addEventListener("blur", scheduleHideHeadingAdd);
  });
}
// Every authored <section> with a heading becomes collapsible: a caret on the heading
// toggles it, and the side TOC gets Expand All / Collapse All. Collapsing sets a class
// (display:none via CSS) - it never removes or reorders nodes, so comment text offsets
// stay valid. The caret is a text-free cm-skip element (pseudo-element glyph) so it does
// not pollute heading text or offsets.
const _cmSectionToggles = [];
// Parallel to _cmSectionToggles but keyed to the owning heading + section, so the review
// filter (84-section-review.js) can expand/collapse a specific section by its review state.
const _cmSectionEntries = [];
// Live side-TOC items/links, captured by setupSideToc so the review layer can paint per-entry
// state dots and drive the review filter.
let _cmTocItems = [];
let _cmTocLinks = [];
let _cmReviewFilterBtns = null;
let _cmReviewFilterEl = null;
function setupCollapsibleSections() {
  _cmSectionToggles.length = 0;
  _cmSectionEntries.length = 0;
  root.querySelectorAll("section").forEach(function (sec) {
    if (sec.closest(".cm-skip")) return;
    const heading = sec.querySelector(":scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > h5, :scope > h6");
    if (!heading || heading.closest(".cm-skip")) return;
    if (heading.querySelector(".cmh-sec-caret")) return;
    heading.classList.add("cmh-section-heading");
    const caret = document.createElement("button");
    caret.type = "button";
    caret.className = "cmh-sec-caret cm-skip";
    caret.setAttribute("aria-expanded", "true");
    caret.setAttribute("aria-label", "Collapse section");
    caret.title = "Collapse section";
    heading.insertBefore(caret, heading.firstChild);
    function setState(collapsed) {
      sec.classList.toggle("cmh-section-collapsed", collapsed);
      caret.setAttribute("aria-expanded", String(!collapsed));
      caret.title = collapsed ? "Expand section" : "Collapse section";
      caret.setAttribute("aria-label", collapsed ? "Expand section" : "Collapse section");
    }
    caret.addEventListener("click", function (e) {
      e.stopPropagation();
      // A manual per-section toggle invalidates any active review filter, so reset it to All -
      // otherwise the next refreshReviewUI would re-collapse the section the user just expanded.
      if (typeof _resetReviewFilterUI === "function") _resetReviewFilterUI();
      setState(!sec.classList.contains("cmh-section-collapsed"));
    });
    // Clicking a collapsed section's title (anywhere but the caret) expands it too - a
    // collapsed section shows only its heading, so a plain click is the natural gesture.
    // Ignore clicks that are part of a text selection so commenting on an expanded heading
    // is unaffected.
    heading.addEventListener("click", function (e) {
      if (e.target.closest(".cmh-sec-caret")) return;
      if (!sec.classList.contains("cmh-section-collapsed")) return;
      const sel = window.getSelection();
      if (sel && sel.toString().trim()) return;
      setState(false);
    });
    _cmSectionToggles.push(setState);
    _cmSectionEntries.push({ heading: heading, section: sec, setState: setState });
  });
}
function setupSideToc() {
  const root = document.getElementById("commentRoot") || document.body;
  const items = [];
  const tocLinks = root.querySelectorAll(".cm-toc a[href^='#']");
  if (tocLinks.length) {
    tocLinks.forEach(function (a) {
      let id = (a.getAttribute("href") || "").slice(1);
      try { id = decodeURIComponent(id); } catch (e) { /* malformed %-encoding: keep the raw id */ }
      const el = id && document.getElementById(id);
      if (el) items.push({ id: id, label: (a.textContent || "").trim(), el: el, level: 1 });
    });
  } else {
    root.querySelectorAll("h2[id], h3[id]").forEach(function (h) {
      items.push({ id: h.id, label: (h.textContent || "").trim(), el: h, level: h.tagName === "H3" ? 2 : 1 });
    });
  }
  if (items.length < 2) return; // not worth a side menu
  const nav = document.createElement("nav");
  nav.className = "cm-side-toc cm-skip";
  nav.id = "cmSideToc";
  nav.setAttribute("aria-label", "Section navigation");
  const head = document.createElement("div");
  head.className = "cm-side-toc-head";
  const title = document.createElement("span");
  title.className = "cm-side-toc-title";
  title.textContent = "Navigation";
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "cm-side-toc-toggle";
  toggle.title = "Collapse the section menu";
  toggle.setAttribute("aria-expanded", "true");
  toggle.setAttribute("aria-label", "Collapse section menu");
  toggle.innerHTML = "&laquo;";
  head.append(title, toggle);
  // A11: search-as-filter over the sections (not just the list); runtime chrome, cm-skip.
  const search = document.createElement("input");
  search.type = "search";
  search.className = "cm-side-toc-search cm-skip";
  search.setAttribute("placeholder", "Filter sections...");
  search.setAttribute("aria-label", "Filter sections");
  const list = document.createElement("ul");
  list.className = "cm-side-toc-list";
  const links = [];
  // If the author already numbered their headings (e.g. "1. Summary", "3.1 Goals"), do NOT
  // add a second computed number - show the label as-is so there is a single number.
  const _numRe = /^(?:\d+(?:\.\d+)*[.)]|\d+\.\d+(?:\.\d+)*)\s+/;
  const authorNumbered = items.some(function (it) { return _numRe.test(it.label); });
  let n1 = 0, n2 = 0;
  items.forEach(function (it) {
    const li = document.createElement("li");
    if (it.level === 2) li.className = "is-sub";
    const a = document.createElement("a");
    a.href = "#" + it.id;
    if (authorNumbered) {
      a.textContent = it.label;
    } else {
      // Section numbers: top-level items count 1, 2, 3...; sub-items count 1.1, 1.2...
      let num;
      if (it.level === 2) { n2++; num = (n1 || 1) + "." + n2; }
      else { n1++; n2 = 0; num = String(n1); }
      a.innerHTML = '<span class="cm-toc-num">' + num + '</span> ' + escapeHtml(it.label);
    }
    li.appendChild(a);
    list.appendChild(li);
    links.push(a);
  });
  _cmTocItems = items;
  _cmTocLinks = links;
  // A segmented review filter: All / Reviewed / Unreviewed / Commented / Changed. Selecting a
  // state collapses every section that does not contain a heading in that state and expands the
  // rest; All re-expands everything. Runtime chrome, cm-skip.
  const reviewFilter = document.createElement("div");
  reviewFilter.className = "cm-side-toc-review cm-skip";
  reviewFilter.setAttribute("role", "group");
  reviewFilter.setAttribute("aria-label", "Filter sections by review state");
  // Dormant by default: the filter is revealed by updateTocReviewMarks() once the review UI is active
  // (a section is marked reviewed or the first comment is added), so a first-time reader never sees it.
  reviewFilter.hidden = true;
  _cmReviewFilterEl = reviewFilter;
  _cmReviewFilterBtns = {};
  [["all", "All"], ["reviewed", "Reviewed"], ["unreviewed", "Unreviewed"], ["commented", "Commented"], ["changed", "Changed"]]
    .forEach(function (pair) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "cm-side-toc-review-btn cmh-review-filter-" + pair[0];
      b.dataset.cmhReviewFilter = pair[0];
      b.dataset.cmhBaseLabel = pair[1];
      const labelEl = document.createElement("span");
      labelEl.className = "cm-side-toc-review-btn-label";
      labelEl.textContent = pair[1];
      // A live per-state count (filled by updateReviewFilterCounts). Decorative: the accessible
      // name lives on the button's aria-label so the count is not announced as a second reading.
      const countEl = document.createElement("span");
      countEl.className = "cm-side-toc-review-btn-count";
      countEl.setAttribute("aria-hidden", "true");
      b.append(labelEl, countEl);
      b.title = "Show " + pair[1].toLowerCase() + " sections";
      b.setAttribute("aria-pressed", pair[0] === "all" ? "true" : "false");
      b.addEventListener("click", function () { applyReviewFilter(pair[0]); });
      _cmReviewFilterBtns[pair[0]] = b;
      reviewFilter.appendChild(b);
    });
  // A11: filter the visible sections (and their menu entries) by heading + body text.
  function _cmTocSectionOf(it) { return (it.el && it.el.closest) ? it.el.closest("section") : null; }
  // Cache each item's lowercase haystack (label + its section/heading text) once, so typing does
  // not re-read textContent of every section on each keystroke.
  items.forEach(function (it) {
    const sec = _cmTocSectionOf(it);
    it._cmHay = ((it.label || "") + " " + (sec ? sec.textContent : (it.el.textContent || ""))).toLowerCase();
  });
  function applyTocFilter(q) {
    const query = String(q || "").trim().toLowerCase();
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      const sec = _cmTocSectionOf(it);
      const match = !query || it._cmHay.indexOf(query) !== -1;
      it._cmFiltered = !match; // scroll-spy reads this so it skips hidden entries (sectioned or not)
      const li = links[i].closest("li");
      if (li) li.classList.toggle("cm-toc-li-hidden", !match);
      if (sec) sec.classList.toggle("cm-toc-filtered", !match);
    }
    if (typeof schedule === "function") schedule(); // re-run scroll-spy so aria-current follows the filter
  }
  function clearTocFilter() { if (search.value) search.value = ""; applyTocFilter(""); }
  search.addEventListener("input", function () { applyTocFilter(search.value); });
  search.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { e.preventDefault(); clearTocFilter(); search.blur(); }
  });
  // Reveal a filtered-out section when a deep link targets it, rather than scrolling to nothing.
  window.addEventListener("hashchange", function () {
    let id = (location.hash || "").slice(1);
    try { id = decodeURIComponent(id); } catch (e) { /* keep the raw id */ }
    const el = id && document.getElementById(id);
    const sec = el && el.closest && el.closest("section");
    if (sec && sec.classList.contains("cm-toc-filtered")) {
      // expandCollapsedAncestors (shared bundle scope) clears the filter AND expands collapsed
      // ancestors so a revealed section shows its body, not just its heading.
      if (typeof expandCollapsedAncestors === "function") expandCollapsedAncestors(el);
      else clearTocFilter();
      el.scrollIntoView({ block: "start" });
    }
  });
  // If the viewport narrows below the side-menu breakpoint the filter box is hidden, so drop any
  // active filter to avoid stranding sections hidden with no visible control to restore them.
  window.addEventListener("resize", function () {
    if (search.value && nav && getComputedStyle(nav).display === "none") clearTocFilter();
  });
  const scrollBtns = document.createElement("div");
  scrollBtns.className = "cm-side-toc-scroll";
  let expandGrp = null;
  if (_cmSectionToggles.length) {
    const expandAll = document.createElement("button");
    expandAll.type = "button";
    expandAll.className = "cm-side-toc-top";
    expandAll.title = "Expand all sections";
    expandAll.innerHTML = _cmIco("expand") + "<span>Expand All</span>";
    expandAll.addEventListener("click", function () { _resetReviewFilterUI(); _cmSectionToggles.forEach(function (t) { t(false); }); });
    const collapseAll = document.createElement("button");
    collapseAll.type = "button";
    collapseAll.className = "cm-side-toc-top";
    collapseAll.title = "Collapse all sections";
    collapseAll.innerHTML = _cmIco("collapse") + "<span>Collapse All</span>";
    collapseAll.addEventListener("click", function () { _resetReviewFilterUI(); _cmSectionToggles.forEach(function (t) { t(true); }); });
    expandGrp = document.createElement("div");
    expandGrp.className = "cm-side-toc-scroll";
    expandGrp.append(expandAll, collapseAll);
  }
  const top = document.createElement("button");
  top.type = "button";
  top.className = "cm-side-toc-top";
  top.title = "Scroll to the top of the document";
  top.innerHTML = _cmIco("top") + "<span>Scroll to Top</span>";
  const bottom = document.createElement("button");
  bottom.type = "button";
  bottom.className = "cm-side-toc-top cm-side-toc-bottom";
  bottom.title = "Scroll to the bottom of the document";
  bottom.innerHTML = _cmIco("bottom") + "<span>Scroll to Bottom</span>";
  scrollBtns.append(top, bottom);
  if (expandGrp) nav.append(head, search, reviewFilter, list, expandGrp, scrollBtns);
  else nav.append(head, search, reviewFilter, list, scrollBtns);
  document.body.appendChild(nav);
  document.body.classList.add("cm-side-toc-on");
  toggle.addEventListener("click", function () {
    const collapsed = nav.classList.toggle("is-collapsed");
    document.body.classList.toggle("cm-side-toc-collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    // Collapsed shows a "Navigation" label + >> expand chevron; open shows << collapse.
    toggle.innerHTML = collapsed ? "Navigation &raquo;" : "&laquo;";
    toggle.setAttribute("aria-label", collapsed ? "Expand section menu" : "Collapse section menu");
    toggle.title = collapsed ? "Expand the section menu" : "Collapse the section menu";
  });
  top.addEventListener("click", function () {
    window.scrollTo({ top: 0, behavior: cmScrollBehavior() });
  });
  bottom.addEventListener("click", function () {
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: cmScrollBehavior() });
  });
  function onScroll() {
    // Activate the visible section nearest above the threshold by GEOMETRY (greatest top still
    // <= 120), skipping any section hidden by the filter so aria-current never lands on it.
    let activeIdx = -1;
    let bestTop = -Infinity;
    let firstVisible = -1;
    for (let i = 0; i < items.length; i++) {
      if (items[i]._cmFiltered) continue; // never activate an entry the filter has hidden
      if (firstVisible === -1) firstVisible = i;
      const top = items[i].el.getBoundingClientRect().top;
      if (top <= 120 && top > bestTop) { bestTop = top; activeIdx = i; }
    }
    if (activeIdx === -1) activeIdx = firstVisible; // above the first visible section (or none visible)
    // At the page bottom a short trailing section never reaches the 120px threshold, so force the
    // LAST visible item active once the document is fully scrolled.
    const doc = document.documentElement;
    if (window.innerHeight + window.scrollY >= doc.scrollHeight - 2) {
      for (let i = items.length - 1; i >= 0; i--) {
        if (!items[i]._cmFiltered) { activeIdx = i; break; }
      }
    }
    for (let i = 0; i < links.length; i++) {
      const on = i === activeIdx;
      links[i].classList.toggle("is-active", on);
      // aria-current marks the reader's location for assistive tech, not just visually.
      if (on) links[i].setAttribute("aria-current", "location");
      else links[i].removeAttribute("aria-current");
    }
  }
  let raf = 0;
  function schedule() {
    if (raf) return;
    if (typeof requestAnimationFrame !== "function") { onScroll(); return; }
    raf = requestAnimationFrame(function () { raf = 0; onScroll(); });
  }
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  onScroll();
}

// A small bottom-right bubble showing how far through the document the reader has
// scrolled. cm-skip and runtime-created, so it never appears in a Plain export.
function setupScrollProgress() {
  if (document.getElementById("cmScrollProgress")) return;
  const el = document.createElement("div");
  el.className = "cm-scroll-progress cm-skip";
  el.id = "cmScrollProgress";
  el.setAttribute("aria-hidden", "true");
  el.title = "Scroll position in the document";
  document.body.appendChild(el);
  function update() {
    const doc = document.documentElement;
    const max = doc.scrollHeight - window.innerHeight;
    const pct = max > 4 ? Math.round((window.scrollY / max) * 100) : 100;
    el.textContent = Math.max(0, Math.min(100, pct)) + "%";
  }
  let raf = 0;
  function schedule() {
    if (raf) return;
    if (typeof requestAnimationFrame !== "function") { update(); return; }
    raf = requestAnimationFrame(function () { raf = 0; update(); });
  }
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  update();
}

// ----- Section-review TOC integration (state dots + segmented filter) -----
// A section matches a review filter when it (or any heading nested inside it) is in that state,
// so a parent section stays open when one of its subsections matches.
function _sectionHasState(entry, states, mode) {
  const hs = entry.section.querySelectorAll("h1, h2, h3, h4, h5, h6");
  for (let i = 0; i < hs.length; i++) {
    const info = states.get(hs[i]);
    if (info && info.state === mode) return true;
  }
  return false;
}
function applyReviewFilter(mode, precomputedStates) {
  _cmReviewFilter = mode || "all";
  if (_cmReviewFilterBtns) {
    Object.keys(_cmReviewFilterBtns).forEach(function (k) {
      _cmReviewFilterBtns[k].setAttribute("aria-pressed", String(k === _cmReviewFilter));
    });
  }
  if (_cmReviewFilter === "all") {
    _cmSectionToggles.forEach(function (t) { t(false); });
    return;
  }
  const states = precomputedStates || ((typeof computeSectionStates === "function") ? computeSectionStates() : new Map());
  _cmSectionEntries.forEach(function (entry) {
    const match = _sectionHasState(entry, states, _cmReviewFilter);
    entry.setState(!match); // collapse (true) when the section does not match the filter
  });
}
// Set the segmented control back to All without touching section collapse state - used when the
// user drives Expand/Collapse All directly, so a still-pressed filter does not fight the next refresh.
function _resetReviewFilterUI() {
  _cmReviewFilter = "all";
  if (_cmReviewFilterBtns) {
    Object.keys(_cmReviewFilterBtns).forEach(function (k) {
      _cmReviewFilterBtns[k].setAttribute("aria-pressed", String(k === "all"));
    });
  }
}
// Single-character status marks shown next to each side-TOC entry once the review UI is active.
// The letter is rendered as a CSS pseudo-element (data-cmh-mark) so it never enters the TOC link
// text that search and deep-links read. Unreviewed is a hollow badge (no letter).
const _CMH_TOC_MARK_CHAR = { reviewed: "R", commented: "C", changed: "!", unreviewed: "" };
// Tally every reviewable heading's state into per-filter counts. The four states partition the
// set, so `all` equals the total section count and reviewed+unreviewed+commented+changed == all.
function _cmhReviewFilterCounts(states) {
  const counts = { all: 0, reviewed: 0, unreviewed: 0, commented: 0, changed: 0 };
  if (states && typeof states.forEach === "function") {
    states.forEach(function (info) {
      counts.all++;
      const s = info && info.state;
      if (s && Object.prototype.hasOwnProperty.call(counts, s)) counts[s]++;
    });
  }
  return counts;
}
// Refresh the "(N)" count shown on each segmented filter button and keep its accessible name in
// sync (the visible count span is aria-hidden, so the aria-label carries the number for AT). This
// runs on every refreshReviewUI, which is the single funnel every state change flows through
// (mark reviewed/cleared, comment add/delete, load-time prune), so the counts never go stale.
function updateReviewFilterCounts(states) {
  if (!_cmReviewFilterBtns) return;
  const counts = _cmhReviewFilterCounts(states);
  Object.keys(_cmReviewFilterBtns).forEach(function (k) {
    const b = _cmReviewFilterBtns[k];
    const n = counts[k] || 0;
    const countEl = b.querySelector(":scope > .cm-side-toc-review-btn-count");
    if (countEl) countEl.textContent = "(" + n + ")";
    const base = b.dataset.cmhBaseLabel || k;
    b.setAttribute("aria-label", base + ", " + n + " section" + (n === 1 ? "" : "s"));
    b.title = "Show " + base.toLowerCase() + " sections (" + n + ")";
  });
}
function updateTocReviewMarks(states, active) {
  // The segmented filter appears only when active; when dormant, hide it and reset any lingering
  // filter to All so no section is left collapsed behind a control the reader can no longer see.
  if (_cmReviewFilterEl) {
    _cmReviewFilterEl.hidden = !active;
    if (!active && _cmReviewFilter !== "all" && typeof applyReviewFilter === "function") applyReviewFilter("all");
  }
  updateReviewFilterCounts(states);
  if (!_cmTocLinks || !_cmTocLinks.length) return;
  for (let i = 0; i < _cmTocLinks.length; i++) {
    const a = _cmTocLinks[i];
    const item = _cmTocItems[i];
    let mark = a.querySelector(":scope > .cmh-toc-mark");
    if (!active) { if (mark) mark.remove(); continue; }
    if (!mark) {
      mark = document.createElement("span");
      mark.className = "cmh-toc-mark";
      a.insertBefore(mark, a.firstChild);
    }
    const info = (item && item.el) ? states.get(item.el) : null;
    const state = info ? info.state : "unreviewed";
    const label = state.charAt(0).toUpperCase() + state.slice(1);
    mark.className = "cmh-toc-mark cmh-toc-mark-" + state;
    mark.dataset.cmhMark = _CMH_TOC_MARK_CHAR[state] || "";
    mark.title = label;
    // Announce a meaningful status to screen readers (the letter is a CSS pseudo-element, so a plain
    // title/aria-hidden would be inaudible); the neutral "unreviewed" hollow mark stays decorative.
    if (state === "unreviewed") {
      mark.setAttribute("aria-hidden", "true");
      mark.removeAttribute("role");
      mark.removeAttribute("aria-label");
    } else {
      mark.removeAttribute("aria-hidden");
      mark.setAttribute("role", "img");
      mark.setAttribute("aria-label", label);
    }
  }
}
