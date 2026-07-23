import { test, expect } from "@playwright/test";
import fs from "fs";
import { openKitchenSink, addTextComment, stageContent, fileUrl, ready } from "./helpers.js";

async function openSidebarPanel(page) {
  if (!(await page.evaluate(() => document.body.classList.contains("sidebar-open")))) {
    await page.click("#btnToggleSidebar");
  }
  await expect(page.locator("body")).toHaveClass(/sidebar-open/);
}

test.describe("comment search / filter", () => {
  test.use({ locale: "tr-TR" });

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

  test("search matches only the comment note, not the quoted anchor text (CMH-SEARCH-04)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "zzznoteonly", 0);
    await openSidebarPanel(page);

    const input = page.locator("#cmSearchInput");
    const visible = page.locator("#commentList .cm-card[data-cid]:visible");
    await expect(visible).toHaveCount(1);

    // Pull a distinctive word out of the QUOTED anchor text that is NOT in the note.
    const quoteWord = await page.evaluate(() => {
      const q = document.querySelector("#commentList .cm-card[data-cid] .quote");
      const words = (q ? q.textContent : "").trim().split(/\s+/)
        .filter((w) => w.length >= 4 && !/zzznoteonly/i.test(w));
      return words[0] || "";
    });
    expect(quoteWord.length).toBeGreaterThan(0);

    // Searching a quote-only word must NOT match: the filter looks only at the comment note.
    await input.fill(quoteWord);
    await expect(visible).toHaveCount(0);
    await expect(page.locator("#cmSearchCount")).toHaveText("0 / 1");

    // The reviewer's own note text still matches.
    await input.fill("zzznoteonly");
    await expect(visible).toHaveCount(1);
    await expect(page.locator("#cmSearchCount")).toHaveText("1 / 1");
  });

  test("search ignores section paths and pin labels (CMH-SEARCH-04)", async ({ page }) => {
    const staged = stageContent(`
<section>
  <h2>cmhsectionprobe heading</h2>
  <p>Anchor text for the section-path search guard.</p>
  <pre><code class="language-cmhpinprobe">const answer = 42;</code></pre>
</section>`, { key: "cmh-search-excluded-fields" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addTextComment(page, "#commentRoot section p", "search-note-section-only", 0);
      await addTextComment(page, "#commentRoot pre code", "search-note-pin-only", 0);
      await openSidebarPanel(page);

      const input = page.locator("#cmSearchInput");
      const visible = page.locator("#commentList .cm-card[data-cid]:visible");
      await expect(visible).toHaveCount(2);

      await input.fill("cmhsectionprobe");
      await expect(visible).toHaveCount(0);
      await expect(page.locator("#cmSearchCount")).toHaveText("0 / 2");

      await input.fill("cmhpinprobe");
      await expect(visible).toHaveCount(0);
      await expect(page.locator("#cmSearchCount")).toHaveText("0 / 2");

      await input.fill("search-note-pin-only");
      await expect(visible).toHaveCount(1);
      await expect(page.locator("#cmSearchCount")).toHaveText("1 / 2");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("the search field shows its full placeholder even at the minimum panel width (CMH-SEARCH-05)", async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 800 });
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "note so the search row appears");
    await openSidebarPanel(page);
    // Shrink the panel to its enforced minimum width.
    const handle = page.locator("#sidebarResizeHandle");
    await handle.focus();
    await page.keyboard.press("Home");
    const input = page.locator("#cmSearchInput");
    await expect(input).toBeVisible();
    // The full "Search comments" placeholder fits in the input without horizontal clipping.
    const clip = await input.evaluate((el) => {
      const probe = el.value;
      el.value = el.getAttribute("placeholder");
      void el.getBoundingClientRect();
      const c = Math.max(0, el.scrollWidth - el.clientWidth);
      el.value = probe;
      return c;
    });
    expect(clip).toBeLessThanOrEqual(0.5);
  });

  test("search matches canonically equivalent NFC and NFD note text (CMH-SEARCH-06)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "Cafe\u0301 review");
    await openSidebarPanel(page);

    await page.locator("#cmSearchInput").fill("Caf\u00e9");
    await expect(page.locator("#commentList .cm-card[data-cid]:visible")).toHaveCount(1);
    await expect(page.locator("#cmSearchCount")).toHaveText("1 / 1");
  });

  test("search applies locale-aware casing for Turkish dotless I (CMH-SEARCH-07)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "IRMAK review");
    await openSidebarPanel(page);

    await page.locator("#cmSearchInput").fill("\u0131rmak");
    await expect(page.locator("#commentList .cm-card[data-cid]:visible")).toHaveCount(1);
    await expect(page.locator("#cmSearchCount")).toHaveText("1 / 1");
  });
});
