const { test, expect, contrastRatio, compositedContrast, PROD } = require("./site-support");

test("plugin page renders version, features, changelog, and demo", async ({ page }) => {
  const resp = await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  expect(resp.status()).toBeLessThan(400);
  await expect(page).toHaveTitle(/Commentable HTML/i);
  await expect(page.locator(".badge.version")).toContainText(/v\d+\.\d+\.\d+/);
  expect(await page.locator("#features .feature").count()).toBeGreaterThanOrEqual(4);
  expect(await page.locator("#changelog .release").count()).toBeGreaterThanOrEqual(1);
  await expect(page.locator("#demo iframe")).toHaveAttribute("src", /demo\/report-taxi\.html/);
});

test("demo has one safe full-screen button and a six-option slider", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const fs = page.locator("#demo-fullscreen");
  await expect(fs).toHaveCount(1);
  await expect(fs).toHaveAttribute("target", "_blank");
  expect((await fs.getAttribute("rel")) || "").toContain("noopener");
  await expect(fs).toHaveAccessibleName(/full screen.*new tab/i);
  await expect(page.locator(".demo-tab")).toHaveCount(6);
  await expect(page.locator(".demo-tab.active")).toHaveText(/Taxi/i);
  for (const id of ["#demo-tab-taxi", "#demo-tab-showcase", "#demo-tab-garden", "#demo-tab-triage", "#demo-tab-metrics", "#demo-tab-checklist"]) {
    await expect(page.locator(id)).toBeVisible();
  }
});

test("demo slider switches the iframe, title, and full-screen target", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#demo-iframe")).toHaveAttribute("src", /report-taxi\.html/);
  await page.locator(".demo-tab", { hasText: "Community Garden Plan" }).click();
  await expect(page.locator("#demo-iframe")).toHaveAttribute("src", /report-community-garden\.html/);
  await expect(page.locator("#demo-fullscreen")).toHaveAttribute("href", /report-community-garden\.html/);
  await expect(page.locator("#demo-title")).toHaveText("Community Garden Plan");
  await expect(page.locator(".demo-tab.active")).toHaveText(/Community Garden/i);
  await page.locator(".demo-tab", { hasText: "Triage Board" }).click();
  await expect(page.locator("#demo-iframe")).toHaveAttribute("src", /report-triage\.html/);
  await expect(page.locator("#demo-fullscreen")).toHaveAttribute("href", /report-triage\.html/);
  await expect(page.locator("#demo-title")).toHaveText("Triage Board");
});

test("demo slider exposes and loads the Checklist report (SITE-DEMO-09)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const checklist = page.locator("#demo-tab-checklist");
  await expect(checklist).toBeVisible();
  await expect(checklist).toHaveAttribute("role", "tab");
  await expect(checklist).toHaveAttribute("aria-controls", "demo-panel");
  await expect(checklist).toHaveAttribute("aria-selected", "false");
  await expect(checklist).toHaveAttribute("tabindex", "-1");
  await checklist.click();
  await expect(page.locator("#demo-iframe")).toHaveAttribute("src", /report-checklist\.html/);
  await expect(page.locator("#demo-fullscreen")).toHaveAttribute("href", /report-checklist\.html/);
  await expect(page.locator("#demo-title")).toHaveText("Checklist");
  await expect(page.locator("#demo-panel")).toHaveAttribute("aria-labelledby", "demo-tab-checklist");
  const frame = page.frameLocator("#demo-iframe");
  await expect(frame.locator("[data-cmh-checklist]")).toHaveCount(2, { timeout: 15000 });
});

test("demo slider exposes and loads the Showcase deck (SITE-DEMO-10)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const showcase = page.locator("#demo-tab-showcase");
  await expect(showcase).toBeVisible();
  await expect(showcase).toHaveAttribute("role", "tab");
  await expect(showcase).toHaveAttribute("aria-controls", "demo-panel");
  await showcase.click();
  await expect(page.locator("#demo-iframe")).toHaveAttribute("src", /deck-showcase\.html/);
  await expect(page.locator("#demo-fullscreen")).toHaveAttribute("href", /deck-showcase\.html/);
  await expect(page.locator("#demo-title")).toHaveText("Showcase Deck");
  await expect(page.locator("#demo-panel")).toHaveAttribute("aria-labelledby", "demo-tab-showcase");
  const frame = page.frameLocator("#demo-iframe");
  await expect(frame.locator("#commentRoot[data-cmh-mode='deck']")).toHaveCount(1, { timeout: 15000 });
  await expect(frame.locator(".cmh-deck-mode-toggle")).toBeVisible();
});

test("demo tabs are keyboard operable (arrow keys switch the shown report)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  await page.locator("#demo-tab-taxi").focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("#demo-tab-garden")).toBeFocused();
  await expect(page.locator(".demo-tab.active")).toHaveText(/Community Garden/i);
  await expect(page.locator("#demo-iframe")).toHaveAttribute("src", /report-community-garden\.html/);
  await page.keyboard.press("ArrowLeft");
  await expect(page.locator("#demo-tab-taxi")).toBeFocused();
  await expect(page.locator("#demo-iframe")).toHaveAttribute("src", /report-taxi\.html/);
});

test("demo tabs expose a complete ARIA tabs contract", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const taxi = page.locator("#demo-tab-taxi");
  const garden = page.locator("#demo-tab-garden");
  const checklist = page.locator("#demo-tab-checklist");
  const panel = page.locator("#demo-panel");
  await expect(panel).toHaveAttribute("role", "tabpanel");
  await expect(taxi).toHaveAttribute("aria-controls", "demo-panel");
  // Initial state: only the active tab is in the tab order and labels the panel.
  await expect(taxi).toHaveAttribute("aria-selected", "true");
  await expect(taxi).toHaveAttribute("tabindex", "0");
  await expect(garden).toHaveAttribute("aria-selected", "false");
  await expect(garden).toHaveAttribute("tabindex", "-1");
  await expect(panel).toHaveAttribute("aria-labelledby", "demo-tab-taxi");
  // Home/End jump to the first/last tab and move the roving tabindex + panel label.
  await taxi.focus();
  await page.keyboard.press("End");
  await expect(checklist).toHaveAttribute("aria-selected", "true");
  await expect(checklist).toHaveAttribute("tabindex", "0");
  await expect(taxi).toHaveAttribute("tabindex", "-1");
  await expect(panel).toHaveAttribute("aria-labelledby", "demo-tab-checklist");
  await expect(page.locator("#demo-iframe")).toHaveAttribute("title", /Checklist|report-checklist/);
  await page.keyboard.press("Home");
  await expect(taxi).toHaveAttribute("aria-selected", "true");
  await expect(taxi).toBeFocused();
});

test("demo mounts inside the iframe on the plugin page (CSP allows it)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const frame = page.frameLocator("#demo iframe");
  await expect(frame.locator(".cm-toolbar")).toHaveCount(1, { timeout: 20000 });
  await expect(frame.locator("#btnCopyAll")).toBeAttached({ timeout: 20000 });
});

test("all demo reports load and their toolbars mount", async ({ page }) => {
  for (const report of ["report-taxi.html", "report-community-garden.html", "report-triage.html", "report-metrics.html", "report-checklist.html"]) {
    await page.goto("/commentable-html/demo/" + report, { waitUntil: "domcontentloaded" });
    await expect(page.locator(".cm-toolbar")).toHaveCount(1, { timeout: 15000 });
    await expect(page.locator("#btnCopyAll")).toBeAttached({ timeout: 15000 });
  }
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
