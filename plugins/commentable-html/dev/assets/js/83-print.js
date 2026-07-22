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
    return '<div class="cmh-print-reply"><p class="cmh-print-note">' + rp + escapeHtml(r.note || "") + '</p>'
      + '<p class="cmh-print-meta">reply #' + escapeHtml(r.id || "") + (rt ? " - " + escapeHtml(rt) : "") + '</p></div>';
  }).join("");
  return '<article class="cmh-print-comment" data-cid="' + escapeHtml(c.id || "") + '">'
    + '<h3>Comment ' + (index + 1) + '</h3>'
    + (path ? '<p class="cmh-print-path"><strong>In:</strong> ' + escapeHtml(path) + '</p>' : "")
    + '<p class="cmh-print-anchor"><strong>Anchor:</strong> ' + escapeHtml(_printAnchorLabel(c)) + '</p>'
    + (quote ? '<blockquote>' + escapeHtml(quote) + '</blockquote>' : "")
    + '<p class="cmh-print-note">' + pill + escapeHtml(c.note || "") + '</p>'
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
