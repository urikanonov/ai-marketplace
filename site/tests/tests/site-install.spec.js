const { test, expect } = require("@playwright/test");
const { contrastRatio, compositedContrast, installNetworkBlock } = require("./site-helpers");

installNetworkBlock(test);

test("hub embeds the GitHub star widget and its CSP permits it", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("a.github-button")).toHaveCount(1);
  await expect(page.locator('script[src="https://buttons.github.io/buttons.js"]')).toHaveCount(1);
  const csp = await page
    .locator('meta[http-equiv="Content-Security-Policy"]')
    .getAttribute("content");
  expect(csp).toContain("https://buttons.github.io");
  expect(csp, "widget fetches the star count").toContain("https://api.github.com");
  expect(csp, "widget injects a <style>, so style-src must allow 'unsafe-inline'").toMatch(
    /style-src[^;]*'unsafe-inline'/
  );
});


test("plugin pages embed the GitHub star widget and its CSP permits it (SITE-PLUGIN-02)", async ({ page }) => {
  // The plugin pages carry exactly the hub's widget-scoped policy - no more. Asserting the whole
  // string (not just that the required sources are present) makes any future broadening of a
  // directive (an extra origin, 'unsafe-eval', etc.) fail this test, per SITE-PLUGIN-02's
  // "exactly what the widget needs" constraint.
  const EXPECTED_CSP =
    "default-src 'self'; script-src 'self' https://buttons.github.io; " +
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; " +
    "connect-src 'self' https://api.github.com; frame-src 'self' https://buttons.github.io; " +
    "base-uri 'self'; form-action 'self'";
  for (const p of ["/commentable-html/", "/multi-duck/", "/urikan-ai-marketplace-auto-updater/"]) {
    await page.goto(p, { waitUntil: "domcontentloaded" });
    // The widget lives in the hero and degrades to a visible plain repo link when its script is blocked.
    const link = page.locator(".hero a.github-button");
    await expect(link, p + " hero star widget present").toHaveCount(1);
    await expect(link, p + " star widget visible").toBeVisible();
    await expect(link, p + " star widget links to the repo").toHaveAttribute(
      "href",
      "https://github.com/urikanonov/ai-marketplace"
    );
    await expect(
      page.locator('script[src="https://buttons.github.io/buttons.js"]'),
      p + " loads the widget script"
    ).toHaveCount(1);
    const csp = await page
      .locator('meta[http-equiv="Content-Security-Policy"]')
      .getAttribute("content");
    expect(csp, p + " CSP is exactly the widget-scoped policy, nothing broader").toBe(EXPECTED_CSP);
  }
});


test("the tutorial page keeps a tight CSP (no widget relaxations) (SITE-TUT-02)", async ({ page }) => {
  for (const p of ["/commentable-html/tutorial/"]) {
    await page.goto(p, { waitUntil: "domcontentloaded" });
    const csp = await page
      .locator('meta[http-equiv="Content-Security-Policy"]')
      .getAttribute("content");
    expect(csp, p + " CSP present").toBeTruthy();
    expect(csp, p + " script-src 'self'").toContain("script-src 'self'");
    expect(csp, p + " must not allow the star-widget script host").not.toContain("buttons.github.io");
    expect(csp, p + " must not allow inline styles/scripts").not.toContain("'unsafe-inline'");
    await expect(page.locator("a.github-button"), p + " has no star widget").toHaveCount(0);
  }
});


test("star widget degrades to a visible plain link when its script is blocked", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const link = page.locator("a.github-button");
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute("href", "https://github.com/urikanonov/ai-marketplace");
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
  // commentable-html and multi-duck are importable skills, so their install block has a third
  // "Claude Desktop" tab whose panel downloads the skill ZIP (no CLI command). The auto-updater's
  // value is a session hook a Desktop import cannot provide, so it offers CLI tabs only.
  for (const [path, zip] of [
    ["/commentable-html/", "../skills/commentable-html.zip"],
    ["/multi-duck/", "../skills/multi-duck.zip"],
  ]) {
    await page.goto(path, { waitUntil: "domcontentloaded" });
    const block = page.locator("#install .install-tabs");
    const desktopTab = block.locator(".install-tab", { hasText: "Claude Desktop" });
    await expect(desktopTab).toBeVisible();
    await desktopTab.click();
    const download = page.locator("#install .install-download a[download]");
    await expect(download).toBeVisible();
    // Exact per-page relative path: the plugin page lives one level deep, so the ZIP is under ../.
    await expect(download).toHaveAttribute("href", zip);
  }
  // The auto-updater page keeps only the two CLI tabs.
  await page.goto("/urikan-ai-marketplace-auto-updater/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#install .install-tab", { hasText: "GitHub Copilot" })).toBeVisible();
  await expect(page.locator("#install .install-tab", { hasText: "Claude Code" })).toBeVisible();
  await expect(page.locator("#install .install-tab", { hasText: "Claude Desktop" })).toHaveCount(0);
});


test("the Claude Desktop skill ZIP is served for download (SITE-INSTALL-06)", async ({ request }) => {
  for (const zip of ["/skills/commentable-html.zip", "/skills/multi-duck.zip"]) {
    const r = await request.get(zip);
    expect(r.status()).toBeLessThan(400);
    expect(r.headers()["content-type"]).toContain("application/zip");
  }
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

