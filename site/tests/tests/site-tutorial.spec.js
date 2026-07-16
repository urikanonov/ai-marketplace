const { test, expect, contrastRatio, compositedContrast, PROD } = require("./site-support");

test("plugin, tutorial, and updater footers share the same link structure (SITE-FOOTER-01)", async ({ page }) => {
  const common = [
    ["Uri Kanonov", "https://www.linkedin.com/in/uri-kanonov-946761119"],
    ["Contribute", "https://github.com/urikanonov/ai-marketplace/blob/main/CONTRIBUTING.md"],
    ["Request a feature", "https://github.com/urikanonov/ai-marketplace/issues/new?template=feature-request.yml"],
    ["File an issue", "https://github.com/urikanonov/ai-marketplace/issues/new/choose"],
  ];
  const pages = [
    ["/commentable-html/", "https://github.com/urikanonov/ai-marketplace/tree/main/plugins/commentable-html"],
    ["/commentable-html/tutorial/", "https://github.com/urikanonov/ai-marketplace/tree/main/plugins/commentable-html"],
    ["/urikan-ai-marketplace-auto-updater/", "https://github.com/urikanonov/ai-marketplace/tree/main/plugins/urikan-ai-marketplace-auto-updater"],
  ];

  const structures = [];
  for (const [path, pluginSource] of pages) {
    await page.goto(path, { waitUntil: "domcontentloaded" });
    const links = await page.locator("footer.footer a").evaluateAll((anchors) =>
      anchors.map((a) => [a.textContent.trim().replace(/\s+/g, " "), a.href])
    );
    expect(links).toEqual([...common, ["Plugin source", pluginSource]]);
    structures.push(links.map(([label]) => label));
  }

  expect(structures[1]).toEqual(structures[0]);
  expect(structures[2]).toEqual(structures[0]);
});

test("plugin and tutorial pages keep a tight CSP (no widget relaxations)", async ({ page }) => {
  for (const p of ["/commentable-html/", "/commentable-html/tutorial/", "/urikan-ai-marketplace-auto-updater/"]) {
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
  expect(body).toContain("# ai-marketplace");
  expect(body).toContain("(" + PROD + "commentable-html/)");
  expect(body).toContain("(" + PROD + "urikan-ai-marketplace-auto-updater/)");
  expect(body).toContain("commentable-html/tutorial/");
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
