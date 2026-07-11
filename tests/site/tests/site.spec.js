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
  // Force the browser clock to a sentinel year before load so the assertion proves initYear()
  // writes the live year rather than passing tautologically on the hardcoded fallback baked into
  // the committed HTML. Overriding getFullYear (what site.js reads) also sidesteps any Node/browser
  // timezone difference and the New-Year rollover window.
  const SENTINEL = 2099;
  await page.addInitScript((year) => {
    Date.prototype.getFullYear = function () { return year; };
  }, SENTINEL);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#year")).toHaveText(String(SENTINEL));
});

test("theme variables are present (light + crimson)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const accent = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--cp-accent").trim()
  );
  expect(accent.toLowerCase()).toBe("#b11f4b");
});

test("light and dark themes preserve readable contrast", async ({ page }) => {
  const contrast = (foreground, background) => {
    const channels = (color) => {
      let values;
      if (/^#[0-9a-f]{6}$/i.test(color)) {
        values = [1, 3, 5].map((index) => parseInt(color.slice(index, index + 2), 16));
      } else {
        const match = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        expect(match, "unsupported color format: " + color).not.toBeNull();
        values = match.slice(1, 4).map(Number);
      }
      return values.map((value) => {
        const channel = value / 255;
        return channel <= 0.04045
          ? channel / 12.92
          : Math.pow((channel + 0.055) / 1.055, 2.4);
      });
    };
    const luminance = (color) => {
      const [r, g, b] = channels(color);
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const a = luminance(foreground);
    const b = luminance(background);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  };

  for (const scheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const colors = await page.evaluate(() => {
      const root = getComputedStyle(document.documentElement);
      const read = (name) => root.getPropertyValue(name).trim();
      return {
        scheme: root.colorScheme,
        background: getComputedStyle(document.body).backgroundColor,
        surface: read("--cp-surface"),
        text: read("--cp-text"),
        muted: read("--cp-text-muted"),
        soft: read("--cp-text-soft"),
        link: read("--cp-link"),
        accent: read("--cp-accent"),
        accentForeground: read("--cp-accent-fg"),
      };
    });
    expect(colors.scheme).toBe(scheme);
    for (const foreground of ["text", "muted", "soft", "link"]) {
      expect(
        contrast(colors[foreground], colors.background),
        scheme + " " + foreground + " on page background"
      ).toBeGreaterThanOrEqual(4.5);
      expect(
        contrast(colors[foreground], colors.surface),
        scheme + " " + foreground + " on card surface"
      ).toBeGreaterThanOrEqual(4.5);
    }
    expect(
      contrast(colors.accentForeground, colors.accent),
      scheme + " primary button contrast"
    ).toBeGreaterThanOrEqual(4.5);
  }
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
  const status = btn.locator(":scope + .copy-status");
  await expect(status).toHaveAttribute("aria-live", "polite");
  await expect(status).toHaveAttribute("aria-atomic", "true");
  await expect(status).toHaveText("Copied to clipboard.");
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  expect(clip).toBe(command);
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

test("plugin cards use one clearly focused title link without a stretched overlay", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const card = page.locator(".plugin-card", { hasText: "commentable-html" });
  const title = card.locator("a.name");
  await expect(title).toHaveAttribute("href", "./commentable-html/");
  await expect(card.locator('a[href="./commentable-html/"]')).toHaveCount(1);
  await expect(card.locator(".card-link")).toHaveCount(0);
  await expect(card.getByText("Learn more", { exact: true })).toHaveCount(0);
  await title.focus();
  const focus = await title.evaluate((el) => {
    const style = getComputedStyle(el);
    return { style: style.outlineStyle, width: parseFloat(style.outlineWidth) };
  });
  expect(focus.style).toBe("solid");
  expect(focus.width).toBeGreaterThanOrEqual(2);
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

test("every image on every page has non-empty alt text", async ({ page }) => {
  for (const p of ["/", "/commentable-html/", "/commentable-html/tutorial/"]) {
    await page.goto(p, { waitUntil: "domcontentloaded" });
    const missing = await page.evaluate(() =>
      Array.prototype.filter
        .call(document.querySelectorAll("img"), (img) => !(img.getAttribute("alt") || "").trim())
        .map((img) => img.getAttribute("src"))
    );
    expect(missing, "images without alt text on " + p + ": " + missing.join(", ")).toEqual([]);
  }
});

test("commentable-html nav keeps the user on the page and offers a Marketplace link", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  // The top-left brand icon stays on the commentable-html page (does not jump to the hub).
  await expect(page.locator(".brand")).toHaveAttribute("href", "./");
  // A Marketplace link sits to the right of GitHub and goes back to the hub.
  const market = page.locator('.nav-links a', { hasText: "Marketplace" });
  await expect(market).toHaveAttribute("href", "../");
  const links = page.locator(".nav-links a");
  const count = await links.count();
  const texts = [];
  for (let linkIndex = 0; linkIndex < count; linkIndex++) texts.push((await links.nth(linkIndex).textContent()).trim());
  expect(texts.indexOf("Marketplace")).toBe(texts.indexOf("GitHub") + 1);
});

test("commentable-html hero shows the plugin logo", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const logo = page.locator(".hero-logo");
  await expect(logo).toHaveCount(1);
  await expect(logo).toHaveAttribute("alt", /commentable html/i);
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
});

test("tutorial brand keeps the user in the commentable-html section", async ({ page }) => {
  await page.goto("/commentable-html/tutorial/", { waitUntil: "domcontentloaded" });
  // The brand icon returns to the commentable-html plugin home, not the hub root.
  await expect(page.locator(".brand")).toHaveAttribute("href", "../");
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

test("the demo frame spans the full viewport width while its heading stays in the content column", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
  const frame = await page.locator("#demo-panel").boundingBox();
  // The demo frame breaks out of the content column to span the full layout width.
  expect(frame.x).toBeLessThanOrEqual(2);
  expect(frame.width).toBeGreaterThanOrEqual(clientWidth - 2);
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

test("the plugin page footer links to contribute, feature request, issues, source, and the author's LinkedIn", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const footer = page.locator("footer.footer");
  await expect(footer.locator("a", { hasText: "Contribute" })).toHaveAttribute("href", /\/CONTRIBUTING\.md$/);
  await expect(footer.locator("a", { hasText: "Request a feature" })).toHaveAttribute("href", /feature-request\.yml$/);
  await expect(footer.locator("a", { hasText: "File an issue" })).toHaveAttribute("href", /\/issues\/new\/choose$/);
  await expect(footer.locator("a", { hasText: "Plugin source" })).toHaveAttribute("href", /\/plugins\/commentable-html$/);
  await expect(footer.locator("a", { hasText: "Uri Kanonov" })).toHaveAttribute("href", /linkedin\.com\/in\/uri-kanonov/);
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
