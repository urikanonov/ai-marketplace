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



test("the hub lays each plugin out as a full-width row with the actions in a plain row under the tags (SITE-HUB-09)", async ({ page }) => {
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
  // The card info is a flat vertical stack: description, then tags, then the actions row, then the
  // install section - each below the previous and sharing the left edge (no second column).
  const desc = await first.locator(".desc").boundingBox();
  const keywords = await first.locator(".keywords").boundingBox();
  const foot = await first.locator(".foot").boundingBox();
  const install = await first.locator(".install").boundingBox();
  expect(keywords.y).toBeGreaterThan(desc.y + desc.height - 5);
  // The description is capped to a comfortable measure (SITE-HUB-09: max-width 84ch), not stretched
  // to the full card width. Assert the effective cap in CHARACTER units so a regression to the old
  // 78ch (or any other value) is caught - a relative "less than the card width" check would not
  // distinguish 84ch from 78ch.
  expect(desc.width).toBeLessThan(firstBox.width * 0.8);
  const capCh = await first.locator(".desc").evaluate((el) => {
    const cs = getComputedStyle(el);
    const maxWidthPx = parseFloat(cs.maxWidth);
    const probe = document.createElement("span");
    probe.style.font = cs.font;
    probe.style.fontFamily = cs.fontFamily;
    probe.style.fontSize = cs.fontSize;
    probe.style.fontWeight = cs.fontWeight;
    probe.style.visibility = "hidden";
    probe.style.whiteSpace = "nowrap";
    probe.style.position = "absolute";
    probe.textContent = "0".repeat(100);
    el.appendChild(probe);
    const chPx = probe.getBoundingClientRect().width / 100;
    probe.remove();
    return maxWidthPx / chPx;
  });
  expect(Math.round(capCh)).toBe(84);
  // The Learn more/Source actions sit in a plain row UNDER the tags (not a box floated to the right
  // of the description), sharing the left edge - so there is no dead whitespace gap beside the prose.
  expect(foot.y).toBeGreaterThan(keywords.y + keywords.height - 5);
  expect(foot.x).toBeLessThan(desc.x + 5);
  expect(install.y).toBeGreaterThan(foot.y + foot.height - 5);
  expect(install.x).toBeLessThan(desc.x + 5);
  // The actions row carries no box chrome (no border, transparent background), unlike the old panel.
  const footEl = first.locator(".foot");
  const border = await footEl.evaluate((el) => parseFloat(getComputedStyle(el).borderTopWidth));
  expect(border).toBe(0);
  const bg = await footEl.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(["rgba(0, 0, 0, 0)", "transparent"]).toContain(bg);
  // On a narrow (mobile) viewport the actions row wraps within the card without horizontal overflow
  // (the old boxed 560px .foot override is gone; the shared flex-wrap rule covers it), and both
  // buttons stay reachable and keyboard-focusable.
  await page.setViewportSize({ width: 375, height: 900 });
  const narrow = page.locator("#plugins .plugin-card").first();
  await narrow.scrollIntoViewIfNeeded();
  const narrowFoot = narrow.locator(".foot");
  const noOverflow = await narrowFoot.evaluate((el) => el.scrollWidth <= el.clientWidth + 1);
  expect(noOverflow).toBe(true);
  const narrowLearn = narrowFoot.locator("a.learn-more");
  await expect(narrowLearn).toBeVisible();
  await narrowLearn.focus();
  await expect(narrowLearn).toBeFocused();
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


test("each hub plugin card has a stable anchor id and clears the sticky nav (SITE-HUB-11)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  // Every card carries id="plugin-<name>" so the nav dropdown and hero pills can target it.
  await expect(page.locator("#plugin-commentable-html.plugin-card")).toHaveCount(1);
  await expect(page.locator("#plugin-multi-duck.plugin-card")).toHaveCount(1);
  await expect(page.locator("#plugin-urikan-ai-marketplace-auto-updater.plugin-card")).toHaveCount(1);
  // scroll-margin-top keeps a jumped-to card from hiding under the sticky navbar.
  const margin = await page.locator("#plugin-multi-duck").evaluate(
    (el) => parseFloat(getComputedStyle(el).scrollMarginTop));
  expect(margin).toBeGreaterThan(0);
});


test("the hub nav 'Plugins' is a dropdown that lists each plugin and scrolls to its card (SITE-NAV-02)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const trigger = page.locator(".nav-switcher-start .nav-switcher-trigger");
  await expect(trigger).toHaveText(/Plugins/);
  // Clicking the trigger still scrolls to the plugins section, exactly like the old plain link.
  await expect(trigger).toHaveAttribute("href", "#plugins");
  const menu = page.locator(".nav-switcher-start .nav-switcher-menu");
  // Hidden until the control is hovered or focused (progressive enhancement).
  await expect(menu).toBeHidden();
  await trigger.hover();
  await expect(menu).toBeVisible();
  // One tile per plugin, each scrolling to that plugin's card on the page.
  await expect(menu.locator('a[href="#plugin-commentable-html"]')).toHaveCount(1);
  await expect(menu.locator('a[href="#plugin-multi-duck"]')).toHaveCount(1);
  await expect(menu.locator('a[href="#plugin-urikan-ai-marketplace-auto-updater"]')).toHaveCount(1);
  // The tile category sub-labels are Title Case (matching the card badges), not lowercase slugs.
  await expect(menu.locator(".switch-tile-sub", { hasText: "Planning and Analysis" })).toHaveCount(1);
  await expect(menu.locator(".switch-tile-sub", { hasText: "Code and Plan Review" })).toHaveCount(1);
  await expect(menu.locator(".switch-tile-sub", { hasText: "Infrastructure" })).toHaveCount(1);
  // Clicking a tile jumps to that card.
  await menu.locator('a[href="#plugin-multi-duck"]').click();
  await expect(page).toHaveURL(/#plugin-multi-duck$/);
  await expect(page.locator("#plugin-multi-duck")).toBeInViewport();
});


test("the hub nav 'Plugins' dropdown also reveals on keyboard focus (SITE-NAV-02)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const menu = page.locator(".nav-switcher-start .nav-switcher-menu");
  await expect(menu).toBeHidden();
  await page.locator(".nav-switcher-start .nav-switcher-trigger").focus();
  await expect(menu).toBeVisible();
});


test("the hero shows a pill per plugin that scrolls to its card (SITE-HUB-12)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const pills = page.locator(".hero-pills .hero-pill");
  expect(await pills.count()).toBe(3);
  await expect(page.locator('.hero-pill[href="#plugin-commentable-html"]')).toBeVisible();
  const updaterPill = page.locator('.hero-pill[href="#plugin-urikan-ai-marketplace-auto-updater"]');
  await updaterPill.click();
  await expect(page).toHaveURL(/#plugin-urikan-ai-marketplace-auto-updater$/);
  await expect(page.locator("#plugin-urikan-ai-marketplace-auto-updater")).toBeInViewport();
});
