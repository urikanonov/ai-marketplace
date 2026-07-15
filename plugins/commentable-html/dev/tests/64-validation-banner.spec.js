import { test, expect } from "@playwright/test";
import fs from "fs";
import { fileUrl, ready, stageContent, installClipboardCapture, openToolbarMenu } from "./helpers.js";

// CMH-STAMP-03: the runtime shows a small dismissible amber fallback banner when a document carries a
// commentable-html-created stamp but no current commentable-html-validated stamp - a produced but
// never-strict-validated document. A validated document (and one with no created stamp) shows nothing.

const CONTENT = "<h1>Doc</h1><p>Body text for the document.</p>";

function injectMetas(htmlPath, metas) {
  let html = fs.readFileSync(htmlPath, "utf8");
  const tags = Object.entries(metas)
    .map(([name, content]) => '<meta name="' + name + '" content="' + content + '" />')
    .join("\n");
  html = html.replace(/<head[^>]*>/i, (m) => m + "\n" + tags);
  fs.writeFileSync(htmlPath, html);
}

async function open(page, metas, key) {
  const staged = stageContent(CONTENT, { key });
  injectMetas(staged.html, metas);
  await installClipboardCapture(page);
  await page.goto(fileUrl(staged.html));
  await ready(page);
  return staged;
}

test.describe("unvalidated-document fallback banner (CMH-STAMP-03)", () => {
  test("an unvalidated document shows the fallback banner", async ({ page }) => {
    await open(page, { "commentable-html-created": "2026-07-15T10:00:00Z" }, "cmh-banner-1");
    const banner = page.locator(".cmh-unvalidated-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("not validated");
  });

  test("a validated document shows no banner", async ({ page }) => {
    await open(page, {
      "commentable-html-created": "2026-07-15T10:00:00Z",
      "commentable-html-validated": "2026-07-15T10:05:00Z",
    }, "cmh-banner-2");
    await expect(page.locator(".cmh-unvalidated-banner")).toHaveCount(0);
  });

  test("a validation older than creation still shows the banner", async ({ page }) => {
    await open(page, {
      "commentable-html-created": "2026-07-15T10:05:00Z",
      "commentable-html-validated": "2026-07-15T10:00:00Z",
    }, "cmh-banner-3");
    await expect(page.locator(".cmh-unvalidated-banner")).toBeVisible();
  });

  test("a document with no created stamp shows no banner", async ({ page }) => {
    await open(page, {}, "cmh-banner-4");
    await expect(page.locator(".cmh-unvalidated-banner")).toHaveCount(0);
  });

  test("the banner is dismissible", async ({ page }) => {
    await open(page, { "commentable-html-created": "2026-07-15T10:00:00Z" }, "cmh-banner-5");
    const banner = page.locator(".cmh-unvalidated-banner");
    await expect(banner).toBeVisible();
    await banner.locator(".cmh-unvalidated-dismiss").click();
    await expect(banner).toHaveCount(0);
  });

  test("the banner does not leak into a Plain export", async ({ page }) => {
    await open(page, { "commentable-html-created": "2026-07-15T10:00:00Z" }, "cmh-banner-6");
    await expect(page.locator(".cmh-unvalidated-banner")).toBeVisible();
    await openToolbarMenu(page);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnSavePlainTop").click(),
    ]);
    const saved = fs.readFileSync(await download.path(), "utf8");
    // The runtime-injected banner element (and its message) must not bake into the plain copy; the
    // inert layer CSS rule that styles it is harmlessly retained like every other stylesheet.
    expect(saved).not.toContain("This document was not validated");
    expect(saved).not.toContain('class="cm-skip cmh-unvalidated-banner"');
  });
});
