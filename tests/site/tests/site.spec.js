const { test, expect } = require("@playwright/test");

// Keep the suite hermetic and deterministic: block every request that is not our
// local static server so a flaky GitHub API, the star-widget CDN, or the mermaid
// CDN can never fail the deploy gate. We validate the built static output only.
test.beforeEach(async ({ context }) => {
  await context.route("**/*", (route) => {
    const host = new URL(route.request().url()).hostname;
    if (host === "127.0.0.1" || host === "localhost") {
      return route.continue();
    }
    return route.abort();
  });
});

test("hub renders with plugins, install command, and logo", async ({ page }) => {
  const resp = await page.goto("/", { waitUntil: "domcontentloaded" });
  expect(resp.status()).toBeLessThan(400);
  await expect(page).toHaveTitle(/ai-marketplace/i);
  await expect(page.locator(".brand img")).toHaveCount(1);
  const cards = page.locator(".plugin-card");
  expect(await cards.count()).toBeGreaterThanOrEqual(2);
  await expect(page.locator(".plugin-card .name", { hasText: "commentable-html" })).toBeVisible();
  await expect(page.locator("#install .cmd pre")).toContainText("marketplace add");
});

test("theme variables are present (light + crimson)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const accent = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--cp-accent").trim()
  );
  expect(accent.toLowerCase()).toBe("#b11f4b");
});

test("plugin page renders version, features, changelog, and demo", async ({ page }) => {
  const resp = await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  expect(resp.status()).toBeLessThan(400);
  await expect(page).toHaveTitle(/commentable-html/i);
  await expect(page.locator(".badge.version")).toContainText(/v\d+\.\d+\.\d+/);
  expect(await page.locator("#features .feature").count()).toBeGreaterThanOrEqual(4);
  expect(await page.locator("#changelog .release").count()).toBeGreaterThanOrEqual(1);
  await expect(page.locator("#demo iframe")).toHaveAttribute("src", /demo\/report-taxi\.html/);
});

test("open-full demo links are safe external targets", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const links = page.locator(".demo-actions a");
  const count = await links.count();
  expect(count).toBeGreaterThanOrEqual(1);
  for (let i = 0; i < count; i++) {
    await expect(links.nth(i)).toHaveAttribute("target", "_blank");
    const rel = (await links.nth(i).getAttribute("rel")) || "";
    expect(rel).toContain("noopener");
  }
});

test("demo report loads and the commentable toolbar mounts", async ({ page }) => {
  await page.goto("/commentable-html/demo/report-taxi.html", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".cm-toolbar")).toHaveCount(1, { timeout: 15000 });
  await expect(page.locator("#btnCopyAll")).toBeAttached({ timeout: 15000 });
});

test("no broken internal links or assets", async ({ page, request }) => {
  const pagesToCrawl = ["/", "/commentable-html/"];
  const checked = new Set();
  for (const p of pagesToCrawl) {
    await page.goto(p, { waitUntil: "domcontentloaded" });
    const currentPath = new URL(page.url()).pathname;
    const urls = await page.evaluate(() => {
      const out = [];
      const add = (u) => {
        if (u) out.push(u);
      };
      document.querySelectorAll("a[href]").forEach((n) => add(n.href));
      document.querySelectorAll("link[href]").forEach((n) => add(n.href));
      document.querySelectorAll("script[src]").forEach((n) => add(n.src));
      document.querySelectorAll("img[src]").forEach((n) => add(n.src));
      return out;
    });
    for (const u of urls) {
      const url = new URL(u);
      if (url.hostname !== "127.0.0.1" && url.hostname !== "localhost") continue;
      if (url.hash && url.pathname === currentPath) continue;
      const key = url.origin + url.pathname;
      if (checked.has(key)) continue;
      checked.add(key);
      const r = await request.get(key);
      expect(r.status(), "broken internal URL: " + url.pathname).toBeLessThan(400);
    }
  }
});
