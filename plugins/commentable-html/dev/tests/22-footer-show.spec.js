import { test, expect } from "@playwright/test";
import { openInline, openToolbarMenu, ready, readDownload } from "./helpers.js";

test.describe("attribution footer + Show affordance", () => {
  test("the footer shows version and a Help link; attribution lives in Help", async ({ page }) => {
    await openInline(page);
    const footer = page.locator("#cmFooter");
    await expect(footer).toBeVisible();
    await expect(footer).toContainText(/Commentable HTML v\d+\.\d+\.\d+/);
    // Source/issue/author are NOT in the footer anymore.
    await expect(footer).not.toContainText("Authored by");
    await expect(footer.locator("a")).toHaveCount(0);
    // The footer Help & about button opens the Help modal, which carries the attribution.
    await footer.locator(".cm-footer-help").click();
    const help = page.locator(".cm-help");
    await expect(help).toBeVisible();
    await expect(help).toContainText(/authored by Uri Kanonov/i);
    await expect(help.locator('a[href="https://github.com/urikanonov/ai-marketplace"]')).toHaveCount(1);
    await expect(help.locator('a[href*="issues/new?template=plugin-issue.yml"]')).toHaveCount(1);
    for (const a of await help.locator('a[href*="github.com/urikanonov"]').all()) {
      await expect(a).toHaveAttribute("rel", /noopener/);
      await expect(a).toHaveAttribute("target", "_blank");
    }
  });

  test("the footer shows the brand icon and the generated timestamp", async ({ page }) => {
    await openInline(page);
    const footer = page.locator("#cmFooter");
    await expect(footer).toBeVisible();
    await expect(footer.locator(".cm-brand-icon")).toHaveCount(1);
    await expect(footer).toContainText(/Generated /);
  });

  test("the brand icon shows in the panel meta row and a favicon is set", async ({ page }) => {
    await openInline(page);
    await expect(page.locator(".cm-sidebar .head-meta .cm-brand-icon")).toHaveCount(1);
    const favicon = await page.evaluate(() => {
      const l = document.querySelector('link[rel="icon"]');
      return l ? l.getAttribute("href") : null;
    });
    expect(favicon).toBeTruthy();
    expect(favicon).toContain("image/svg+xml");
  });

  test("the footer does not leak into a Plain HTML export", async ({ page }) => {
    await openInline(page);
    await expect(page.locator("#cmFooter")).toBeVisible();
    await openToolbarMenu(page);
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#btnSavePlainTop")]);
    const out = await readDownload(dl);
    expect(out).not.toContain('id="cmFooter"');
  });

  test("the overflow-menu Show button reopens the panel", async ({ page }) => {
    await openInline(page);
    // Ensure the panel is closed first (the toolbar toggle is hidden while it is open).
    if (await page.evaluate(() => document.body.classList.contains("sidebar-open"))) {
      await page.click("#btnCloseSidebar");
    }
    await expect(page.locator("body")).not.toHaveClass(/sidebar-open/);
    await openToolbarMenu(page);
    await page.click("#btnShowTop");
    await expect(page.locator("body")).toHaveClass(/sidebar-open/);
  });

  test("the collapsed toolbar toggle reads Show and gets a filled bubble", async ({ page }) => {
    await openInline(page);
    if (await page.evaluate(() => document.body.classList.contains("sidebar-open"))) {
      await page.click("#btnCloseSidebar");
    }
    const toggle = page.locator("#btnToggleSidebar");
    await expect(toggle).toHaveText("Show");
    // Collapsed Show button is filled (a non-transparent background) so it stands out.
    const bg = await toggle.evaluate(el => getComputedStyle(el).backgroundColor);
    expect(bg).not.toBe("rgba(0, 0, 0, 0)");
    expect(bg).not.toBe("transparent");
  });
});
