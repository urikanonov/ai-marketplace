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
  return '<article class="cmh-print-comment" data-cid="' + escapeHtml(c.id || "") + '">'
    + '<h3>Comment ' + (index + 1) + '</h3>'
    + (path ? '<p class="cmh-print-path"><strong>In:</strong> ' + escapeHtml(path) + '</p>' : "")
    + '<p class="cmh-print-anchor"><strong>Anchor:</strong> ' + escapeHtml(_printAnchorLabel(c)) + '</p>'
    + (quote ? '<blockquote>' + escapeHtml(quote) + '</blockquote>' : "")
    + '<p class="cmh-print-note">' + escapeHtml(c.note || "") + '</p>'
    + '<p class="cmh-print-meta">#' + escapeHtml(c.id || "") + (time ? " - " + escapeHtml(time) : "") + '</p>'
    + '</article>';
}
function materializePrintAppendix() {
  if (IS_DECK) return;
  let appendix = document.getElementById("cmhPrintComments");
  if (!comments.length) {
    if (appendix) appendix.remove();
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
    + comments.map(_renderPrintComment).join("");
}
function clearPrintAppendix() {
  const appendix = document.getElementById("cmhPrintComments");
  if (appendix) appendix.remove();
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
