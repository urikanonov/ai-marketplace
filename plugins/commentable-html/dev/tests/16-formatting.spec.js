// Document formatting conventions shipped by the layer: section cards, TOC,
// themed tables, and status badges (matching the reference report style).
import { test, expect } from "@playwright/test";
import { openInline, ready, fileUrl, INLINE } from "./helpers.js";

test.describe("document formatting conventions", () => {
  test("sections render as cards (border + radius + shadow)", async ({ page }) => {
    await openInline(page);
    const s = await page.locator("#commentRoot section").first().evaluate((el) => {
      const cs = getComputedStyle(el);
      return { border: cs.borderTopWidth, radius: cs.borderTopLeftRadius, shadow: cs.boxShadow };
    });
    expect(parseFloat(s.border)).toBeGreaterThan(0);
    expect(parseFloat(s.radius)).toBeGreaterThan(0);
    expect(s.shadow).not.toBe("none");
  });

  test("a table of contents renders with anchor links that resolve to sections", async ({ page }) => {
    await openInline(page);
    await expect(page.locator("nav.cm-toc")).toHaveCount(1);
    const links = page.locator("nav.cm-toc a");
    expect(await links.count()).toBeGreaterThanOrEqual(4);
    const targets = await links.evaluateAll((as) => as.map((a) => a.getAttribute("href")));
    for (const t of targets) {
      expect(t.startsWith("#")).toBe(true);
      await expect(page.locator(t)).toHaveCount(1);
    }
  });

  test("tables use collapsed borders and a themed header", async ({ page }) => {
    await openInline(page);
    await page.evaluate(() => {
      document.querySelector("#commentRoot section").insertAdjacentHTML(
        "beforeend",
        "<table><thead><tr><th>H</th></tr></thead><tbody><tr><td>C</td></tr></tbody></table>");
    });
    const collapse = await page.locator("#commentRoot table").first()
      .evaluate((el) => getComputedStyle(el).borderCollapse);
    expect(collapse).toBe("collapse");
    const th = await page.locator("#commentRoot th").first()
      .evaluate((el) => getComputedStyle(el).borderTopWidth);
    expect(parseFloat(th)).toBeGreaterThan(0);
  });

  test("status badges are styled pills with a border", async ({ page }) => {
    await openInline(page);
    await page.evaluate(() => {
      document.querySelector("#commentRoot section").insertAdjacentHTML(
        "beforeend", '<span class="badge ok">Ready</span>');
    });
    const cs = await page.locator("#commentRoot .badge.ok").evaluate((el) => {
      const c = getComputedStyle(el);
      return { radius: c.borderTopLeftRadius, border: c.borderTopWidth };
    });
    expect(parseFloat(cs.radius)).toBeGreaterThan(0);
    expect(parseFloat(cs.border)).toBeGreaterThan(0);
  });

  test("a nested section does not get a second card (direct-child scoping)", async ({ page }) => {
    await openInline(page);
    await page.evaluate(() => {
      document.querySelector("#commentRoot > section").insertAdjacentHTML(
        "beforeend", '<section id="cmh-nested"><h3>nested</h3></section>');
    });
    const outer = await page.locator("#commentRoot > section").first()
      .evaluate((el) => getComputedStyle(el).borderTopWidth);
    const nested = await page.locator("#cmh-nested").evaluate((el) => getComputedStyle(el).borderTopWidth);
    expect(parseFloat(outer)).toBeGreaterThan(0);
    expect(parseFloat(nested)).toBe(0); // no card border on the nested section
  });

  test("section cards and badges are styled in dark theme too", async ({ page }) => {
    await page.goto(fileUrl(INLINE) + "?clawpilotTheme=dark");
    await ready(page);
    expect(await page.evaluate(() => document.documentElement.getAttribute("data-theme"))).toBe("dark");
    const shadow = await page.locator("#commentRoot > section").first()
      .evaluate((el) => getComputedStyle(el).boxShadow);
    expect(shadow).not.toBe("none");
    await page.evaluate(() => document.querySelector("#commentRoot > section")
      .insertAdjacentHTML("beforeend", '<span class="badge warn">W</span>'));
    const border = await page.locator("#commentRoot .badge.warn")
      .evaluate((el) => getComputedStyle(el).borderTopWidth);
    expect(parseFloat(border)).toBeGreaterThan(0);
  });
});
