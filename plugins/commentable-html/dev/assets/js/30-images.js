/* ---------- Image comment layer ----------
   Makes any <img>, chart <canvas> or authored inline <svg> inside #commentRoot
   commentable. Each one is indexed in document order (imageIndex); hovering or
   keyboard-focusing it reveals a floating "+ comment" button, and the comment
   anchors by (imageIndex) with the src plus media metadata as a fallback key so
   it survives reload, Copy all, and Export as Shareable. This mirrors the
   mermaid-node layer: images carry no text offsets, so image comments are
   excluded from backfillContext / restoreHighlights. */
const imageEls = [];
// Memoized structural signatures, keyed by media element; rebuilt with the media index.
let imageSigCache = new WeakMap();
const imageAddBtn = document.getElementById("imageAddBtn");
// Every commentable media element that can carry an image ring. Shared by the clear and flash
// paths so a canvas or svg anchor is never left ringed after its comment is deleted.
const CMH_MEDIA_HL_SEL = "img.cm-img-hl, canvas.cm-img-hl, svg.cm-img-hl";
// Marks an aria-label this layer synthesized for an otherwise nameless inline <svg>, so the
// affordance hint is never mistaken for the author's label (the anchor metadata).
const CMH_SVG_AUTO_LABEL_ATTR = "data-cm-img-auto-label";
const CMH_SVG_AUTO_LABEL_TEXT = "Image - press Enter to comment";
// Ancestors whose activation owns the click: an icon inside one of these is chrome, not a figure.
const CMH_SVG_INTERACTIVE_ANCESTORS = "button, summary, label, [role='button'], [role='menuitem'],"
  + " [role='tab'], [role='option'], [role='switch'], [role='checkbox'], [role='treeitem']";
let pendingImage = null;
let imageAddHideTimer = null;
let imageActiveEl = null;
let chartTooltipEl = null;
let chartTooltipCanvas = null;
let chartResizeBound = false;
// Cap the number of y-axis gridline ticks so a tiny/zero data-cmh-chart-step (an attacker-
// controllable attribute) cannot drive an effectively unbounded synchronous tick loop and freeze
// the tab. Ordinary charts use a handful of ticks, far below this.
const MAX_CHART_TICKS = 100;

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
  // Derive ticks by a BOUNDED integer index so a tiny/zero step cannot loop unbounded: cap the
  // count at MAX_CHART_TICKS. Normal charts (a handful of ticks) are unaffected.
  const rawCount = config.step > 0 ? Math.floor((config.max + 0.0001) / config.step) : 0;
  const stepCount = Math.min(MAX_CHART_TICKS, Math.max(0, rawCount));
  for (let i = 0; i <= stepCount; i++) ticks.push(i * config.step);
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
  canvas._cmhChart = { points: renderedPoints, activeIndex: activeIndex == null ? -1 : activeIndex, width: width, height: height, dpr: dpr, tickCount: ticks.length };
  return true;
}
function setupInteractiveCharts() {
  const charts = Array.from(root.querySelectorAll(CMH_CHART_DATA_SEL));
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
      root.querySelectorAll(CMH_CHART_DATA_SEL).forEach(function (canvas) {
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

// Chart MEDIA: the chart FIGURE is matched ancestor-or-self (so an <img> inside a chart figure
// counts too), the `.cmh-chart` class is matched on the element itself, and a canvas the built-in
// renderer draws counts by its data attributes. Shared by the index pass and the anchor metadata so
// the two can never classify the same element differently.
function _isChartMedia(el) {
  if (!el) return false;
  return !!(el.closest(CMH_CHART_FIGURE_SEL) || el.matches(CMH_CHART_MARK_SEL)
    || el.matches(CMH_CHART_DATA_SEL));
}
// Inline SVG MEDIA: an authored <svg> figure is commentable exactly like an <img>, but plenty of
// SVG in a document must stay inert - UI chrome, a decorative icon, the icon inside a link or
// button, a rendered mermaid/diff surface, an SVG whose nodes the widget layer already makes
// commentable part by part, and an inner <svg> nested in an outer one (the outer node is the
// figure a reader means). `.cm-skip` is UNCONDITIONAL here (unlike the img/canvas paths, whose
// chart-media exception exists for the built-in canvas renderer): chrome inside a chart figure
// must never gain an affordance just because an ancestor is a chart.
const CMH_SVG_DECORATIVE_ROLES = ["presentation", "none"];
// Element children that only DEFINE graphics rather than draw them. An <svg> made only of these
// (the sprite-sheet / <symbol> idiom, often width=0 or display:none at the top of a document)
// paints nothing, so indexing it would add an invisible focus stop and shift every later
// imageIndex.
const CMH_SVG_NON_DRAWING = ["defs", "symbol", "style", "title", "desc", "metadata",
  "filter", "clippath", "mask", "lineargradient", "radialgradient", "pattern"];
function _isSvgNonDrawing(el) {
  const kids = el.children;
  if (!kids.length) return true;
  for (let i = 0; i < kids.length; i++) {
    if (CMH_SVG_NON_DRAWING.indexOf((kids[i].tagName || "").toLowerCase()) === -1) return false;
  }
  return true;
}
function _isSvgZeroSized(el) {
  const w = parseFloat(el.getAttribute("width"));
  const h = parseFloat(el.getAttribute("height"));
  return w === 0 || h === 0;
}
// An icon inside a link is chrome, but a link that wraps ONLY the graphic (the "click the figure
// to open it full size" pattern) is still a figure, and a linked <img> stays commentable too.
function _isSvgLinkIcon(el) {
  const link = el.closest("a[href], [role='link']");
  if (!link) return false;
  const own = el.textContent || "";
  const around = (link.textContent || "").replace(own, "");
  return around.replace(/\s+/g, "").length > 0;
}
function _isCommentableSvg(el) {
  if (el.closest(".cm-skip")) return false;
  if (el.closest(".cm-mermaid-host") || el.closest(".cmh-diff-host")) return false;
  if (el.closest('[aria-hidden="true"]')) return false;
  const role = (el.getAttribute("role") || "").trim().toLowerCase();
  if (CMH_SVG_DECORATIVE_ROLES.indexOf(role) !== -1) return false;
  if (el.parentElement && el.parentElement.closest("svg")) return false;
  // The widget layer owns labeled parts, but ONLY inside a [data-cm-widget]; a stray
  // [data-cm-part] with no widget ancestor is commentable by neither layer, so the whole
  // figure stays this layer's target.
  if (el.closest("[data-cm-widget]")
    && (el.closest("[data-cm-part]") || el.querySelector("[data-cm-part]"))) return false;
  if (el.closest(CMH_SVG_INTERACTIVE_ANCESTORS)) return false;
  if (_isSvgLinkIcon(el)) return false;
  if (_isSvgZeroSized(el)) return false;
  if (el.hasAttribute("hidden")) return false;
  if (el.style && el.style.display === "none") return false;
  if (_isSvgNonDrawing(el)) return false;
  return true;
}
// The AUTHOR's accessible name for an inline <svg>, in accessible-name order: aria-labelledby
// (resolved to the referenced elements' text), then aria-label, then a DIRECT-CHILD <title>
// (only a direct child names the svg, so a figure never borrows a nested shape's tooltip).
// An aria-label this layer synthesized for a nameless graphic is marked and never counts - that
// label is an affordance hint, not anchor metadata.
function _svgLabelledByText(el) {
  const ids = (el.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean);
  if (!ids.length) return "";
  const parts = [];
  ids.forEach((id) => {
    let ref = null;
    try { ref = document.getElementById(id); } catch (e) { ref = null; }
    if (ref) parts.push(ref.textContent || "");
  });
  return parts.join(" ");
}
function _svgAuthorLabel(el) {
  if (!el) return "";
  const own = el.querySelector(":scope > title");
  const title = own ? (own.textContent || "") : "";
  const labelledBy = _svgLabelledByText(el);
  const label = el.getAttribute("aria-label");
  // The marker only disqualifies the exact label this layer writes, so an author's own
  // aria-label still wins even on an element that carries (or forges) the marker.
  const synthesized = el.getAttribute(CMH_SVG_AUTO_LABEL_ATTR) === "1"
    && label === CMH_SVG_AUTO_LABEL_TEXT;
  return _imageOneLine(labelledBy || (synthesized ? "" : label) || title);
}
function indexImages() {
  imageEls.length = 0;
  imageSigCache = new WeakMap();
  root.querySelectorAll("img, canvas, svg").forEach((el) => {
    const tag = (el.tagName || "").toLowerCase();
    const isChartMedia = _isChartMedia(el);
    if (tag === "img") {
      if (el.closest(".cm-skip") && !isChartMedia) return; // skip UI-chrome images
    } else if (tag === "svg") {
      if (!_isCommentableSvg(el)) return;
    } else { // CANVAS: only chart canvases are commentable media (never mermaid/diff surfaces).
      if (!isChartMedia) return;
      if (el.closest(".cm-mermaid-host") || el.closest(".cmh-diff-host")) return;
    }
    const i = imageEls.length;
    el.classList.add("cm-img-commentable");
    el.dataset.cmImageIndex = String(i);
    if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
    if (tag === "img") {
      const alt = (el.getAttribute("alt") || "").trim();
      el.setAttribute("aria-label", (alt ? alt + " - " : "Image - ") + "press Enter to comment");
    } else if (tag === "svg") {
      if (!el.hasAttribute("role")) el.setAttribute("role", "img");
      // Never overwrite the author's aria-label/<title> - that text IS the anchor metadata this
      // layer resolves comments by. A graphic with neither would otherwise become a focus stop
      // with no accessible name, so name it and MARK the label as ours so it stays out of the
      // metadata.
      if (!_svgAuthorLabel(el)) {
        el.setAttribute("aria-label", CMH_SVG_AUTO_LABEL_TEXT);
        el.setAttribute(CMH_SVG_AUTO_LABEL_ATTR, "1");
      }
    }
    imageEls.push(el);
  });
}
function findImageEl(index) {
  if (!/^\d+$/.test(String(index))) return null;
  return imageEls[index] || root.querySelector(`[data-cm-image-index="${index}"]`) || null;
}
function _imageOneLine(value) {
  // Inert at the WRITE side: line separators (including NEL) and bidi controls are stripped here
  // so stored media metadata can never carry a line break or a direction override into a bundle
  // line, a card, or an export, whatever a downstream consumer forgets to re-sanitize.
  return String(value || "")
    .replace(/[\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/g, "")
    .replace(/[\r\n\t\u0085\u2028\u2029]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
function _imageElMeta(img, freshSig) {
  const tag = (img && img.tagName ? img.tagName : "").toLowerCase();
  const isCanvas = tag === "canvas";
  const isSvg = tag === "svg";
  const alt = isSvg
    ? _svgAuthorLabel(img)
    : _imageOneLine(img && (img.getAttribute("alt") || img.getAttribute("aria-label")));
  const src = _imageOneLine(img && img.getAttribute("src"));
  const kind = (isCanvas || _isChartMedia(img)) ? "chart" : "image";
  return { alt, src, kind, sig: _imageSig(img, freshSig) };
}
// A stable structural discriminator for media whose LABEL and SRC say nothing (an unlabeled inline
// <svg>, an unlabeled chart <canvas>): without it such a figure has no identity beyond its position,
// so shifting the document's media order silently moves the comment to a different figure.
// Everything the descriptor reads is AUTHORED - the tag, the author's `id`, an svg's viewBox and the
// shape of what it draws (each descendant's tag, its drawing attributes and its own short text), a
// canvas's chart data attributes, and the figure's caption - so it survives a reload, a re-render
// and a device-pixel-ratio change. Anything the RUNTIME writes is excluded, or the signature would
// disagree with itself: the synthesized aria-label, the cm-* classes and index attribute, a chart
// canvas's backing-store width/height, and any node this layer injects into authored markup (a
// restored text highlight, a diff-line mark, a composer preview - see CMH_SIG_RUNTIME_CLASSES).
// It is NOT a content hash of the document: outside the figure it reads only the caption (the one
// authored thing that tells two otherwise identical blank figures apart), never the prose around it.
// The parts are JSON-encoded rather than string-joined, so no value can impersonate a delimiter and
// make two different figures hash alike.
const CMH_SIG_MAX_NODES = 64;
const CMH_SIG_MAX_CAPTION = 120;
const CMH_SIG_MAX_TEXT = 40;
const CMH_SIG_SHAPE_ATTRS = ["d", "points", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r",
  "rx", "ry", "width", "height", "fill", "stroke", "stroke-width", "opacity", "transform", "offset",
  "viewBox", "href"];
// The EXACT classes this layer puts on a node it injects into authored markup. Matching a `cm-`
// PREFIX instead would drop an author's own `cm-`-named shape from the signature, quietly making
// the digest depend on their class naming.
const CMH_SIG_RUNTIME_CLASSES = ["cm-hl", "cm-hl-gap", "cm-preview", "cmh-dl-mark"];
function _sigRuntimeNode(el) {
  if (!el || !el.getAttribute) return true;
  if (el.hasAttribute("data-cid") || el.hasAttribute("data-cids")) return true;
  const cls = _imageOneLine(el.getAttribute("class")).split(" ");
  for (let i = 0; i < cls.length; i++) {
    if (CMH_SIG_RUNTIME_CLASSES.indexOf(cls[i]) !== -1) return true;
  }
  return false;
}
// A node's OWN text (its direct text children only, so a parent never restates its subtree): two
// otherwise identical charts whose <text> labels differ are different figures.
function _sigOwnText(node) {
  let text = "";
  const kids = node.childNodes || [];
  for (let i = 0; i < kids.length && text.length < CMH_SIG_MAX_TEXT; i++) {
    if (kids[i].nodeType === 3) text += kids[i].nodeValue || "";
  }
  return _imageOneLine(text).slice(0, CMH_SIG_MAX_TEXT);
}
function _sigShape(el) {
  const all = el.getElementsByTagName("*");
  const drawn = [];
  let count = 0;
  for (let i = 0; i < all.length; i++) {
    const node = all[i];
    if (_sigRuntimeNode(node)) continue;
    count++;
    if (drawn.length >= CMH_SIG_MAX_NODES) continue;
    const bits = [(node.tagName || "").toLowerCase(), _sigOwnText(node)];
    for (let a = 0; a < CMH_SIG_SHAPE_ATTRS.length; a++) {
      const name = CMH_SIG_SHAPE_ATTRS[a];
      if (node.hasAttribute(name)) bits.push(name, _imageOneLine(node.getAttribute(name)));
    }
    drawn.push(bits);
  }
  return [count, drawn];
}
function _sigChartData(el) {
  const attrs = el.attributes || [];
  const named = [];
  for (let i = 0; i < attrs.length; i++) {
    if (attrs[i].name.indexOf("data-cmh-chart") === 0) {
      named.push([attrs[i].name, _imageOneLine(attrs[i].value)]);
    }
  }
  return named.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
}
// The caption is the one AUTHORED thing that tells two otherwise identical unlabeled figures apart
// (two blank chart canvases, say). UI chrome inside it is excluded so the runtime cannot move it.
function _sigCaption(el) {
  const fig = el.closest ? el.closest("figure") : null;
  const cap = fig ? fig.querySelector("figcaption") : null;
  if (!cap) return "";
  let text = "";
  const walker = document.createTreeWalker(cap, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      return (n.parentElement && n.parentElement.closest(".cm-skip"))
        ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
    },
  });
  let n;
  while ((n = walker.nextNode()) && text.length < CMH_SIG_MAX_CAPTION) text += n.nodeValue || "";
  return _imageOneLine(text).slice(0, CMH_SIG_MAX_CAPTION);
}
function _imageSigParts(el) {
  const tag = (el.tagName || "").toLowerCase();
  const parts = [tag, _imageOneLine(el.getAttribute("id")), _sigCaption(el)];
  if (tag === "svg") {
    parts.push(_imageOneLine(el.getAttribute("viewBox")));
    parts.push(_sigShape(el));
  } else if (tag === "canvas") {
    parts.push(_sigChartData(el));
  }
  return parts;
}
// Resolution walks every media element for every unresolved comment, so the digest is memoized per
// element and dropped whenever the media index is rebuilt (see indexImages()). The WRITE path
// passes fresh=true: a signature about to be STORED must never come from a cache, since the caption
// it reads lives outside the element and a host script could have edited it since the index was
// built. A resolve may use the memo, and a stale one can only fail safe (the anchor goes
// unresolved), never re-attach the comment to a different figure.
function _imageSig(el, fresh) {
  if (!el || !el.tagName) return "";
  if (!fresh) {
    const cached = imageSigCache.get(el);
    if (cached !== undefined) return cached;
  }
  const descriptor = JSON.stringify(_imageSigParts(el));
  // FNV-1a, 32-bit: a short deterministic digest, not a security primitive.
  let hash = 0x811c9dc5;
  for (let i = 0; i < descriptor.length; i++) {
    hash ^= descriptor.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  const sig = hash.toString(36);
  imageSigCache.set(el, sig);
  return sig;
}
// A stored signature is only ever compared with one this runtime just computed, so anything that is
// not in that format (a poisoned or oversized value in a shared report) is treated as absent - the
// comment then resolves exactly like one saved before the field existed. Ours is a 32-bit FNV-1a
// digest rendered with toString(36), so only a CANONICAL uint32 base-36 value can be one of ours:
// too long, out of range, or carrying a leading zero all mean "not a digest we wrote".
const CMH_SIG_RE = /^[0-9a-z]{1,7}$/;
function _storedImageSig(comment) {
  const raw = _imageOneLine(comment && comment.imageSig);
  if (!CMH_SIG_RE.test(raw)) return "";
  const value = parseInt(raw, 36);
  if (!Number.isFinite(value) || value > 0xffffffff) return "";
  return value.toString(36) === raw ? raw : "";
}
// The signature only ever speaks when nothing else can: it BLOCKS the indexed anchor solely for a
// comment stored with neither a label nor a src (the case that has no other identity), so redrawing
// a still-labelled figure never orphans its comment.
function _imageSigDecides(comment) {
  if (!_storedImageSig(comment)) return false;
  return !_imageOneLine(comment.imageAlt) && !_imageOneLine(comment.imageSrc);
}
function _imageSigMatches(img, comment) {
  const sig = _storedImageSig(comment);
  if (!sig) return false;
  return _imageSig(img) === sig;
}
function _imageMismatch(img, comment) {
  if (!img) return true;
  const meta = _imageElMeta(img);
  const src = _imageOneLine(comment && comment.imageSrc);
  const alt = _imageOneLine(comment && comment.imageAlt);
  const kind = comment && comment.imageKind;
  const hasAlt = !!(comment && Object.prototype.hasOwnProperty.call(comment, "imageAlt"));
  // A STORED but empty imageSrc is metadata too, not "no opinion": an inline svg never has a src,
  // so an svg anchor must not silently match an <img> that does (the empty-src slot is what tells
  // the two media apart when neither carries a label).
  const hasSrc = !!(comment && Object.prototype.hasOwnProperty.call(comment, "imageSrc"));
  if (_imageSigDecides(comment) && !_imageSigMatches(img, comment)) return true;
  return !!((kind && meta.kind !== kind) || (hasSrc && meta.src !== src) || (hasAlt && meta.alt !== alt));
}

function _imageMatchesMeta(img, comment) {
  const meta = _imageElMeta(img);
  const src = _imageOneLine(comment && comment.imageSrc);
  const alt = _imageOneLine(comment && comment.imageAlt);
  const kind = comment && comment.imageKind;
  const hasAlt = !!(comment && Object.prototype.hasOwnProperty.call(comment, "imageAlt"));
  const hasSrc = !!(comment && Object.prototype.hasOwnProperty.call(comment, "imageSrc"));
  const bySig = _imageSigDecides(comment);
  if (bySig && meta.sig !== _storedImageSig(comment)) return false;
  if (kind && meta.kind !== kind) return false;
  if (hasSrc && meta.src !== src) return false;
  if (hasAlt && meta.alt !== alt) return false;
  return !!(kind || hasSrc || hasAlt || bySig);
}
function resolveImageEl(comment) {
  let img = findImageEl(comment && comment.imageIndex);
  const src = _imageOneLine(comment && comment.imageSrc);
  const kind = comment && comment.imageKind;
  if (_imageMismatch(img, comment)) {
    // Only an UNAMBIGUOUS metadata match may re-anchor the comment: media with no distinguishing
    // metadata (an unlabeled inline svg has no src at all) must leave the anchor unresolved
    // rather than silently attach the note to a different figure.
    const byMeta = imageEls.filter(im => _imageMatchesMeta(im, comment));
    if (byMeta.length === 1) return byMeta[0];
    // Otherwise-equal candidates (two figures sharing one label) are separated by the stored
    // structural signature; it can only ever NARROW an already-ambiguous set, so a comment saved
    // before the signature existed still resolves exactly as it did.
    if (byMeta.length > 1) {
      const bySig = byMeta.filter(im => _imageSigMatches(im, comment));
      return bySig.length === 1 ? bySig[0] : null;
    }
    const bySrc = src ? imageEls.filter(im => {
      const meta = _imageElMeta(im);
      return meta.src === src && (!kind || meta.kind === kind);
    }) : [];
    img = bySrc.length === 1 ? bySrc[0] : null;
  }
  return img;
}
function imageInfo(img) {
  const i = parseInt(img.dataset.cmImageIndex, 10) || 0;
  // The write path recomputes the signature rather than trusting the memo (see _imageSig).
  const meta = _imageElMeta(img, true);
  const isSvg = (img.tagName || "").toLowerCase() === "svg";
  const alt = meta.alt;
  const src = meta.src;
  const shortSrc = src.length > 120 ? src.slice(0, 117) + "..." : src;
  const kind = meta.kind;
  // The fallback quote follows the stored KIND, not the tag, so a chart svg and a chart canvas
  // are both pinned "chart N" while a plain graphic (which has no src to name) reads "image N".
  const quote = alt
    || (kind === "chart" ? ("chart " + (i + 1))
      : isSvg ? ("image " + (i + 1))
        : ("image: " + (shortSrc || "(no src)")));
  return { imageIndex: i, src, alt, quote, kind, sig: meta.sig };
}
function applyImageHighlight(comment) {
  const img = resolveImageEl(comment);
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
  root.querySelectorAll(CMH_MEDIA_HL_SEL).forEach(im => {
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
  const img = [...root.querySelectorAll(CMH_MEDIA_HL_SEL)].find(im => _imgCids(im).includes(id));
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
