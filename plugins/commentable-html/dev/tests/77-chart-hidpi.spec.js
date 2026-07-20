import { test, expect } from "@playwright/test";
import fs from "fs";
import { fileUrl, ready, stageContent, denyExternalNetwork } from "./helpers.js";

// CMH-CHART-10 (issue #501): a STANDALONE canvas.cmh-chart (not inside the shipped
// figure.chart > .chart-wrap, which has a definite width) placed directly in a shrink-to-fit
// container (width: max-content, an inline-block, a float, or an auto-sized flex/grid item) used to
// size its bitmap from its own clientWidth. On a HiDPI screen (devicePixelRatio > 1) the bitmap is
// clientWidth * dpr, which - because the canvas is width:100% and the container's width is driven by
// the canvas's own (bitmap) intrinsic size - inflates the container, so the chart stabilizes
// displayed at dpr x its intended size. The fix measures the intended size against a bitmap reset to
// the authored (dpr-independent, aspect-preserving) size and pins the box so the dpr-scaled bitmap
// cannot stretch it.

test.describe("chart HiDPI shrink-to-fit sizing", () => {
  const points = '[{"label":"A","value":10},{"label":"B","value":24},{"label":"C","value":16}]';
  const ATTR_W = 760;
  const ATTR_H = 340;

  async function openStandaloneChart(browser, containerStyle) {
    const context = await browser.newContext({ deviceScaleFactor: 2, viewport: { width: 1200, height: 900 } });
    const page = await context.newPage();
    await denyExternalNetwork(page);
    const content =
      '<section><h2>Metrics</h2><p>Lead-in prose.</p>'
      + '<div id="shrink" style="' + containerStyle + '">'
      + '<canvas id="chart" class="cmh-chart" width="' + ATTR_W + '" height="' + ATTR_H + '" role="img" aria-label="Chart"'
      + " data-cmh-chart-points='" + points + "'></canvas>"
      + "</div></section>";
    const { dir, html } = stageContent(content, { key: "cmh-chart-hidpi", source: "chart-hidpi.html" });
    await page.goto(fileUrl(html));
    await ready(page);
    return { context, page, dir };
  }

  const readChart = (page) => page.evaluate(() => {
    const c = document.getElementById("chart");
    return {
      clientWidth: c.clientWidth,
      clientHeight: c.clientHeight,
      bitmap: c.width,
      bitmapHeight: c.height,
      dpr: window.devicePixelRatio || 1,
    };
  });

  // A shrink-to-fit container pins the chart to its authored size; the four container kinds below all
  // drive their width from the canvas's own intrinsic size, so all used to feed the HiDPI loop.
  for (const [label, style] of [
    ["max-content", "width: max-content"],
    ["inline-block", "display: inline-block"],
    ["float", "float: left"],
    ["inline-flex", "display: inline-flex"],
  ]) {
    test(`CMH-CHART-10: a standalone chart in a ${label} container renders at its authored size on HiDPI (dpr 2)`, async ({ browser }) => {
      const { context, page, dir } = await openStandaloneChart(browser, style);
      try {
        const dpr = await page.evaluate(() => window.devicePixelRatio || 1);
        expect(dpr).toBe(2); // guard the premise: this test only means something on HiDPI

        const m = await readChart(page);
        // Renders at its authored (760x340) size, not dpr x (1520) it.
        expect(Math.abs(m.clientWidth - ATTR_W)).toBeLessThanOrEqual(2);
        expect(Math.abs(m.clientHeight - ATTR_H)).toBeLessThanOrEqual(2);
        // The correct-render invariant: the backing bitmap is exactly dpr x the displayed CSS box
        // (a chart stretched by the feedback loop has bitmap == clientWidth, i.e. bitmap/dpr == half).
        expect(Math.abs(m.bitmap / m.dpr - m.clientWidth)).toBeLessThanOrEqual(2);
        expect(Math.abs(m.bitmapHeight / m.dpr - m.clientHeight)).toBeLessThanOrEqual(2);

        // Stability: a re-render (the window-resize path already re-draws every chart) must not grow
        // it a further dpr step - it stays at its intended size.
        await page.evaluate(() => window.dispatchEvent(new Event("resize")));
        await expect
          .poll(() => page.evaluate(() => {
            const c = document.getElementById("chart");
            const d = window.devicePixelRatio || 1;
            return Math.abs(c.width / d - c.clientWidth);
          }), { timeout: 3000 })
          .toBeLessThanOrEqual(2);
        const m2 = await readChart(page);
        expect(Math.abs(m2.clientWidth - ATTR_W)).toBeLessThanOrEqual(2);
      } finally {
        await context.close();
        fs.rmSync(dir, { recursive: true, force: true });
      }
    });
  }

  // A DEFINITE-width but AUTO-height standalone chart must keep its aspect ratio (not go square): the
  // fix measures against the authored bitmap, not a 1x1 one, so the auto height stays proportional.
  test("CMH-CHART-10: a definite-width auto-height standalone chart keeps its aspect ratio on HiDPI (dpr 2)", async ({ browser }) => {
    const { context, page, dir } = await openStandaloneChart(browser, "width: 800px"); // definite width, auto height
    try {
      expect(await page.evaluate(() => window.devicePixelRatio || 1)).toBe(2);
      const m = await readChart(page);
      // Fills the 800px container width; height stays proportional to the authored 760x340 aspect
      // (~358), NOT squared to ~800 and NOT stretched dpr x.
      expect(Math.abs(m.clientWidth - 800)).toBeLessThanOrEqual(2);
      const proportional = Math.round(800 * ATTR_H / ATTR_W); // ~358
      expect(Math.abs(m.clientHeight - proportional)).toBeLessThanOrEqual(4);
      expect(Math.abs(m.bitmap / m.dpr - m.clientWidth)).toBeLessThanOrEqual(2);
      expect(Math.abs(m.bitmapHeight / m.dpr - m.clientHeight)).toBeLessThanOrEqual(2);
    } finally {
      await context.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  // Pin lifecycle through the reveal path: a standalone shrink-to-fit chart authored inside a section
  // that is collapsed (display:none) at load measures 0 and must NOT be pinned while hidden; the reveal
  // ResizeObserver then renders it, and it must settle pinned at its authored size (not dpr x, not
  // stuck at the collapsed fallback) and stay stable across a resize.
  test("CMH-CHART-10: a standalone shrink-to-fit chart revealed from a collapsed section pins to its authored size (dpr 2)", async ({ browser }) => {
    const context = await browser.newContext({ deviceScaleFactor: 2, viewport: { width: 1200, height: 900 } });
    const page = await context.newPage();
    await denyExternalNetwork(page);
    const content =
      '<section><h2>Intro</h2><p>Lead-in prose so the column has width.</p></section>'
      + '<section class="cmh-section-collapsed" id="sec-chart"><h2>Metrics</h2>'
      + '<div id="shrink" style="width: max-content">'
      + '<canvas id="chart" class="cmh-chart" width="' + ATTR_W + '" height="' + ATTR_H + '" role="img" aria-label="Chart"'
      + " data-cmh-chart-points='" + points + "'></canvas>"
      + "</div></section>";
    const { dir, html } = stageContent(content, { key: "cmh-chart-hidpi-reveal", source: "chart-hidpi-reveal.html" });
    try {
      await page.goto(fileUrl(html));
      await ready(page);
      // While collapsed: measured 0 -> authored fallback, and NOT pinned (you must not pin while hidden).
      const collapsed = await page.evaluate(() => {
        const c = document.getElementById("chart");
        return { clientWidth: c.clientWidth, pinnedW: !!c._cmhPinnedW, bitmap: c.width, dpr: window.devicePixelRatio || 1 };
      });
      expect(collapsed.clientWidth).toBe(0);
      expect(collapsed.pinnedW).toBe(false);
      expect(collapsed.bitmap).toBe(Math.round(ATTR_W * collapsed.dpr));

      await page.locator("#sec-chart .cmh-sec-caret").click();
      await expect(page.locator("#sec-chart")).not.toHaveClass(/cmh-section-collapsed/);

      // On reveal it settles pinned at the authored size, bitmap == dpr x css, stable across a resize.
      await expect
        .poll(() => page.evaluate(() => {
          const c = document.getElementById("chart");
          const d = window.devicePixelRatio || 1;
          return Math.abs(c.width / d - c.clientWidth);
        }), { timeout: 5000 })
        .toBeLessThanOrEqual(2);
      const after = await readChart(page);
      expect(Math.abs(after.clientWidth - ATTR_W)).toBeLessThanOrEqual(2);
      await page.evaluate(() => window.dispatchEvent(new Event("resize")));
      const m2 = await readChart(page);
      expect(Math.abs(m2.clientWidth - ATTR_W)).toBeLessThanOrEqual(2);
      expect(Math.abs(m2.bitmap / m2.dpr - m2.clientWidth)).toBeLessThanOrEqual(2);
    } finally {
      await context.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  // A hover redraw must NOT re-measure/re-size the bitmap (measure=false reuses the cached size), yet
  // must still update the active point/tooltip. Guards both the hover cost optimization and that the
  // interactive hit-test still works after it.
  test("CMH-CHART-10: hovering a chart updates the active point without resizing the bitmap", async ({ browser }) => {
    const { context, page, dir } = await openStandaloneChart(browser, "width: max-content");
    try {
      const before = await page.evaluate(() => {
        const c = document.getElementById("chart");
        return { bitmap: c.width, bitmapHeight: c.height, clientWidth: c.clientWidth };
      });
      // Hover across the plot area to land on a bar/point.
      const box = await page.locator("#chart").boundingBox();
      await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.6);
      await expect
        .poll(() => page.evaluate(() => {
          const c = document.getElementById("chart");
          return c._cmhChart ? c._cmhChart.activeIndex : -1;
        }), { timeout: 3000 })
        .toBeGreaterThanOrEqual(0);
      // The bitmap and CSS box are unchanged by the hover redraw (no re-measure/resize on hover).
      const after = await page.evaluate(() => {
        const c = document.getElementById("chart");
        return { bitmap: c.width, bitmapHeight: c.height, clientWidth: c.clientWidth };
      });
      expect(after.bitmap).toBe(before.bitmap);
      expect(after.bitmapHeight).toBe(before.bitmapHeight);
      expect(after.clientWidth).toBe(before.clientWidth);
    } finally {
      await context.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
