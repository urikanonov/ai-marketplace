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
    for (const label of ["Copy all", "Export as Shareable", "Export Offline", "Export to Plain HTML", "Export to Markdown", "Save as PDF", "Help & About", "Comment on document"]) {
      await expect(body).toContainText(label);
    }
  });

  test("the panel-and-toolbar topic describes the composite header ribbon, Search, and More menu (CMH-HELP-TERMS-01)", async ({ page }) => {
    await openHelp(page);
    const search = page.locator(".cm-help-search-input");
    // The panel-and-toolbar topic must name the redesigned composite header: the captioned ribbon
    // (Search, Sort, More, Help, Hide), the Copy all / Export primary row, and the More menu that now
    // holds Manage storage and Clear all comments.
    await search.fill("panel and toolbar");
    const panelTopic = page.locator(".cm-help-topic:visible", { hasText: "The panel and toolbar" });
    await expect(panelTopic).toHaveCount(1);
    const panelText = await panelTopic.innerText();
    for (const label of ["Export", "Sort", "More", "Help", "Hide", "Search", "Copy all", "Manage storage", "Clear all comments"]) {
      expect(panelText, `panel-and-toolbar topic names ${label}`).toContain(label);
    }
    // The collapsed-toolbar sentence names Clear all comments as a second entry point, so a reader
    // working with the panel hidden knows the overflow menu can clear too (CMH-UI-13).
    expect(panelText).toMatch(/collapsed[\s\S]*overflow[\s\S]*Clear all comments/);
    // The managing-storage topic points reviewers at the More menu, not the old Export menu.
    await search.fill("Managing storage");
    const storageTopic = page.locator(".cm-help-topic:visible", { hasText: "Managing storage" });
    await expect(storageTopic).toHaveCount(1);
    const storageText = await storageTopic.innerText();
    expect(storageText).toContain("More menu");
    expect(storageText).not.toContain("Export menu");
    // The managing-comments topic must use the exact current control label, not the old bare "Clear".
    await search.fill("Clear all comments");
    const commentsTopic = page.locator(".cm-help-topic:visible", { hasText: "Managing comments" });
    await expect(commentsTopic).toHaveCount(1);
    const commentsText = await commentsTopic.innerText();
    expect(commentsText).toContain("Clear all comments");
    expect(commentsText).toMatch(/Clear all comments[\s\S]*More[\s\S]*overflow/); // both entry points (CMH-UI-13)
    expect(commentsText).not.toContain("Clear deletes");
  });

  test("a shell without the toolbar Clear item does not advertise it (CMH-HELP-TERMS-01)", async ({ page }) => {
    // An older document's shell can load CURRENT companion assets (same-major runtimes are
    // compatible), so the help copy must describe the chrome THIS document actually has.
    await openInline(page);
    await page.evaluate(() => {
      const b = document.getElementById("btnClearAllTop");
      if (b) b.remove();
    });
    await openToolbarMenu(page);
    await page.click("#btnHelpTop");
    await expect(page.locator(".cm-help")).toBeVisible();
    const search = page.locator(".cm-help-search-input");
    await search.fill("Clear all comments");
    const commentsText = await page.locator(".cm-help-topic:visible", { hasText: "Managing comments" }).innerText();
    expect(commentsText).toContain("Clear all comments"); // the sidebar route is still described
    expect(commentsText).not.toMatch(/Clear all comments[\s\S]*More[\s\S]*overflow/);
    await search.fill("panel and toolbar");
    const panelText = await page.locator(".cm-help-topic:visible", { hasText: "The panel and toolbar" }).innerText();
    expect(panelText).not.toMatch(/collapsed[\s\S]*overflow[\s\S]*Clear all comments/);
  });
});

test.describe("Help documents recently shipped features (issue #655)", () => {
  test("the panel-and-toolbar topic explains the count bubble includes note and checklist changes (CMH-HELP-COUNT-01)", async ({ page }) => {
    await openHelp(page);
    const search = page.locator(".cm-help-search-input");
    await search.fill("count bubble");
    const visible = page.locator(".cm-help-topic:visible");
    expect(await visible.count()).toBeGreaterThan(0);
    let text = "";
    for (const t of await visible.all()) text += "\n" + (await t.innerText());
    expect(text).toMatch(/count bubble/i);
    expect(text).toMatch(/thread/i);
    expect(text).toMatch(/note/i);
    expect(text).toMatch(/checklist/i);
  });

  test("the help panel documents inline replies, author names, and thread export (CMH-HELP-THREADS-01)", async ({ page }) => {
    await openHelp(page);
    const search = page.locator(".cm-help-search-input");
    await search.fill("Threads, replies and author names");
    const topic = page.locator(".cm-help-topic:visible", { hasText: "Threads, replies and author names" });
    await expect(topic).toHaveCount(1);
    const text = await topic.innerText();
    expect(text).toMatch(/Commenting as/);
    expect(text).toMatch(/author pill/i);
    expect(text).toMatch(/inline/i);
    expect(text).toMatch(/oldest first/i);
    expect(text).toMatch(/whole thread/i);
    expect(text).toMatch(/Copy all/);
  });

  test("the managing-storage topic documents the pie chart, Share column, and per-comment browsing (CMH-HELP-STORE-01)", async ({ page }) => {
    await openHelp(page);
    const search = page.locator(".cm-help-search-input");
    await search.fill("pie chart");
    const topic = page.locator(".cm-help-topic:visible", { hasText: "Managing storage" });
    await expect(topic).toHaveCount(1);
    const text = await topic.innerText();
    expect(text).toMatch(/pie chart/i);
    expect(text).toMatch(/Other commentable-html documents/);
    expect(text).toMatch(/Free/);
    expect(text).toMatch(/Share/);
    expect(text).toMatch(/Show comments/);
  });
});
