import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import {
  PYTHON, SKILL, fileUrl, ready, stageContent, denyExternalNetwork, openToolbarMenu,
  mutateStoredComments,
} from "./helpers.js";
import { execFileSync } from "child_process";

// CMH-CHART-12 (issue #740): the live chart renderer and the offline exporter disagreed about what
// counts as a chart. The renderer's setup pass took `canvas.cmh-chart[data-cmh-chart-*]` /
// `figure.chart canvas[data-cmh-chart-*]` while its own resize listener took any
// `canvas[data-cmh-chart-points], canvas[data-cmh-chart-source]`, and the exporter took a third list
// (`figure.chart canvas, canvas.cmh-chart`). A BARE data-bearing canvas - no `cmh-chart` class, not
// inside a `figure.chart` - therefore drew nothing at load (only a window resize revived it) and was
// not treated as a chart by the exporter. All three now derive from one shared selector definition.

const POINTS = '[{"label":"Alpha","value":10},{"label":"Beta","value":24},{"label":"Gamma","value":16}]';
// The authorable bare shape: no `cmh-chart` class and no `figure.chart` wrapper, but still inside a
// `cm-skip` wrapper - the validator already fails loudly on a canvas that is not (chart pixels must
// not be selectable), so this is the shape a hand-authored document can actually ship.
const BARE_CANVAS =
  '<div class="cm-skip"><canvas id="bareChart" width="360" height="180" role="img" aria-label="Bare canvas chart"'
  + " data-cmh-chart-points='" + POINTS + "'></canvas></div>";
const CONTENT =
  '<section><h2>Bare canvas chart</h2><p id="bare-note">A chart canvas with no wrapper figure.</p>'
  + BARE_CANVAS + "</section>";

function chartState(page) {
  return page.evaluate(() => {
    const canvas = document.getElementById("bareChart");
    if (!canvas) return null;
    const ctx = canvas.getContext("2d");
    const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    let painted = 0;
    for (let i = 3; i < pixels.length; i += 4) if (pixels[i] !== 0) painted++;
    return {
      points: canvas._cmhChart ? canvas._cmhChart.points.length : 0,
      painted: painted,
      imageIndex: canvas.getAttribute("data-cm-image-index"),
    };
  });
}

test("CMH-CHART-12: a bare data-bearing canvas renders and is commentable at load", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 1000, height: 800 } });
  const page = await context.newPage();
  const { dir, html } = stageContent(CONTENT, { key: "cmh-bare-chart", source: "bare-chart.html" });
  try {
    await denyExternalNetwork(page);
    await page.goto(fileUrl(html));
    await ready(page);
    const state = await chartState(page);
    expect(state).not.toBeNull();
    expect(state.points).toBe(3);
    expect(state.painted).toBeGreaterThan(0);
    // The image layer indexes it as commentable chart media, exactly like a wrapped chart canvas.
    expect(state.imageIndex).not.toBeNull();
  } finally {
    await context.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("CMH-CHART-12: a legacy image comment still resolves when a bare canvas becomes commentable", async ({ browser }) => {
  // The bare canvas was NOT indexed before this change, so a document authored with one gave every
  // later image a lower imageIndex. A comment persisted under that old indexing must still land on
  // its image (the stored src/alt/kind metadata is what rescues it), not on the newly-indexed canvas.
  const context = await browser.newContext({ viewport: { width: 1000, height: 800 } });
  const page = await context.newPage();
  const content =
    '<section><h2>Legacy anchor</h2>' + BARE_CANVAS
    + '<img id="afterImg" src="after-image.png" alt="After image">'
    + "</section>";
  const { dir, html } = stageContent(content, { key: "cmh-bare-chart-legacy", source: "bare-legacy.html" });
  try {
    await denyExternalNetwork(page);
    await page.goto(fileUrl(html));
    await ready(page);
    await page.evaluate(() => {
      const img = document.getElementById("afterImg");
      img.scrollIntoView({ block: "center" });
      img.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
    });
    await expect(page.locator("#imageAddBtn")).toBeVisible();
    await page.locator("#imageAddBtn").click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("on the image");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toBeHidden();
    await expect(page.locator("#afterImg.cm-img-hl")).toHaveCount(1);

    // Rewind the anchor to the index the PRE-FIX layer would have stored (the canvas was skipped,
    // so the image was 0, not 1). The stored metadata must still resolve it to the same image.
    await mutateStoredComments(page, (arr) => arr.map((c) => ({ ...c, imageIndex: 0 })));
    await page.reload();
    await ready(page);
    await expect(page.locator("#afterImg.cm-img-hl")).toHaveCount(1);
    await expect(page.locator("#bareChart.cm-img-hl")).toHaveCount(0);
  } finally {
    await context.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("CMH-CHART-12: the Offline export of a bare data-bearing canvas renders with zero network", async ({ browser }) => {
  test.setTimeout(90000);
  const context = await browser.newContext({ viewport: { width: 1000, height: 800 } });
  const page = await context.newPage();
  const { dir, html } = stageContent(CONTENT, { key: "cmh-bare-chart-offline", source: "bare-chart-offline.html" });
  const outDir = fs.mkdtempSync(path.join(dir, "out_"));
  let offlineCtx;
  try {
    await denyExternalNetwork(page);
    await page.addInitScript(() => {
      window.__cmhDownloadTexts = [];
      const original = URL.createObjectURL.bind(URL);
      URL.createObjectURL = (blob) => {
        if (blob && String(blob.type || "").includes("text/html")) {
          blob.text().then((text) => window.__cmhDownloadTexts.push(text));
        }
        return original(blob);
      };
    });
    await page.goto(fileUrl(html));
    await ready(page);
    await openToolbarMenu(page);
    await expect(page.locator("#btnExportOfflineTop")).toBeVisible();
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    await page.waitForFunction(() => window.__cmhDownloadTexts && window.__cmhDownloadTexts.length > 0);
    const exportedHtml = await page.evaluate(() => window.__cmhDownloadTexts[window.__cmhDownloadTexts.length - 1]);
    // The exporter agrees with the renderer that this is a chart, so it inlines Chart.js for any
    // author script the document may add later, exactly as it does for a wrapped chart canvas.
    expect(exportedHtml).toContain('data-cmh-offline-lib="chartjs"');
    const exportedPath = path.join(outDir, "bare-chart-offline.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });

    offlineCtx = await browser.newContext({ viewport: { width: 1000, height: 800 }, offline: true });
    const page2 = await offlineCtx.newPage();
    const external = [];
    page2.on("request", (request) => {
      if (/^https?:\/\//.test(request.url())) external.push(request.url());
    });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    const state = await chartState(page2);
    expect(state).not.toBeNull();
    expect(state.points).toBe(3);
    expect(state.painted).toBeGreaterThan(0);
    expect(external).toEqual([]);
  } finally {
    if (offlineCtx) await offlineCtx.close();
    await context.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
