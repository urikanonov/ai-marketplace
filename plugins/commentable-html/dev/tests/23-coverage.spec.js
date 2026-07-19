import { test, expect } from "@playwright/test";
import {
  openInline,
  openKitchenSink,
  ready,
  fileUrl,
  INLINE,
  startStaticServer,
  routeMermaidLocal,
  SKILL,
  PLUGIN,
} from "./helpers.js";

async function openComposerFromSelection(page, selector, index = 0) {
  // Select the element's full contents rather than a text-offset range so the second
  // composer collides with the first even though the composing preview (CMH-CORE-17)
  // wraps the selected text and splits its text nodes.
  await page.evaluate(({ sel, i }) => {
    const el = document.querySelectorAll(sel)[i];
    const range = document.createRange();
    range.selectNodeContents(el);
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(range);
    el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 40, clientY: 40 }));
  }, { sel: selector, i: index });
  await expect(page.locator("#menuComment")).toBeVisible();
  await page.locator("#menuComment").evaluate((button) => button.click());
  return page.locator(".cm-composer").last();
}

test.describe("coverage gap closures", () => {
  test("CMH-THEME-01: template defaults to light, supports dark, and follows OS for auto", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await openInline(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

    await page.goto(fileUrl(INLINE) + "?clawpilotTheme=dark");
    await ready(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

    await page.goto(fileUrl(INLINE) + "?clawpilotTheme=auto&os=dark");
    await ready(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

    await page.emulateMedia({ colorScheme: "light" });
    await page.goto(fileUrl(INLINE) + "?clawpilotTheme=auto&os=light");
    await ready(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  });

  test("CMH-CORE-09: overlapping new composers are staggered", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await openKitchenSink(page);

    const first = await openComposerFromSelection(page, "#commentRoot section p", 0);
    await expect(first).toBeVisible();
    await openComposerFromSelection(page, "#commentRoot section p", 0);

    const composers = page.locator(".cm-composer");
    await expect(composers).toHaveCount(2);
    await expect(composers.nth(0)).toBeVisible();
    await expect(composers.nth(1)).toBeVisible();

    const boxes = await composers.evaluateAll((els) => els.map((el) => {
      const r = el.getBoundingClientRect();
      return { left: r.left, top: r.top };
    }));
    const dx = boxes[1].left - boxes[0].left;
    const dy = boxes[1].top - boxes[0].top;
    expect(Math.abs(dx) + Math.abs(dy)).toBeGreaterThan(1);
    expect(dx).toBeGreaterThanOrEqual(24);
    expect(dx).toBeLessThanOrEqual(32);
    expect(dy).toBeGreaterThanOrEqual(24);
    expect(dy).toBeLessThanOrEqual(32);
  });

  test("CMH-MMDLOAD-01: mermaid renders by default when served over http", async ({ page }) => {
    const server = await startStaticServer(SKILL);
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/dist/PORTABLE.html");
      await ready(page);
      await expect(page.locator("#commentRoot .mermaid svg g.node").first()).toBeVisible({ timeout: 20000 });
    } finally {
      await server.close();
    }
  });

  test("CMH-GANTT-01: gantt task labels are commentable", async ({ page }) => {
    test.setTimeout(60000);
    const server = await startStaticServer(SKILL);
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/dist/PORTABLE.html");
      await ready(page);
      const taskLabel = page.locator("#commentRoot .mermaid svg .taskText").first();
      await expect(taskLabel).toBeVisible({ timeout: 20000 });
      await taskLabel.hover();
      const addBtn = page.locator("#mermaidAddBtn");
      await expect(addBtn).toBeVisible();
      await addBtn.click();
      const composer = page.locator(".cm-composer").last();
      await composer.locator("textarea").fill("gantt task note");
      await composer.locator('[data-act="save"]').click();
      await expect(composer).toHaveCount(0);
      await expect(page.locator("#commentRoot .mermaid svg .taskText.cm-mermaid-hl")).toHaveCount(1);
      await expect(page.locator(".cm-card .quote")).toContainText(/mermaid node/i);
    } finally {
      await server.close();
    }
  });

  test("CMH-CHART-04: community garden Chart.js tooltip has title and body", async ({ page }) => {
    test.setTimeout(60000);
    const server = await startStaticServer(PLUGIN);
    try {
      await page.goto(server.url + "/examples/report-community-garden.html");
      await ready(page);
      await page.waitForFunction(() => {
        const chart = window.Chart && window.Chart.getChart && window.Chart.getChart("wateringNeedsChart");
        return !!(chart && chart.getDatasetMeta(0).data.length > 0);
      }, null, { timeout: 30000 });

      const tooltip = await page.evaluate(() => {
        const chart = window.Chart.getChart("wateringNeedsChart");
        const bar = chart.getDatasetMeta(0).data[0];
        const point = bar.getProps(["x", "y"], true);
        chart.tooltip.setActiveElements([{ datasetIndex: 0, index: 0 }], point);
        chart.update();
        return {
          version: window.Chart.version || "",
          title: chart.tooltip.title || [],
          body: (chart.tooltip.body || []).map((item) => item.lines || []),
        };
      });

      expect(tooltip.version).toBeTruthy();
      expect(tooltip.title.join("\n").trim()).not.toBe("");
      expect(tooltip.body.flat().join("\n").trim()).not.toBe("");
    } finally {
      await server.close();
    }
  });
});
