const { test, expect, contrastRatio, compositedContrast, PROD } = require("./site-support");

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

test("the auto-updater page keeps the user on the page and links back to the marketplace (SITE-UPDATER-05)", async ({ page }) => {
  await page.goto("/urikan-ai-marketplace-auto-updater/", { waitUntil: "domcontentloaded" });
  // The brand link stays on the auto-updater page (does not jump to the hub).
  await expect(page.locator(".brand")).toHaveAttribute("href", "./");
  // A Marketplace link sits immediately after GitHub and returns to the hub.
  await expect(page.locator(".nav-links a", { hasText: "Marketplace" })).toHaveAttribute("href", "../");
  const links = page.locator(".nav-links a");
  const count = await links.count();
  const texts = [];
  for (let i = 0; i < count; i++) texts.push((await links.nth(i).textContent()).trim());
  expect(texts.indexOf("Marketplace")).toBe(texts.indexOf("GitHub") + 1);
  // The footer points at the plugin's own source tree.
  await expect(page.locator("footer.footer a", { hasText: "Plugin source" }))
    .toHaveAttribute("href", /\/plugins\/urikan-ai-marketplace-auto-updater$/);
});

test("the auto-updater page Why section links the marketplace name to the hub (SITE-UPDATER-07)", async ({ page }) => {
  await page.goto("/urikan-ai-marketplace-auto-updater/", { waitUntil: "domcontentloaded" });
  const link = page.locator('#why a[href="../"]');
  await expect(link).toHaveCount(1);
  await expect(link).toContainText("urikan-ai-marketplace");
  await link.click();
  expect(new URL(page.url()).pathname).toBe("/");
});

test("the auto-updater page renders a changelog section built from its CHANGELOG (SITE-UPDATER-09)", async ({ page }) => {
  await page.goto("/urikan-ai-marketplace-auto-updater/", { waitUntil: "domcontentloaded" });
  // A nav Changelog link and a #changelog section with at least one rendered release.
  await expect(page.locator('.nav-links a[href="#changelog"]')).toHaveCount(1);
  const changelog = page.locator("#changelog .changelog");
  await expect(changelog).toHaveCount(1);
  await expect(changelog.locator(".release").first()).toBeVisible();
  // The section links to the auto-updater's full changelog in source.
  expect(
    await page.locator('#changelog a[href$="urikan-ai-marketplace-auto-updater/CHANGELOG.md"]').count()
  ).toBeGreaterThan(0);
});

test("the auto-updater page describes the session-start hook for both agents (SITE-UPDATER-10)", async ({ page }) => {
  await page.goto("/urikan-ai-marketplace-auto-updater/", { waitUntil: "domcontentloaded" });
  // The "How it works" hook-registration step must describe the hook in a dual-agent way, naming
  // both the Copilot sessionStart hook and the Claude Code SessionStart hook, not a Copilot-only
  // hooks.json. Pin the exact per-agent phrasing so it cannot regress to Copilot-only.
  const howText = await page.locator("#how").innerText();
  expect(howText).toContain("Copilot");
  expect(howText).toContain("Claude Code");
  expect(howText).toContain("sessionStart");
  expect(howText).toContain("SessionStart");
});

test("the auto-updater hero gives a complete self-update command for both agents (SITE-UPDATER-11)", async ({ page }) => {
  await page.goto("/urikan-ai-marketplace-auto-updater/", { waitUntil: "domcontentloaded" });
  // The updater excludes itself, so the hero must show the FULL self-update command for each agent
  // (binary + plugin name + marketplace), not a bare/invalid `plugin update`.
  const heroText = await page.locator(".hero").innerText();
  expect(heroText).toContain("copilot plugin update urikan-ai-marketplace-auto-updater@urikan-ai-marketplace");
  expect(heroText).toContain("claude plugin update urikan-ai-marketplace-auto-updater@urikan-ai-marketplace");
});

test("the auto-updater hero states the accurate Claude update-apply timing (SITE-UPDATER-12)", async ({ page }) => {
  await page.goto("/urikan-ai-marketplace-auto-updater/", { waitUntil: "domcontentloaded" });
  // The hook FETCHES updates on session start; Claude Code applies a plugin update on the next
  // restart (see the marketplace-update SKILL.md). The hero must not overstate this as updates being
  // instantly "already there next time you open" - it must note the next-restart apply timing.
  const heroText = await page.locator(".hero").innerText();
  expect(heroText).toContain("next restart");
  expect(heroText).not.toContain("already there next time you open");
});
