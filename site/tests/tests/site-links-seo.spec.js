const { test, expect } = require("@playwright/test");
const { contrastRatio, compositedContrast, installNetworkBlock } = require("./site-helpers");

installNetworkBlock(test);

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

const PROD = "https://urikanonov.github.io/ai-marketplace/";


test("hub head exposes canonical, Open Graph, and Twitter Card tags", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", PROD);
  await expect(page.locator('meta[property="og:type"]')).toHaveAttribute("content", "website");
  await expect(page.locator('meta[property="og:title"]')).toHaveAttribute("content", /AI Marketplace/);
  await expect(page.locator('meta[property="og:url"]')).toHaveAttribute("content", PROD);
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute("content", PROD + "assets/og-cover.png");
  await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute("content", "summary_large_image");
});


test("hub head declares the sitemap link (SITE-SEO-12)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const sitemap = page.locator('link[rel="sitemap"]');
  await expect(sitemap).toHaveAttribute("type", "application/xml");
  await expect(sitemap).toHaveAttribute("href", "sitemap.xml");
});


test("plugin and tutorial pages carry a self-referencing canonical and Open Graph metadata", async ({ page }) => {
  const cases = [
    ["/commentable-html/", PROD + "commentable-html/"],
    ["/commentable-html/tutorial/", PROD + "commentable-html/tutorial/"],
    ["/urikan-ai-marketplace-auto-updater/", PROD + "urikan-ai-marketplace-auto-updater/"],
  ];
  for (const [p, canonical] of cases) {
    await page.goto(p, { waitUntil: "domcontentloaded" });
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", canonical);
    await expect(page.locator('meta[property="og:url"]')).toHaveAttribute("content", canonical);
    await expect(page.locator('meta[property="og:title"]')).toHaveAttribute("content", /.+/);
    await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute("content", "summary_large_image");
  }
});


test("plugin and tutorial metadata use display titles while stable identifiers keep the slug (SITE-SEO-09)", async ({ page }) => {
  const cases = [
    {
      path: "/commentable-html/",
      title: "Commentable HTML - inline-comment review surface for any HTML",
      canonical: PROD + "commentable-html/",
      jsonLdName: "commentable-html",
    },
    {
      path: "/commentable-html/tutorial/",
      title: "Commentable HTML tutorial - a guided walkthrough",
      canonical: PROD + "commentable-html/tutorial/",
    },
  ];
  for (const c of cases) {
    await page.goto(c.path, { waitUntil: "domcontentloaded" });
    await expect(page).toHaveTitle(c.title);
    await expect(page.locator('meta[property="og:title"]')).toHaveAttribute("content", c.title);
    await expect(page.locator('meta[name="twitter:title"]')).toHaveAttribute("content", c.title);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", c.canonical);
    await expect(page.locator('meta[property="og:url"]')).toHaveAttribute("content", c.canonical);
    if (c.jsonLdName) {
      const raw = await page.locator('script[type="application/ld+json"]').first().textContent();
      const graph = JSON.parse(raw)["@graph"];
      const app = graph.find((n) => n["@type"] === "SoftwareApplication");
      expect(app.name).toBe(c.jsonLdName);
    }
  }
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


test("sitemap.xml is served and lists the hub, plugin, and tutorial pages", async ({ request }) => {
  const r = await request.get("/sitemap.xml");
  expect(r.status()).toBeLessThan(400);
  const body = await r.text();
  expect(body).toContain("<urlset");
  for (const u of [PROD, PROD + "commentable-html/", PROD + "commentable-html/tutorial/",
                   PROD + "urikan-ai-marketplace-auto-updater/"]) {
    expect(body).toContain("<loc>" + u + "</loc>");
  }
});


test("llms.txt is served and links each plugin and the tutorial", async ({ request }) => {
  const r = await request.get("/llms.txt");
  expect(r.status()).toBeLessThan(400);
  const body = await r.text();
  expect(body).toContain("# AI Marketplace");
  expect(body).toContain("(" + PROD + "commentable-html/)");
  expect(body).toContain("(" + PROD + "urikan-ai-marketplace-auto-updater/)");
  expect(body).toContain("commentable-html/tutorial/");
});


test("the og:image cover asset is served as a PNG", async ({ request }) => {
  const r = await request.get("/assets/og-cover.png");
  expect(r.status()).toBeLessThan(400);
  expect(r.headers()["content-type"]).toContain("image/png");
});


test("the commentable-html plugin and tutorial pages use a dedicated branded social cover (SITE-SEO-10)", async ({ page, request }) => {
  const branded = PROD + "assets/og-commentable-html.png";
  for (const p of ["/commentable-html/", "/commentable-html/tutorial/"]) {
    await page.goto(p, { waitUntil: "domcontentloaded" });
    await expect(page.locator('meta[property="og:image"]')).toHaveAttribute("content", branded);
    await expect(page.locator('meta[name="twitter:image"]')).toHaveAttribute("content", branded);
  }
  const r = await request.get("/assets/og-commentable-html.png");
  expect(r.status()).toBeLessThan(400);
  expect(r.headers()["content-type"]).toContain("image/png");
});


test("the marketplace brand and site name display as 'AI Marketplace' while identifiers keep the ai-marketplace slug (SITE-SEO-11)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".brand span")).toHaveText("AI Marketplace");
  await expect(page.locator(".brand img")).toHaveAttribute("alt", "AI Marketplace logo");
  await expect(page).toHaveTitle(/^AI Marketplace\b/);
  await expect(page.locator('meta[property="og:site_name"]')).toHaveAttribute("content", "AI Marketplace");
  await expect(page.locator('meta[property="og:title"]')).toHaveAttribute("content", /^AI Marketplace\b/);
  await expect(page.locator('meta[name="twitter:title"]')).toHaveAttribute("content", /^AI Marketplace\b/);

  const raw = await page.locator('script[type="application/ld+json"]').first().textContent();
  const website = JSON.parse(raw)["@graph"].find((n) => n["@type"] === "WebSite");
  expect(website.name).toBe("AI Marketplace");
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", PROD);
  await expect(page.locator("nav.navbar a.gh")).toHaveAttribute(
    "href", "https://github.com/urikanonov/ai-marketplace");

  for (const p of ["/commentable-html/", "/urikan-ai-marketplace-auto-updater/", "/commentable-html/tutorial/"]) {
    await page.goto(p, { waitUntil: "domcontentloaded" });
    await expect(page.locator('meta[property="og:site_name"]')).toHaveAttribute("content", "AI Marketplace");
  }

  for (const p of ["/commentable-html/", "/urikan-ai-marketplace-auto-updater/"]) {
    await page.goto(p, { waitUntil: "domcontentloaded" });
    const rawLd = await page.locator('script[type="application/ld+json"]').first().textContent();
    const crumbs = JSON.parse(rawLd)["@graph"].find((n) => n["@type"] === "BreadcrumbList").itemListElement;
    expect(crumbs[0].name).toBe("AI Marketplace");
    expect(crumbs[0].item).toBe(PROD);
  }
});


test("the hub H1 reads as continuous text with correct word spacing", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const text = (await page.locator("h1").first().textContent()).replace(/\s+/g, " ").trim();
  expect(text).toBe("A marketplace of AI plugins for Claude Code and Copilot");
});


test("plugin card text can be selected without navigation and plain body clicks still navigate (SITE-HUB-08)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const card = page.locator(".plugin-card", { hasText: "commentable-html" }).first();
  const desc = card.locator(".desc");
  await desc.scrollIntoViewIfNeeded();
  const box = await desc.evaluate((el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    const rect = Array.from(range.getClientRects()).find((r) => r.width > 80 && r.height > 8);
    range.detach();
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
  });
  await page.evaluate(() => window.getSelection().removeAllRanges());
  await page.mouse.move(box.x + 8, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + Math.min(box.width - 8, 240), box.y + box.height / 2, { steps: 12 });
  await page.mouse.up();
  const selected = await page.evaluate(() => window.getSelection().toString());
  expect(selected.trim().length).toBeGreaterThan(0);
  await expect(page).toHaveURL(/\/$/);

  await page.evaluate(() => window.getSelection().removeAllRanges());
  await page.mouse.click(box.x + 20, box.y + box.height / 2);
  await expect(page).toHaveURL(/\/commentable-html\/$/);
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


test("initHeaderAnchors leaves a section whose title already holds a link untouched (SITE-NAV-01)", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  // Inject a section whose heading already contains an interactive element.
  await page.evaluate(() => {
    const section = document.createElement("section");
    section.id = "hermetic-existing-anchor";
    const heading = document.createElement("h2");
    heading.className = "section-title";
    const inner = document.createElement("a");
    inner.setAttribute("href", "/y");
    inner.textContent = "T";
    heading.appendChild(inner);
    section.appendChild(heading);
    document.body.appendChild(section);
  });
  // Re-run the progressive-enhancement script so initHeaderAnchors sees the new section.
  await page.addScriptTag({ url: "/assets/site.js" });
  const injected = page.locator("section#hermetic-existing-anchor");
  // The pre-existing link must not be wrapped (which would nest an <a> inside an <a>).
  await expect(injected.locator(".section-title a.header-anchor")).toHaveCount(0);
  await expect(injected.locator("a a")).toHaveCount(0);
  // The original link stays a direct child of the heading, intact.
  await expect(injected.locator(".section-title > a[href='/y']")).toHaveCount(1);
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


test("a nav jump clears the sticky navbar so the target section is not hidden (SITE-NAV-03)", async ({ page }) => {
  // Reduced motion turns the hash jump instant, so the assertion never races a smooth scroll.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/", { waitUntil: "networkidle" });
  const navBottom = await page.locator(".navbar").evaluate((n) => n.getBoundingClientRect().bottom);
  expect(navBottom).toBeGreaterThan(0);
  // Jump to the first hub section (it has enough content below to reach the top of the
  // scroll area, so a missing scroll offset would hide it behind the sticky navbar).
  const navLink = page.locator('.nav-links a[href="#install"]');
  await expect(navLink).toBeVisible();
  await navLink.click();
  await expect(page).toHaveURL(/#install$/);
  // scroll-margin-top keeps the section's own top edge at or below the navbar bottom,
  // so the heading is never drawn behind the translucent sticky navbar.
  const top = await page.locator("section#install").evaluate((n) => n.getBoundingClientRect().top);
  expect(top).toBeGreaterThanOrEqual(navBottom - 1);
});


test("the anchor offset tracks a taller wrapped navbar on a narrow plugin page (SITE-NAV-03)", async ({ page }) => {
  // On a narrow plugin page the sticky navbar wraps to well over the 76px static fallback,
  // so a fixed offset would still hide the heading; site.js keeps --nav-offset at the real height.
  await page.setViewportSize({ width: 320, height: 640 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/commentable-html/", { waitUntil: "networkidle" });
  const navBottom = await page.locator(".navbar").evaluate((n) => n.getBoundingClientRect().bottom);
  // Guard the premise of the test: this navbar is taller than the 76px static fallback.
  expect(navBottom).toBeGreaterThan(76);
  // Jump to an early section (plenty of content below to reach the top of the scroll area).
  await page.locator("section#install .section-title a.header-anchor").click();
  await expect(page).toHaveURL(/#install$/);
  const top = await page.locator("section#install").evaluate((n) => n.getBoundingClientRect().top);
  expect(top).toBeGreaterThanOrEqual(navBottom - 1);
  // The [data-anchor][id] sub-heading offset must track the same wrapped navbar, so removing
  // that selector from the rule would be caught here (not only the section[id] case above).
  await page.locator("h3.why-sub#mediums[data-anchor] a.header-anchor").click();
  await expect(page).toHaveURL(/#mediums$/);
  const subTop = await page.locator("#mediums").evaluate((n) => n.getBoundingClientRect().top);
  expect(subTop).toBeGreaterThanOrEqual(navBottom - 1);
});
