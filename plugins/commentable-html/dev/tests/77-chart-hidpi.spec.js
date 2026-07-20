import { test, expect } from "@playwright/test";
import fs from "fs";
import { fileUrl, ready, stageContent, denyExternalNetwork } from "./helpers.js";

// CMH-CHART-10 (issue #501): a STANDALONE canvas.cmh-chart (not inside the shipped
// figure.chart > .chart-wrap, which has a definite width) placed directly in a shrink-to-fit
// container (width: max-content, an inline-block, a float, or an auto-sized flex/grid item) used to
// size its bitmap from its own clientWidth. On a HiDPI screen (devicePixelRatio > 1) the bitmap is
// clientWidth * dpr, which - because the canvas is width:100% and the container's width is driven by
// the canvas's own (bitmap) intrinsic size - inflates the container, so the chart stabilizes
// displayed at dpr x its intended size. The fix measures the intended size against a neutralized
// bitmap and pins the canvas box so the dpr-scaled bitmap cannot stretch it.

test.describe("chart HiDPI shrink-to-fit sizing", () => {
  const points = '[{"label":"A","value":10},{"label":"B","value":24},{"label":"C","value":16}]';

  async function openStandaloneChart(browser, containerStyle) {
    const context = await browser.newContext({ deviceScaleFactor: 2, viewport: { width: 1200, height: 900 } });
    const page = await context.newPage();
    await denyExternalNetwork(page);
    const content =
      '<section><h2>Metrics</h2><p>Lead-in prose.</p>'
      + '<div id="shrink" style="' + containerStyle + '">'
      + '<canvas id="chart" class="cmh-chart" width="760" height="340" role="img" aria-label="Chart"'
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

  // width: max-content is the canonical shrink-to-fit container from the issue's repro.
  test("CMH-CHART-10: a standalone chart in a max-content container renders at intended size on HiDPI (dpr 2)", async ({ browser }) => {
    const { context, page, dir } = await openStandaloneChart(browser, "width: max-content");
    try {
      const dpr = await page.evaluate(() => window.devicePixelRatio || 1);
      expect(dpr).toBe(2); // guard the premise: this test only means something on HiDPI

      const m = await readChart(page);
      // Renders at its intended (~760) CSS size, not dpr x (1520) it.
      expect(m.clientWidth).toBeGreaterThan(600);
      expect(m.clientWidth).toBeLessThan(900);
      expect(m.clientHeight).toBeGreaterThan(280);
      expect(m.clientHeight).toBeLessThan(400);
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
          const dpr = window.devicePixelRatio || 1;
          return Math.abs(c.width / dpr - c.clientWidth);
        }), { timeout: 3000 })
        .toBeLessThanOrEqual(2);
      const m2 = await readChart(page);
      expect(Math.abs(m2.clientWidth - m.clientWidth)).toBeLessThanOrEqual(2);
    } finally {
      await context.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  // display: inline-block is another shrink-to-fit context that drove the same feedback.
  test("CMH-CHART-10: a standalone chart in an inline-block container renders at intended size on HiDPI (dpr 2)", async ({ browser }) => {
    const { context, page, dir } = await openStandaloneChart(browser, "display: inline-block");
    try {
      const m = await readChart(page);
      expect(m.clientWidth).toBeGreaterThan(600);
      expect(m.clientWidth).toBeLessThan(900);
      expect(Math.abs(m.bitmap / m.dpr - m.clientWidth)).toBeLessThanOrEqual(2);
    } finally {
      await context.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
