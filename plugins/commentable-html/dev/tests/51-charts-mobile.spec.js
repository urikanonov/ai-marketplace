import { test, expect } from "@playwright/test";
import path from "path";
import fs from "fs";
import { SKILL, fileUrl, ready, stageContent, routeMermaidLocal, startStaticServer, denyExternalNetwork } from "./helpers.js";

const METRICS = path.join(SKILL, "..", "..", "examples", "report-metrics.html");

test.use({ viewport: { width: 380, height: 820 } });

test("charts and mermaid blocks are contained in the mobile content column (CMH-RESP-01)", async ({ page }) => {
  await page.goto(fileUrl(METRICS));
  await ready(page);

  const result = await page.evaluate(() => {
    const root = document.getElementById("commentRoot");
    const viewportWidth = document.documentElement.clientWidth;
    const rootRect = root.getBoundingClientRect();
    const metrics = (el) => {
      const prior = el.scrollLeft;
      el.scrollLeft = 0;
      el.scrollLeft = 24;
      const scrolled = el.scrollLeft > 0;
      el.scrollLeft = prior;
      const overflowX = getComputedStyle(el).overflowX;
      return {
        overflowX,
        fits: el.getBoundingClientRect().right <= viewportWidth + 1,
        wide: el.scrollWidth > el.clientWidth + 1,
        canScroll: ["auto", "scroll"].includes(overflowX) && scrolled,
      };
    };
    const mermaid = [...root.querySelectorAll("pre.mermaid")].map(metrics);
    const charts = [...root.querySelectorAll("figure.chart")].map(metrics);
    return {
      rootFits: rootRect.left >= -1 && rootRect.right <= viewportWidth + 1,
      mermaid,
      charts,
    };
  });

  expect(result.rootFits, "#commentRoot stays inside the viewport").toBe(true);
  expect(result.mermaid.length, "fixture has mermaid diagrams").toBeGreaterThan(0);
  expect(result.charts.length, "fixture has chart figures").toBeGreaterThan(0);
  const richBlocks = [...result.mermaid, ...result.charts];
  const wideBlocks = richBlocks.filter((item) => item.wide);
  expect(wideBlocks.length, "fixture has at least one genuinely wide rich block").toBeGreaterThan(0);
  expect(wideBlocks.some((item) => item.canScroll), "a wide rich block can scroll horizontally").toBe(true);
  for (const item of richBlocks) {
    expect(item.fits, "block box stays inside the viewport").toBe(true);
    expect(["auto", "scroll"], "wide rich content scrolls inside its own block").toContain(item.overflowX);
  }
});

test("chart add buttons stay inside the chart scroll container on mobile (CMH-RESP-02)", async ({ page }) => {
  const staged = stageContent(`
<h1>Wide chart</h1>
<figure class="chart" id="wideChartFigure">
  <div class="chart-wrap cm-skip" style="min-width: 960px; height: 220px;">
    <canvas id="wideChartCanvas" width="960" height="220" role="img" aria-label="Wide chart for clipping"></canvas>
  </div>
  <figcaption>Wide chart with horizontal scrolling.</figcaption>
</figure>`, { key: "cmh-chart-button-clipping", source: "chart-button-clipping.html" });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await page.locator("#wideChartCanvas").hover({ position: { x: 40, y: 40 } });
    await expect(page.locator("#imageAddBtn")).toBeVisible();

    const metrics = await page.evaluate(() => {
      const figure = document.getElementById("wideChartFigure").getBoundingClientRect();
      const button = document.getElementById("imageAddBtn").getBoundingClientRect();
      return {
        figureLeft: figure.left,
        figureRight: figure.right,
        buttonLeft: button.left,
        buttonRight: button.right,
      };
    });
    expect(metrics.buttonLeft).toBeGreaterThanOrEqual(metrics.figureLeft - 1);
    expect(metrics.buttonRight).toBeLessThanOrEqual(metrics.figureRight + 1);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

// F25 regression: a highlight bubble and the floating Add buttons are clip-aware. When the
// annotation target scrolls fully OUT of a horizontal-overflow container they hide (instead of
// floating at a stale viewport position), and when the target is only PARTLY visible the floating
// element is clamped inside the container. Reverting the clip logic (_clipAwareRect /
// _floatingBounds) turns these red: the pre-fix code only tested the viewport, so a target clipped
// by its container but still inside the viewport kept the bubble/button visible and mispositioned.
test("the highlight bubble hides and clamps to a horizontal-overflow clip container across container types (CMH-RESP-02)", async ({ page }) => {
  const staged = stageContent(`<h1>Clip containers</h1><p id="anchor">Anchor paragraph.</p>`,
    { key: "cmh-hl-clip", source: "hl-clip.html" });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);

    // Each clip-container selector recognized by _clipContainersFor. .cmh-diff-raw is the inert raw
    // diff block (no per-line commenting), so it is exercised via the highlight bubble like the rest.
    // BOTH mermaid host shapes are covered: the runtime treats `pre.mermaid` and `div.mermaid` alike
    // everywhere else, so a document that authors its diagrams as `div.mermaid` must clip the same
    // (issue #769 - the fallback recognized only the `pre` form).
    const types = [
      { tag: "table", cls: "" },
      { tag: "figure", cls: "chart" },
      { tag: "pre", cls: "mermaid" },
      { tag: "div", cls: "mermaid" },
      { tag: "div", cls: "cmh-diff-raw" },
    ];

    for (const t of types) {
      const label = t.tag + (t.cls ? "." + t.cls : "");

      const hide = await page.evaluate(({ tag, cls }) => {
        const root = document.getElementById("commentRoot");
        root.querySelectorAll(".cmh-cov-clip").forEach((n) => n.remove());
        const c = document.createElement(tag);
        c.className = "cmh-cov-clip" + (cls ? " " + cls : "");
        c.setAttribute("style", "display:block;overflow-x:auto;width:160px;margin-left:140px;white-space:nowrap;");
        const inner = '<mark class="cm-hl" data-cid="cov-hide">HL</mark>' +
          '<span style="display:inline-block;width:800px;"></span>';
        c.innerHTML = tag === "table" ? "<tbody><tr><td>" + inner + "</td></tr></tbody>" : inner;
        root.appendChild(c);
        const mark = c.querySelector("mark.cm-hl");
        mark.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
        const bubble = document.getElementById("hlBubble");
        const shown = !bubble.hidden;
        const cRect = c.getBoundingClientRect();
        const m0 = mark.getBoundingClientRect();
        // Scroll the mark fully left of the container box, but keep it inside the viewport.
        c.scrollLeft = (m0.right - cRect.left) + 30;
        window.dispatchEvent(new Event("scroll"));
        const m1 = mark.getBoundingClientRect();
        const c1 = c.getBoundingClientRect();
        const res = {
          shown,
          markInViewport: m1.right > 4 && m1.left < window.innerWidth - 4,
          markLeftOfContainer: m1.right <= c1.left,
          hiddenAfterScroll: bubble.hidden,
        };
        c.remove();
        return res;
      }, t);
      expect(hide.shown, `${label}: bubble shows while the mark is visible`).toBe(true);
      expect(hide.markInViewport, `${label}: scrolled mark stays inside the viewport`).toBe(true);
      expect(hide.markLeftOfContainer, `${label}: scrolled mark is clipped out of the container box`).toBe(true);
      expect(hide.hiddenAfterScroll, `${label}: bubble hides once the mark is clipped out of the container`).toBe(true);

      const clamp = await page.evaluate(({ tag, cls }) => {
        const root = document.getElementById("commentRoot");
        root.querySelectorAll(".cmh-cov-clip").forEach((n) => n.remove());
        const c = document.createElement(tag);
        c.className = "cmh-cov-clip" + (cls ? " " + cls : "");
        c.setAttribute("style", "display:block;overflow-x:auto;width:160px;margin-left:40px;white-space:nowrap;");
        const inner = '<span style="display:inline-block;width:120px;"></span>' +
          '<mark class="cm-hl" data-cid="cov-clamp" style="display:inline-block;width:90px;">HL</mark>' +
          '<span style="display:inline-block;width:800px;"></span>';
        c.innerHTML = tag === "table" ? "<tbody><tr><td>" + inner + "</td></tr></tbody>" : inner;
        root.appendChild(c);
        const mark = c.querySelector("mark.cm-hl");
        mark.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
        const bubble = document.getElementById("hlBubble");
        const cRect = c.getBoundingClientRect();
        const mRect = mark.getBoundingClientRect();
        const bRect = bubble.getBoundingClientRect();
        const res = {
          hidden: bubble.hidden,
          straddles: mRect.left < cRect.right && mRect.right > cRect.right,
          bubbleLeft: bRect.left,
          bubbleRight: bRect.right,
          containerLeft: cRect.left,
          containerRight: cRect.right,
        };
        c.remove();
        return res;
      }, t);
      expect(clamp.hidden, `${label}: bubble stays visible while the mark is partly in view`).toBe(false);
      expect(clamp.straddles, `${label}: mark straddles the container right edge`).toBe(true);
      expect(clamp.bubbleLeft, `${label}: bubble left stays inside the container`).toBeGreaterThanOrEqual(clamp.containerLeft - 1);
      expect(clamp.bubbleRight, `${label}: bubble right stays inside the container`).toBeLessThanOrEqual(clamp.containerRight + 1);
    }
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("the chart Add button clamps inside a narrow chart container on horizontal overflow (CMH-RESP-02)", async ({ page }) => {
  // A narrow chart container (narrower than the viewport) whose canvas overflows horizontally.
  // With the clip fix the Add button clamps to the container; the pre-fix code clamped only to the
  // viewport, so the button landed well to the right of the narrow figure.
  const staged = stageContent(`
<h1>Narrow wide chart</h1>
<figure class="chart" id="narrowChartFigure" style="width: 180px; overflow-x: auto; margin: 0;">
  <div class="chart-wrap cm-skip" style="width: 900px; height: 200px;">
    <canvas id="narrowChartCanvas" width="900" height="200" role="img" aria-label="Narrow wide chart for clamping"></canvas>
  </div>
  <figcaption>Narrow chart with horizontal scrolling.</figcaption>
</figure>`, { key: "cmh-narrow-chart-clamp", source: "narrow-chart-clamp.html" });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await page.locator("#narrowChartCanvas").hover({ position: { x: 40, y: 40 } });
    await expect(page.locator("#imageAddBtn")).toBeVisible();

    const metrics = await page.evaluate(() => {
      const figure = document.getElementById("narrowChartFigure").getBoundingClientRect();
      const button = document.getElementById("imageAddBtn").getBoundingClientRect();
      return {
        figureLeft: figure.left,
        figureRight: figure.right,
        buttonLeft: button.left,
        buttonRight: button.right,
        narrowerThanViewport: figure.right < window.innerWidth - 40,
      };
    });
    expect(metrics.narrowerThanViewport, "the chart figure is narrower than the viewport").toBe(true);
    expect(metrics.buttonLeft).toBeGreaterThanOrEqual(metrics.figureLeft - 1);
    expect(metrics.buttonRight).toBeLessThanOrEqual(metrics.figureRight + 1);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

// Issue #769: the clip-container resolver recognized a standalone `pre.mermaid` host but not a standalone
// `div.mermaid` one, even though the runtime treats both as diagram hosts everywhere else - so in a
// document that authors its diagrams as `div.mermaid` the floating whole-diagram control escaped the
// host's clipping/scrolling box. Both shapes are staged with IDENTICAL markup, so this is a parity
// assertion: whatever holds for `pre.mermaid` must hold for `div.mermaid`. The rendered SVG is inlined
// rather than produced by mermaid, so the case is hermetic and deterministic - the runtime treats a
// host whose SVG carries painted nodes as rendered.
const RENDERED_SVG = '<svg width="900" height="120" viewBox="0 0 900 120" style="width:900px">'
  + '<g class="node"><rect x="10" y="10" width="140" height="60"></rect><text x="20" y="46">A</text></g>'
  + '<g class="node"><rect x="750" y="10" width="140" height="60"></rect><text x="760" y="46">B</text></g>'
  + "</svg>";
const CLIP_HOST_STYLE = "display:block;width:300px;max-width:300px;height:60px;overflow:auto;margin:0;padding:0;";

test("the whole-diagram button clamps inside a standalone div.mermaid host exactly as inside a pre.mermaid one (CMH-RESP-02)", async ({ page }) => {
  const staged = stageContent(
    "<h1>Standalone diagram hosts</h1>"
    + `<pre class="mermaid" id="preHost" style="${CLIP_HOST_STYLE}">${RENDERED_SVG}</pre>`
    + `<div class="mermaid" id="divHost" style="${CLIP_HOST_STYLE}">${RENDERED_SVG}</div>`,
    { key: "cmh-standalone-mermaid-clip", source: "standalone-mermaid-clip.html" });
  try {
    // The mermaid loader in the shell fires for any diagram host; block the network so the vendored
    // library never loads and the staged pre-rendered SVG is the exact thing measured.
    await denyExternalNetwork(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);

    const btn = page.locator("#mermaidAddBtn");
    for (const sel of ["#preHost", "#divHost"]) {
      const host = page.locator(sel);
      await expect(host).toHaveAttribute("data-cmh-comment-a11y", "1", { timeout: 10000 });
      // Scroll the host on BOTH axes before revealing the button, so the diagram overflows its box in
      // both directions and each axis of the clamp is genuinely exercised (with the host at scroll 0
      // the diagram's top edge coincides with the box's, and the vertical assertions would hold even
      // with no clipping at all).
      await host.evaluate((h) => { h.scrollLeft = 120; h.scrollTop = 40; });
      // The button is a single shared element that survives the previous iteration, so drop it first
      // (blur whatever is focused, not this host, which is not focused yet): otherwise a `#divHost`
      // focus handler that never fired would still be measured as a pass on the stale `#preHost`
      // placement.
      await page.evaluate(() => { const a = document.activeElement; if (a && a.blur) a.blur(); });
      await expect(btn).toBeHidden();
      // Focusing the host is the deterministic whole-diagram affordance (it reveals the same floating
      // button an empty-area hover does), so the measurement never depends on pointer coordinates.
      await host.focus();
      await expect(btn).toBeVisible();
      await expect(btn).toHaveText(/diagram/i);

      const m = await page.evaluate((s) => {
        const h = document.querySelector(s);
        const b = document.getElementById("mermaidAddBtn").getBoundingClientRect();
        const r = h.getBoundingClientRect();
        const svg = h.querySelector("svg").getBoundingClientRect();
        return {
          overflowsX: h.scrollWidth > h.clientWidth + 1,
          overflowsY: h.scrollHeight > h.clientHeight + 1,
          // The diagram really does extend past the box on both axes at this scroll offset, so a
          // clip-unaware placement lands outside the host.
          svgEscapes: svg.right > r.right + 1 && svg.top < r.top - 1,
          fitsButton: r.width > b.width && r.height > b.height,
          bLeft: b.left, bRight: b.right, bTop: b.top, bBottom: b.bottom,
          hLeft: r.left, hRight: r.right, hTop: r.top, hBottom: r.bottom,
        };
      }, sel);
      expect(m.overflowsX, `${sel}: the diagram genuinely overflows its host box horizontally`).toBe(true);
      expect(m.overflowsY, `${sel}: the diagram genuinely overflows its host box vertically`).toBe(true);
      expect(m.svgEscapes, `${sel}: the scrolled diagram extends past the host box on both axes`).toBe(true);
      expect(m.fitsButton, `${sel}: the host is big enough to hold the button`).toBe(true);
      expect(m.bLeft, `${sel}: button left stays inside the host`).toBeGreaterThanOrEqual(m.hLeft - 2);
      expect(m.bRight, `${sel}: button right stays inside the host`).toBeLessThanOrEqual(m.hRight + 2);
      expect(m.bTop, `${sel}: button top stays inside the host`).toBeGreaterThanOrEqual(m.hTop - 2);
      expect(m.bBottom, `${sel}: button bottom stays inside the host`).toBeLessThanOrEqual(m.hBottom + 2);
    }
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

// Issue #823: a clip container nested INSIDE another clip container used to shadow it. The resolver
// took the FIRST `closest()` match and intersected that one rect, so a diagram host inside a
// scrolling table wrapper (CMH-RESP-11) or inside a `figure.chart` bounded the floating control to
// the INNER box alone: once the OUTER box scrolled the target out of view the control stayed
// visible over unrelated content, and while the target was only partly visible the control was
// clamped to a box that reaches past the outer one. Every case asserts that the target is still
// fully inside the INNER host, so the nearest container alone explains none of the behaviour - the
// outer box is the only thing that can - which is exactly what made these red before the fix.
const NEST_OUTER_STYLE = "display:block;box-sizing:border-box;width:160px;margin:0 0 0 140px;"
  + "padding:0;border:0;overflow-x:auto;white-space:nowrap;";
const NEST_INNER_STYLE = "display:inline-block;overflow:hidden;margin:0;padding:0;vertical-align:top;"
  // The layer caps a diagram host at `max-width:100%` (70-kql.css), which inside the narrow outer
  // box would shrink the inner host to the outer one and collapse the nesting under test.
  + "max-width:none;";
// The runtime wraps every author table in a `.cmh-table-scroll` box and leaves an existing wrapper
// alone (61-table-scroll.js), so authoring the wrapper here produces exactly the shipped shape while
// keeping the geometry of the test under control.
function nestedClipMarkup(outer, inner) {
  if (outer === "table") {
    return `<div class="cmh-table-scroll cmh-nest-outer" style="${NEST_OUTER_STYLE}">`
      + '<table style="margin:0;border:0;border-collapse:collapse;width:auto;"><tbody><tr>'
      + `<td style="padding:0;border:0;white-space:nowrap;">${inner}</td>`
      + "</tr></tbody></table></div>";
  }
  return `<figure class="chart cmh-nest-outer" style="${NEST_OUTER_STYLE}">${inner}</figure>`;
}
const NEST_HIDE_INNER = `<div class="mermaid cmh-nest-inner" style="${NEST_INNER_STYLE}width:150px;">`
  + '<span style="display:inline-block;width:110px;"></span>'
  + '<mark class="cm-hl" data-cid="nest-hide" style="display:inline-block;width:30px;">HL</mark>'
  + "</div><span style=\"display:inline-block;width:800px;\"></span>";
const NEST_CLAMP_INNER = `<div class="mermaid cmh-nest-inner" style="${NEST_INNER_STYLE}width:320px;">`
  + '<span style="display:inline-block;width:120px;"></span>'
  + '<mark class="cm-hl" data-cid="nest-clamp" style="display:inline-block;width:90px;">HL</mark>'
  + "</div><span style=\"display:inline-block;width:800px;\"></span>";

test("a floating control honours the WHOLE chain of nested clip containers, not just the nearest (CMH-RESP-12)", async ({ page }) => {
  const staged = stageContent("<h1>Nested clip containers</h1><p id=\"anchor\">Anchor paragraph.</p>",
    { key: "cmh-nested-clip", source: "nested-clip.html" });
  try {
    await denyExternalNetwork(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);

    for (const outer of ["table", "figure.chart"]) {
      const hide = await page.evaluate((markup) => {
        const root = document.getElementById("commentRoot");
        root.querySelectorAll(".cmh-nest-outer").forEach((n) => n.remove());
        root.insertAdjacentHTML("beforeend", markup);
        const box = root.querySelector(".cmh-nest-outer");
        const host = box.querySelector(".cmh-nest-inner");
        const mark = box.querySelector("mark.cm-hl");
        mark.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
        const bubble = document.getElementById("hlBubble");
        const shown = !bubble.hidden;
        // Scroll the OUTER box until the mark sits just left of it, still on screen and still
        // wholly inside the inner diagram host.
        const m0 = mark.getBoundingClientRect();
        box.scrollLeft = (m0.right - box.getBoundingClientRect().left) + 12;
        window.dispatchEvent(new Event("scroll"));
        const m1 = mark.getBoundingClientRect();
        const b1 = box.getBoundingClientRect();
        const h1 = host.getBoundingClientRect();
        const res = {
          shown,
          markInViewport: m1.right > 4 && m1.left < window.innerWidth - 4,
          markInsideInnerHost: m1.left >= h1.left - 1 && m1.right <= h1.right + 1,
          markLeftOfOuter: m1.right <= b1.left,
          hiddenAfterScroll: bubble.hidden,
        };
        box.remove();
        return res;
      }, nestedClipMarkup(outer, NEST_HIDE_INNER));
      expect(hide.shown, `${outer}: bubble shows while the mark is visible`).toBe(true);
      expect(hide.markInViewport, `${outer}: the scrolled mark stays inside the viewport`).toBe(true);
      expect(hide.markInsideInnerHost, `${outer}: the mark is still wholly inside the INNER diagram host`).toBe(true);
      expect(hide.markLeftOfOuter, `${outer}: the mark is scrolled out of the OUTER container box`).toBe(true);
      expect(hide.hiddenAfterScroll, `${outer}: bubble hides once the OUTER container clips the mark away`).toBe(true);

      const clamp = await page.evaluate((markup) => {
        const root = document.getElementById("commentRoot");
        root.querySelectorAll(".cmh-nest-outer").forEach((n) => n.remove());
        root.insertAdjacentHTML("beforeend", markup);
        const box = root.querySelector(".cmh-nest-outer");
        const host = box.querySelector(".cmh-nest-inner");
        const mark = box.querySelector("mark.cm-hl");
        mark.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
        const bubble = document.getElementById("hlBubble");
        const bRect = bubble.getBoundingClientRect();
        const mRect = mark.getBoundingClientRect();
        const boxRect = box.getBoundingClientRect();
        const hRect = host.getBoundingClientRect();
        const res = {
          hidden: bubble.hidden,
          straddles: mRect.left < boxRect.right && mRect.right > boxRect.right,
          markInsideInnerHost: mRect.left >= hRect.left - 1 && mRect.right <= hRect.right + 1,
          innerEscapesOuter: hRect.right > boxRect.right + 1,
          fitsBubble: boxRect.width > bRect.width,
          bubbleLeft: bRect.left,
          bubbleRight: bRect.right,
          outerLeft: boxRect.left,
          outerRight: boxRect.right,
        };
        box.remove();
        return res;
      }, nestedClipMarkup(outer, NEST_CLAMP_INNER));
      expect(clamp.hidden, `${outer}: bubble stays visible while the mark is partly in view`).toBe(false);
      expect(clamp.straddles, `${outer}: the mark straddles the OUTER container's right edge`).toBe(true);
      expect(clamp.markInsideInnerHost, `${outer}: the mark is wholly inside the INNER diagram host`).toBe(true);
      expect(clamp.innerEscapesOuter, `${outer}: the inner host really does reach past the outer box`).toBe(true);
      expect(clamp.fitsBubble, `${outer}: the outer box is wide enough to hold the bubble`).toBe(true);
      expect(clamp.bubbleLeft, `${outer}: bubble left stays inside the OUTER container`).toBeGreaterThanOrEqual(clamp.outerLeft - 1);
      expect(clamp.bubbleRight, `${outer}: bubble right stays inside the OUTER container`).toBeLessThanOrEqual(clamp.outerRight + 1);
    }
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

// Honouring the whole chain only helps if every box in it really clips. A gallery card's inner
// `pre.mermaid` ships `overflow:visible` and grows to the diagram it holds, and an author can set
// `overflow:visible` on any recognised container - bounding a control by a box its content plainly
// spills out of would be a NEW defect introduced by counting more boxes. `display:contents`
// generates no box at all, so its empty rect would hide every control inside it.
test("a recognised container that does not clip does not bound the control (CMH-RESP-12)", async ({ page }) => {
  const staged = stageContent("<h1>Non-clipping ancestors</h1><p id=\"anchor\">Anchor paragraph.</p>",
    { key: "cmh-nonclip-chain", source: "nonclip-chain.html" });
  try {
    await denyExternalNetwork(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);

    for (const outerOverflow of ["visible", "contents"]) {
      const style = outerOverflow === "contents"
        ? "display:contents;"
        : "display:block;box-sizing:border-box;width:160px;margin:0 0 0 140px;padding:0;border:0;overflow:visible;white-space:nowrap;";
      const markup = `<figure class="chart cmh-nest-outer" style="${style}">${NEST_CLAMP_INNER}</figure>`;
      const m = await page.evaluate((html) => {
        const root = document.getElementById("commentRoot");
        root.querySelectorAll(".cmh-nest-outer").forEach((n) => n.remove());
        root.insertAdjacentHTML("beforeend", html);
        const box = root.querySelector(".cmh-nest-outer");
        const host = box.querySelector(".cmh-nest-inner");
        const mark = box.querySelector("mark.cm-hl");
        mark.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
        const bubble = document.getElementById("hlBubble");
        const bRect = bubble.getBoundingClientRect();
        const boxRect = box.getBoundingClientRect();
        const hRect = host.getBoundingClientRect();
        const mRect = mark.getBoundingClientRect();
        const res = {
          hidden: bubble.hidden,
          markEscapesOuter: mRect.right > boxRect.right + 1,
          bubbleEscapesOuter: bRect.right > boxRect.right + 1,
          bubbleLeft: bRect.left,
          bubbleRight: bRect.right,
          hostLeft: hRect.left,
          hostRight: hRect.right,
        };
        box.remove();
        return res;
      }, markup);
      expect(m.hidden, `outer overflow ${outerOverflow}: the bubble stays visible for a plainly visible mark`).toBe(false);
      if (outerOverflow === "visible") {
        expect(m.markEscapesOuter, `outer overflow ${outerOverflow}: the mark really does spill out of the outer box`).toBe(true);
        expect(m.bubbleEscapesOuter, `outer overflow ${outerOverflow}: the bubble is NOT clamped to a box that does not clip`).toBe(true);
      }
      expect(m.bubbleLeft, `outer overflow ${outerOverflow}: bubble left stays inside the box that DOES clip`).toBeGreaterThanOrEqual(m.hostLeft - 1);
      expect(m.bubbleRight, `outer overflow ${outerOverflow}: bubble right stays inside the box that DOES clip`).toBeLessThanOrEqual(m.hostRight + 1);
    }
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

// The clipping box the test above clamps to only exists because the layer's own stylesheet makes a
// diagram host a scroll box. That rule named only `pre.mermaid`, so a document that authors its
// diagrams as `div.mermaid` got no box at all and the parity above would hold only for a host the
// AUTHOR styled. This pins the CSS half: an unstyled host of either shape is the same scroll box.
test("an unstyled div.mermaid host is the same scrolling box as a pre.mermaid one (CMH-RESP-09)", async ({ page }) => {
  const staged = stageContent(
    "<h1>Unstyled diagram hosts</h1>"
    + `<pre class="mermaid" id="barePre">${RENDERED_SVG}</pre>`
    + `<div class="mermaid" id="bareDiv">${RENDERED_SVG}</div>`,
    { key: "cmh-bare-mermaid-box", source: "bare-mermaid-box.html" });
  try {
    await denyExternalNetwork(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);

    const m = await page.evaluate(() => ["#barePre", "#bareDiv"].map((s) => {
      const h = document.querySelector(s);
      const r = h.getBoundingClientRect();
      return {
        sel: s,
        overflowX: getComputedStyle(h).overflowX,
        scrolls: h.scrollWidth > h.clientWidth + 1,
        fitsViewport: r.right <= document.documentElement.clientWidth + 1,
      };
    }));
    for (const host of m) {
      expect(["auto", "scroll"], `${host.sel}: the host is its own horizontal scroll box`).toContain(host.overflowX);
      expect(host.scrolls, `${host.sel}: a wide diagram scrolls inside the host`).toBe(true);
      expect(host.fitsViewport, `${host.sel}: the host box stays inside the viewport`).toBe(true);
    }
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("small mermaid diagrams fit while genuinely wide ones scroll with an edge fade (CMH-RESP-09)", async ({ page }) => {
  const staged = stageContent(`
<h1>Diagram widths</h1>
<pre class="mermaid" id="smallDiagram">
flowchart LR
  A[Start] --> B[Done]
</pre>
<pre class="mermaid" id="wideDiagram">
flowchart LR
  A[Ingest] --> B[Normalize] --> C[Enrich] --> D[Correlate] --> E[Score] --> F[Route] --> G[Notify] --> H[Archive]
  A --> I[Backfill] --> J[Replay] --> K[Compare] --> L[Publish]
</pre>`, { key: "cmh-mermaid-width-classifier", source: "mermaid-width-classifier.html" });
  const server = await startStaticServer(staged.dir);
  try {
    await routeMermaidLocal(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await page.waitForSelector("#smallDiagram svg");
    await page.waitForSelector("#wideDiagram svg");
    await expect.poll(() => page.locator("#wideDiagram").evaluate((el) => el.classList.contains("cmh-diagram-wide"))).toBe(true);

    const metrics = await page.evaluate(() => {
      const measure = (id) => {
        const host = document.getElementById(id);
        const box = host.getBoundingClientRect();
        return {
          wide: host.classList.contains("cmh-diagram-wide"),
          fade: host.classList.contains("cmh-diagram-scroll-fade"),
          maskImage: getComputedStyle(host).maskImage || "",
          webkitMaskImage: getComputedStyle(host).webkitMaskImage || "",
          fits: box.right <= document.documentElement.clientWidth + 1,
          delta: host.scrollWidth - host.clientWidth,
        };
      };
      return { small: measure("smallDiagram"), wide: measure("wideDiagram") };
    });
    expect(metrics.small.fits, "the small diagram host stays inside the viewport").toBe(true);
    expect(metrics.small.wide, "the small diagram is not force-classified wide").toBe(false);
    expect(metrics.small.delta, "the small diagram does not need horizontal scrolling").toBeLessThanOrEqual(1);
    expect(metrics.wide.fits, "the wide diagram host stays inside the viewport").toBe(true);
    expect(metrics.wide.wide, "the wide diagram keeps a legible scroll width").toBe(true);
    expect(metrics.wide.delta, "the wide diagram scrolls horizontally").toBeGreaterThan(40);
    expect(metrics.wide.fade, "scrollable diagrams carry the edge-fade cue class").toBe(true);
    expect(metrics.wide.maskImage, "the unprefixed edge-fade mask is active").toContain("gradient");
    expect(metrics.wide.webkitMaskImage, "the webkit edge-fade mask is active").toContain("gradient");
  } finally {
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});
