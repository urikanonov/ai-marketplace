import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import { PYTHON } from "./helpers.js";
import fs from "fs";
import path from "path";
import os from "os";
import {
  openInline, openNonPortable, openToolbarMenu, readDownload, ready, fileUrl, stageNonPortable, SKILL,
} from "./helpers.js";

function buildVersion() {
  return JSON.parse(fs.readFileSync(path.join(SKILL, "dist", "manifest.json"), "utf8")).version;
}

function sameMajorOlderVersion(version) {
  const [major, minor] = version.split(".").map(Number);
  return `${major}.${Math.max(0, minor - 1)}.0`;
}

function sameMajorNewerVersion(version) {
  const [major, minor] = version.split(".").map(Number);
  return `${major}.${minor + 1}.0`;
}

function nextMajorVersion(version) {
  const [major] = version.split(".").map(Number);
  return `${major + 1}.0.0`;
}

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
    // Scope the version-meta checks to <head>: the inlined runtime source can contain
    // string literals that mention meta names.
    const head = (html.match(/<head[\s\S]*?<\/head>/i) || [""])[0];
    expect(head).not.toMatch(/<meta\b[^>]*commentable-html-assets/i);
    // The version stamp is universal and must survive export, carrying the exact build version.
    const metaMatch = head.match(/<meta\b[^>]*name="commentable-html-version"[^>]*content="([^"]+)"/i);
    expect(metaMatch && metaMatch[1]).toBe(buildVersion());
    expect(html).toContain("BEGIN: commentable-html - CSS");
    expect(html).toContain("BEGIN: commentable-html - JS");

    // It passes validate.py as an inline document.
    const tmp = path.join(os.tmpdir(), "cmh_standalone_" + Date.now() + ".html");
    fs.writeFileSync(tmp, html);
    let page2;
    try {
      execFileSync(PYTHON, ["tools/validate/validate.py", tmp], { cwd: SKILL }); // throws on non-zero exit

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

  test("an older same-major page version does not show the version banner", async ({ page }) => {
    const older = sameMajorOlderVersion(buildVersion());
    const { html, dir } = stageNonPortable({
      mutate: (h) => h.replace(/content="[0-9]+\.[0-9]+\.[0-9]+"/, `content="${older}"`),
    });
    try {
      await page.goto(fileUrl(html));
      await ready(page);
      await expect(page.locator("#cmhAssetBanner")).toBeHidden();
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("a different-major page version shows the incompatible banner", async ({ page }) => {
    const newerMajor = nextMajorVersion(buildVersion());
    const { html, dir } = stageNonPortable({
      mutate: (h) => h.replace(/content="[0-9]+\.[0-9]+\.[0-9]+"/, `content="${newerMajor}"`),
    });
    try {
      await page.goto(fileUrl(html));
      await ready(page);
      await expect(page.locator("#cmhAssetBanner")).toBeVisible();
      await expect(page.locator("#cmhAssetBanner")).toContainText(/not compatible/i);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("a newer same-major page version shows the soft version banner", async ({ page }) => {
    const newer = sameMajorNewerVersion(buildVersion());
    const { html, dir } = stageNonPortable({
      mutate: (h) => h.replace(/content="[0-9]+\.[0-9]+\.[0-9]+"/, `content="${newer}"`),
    });
    try {
      await page.goto(fileUrl(html));
      await ready(page);
      await expect(page.locator("#cmhAssetBanner")).toBeVisible();
      await expect(page.locator("#cmhAssetBanner")).toContainText(/expects a newer commentable-html/i);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("dismissing a version banner hides it across reloads for that version pair", async ({ page }) => {
    const newer = sameMajorNewerVersion(buildVersion());
    const { html, dir } = stageNonPortable({
      mutate: (h) => h.replace(/content="[0-9]+\.[0-9]+\.[0-9]+"/, `content="${newer}"`),
    });
    try {
      await page.goto(fileUrl(html));
      await ready(page);
      const banner = page.locator("#cmhAssetBanner");
      await expect(banner).toBeVisible();
      await banner.getByRole("button", { name: "Dismiss" }).click();
      await expect(banner).toBeHidden();
      await page.reload();
      await ready(page);
      await expect(banner).toBeHidden();
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
