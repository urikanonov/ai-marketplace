const { test, expect, contrastRatio, compositedContrast, PROD } = require("./site-support");

test("the plugin card body shows a pointer cursor so it reads as clickable (SITE-HUB-06)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const card = page.locator(".plugin-card", { hasText: "commentable-html" }).first();
  // The whole card navigates, so its body carries the hand/pointer cursor to signal it.
  expect(await card.evaluate((el) => getComputedStyle(el).cursor)).toBe("pointer");
  expect(await card.locator(".desc").evaluate((el) => getComputedStyle(el).cursor)).toBe("pointer");
  // The install command block stays a text surface (it does not navigate), not a pointer.
  expect(await card.locator(".cmd").first().evaluate((el) => getComputedStyle(el).cursor)).not.toBe("pointer");
});

test("the hub Learn more button uses the brand accent color, not yellow (SITE-HUB-07)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const learn = page.locator(".plugin-card .learn-more").first();
  const bg = await learn.evaluate((el) => getComputedStyle(el).backgroundColor);
  const accentBg = await page.evaluate(() => {
    const d = document.createElement("div");
    d.style.backgroundColor = "var(--cp-accent)";
    document.body.appendChild(d);
    const c = getComputedStyle(d).backgroundColor;
    d.remove();
    return c;
  });
  expect(bg).toBe(accentBg);
  // The old design used amber #ffc107 -> rgb(255, 193, 7); make sure that is gone.
  expect(bg).not.toBe("rgb(255, 193, 7)");
});

test("every page exposes a skip-to-content link that targets the main region", async ({ page }) => {
  for (const p of ["/", "/commentable-html/", "/commentable-html/tutorial/", "/urikan-ai-marketplace-auto-updater/"]) {
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

test("star widget degrades to a visible plain link when its script is blocked", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const link = page.locator("a.github-button");
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute("href", "https://github.com/urikanonov/ai-marketplace");
});

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
