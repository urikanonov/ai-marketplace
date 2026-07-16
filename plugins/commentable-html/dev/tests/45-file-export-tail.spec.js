import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import os from "os";
import { INLINE, fileUrl, ready, readDownload, openToolbarMenu } from "./helpers.js";

// CMH-EXP-06 (C1): on file:// the export base falls back to a DOM snapshot. That
// snapshot must include host content placed AFTER the layer <script> (per charts-embedding.md:
// chart data + init scripts land after the "END: commentable-html - JS" marker, before
// the final </body>). A snapshot captured at IIFE start stops at the script and silently
// drops that tail, losing the chart on every file:// export.

const CHART_TAIL =
  '\n<canvas id="c1Canvas" class="cm-skip" role="img" aria-label="test chart"></canvas>\n'
  + '<script id="c1ChartData" type="application/json">{"labels":["a","b"],"values":[1,2]}</script>\n'
  + '<script>/* C1-CHART-INIT-MARKER */ (function(){ var d = document.getElementById("c1ChartData");'
  + ' if (d) { window.__c1ChartInit = JSON.parse(d.textContent).values.length; } })();</script>\n';

function stageWithChartTail() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_c1_"));
  let html = fs.readFileSync(INLINE, "utf8");
  const marker = "<!-- END: commentable-html - JS -->";
  const idx = html.lastIndexOf(marker);
  if (idx < 0) throw new Error("no JS END marker in PORTABLE.html");
  const after = idx + marker.length;
  html = html.slice(0, after) + CHART_TAIL + html.slice(after);
  const p = path.join(dir, "doc-with-chart.html");
  fs.writeFileSync(p, html);
  return { dir, html: p };
}

async function assertChartSurvives(browser, exportedHtml, { layer = true } = {}) {
  expect(exportedHtml).toContain("C1-CHART-INIT-MARKER");
  expect(exportedHtml).toContain('id="c1ChartData"');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_c1_out_"));
  const p = path.join(dir, "reopened.html");
  fs.writeFileSync(p, exportedHtml);
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  try {
    await page.goto(fileUrl(p));
    if (layer) await ready(page);
    await page.waitForFunction(() => window.__c1ChartInit === 2, null, { timeout: 8000 });
    expect(await page.locator("#c1Canvas").count()).toBe(1);
  } finally {
    await ctx.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

test.describe("file:// export preserves host content after the layer", () => {
  test("Export as Portable keeps a chart placed after the JS marker", async ({ page, browser }) => {
    const staged = stageWithChartTail();
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await openToolbarMenu(page);
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.locator("#btnSaveHtmlTop").click(),
      ]);
      const html = await readDownload(download);
      await assertChartSurvives(browser, html);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("Export as Plain keeps a chart placed after the JS marker", async ({ page, browser }) => {
    const staged = stageWithChartTail();
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await openToolbarMenu(page);
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.locator("#btnSavePlainTop").click(),
      ]);
      const html = await readDownload(download);
      await assertChartSurvives(browser, html, { layer: false });
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });
});
