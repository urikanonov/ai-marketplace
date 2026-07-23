import { test, expect } from "@playwright/test";
import fs from "fs";
import { fileUrl, ready, stageContent, denyExternalNetwork } from "./helpers.js";

// CMH-CHART-11 (issue #619): the interactive chart's y-axis tick loop derived the tick list by
// repeatedly adding data-cmh-chart-step (an attacker-controllable attribute). A tiny positive step
// against a large max produced an effectively unbounded synchronous loop that froze the tab during
// startup. The fix derives the ticks by a BOUNDED integer index (capped at MAX_CHART_TICKS), so a
// pathological step can never freeze the page; the rendered tick count is exposed on
// canvas._cmhChart.tickCount for this test.

test.describe("chart tick-count cap", () => {
  const points = '[{"label":"A","value":10},{"label":"B","value":24},{"label":"C","value":16}]';

  async function openChart(browser, extraAttrs) {
    const context = await browser.newContext({ viewport: { width: 1000, height: 800 } });
    const page = await context.newPage();
    await denyExternalNetwork(page);
    const content =
      '<section><h2>Metrics</h2><p>Lead-in prose.</p>'
      + '<canvas id="chart" class="cmh-chart" width="760" height="340" role="img" aria-label="Chart"'
      + " data-cmh-chart-points='" + points + "'" + extraAttrs + "></canvas>"
      + "</section>";
    const { dir, html } = stageContent(content, { key: "cmh-chart-tick", source: "chart-tick.html" });
    await page.goto(fileUrl(html));
    await ready(page);
    return { context, page, dir };
  }

  const tickCount = (page) => page.evaluate(() => {
    const c = document.getElementById("chart");
    return c._cmhChart ? c._cmhChart.tickCount : null;
  });

  // The pathological case: a tiny positive step with a large max. On the old code this froze the tab
  // (ready() would time out); on the fixed code the page loads and the tick count is bounded.
  test("CMH-CHART-11: a tiny step against a large max cannot freeze the tab", async ({ browser }) => {
    const { context, page, dir } = await openChart(
      browser,
      ' data-cmh-chart-max="100" data-cmh-chart-step="0.0000001"'
    );
    try {
      const n = await tickCount(page);
      expect(n).not.toBeNull();
      expect(n).toBeLessThanOrEqual(102);
    } finally {
      await context.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  // A normal step still renders the expected number of gridlines (regression guard: the cap must not
  // change ordinary charts). max 100, step 25 -> ticks at 0,25,50,75,100 == 5 ticks.
  test("CMH-CHART-11: a normal step renders the expected gridlines", async ({ browser }) => {
    const { context, page, dir } = await openChart(
      browser,
      ' data-cmh-chart-max="100" data-cmh-chart-step="25"'
    );
    try {
      const n = await tickCount(page);
      expect(n).toBe(5);
    } finally {
      await context.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
