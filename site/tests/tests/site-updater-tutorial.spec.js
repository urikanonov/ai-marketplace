const { test, expect } = require("@playwright/test");
const { contrastRatio, compositedContrast, installNetworkBlock } = require("./site-helpers");

installNetworkBlock(test);

test("the auto-updater page renders its pitch: hero logo, version badge, features, and install (SITE-UPDATER-04)", async ({ page }) => {
  await page.goto("/urikan-ai-marketplace-auto-updater/", { waitUntil: "domcontentloaded" });
  // Hero identity: the dedicated brand logo with descriptive alt text and a semver version badge.
  const logo = page.locator(".hero-logo");
  await expect(logo).toHaveCount(1);
  await expect(logo).toHaveAttribute("alt", /auto-updater/i);
  await expect(page.locator(".hero .badge.version")).toHaveText(/^v\d+\.\d+\.\d+$/);
  // A full pitch: at least four feature cards and the split marketplace + plugin install rows.
  expect(await page.locator("#features .card.feature").count()).toBeGreaterThanOrEqual(4);
  await expect(page.locator("#install .cmd pre", {
    hasText: "copilot plugin install urikan-ai-marketplace-auto-updater@urikan-ai-marketplace",
  })).toHaveCount(1);
  // The auto-updater is now dual-agent (Claude Code + GitHub Copilot CLI), so it has both tabs.
  await expect(page.locator("#install .install-tab", { hasText: "GitHub Copilot" })).toBeVisible();
  const updaterClaudeTab = page.locator("#install .install-tab", { hasText: "Claude Code" });
  await expect(updaterClaudeTab).toBeVisible();
  await updaterClaudeTab.click();
  await expect(page.locator("#install")).toContainText(
    "claude plugin install urikan-ai-marketplace-auto-updater@urikan-ai-marketplace");
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


test("the commentable-html Install section links to the auto-updater install section (SITE-UPDATER-06)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const link = page.locator('#install a[href="../urikan-ai-marketplace-auto-updater/#install"]');
  await expect(link).toHaveCount(1);
  await expect(link).toHaveText(/auto-updater/i);
  // The note explains the auto-updater keeps commentable-html up to date on session start.
  await expect(page.locator("#install .install-note")).toContainText(/session start/i);
  // It is a clearly-visible card (not plain muted text) that shows the auto-updater plugin icon.
  const icon = link.locator("img.install-updater-icon");
  await expect(icon).toHaveAttribute("src", /urikan-ai-marketplace-auto-updater\.svg$/);
  await expect(icon).toHaveAttribute("alt", /auto-updater/i);
  await link.click();
  await expect(page).toHaveURL(/\/urikan-ai-marketplace-auto-updater\/#install$/);
});


test("the commentable-html nav has an Install link to the install section (SITE-PLUGIN-18)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const install = page.locator(".nav-links a", { hasText: "Install" }).first();
  await expect(install).toHaveAttribute("href", "#install");
  // It stays visible on small screens (unlike Privacy/Changelog, which carry hide-sm).
  await expect(install).not.toHaveClass(/hide-sm/);
  await install.click();
  await expect(page).toHaveURL(/#install$/);
});


test("the auto-updater page Why section links the marketplace name to the hub (SITE-UPDATER-07)", async ({ page }) => {
  await page.goto("/urikan-ai-marketplace-auto-updater/", { waitUntil: "domcontentloaded" });
  const link = page.locator('#why a[href="../"]');
  await expect(link).toHaveCount(1);
  await expect(link).toContainText("urikan-ai-marketplace");
  await link.click();
  expect(new URL(page.url()).pathname).toBe("/");
});


test("the auto-updater install note is clearly spaced below the command box (SITE-UPDATER-08)", async ({ page }) => {
  await page.goto("/urikan-ai-marketplace-auto-updater/", { waitUntil: "domcontentloaded" });
  const note = page.locator("#install .install-note");
  await expect(note).toContainText(/PowerShell/i);
  // A visible vertical gap between the command box and the PowerShell note (not cramped against it).
  const gap = await page.evaluate(() => {
    const cmd = document.querySelector("#install .cmd").getBoundingClientRect();
    const note = document.querySelector("#install .install-note").getBoundingClientRect();
    return note.top - cmd.bottom;
  });
  expect(gap).toBeGreaterThanOrEqual(12);
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


test("the auto-updater install section gives a complete self-update command for both agents (SITE-UPDATER-11)", async ({ page }) => {
  await page.goto("/urikan-ai-marketplace-auto-updater/", { waitUntil: "domcontentloaded" });
  // The updater excludes itself, so the page must show the FULL self-update command for each agent
  // (binary + plugin name + marketplace), not a bare/invalid `plugin update`. It lives in the
  // Install-section note, not the hero, so the hero pitch stays short.
  const note = page.locator("#install .install-selfupdate");
  await expect(note).toContainText("copilot plugin update urikan-ai-marketplace-auto-updater@urikan-ai-marketplace");
  await expect(note).toContainText("claude plugin update urikan-ai-marketplace-auto-updater@urikan-ai-marketplace");
  // The hero no longer crams the commands into its pitch.
  const heroText = await page.locator(".hero").innerText();
  expect(heroText).not.toContain("plugin update urikan-ai-marketplace-auto-updater");
});


test("the auto-updater states the accurate Claude update-apply timing (SITE-UPDATER-12)", async ({ page }) => {
  await page.goto("/urikan-ai-marketplace-auto-updater/", { waitUntil: "domcontentloaded" });
  // The hook FETCHES updates on session start; Claude Code applies a plugin update on the next
  // restart (see the marketplace-update SKILL.md). The Install-section self-update note states this,
  // and the page must not overstate updates as instantly "already there next time you open".
  const note = page.locator("#install .install-selfupdate");
  await expect(note).toContainText("next restart");
  const bodyText = await page.locator("body").innerText();
  expect(bodyText).not.toContain("already there next time you open");
});


test("the full-screen button has a light-red (accent-tinted) background", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const bg = await page.locator("#demo-fullscreen").evaluate(
    (el) => getComputedStyle(el).backgroundColor
  );
  const m = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  expect(m, "unexpected background color: " + bg).not.toBeNull();
  const [r, g, b] = [Number(m[1]), Number(m[2]), Number(m[3])];
  // A light red tint: red channel clearly dominant and the fill is light.
  expect(r).toBeGreaterThan(g);
  expect(r).toBeGreaterThan(b);
  expect(r).toBeGreaterThan(220);
});


test("clicking a tutorial image opens a full-size lightbox that Escape closes", async ({ page }) => {
  await page.goto("/commentable-html/tutorial/", { waitUntil: "domcontentloaded" });
  const overlay = page.locator(".lightbox");
  await expect(overlay).toBeHidden();
  const firstImg = page.locator(".tutorial img").first();
  const src = await firstImg.getAttribute("src");
  await firstImg.click();
  await expect(overlay).toBeVisible();
  expect(await overlay.locator("img").getAttribute("src")).toContain(src);
  await page.keyboard.press("Escape");
  await expect(overlay).toBeHidden();
  // Escape restores focus to the clicked image itself, not just document.activeElement.
  await expect(firstImg).toBeFocused();
});


test("tutorial image lightbox opens via keyboard, traps Tab, and restores focus on close (SITE-TUT-07)", async ({ page }) => {
  await page.goto("/commentable-html/tutorial/", { waitUntil: "domcontentloaded" });
  const overlay = page.locator(".lightbox");
  await expect(overlay).toBeHidden();
  const firstImg = page.locator(".tutorial img").first();
  await expect(firstImg).toHaveAttribute("tabindex", "0");
  await expect(firstImg).toHaveAttribute("role", "button");
  await expect(firstImg).toHaveAttribute("aria-label", /.+/);
  await firstImg.focus();
  await page.keyboard.press("Enter");
  await expect(overlay).toBeVisible();
  // Opening moves focus into the overlay (the close button).
  await expect(overlay.locator(".lightbox-close")).toBeFocused();
  const isInsideOverlay = () => page.evaluate(
    () => document.querySelector(".lightbox").contains(document.activeElement));
  await page.keyboard.press("Tab");
  expect(await isInsideOverlay()).toBe(true);
  await page.keyboard.press("Shift+Tab");
  expect(await isInsideOverlay()).toBe(true);
  await page.keyboard.press("Escape");
  await expect(overlay).toBeHidden();
  await expect(firstImg).toBeFocused();

  // Reopening a *different* image and closing via the close button (not Escape)
  // also restores focus to that specific image, not the first one.
  const secondImg = page.locator(".tutorial img").nth(1);
  await secondImg.focus();
  await secondImg.press("Enter");
  await expect(overlay).toBeVisible();
  await overlay.locator(".lightbox-close").click();
  await expect(overlay).toBeHidden();
  await expect(secondImg).toBeFocused();

  // The Space key also activates the trigger (not just Enter).
  const thirdImg = page.locator(".tutorial img").nth(2);
  await thirdImg.focus();
  await page.keyboard.press(" ");
  await expect(overlay).toBeVisible();
  await expect(overlay.locator(".lightbox-close")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(overlay).toBeHidden();
  await expect(thirdImg).toBeFocused();

  // Clicking the backdrop (outside the image) also dismisses and restores focus.
  await thirdImg.focus();
  await page.keyboard.press(" ");
  await expect(overlay).toBeVisible();
  await overlay.click({ position: { x: 5, y: 5 } });
  await expect(overlay).toBeHidden();
  await expect(thirdImg).toBeFocused();
});


test("tutorial brand keeps the user in the commentable-html section", async ({ page }) => {
  await page.goto("/commentable-html/tutorial/", { waitUntil: "domcontentloaded" });
  // The brand icon returns to the commentable-html plugin home, not the hub root.
  await expect(page.locator(".brand")).toHaveAttribute("href", "../");
});


test("the tutorial page footer matches the commentable-html footer links (SITE-TUT-06)", async ({ page }) => {
  await page.goto("/commentable-html/tutorial/", { waitUntil: "domcontentloaded" });
  const footer = page.locator("footer.footer");
  const link = (name) => footer.getByRole("link", { name, exact: true });
  // Assert the exact hrefs (not just the link text) so a wrong repo/plugin target or a root-relative
  // regression is caught; these must match the commentable-html page footer.
  await expect(link("Contribute")).toHaveAttribute("href", "https://github.com/urikanonov/ai-marketplace/blob/main/CONTRIBUTING.md");
  await expect(link("Request a feature")).toHaveAttribute("href", "https://github.com/urikanonov/ai-marketplace/issues/new?template=feature-request.yml");
  await expect(link("File an issue")).toHaveAttribute("href", "https://github.com/urikanonov/ai-marketplace/issues/new/choose");
  await expect(link("Plugin source")).toHaveAttribute("href", "https://github.com/urikanonov/ai-marketplace/tree/main/plugins/commentable-html");
});


test("tutorial example links open the live demo, not a GitHub blob", async ({ page }) => {
  await page.goto("/commentable-html/tutorial/", { waitUntil: "domcontentloaded" });
  const exampleLinks = page.locator('.tutorial a[href*="report-community-garden.html"]');
  const n = await exampleLinks.count();
  expect(n).toBeGreaterThan(0);
  for (let linkIndex = 0; linkIndex < n; linkIndex++) {
    const href = await exampleLinks.nth(linkIndex).getAttribute("href");
    expect(href).toMatch(/(^|\/)demo\/report-community-garden\.html$/);
    expect(href).not.toContain("github.com");
  }
});


test("the demo frame breaks out of the content column while its heading stays in the content column", async ({ page }) => {
  await page.setViewportSize({ width: 1680, height: 900 });
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const frame = await page.locator("#demo-panel").boundingBox();
  // It is clearly wider than the constrained content column (proving the breakout).
  const wrap = await page.locator("#features .wrap").boundingBox();
  expect(frame.width).toBeGreaterThan(wrap.width + 20);
  // The heading, description, and tabs stay in the content column, aligned with every other
  // section heading (only the frame is full-bleed, not the whole section).
  const demoTitle = await page.locator("#demo .section-title").boundingBox();
  expect(demoTitle.x).toBeGreaterThan(frame.x + 8);
  for (const id of ["#install", "#features", "#loop", "#modes"]) {
    const other = await page.locator(id + " .section-title").boundingBox();
    expect(Math.abs(other.x - demoTitle.x)).toBeLessThanOrEqual(2);
  }
});


test("the full-bleed demo frame keeps a comfortable side buffer inside the viewport (SITE-DEMO-08)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
  const frame = await page.locator("#demo-panel").boundingBox();
  // A ~50px buffer each side (up from ~20px) so the demo no longer runs too wide: the left edge
  // is inset ~50px and the right edge stays that far off the viewport edge.
  expect(frame.x).toBeGreaterThanOrEqual(44);
  expect(frame.x).toBeLessThanOrEqual(56);
  const rightBuffer = clientWidth - (frame.x + frame.width);
  expect(rightBuffer).toBeGreaterThanOrEqual(44);
  expect(rightBuffer).toBeLessThanOrEqual(56);
});


test("the plugin page footer links to contribute, feature request, issues, source, and the author's LinkedIn", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const footer = page.locator("footer.footer");
  await expect(footer.locator("a", { hasText: "Contribute" })).toHaveAttribute("href", /\/CONTRIBUTING\.md$/);
  await expect(footer.locator("a", { hasText: "Request a feature" })).toHaveAttribute("href", /feature-request\.yml$/);
  await expect(footer.locator("a", { hasText: "File an issue" })).toHaveAttribute("href", /\/issues\/new\/choose$/);
  await expect(footer.locator("a", { hasText: "Plugin source" })).toHaveAttribute("href", /\/plugins\/commentable-html$/);
  await expect(footer.locator("a", { hasText: "Uri Kanonov" })).toHaveAttribute("href", /linkedin\.com\/in\/uri-kanonov/);
});



test("the auto-updater and multi-duck pages lead with the Why section and place Install below it (SITE-INSTALL-08)", async ({ page }) => {
  for (const path of ["/urikan-ai-marketplace-auto-updater/", "/multi-duck/"]) {
    await page.goto(path, { waitUntil: "domcontentloaded" });
    const ids = await page.locator("main > section").evaluateAll((els) => els.map((e) => e.id));
    // The rationale (Why) section comes first, right after the hero header.
    expect(ids[0]).toBe("why");
    // ...and the Install section sits below it (not above the rationale).
    expect(ids.indexOf("why")).toBeLessThan(ids.indexOf("install"));
  }
});


test("the multi-duck page recommends running multiple rounds for complex work (SITE-MDUCK-04)", async ({ page }) => {
  await page.goto("/multi-duck/", { waitUntil: "domcontentloaded" });
  const callout = page.locator(".callout", { hasText: "Run it more than once" });
  await expect(callout).toBeVisible();
  await expect(callout).toContainText(/several rounds|multiple rounds|number of rounds/i);
  await expect(callout).toContainText(/complex/i);
});
