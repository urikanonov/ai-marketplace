import { test, expect } from "@playwright/test";
import { openInline } from "./helpers.js";

test.describe("inline (standalone) mode", () => {
  test("initializes and reports itself as a portable file", async ({ page }) => {
    await openInline(page);
    await expect(page.locator("#cmhModeBadge")).toHaveText("Portable");
    expect(await page.evaluate(() => document.body.classList.contains("cm-economy"))).toBe(false);
    expect(await page.evaluate(() => !!window.__COMMENTABLE_ASSETS__)).toBe(false);
    expect(await page.evaluate(() => window.__commentableHtmlVersion)).toBeTruthy();
  });

  test("renders in a light theme by default", async ({ page }) => {
    await openInline(page);
    expect(await page.evaluate(() => document.documentElement.getAttribute("data-theme"))).toBe("light");
  });

  test("loads without unexpected console/page errors", async ({ page }) => {
    const errors = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("pageerror", (e) => errors.push(String(e)));
    await openInline(page);
    // The mermaid module import from jsdelivr is caught by the layer; ignore only that.
    const real = errors.filter((e) => !/jsdelivr|mermaid/i.test(e));
    expect(real).toEqual([]);
  });
});
