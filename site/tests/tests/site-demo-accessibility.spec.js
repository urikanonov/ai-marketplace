const { test, expect } = require("@playwright/test");
const { contrastRatio, compositedContrast, installNetworkBlock } = require("./site-helpers");

installNetworkBlock(test);

test("plugin card keeps keyboard links plus the stretched overlay and independent controls (SITE-A11Y-04)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const card = page.locator(".plugin-card", { hasText: "commentable-html" });
  const titleLink = card.locator(".name a");
  await expect(titleLink).toHaveAttribute("href", "./commentable-html/");
  const overlay = await titleLink.evaluate((el) => {
    const after = getComputedStyle(el, "::after");
    return { content: after.content, position: after.position, zIndex: after.zIndex };
  });
  expect(overlay.content).not.toBe("none");
  expect(overlay.position).toBe("absolute");
  expect(overlay.zIndex).toBe("1");
  const learn = card.locator("a.learn-more");
  await expect(learn).toHaveAttribute("href", "./commentable-html/");
  const descInLink = await card.locator(".desc").evaluate((el) => !!el.closest("a"));
  expect(descInLink, "description must not be inside a card-wide link").toBe(false);
  await expect(card.locator(".copy-btn").first()).toBeVisible();
  await expect(card.locator(".foot a.btn:not(.learn-more)")).toHaveCount(1);
  await titleLink.click();
  await expect(page).toHaveURL(/\/commentable-html\/$/);
});


test("the Learn more button keeps AA contrast in light and dark themes", async ({ page }) => {
  const contrast = (fg, bg) => {
    const channels = (color) => {
      const m = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
      expect(m, "unsupported color format: " + color).not.toBeNull();
      return m.slice(1, 4).map(Number).map((value) => {
        const channel = value / 255;
        return channel <= 0.04045 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4);
      });
    };
    const luminance = (color) => {
      const [r, g, b] = channels(color);
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const a = luminance(fg);
    const b = luminance(bg);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  };
  for (const scheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const colors = await page.locator(".plugin-card .learn-more").first().evaluate((el) => {
      const style = getComputedStyle(el);
      return { color: style.color, background: style.backgroundColor };
    });
    expect(
      contrast(colors.color, colors.background),
      scheme + " Learn more contrast"
    ).toBeGreaterThanOrEqual(4.5);
  }
});


test("the plugin page identity line (logo, name, version) sits below the call-to-action buttons", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const identity = page.locator(".hero .identity");
  await expect(identity).toBeVisible();
  // The identity line carries the logo and the version badge.
  await expect(identity.locator(".hero-logo")).toHaveCount(1);
  await expect(identity.locator(".badge.version")).toHaveCount(1);
  // It sits below the call-to-action buttons.
  const actions = await page.locator(".hero-actions").boundingBox();
  const idBox = await identity.boundingBox();
  expect(idBox.y).toBeGreaterThan(actions.y + actions.height - 1);
  // The identity line links to the plugin's source directory on GitHub.
  await expect(identity).toHaveAttribute(
    "href",
    "https://github.com/urikanonov/ai-marketplace/tree/main/plugins/commentable-html");
});


test("the plugin-page GitHub star button sits beside the identity line, not among the CTAs (SITE-PLUGIN-26)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  for (const p of ["/commentable-html/", "/multi-duck/", "/urikan-ai-marketplace-auto-updater/"]) {
    await page.goto(p, { waitUntil: "domcontentloaded" });
    // The star is no longer one of the call-to-action buttons.
    await expect(
      page.locator(".hero-actions a.github-button"),
      p + " star is not in the CTA row"
    ).toHaveCount(0);
    // The star shares one row with the identity line (logo, name, version badge).
    const row = page.locator(".hero .hero-identity");
    await expect(row, p + " identity row present").toHaveCount(1);
    const identity = row.locator(".identity");
    const star = row.locator("a.github-button");
    await expect(identity, p + " identity in the row").toHaveCount(1);
    await expect(star, p + " star in the row").toHaveCount(1);
    await expect(star, p + " star visible").toBeVisible();
    // The two render on the same row, with the star to the right of the identity pill.
    const idBox = await identity.boundingBox();
    const starBox = await star.boundingBox();
    const idMid = idBox.y + idBox.height / 2;
    expect(idMid, p + " star shares the identity row (top)").toBeGreaterThan(starBox.y - 1);
    expect(idMid, p + " star shares the identity row (bottom)").toBeLessThan(
      starBox.y + starBox.height + 1
    );
    expect(starBox.x, p + " star sits to the right of the identity").toBeGreaterThan(
      idBox.x + idBox.width - 1
    );
  }
});


test("the medium comparison table stacks without horizontal overflow on a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const table = page.locator("table.compare");
  await expect(table).toBeVisible();
  // No horizontal overflow: the table fits within the viewport width.
  const fits = await table.evaluate((el) => el.scrollWidth <= document.documentElement.clientWidth + 1);
  expect(fits, "comparison table must not overflow the mobile viewport").toBe(true);
  // On narrow screens each value cell exposes its column label for the stacked-card layout.
  const labelShown = await page.locator("table.compare td[data-label]").first().evaluate((el) => {
    const before = getComputedStyle(el, "::before");
    return before.content && before.content !== "none" && before.content !== "normal";
  });
  expect(labelShown, "stacked cells must show their column label via ::before").toBe(true);
});


test("the Why section presents the medium comparison table and the HTML blog reference", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const why = page.locator("#why");
  const table = why.locator("table.compare");
  await expect(table).toBeVisible();
  // Four media rows, with Commentable HTML as the highlighted row.
  await expect(table.locator("tbody tr")).toHaveCount(4);
  await expect(table.locator("tr.compare-hero", { hasText: "Commentable HTML" })).toHaveCount(1);
  // The section references the external HTML blog post, opening in a new tab.
  const blog = why.locator('a[href*="unreasonable-effectiveness-of-html"]').first();
  await expect(blog).toHaveAttribute("target", "_blank");
  await expect(blog).toHaveAttribute("rel", /noopener/);
});


test("the review-loop diagram lives in the Why section, not the loop section", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#why .loop-figure")).toHaveCount(1);
  await expect(page.locator("#loop .loop-figure")).toHaveCount(0);
  // The loop section keeps its heading and the three-column self/peer/reviewer steps.
  await expect(page.locator("#loop .section-title")).toHaveCount(1);
  expect(await page.locator("#loop .loop-col").count()).toBe(3);
});


test("the Why section states commentable-html shortens the AI planning loop", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#why")).toContainText("drastically shortens the AI planning and iteration loop");
});


test("the 'With Commentable HTML' bullet says an even richer HTML and highlights 'review in place' (SITE-WHY-10)", async ({ page }) => {
  // The comment-style highlight mirrors the runtime amber mark; assert the exact amber fill under
  // both color schemes (an opaque gray or blue would still be "not transparent", so a bare opacity
  // check would not prove the named amber behavior).
  const amberByScheme = {
    light: "rgba(245, 158, 11, 0.32)",
    dark: "rgba(251, 191, 36, 0.28)",
  };
  for (const scheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
    const bullet = page.locator(".why-list li", { hasText: "With Commentable HTML" });
    await expect(bullet).toHaveCount(1);
    await expect(bullet).toContainText(/even richer HTML/i);
    await expect(bullet).not.toContainText(/the same rich HTML/i);
    const mark = bullet.locator("mark.hl-comment");
    await expect(mark).toHaveText("review in place");
    const bg = await mark.evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(bg, scheme + " highlight fill must be the runtime amber").toBe(amberByScheme[scheme]);
  }
});


test("the Why section frames HTML as the de-facto standard for AI planning and reporting (SITE-WHY-07)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const why = page.locator("#why");
  await expect(why).toContainText(/de-facto standard/i);
  await expect(why).toContainText(/plan/i);
  await expect(why).toContainText(/report/i);
  // The old framing overstated it as agents "increasingly answer with HTML"; it should be gone.
  await expect(why).not.toContainText("increasingly answer with");
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
  // The demo iframe is lazy-loaded far down the page; scroll it into view so it loads (as a
  // real reader reaching the section would), then assert it mounts under the page CSP.
  await page.locator("#demo iframe").scrollIntoViewIfNeeded();
  const frame = page.frameLocator("#demo iframe");
  await expect(frame.locator(".cm-toolbar")).toHaveCount(1, { timeout: 20000 });
  await expect(frame.locator("#btnCopyAll")).toBeAttached({ timeout: 20000 });
});


test("all demo reports load and their toolbars mount", async ({ page }) => {
  for (const report of ["report-taxi.html", "report-community-garden.html", "report-triage.html", "report-metrics.html", "report-checklist.html", "report-notes.html"]) {
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
  for (const p of ["/", "/commentable-html/", "/commentable-html/tutorial/", "/urikan-ai-marketplace-auto-updater/"]) {
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

