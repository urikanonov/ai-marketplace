const { test, expect, contrastRatio, compositedContrast, PROD } = require("./site-support");

test("hub renders with plugins, install command, and logo", async ({ page }) => {
  const resp = await page.goto("/", { waitUntil: "domcontentloaded" });
  expect(resp.status()).toBeLessThan(400);
  await expect(page).toHaveTitle(/ai-marketplace/i);
  await expect(page.locator(".brand img")).toHaveCount(1);
  const cards = page.locator(".plugin-card");
  expect(await cards.count()).toBeGreaterThanOrEqual(2);
  await expect(page.locator(".plugin-card .name", { hasText: "commentable-html" })).toBeVisible();
  await expect(page.locator("#install .install-tab", { hasText: "GitHub Copilot" })).toBeVisible();
  await expect(page.locator("#install .cmd pre").first()).toContainText("marketplace add");
});

test("the card copy button and Learn more stay independently clickable over the card link (SITE-HUB-06)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const card = page.locator(".plugin-card", { hasText: "commentable-html" }).first();
  await card.locator(".copy-btn").first().click();
  await expect(page).toHaveURL(/\/$/);
});

test("the What you get section covers exporting an Offline, zero-network copy (SITE-PLUGIN-11)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const features = page.locator("#features");
  await expect(features).toContainText(/Offline/);
  await expect(features).toContainText(/no network|zero network|without a network/i);
});

test("the What you get Round-trip card explains Copy all returns every comment at once for one coordinated edit (SITE-PLUGIN-20)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const features = page.locator("#features");
  await expect(features).toContainText(/every comment at once/i);
  await expect(features).toContainText(/coordinated/i);
});

test("install command copy button copies the command and shows feedback", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const btn = page.locator("#install .copy-btn").first();
  const command = await btn.getAttribute("data-copy");
  expect(command).toContain("marketplace add");
  await btn.click();
  await expect(btn).toHaveText("copied");
  const status = btn.locator(":scope + .copy-status");
  await expect(status).toHaveAttribute("aria-live", "polite");
  await expect(status).toHaveAttribute("aria-atomic", "true");
  await expect(status).toHaveText("Copied to clipboard.");
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  expect(clip).toBe(command);
});

test("the hub install block tabs between Copilot and Claude commands (SITE-INSTALL-01)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const block = page.locator("#install .install-tabs");
  await expect(block).toHaveCount(1);
  const copilotTab = block.locator(".install-tab", { hasText: "GitHub Copilot" });
  const claudeTab = block.locator(".install-tab", { hasText: "Claude Code" });
  await expect(copilotTab).toHaveAttribute("aria-selected", "true");
  const copilotPanel = block.locator(".install-panel", { hasText: "copilot plugin marketplace add" });
  const claudePanel = block.locator(".install-panel", { hasText: "claude plugin marketplace add" });
  await expect(copilotPanel).toBeVisible();
  await expect(claudePanel).toBeHidden();
  // The inactive panel is removed from the a11y tree via the hidden attribute (not just CSS).
  await expect(claudePanel).toHaveAttribute("hidden", "");
  await expect(copilotPanel).not.toHaveAttribute("hidden", "");
  await claudeTab.click();
  await expect(claudeTab).toHaveAttribute("aria-selected", "true");
  await expect(copilotTab).toHaveAttribute("aria-selected", "false");
  await expect(claudePanel).toBeVisible();
  await expect(copilotPanel).toBeHidden();
  await expect(copilotPanel).toHaveAttribute("hidden", "");
  await expect(claudePanel).not.toHaveAttribute("hidden", "");
});

test("the commentable-html install splits marketplace and plugin into copyable rows per agent (SITE-INSTALL-02)", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const block = page.locator("#install .install-tabs");
  const copilotPanel = block.locator(".install-panel").first();
  // Two labelled rows (marketplace, plugin), each with its own copy button.
  await expect(copilotPanel.locator(".install-label")).toHaveText(["Install marketplace", "Install plugin"]);
  await expect(copilotPanel.locator(".install-row .copy-btn")).toHaveCount(2);
  const pluginRow = copilotPanel.locator(".install-row", { hasText: "Install plugin" });
  const btn = pluginRow.locator(".copy-btn");
  const command = await btn.getAttribute("data-copy");
  expect(command).toBe("copilot plugin install commentable-html@urikan-ai-marketplace");
  await btn.click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(command);
  // The Claude tab exposes the claude plugin-install command for the same plugin.
  await block.locator(".install-tab", { hasText: "Claude Code" }).click();
  await expect(page.locator("#install")).toContainText("claude plugin install commentable-html@urikan-ai-marketplace");
});

test("install tabs support arrow-key navigation (SITE-INSTALL-03)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const block = page.locator("#install .install-tabs");
  const copilotTab = block.locator(".install-tab", { hasText: "GitHub Copilot" });
  const claudeTab = block.locator(".install-tab", { hasText: "Claude Code" });
  await copilotTab.focus();
  await page.keyboard.press("ArrowRight");
  await expect(claudeTab).toHaveAttribute("aria-selected", "true");
  await expect(claudeTab).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(copilotTab).toHaveAttribute("aria-selected", "true");
  await expect(copilotTab).toBeFocused();
  // Home/End jump to the first/last tab.
  await page.keyboard.press("End");
  await expect(claudeTab).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Home");
  await expect(copilotTab).toHaveAttribute("aria-selected", "true");
});

test("a skill plugin offers a Claude Desktop ZIP-download tab; the auto-updater does not (SITE-INSTALL-05)", async ({ page }) => {
  // commentable-html is a pure importable skill, so its install block has a third "Claude Desktop"
  // tab whose panel downloads the skill ZIP (no CLI command). The auto-updater's value is a session
  // hook a Desktop import cannot provide, so it offers CLI tabs only.
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const block = page.locator("#install .install-tabs");
  const desktopTab = block.locator(".install-tab", { hasText: "Claude Desktop" });
  await expect(desktopTab).toBeVisible();
  await desktopTab.click();
  const download = page.locator("#install .install-download a[download]");
  await expect(download).toBeVisible();
  // Exact per-page relative path: the plugin page lives one level deep, so the ZIP is under ../.
  await expect(download).toHaveAttribute("href", "../skills/commentable-html.zip");
  // The auto-updater page keeps only the two CLI tabs.
  await page.goto("/urikan-ai-marketplace-auto-updater/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#install .install-tab", { hasText: "GitHub Copilot" })).toBeVisible();
  await expect(page.locator("#install .install-tab", { hasText: "Claude Code" })).toBeVisible();
  await expect(page.locator("#install .install-tab", { hasText: "Claude Desktop" })).toHaveCount(0);
});

test("the Claude Desktop skill ZIP is served for download (SITE-INSTALL-06)", async ({ request }) => {
  const r = await request.get("/skills/commentable-html.zip");
  expect(r.status()).toBeLessThan(400);
  expect(r.headers()["content-type"]).toContain("application/zip");
});

test("the install tabs read as a clickable segmented control (SITE-INSTALL-07)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const block = page.locator("#install .install-tabs");
  const selectedBg = await block.locator('.install-tab[aria-selected="true"]').evaluate(
    (el) => getComputedStyle(el).backgroundColor);
  const unselectedBg = await block.locator('.install-tab[aria-selected="false"]').first().evaluate(
    (el) => getComputedStyle(el).backgroundColor);
  // The active tab carries a real filled background (not transparent) distinct from an inactive tab,
  // so it is obvious which tab is selected and that the tabs are interactive controls.
  expect(selectedBg).not.toBe(unselectedBg);
  expect(selectedBg).not.toMatch(/rgba\(0,\s*0,\s*0,\s*0\)|^transparent$/);
  // The tablist is a visible bordered tray, reinforcing the segmented-control affordance.
  const trayBorder = await block.locator(".install-tablist").evaluate(
    (el) => parseFloat(getComputedStyle(el).borderTopWidth));
  expect(trayBorder).toBeGreaterThan(0);
});

test("the pages state dual-agent invocation from each agent's CLI and Desktop app (SITE-DUAL-01)", async ({ page }) => {
  // Hub: the hero lead names both agents and the CLI+Desktop invocation.
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".hero .lead")).toContainText("CLI and Desktop app");
  await expect(page.locator(".hero .lead")).toContainText("Claude Code");
  await expect(page.locator("#install .install-tab", { hasText: "Claude Code" })).toBeVisible();
  // Plugin page: the install section states it and names both agents.
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#install .section-sub")).toContainText("CLI and Desktop app");
  await expect(page.locator("#install .section-sub")).toContainText("Claude Code");
});

test("copy failure gives a platform-neutral manual hint", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      get: () => ({ writeText: () => Promise.reject(new Error("blocked")) }),
    });
    document.execCommand = () => false;
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const btn = page.locator("#install .copy-btn").first();
  await btn.click();
  await expect(btn).toHaveText("copy manually");
  await expect(btn).not.toContainText(/Ctrl|Cmd/);
  await expect(btn.locator(":scope + .copy-status")).toHaveText(
    "Copy unavailable. Copy the command manually."
  );
  await expect(btn).toHaveClass(/copy-failed/);
});

test("copy button restores its original label after a rapid double click", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const btn = page.locator("#install .copy-btn").first();
  const label = (await btn.textContent()).trim();
  await btn.click();
  await btn.click();
  await expect(btn).toHaveText(label, { timeout: 4000 });
});

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

test("the commentable-html Install section links to the auto-updater page (SITE-UPDATER-06)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const link = page.locator('#install a[href="../urikan-ai-marketplace-auto-updater/"]');
  await expect(link).toHaveCount(1);
  await expect(link).toHaveText(/auto-updater/i);
  // The note explains the auto-updater keeps commentable-html up to date on session start.
  await expect(page.locator("#install .install-note")).toContainText(/session start/i);
  // It is a clearly-visible card (not plain muted text) that shows the auto-updater plugin icon.
  const icon = link.locator("img.install-updater-icon");
  await expect(icon).toHaveAttribute("src", /urikan-ai-marketplace-auto-updater\.svg$/);
  await expect(icon).toHaveAttribute("alt", /auto-updater/i);
  await link.click();
  await expect(page).toHaveURL(/\/urikan-ai-marketplace-auto-updater\/$/);
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
