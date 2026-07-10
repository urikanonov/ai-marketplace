import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import { PYTHON } from "./helpers.js";
import fs from "fs";
import path from "path";
import os from "os";
import {
  openInline, openNonPortable, openToolbarMenu, readDownload, ready, fileUrl, stageNonPortable, SKILL,
} from "./helpers.js";

test.describe("nonportable mode", () => {
  test("loads from companion files and reports itself as needing them", async ({ page }) => {
    await openNonPortable(page);
    await expect(page.locator("#cmhModeBadge")).toHaveText("Not portable");
    expect(await page.evaluate(() => document.body.classList.contains("cm-nonportable"))).toBe(true);
    expect(await page.evaluate(() => !!(window.__COMMENTABLE_ASSETS__ && window.__COMMENTABLE_ASSETS__.css && window.__COMMENTABLE_ASSETS__.js))).toBe(true);
    await expect(page.locator("#cmhAssetBanner")).toBeHidden();
  });

  test("Export with embedded comments produces one portable standalone file in nonportable mode", async ({ page, context }) => {
    await openNonPortable(page);
    await openToolbarMenu(page);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.click("#btnSaveHtmlTop"),
    ]);
    const html = await readDownload(download);

    // No companion references survive; the inline regions are restored - even
    // though the source document was nonportable, the export is always combined.
    expect(html).not.toMatch(/<link\b[^>]*\bhref\s*=\s*["'][^"']*commentable-html/i);
    expect(html).not.toMatch(/<script\b[^>]*\bsrc\s*=\s*["'][^"']*commentable-html/i);
    // Scope the version-meta check to <head>: the inlined runtime source legitimately
    // contains a "<meta ... commentable-html-assets ...>" string literal.
    const head = (html.match(/<head[\s\S]*?<\/head>/i) || [""])[0];
    expect(head).not.toMatch(/<meta\b[^>]*commentable-html-assets/i);
    expect(html).toContain("BEGIN: commentable-html v2 - CSS");
    expect(html).toContain("BEGIN: commentable-html v2 - JS");

    // It passes validate.py as an inline document.
    const tmp = path.join(os.tmpdir(), "cmh_standalone_" + Date.now() + ".html");
    fs.writeFileSync(tmp, html);
    let page2;
    try {
      execFileSync(PYTHON, ["tools/validate.py", tmp], { cwd: SKILL }); // throws on non-zero exit

      // And it re-opens as a working inline (portable) document.
      page2 = await context.newPage();
      await page2.goto(fileUrl(tmp));
      await ready(page2);
      expect(await page2.evaluate(() => document.body.classList.contains("cm-nonportable"))).toBe(false);
      await expect(page2.locator("#cmhModeBadge")).toHaveText("Portable");
    } finally {
      if (page2) await page2.close();
      fs.rmSync(tmp, { force: true });
    }
  });

  test("missing companions reveal the banner and never mark the runtime ready", async ({ page }) => {
    const { html, dir } = stageNonPortable({ companions: false });
    try {
      await page.goto(fileUrl(html));
      await expect(page.locator("#cmhAssetBanner")).toBeVisible({ timeout: 6000 });
      await expect(page.locator("#cmhAssetBanner")).toContainText(/companion files/i);
      expect(await page.evaluate(() => window.__commentableHtmlReady === true)).toBe(false);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("a version-handshake mismatch reveals the banner", async ({ page }) => {
    const { html, dir } = stageNonPortable({ mutate: (h) => h.replace('content="2.5.0"', 'content="9.9.9"') });
    try {
      await page.goto(fileUrl(html));
      await ready(page);
      await expect(page.locator("#cmhAssetBanner")).toBeVisible();
      await expect(page.locator("#cmhAssetBanner")).toContainText(/mismatch/i);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
