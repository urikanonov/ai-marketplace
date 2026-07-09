import { test, expect } from "@playwright/test";
import { openInline, addTextComment, distinctCids, storedComments } from "./helpers.js";

async function openComposer(page, selector) {
  await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    const range = document.createRange();
    range.selectNodeContents(el);
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(range);
    el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  }, selector);
  await page.locator("#menuComment").click();
  return page.locator(".cm-composer").last();
}

test.describe("text comments", () => {
  test("adding a comment creates a highlight, a sidebar card, and updates the count", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "please clarify this");
    expect(await distinctCids(page)).toBe(1);
    await expect(page.locator("#commentList")).toContainText("please clarify this");
    await expect(page.locator("#toolbarCount")).toHaveText("1");
    await expect(page.locator("#sidebarCount")).toHaveText("1");
  });

  test("a comment survives a reload (localStorage persistence)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "persist me");
    await page.reload();
    await page.waitForFunction(() => window.__commentableHtmlReady === true);
    expect(await distinctCids(page)).toBe(1);
    await expect(page.locator("#commentList")).toContainText("persist me");
  });

  test("Ctrl+Enter in the composer saves the comment", async ({ page }) => {
    await openInline(page);
    const composer = await openComposer(page, "#commentRoot section p");
    await composer.locator("textarea").fill("saved via keyboard");
    await composer.locator("textarea").press("Control+Enter");
    await expect(composer).toHaveCount(0);
    await expect(page.locator("#commentList")).toContainText("saved via keyboard");
    expect(await distinctCids(page)).toBe(1);
  });

  test("Escape cancels the composer without creating a comment", async ({ page }) => {
    await openInline(page);
    const composer = await openComposer(page, "#commentRoot section p");
    await composer.locator("textarea").fill("do not keep me");
    await composer.locator("textarea").press("Escape");
    await expect(composer).toHaveCount(0);
    expect(await distinctCids(page)).toBe(0);
    await expect(page.locator("#toolbarCount")).toHaveText("0");
    // Nothing persisted to localStorage either.
    expect(await storedComments(page)).toEqual([]);
  });

  test("multiple comments accumulate", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "first", 0);
    await addTextComment(page, "#commentRoot section p", "second", 1);
    expect(await distinctCids(page)).toBe(2);
    await expect(page.locator("#toolbarCount")).toHaveText("2");
  });

  test("Clear removes every comment", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "temporary");
    await page.locator("#btnClearAll").click();
    await page.locator(".cm-modal").getByRole("button", { name: "OK" }).click();
    expect(await distinctCids(page)).toBe(0);
    await expect(page.locator("#toolbarCount")).toHaveText("0");
  });
});
