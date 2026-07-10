import { test, expect } from "@playwright/test";
import fs from "fs";
import os from "os";
import path from "path";
import {
  openInline, fileUrl, addTextComment, storedComments, readDownload,
} from "./helpers.js";

// Explicit end-to-end coverage of the three document modes a reviewer encounters:
// Portable (clean), Not portable (live comments not embedded), and Portable-with-comments
// (a shared copy whose comments travel embedded in the file, independent of localStorage).

test("MODE Portable: a fresh self-contained document reports Portable", async ({ page }) => {
  await openInline(page); // dist/PORTABLE.html: assets embedded, no live comments
  await expect(page.locator("#cmTypeBadge")).toHaveText("Portable");
});

test("MODE Not portable: a live comment that is not embedded flips the badge to Not portable", async ({ page }) => {
  await openInline(page);
  await expect(page.locator("#cmTypeBadge")).toHaveText("Portable");
  await addTextComment(page, "#commentRoot section p", "please review this");
  await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable"); // comment lives only in localStorage
});

test("MODE Portable-with-comments: Save embeds comments that travel to a fresh browser and stay Portable", async ({ page, browser }) => {
  await openInline(page);
  await addTextComment(page, "#commentRoot section p", "carry me into the file");
  expect((await storedComments(page)).length).toBe(1);

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#btnSaveHtml").click(),
  ]);
  const shared = path.join(os.tmpdir(), "cmh_modes_" + Date.now() + ".html");
  fs.writeFileSync(shared, await readDownload(download));

  // The live page has not reloaded: its own comment is still localStorage-only (not
  // embedded in its DOM), so the live badge stays Not portable after the export.
  await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable");

  const ctx = await browser.newContext();
  const fresh = await ctx.newPage();
  try {
    await fresh.goto(fileUrl(shared));
    await fresh.waitForFunction(() => window.__commentableHtmlReady === true);
    await expect(fresh.locator("#commentList")).toContainText("carry me into the file");
    await expect(fresh.locator("#cmTypeBadge")).toHaveText("Portable"); // embedded, not from localStorage
  } finally {
    await ctx.close();
    fs.unlinkSync(shared);
  }
});
