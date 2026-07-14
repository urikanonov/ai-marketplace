import { test, expect } from "@playwright/test";
import { openKitchenSink, addTextComment } from "./helpers.js";

async function openSidebarPanel(page) {
  if (!(await page.evaluate(() => document.body.classList.contains("sidebar-open")))) {
    await page.click("#btnToggleSidebar");
  }
  await expect(page.locator("body")).toHaveClass(/sidebar-open/);
}

test.describe("comment search / filter", () => {
  test("filters the comment list case-insensitively with a shown/total count and a clear button (CMH-SEARCH-01)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "cmhsearch alpha apple", 0);
    await addTextComment(page, "#commentRoot section p", "cmhsearch beta melon", 1);
    await addTextComment(page, "#commentRoot section p", "cmhsearch gamma apple", 2);
    await openSidebarPanel(page);

    const input = page.locator("#cmSearchInput");
    const count = page.locator("#cmSearchCount");
    const visible = page.locator("#commentList .cm-card[data-cid]:visible");
    const clear = page.locator("#cmSearchClear");

    await expect(input).toBeVisible();
    await expect(visible).toHaveCount(3);
    await expect(count).toHaveText("3 / 3");
    await expect(clear).toBeHidden();

    // Case-insensitive substring: two notes contain "apple".
    await input.fill("APPLE");
    await expect(visible).toHaveCount(2);
    await expect(count).toHaveText("2 / 3");
    await expect(clear).toBeVisible();

    await input.fill("melon");
    await expect(visible).toHaveCount(1);
    await expect(count).toHaveText("1 / 3");

    // The clear (X) button empties the field and restores every card.
    await clear.click();
    await expect(input).toHaveValue("");
    await expect(visible).toHaveCount(3);
    await expect(count).toHaveText("3 / 3");
    await expect(clear).toBeHidden();
  });

  test("a search that matches nothing shows a no-results note and a zero shown count (CMH-SEARCH-02)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "cmhsearch alpha apple", 0);
    await addTextComment(page, "#commentRoot section p", "cmhsearch beta melon", 1);
    await openSidebarPanel(page);

    await page.locator("#cmSearchInput").fill("zzznomatch");
    await expect(page.locator("#commentList .cm-card[data-cid]:visible")).toHaveCount(0);
    await expect(page.locator("#cmSearchCount")).toHaveText("0 / 2");
    await expect(page.locator("#commentList .cm-search-empty")).toBeVisible();
  });

  test("the search row is hidden until there is at least one comment (CMH-SEARCH-03)", async ({ page }) => {
    await openKitchenSink(page);
    await openSidebarPanel(page);
    await expect(page.locator(".head-search")).toBeHidden();
    await addTextComment(page, "#commentRoot section p", "cmhsearch first", 0);
    await expect(page.locator(".head-search")).toBeVisible();
  });
});
