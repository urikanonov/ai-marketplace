import { test, expect } from "@playwright/test";
import path from "path";
import { SKILL, fileUrl, ready } from "./helpers.js";

const METRICS = path.join(SKILL, "examples", "report-metrics.html");

test.use({ viewport: { width: 380, height: 820 } });

test("charts and mermaid blocks are contained in the mobile content column (CMH-RESP-01)", async ({ page }) => {
  await page.goto(fileUrl(METRICS));
  await ready(page);

  const result = await page.evaluate(() => {
    const root = document.getElementById("commentRoot");
    const viewportWidth = document.documentElement.clientWidth;
    const rootRect = root.getBoundingClientRect();
    const mermaid = [...root.querySelectorAll("pre.mermaid")].map((el) => ({
      overflowX: getComputedStyle(el).overflowX,
      fits: el.getBoundingClientRect().right <= viewportWidth + 1,
      canScroll: el.scrollWidth >= el.clientWidth,
    }));
    const charts = [...root.querySelectorAll("figure.chart")].map((el) => ({
      overflowX: getComputedStyle(el).overflowX,
      fits: el.getBoundingClientRect().right <= viewportWidth + 1,
      canScroll: el.scrollWidth >= el.clientWidth,
    }));
    return {
      rootFits: rootRect.left >= -1 && rootRect.right <= viewportWidth + 1,
      mermaid,
      charts,
    };
  });

  expect(result.rootFits, "#commentRoot stays inside the viewport").toBe(true);
  expect(result.mermaid.length, "fixture has mermaid diagrams").toBeGreaterThan(0);
  expect(result.charts.length, "fixture has chart figures").toBeGreaterThan(0);
  for (const item of [...result.mermaid, ...result.charts]) {
    expect(item.fits, "block box stays inside the viewport").toBe(true);
    expect(["auto", "scroll"], "wide rich content scrolls inside its own block").toContain(item.overflowX);
    expect(item.canScroll, "scroll metrics are bounded to the block").toBe(true);
  }
});
