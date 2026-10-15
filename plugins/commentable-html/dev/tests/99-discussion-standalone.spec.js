import { test, expect } from "@playwright/test";
import {
  stageContent, fileUrl, ready, routeExampleLibsLocal, openComposerFor,
  storedComments, installClipboardCapture, lastCopied,
} from "./helpers.js";

test("standalone AI discussions need no shared-folder controls or directory permission (CMH-DISC-06)", async ({ page }) => {
  const { html } = stageContent(
    '<h1>Queue design</h1><p id="question">Each task has at most three attempts.</p>',
    { key: "discussion-standalone", source: "queue.html" },
  );
  await routeExampleLibsLocal(page);
  await installClipboardCapture(page);
  await page.addInitScript(() => {
    window.__directoryRequests = 0;
    window.showDirectoryPicker = () => {
      window.__directoryRequests += 1;
      throw new Error("Standalone discussions must not request folder access.");
    };
  });
  await page.goto(fileUrl(html));
  await ready(page);
  await expect(page.locator("#btnSharedFolder, #cmSharedStrip, .cm-shared-dialog")).toHaveCount(0);
  const composer = await openComposerFor(page, "#question");
  await composer.getByLabel("Comment purpose").selectOption("discussion");
  await composer.locator("textarea").fill("Why only three attempts?");
  await composer.locator('[data-act="save"]').click();
  expect((await storedComments(page))[0].intent).toBe("question");
  if (!await page.locator("body").evaluate((el) => el.classList.contains("sidebar-open"))) {
    await page.click("#btnToggleSidebar");
  }
  await page.click("#btnCopyAll");
  await expect.poll(async () => await lastCopied(page)).toContain("Why only three attempts?");
  expect(await lastCopied(page)).toContain("Do not edit the document for questions");
  expect(await lastCopied(page)).not.toContain("--folder");
  expect(await page.evaluate(() => window.__directoryRequests)).toBe(0);
  await page.reload();
  await ready(page);
  expect((await storedComments(page))[0].note).toBe("Why only three attempts?");
});
