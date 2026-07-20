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
let chartTooltipEl = null;
let chartTooltipCanvas = null;
let chartResizeBound = false;

function _chartColors(canvas) {
  const rootStyle = getComputedStyle(document.documentElement);
  const canvasStyle = getComputedStyle(canvas);
  return {
    text: canvas.getAttribute("data-cmh-chart-text") || canvasStyle.color || rootStyle.getPropertyValue("--cp-text").trim() || "#1b1f3b",
    axis: canvas.getAttribute("data-cmh-chart-axis") || rootStyle.getPropertyValue("--cp-border-strong").trim() || "#cbb48a",
    grid: canvas.getAttribute("data-cmh-chart-grid") || rootStyle.getPropertyValue("--cp-border").trim() || "#dedede",
    accent: canvas.getAttribute("data-cmh-chart-accent") || rootStyle.getPropertyValue("--cp-accent").trim() || "#b11f4b",
    background: canvas.getAttribute("data-cmh-chart-background") || "#ffffff",
  };
}
function _chartStep(max) {
  if (!Number.isFinite(max) || max <= 0) return 1;
  const rough = max / 4;
  const pow = Math.pow(10, Math.floor(Math.log10(rough || 1)));
  const unit = rough / pow;
  const nice = unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10;
  return nice * pow;
}
function _chartConfig(canvas) {
  const sourceId = (canvas.getAttribute("data-cmh-chart-source") || "").trim();
  let source = null;
  if (sourceId) {
    const el = document.getElementById(sourceId);
    if (el) {
      try { source = JSON.parse((el.textContent || "").trim() || "null"); }
      catch (e) { console.warn("Could not parse chart data source #" + sourceId + ":", e); return null; }
    }
  }
  if (!source) {
    const raw = canvas.getAttribute("data-cmh-chart-points");
    if (!raw) return null;
    try { source = { points: JSON.parse(raw) }; }
    catch (e) { console.warn("Could not parse inline chart data:", e); return null; }
  }
  const parsed = Array.isArray(source) ? source : source.points;
  if (!Array.isArray(parsed) || !parsed.length) return null;
  const points = parsed.map(function (point, index) {
    const label = point && typeof point.label === "string" ? point.label.trim() : "";
    const value = Number(point && point.value);
    if (!label || !Number.isFinite(value)) return null;
    return {
      label: label,
      value: value,
      fill: point && typeof point.fill === "string" && point.fill.trim() ? point.fill.trim() : (index === 1 ? "#b11f4b" : "#e08aa4"),
    };
  }).filter(Boolean);
  if (!points.length) return null;
  const attrMax = Number(source.max != null ? source.max : canvas.getAttribute("data-cmh-chart-max"));
  const max = Number.isFinite(attrMax) && attrMax > 0 ? attrMax : Math.max.apply(null, points.map(function (point) { return point.value; }));
  const attrStep = Number(source.step != null ? source.step : canvas.getAttribute("data-cmh-chart-step"));
  const unit = String(source.unit != null ? source.unit : (canvas.getAttribute("data-cmh-chart-unit") || "")).trim();
  const tooltipUnit = String(source.tooltipUnit != null ? source.tooltipUnit : (canvas.getAttribute("data-cmh-chart-tooltip-unit") || unit)).trim();
  return {
    points: points,
    max: max,
    step: Number.isFinite(attrStep) && attrStep > 0 ? attrStep : _chartStep(max),
    unit: unit,
    tooltipUnit: tooltipUnit,
    colors: _chartColors(canvas),
  };
}
function _chartTooltip() {
  if (!chartTooltipEl) {
    chartTooltipEl = document.createElement("div");
    chartTooltipEl.className = "cm-tooltip cmh-chart-tooltip cm-skip";
    chartTooltipEl.setAttribute("role", "tooltip");
    document.body.appendChild(chartTooltipEl);
  }
  return chartTooltipEl;
}
function hideChartTooltip() {
  chartTooltipCanvas = null;
  if (chartTooltipEl) chartTooltipEl.classList.remove("is-visible", "below");
}
function _showChartTooltip(canvas, point) {
  const tip = _chartTooltip();
  const rect = canvas.getBoundingClientRect();
  const leftAtPoint = rect.left + point.x;
  const topAtPoint = rect.top + point.top;
  chartTooltipCanvas = canvas;
  tip.textContent = point.tooltip;
  tip.classList.remove("below");
  tip.style.visibility = "hidden";
  tip.classList.add("is-visible");
  const tipWidth = tip.offsetWidth;
  const tipHeight = tip.offsetHeight;
  let left = leftAtPoint - tipWidth / 2;
  let top = topAtPoint - tipHeight - 12;
  if (top < 8) {
    top = rect.top + point.bottom + 12;
    tip.classList.add("below");
  }
  left = Math.max(8, Math.min(left, window.innerWidth - tipWidth - 8));
  top = Math.max(8, Math.min(top, window.innerHeight - tipHeight - 8));
  tip.style.left = left + "px";
  tip.style.top = top + "px";
  tip.style.setProperty("--cm-tip-arrow", Math.max(10, Math.min(tipWidth - 10, leftAtPoint - left)) + "px");
  tip.style.visibility = "";
}
function _chartHit(state, x, y) {
  if (!state || !state.points) return null;
  return state.points.find(function (point) {
    return x >= point.left && x <= point.right && y >= point.top && y <= point.bottom;
  }) || null;
}
function _chartSetHover(canvas, point) {
  const state = canvas._cmhChart;
  const nextIndex = point ? point.index : -1;
  if (state && state.activeIndex === nextIndex) {
    if (point) _showChartTooltip(canvas, point);
    return;
  }
  renderInteractiveChart(canvas, nextIndex, false);
  if (point) _showChartTooltip(canvas, canvas._cmhChart.points[nextIndex]);
  else hideChartTooltip();
}
function _chartEventPoint(canvas, event) {
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  return {
    x: (event.clientX - rect.left) * ((canvas._cmhChart && canvas._cmhChart.width) || rect.width) / rect.width,
    y: (event.clientY - rect.top) * ((canvas._cmhChart && canvas._cmhChart.height) || rect.height) / rect.height,
  };
}
// Size a chart canvas's backing bitmap for the current devicePixelRatio and return its logical CSS
// size (the coordinate space all the drawing below uses). The bitmap is dpr x the CSS box so the
// chart stays crisp on HiDPI. The measurement is taken against a bitmap reset to the AUTHORED size -
// which is devicePixelRatio-independent, so a shrink-to-fit container (whose width is otherwise driven
// by the canvas's own dpr-scaled bitmap) is not inflated by the previous render's bitmap (the #501
// HiDPI feedback loop) - while preserving the intrinsic aspect ratio so an auto-height canvas is not
// squared. If such a container then stretches the canvas past its logical CSS size, the box is pinned
// so the chart displays at its intended size; a definite-width ancestor (the shipped figure.chart >
// .chart-wrap) is unaffected and is never pinned. A collapsed section (display:none) measures 0 and
// falls back to the authored width/height attributes (CMH-CHART-09). The authored attributes are
// captured once, before any bitmap write, because setting canvas.width/height reflects onto those
// content attributes and would otherwise drift each render.
// Clear a size pin the runtime set on one axis, restoring whatever inline declaration was there
// before. It only reclaims the pin when the current inline declaration is STILL exactly the one the
// runtime set - if author code changed style.width/height after the pin, that value is left alone and
// the runtime relinquishes ownership.
function _clearChartAxisPin(canvas, prop, pinKey, savedValKey, savedPriKey, pinnedKey) {
  if (!canvas[pinnedKey]) return;
  if (canvas.style.getPropertyValue(prop) === canvas[pinKey] && canvas.style.getPropertyPriority(prop) === "important") {
    if (canvas[savedValKey]) canvas.style.setProperty(prop, canvas[savedValKey], canvas[savedPriKey]);
    else canvas.style.removeProperty(prop);
  }
  canvas[pinnedKey] = false;
}
function _sizeChartCanvas(canvas, dpr) {
  if (canvas._cmhAttrW == null) {
    canvas._cmhAttrW = Math.max(1, Math.round(Number(canvas.getAttribute("width")) || canvas.width || 760));
    canvas._cmhAttrH = Math.max(1, Math.round(Number(canvas.getAttribute("height")) || canvas.height || 340));
    // Remember the author's own inline width/height (value + priority), captured before the runtime
    // ever pins, so clearing a pin restores exactly what was there rather than deleting it.
    canvas._cmhInlineW = canvas.style.getPropertyValue("width");
    canvas._cmhInlineWPri = canvas.style.getPropertyPriority("width");
    canvas._cmhInlineH = canvas.style.getPropertyValue("height");
    canvas._cmhInlineHPri = canvas.style.getPropertyPriority("height");
  }
  // Clear only a pin WE set on a prior render (per axis), so the measurement reflects the current
  // layout without clobbering an author's own inline width/height on an axis we never pinned.
  _clearChartAxisPin(canvas, "width", "_cmhPinW", "_cmhInlineW", "_cmhInlineWPri", "_cmhPinnedW");
  _clearChartAxisPin(canvas, "height", "_cmhPinH", "_cmhInlineH", "_cmhInlineHPri", "_cmhPinnedH");
  canvas.width = canvas._cmhAttrW;
  canvas.height = canvas._cmhAttrH;
  let width = canvas.clientWidth;
  let height = canvas.clientHeight;
  if (!(width > 0)) width = canvas._cmhAttrW;
  if (!(height > 0)) height = canvas._cmhAttrH;
  width = Math.max(1, Math.round(width));
  height = Math.max(1, Math.round(height));
  canvas.width = Math.max(1, Math.round(width * dpr));
  canvas.height = Math.max(1, Math.round(height * dpr));
  if (canvas.clientWidth > width + 1) { canvas._cmhPinW = width + "px"; canvas.style.setProperty("width", canvas._cmhPinW, "important"); canvas._cmhPinnedW = true; }
  if (canvas.clientHeight > height + 1) { canvas._cmhPinH = height + "px"; canvas.style.setProperty("height", canvas._cmhPinH, "important"); canvas._cmhPinnedH = true; }
  return { width: width, height: height };
}
function renderInteractiveChart(canvas, activeIndex, measure) {
  const config = _chartConfig(canvas);
  if (!config) return false;
  const dpr = window.devicePixelRatio || 1;
  // Re-measure/re-size the bitmap only on layout renders (setup, reveal, window resize). A hover
  // redraw (measure === false) reuses the cached logical size and the existing bitmap, so it does not
  // force the neutralize/measure reflows on every mousemove over a chart - but only while the cached
  // size is for the current devicePixelRatio (a dpr change re-measures so the bitmap is not stale).
  const size = (measure === false && canvas._cmhChart && canvas._cmhChart.dpr === dpr)
    ? { width: canvas._cmhChart.width, height: canvas._cmhChart.height }
    : _sizeChartCanvas(canvas, dpr);
  const width = size.width;
  const height = size.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return false;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = config.colors.background;
  ctx.fillRect(0, 0, width, height);
  const pad = { top: 26, right: 28, bottom: 54, left: 62 };
  const plotWidth = Math.max(10, width - pad.left - pad.right);
  const plotHeight = Math.max(10, height - pad.top - pad.bottom);
  const startY = pad.top + plotHeight;
  const ticks = [];
  for (let tick = 0; tick <= config.max + 0.0001; tick += config.step) ticks.push(tick);
  if (ticks[ticks.length - 1] !== config.max) ticks.push(config.max);
  ctx.strokeStyle = config.colors.axis;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(pad.left, pad.top);
  ctx.lineTo(pad.left, startY);
  ctx.lineTo(width - pad.right, startY);
  ctx.stroke();
  ctx.font = "16px Segoe UI, sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  ticks.forEach(function (tick) {
    const y = startY - (tick / config.max) * plotHeight;
    ctx.strokeStyle = tick === 0 ? config.colors.axis : config.colors.grid;
    ctx.lineWidth = tick === 0 ? 2 : 1;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    ctx.fillStyle = config.colors.text;
    ctx.fillText(String(tick), pad.left - 10, y);
  });
  const gap = Math.max(18, Math.min(36, plotWidth * 0.08));
  const barWidth = Math.max(34, Math.min(92, (plotWidth - gap * (config.points.length - 1)) / config.points.length));
  const used = barWidth * config.points.length + gap * (config.points.length - 1);
  const startX = pad.left + Math.max(0, (plotWidth - used) / 2);
  const renderedPoints = config.points.map(function (point, index) {
    const x = startX + index * (barWidth + gap);
    const barHeight = Math.max(0, (point.value / config.max) * plotHeight);
    const top = startY - barHeight;
    ctx.fillStyle = point.fill;
    ctx.fillRect(x, top, barWidth, barHeight);
    if (activeIndex === index) {
      ctx.strokeStyle = config.colors.accent;
      ctx.lineWidth = 3;
      ctx.strokeRect(x - 1.5, top - 1.5, barWidth + 3, barHeight + 3);
    }
    ctx.fillStyle = config.colors.text;
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.font = "bold 20px Segoe UI, sans-serif";
    ctx.fillText(point.value + (config.unit ? " " + config.unit.replace(/^\/?\s*/, "") : ""), x + barWidth / 2, Math.max(18, top - 8));
    ctx.textBaseline = "top";
    ctx.font = "18px Segoe UI, sans-serif";
    ctx.fillText(point.label, x + barWidth / 2, startY + 12);
    return {
      index: index,
      label: point.label,
      value: point.value,
      tooltip: point.label + ": " + point.value + (config.tooltipUnit ? " " + config.tooltipUnit : ""),
      left: x,
      right: x + barWidth,
      top: top,
      bottom: startY,
      x: x + barWidth / 2,
      y: top + Math.max(10, barHeight * 0.35),
      width: barWidth,
      height: barHeight,
    };
  });
  canvas._cmhChart = { points: renderedPoints, activeIndex: activeIndex == null ? -1 : activeIndex, width: width, height: height, dpr: dpr };
  return true;
}
function setupInteractiveCharts() {
  const charts = Array.from(root.querySelectorAll("canvas.cmh-chart[data-cmh-chart-points], canvas.cmh-chart[data-cmh-chart-source], figure.chart canvas[data-cmh-chart-points], figure.chart canvas[data-cmh-chart-source]"));
  charts.forEach(function (canvas) {
    renderInteractiveChart(canvas, canvas._cmhChart ? canvas._cmhChart.activeIndex : -1);
    if (canvas._cmhChartBound) return;
    canvas._cmhChartBound = true;
    canvas.addEventListener("mousemove", function (event) {
      const point = _chartEventPoint(canvas, event);
      _chartSetHover(canvas, point && _chartHit(canvas._cmhChart, point.x, point.y));
    });
    canvas.addEventListener("mouseleave", function () {
      if (chartTooltipCanvas === canvas) hideChartTooltip();
      _chartSetHover(canvas, null);
    });
    canvas.addEventListener("blur", function () {
      if (chartTooltipCanvas === canvas) hideChartTooltip();
      _chartSetHover(canvas, null);
    });
  });
  if (!chartResizeBound) {
    chartResizeBound = true;
    window.addEventListener("resize", function () {
      root.querySelectorAll("canvas[data-cmh-chart-points], canvas[data-cmh-chart-source]").forEach(function (canvas) {
        renderInteractiveChart(canvas, canvas._cmhChart ? canvas._cmhChart.activeIndex : -1);
      });
      if (chartTooltipCanvas && chartTooltipCanvas._cmhChart && chartTooltipCanvas._cmhChart.activeIndex >= 0) {
        const point = chartTooltipCanvas._cmhChart.points[chartTooltipCanvas._cmhChart.activeIndex];
        if (point) _showChartTooltip(chartTooltipCanvas, point);
      }
    });
    window.addEventListener("scroll", hideChartTooltip, true);
  }
  // A chart drawn while its section was collapsed (display:none) read clientWidth 0 and fell back to
  // the width attribute (760), so its bitmap is wrong for the real column width and looks blurry once
  // revealed - and a window resize was the only thing that re-drew it. Re-render each chart ONCE when
  // its section is revealed, i.e. when its box goes from zero-size to a real size (mirrors the Mermaid
  // width-class ResizeObserver in 20-mermaid.js). This is a one-shot reveal hook, not a perpetual
  // size mirror: re-rendering on every size change would, for a standalone canvas.cmh-chart in a
  // shrink-to-fit container on a HiDPI screen, keep enlarging the bitmap (each render sets the bitmap
  // from clientWidth, which in a shrink-to-fit box tracks the bitmap) and never settle. Genuine window
  // resizes of an already-visible chart are handled by the resize listener above.
  if (typeof ResizeObserver === "function") {
    if (setupInteractiveCharts._revealObs) setupInteractiveCharts._revealObs.disconnect();
    const obs = new ResizeObserver(function (entries) {
      entries.forEach(function (entry) {
        const canvas = entry.target;
        if (Math.round(canvas.clientWidth) === 0) { canvas._cmhWasHidden = true; return; }
        if (!canvas._cmhWasHidden) return; // already visible; the reveal has been handled
        canvas._cmhWasHidden = false;
        renderInteractiveChart(canvas, canvas._cmhChart ? canvas._cmhChart.activeIndex : -1);
        if (chartTooltipCanvas === canvas && canvas._cmhChart && canvas._cmhChart.activeIndex >= 0) {
          const point = canvas._cmhChart.points[canvas._cmhChart.activeIndex];
          if (point) _showChartTooltip(canvas, point);
        }
      });
    });
    charts.forEach(function (canvas) {
      // Arm synchronously from the current visibility so a reveal that lands before the observer's
      // first (async) delivery is still handled: if that initial callback arrives already non-zero,
      // _cmhWasHidden is set and the reveal re-render still fires.
      if (Math.round(canvas.clientWidth) === 0) canvas._cmhWasHidden = true;
      obs.observe(canvas);
    });
    setupInteractiveCharts._revealObs = obs;
  }
}

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
  setActiveAdd({ el: img, btn: imageAddBtn, position: () => positionImageAdd(img), clear: () => { pendingImage = null; } });
}
function scheduleHideImageAdd() {
  if (imageAddHideTimer) clearTimeout(imageAddHideTimer);
  imageAddHideTimer = setTimeout(() => {
    if (!imageAddBtn.matches(":hover")) { imageAddBtn.hidden = true; imageActiveEl = null; pendingImage = null; clearActiveAdd(imageAddBtn); }
  }, 220);
}
function openImageComposer(info) {
  return createComposerElement({ mode: "new-image", image: info });
}
function setupImageLayer() {
  if (!imageAddBtn) return;
  setupInteractiveCharts();
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
        if (card) { card.scrollIntoView({ behavior: cmScrollBehavior(), block: "center" }); flashActive(id); }
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
