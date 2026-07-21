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

  test("Tab from a focused heading reaches and activates the Add Comment button (CMH-A11Y-08)", async ({ page }) => {
    const staged = stageContent(
      '<section><h2 id="tab-heading">Tab <a id="heading-link" href="#inside">Heading link</a></h2><p><a id="next-link" href="#next">next link</a></p></section>'
      + '<h2 id="plain-heading">Plain Heading</h2>'
      + '<a id="negative-link" href="#negative" tabindex="-2">negative link</a>'
      + '<fieldset disabled><button id="fieldset-disabled">disabled fieldset button</button></fieldset>'
      + '<span inert><a id="inert-link" href="#inert">inert link</a></span>'
      + '<a id="plain-next" href="#plain-next">plain next</a>',
      { key: "cmh-a11y-08-doc" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await page.locator("#tab-heading").focus();
      const btn = page.locator("#headingAddBtn");
      await expect(btn).toBeVisible();
      await page.keyboard.press("Tab");
      await expect(btn).toBeFocused();
      await page.waitForTimeout(300);
      await expect(btn).toBeFocused();
      await expect(btn).toBeVisible();
      await page.keyboard.press("Shift+Tab");
      await expect(page.locator("#tab-heading")).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(btn).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(page.locator("#tab-heading .cmh-sec-caret")).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(page.locator("#heading-link")).toBeFocused();
      await page.locator("#tab-heading").focus();
      await page.keyboard.press("Tab");
      await expect(btn).toBeFocused();
      await page.keyboard.press("Enter");
      const composer = page.locator(".cm-composer").last();
      await expect(composer.locator("textarea")).toBeFocused();
      await page.locator("#plain-heading .cmh-review-badge").evaluate((el) => el.remove());
      await page.locator("#plain-heading").focus();
      await page.keyboard.press("Tab");
      await expect(btn).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(page.locator("#plain-next")).toBeFocused();
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  // CMH-CONTENT-14 (P1): top-level prose is not width-capped - both the lede and ordinary
  // section paragraphs fill the content column (no readable-measure cap).
  test("top-level prose paragraphs are not width-capped (lede and sections both full width)", async ({ page }) => {
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
      expect(sectionMax).toBe("none");
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
