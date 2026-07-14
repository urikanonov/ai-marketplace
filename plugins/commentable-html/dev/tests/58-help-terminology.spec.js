import { test, expect } from "@playwright/test";
import { openInline, ready, openToolbarMenu } from "./helpers.js";

// Help panel: the About author link and terminology kept in sync with current button labels.

async function openHelp(page) {
  await openInline(page);
  await openToolbarMenu(page);
  await page.click("#btnHelpTop");
  await expect(page.locator(".cm-help")).toBeVisible();
}

test.describe("Help About links the author to their GitHub profile", () => {
  test("the About section wraps the author name in a link to https://github.com/urikanonov (CMH-HELP-AUTHOR-01)", async ({ page }) => {
    await openHelp(page);
    const about = page.locator(".cm-help-about");
    const authorLink = about.locator("a", { hasText: "Uri Kanonov" });
    await expect(authorLink).toHaveCount(1);
    await expect(authorLink).toHaveAttribute("href", "https://github.com/urikanonov");
    await expect(authorLink).toHaveAttribute("target", "_blank");
    await expect(authorLink).toHaveAttribute("rel", /noopener/);
    await expect(authorLink).toHaveAttribute("rel", /noreferrer/);
    await expect(about).toContainText("authored by");
  });

  test("the About section gives the author link a visible affordance and links the changelog (CMH-HELP-AUTHOR-02, CMH-HELP-SITE-02)", async ({ page }) => {
    await openHelp(page);
    const about = page.locator(".cm-help-about");
    const authorLink = about.locator("a", { hasText: "Uri Kanonov" });
    await expect(authorLink).toHaveCSS("text-decoration-line", /underline/);
    const changelog = about.locator("a", { hasText: "Changelog" });
    await expect(changelog).toHaveCount(1);
    await expect(changelog).toHaveAttribute("href", "https://github.com/urikanonov/ai-marketplace/blob/main/plugins/commentable-html/CHANGELOG.md");
    await expect(changelog).toHaveAttribute("target", "_blank");
    await expect(changelog).toHaveAttribute("rel", /noopener/);
    await expect(changelog).toHaveAttribute("rel", /noreferrer/);
  });
});

test.describe("Help terminology matches the current button labels", () => {
  test("the help panel names the board Reset moves and board-moves Reset changes buttons (CMH-HELP-TERMS-01)", async ({ page }) => {
    await openHelp(page);
    const search = page.locator(".cm-help-search-input");
    await search.fill("reset moves");
    const visible = page.locator(".cm-help-topic:visible");
    expect(await visible.count()).toBeGreaterThan(0);
    let found = false;
    for (const t of await visible.all()) {
      const text = await t.innerText();
      if (text.includes("Reset moves") && text.includes("Reset changes")) found = true;
    }
    expect(found).toBe(true);
  });

  test("the help panel uses the exact current export and toolbar labels", async ({ page }) => {
    await openHelp(page);
    const body = page.locator(".cm-help-body");
    for (const label of ["Copy all", "Export as Portable", "Export Offline", "Export to Plain HTML", "Export to Markdown", "Help & About", "Comment on document"]) {
      await expect(body).toContainText(label);
    }
  });
});
