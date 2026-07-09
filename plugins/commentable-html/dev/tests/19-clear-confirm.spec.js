// Clear Comments opens a confirm dialog instead of clearing immediately: Cancel is the
// default (Enter cancels), Escape cancels, a backdrop click cancels, and only OK clears
// every comment. This guards against an accidental, irreversible clear.
import { test, expect } from "@playwright/test";
import { openInline, addTextComment } from "./helpers.js";

test.describe("Clear Comments confirm dialog", () => {
  async function seedOneComment(page) {
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "keep me unless OK is clicked");
    await expect(page.locator("#commentList .cm-card")).toHaveCount(1);
  }

  test("Clear Comments opens a confirm dialog rather than clearing immediately", async ({ page }) => {
    await seedOneComment(page);
    await page.click("#btnClearAll");
    await expect(page.locator(".cm-modal")).toBeVisible();
    await expect(page.locator("#commentList .cm-card")).toHaveCount(1); // nothing cleared yet
  });

  test("Cancel is the default: pressing Enter cancels and keeps the comments", async ({ page }) => {
    await seedOneComment(page);
    await page.click("#btnClearAll");
    await expect(page.locator(".cm-modal")).toBeVisible();
    await page.keyboard.press("Enter"); // focus starts on Cancel -> Enter cancels
    await expect(page.locator(".cm-modal")).toHaveCount(0);
    await expect(page.locator("#commentList .cm-card")).toHaveCount(1);
  });

  test("Escape cancels and keeps the comments", async ({ page }) => {
    await seedOneComment(page);
    await page.click("#btnClearAll");
    await expect(page.locator(".cm-modal")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator(".cm-modal")).toHaveCount(0);
    await expect(page.locator("#commentList .cm-card")).toHaveCount(1);
  });

  test("clicking the backdrop cancels and keeps the comments", async ({ page }) => {
    await seedOneComment(page);
    await page.click("#btnClearAll");
    const overlay = page.locator(".cm-modal-overlay");
    await expect(overlay).toBeVisible();
    // Click the overlay itself (outside the dialog box) at the top-left corner.
    await overlay.click({ position: { x: 5, y: 5 } });
    await expect(page.locator(".cm-modal")).toHaveCount(0);
    await expect(page.locator("#commentList .cm-card")).toHaveCount(1);
  });

  test("Clear Comments does nothing (no dialog) when there are no comments", async ({ page }) => {
    await openInline(page);
    await page.click("#btnToggleSidebar"); // open the panel (empty state)
    await expect(page.locator("#commentList .cm-card")).toHaveCount(0);
    await page.click("#btnClearAll");
    await expect(page.locator(".cm-modal")).toHaveCount(0); // no confirm dialog for an empty set
  });

  test("the confirm dialog is an accessible modal that traps Tab and restores focus (CMH-A11Y-01)", async ({ page }) => {
    await seedOneComment(page);
    await page.locator("#btnClearAll").focus();
    await page.click("#btnClearAll");
    const modal = page.locator(".cm-modal");
    await expect(modal).toBeVisible();
    await expect(modal).toHaveAttribute("role", "dialog");
    await expect(modal).toHaveAttribute("aria-modal", "true");
    const labelledby = await modal.getAttribute("aria-labelledby");
    expect(labelledby).toBeTruthy();
    await expect(page.locator("#" + labelledby)).toBeVisible();
    // Tab stays trapped inside the dialog.
    for (let i = 0; i < 4; i++) {
      await page.keyboard.press("Tab");
      const inside = await page.evaluate(() => document.querySelector(".cm-modal").contains(document.activeElement));
      expect(inside).toBe(true);
    }
    await page.keyboard.press("Escape");
    await expect(page.locator(".cm-modal")).toHaveCount(0);
    await expect(page.locator("#btnClearAll")).toBeFocused(); // focus restored to the trigger
  });
});
