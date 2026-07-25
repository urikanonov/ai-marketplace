function _printHeadingPath(c) {
  if (c && c.headingPath && c.headingPath.length) {
    return c.headingPath.map(function (h) { return h && h.text; }).filter(Boolean).join(" > ");
  }
  return (c && c.section) || "";
}
function _printAnchorLabel(c) {
  if (!c) return "Comment";
  if (c.anchorType === "document") return "Document-wide comment";
  if (c.anchorType === "slide") return "Slide comment" + (c.slideTitle ? ' - "' + c.slideTitle + '"' : "");
  if (c.anchorType === "mermaid") {
    return c.nodeKey && c.nodeKey !== "__diagram__" ? "Mermaid node " + c.nodeKey : "Mermaid diagram";
  }
  if (c.anchorType === "diff") {
    const line = (typeof diffLineLocator === "function") ? diffLineLocator(c) : "";
    return "Diff" + (c.diffLabel ? " " + c.diffLabel : "") + (line ? " - " + line : "");
  }
  if (c.anchorType === "image") return (c.imageKind === "chart" ? "Chart" : "Image") + " " + ((Number(c.imageIndex) || 0) + 1);
  if (c.anchorType === "link") return "Link" + (c.linkText ? ' - "' + c.linkText + '"' : "");
  if (c.anchorType === "widget") return "Widget " + (c.widget || "widget") + (c.partLabel || c.part ? " - " + (c.partLabel || c.part) : "");
  if (c.isCode) return c.codeLanguage ? "Code block (" + c.codeLanguage + ")" : "Code block";
  return "Text selection";
}
function _printQuote(c) {
  if (!c) return "";
  if (c.anchorType === "document") return "(document-wide comment)";
  if (c.anchorType === "slide") return c.slideTitle ? ('slide: "' + c.slideTitle + '"') : "(comment on slide)";
  if (c.anchorType === "image") return c.imageAlt || c.quote || c.imageSrc || "";
  if (c.anchorType === "link") return c.linkText || c.quote || c.linkHref || "";
  if (c.anchorType === "widget") return c.partLabel || c.part || c.quote || "";
  if (c.anchorType === "mermaid") return c.nodeLabel || c.nodeKey || c.quote || "";
  return c.quote || "";
}
function _renderPrintComment(c, index) {
  const path = _printHeadingPath(c);
  const quote = _printQuote(c);
  const time = formatTime((c && (c.updatedAt || c.createdAt)) || "");
  const pill = (typeof authorPillHtml === "function") ? authorPillHtml(c.author) : "";
  const replies = (typeof repliesOf === "function") ? repliesOf(c.id, comments) : [];
  const repliesHtml = replies.map(function (r) {
    const rp = (typeof authorPillHtml === "function") ? authorPillHtml(r.author) : "";
    const rt = formatTime((r && (r.updatedAt || r.createdAt)) || "");
    return '<div class="cmh-print-reply"><div class="cmh-print-note cmh-rich">' + rp + renderRichNote(r.note || "") + '</div>'
      + '<p class="cmh-print-meta">reply #' + escapeHtml(r.id || "") + (rt ? " - " + escapeHtml(rt) : "") + '</p></div>';
  }).join("");
  return '<article class="cmh-print-comment" data-cid="' + escapeHtml(c.id || "") + '">'
    + '<h3>Comment ' + (index + 1) + '</h3>'
    + (path ? '<p class="cmh-print-path"><strong>In:</strong> ' + escapeHtml(path) + '</p>' : "")
    + '<p class="cmh-print-anchor"><strong>Anchor:</strong> ' + escapeHtml(_printAnchorLabel(c)) + '</p>'
    + (quote ? '<blockquote>' + escapeHtml(quote) + '</blockquote>' : "")
    + '<div class="cmh-print-note cmh-rich">' + pill + renderRichNote(c.note || "") + '</div>'
    + '<p class="cmh-print-meta">#' + escapeHtml(c.id || "") + (time ? " - " + escapeHtml(time) : "") + '</p>'
    + repliesHtml
    + '</article>';
}
function materializePrintAppendix() {
  if (IS_DECK) return;
  let appendix = document.getElementById("cmhPrintComments");
  const roots = (typeof threadRoots === "function") ? threadRoots(comments) : comments;
  if (!roots.length) {
    if (appendix) {
      CMH_INJECTED_CHROME.delete(appendix);
      appendix.remove();
    }
    return;
  }
  if (!appendix) {
    appendix = document.createElement("section");
    appendix.id = "cmhPrintComments";
    appendix.className = "cmh-print-comments";
    appendix.setAttribute("aria-label", "Review comments");
    root.appendChild(appendix);
    CMH_INJECTED_CHROME.add(appendix);
  }
  appendix.innerHTML = '<h2>Review comments</h2>'
    + '<p class="cmh-print-intro">Current in-browser comments at print time.</p>'
    + roots.map(_renderPrintComment).join("");
}
function clearPrintAppendix() {
  const appendix = document.getElementById("cmhPrintComments");
  if (appendix) {
    // Drop it from the injected-chrome set too, so repeated print/cancel cycles (each of which
    // recreates the appendix) do not accumulate detached nodes that the set keeps alive.
    CMH_INJECTED_CHROME.delete(appendix);
    appendix.remove();
  }
}
function setupPrintAppendix() {
  if (IS_DECK || setupPrintAppendix._done) return;
  setupPrintAppendix._done = true;
  window.addEventListener("beforeprint", materializePrintAppendix);
  window.addEventListener("afterprint", clearPrintAppendix);
  if (window.matchMedia) {
    const query = window.matchMedia("print");
    const onChange = function (event) {
      if (event.matches) materializePrintAppendix();
      else clearPrintAppendix();
    };
    if (query.addEventListener) query.addEventListener("change", onChange);
    else if (query.addListener) query.addListener(onChange);
    if (query.matches) materializePrintAppendix();
  }
}

// The vendored deck engine's print stylesheet forces every slide to `display: block`, which flattens
// a slide's authored flex/grid layout so its columns stack and overflow the fixed 1080px slide box,
// clipping content. While printing, pin each deck slide's on-screen computed display inline (an
// inline `!important` beats the vendored rule) so the print/PDF keeps the exact layout the reader
// sees on screen, then remove the inline display when print ends. The pin is PRINT-SCOPED (applied
// on print-media entry / beforeprint, cleared on exit / afterprint) rather than permanent, so a
// slide carries no inline `style` attribute under normal media - it never leaks into an exported
// file and never trips invariants that require clean slide elements (e.g. the deck-theme applies via
// a `<style>` element, not inline styles). Safe because the engine shows/hides slides via
// `visibility`/`opacity`, never `display`, so the pinned (always non-`none`) display never fights it.
function pinDeckSlideDisplayForPrint() {
  if (!IS_DECK) return;
  const slides = [].slice.call(root.querySelectorAll(".slide"));
  // Capture each slide's ON-SCREEN display now (startup, screen media) - once print media is active
  // the vendored `.slide{display:block}` rule already flattens it, so reading the display during
  // print would just pin `block`. The authored display comes from static CSS and never changes
  // (the engine toggles visibility/opacity, not display), so this startup snapshot is correct.
  const screenDisplays = slides.map(function (slide) { return getComputedStyle(slide).display; });
  const pin = function () {
    slides.forEach(function (slide, i) {
      const display = screenDisplays[i];
      if (display && display !== "none") slide.style.setProperty("display", display, "important");
    });
  };
  const unpin = function () {
    slides.forEach(function (slide) {
      slide.style.removeProperty("display");
      // Drop an emptied style attribute so the slide is byte-clean under normal media.
      if (!slide.getAttribute("style")) slide.removeAttribute("style");
    });
  };
  window.addEventListener("beforeprint", pin);
  window.addEventListener("afterprint", unpin);
  if (window.matchMedia) {
    const query = window.matchMedia("print");
    const onChange = function (event) {
      if (event.matches) pin();
      else unpin();
    };
    if (query.addEventListener) query.addEventListener("change", onChange);
    else if (query.addListener) query.addListener(onChange);
    if (query.matches) pin();
  }
}

// Single continuous page for flat (non-deck) documents: rather than paginating onto A4/Letter
// sheets, print/Save-as-PDF a flat document as ONE page sized to the content, so no page break ever
// cuts through a section, table, chart, or diagram. On print entry the runtime measures the full
// content (width and height) and injects a dynamic `@page { size: W H }`, so the whole document
// (including the materialized comments appendix) flows onto a single page. It depends on the browser
// honoring a CSS `@page` size (Chromium's native print/PDF, the engine behind the "Save as PDF"
// action); a document taller/wider than the browser's page-size limit falls back to normal
// pagination. Decks are excluded - they keep their own one-landscape-16:9-page-per-slide layout (see
// pinDeckSlideDisplayForPrint and 92-print.css).
//
// The injected <style> cannot leak into an exported file: the whole final rule set is scoped to
// `@media print` (inert on screen) AND is emptied on afterprint / print-media exit, and every export
// path rebuilds from the pristine on-disk / snapshot HTML rather than re-serializing the live <head>.
function setupSinglePagePrint() {
  if (IS_DECK || setupSinglePagePrint._done) return;
  setupSinglePagePrint._done = true;

  // Single-page sizing is reliable only when the PRINT layout matches the ON-SCREEN layout, because
  // Chromium locks the print @page size to a measurement taken at `beforeprint` (in screen media,
  // before print media activates). A multi-column gallery (`.visual-grid`), a diagram gallery
  // (`.cmh-diagram-gallery`, which block-stacks and drops its per-card height cap for print), or a
  // grid/flex widget (a kanban board) reflows grid->block for print (92-print.css) and async-resizes
  // its charts/diagrams, so its printed height differs from - and cannot be reliably measured before -
  // the @page lock. Leave a document that contains such a container on normal pagination (its content
  // is never clipped; it just spans standard pages). Prose, tables, inline charts, standalone
  // diagrams, code, KQL, and diffs all keep the single-page treatment.
  function hasBlockStackingContainer() {
    if (root.querySelector(".visual-grid, .cmh-diagram-gallery")) return true;
    const widgets = root.querySelectorAll("[data-cm-widget]");
    for (let i = 0; i < widgets.length; i++) {
      const d = getComputedStyle(widgets[i]).display;
      if (d === "grid" || d === "flex" || d === "inline-grid" || d === "inline-flex") return true;
    }
    return false;
  }
  if (hasBlockStackingContainer()) return;

  // Chromium clamps a page dimension to 200in (~19200px at 96dpi); stay well under it. A document
  // that would exceed this in either axis falls back to normal pagination rather than being clipped.
  const MAX_PAGE_PX = 18000;
  // The inset around the single-page content, as a real print margin (0.5in - a standard, safe page
  // margin that clears typical printer hardware minimums, ~0.25in). It is applied as the `@page`
  // MARGIN (see printCss), not body padding, so a driver that ignores the custom @page size but honors
  // its margin still gets a sane inset, and the content height is not double-counted. It is also the
  // amount by which the page is larger than the measured content in each axis
  // (pageW = contentW + 2*PAD, pageH = h + 2*PAD).
  const PAD = 48;

  // The honored single continuous page is sized to a portable, standard page width (US Letter, 816px)
  // rather than the on-screen reading column (which is ~1280px on a wide screen), so the browsers that
  // honor the custom @page (Chromium's native vector "Save as PDF") produce a standard-sheet-width
  // PDF instead of an awkward 13in-wide one. On drivers that IGNORE the custom @page (Microsoft Print
  // to PDF, physical printers) the content is NOT forced to this width at all - printCss uses
  // width:auto so it reflows into the real printable area (see printCss) - so the exact value here
  // only sets the honored page's width; content that genuinely cannot fit it (a wide table) still
  // grows the page past the cap so nothing is clipped.
  const PORTABLE_PAGE_W = 816;

  // The on-screen reading-column width drives the single-page width. Print media resets body/.app
  // width, so it must be read under SCREEN media; keep it fresh across window resizes (but never
  // sample the reset width during a print) so a resize before printing does not use a stale value.
  function readColumnWidth() { return Math.round(root.getBoundingClientRect().width) || 0; }
  function inPrintMedia() { return !!(window.matchMedia && window.matchMedia("print").matches); }
  let readWidth = readColumnWidth();
  window.addEventListener("resize", function () {
    if (!inPrintMedia()) { const w = readColumnWidth(); if (w) readWidth = w; }
  });

  let styleEl = null;
  let cachedW = 0, cachedH = 0;
  let measuring = false;
  let applied = false;

  function ensureStyle() {
    if (styleEl) return;
    styleEl = document.createElement("style");
    styleEl.id = "cmhPrintSinglePage";
    document.head.appendChild(styleEl);
    if (typeof CMH_INJECTED_CHROME !== "undefined" && CMH_INJECTED_CHROME.add) CMH_INJECTED_CHROME.add(styleEl);
  }

  function measureHeight() {
    const de = document.documentElement;
    const body = document.body;
    return Math.max(de.scrollHeight, body.scrollHeight, body.offsetHeight,
      root.offsetTop + root.scrollHeight);
  }

  // Measurement rules: NOT wrapped in `@media print`, so they apply while measuring under SCREEN
  // media. They MIRROR the SYNCHRONOUS height-affecting print rules in 92-print.css (reveal the
  // print-only appendix, expand collapsed sections/notes, wrap code, reflow tables, cap tall media).
  // They do NOT change the width, and printCss below UNDOES the print block-stacking of
  // widgets/galleries - both because a width change or a grid->block reflow retriggers an async
  // Chart.js canvas resize that makes the page measure short. So single-page print keeps the
  // on-screen grid layout and the measurement equals the printed height. Keep in sync with
  // 92-print.css (drift is caught by CMH-PRINT-06). Applied and measured synchronously, then removed,
  // so nothing repaints on screen.
  function measureCss() {
    return ".cmh-print-comments,.cmh-print-noscript{display:block !important}"
      + "#commentRoot section.cmh-section-collapsed>*{display:revert !important}"
      + "#commentRoot .cmh-note.cmh-note-collapsed .cmh-note-input,"
      + "#commentRoot .cmh-note.cmh-note-collapsed .cmh-note-head{display:revert !important}"
      + "#commentRoot pre,#commentRoot code,#commentRoot .cmh-diff-view pre,#commentRoot .cmh-diff-view code,"
      + "#commentRoot figure.cmh-kql pre,#commentRoot figure.cmh-kql code{white-space:pre-wrap !important;"
      + "overflow-wrap:anywhere !important;word-break:break-word !important}"
      + "#commentRoot table{display:table !important;width:100% !important;max-width:100% !important;table-layout:auto !important}"
      // Long unbreakable cell text (an id, url, or token) wraps rather than forcing the table wider,
      // so on a driver that CANNOT grow the page (a non-honoring driver paginating onto fixed paper) a
      // wide cell wraps instead of being clipped off the sheet edge. Mirrors 92-print.css.
      + "#commentRoot td,#commentRoot th{overflow-wrap:anywhere !important;word-break:break-word !important}"
      + "#commentRoot pre.mermaid svg,#commentRoot figure svg,#commentRoot figure img,#commentRoot img{"
      + "max-height:8.4in !important;max-width:100% !important;width:auto !important;height:auto !important}"
      // Chart canvases (and any inline SVG) scale to fit the column too, so a narrowed measurement
      // matches print instead of overflowing the capped page width. Mirrors 92-print.css.
      + "#commentRoot img,#commentRoot svg,#commentRoot canvas{max-width:100% !important;height:auto !important}"
      // Mirror the print-only box model of the materialized comments appendix (92-print.css) so its
      // height is measured accurately - each comment's margin/padding/border is print-scoped and would
      // otherwise be invisible to this screen-media measure, under-counting a heavily-commented
      // document's height enough to spill a trailing overflow page. Borders are made transparent so
      // the measurement adds their WIDTH without painting anything on screen.
      + ".cmh-print-comments,.cmh-print-noscript{margin:2rem 0 0 !important;padding:1rem 0 0 !important;"
      + "border-top:2px solid transparent !important}"
      + ".cmh-print-comment{margin:1rem 0 !important;padding:0.85rem 1rem !important;"
      + "border:1px solid transparent !important}"
      + ".cmh-print-comment h3{margin:0 0 0.45rem !important}"
      + ".cmh-print-comment p{margin:0.35rem 0 !important}"
      + ".cmh-print-comment blockquote{margin:0.5rem 0 !important;padding:0.4rem 0.65rem !important}"
      // Replies are print-only indented and top-margined (88-threads.css @media print); mirror that so
      // a thread-heavy document's replies are counted (the indent also wraps reply text taller).
      + ".cmh-print-reply{margin:0.2rem 0 0 0.8rem !important}";
  }
  // Final rules: print-scoped (inert on screen). PROGRESSIVE DEGRADATION - do NOT force a fixed body
  // width. The single custom `@page { size: pageW pageH; margin: PAD }` carries the portable page
  // dimensions, and `width: auto` lets the content flow into whatever page it actually gets: on a
  // browser that HONORS the custom `@page` size (Chromium's native vector "Save as PDF") the content
  // fills the pageW-wide custom page as ONE tall page; on a driver that IGNORES it (Microsoft Print
  // to PDF, physical printers, browsers without custom-`@page` support) the content instead reflows
  // into the driver's real Letter/A4 printable area and paginates normally - NEVER forced to an
  // oversized width that the driver would then downscale (the old bug). The @page MARGIN (not body
  // padding) provides the inset, so it is honored on both paths without double-counting the height.
  // Two assumptions the honored-path math relies on: (1) this runtime <style> is appended to <head>
  // AFTER the bundled 92-print.css, so its `@page{margin:PAD}` wins over the base `@page{margin:0.6in}`
  // by source order (keep it appended last); (2) the honored content area equals `pageW - 2*PAD`, so a
  // user who manually selects a LARGER margin than PAD in the browser's own print dialog shrinks that
  // area below the measured contentW - inherent to any custom-@page single-page layout, harmless
  // (content just wraps a little) but not something CSS can prevent.
  function printCss(pageW, pageH) {
    return "@media print{html,body,.app{width:auto !important;max-width:none !important;"
      + "margin:0 !important;padding:0 !important;box-sizing:border-box !important}"
      + ".cmh-print-comments,.cmh-print-noscript{break-before:auto !important;page-break-before:auto !important}"
      + "@page{size:" + pageW + "px " + pageH + "px;margin:" + PAD + "px}}";
  }

  // Screen-media replica used to MEASURE the printed CONTENT height at content width `cw` (= the page
  // content area, pageW - 2*PAD). It forces html/body/.app to `cw` with NO padding (the inset is the
  // @page margin in print, applied outside the content box), so the measured height is the true
  // content height at the width the honored page will render it - no `.app`-overflows-body box-model
  // skew and no PAD double-count. Applied and read synchronously, then replaced, so nothing repaints.
  function layoutAtWidthCss(cw) {
    return "html,body,.app{width:" + cw + "px !important;max-width:none !important;"
      + "margin:0 !important;padding:0 !important;box-sizing:border-box !important}";
  }

  // Measure the print-layout size (WITHOUT the comments appendix) under STABLE screen media and cache
  // it. This is the crux of the robustness: Chromium fires `beforeprint` in screen media and LOCKS
  // the @page to what is measured then - but at `beforeprint` the print pipeline is re-rendering
  // charts/mermaid asynchronously, so a measurement taken then catches a transient short state and
  // the page spills. Measuring HERE instead (charts/mermaid settled, no print pipeline) is reliable,
  // and apply() uses the cache. The appendix is added at print time (synchronous DOM, safe then).
  function computeAndCache() {
    if (measuring || inPrintMedia()) return;
    measuring = true;
    ensureStyle();
    const prev = styleEl.textContent;
    try {
      styleEl.textContent = measureCss();
      void document.documentElement.offsetHeight;
      const colW = Math.round(root.getBoundingClientRect().width) || readWidth || 800;
      const w = Math.max(colW, root.scrollWidth);
      const h = measureHeight();
      if (w > 0 && h > 0) { cachedW = w; cachedH = h; }
    } catch (e) { /* keep the last good cache */ }
    finally { styleEl.textContent = prev; measuring = false; }
  }

  // Refresh the cache when the layout can change: initial progressive settle (charts/mermaid render
  // async over the first few seconds), window resize, and a ResizeObserver on chart canvases (which
  // settle asynchronously). computeAndCache measures at the NATURAL (un-narrowed) width, where the
  // canvas cap in measureCss (max-width:100%) is a no-op because a canvas already fits its container -
  // so no canvas is resized and observing canvases cannot loop on our own measurement. The width
  // narrowing that scales canvases (layoutAtWidthCss) only runs synchronously inside apply() at print
  // time, not here.
  let rafId = 0;
  function scheduleCache() {
    if (rafId) return;
    const raf = window.requestAnimationFrame || function (f) { return setTimeout(f, 32); };
    rafId = raf(function () { rafId = 0; computeAndCache(); });
  }
  [0, 250, 700, 1500, 3000].forEach(function (t) { setTimeout(scheduleCache, t); });
  window.addEventListener("resize", function () { if (!inPrintMedia()) scheduleCache(); });
  if (window.ResizeObserver) {
    try {
      const ro = new ResizeObserver(function () { scheduleCache(); });
      const observeCanvases = function () {
        const cs = root.querySelectorAll(".chart-wrap canvas");
        for (let i = 0; i < cs.length; i++) { try { ro.observe(cs[i]); } catch (e) { /* ignore */ } }
      };
      observeCanvases();
      // Refresh the cache on any content mutation while not printing too, so late-inserted content
      // (a Mermaid SVG rendered after the last settle timer, lazy content) updates cachedH - not just
      // an observed canvas resize. scheduleCache is rAF-debounced, and computeAndCache mutates only a
      // <head> <style> (not #commentRoot), so this never loops on our own measurement.
      const mo = new MutationObserver(function () { observeCanvases(); if (!inPrintMedia()) scheduleCache(); });
      mo.observe(root, { childList: true, subtree: true });
    } catch (e) { /* observers are best-effort */ }
  }

  function apply() {
    // Chromium LOCKS the @page to the first measurement (beforeprint, screen media), so run once per
    // print and reset by clear() on exit.
    if (applied) return;
    applied = true;
    ensureStyle();
    try {
      // Re-check eligibility here, not only at setup: a block-stacking container (a diagram/chart
      // gallery or a grid/flex widget) inserted AFTER setup would otherwise get the single-page path
      // even though its print-time reflow cannot be pre-measured. If one is present now, fall back.
      if (hasBlockStackingContainer()) { styleEl.textContent = ""; return; }
      // Document size: prefer the stable cache (charts settled), but never go below a fresh inline
      // measure - so the very first print before anything cached is still covered.
      styleEl.textContent = measureCss();
      // Ensure the comments appendix is present (setupPrintAppendix also materializes it on
      // beforeprint; idempotent), so the inline measurement below includes it.
      if (typeof materializePrintAppendix === "function") materializePrintAppendix();
      void document.documentElement.offsetHeight;
      const colW = Math.round(root.getBoundingClientRect().width) || readWidth || 800;
      // Cap the CONTENT width to a portable standard page's content area (PORTABLE_PAGE_W minus the
      // two @page margins) so the honored single page is standard-sheet-sized. Content that genuinely
      // cannot fit the cap (a wide table) still grows the page below, so nothing is ever clipped.
      const MAX_CONTENT_W = PORTABLE_PAGE_W - PAD * 2;
      let contentW = Math.min(Math.max(cachedW, colW, root.scrollWidth), MAX_CONTENT_W);
      // Measure the height AT the content width the honored page renders at (pageW - 2*PAD): a
      // narrower column reflows taller and scales charts/diagrams to fit, so the height must be taken
      // there, not at the wide reading column. This width now MATCHES the printed content width
      // (printCss uses width:auto inside the pageW-wide @page), so the measurement is accurate.
      styleEl.textContent = measureCss() + layoutAtWidthCss(contentW);
      void document.documentElement.offsetHeight;
      // Unbreakable content wider than the capped column (a wide table, a long code token, an
      // author-styled overwide child) overflows #commentRoot; grow the content width by the overflow
      // so it is never clipped. Iterate a few times because widening can expose a DIFFERENT widest
      // element (a percentage-width or containing-block-relative child); contentW only grows, so it
      // cannot oscillate, and it converges when the row no longer overflows.
      for (let i = 0; i < 4; i++) {
        const overflow = root.scrollWidth - root.clientWidth;
        if (overflow <= 1) break;
        contentW = contentW + Math.ceil(overflow);
        styleEl.textContent = measureCss() + layoutAtWidthCss(contentW);
        void document.documentElement.offsetHeight;
      }
      // If content STILL overflows after bounded growth (pathological content that widens with its
      // container, e.g. a percentage width), do not emit a page that clips it - fall back to normal
      // pagination instead.
      if (root.scrollWidth - root.clientWidth > 1) { styleEl.textContent = ""; return; }
      // The INLINE measure already includes the materialized appendix; the stable cache measured the
      // document WITHOUT the appendix, so add the appendix height to the CACHE path only (never to the
      // inline path - that would double-count it), and take the larger. The inline capped-width measure
      // is the accurate one; the cache is a SAFE FLOOR that only ever errs TALL: it was measured at the
      // wide reading column, where a wide chart/diagram can be proportionally taller than at the capped
      // print width, so `cachedH` can exceed the true narrow height - which adds harmless bottom
      // whitespace, never a spill or clip. It also covers a rare very-early print before charts settle.
      const appendix = document.getElementById("cmhPrintComments");
      const appendixH = appendix ? Math.ceil(appendix.getBoundingClientRect().height) : 0;
      const h0 = Math.max(measureHeight(), cachedH > 0 ? cachedH + appendixH : 0);
      const w = contentW + PAD * 2;
      // Page height = content height + the two @page margins + a small safety band. Because the height
      // is now measured at the SAME width the honored page renders at, the screen-vs-print drift is
      // tiny (rounding only), so a small band suffices - unlike the old wrong-width measurement that
      // needed a large proportional band. The band still guards a small over/under so a slight
      // under-measure can never spill a near-blank overflow page (harmless bottom whitespace instead).
      const h = h0 + PAD * 2 + Math.max(24, Math.ceil(h0 * 0.01));
      if (h > MAX_PAGE_PX || w > MAX_PAGE_PX) {
        // Too large for one page - fall back to the default paginated print layout.
        styleEl.textContent = "";
        return;
      }
      styleEl.textContent = printCss(w, h);
    } catch (e) {
      // Never let print sizing throw - fall back to normal pagination.
      styleEl.textContent = "";
    }
  }

  function clear() {
    applied = false;
    if (styleEl) styleEl.textContent = "";
  }

  window.addEventListener("beforeprint", apply);
  window.addEventListener("afterprint", clear);
  if (window.matchMedia) {
    // Some browsers fire only the print-media change, not `beforeprint`; apply on the print-media
    // entry as a fallback. Do NOT clear on the print-media EXIT here - that transition can fire
    // before the print pipeline finishes rasterizing, which would drop the @page/pins mid-render and
    // spill the page; `afterprint` is the reliable teardown signal.
    const query = window.matchMedia("print");
    const onChange = function (event) { if (event.matches) apply(); };
    if (query.addEventListener) query.addEventListener("change", onChange);
    else if (query.addListener) query.addListener(onChange);
    if (query.matches) apply();
  }
}

// sidebar export menu (btnPrint) trigger the browser's native print, which renders the print/PDF
// layout. This deliberately does NOT intercept Ctrl/Cmd+P, so the native shortcut still works.
// Wired for flat documents and decks alike (deck print page-breaks one slide per page).
function triggerNativePrint() {
  if (typeof window.print === "function") window.print();
}
["btnPrint", "btnPrintTop"].forEach(function (id) {
  const button = document.getElementById(id);
  if (button) button.addEventListener("click", triggerNativePrint);
});
