/* ---------- Document-wide comments ---------- */
// A comment not tied to any element (raised by right-clicking empty space). It has no
// highlight and no offsets; it just carries a note about the whole document.
function openDocumentComposer() { return createComposerElement({ mode: "new-document" }); }

// Deck-only: a comment tied to a specific slide (raised by "Comment on slide" on an empty
// right-click). Like a document comment it has no text highlight, but it records the slide
// id/title/index so the sidebar can label it and its jump can navigate to that slide.
function _deckSlideMeta(slideEl) {
  if (!slideEl) return null;
  // Index within the SAME slide set the deck runtime uses (the stage), so a persisted slideIndex
  // matches window.__cmhDeck's indexing for the id-less jump fallback.
  const scope = root.querySelector(".deck-stage") || root;
  const slides = Array.prototype.slice.call(scope.querySelectorAll(".slide"));
  const index = slides.indexOf(slideEl);
  const explicit = slideEl.getAttribute("data-slide-title") || slideEl.getAttribute("aria-label");
  const heading = slideEl.querySelector("h1,h2,h3,h4,h5,h6");
  const text = explicit || (heading && heading.textContent) || slideEl.getAttribute("data-slide-id");
  // Cap the derived title so an over-long heading cannot bloat every sidebar card and Copy-all
  // line; the full slide is still identified by its id.
  const title = (text || ("Slide " + (index + 1))).replace(/\s+/g, " ").trim().slice(0, 120);
  return { slideId: slideEl.getAttribute("data-slide-id"), slideTitle: title, slideIndex: index };
}
function openSlideComposer(slideId) {
  let slideEl = null;
  if (slideId) {
    // Match by getAttribute rather than an attribute selector so the runtime never inlines a
    // literal data-slide-id attribute string (which a scaffold's slide-id count would miscount).
    const scope = root.querySelector(".deck-stage") || root;
    const all = Array.prototype.slice.call(scope.querySelectorAll(".slide"));
    slideEl = all.filter(function (s) { return s.getAttribute("data-slide-id") === slideId; })[0] || null;
  }
  // Fall back to the active slide when the id is missing or did not resolve (e.g. a slide
  // authored without a data-slide-id), so the comment still ties to the on-screen slide.
  if (!slideEl) slideEl = root.querySelector(".slide.active") || root.querySelector(".slide");
  const meta = _deckSlideMeta(slideEl) || { slideId: slideId || null, slideTitle: "", slideIndex: -1 };
  return createComposerElement({ mode: "new-slide", slide: meta });
}

