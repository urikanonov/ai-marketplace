const { test, expect } = require("@playwright/test");

// Keep the suite hermetic and deterministic: block every request that is not our
// local static server so a flaky GitHub API, the star-widget CDN, or the mermaid
// CDN can never fail the deploy gate. We validate the built static output only.
test.beforeEach(async ({ context }) => {
  await context.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.protocol === "data:" || url.hostname === "127.0.0.1" || url.hostname === "localhost") {
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

test("every page exposes a skip-to-content link that targets the main region", async ({ page }) => {
  for (const p of ["/", "/commentable-html/", "/commentable-html/tutorial/"]) {
    await page.goto(p, { waitUntil: "domcontentloaded" });
    const skip = page.locator("a.skip-link");
    await expect(skip).toHaveCount(1);
    await expect(skip).toHaveAttribute("href", "#main");
    await expect(page.locator("main#main")).toHaveCount(1);
  }
});

test("footer year is filled in with the current year", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  // site.js sets #year to new Date().getFullYear(), so the expectation tracks the
  // real current year on purpose - a hardcoded year would go stale every January.
  const year = String(new Date().getFullYear());
  await expect(page.locator("#year")).toHaveText(year);
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

test("demo has one safe full-screen button and a two-option slider", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const fs = page.locator("#demo-fullscreen");
  await expect(fs).toHaveCount(1);
  await expect(fs).toHaveAttribute("target", "_blank");
  expect((await fs.getAttribute("rel")) || "").toContain("noopener");
  await expect(page.locator(".demo-tab")).toHaveCount(2);
  await expect(page.locator(".demo-tab.active")).toHaveText(/Taxi/i);
});

test("demo slider switches the iframe, title, and full-screen target", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#demo-iframe")).toHaveAttribute("src", /report-taxi\.html/);
  await page.locator(".demo-tab", { hasText: "Community Garden Plan" }).click();
  await expect(page.locator("#demo-iframe")).toHaveAttribute("src", /report-community-garden\.html/);
  await expect(page.locator("#demo-fullscreen")).toHaveAttribute("href", /report-community-garden\.html/);
  await expect(page.locator("#demo-title")).toHaveText("Community Garden Plan");
  await expect(page.locator(".demo-tab.active")).toHaveText(/Community Garden/i);
});

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

test("plugin and tutorial pages keep a tight CSP (no widget relaxations)", async ({ page }) => {
  for (const p of ["/commentable-html/", "/commentable-html/tutorial/"]) {
    await page.goto(p, { waitUntil: "domcontentloaded" });
    const csp = await page
      .locator('meta[http-equiv="Content-Security-Policy"]')
      .getAttribute("content");
    expect(csp, p + " CSP present").toBeTruthy();
    expect(csp, p + " script-src 'self'").toContain("script-src 'self'");
    expect(csp, p + " must not allow the star-widget script host").not.toContain("buttons.github.io");
    expect(csp, p + " must not allow inline styles/scripts").not.toContain("'unsafe-inline'");
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
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  expect(clip).toBe(command);
});

test("copy button shows a manual-copy hint when the clipboard is unavailable", async ({ page }) => {
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
  await expect(btn).toHaveText("press Ctrl+C");
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

test("the static test server refuses path traversal out of site/", async () => {
  // A high-level client normalizes ".." out of the path, so hit the server with a raw
  // request whose request-target keeps the traversal literal.
  const http = require("http");
  const status = await new Promise((resolve, reject) => {
    const req = http.request(
      { host: "127.0.0.1", port: 4173, path: "/../../package.json", method: "GET" },
      (res) => {
        res.resume();
        resolve(res.statusCode);
      }
    );
    req.on("error", reject);
    req.end();
  });
  expect(status).toBe(403);
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
  await expect(garden).toHaveAttribute("aria-selected", "true");
  await expect(garden).toHaveAttribute("tabindex", "0");
  await expect(taxi).toHaveAttribute("tabindex", "-1");
  await expect(panel).toHaveAttribute("aria-labelledby", "demo-tab-garden");
  await expect(page.locator("#demo-iframe")).toHaveAttribute("title", /Community Garden|report-community-garden/);
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

test("both demo reports load and their toolbars mount", async ({ page }) => {
  for (const report of ["report-taxi.html", "report-community-garden.html"]) {
    await page.goto("/commentable-html/demo/" + report, { waitUntil: "domcontentloaded" });
    await expect(page.locator(".cm-toolbar")).toHaveCount(1, { timeout: 15000 });
    await expect(page.locator("#btnCopyAll")).toBeAttached({ timeout: 15000 });
  }
});

test("tutorial page renders from TUTORIAL.md with working images", async ({ page, request }) => {
  const resp = await page.goto("/commentable-html/tutorial/", { waitUntil: "domcontentloaded" });
  expect(resp.status()).toBeLessThan(400);
  await expect(page).toHaveTitle(/tutorial/i);
  expect(await page.locator(".tutorial h2, .tutorial h3").count()).toBeGreaterThan(3);
  const imgs = page.locator(".tutorial img");
  const n = await imgs.count();
  expect(n).toBeGreaterThan(0);
  for (let i = 0; i < n; i++) {
    const src = await imgs.nth(i).getAttribute("src");
    const abs = new URL(src, page.url());
    const r = await request.get(abs.href);
    expect(r.status(), "broken tutorial image: " + src).toBeLessThan(400);
  }
});

test("plugin page links to the tutorial", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  await expect(page.locator('a[href="tutorial/"]').first()).toBeVisible();
});

test("no internal link or asset uses a root-relative path (would break the project sub-path)", async ({ page }) => {
  for (const p of ["/", "/commentable-html/", "/commentable-html/tutorial/"]) {
    await page.goto(p, { waitUntil: "domcontentloaded" });
    const bad = await page.evaluate(() => {
      const out = [];
      const check = (nodes, attr) =>
        nodes.forEach((n) => {
          const raw = n.getAttribute(attr);
          if (raw && raw.startsWith("/") && !raw.startsWith("//")) out.push(attr + "=" + raw);
        });
      check(document.querySelectorAll("a[href]"), "href");
      check(document.querySelectorAll("link[href]"), "href");
      check(document.querySelectorAll("script[src]"), "src");
      check(document.querySelectorAll("img[src]"), "src");
      check(document.querySelectorAll("iframe[src]"), "src");
      return out;
    });
    expect(bad, "root-relative refs would 404 under /ai-marketplace/: " + bad.join(", ")).toEqual([]);
  }
});

test("no broken internal links or assets", async ({ page, request }) => {
  const pagesToCrawl = ["/", "/commentable-html/", "/commentable-html/tutorial/"];
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
      document.querySelectorAll("iframe[src]").forEach((n) => add(n.src));
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
