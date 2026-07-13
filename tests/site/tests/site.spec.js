const { test, expect } = require("@playwright/test");

function contrastRatio(foreground, background) {
  const channel = (value) => {
    const normalized = value / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : Math.pow((normalized + 0.055) / 1.055, 2.4);
  };
  const luminance = (color) => {
    const r = channel(color.r);
    const g = channel(color.g);
    const b = channel(color.b);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

async function compositedContrast(page, selector) {
  return page.locator(selector).first().evaluate((el) => {
    const parseColor = (value) => {
      const raw = (value || "").trim().toLowerCase();
      if (!raw || raw === "transparent") return { r: 0, g: 0, b: 0, a: 0 };
      const hex = raw.match(/^#([0-9a-f]{6})$/i);
      if (hex) {
        return {
          r: parseInt(hex[1].slice(0, 2), 16),
          g: parseInt(hex[1].slice(2, 4), 16),
          b: parseInt(hex[1].slice(4, 6), 16),
          a: 1,
        };
      }
      const rgb = raw.match(/^rgba?\((.*)\)$/);
      if (rgb) {
        const parts = rgb[1].replace(/\//g, " ").split(/[,\s]+/).filter(Boolean);
        const channel = (part) => part.endsWith("%") ? Number(part.slice(0, -1)) * 2.55 : Number(part);
        return {
          r: channel(parts[0]),
          g: channel(parts[1]),
          b: channel(parts[2]),
          a: parts[3] === undefined ? 1 : Number(parts[3]),
        };
      }
      const srgb = raw.match(/^color\(srgb\s+(.+)\)$/);
      if (srgb) {
        const parts = srgb[1].replace(/\//g, " ").split(/\s+/).filter(Boolean);
        return {
          r: Number(parts[0]) * 255,
          g: Number(parts[1]) * 255,
          b: Number(parts[2]) * 255,
          a: parts[3] === undefined ? 1 : Number(parts[3]),
        };
      }
      throw new Error("unsupported color format: " + value);
    };
    const blend = (top, bottom) => {
      const alpha = top.a + bottom.a * (1 - top.a);
      if (alpha === 0) return { r: 0, g: 0, b: 0, a: 0 };
      return {
        r: (top.r * top.a + bottom.r * bottom.a * (1 - top.a)) / alpha,
        g: (top.g * top.a + bottom.g * bottom.a * (1 - top.a)) / alpha,
        b: (top.b * top.a + bottom.b * bottom.a * (1 - top.a)) / alpha,
        a: alpha,
      };
    };
    let background = { r: 0, g: 0, b: 0, a: 0 };
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE) {
      background = blend(background, parseColor(getComputedStyle(node).backgroundColor));
      if (background.a >= 0.999) break;
      node = node.parentElement;
    }
    if (background.a < 0.999) {
      background = blend(background, { r: 255, g: 255, b: 255, a: 1 });
    }
    return {
      foreground: parseColor(getComputedStyle(el).color),
      background: background,
    };
  });
}

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

test("a plugin card is clickable across its body, navigating to the plugin page (SITE-HUB-06)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const card = page.locator(".plugin-card", { hasText: "commentable-html" }).first();
  const desc = card.locator(".desc");
  await desc.scrollIntoViewIfNeeded();
  const box = await desc.boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page).toHaveURL(/\/commentable-html\/$/);
});

test("the card copy button and Learn more stay independently clickable over the card link (SITE-HUB-06)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const card = page.locator(".plugin-card", { hasText: "commentable-html" }).first();
  await card.locator(".copy-btn").click();
  await expect(page).toHaveURL(/\/$/);
});

test("the plugin card body shows a pointer cursor so it reads as clickable (SITE-HUB-06)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const card = page.locator(".plugin-card", { hasText: "commentable-html" }).first();
  // The whole card navigates, so its body carries the hand/pointer cursor to signal it.
  expect(await card.evaluate((el) => getComputedStyle(el).cursor)).toBe("pointer");
  expect(await card.locator(".desc").evaluate((el) => getComputedStyle(el).cursor)).toBe("pointer");
  // The install command block stays a text surface (it does not navigate), not a pointer.
  expect(await card.locator(".cmd").evaluate((el) => getComputedStyle(el).cursor)).not.toBe("pointer");
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

test("the review-loop diagram swaps to a vertical, uncramped layout on a mobile viewport (SITE-WHY-04)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const horizontal = page.locator("#why .loop-fig-h");
  const vertical = page.locator("#why .loop-fig-v");
  await expect(horizontal).toHaveCount(1);
  await expect(vertical).toHaveCount(1);
  // Desktop shows the wide horizontal diagram; the tall variant is hidden.
  await page.setViewportSize({ width: 1000, height: 900 });
  await expect(horizontal).toBeVisible();
  await expect(vertical).toBeHidden();
  // Mobile swaps to the tall vertical diagram so the labels are not cramped against the
  // boxes; the horizontal variant is hidden. The rendered figure is taller than it is wide.
  await page.setViewportSize({ width: 380, height: 900 });
  await expect(vertical).toBeVisible();
  await expect(horizontal).toBeHidden();
  const box = await vertical.boundingBox();
  expect(box.height).toBeGreaterThan(box.width);
  // The vertical variant numbers each transfer with a badge anchored to its directional arrow
  // (agent-to-you down, you-to-agent up) so the flow direction is not lost on mobile (SITE-WHY-04).
  await expect(vertical.locator(".loop-fig-badge")).toHaveCount(3);
  await expect(vertical).toContainText("Generates HTML");
  await expect(vertical).toContainText("Copy all back");
  await expect(vertical).toContainText("Comment inline");
  await expect(vertical).toContainText("reload and repeat");
});

test("mobile comparison cards color only the verdicts and show a good/total score (SITE-WHY-05)", async ({ page }) => {
  await page.setViewportSize({ width: 380, height: 900 });
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const table = page.locator("table.compare");
  await expect(table.locator("tr", { hasText: "Plain HTML" }).locator(".cmp-score")).toHaveText("3/5");
  await expect(table.locator("tr.compare-hero", { hasText: "Commentable HTML" }).locator(".cmp-score")).toHaveText("5/5");
  const goodBg = await table.locator('td[data-v="good"] .cmp-v').first().evaluate((el) => getComputedStyle(el).backgroundColor);
  const badBg = await table.locator('td[data-v="bad"] .cmp-v').first().evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(goodBg).not.toBe("rgba(0, 0, 0, 0)");
  expect(badBg).not.toBe("rgba(0, 0, 0, 0)");
  expect(goodBg).not.toBe(badBg);
  // The hero row no longer has a full-cell fill on mobile - only the verdict pills are colored.
  const heroCellBg = await table.locator("tr.compare-hero td").first().evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(heroCellBg).toBe("rgba(0, 0, 0, 0)");
});

test("the portability section shows three modes including Offline with a source graph (SITE-PLUGIN-09)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".mode-card")).toHaveCount(3);
  await expect(page.locator(".mode-card h3", { hasText: "Offline" })).toHaveCount(1);
  await expect(page.locator(".mode-card .mode-sources .src").first()).toBeVisible();
  // Offline inlines the CDN parts (mermaid + charts): its card has an inline chip and no CDN chip.
  const offline = page.locator(".mode-card", { hasText: "Offline" });
  await expect(offline.locator(".src-cdn")).toHaveCount(0);
  await expect(offline.locator(".src-inline")).not.toHaveCount(0);
  // Non-portable still pulls mermaid + charts from a CDN.
  await expect(page.locator(".mode-card", { hasText: "Non-portable" }).locator(".src-cdn")).not.toHaveCount(0);
});

test("the portability section explains the CDN chip needs a network connection and Offline removes it (SITE-PLUGIN-10)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const modes = page.locator("#modes");
  // The CDN chip means mermaid/charts load over the network, so a Non-portable or Portable report
  // that uses them needs an internet connection to render them; Offline inlines them instead.
  const note = modes.locator(".modes-note");
  await expect(note).toContainText(/internet connection/i);
  await expect(note).toContainText(/mermaid/i);
  await expect(note).toContainText(/chart/i);
  await expect(note).toContainText(/Portable/);
  await expect(note).toContainText(/Offline/);
});

test("the What you get section covers exporting an Offline, zero-network copy (SITE-PLUGIN-11)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const features = page.locator("#features");
  await expect(features).toContainText(/Offline/);
  await expect(features).toContainText(/no network|zero network|without a network/i);
});

test("portability source chips keep AA contrast in the light theme (SITE-A11Y-05)", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  for (const selector of [".src-cdn", ".src-inline"]) {
    const colors = await compositedContrast(page, selector);
    expect(
      contrastRatio(colors.foreground, colors.background),
      selector + " contrast"
    ).toBeGreaterThanOrEqual(4.5);
  }
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
  await expect(page).toHaveTitle(/Commentable HTML/i);
  await expect(page.locator(".badge.version")).toContainText(/v\d+\.\d+\.\d+/);
  expect(await page.locator("#features .feature").count()).toBeGreaterThanOrEqual(4);
  expect(await page.locator("#changelog .release").count()).toBeGreaterThanOrEqual(1);
  await expect(page.locator("#demo iframe")).toHaveAttribute("src", /demo\/report-taxi\.html/);
});

test("demo has one safe full-screen button and a four-option slider", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const fs = page.locator("#demo-fullscreen");
  await expect(fs).toHaveCount(1);
  await expect(fs).toHaveAttribute("target", "_blank");
  expect((await fs.getAttribute("rel")) || "").toContain("noopener");
  await expect(fs).toHaveAccessibleName(/full screen.*new tab/i);
  await expect(page.locator(".demo-tab")).toHaveCount(4);
  await expect(page.locator(".demo-tab.active")).toHaveText(/Taxi/i);
  for (const id of ["#demo-tab-taxi", "#demo-tab-garden", "#demo-tab-triage", "#demo-tab-metrics"]) {
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
  await expect(card.locator(".copy-btn")).toBeVisible();
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
  const metrics = page.locator("#demo-tab-metrics");
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
  await expect(metrics).toHaveAttribute("aria-selected", "true");
  await expect(metrics).toHaveAttribute("tabindex", "0");
  await expect(taxi).toHaveAttribute("tabindex", "-1");
  await expect(panel).toHaveAttribute("aria-labelledby", "demo-tab-metrics");
  await expect(page.locator("#demo-iframe")).toHaveAttribute("title", /Visuals Matrix|report-metrics/);
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
  for (const report of ["report-taxi.html", "report-community-garden.html", "report-triage.html", "report-metrics.html"]) {
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

const PROD = "https://urikanonov.github.io/ai-marketplace/";

test("hub head exposes canonical, Open Graph, and Twitter Card tags", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", PROD);
  await expect(page.locator('meta[property="og:type"]')).toHaveAttribute("content", "website");
  await expect(page.locator('meta[property="og:title"]')).toHaveAttribute("content", /ai-marketplace/);
  await expect(page.locator('meta[property="og:url"]')).toHaveAttribute("content", PROD);
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute("content", PROD + "assets/og-cover.png");
  await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute("content", "summary_large_image");
});

test("plugin and tutorial pages carry a self-referencing canonical and Open Graph metadata", async ({ page }) => {
  const cases = [
    ["/commentable-html/", PROD + "commentable-html/"],
    ["/commentable-html/tutorial/", PROD + "commentable-html/tutorial/"],
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
  for (const u of [PROD, PROD + "commentable-html/", PROD + "commentable-html/tutorial/"]) {
    expect(body).toContain("<loc>" + u + "</loc>");
  }
});

test("llms.txt is served and links each plugin and the tutorial", async ({ request }) => {
  const r = await request.get("/llms.txt");
  expect(r.status()).toBeLessThan(400);
  const body = await r.text();
  expect(body).toContain("# ai-marketplace");
  expect(body).toContain("(" + PROD + "commentable-html/)");
  expect(body).toContain("commentable-html/tutorial/");
});

test("the og:image cover asset is served as a PNG", async ({ request }) => {
  const r = await request.get("/assets/og-cover.png");
  expect(r.status()).toBeLessThan(400);
  expect(r.headers()["content-type"]).toContain("image/png");
});

test("the hub H1 reads as continuous text with correct word spacing", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const text = (await page.locator("h1").first().textContent()).replace(/\s+/g, " ").trim();
  expect(text).toBe("A marketplace of AI plugins for the Copilot CLI");
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
  // Clicking a header anchor moves the URL fragment to that section.
  await page.locator("section#install .section-title a.header-anchor").click();
  await expect(page).toHaveURL(/#install$/);
});
