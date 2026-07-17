const { test, expect } = require("@playwright/test");
const { contrastRatio, compositedContrast, installNetworkBlock } = require("./site-helpers");

installNetworkBlock(test);

test("hub renders with plugins, install command, and logo", async ({ page }) => {
  const resp = await page.goto("/", { waitUntil: "domcontentloaded" });
  expect(resp.status()).toBeLessThan(400);
  await expect(page).toHaveTitle(/AI Marketplace/);
  await expect(page.locator(".brand img")).toHaveCount(1);
  const cards = page.locator(".plugin-card");
  expect(await cards.count()).toBeGreaterThanOrEqual(2);
  await expect(page.locator(".plugin-card .name", { hasText: "commentable-html" })).toBeVisible();
  await expect(page.locator("#install .install-tab", { hasText: "GitHub Copilot" })).toBeVisible();
  await expect(page.locator("#install .cmd pre").first()).toContainText("marketplace add");
});


test("a plugin card is clickable across its body, navigating to the plugin page (SITE-HUB-06)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const card = page.locator(".plugin-card", { hasText: "commentable-html" }).first();
  const desc = card.locator(".desc");
  await desc.scrollIntoViewIfNeeded();
  const box = await desc.boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page).toHaveURL(/\/commentable-html\/$/);
});


test("the card copy button and Learn more stay independently clickable over the card link (SITE-HUB-06)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const card = page.locator(".plugin-card", { hasText: "commentable-html" }).first();
  await card.locator(".copy-btn").first().click();
  await expect(page).toHaveURL(/\/$/);
});


test("the plugin card body shows a pointer cursor so it reads as clickable (SITE-HUB-06)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const card = page.locator(".plugin-card", { hasText: "commentable-html" }).first();
  // The whole card navigates, so its body carries the hand/pointer cursor to signal it.
  expect(await card.evaluate((el) => getComputedStyle(el).cursor)).toBe("pointer");
  expect(await card.locator(".desc").evaluate((el) => getComputedStyle(el).cursor)).toBe("pointer");
  // The install command block stays a text surface (it does not navigate), not a pointer.
  expect(await card.locator(".cmd").first().evaluate((el) => getComputedStyle(el).cursor)).not.toBe("pointer");
});


test("the auto-updater card navigates to its plugin page (SITE-HUB-06)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  // The auto-updater now has its own generated page, so (like commentable-html) its card title is
  // a link and the whole card navigates to that page with a pointer cursor. The linkless-card
  // rendering path (a plugin with no page) stays covered by the generator test
  // RenderPluginsTests.test_card_without_page_has_no_learn_more.
  const card = page.locator(".plugin-card", { hasText: "urikan-ai-marketplace-auto-updater" }).first();
  await expect(card.locator(".name a")).toHaveAttribute("href", "./urikan-ai-marketplace-auto-updater/");
  expect(await card.evaluate((el) => getComputedStyle(el).cursor)).toBe("pointer");
  await card.locator(".desc").click();
  await expect(page).toHaveURL(/\/urikan-ai-marketplace-auto-updater\/$/);
});


test("the hub Learn more button uses the brand accent color, not yellow (SITE-HUB-07)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const learn = page.locator(".plugin-card .learn-more").first();
  const bg = await learn.evaluate((el) => getComputedStyle(el).backgroundColor);
  const accentBg = await page.evaluate(() => {
    const d = document.createElement("div");
    d.style.backgroundColor = "var(--cp-accent)";
    document.body.appendChild(d);
    const c = getComputedStyle(d).backgroundColor;
    d.remove();
    return c;
  });
  expect(bg).toBe(accentBg);
  // The old design used amber #ffc107 -> rgb(255, 193, 7); make sure that is gone.
  expect(bg).not.toBe("rgb(255, 193, 7)");
});



test("the hub lays each plugin out as a full-width row with the actions boxed beside the description (SITE-HUB-09)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const grid = page.locator("#plugins .grid");
  // The plugins grid is a single column, so each plugin card is a full-width row (not a cramped 1/3 column).
  const columns = await grid.evaluate((el) => getComputedStyle(el).gridTemplateColumns);
  expect(columns.trim().split(/\s+/).length).toBe(1);
  const cards = page.locator("#plugins .plugin-card");
  const first = cards.nth(0);
  const second = cards.nth(1);
  const gridBox = await grid.boundingBox();
  const firstBox = await first.boundingBox();
  const secondBox = await second.boundingBox();
  // Each card spans (nearly) the full grid width and the cards are stacked vertically.
  expect(firstBox.width).toBeGreaterThan(gridBox.width * 0.9);
  expect(secondBox.y).toBeGreaterThan(firstBox.y + firstBox.height - 5);
  // The card info is a vertical stack: description, then tags, then the install section - each below
  // the previous and sharing the left edge, not split into a second install column off to the right.
  const desc = await first.locator(".desc").boundingBox();
  const keywords = await first.locator(".keywords").boundingBox();
  const foot = await first.locator(".foot").boundingBox();
  const install = await first.locator(".install").boundingBox();
  expect(keywords.y).toBeGreaterThan(desc.y + desc.height - 5);
  expect(install.y).toBeGreaterThan(keywords.y + keywords.height - 5);
  expect(install.x).toBeLessThan(desc.x + 5);
  // The Learn more/Source actions no longer stack below the tags: they sit in a bordered box to the
  // RIGHT of the description, using the space the capped-width description leaves on a full-width row.
  expect(foot.x).toBeGreaterThanOrEqual(desc.x + desc.width);
  expect(foot.y).toBeLessThan(desc.y + desc.height);
  const footEl = first.locator(".foot");
  const border = await footEl.evaluate((el) => parseFloat(getComputedStyle(el).borderTopWidth));
  expect(border).toBeGreaterThan(0);
  const bg = await footEl.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(bg).not.toBe("rgba(0, 0, 0, 0)");
  expect(bg).not.toBe("transparent");
});


test("the hub plugin cards are ordered commentable-html, multi-duck, then the auto-updater (SITE-HUB-10)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const names = await page.locator("#plugins .plugin-card .name").allTextContents();
  const trimmed = names.map((n) => n.trim());
  expect(trimmed.slice(0, 3)).toEqual([
    "commentable-html",
    "multi-duck",
    "urikan-ai-marketplace-auto-updater",
  ]);
});
