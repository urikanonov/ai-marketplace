/* ---------- Image comment layer ----------
   Makes any <img> inside #commentRoot commentable. Each image is indexed in
   document order (imageIndex); hovering or keyboard-focusing it reveals a
   floating "+ comment" button, and the comment anchors by (imageIndex) with the
   src as a fallback key so it survives reload, Copy all, and Export as Portable. This
   mirrors the mermaid-node layer: images carry no text offsets, so image
   comments are excluded from backfillContext / restoreHighlights. */
const imageEls = [];
const imageAddBtn = document.getElementById("imageAddBtn");
let pendingImage = null;
let imageAddHideTimer = null;
let imageActiveEl = null;

function indexImages() {
  imageEls.length = 0;
  root.querySelectorAll("img, canvas").forEach((el) => {
    const isChartMedia = el.closest("figure.chart") || el.classList.contains("cmh-chart");
    if (el.tagName === "IMG") {
      if (el.closest(".cm-skip") && !isChartMedia) return; // skip UI-chrome images
    } else { // CANVAS: only chart canvases are commentable media (never mermaid/diff surfaces).
      if (!isChartMedia) return;
      if (el.closest(".cm-mermaid-host") || el.closest(".cmh-diff-host")) return;
    }
    const i = imageEls.length;
    el.classList.add("cm-img-commentable");
    el.dataset.cmImageIndex = String(i);
    if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
    if (el.tagName === "IMG") {
      const alt = (el.getAttribute("alt") || "").trim();
      el.setAttribute("aria-label", (alt ? alt + " - " : "Image - ") + "press Enter to comment");
    }
    imageEls.push(el);
  });
}
function findImageEl(index) {
  if (!/^\d+$/.test(String(index))) return null;
  return imageEls[index] || root.querySelector(`[data-cm-image-index="${index}"]`) || null;
}
function imageInfo(img) {
  const i = parseInt(img.dataset.cmImageIndex, 10) || 0;
  const isCanvas = img.tagName === "CANVAS";
  const alt = (img.getAttribute("alt") || img.getAttribute("aria-label") || "").replace(/[\r\n\t]+/g, " ").replace(/\s+/g, " ").trim();
  const src = (img.getAttribute("src") || "").replace(/[\r\n\t]+/g, " ").trim();
  const shortSrc = src.length > 120 ? src.slice(0, 117) + "..." : src;
  const kind = (isCanvas || img.closest("figure.chart") || img.classList.contains("cmh-chart")) ? "chart" : "image";
  const quote = alt || (isCanvas ? ("chart " + (i + 1)) : ("image: " + (shortSrc || "(no src)")));
  return { imageIndex: i, src, alt, quote, kind };
}
function applyImageHighlight(comment) {
  let img = findImageEl(comment.imageIndex);
  // If the document was re-ordered, relocate the image by its stored src.
  if ((!img || (comment.imageSrc && img.getAttribute("src") !== comment.imageSrc)) && comment.imageSrc) {
    const bySrc = imageEls.find(im => im.getAttribute("src") === comment.imageSrc);
    if (bySrc) img = bySrc;
  }
  if (!img) return false;
  // An image can carry several comments; track them all in data-cids and keep the
  // first in data-cid for backward-compatible selectors.
  img.classList.add("cm-img-hl");
  const cids = (img.getAttribute("data-cids") || "").split(/\s+/).filter(Boolean);
  if (!cids.includes(comment.id)) cids.push(comment.id);
  img.setAttribute("data-cids", cids.join(" "));
  img.setAttribute("data-cid", cids[0]);
  return true;
}
function _imgCids(im) {
  return (im.getAttribute("data-cids") || im.getAttribute("data-cid") || "").split(/\s+/).filter(Boolean);
}
function clearImageHighlight(id) {
  root.querySelectorAll("img.cm-img-hl, canvas.cm-img-hl").forEach(im => {
    const cids = _imgCids(im);
    const rest = cids.filter(c => c !== id);
    if (rest.length === cids.length) return;
    if (rest.length) {
      im.setAttribute("data-cids", rest.join(" "));
      im.setAttribute("data-cid", rest[0]);
    } else {
      im.classList.remove("cm-img-hl", "cm-img-active");
      im.removeAttribute("data-cid");
      im.removeAttribute("data-cids");
    }
  });
}
function flashImage(id) {
  const img = [...root.querySelectorAll("img.cm-img-hl, canvas.cm-img-hl")].find(im => _imgCids(im).includes(id));
  if (!img) return;
  img.classList.add("cm-img-active");
  setTimeout(() => img.classList.remove("cm-img-active"), 2200);
}
function positionImageAdd(img) {
  const rect = img.getBoundingClientRect();
  const visible = _clipAwareRect(img, rect);
  if (!visible) return false;
  const btnW = imageAddBtn.offsetWidth || 96;
  const btnH = imageAddBtn.offsetHeight || 26;
  const bounds = _floatingBounds(img);
  const left = visible.right - btnW - 6;
  const top = visible.top + 6;
  imageAddBtn.style.left = _clamp(left, bounds.left, bounds.right - btnW) + "px";
  imageAddBtn.style.top = _clamp(top, bounds.top, bounds.bottom - btnH) + "px";
  return true;
}
function showImageAddFor(img) {
  const rect = img.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return;
  pendingImage = imageInfo(img);
  imageAddBtn.title = pendingImage.kind === "chart" ? "Comment on this chart" : "Comment on this image";
  if (imageAddHideTimer) { clearTimeout(imageAddHideTimer); imageAddHideTimer = null; }
  imageAddBtn.hidden = false;
  if (!positionImageAdd(img)) { imageAddBtn.hidden = true; imageActiveEl = null; pendingImage = null; return; }
  _activeAdd = { el: img, btn: imageAddBtn, position: () => positionImageAdd(img), clear: () => { pendingImage = null; } };
}
function scheduleHideImageAdd() {
  if (imageAddHideTimer) clearTimeout(imageAddHideTimer);
  imageAddHideTimer = setTimeout(() => {
    if (!imageAddBtn.matches(":hover")) { imageAddBtn.hidden = true; imageActiveEl = null; pendingImage = null; }
  }, 220);
}
function openImageComposer(info) {
  return createComposerElement({ mode: "new-image", image: info });
}
function setupImageLayer() {
  if (!imageAddBtn) return;
  indexImages();
  imageEls.forEach(img => {
    if (!img._cmImgAttached) {
      img._cmImgAttached = true;
      img.addEventListener("mouseenter", () => { imageActiveEl = img; showImageAddFor(img); });
      img.addEventListener("mouseleave", scheduleHideImageAdd);
      img.addEventListener("focus", () => { imageActiveEl = img; showImageAddFor(img); });
      img.addEventListener("blur", scheduleHideImageAdd);
      img.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        pendingImage = null;
        imageAddBtn.hidden = true;
        imageActiveEl = null;
        openImageComposer(imageInfo(img));
      });
      img.addEventListener("click", () => {
        if (!img.classList.contains("cm-img-hl")) return;
        const id = img.getAttribute("data-cid");
        if (!id) return;
        openSidebar();
        const card = listEl.querySelector(`.cm-card[data-cid="${id}"]`);
        if (card) { card.scrollIntoView({ behavior: "smooth", block: "center" }); flashActive(id); }
        flashImage(id);
      });
    }
  });
  comments.forEach(c => { if (c.anchorType === "image") applyImageHighlight(c); });
}
if (imageAddBtn) {
  imageAddBtn.addEventListener("mouseenter", () => {
    if (imageAddHideTimer) { clearTimeout(imageAddHideTimer); imageAddHideTimer = null; }
  });
  imageAddBtn.addEventListener("mouseleave", scheduleHideImageAdd);
  imageAddBtn.addEventListener("click", () => {
    if (!pendingImage) return;
    const info = pendingImage;
    pendingImage = null;
    imageAddBtn.hidden = true;
    imageActiveEl = null;
    openImageComposer(info);
  });
}

