const { test, expect, contrastRatio, compositedContrast, PROD } = require("./site-support");

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

test("no internal link or asset uses a root-relative path (would break the project sub-path)", async ({ page }) => {
  for (const p of ["/", "/commentable-html/", "/commentable-html/tutorial/", "/urikan-ai-marketplace-auto-updater/"]) {
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
  const pagesToCrawl = ["/", "/commentable-html/", "/commentable-html/tutorial/", "/urikan-ai-marketplace-auto-updater/"];
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


test("hub head exposes canonical, Open Graph, and Twitter Card tags", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", PROD);
  await expect(page.locator('meta[property="og:type"]')).toHaveAttribute("content", "website");
  await expect(page.locator('meta[property="og:title"]')).toHaveAttribute("content", /ai-marketplace/);
  await expect(page.locator('meta[property="og:url"]')).toHaveAttribute("content", PROD);
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute("content", PROD + "assets/og-cover.png");
  await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute("content", "summary_large_image");
});

test("the hub embeds valid JSON-LD describing the site and its plugins", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const raw = await page.locator('script[type="application/ld+json"]').first().textContent();
  const graph = JSON.parse(raw)["@graph"];
  const types = graph.map((n) => n["@type"]);
  expect(types).toContain("WebSite");
  expect(types).toContain("Person");
  expect(types).toContain("ItemList");
  const itemList = graph.find((n) => n["@type"] === "ItemList");
  const names = itemList.itemListElement.map((li) => li.item.name);
  expect(names).toContain("commentable-html");
  expect(names.length).toBeGreaterThanOrEqual(2);
});

test("the plugin page embeds SoftwareApplication and BreadcrumbList JSON-LD", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const raw = await page.locator('script[type="application/ld+json"]').first().textContent();
  const graph = JSON.parse(raw)["@graph"];
  const types = graph.map((n) => n["@type"]);
  expect(types).toContain("SoftwareApplication");
  expect(types).toContain("BreadcrumbList");
  const app = graph.find((n) => n["@type"] === "SoftwareApplication");
  expect(app.name).toBe("commentable-html");
});

test("the og:image cover asset is served as a PNG", async ({ request }) => {
  const r = await request.get("/assets/og-cover.png");
  expect(r.status()).toBeLessThan(400);
  expect(r.headers()["content-type"]).toContain("image/png");
});

test("the hub H1 reads as continuous text with correct word spacing", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const text = (await page.locator("h1").first().textContent()).replace(/\s+/g, " ").trim();
  expect(text).toBe("A marketplace of AI plugins for Claude Code and Copilot");
});

test("every section header is a linkable anchor that updates the URL fragment (SITE-NAV-01)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "networkidle" });
  const sections = page.locator("section[id]");
  const count = await sections.count();
  expect(count).toBeGreaterThan(3);
  let checked = 0;
  for (let i = 0; i < count; i++) {
    const section = sections.nth(i);
    const id = await section.getAttribute("id");
    const title = section.locator(".section-title").first();
    // A section without a .section-title heading (for example a CTA banner) is exempt.
    if ((await title.count()) === 0) {
      continue;
    }
    const anchor = title.locator("a.header-anchor");
    await expect(anchor).toHaveCount(1);
    await expect(anchor).toHaveAttribute("href", "#" + id);
    // The whole heading text is the clickable link (no separate marker glyph).
    expect((await anchor.textContent()).trim()).toBe((await title.textContent()).trim());
    checked++;
  }
  expect(checked).toBeGreaterThan(3);
  // The anchor resolves to an absolute URL ending in the section fragment.
  const resolved = await page
    .locator("section#install .section-title a.header-anchor")
    .evaluate((a) => a.href);
  expect(resolved).toMatch(/^https?:\/\/.+#install$/);
  // Clicking a header anchor moves the URL fragment to that section.
  await page.locator("section#install .section-title a.header-anchor").click();
  await expect(page).toHaveURL(/#install$/);
});

test("section header anchor copies a shareable URL that keeps the query string (SITE-NAV-01)", async ({ page }) => {
  // The clipboard URL is built from the anchor's own href, so it stays a valid
  // absolute URL for any protocol/base (file:// included) and preserves the query.
  await page.goto("/commentable-html/?share=1", { waitUntil: "networkidle" });
  await page.evaluate(() => {
    window.__copied = [];
    const capture = (text) => {
      window.__copied.push(String(text));
      return Promise.resolve();
    };
    if (navigator.clipboard) {
      try {
        Object.defineProperty(navigator.clipboard, "writeText", { value: capture, configurable: true });
      } catch (e) {
        navigator.clipboard.writeText = capture;
      }
    } else {
      navigator.clipboard = { writeText: capture };
    }
  });
  const anchor = page.locator("section#install .section-title a.header-anchor");
  const resolved = await anchor.evaluate((a) => a.href);
  await anchor.click();
  const copied = await page.evaluate(() => window.__copied.slice());
  expect(copied.length).toBe(1);
  expect(copied[0]).toBe(resolved);
  expect(copied[0]).toContain("share=1");
  expect(copied[0]).toMatch(/#install$/);
});

test("a standalone data-anchor sub-heading is a linkable anchor to its own id (SITE-NAV-02)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "networkidle" });
  // The "Chat, Markdown, HTML - or a tight loop?" sub-heading opts in with data-anchor and its own id.
  const heading = page.locator("h3.why-sub#mediums[data-anchor]");
  await expect(heading).toHaveCount(1);
  const anchor = heading.locator("a.header-anchor");
  await expect(anchor).toHaveCount(1);
  await expect(anchor).toHaveAttribute("href", "#mediums");
  // The whole heading text is the clickable link (no separate marker glyph).
  expect((await anchor.textContent()).trim()).toBe((await heading.textContent()).trim());
  // The anchor resolves to an absolute URL ending in the heading's own fragment.
  const resolved = await anchor.evaluate((a) => a.href);
  expect(resolved).toMatch(/^https?:\/\/.+#mediums$/);
  // Clicking the sub-heading anchor moves the URL fragment to it.
  await anchor.click();
  await expect(page).toHaveURL(/#mediums$/);
});
