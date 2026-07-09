import { test, expect } from "@playwright/test";
import { openInline, openToolbarMenu } from "./helpers.js";

test.describe("toolbar (declutter)", () => {
  test("keeps Copy all + count + Show/Hide + more; hides save/export until menu opens", async ({ page }) => {
    await openInline(page);
    await expect(page.locator("#btnCopyAllTop")).toBeVisible();
    await expect(page.locator("#toolbarCount")).toBeVisible();
    await expect(page.locator("#btnToggleSidebar")).toBeVisible();
    await expect(page.locator("#btnToolbarMenu")).toBeVisible();
    await expect(page.locator("#btnSaveHtmlTop")).toBeHidden();

    await openToolbarMenu(page);
    await expect(page.locator("#btnSaveHtmlTop")).toBeVisible();
    await expect(page.locator("#btnSavePlainTop")).toBeVisible();
    await expect(page.locator("#cmhModeBadge")).toBeVisible();
  });

  test("Escape closes the overflow menu", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    await page.keyboard.press("Escape");
    await expect(page.locator("#toolbarMenu")).toBeHidden();
  });

  test("outside click closes the overflow menu", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    await page.mouse.click(6, 6);
    await expect(page.locator("#toolbarMenu")).toBeHidden();
  });

  test("Show/Hide toggle flips the label and shows/hides the panel (toolbar hides while open)", async ({ page }) => {
    await openInline(page);
    const toggle = page.locator("#btnToggleSidebar");
    const isOpen = () => page.evaluate(() => document.body.classList.contains("sidebar-open"));
    expect(await isOpen()).toBe(false);
    expect((await toggle.textContent()).trim()).toBe("Show");
    await toggle.click();
    expect(await isOpen()).toBe(true);
    // The floating toolbar is hidden while the panel is open (no pill over the doc).
    await expect(page.locator(".cm-toolbar")).toBeHidden();
    // Close via the panel's own control; the toolbar returns.
    await page.locator("#btnCloseSidebar").click();
    expect(await isOpen()).toBe(false);
    await expect(page.locator(".cm-toolbar")).toBeVisible();
    expect((await toggle.textContent()).trim()).toBe("Show");
  });
});
