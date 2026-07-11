import { test, expect } from "@playwright/test";
import fs from "fs";
import { openInline, ready, fileUrl, stageContent } from "./helpers.js";

test.describe("heading keyboard affordance, lede width, document title", () => {
  // CMH-TOC-05 (U10): section headings are deep-link affordances but were mouse-only.
  test("a heading is keyboard-focusable and Enter deep-links to it", async ({ page }) => {
    const staged = stageContent(
      '<section><h2 id="target-heading">Target Heading</h2><p>body text here</p></section>',
      { key: "cmh-u10-doc" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      const h = page.locator("#target-heading");
      await expect(h).toHaveAttribute("tabindex", "0");
      await h.focus();
      expect(await h.evaluate((el) => el === document.activeElement)).toBe(true);
      // focusing the heading reveals the add-comment button (keyboard parity with hover)
      await expect(page.locator("#headingAddBtn")).toBeVisible();
      await page.keyboard.press("Enter");
      expect(await page.evaluate(() => location.hash)).toBe("#target-heading");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("Space activates the heading deep-link too", async ({ page }) => {
    const staged = stageContent(
      '<section><h2 id="space-heading">Space Heading</h2><p>body</p></section>',
      { key: "cmh-u10b-doc" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await page.locator("#space-heading").focus();
      await page.keyboard.press("Space");
      expect(await page.evaluate(() => location.hash)).toBe("#space-heading");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("a keyboard-focused heading shows the focus-visible outline", async ({ page }) => {
    const staged = stageContent(
      '<section><h2 id="fv-heading">Focus Ring Heading</h2><p>body</p></section>',
      { key: "cmh-u10c-doc" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      // Establish keyboard modality so the browser applies :focus-visible on focus.
      await page.keyboard.press("Tab");
      const h = page.locator("#fv-heading");
      await h.evaluate((el) => el.focus());
      const seen = await h.evaluate((el) => ({
        matchesFocusVisible: el.matches(":focus-visible"),
        outlineWidth: getComputedStyle(el).outlineWidth,
        outlineStyle: getComputedStyle(el).outlineStyle,
      }));
      expect(seen.matchesFocusVisible).toBe(true);
      expect(seen.outlineStyle).toBe("solid");
      expect(parseFloat(seen.outlineWidth)).toBeGreaterThanOrEqual(3);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  // CMH-LEDE-01 (P1): the 72ch prose measure must not cap the lede, which is a full-width
  // surface box; its paragraph opts out so it is not narrower than sibling sections.
  test("the lede paragraph is not capped by the 72ch prose measure", async ({ page }) => {
    const staged = stageContent(
      '<header class="cmh-lede"><p id="lede-p">lede paragraph</p></header>'
      + '<section><p id="section-p">section paragraph</p></section>',
      { key: "cmh-p1-doc" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      const ledeMax = await page.locator("#lede-p").evaluate((el) => getComputedStyle(el).maxWidth);
      const sectionMax = await page.locator("#section-p").evaluate((el) => getComputedStyle(el).maxWidth);
      expect(ledeMax).toBe("none");
      expect(sectionMax).not.toBe("none");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  // CMH-TITLE-01 (P2): a document has a themed, visible top-level title.
  test("the document title h1 is themed and visibly larger than body prose", async ({ page }) => {
    await openInline(page);
    const h1 = page.locator("#commentRoot header.cmh-lede > h1").first();
    await expect(h1).toBeVisible();
    const h1Size = await h1.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    const pSize = await page.locator("#commentRoot p").first()
      .evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(h1Size).toBeGreaterThan(pSize + 6);
  });
});
