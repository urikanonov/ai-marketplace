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
