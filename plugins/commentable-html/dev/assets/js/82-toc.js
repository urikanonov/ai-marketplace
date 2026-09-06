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
function cmhHeadingText(h) {
  const light = (h.textContent || "").trim();
  if (light || typeof h.getHTML !== "function") return light;
  const source = h.getHTML({
    serializableShadowRoots: true,
    shadowRoots: cmhSerializableOpenShadowRoots(h),
  });
  const holder = document.createElement("template");
  holder.innerHTML = source;
  let text = "";
  const visit = function (node) {
    if (node.nodeType === 3) { text += node.nodeValue; return; }
    if (node.nodeType !== 1 && node.nodeType !== 11) return;
    if (node.nodeType === 1 && /^(SCRIPT|STYLE)$/.test(node.tagName)) return;
    visitChildren(node);
  };
  const visitChildren = function (parent) {
    let shadowUsed = false;
    parent.childNodes.forEach(function (node) {
      if (node.nodeType === 1 && node.tagName === "TEMPLATE") {
        const mode = (node.getAttribute("shadowrootmode") || "").toLowerCase();
        if (!shadowUsed && (mode === "open" || mode === "closed")) {
          shadowUsed = true;
          visitChildren(node.content);
        }
        return;
      }
      visit(node);
    });
  };
  visitChildren(holder.content);
  return text.replace(/\s+/g, " ").trim();
}
// Every heading inside #commentRoot gets a stable id and becomes a deep-link: a plain
// click (no text selection, not on a link or highlight) updates the URL to #<id> and
// scrolls to it, so a reader can copy a link straight to any section.
function setupHeadingAnchors() {
  const seen = {};
  const headingAddBtn = cmhEl("headingAddBtn");
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
    const vp = cmhViewportRect(8);
    if (left + bw > vp.right) left = r.right - bw - 6;
    headingAddBtn.style.left = Math.max(vp.left, Math.min(left, vp.right - bw)) + "px";
    headingAddBtn.style.top = Math.max(vp.top, Math.min(top, vp.bottom - bh)) + "px";
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
      const base = _cmSlugify(cmhHeadingText(h) || "section");
      let id = base, n = 2;
      while (cmhEl(id) || seen[id]) { id = base + "-" + n; n++; }
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
// Heading depth (H2 -> 2) of a side-menu target, or 0 when the anchor points at something else.
function _cmHeadingDepth(el) {
  const m = el && /^H([1-6])$/.exec(el.tagName || "");
  return m ? Number(m[1]) : 0;
}
// How deeply an author `.cm-toc` link is nested in that nav's own lists (1 for a top-level entry).
function _cmTocListDepth(a) {
  const nav = a.closest(".cm-toc");
  let depth = 0;
  for (let n = a.parentNode; n && n !== nav; n = n.parentNode) {
    if (n.tagName === "OL" || n.tagName === "UL") depth++;
  }
  return depth || 1;
}
// Turn each entry's raw depth into a 1-based menu level: heading tags win (an author TOC can list
// h2/h3/h4, and a flat list of them must still nest), an anchor that points at a non-heading falls
// back to the nav's own list nesting, and an OPEN-DEPTH STACK decides the level so a document that
// skips a heading level keeps equal-depth headings as peers (h2, h4, h4, h3 is 1, 2, 2, 2 - not
// 1, 2, 3, 2) and a level still never jumps more than one step, which the numbering below relies on.
function _cmAssignTocLevels(items) {
  let base = 0;
  items.forEach(function (it) { if (it.hLevel && (!base || it.hLevel < base)) base = it.hLevel; });
  if (!base) base = 1;
  const stack = [];
  items.forEach(function (it) {
    const raw = it.hLevel || (base + (it.listDepth || 1) - 1);
    while (stack.length && stack[stack.length - 1] >= raw) stack.pop();
    stack.push(raw);
    it.level = stack.length;
  });
}
// The number an author `.cm-toc` entry already DISPLAYS, or "" when it shows none. `generate_toc.py`
// bakes the hierarchical number into the Contents entry, so reading it keeps the in-document list
// and this menu on ONE number from one source instead of two algorithms that can disagree. Bounded
// by the nav the anchor lives in (as `_cmTocListDepth` is), so a `.cm-toc` nested inside a document
// list item can never read a number from the item OUTSIDE it.
function _cmTocEntryNumber(a) {
  const nav = a.closest(".cm-toc");
  const li = a.closest("li");
  if (!nav || !li || !nav.contains(li)) return "";
  for (let n = li.firstElementChild; n; n = n.nextElementSibling) {
    if (n.classList && n.classList.contains("cm-toc-num")) return (n.textContent || "").replace(/\s+/g, " ").trim();
  }
  return "";
}
// A leading section number an author already wrote ("3.", "2)", "10.3"), or "" when there is none.
// A year-prefixed title ("2024 review") carries no separator, so it is not a number.
function _cmTocLeadingNumber(text) {
  const m = /^((?:\d+(?:\.\d+)*[.)]|\d+\.\d+(?:\.\d+)*))\s+/.exec(String(text || ""));
  return m ? m[1].replace(/[.)]$/, "") : "";
}
// Both sides of the section filter go through one normalizer: a query and a title match on their
// visible words, so surrounding whitespace and the exact run of whitespace inside a title (source
// line breaks and indentation) never decide whether an entry is listed.
function _cmTocNormalize(text) {
  return String(text == null ? "" : text).replace(/\s+/g, " ").trim().toLowerCase();
}
function setupCollapsibleSections() {
  _cmSectionToggles.length = 0;
  _cmSectionEntries.length = 0;
  root.querySelectorAll("section").forEach(function (sec) {
    if (sec.closest(".cm-skip")) return;
    const heading = sec.querySelector(":scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > h5, :scope > h6");
    if (!heading || heading.closest(".cm-skip")) return;
    if (cmhOwnChrome(heading, ":scope > .cmh-sec-caret")) return;
    heading.classList.add("cmh-section-heading");
    const caret = document.createElement("button");
    caret.type = "button";
    caret.className = "cmh-sec-caret cm-skip";
    cmhMarkLayerChrome(caret);
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
      if (caret.contains(e.target)) return;
      if (!sec.classList.contains("cmh-section-collapsed")) return;
      const sel = window.getSelection();
      if (sel && sel.toString().trim()) return;
      setState(false);
    });
    _cmSectionToggles.push(setState);
    _cmSectionEntries.push({ heading: heading, section: sec, setState: setState });
  });
}
// The in-document Contents list folds from a caret in its title row, so a long list stops being a
// wall the reader scrolls past on every visit. Three properties keep the fold out of the DOCUMENT's
// own state: the caret is runtime-injected, TEXT-FREE cm-skip chrome (it spends no character of the
// offset space comments are anchored in), collapsing only sets a class (no node is removed or
// reordered, so a comment inside the list keeps its anchor), and the choice is READER state in a
// per-document localStorage key - an export builds from the on-disk source, so neither the caret nor
// the fold can bake into an exported document.
const CMH_TOC_FOLD_KEY = COMMENT_KEY + "::tocFold";
// Live {nav, setState} pairs, so a jump to a comment anchored INSIDE a folded Contents list can
// unfold it through the owning toggle (and so keep the caret's aria state and the persisted choice
// consistent) rather than by stripping the class behind the control's back.
const _cmTocFoldEntries = [];
function _cmReadTocFolds() {
  let parsed = null;
  try { parsed = JSON.parse(localStorage.getItem(CMH_TOC_FOLD_KEY) || "{}"); } catch (e) { parsed = null; }
  // Null-prototype, matching the ONE convention this runtime has for a document-reachable state
  // map (CMH-SEC-02, `_tsNullProto` in 62-sortable-tables.js): a JSON.parse'd map still chains to
  // Object.prototype, so a read of a key another script polluted there would otherwise fall
  // through and fold a list the reader never folded.
  return (parsed && typeof parsed === "object" && !Array.isArray(parsed))
    ? Object.assign(Object.create(null), parsed) : Object.create(null);
}
function _cmWriteTocFold(key, collapsed) {
  const state = _cmReadTocFolds();
  if (collapsed) state[key] = 1; else delete state[key];
  try { localStorage.setItem(CMH_TOC_FOLD_KEY, JSON.stringify(state)); } catch (e) { /* private mode */ }
}
// The identity a fold is stored under. The nav's AUTHORED id when it has one, else a SIGNATURE of
// the COMPLETE sequence of entry targets it lists. Both survive another Contents list being added
// above this one, which a raw DOM index does not - the reader's fold would silently move onto a
// different list. The whole sequence, not just its ends: two lists can share a first target, a last
// target and a count while listing different sections, and the newcomer would then inherit the
// fold. Each href is percent-encoded before joining, so a separator inside one cannot forge a
// boundary, and the two namespaces are disjoint so an authored id can never collide with a
// signature. Two navs that really do resolve to the same identity (duplicate ids are legal HTML,
// and two lists can genuinely list the same entries) are told apart by their order among
// themselves, which is stable as long as neither is removed.
function _cmTocFoldKeyFor(nav, used) {
  const authored = nav.getAttribute("id");
  let key;
  if (authored) {
    key = "id:" + authored;
  } else {
    const links = nav.querySelectorAll("a[href^='#']");
    const parts = [];
    for (let i = 0; i < links.length; i++) {
      parts.push(encodeURIComponent(links[i].getAttribute("href") || ""));
    }
    key = "sig:" + parts.join("|");
  }
  const seen = used[key] || 0;
  used[key] = seen + 1;
  return seen ? (key + "#" + seen) : key;
}
// Unfold EVERY folded Contents list `el` sits in, if any. Called from the jump path so a comment
// anchored on a list entry is never scrolled to inside a display:none box. Nested lists are walked
// to the outermost, the way expandCollapsedAncestors() walks nested sections: opening only the
// inner one would leave the comment hidden inside a still-folded outer list.
function expandCollapsedToc(el) {
  let nav = el && el.closest && el.closest(".cm-toc.cmh-toc-collapsed");
  while (nav) {
    for (let i = 0; i < _cmTocFoldEntries.length; i++) {
      if (_cmTocFoldEntries[i].nav === nav) { _cmTocFoldEntries[i].setState(false, true); break; }
    }
    nav = nav.parentElement && nav.parentElement.closest
      && nav.parentElement.closest(".cm-toc.cmh-toc-collapsed");
  }
}
// A `.cm-toc` can carry significant text DIRECTLY - an intro sentence beside its list, or entries
// written as bare text. The fold is a CSS rule over ELEMENT children, which cannot reach a text
// node, so such a nav would fold "half way": the caret says the list is away while a stray
// sentence stays on screen. Wrap each run that is not ignorable in a span so the same rule covers
// it. Ignorable means only the whitespace CSS itself collapses away (tab, newline, form feed,
// carriage return, space) - source indentation. It deliberately is NOT `trim()`, which also eats
// `&nbsp;` and the other Unicode space separators; those do NOT collapse, so a nav whose loose run
// is one of them still paints a line box and would still fold half way.
// The wrapper is deliberately NOT `cm-skip`: the text is the AUTHOR's, and dropping it out of the
// offset space would move every comment anchored below it. Moving the same text node under a new
// inline parent leaves that space untouched.
const _CM_TOC_IGNORABLE_TEXT_RE = /^[\t\n\f\r ]*$/;
function _cmTocWrapLooseText(nav) {
  const loose = [];
  for (let n = nav.firstChild; n; n = n.nextSibling) {
    if (n.nodeType === 3 && n.nodeValue && !_CM_TOC_IGNORABLE_TEXT_RE.test(n.nodeValue)) loose.push(n);
  }
  for (let i = 0; i < loose.length; i++) {
    const span = document.createElement("span");
    span.className = "cmh-toc-text";
    loose[i].parentNode.insertBefore(span, loose[i]);
    span.appendChild(loose[i]);
  }
}
function setupTocCollapse() {
  const root = cmhEl("commentRoot") || document.body;
  const saved = _cmReadTocFolds();
  const usedKeys = Object.create(null);
  _cmTocFoldEntries.length = 0;
  root.querySelectorAll(".cm-toc").forEach(function (nav, i) {
    if (nav.closest(".cm-skip")) return;
    if (cmhOwnChrome(nav, ".cmh-toc-caret")) return;
    _cmTocWrapLooseText(nav);
    const title = nav.querySelector(":scope > .cm-toc-title");
    // Resolve the storage identity BEFORE minting an id below, so the minted (index-derived) id
    // never becomes the key the fold is remembered under.
    const storeKey = _cmTocFoldKeyFor(nav, usedKeys);
    const caret = document.createElement("button");
    caret.type = "button";
    caret.className = "cmh-toc-caret cm-skip";
    cmhMarkLayerChrome(caret);
    // aria-controls names the NAV, not its first list: the fold hides every child but the title
    // row, so a nav that also carries an intro paragraph or a second list would otherwise announce
    // less than the button actually toggles (and a nav with no list at all would announce nothing).
    // It is resolved by getElementById, which answers with the FIRST element carrying the id, so a
    // nav whose id resolves to a DIFFERENT element - some earlier element shadows it, which needs
    // an id collision, invalid HTML that does occur - needs a runtime id of its own; otherwise its
    // caret would name a region it does not control. A nav whose id resolves to ITSELF keeps it,
    // including the first of a duplicated pair. The storage identity is already resolved from the
    // authored id above, so re-identifying the nav here never orphans a fold.
    if (!nav.id || document.getElementById(nav.id) !== nav) {
      let n = i;
      // never mint a duplicate id into the document
      while (document.getElementById("cmhToc" + n)) n++;
      nav.id = "cmhToc" + n;
    }
    caret.setAttribute("aria-controls", nav.id);
    // A list with no title of its own still gets the control, standing alone above the entries.
    if (title) title.insertBefore(caret, title.firstChild);
    else nav.insertBefore(caret, nav.firstChild);
    function setState(collapsed, persist) {
      nav.classList.toggle("cmh-toc-collapsed", collapsed);
      caret.setAttribute("aria-expanded", String(!collapsed));
      caret.title = collapsed ? "Show the contents list" : "Hide the contents list";
      caret.setAttribute("aria-label", collapsed ? "Expand table of contents" : "Collapse table of contents");
      if (persist) _cmWriteTocFold(storeKey, collapsed);
    }
    caret.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      setState(!nav.classList.contains("cmh-toc-collapsed"), true);
    });
    // A collapsed list shows only its title, so clicking that title is the natural gesture for
    // bringing it back. Expand-only, and never mid-selection, so commenting on the title of an
    // open list is unaffected.
    if (title) {
      title.addEventListener("click", function (e) {
        if (caret.contains(e.target)) return;
        if (!nav.classList.contains("cmh-toc-collapsed")) return;
        const sel = window.getSelection();
        if (sel && sel.toString().trim()) return;
        setState(false, true);
      });
    }
    _cmTocFoldEntries.push({ nav: nav, setState: setState });
    setState(saved[storeKey] === 1, false);
  });
}
function setupSideToc() {
  const root = cmhEl("commentRoot") || document.body;
  const items = [];
  const tocLinks = root.querySelectorAll(".cm-toc a[href^='#']");
  if (tocLinks.length) {
    tocLinks.forEach(function (a) {
      let id = (a.getAttribute("href") || "").slice(1);
      try { id = decodeURIComponent(id); } catch (e) { /* malformed %-encoding: keep the raw id */ }
      const el = id && cmhEl(id);
      if (el) items.push({ id: id, label: (a.textContent || "").trim(), el: el, hLevel: _cmHeadingDepth(el), listDepth: _cmTocListDepth(a), tocNum: _cmTocEntryNumber(a) });
    });
  } else {
    root.querySelectorAll("h2[id], h3[id], h4[id]").forEach(function (h) {
      if (h.closest(".cm-skip, .cm-toc")) return; // chrome and an author's own contents list, not sections
      items.push({ id: h.id, label: cmhHeadingText(h), el: h, hLevel: _cmHeadingDepth(h), listDepth: 0, tocNum: "" });
    });
  }
  if (items.length < 2) return; // not worth a side menu
  _cmAssignTocLevels(items);
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
  // If the in-document Contents list already DISPLAYS a number for its entries (generate_toc.py
  // bakes the same hierarchical number this menu would compute), show that one, so the two
  // surfaces can never disagree about what a heading is called. Otherwise: if the author already
  // numbered their TOC labels (e.g. "1. Summary", "3.1 Goals"), do NOT add a
  // second computed number - show the label as-is so there is a single number. Otherwise prefer the
  // number the DOCUMENT itself displays on the heading (generate_toc strips it from the label,
  // CMH-TOC-10, so "10.3" must not resurface as a flat "25"), and only compute one when there is
  // none to preserve.
  const tocNumbered = items.some(function (it) { return !!it.tocNum; });
  const authorNumbered = !tocNumbered && items.some(function (it) { return !!_cmTocLeadingNumber(it.label); });
  if (!authorNumbered && !tocNumbered) {
    items.forEach(function (it) {
      it.docNum = _cmHeadingDepth(it.el) ? _cmTocLeadingNumber(cmhHeadingText(it.el)) : "";
    });
  }
  const docNumbered = !authorNumbered && !tocNumbered && items.some(function (it) { return !!it.docNum; });
  // The title each row SHOWS, resolved once so the row and the filter can never disagree. An author
  // nav link with no text of its own (an icon-only link) has no title to show, so fall back to the
  // heading it targets, minus the number already rendered in its own span - resolved here, AFTER the
  // numbering mode is decided, so a heading-derived title can never flip `authorNumbered` for the
  // whole document or suppress another entry's number. A title that merely REPEATS the number the
  // row already shows (a hand-written list carrying both a `.cm-toc-num` and a numbered label) is
  // trimmed the same way, so the number reads once rather than "7 7. Intro"; only an EXACT repeat is
  // dropped, so a title whose own number differs stays visible as the discrepancy it is.
  items.forEach(function (it) {
    it.title = it.label || (_cmHeadingDepth(it.el) ? cmhHeadingText(it.el) : "");
    const shown = it.tocNum || it.docNum;
    if (shown && _cmTocLeadingNumber(it.title) === shown) {
      it.title = it.title.slice(shown.length).replace(/^[.)]?\s*/, "");
    }
  });
  const counters = [];
  items.forEach(function (it) {
    const li = document.createElement("li");
    // The indent classes stop at 6; a deeper level (reachable through a deeply nested author nav)
    // holds the level-6 indent rather than falling back to the much smaller is-sub one.
    li.className = "is-level-" + Math.min(it.level, 6) + (it.level > 1 ? " is-sub" : "");
    const a = document.createElement("a");
    a.href = "#" + it.id;
    if (authorNumbered) {
      a.textContent = it.title;
    } else {
      // Section numbers follow the heading hierarchy to any depth: 1, 1.1, 1.1.1, 1.2, 2...
      let num = it.tocNum || it.docNum || "";
      if (!tocNumbered && !docNumbered) {
        counters.length = it.level;
        for (let d = 0; d < it.level; d++) if (typeof counters[d] !== "number") counters[d] = 0;
        counters[it.level - 1]++;
        num = counters.join(".");
      }
      if (num) a.innerHTML = '<span class="cm-toc-num">' + escapeHtml(num) + '</span> ' + escapeHtml(it.title);
      else a.textContent = it.title;
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
  // A11: filter the visible sections (and their menu entries) by section title.
  // Scope the section lookup to the content root at BOTH ends: an author TOC may target an element
  // outside it, and even an in-root target's nearest `<section>` ancestor can be a host-page one
  // (when the root sits inside the page's own section). The runtime must never write a filter class
  // onto anything but a section the document owns.
  function _cmTocSectionOf(it) {
    if (!it.el || !it.el.closest || !root.contains(it.el)) return null;
    const s = it.el.closest("section");
    return (s && s !== root && root.contains(s)) ? s : null;
  }
  // Cache each item's normalized lowercase TITLE once, so typing does not re-read it on each
  // keystroke. What a query sees is exactly what the row shows: the resolved title plus the number
  // the DOCUMENT itself supplies - the one baked into its Contents entry, else the one the heading
  // displays - never the sequential one the runtime computes for a document that has none (that
  // number is chrome, not title text). Body prose is not part of a title, and the review status mark
  // is a CSS pseudo-element, so neither can reach a query.
  items.forEach(function (it) {
    const docSupplied = it.tocNum || it.docNum;
    it._cmHay = _cmTocNormalize((docSupplied ? docSupplied + " " : "") + it.title);
  });
  // Every <section> any entry lives in, with the entries it holds: a section is hidden only when
  // EVERY entry inside it is filtered out, so a single wrapper section around the whole document
  // can never be hidden out from under a matching heading.
  const filterSecs = [];
  items.forEach(function (it) {
    const s = _cmTocSectionOf(it);
    if (s && filterSecs.indexOf(s) === -1) filterSecs.push(s);
  });
  const filterSecIndex = new Map();
  filterSecs.forEach(function (s, k) { filterSecIndex.set(s, k); });
  const filterSecItems = filterSecs.map(function () { return []; });
  items.forEach(function (it, i) {
    // Walk the entry's own section chain upward: every section that CONTAINS it is exactly its
    // ancestor-or-self chain, so this is the containment map without an O(sections * items) sweep.
    for (let s = _cmTocSectionOf(it); s; s = s.parentElement ? s.parentElement.closest("section") : null) {
      const k = filterSecIndex.get(s);
      if (k !== undefined) filterSecItems[k].push(i);
    }
  });
  function applyTocFilter(q) {
    const query = _cmTocNormalize(q);
    const vis = [];
    for (let i = 0; i < items.length; i++) vis[i] = !query || items[i]._cmHay.indexOf(query) !== -1;
    // Keep the ancestors of a match listed so a matching subsection still shows where it lives.
    // `need` is SET from each visible entry's own level (never merely lowered): a later shallow
    // match must not cancel the ancestor chain an earlier deeper match still needs.
    let need = Infinity;
    for (let i = items.length - 1; i >= 0; i--) {
      if (need < Infinity && items[i].level < need) vis[i] = true;
      if (vis[i]) need = items[i].level;
    }
    let anyMatch = false;
    for (let i = 0; i < items.length; i++) if (vis[i]) { anyMatch = true; break; }
    for (let i = 0; i < items.length; i++) {
      items[i]._cmFiltered = !vis[i]; // scroll-spy reads this so it skips hidden entries (sectioned or not)
      const li = links[i].closest("li");
      if (li) li.classList.toggle("cm-toc-li-hidden", !vis[i]);
    }
    for (let k = 0; k < filterSecs.length; k++) {
      const shown = filterSecItems[k].some(function (i) { return vis[i]; });
      // A query that matches NOTHING narrows the menu only: hiding every section would blank the
      // whole document (a single-wrapper report especially) over what is usually a typo.
      filterSecs[k].classList.toggle("cm-toc-filtered", anyMatch && !shown);
    }
    if (typeof schedule === "function") schedule(); // re-run scroll-spy so aria-current follows the filter
  }
  function clearTocFilter() { if (search.value) search.value = ""; applyTocFilter(""); }
  search.addEventListener("input", function () { applyTocFilter(search.value); });
  search.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { e.preventDefault(); clearTocFilter(); search.blur(); }
  });
  // Reveal a filtered-out entry when a deep link targets it, rather than scrolling to nothing. Test
  // for ANY filtered section ancestor (an outer one hides the target just as well as the nearest),
  // and for the entry's own hidden row - inside a wrapper that stays visible, the row is the only
  // thing the filter took away.
  window.addEventListener("hashchange", function () {
    let id = (location.hash || "").slice(1);
    try { id = decodeURIComponent(id); } catch (e) { /* keep the raw id */ }
    const el = id && cmhEl(id);
    if (!el) return;
    const hidden = (el.closest && el.closest("section.cm-toc-filtered"))
      || items.some(function (it) { return it._cmFiltered && it.el === el; });
    if (hidden) {
      // Clear the filter first: expandCollapsedAncestors only clears it for a filtered SECTION, and
      // a hidden row inside a visible wrapper is exactly the case that has no filtered section.
      clearTocFilter();
      // expandCollapsedAncestors (shared bundle scope) also expands collapsed ancestors so a
      // revealed section shows its body, not just its heading.
      if (typeof expandCollapsedAncestors === "function") expandCollapsedAncestors(el);
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
  if (cmhEl("cmScrollProgress")) return;
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
