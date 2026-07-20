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
    ["inline-flex item", "display: inline-flex"],
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
});
