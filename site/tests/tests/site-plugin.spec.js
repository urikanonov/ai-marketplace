const { test, expect } = require("@playwright/test");
const { contrastRatio, compositedContrast, installNetworkBlock } = require("./site-helpers");
const fs = require("fs");
const path = require("path");

installNetworkBlock(test);

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
  // The vertical variant numbers ALL FOUR steps with a badge (SITE-WHY-04), including the
  // "Reload and repeat" loop-back, so on mobile step 4 reads like the other numbered actions
  // instead of a plain italic caption. The old italic caption class is gone.
  await expect(vertical.locator(".loop-fig-badge")).toHaveCount(4);
  await expect(vertical.locator(".loop-fig-repeat")).toHaveCount(0);
  await expect(vertical).toContainText("Generates HTML");
  await expect(vertical).toContainText("Copy all back");
  await expect(vertical).toContainText("Comment inline");
  // Step 4 reads as a title-cased action ("Reload and repeat") in both SVG variants.
  await expect(vertical).toContainText("Reload and repeat");
  await expect(horizontal).toContainText("Reload and repeat");
});


test("the comparison table's Markdown-file verdict reads 'OK / Need viewer' (SITE-WHY-08)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const markdownRow = page.locator("table.compare tbody tr", { hasText: "Markdown file" });
  const bigPlan = markdownRow.locator('td[data-label="Handles a big plan"] .cmp-v');
  await expect(bigPlan).toHaveText("OK / Need viewer");
});


test("the comparison table breaks a bit out of the section padding for more width (SITE-WHY-09)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const table = page.locator("table.compare");
  const intro = page.locator(".why-mediums > p").first();
  // Desktop/tablet: the table pulls into the section-block side padding by a meaningful amount, so it
  // is wider than the prose column on both sides - not just a decorative 1px.
  await page.setViewportSize({ width: 1000, height: 900 });
  const t = await table.boundingBox();
  const p = await intro.boundingBox();
  expect(p.x - t.x).toBeGreaterThanOrEqual(20);
  expect((t.x + t.width) - (p.x + p.width)).toBeGreaterThanOrEqual(20);
  // Mobile: the pull-out is scoped to min-width:641px, so the stacked card layout is not pulled out.
  await page.setViewportSize({ width: 380, height: 900 });
  const tm = await table.boundingBox();
  const pm = await intro.boundingBox();
  expect(tm.x).toBeGreaterThanOrEqual(pm.x - 1);
});


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
    // The shared footer structure is the attribution + nav row. The commentable-html plugin page
    // additionally carries a page-specific rich-content credit (SITE-CREDIT-01) in a `.credit`
    // span, which is intentionally NOT part of this shared structure, so exclude it here.
    const links = await page.locator("footer.footer a").evaluateAll((anchors) =>
      anchors
        .filter((a) => !a.closest(".credit"))
        .map((a) => [a.textContent.trim().replace(/\s+/g, " "), a.href])
    );
    expect(links).toEqual([...common, ["Plugin source", pluginSource]]);
    structures.push(links.map(([label]) => label));
  }

  expect(structures[1]).toEqual(structures[0]);
  expect(structures[2]).toEqual(structures[0]);
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


test("the What you get section showcases the commentable-decks capability (SITE-PLUGIN-12)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const features = page.locator("#features");
  await expect(features).toContainText(/deck/i);
  await expect(features).toContainText(/slide|present mode|presentation/i);
});


test("the plugin page credits the vendored frontend-slides deck engine (SITE-PLUGIN-13)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });

  // A dedicated Credits section names the upstream project, its author, and its license.
  const credits = page.locator("#credits");
  await expect(credits).toBeVisible();
  await expect(credits).toContainText(/frontend-slides/i);
  await expect(credits).toContainText(/Zara Zhang/i);
  await expect(credits).toContainText(/MIT/);
  await expect(
    credits.locator('a[href="https://github.com/zarazhangrui/frontend-slides"]')
  ).toHaveCount(1);

  // The Commentable decks feature card also carries the credit line.
  const deckCredit = page.locator("#features .feature-credit");
  await expect(deckCredit).toContainText(/frontend-slides/i);
  await expect(deckCredit).toContainText(/Zara Zhang/i);

  // Credits sits above the changelog in document order.
  const changelogFollowsCredits = await page.evaluate(() => {
    const credits = document.querySelector("#credits");
    const changelog = document.querySelector("#changelog");
    return Boolean(
      credits.compareDocumentPosition(changelog) & Node.DOCUMENT_POSITION_FOLLOWING
    );
  });
  expect(changelogFollowsCredits).toBe(true);
});


test("the plugin page has a Private by design section emphasizing local-only data (SITE-PLUGIN-14)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const privacy = page.locator("#privacy");
  await expect(privacy).toBeVisible();
  await expect(privacy).toContainText(/Private by design/i);
  await expect(privacy).toContainText(/localStorage/);
  await expect(privacy).toContainText(/never (uploaded|transmitted|sent)/i);
  await expect(privacy).toContainText(/no server|no account|no telemetry/i);
  await expect(privacy).toContainText(/Export Offline|zero network|air-gapped/i);
  // The nav offers a link to the privacy section.
  await expect(page.locator('.nav-links a[href="#privacy"]')).toHaveCount(1);
  // Four privacy cards laid out 2x2 (no orphan third-row card) on a desktop-width viewport.
  await page.setViewportSize({ width: 1100, height: 900 });
  await expect(page.locator("#privacy .grid > .card.feature")).toHaveCount(4);
  const privacyCols = await page
    .locator("#privacy .grid")
    .evaluate((el) => getComputedStyle(el).gridTemplateColumns.trim().split(/\s+/).length);
  expect(privacyCols).toBe(2);
});


test("the features section pitches no extension, all-HTML, and cross-platform support (SITE-PLUGIN-21)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const card = page.locator("#features .grid > .card.feature", { hasText: "No extension" });
  await expect(card).toHaveCount(1);
  await expect(card).toContainText(/no browser extension/i);
  await expect(card).toContainText("HTML");
  await expect(card).toContainText("Windows");
  await expect(card).toContainText("macOS");
  await expect(card).toContainText("Linux");
});


test("the privacy section qualifies comment persistence to same-origin hosting and export (SITE-PLUGIN-22)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const privacy = page.locator("#privacy");
  await expect(privacy).toContainText("keyed to a stable id");
  await expect(privacy).toContainText("served from one web origin");
  await expect(privacy).toContainText("an exported file always carries every comment inside it");
});


test("each feature card leads with an inline SVG icon beside the title (SITE-PLUGIN-15)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  for (const sectionId of ["#features", "#privacy"]) {
    const cards = page.locator(`${sectionId} .grid > .card.feature`);
    const n = await cards.count();
    expect(n).toBeGreaterThan(0);
    const icons = page.locator(`${sectionId} .grid > .card.feature > .feature-icon > svg`);
    expect(await icons.count()).toBe(n);
    // The icon sits on the same row as the title (beside it), not stacked on a row above it.
    const first = cards.first();
    const iconBox = await first.locator(".feature-icon").boundingBox();
    const titleBox = await first.locator("h3").boundingBox();
    expect(iconBox).not.toBeNull();
    expect(titleBox).not.toBeNull();
    expect(iconBox.y).toBeLessThan(titleBox.y + titleBox.height);
    expect(iconBox.y + iconBox.height).toBeGreaterThan(titleBox.y);
    expect(iconBox.x + iconBox.width).toBeLessThanOrEqual(titleBox.x + 2);
  }
});


test("feature card headings render without a generated greater-than prefix (SITE-PLUGIN-17)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const headings = page.locator(".card.feature h3");
  const prefixes = await headings.evaluateAll((els) =>
    els.map((el) => getComputedStyle(el, "::before").content)
  );
  expect(prefixes.length).toBeGreaterThan(0);
  for (const prefix of prefixes) {
    expect(["none", "normal", '""']).toContain(prefix);
  }
});


test("the What you get section has a Rich content card covering charts, diagrams, boards, diffs, and code (SITE-PLUGIN-16)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const features = page.locator("#features");
  await expect(features).toContainText(/Rich content/i);
  await expect(features).toContainText(/triage board/i);
  await expect(features).toContainText(/diff/i);
  await expect(features).toContainText(/side-by-side/i);
  await expect(features).toContainText(/snippet/i);
});


test("the What you get section highlights that comments survive a browser restart (SITE-PLUGIN-19)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const features = page.locator("#features");
  await expect(features).toContainText(/survive a restart/i);
  await expect(features).toContainText(/localStorage/);
  await expect(features).toContainText(/reboot/i);
});


test("the What you get Round-trip card explains Copy all returns every comment at once for one coordinated edit (SITE-PLUGIN-20)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const features = page.locator("#features");
  await expect(features).toContainText(/every comment at once/i);
  await expect(features).toContainText(/coordinated/i);
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


test("plugin page renders version, features, changelog, and demo", async ({ page }) => {
  const resp = await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  expect(resp.status()).toBeLessThan(400);
  await expect(page).toHaveTitle(/Commentable HTML/i);
  await expect(page.locator(".badge.version")).toContainText(/v\d+\.\d+\.\d+/);
  expect(await page.locator("#features .feature").count()).toBeGreaterThanOrEqual(4);
  expect(await page.locator("#changelog .release").count()).toBeGreaterThanOrEqual(1);
  await expect(page.locator("#demo iframe")).toHaveAttribute("src", /demo\/report-taxi\.html/);
});


test("demo has one safe full-screen button and a seven-option slider (SITE-DEMO-01)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const fs = page.locator("#demo-fullscreen");
  await expect(fs).toHaveCount(1);
  await expect(fs).toHaveAttribute("target", "_blank");
  expect((await fs.getAttribute("rel")) || "").toContain("noopener");
  await expect(fs).toHaveAccessibleName(/full screen.*new tab/i);
  await expect(page.locator(".demo-tab")).toHaveCount(7);
  await expect(page.locator(".demo-tab.active")).toHaveText(/Taxi/i);
  for (const id of ["#demo-tab-taxi", "#demo-tab-showcase", "#demo-tab-garden", "#demo-tab-triage", "#demo-tab-metrics", "#demo-tab-checklist", "#demo-tab-notes"]) {
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
  // Scroll the lazy demo iframe into view so it loads promptly (as a reader reaching it would),
  // then assert the deck mounts inside it.
  await page.locator("#demo-iframe").scrollIntoViewIfNeeded();
  const frame = page.frameLocator("#demo-iframe");
  await expect(frame.locator("#commentRoot[data-cmh-mode='deck']")).toHaveCount(1, { timeout: 15000 });
  await expect(frame.locator(".cmh-deck-mode-toggle")).toBeVisible();
});


test("demo slider exposes and loads the Notes report (SITE-DEMO-11)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const notes = page.locator("#demo-tab-notes");
  await expect(notes).toBeVisible();
  await expect(notes).toHaveAttribute("role", "tab");
  await expect(notes).toHaveAttribute("aria-controls", "demo-panel");
  await expect(notes).toHaveAttribute("aria-selected", "false");
  await expect(notes).toHaveAttribute("tabindex", "-1");
  // Bring the demo into view first so the lazy iframe loads eagerly, then activate Notes and
  // confirm the iframe actually FETCHES report-notes.html (a live demo, not just a swapped href).
  await page.locator("#demo-panel").scrollIntoViewIfNeeded();
  const [resp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/demo/report-notes.html"), { timeout: 20000 }),
    notes.click(),
  ]);
  expect(resp.status()).toBeLessThan(400);
  await expect(page.locator("#demo-iframe")).toHaveAttribute("src", /report-notes\.html/);
  await expect(page.locator("#demo-fullscreen")).toHaveAttribute("href", /report-notes\.html/);
  await expect(page.locator("#demo-title")).toHaveText("Notes");
  await expect(page.locator("#demo-panel")).toHaveAttribute("aria-labelledby", "demo-tab-notes");
});


test("every example is present on the site as a live demo tab (SITE-DEMO-12)", async ({ page, request }) => {
  // The examples/ directory is the source of truth for "examples"; every HTML example must be
  // surfaced on the site as a live demo - a slider tab that loads it in the demo iframe, backed
  // by the file actually being served under commentable-html/demo/. This parity check fails if a
  // new example is added without wiring it into the Try it live slider.
  const examplesDir = path.resolve(__dirname, "..", "..", "..", "plugins", "commentable-html", "examples");
  const examples = fs.readdirSync(examplesDir).filter((name) => name.endsWith(".html")).sort();
  expect(examples.length).toBeGreaterThan(0);
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  for (const file of examples) {
    // Exact string match (not a regex built from the filename) - stronger than a substring/anchored
    // pattern and free of any escaping concern about characters in the filename.
    const demoPath = "demo/" + file;
    const tab = page.locator(`.demo-tab[data-file="${file}"]`);
    await expect(tab, `expected a live-demo slider tab for example ${file}`).toHaveCount(1);
    await tab.click();
    await expect(page.locator("#demo-iframe")).toHaveAttribute("src", demoPath);
    await expect(page.locator("#demo-fullscreen")).toHaveAttribute("href", demoPath);
    const resp = await request.get("/commentable-html/demo/" + file);
    expect(resp.status(), `expected ${file} to be served under commentable-html/demo/`).toBeLessThan(400);
  }
});



test("the commentable-html nav has a Marketplace switcher that reveals tiles to the other plugins (SITE-SWITCH-01)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const trigger = page.locator(".nav-switcher-trigger");
  await expect(trigger).toHaveAttribute("href", "../");
  const menu = page.locator(".nav-switcher-menu");
  // Hidden until the control is hovered or focused (progressive enhancement).
  await expect(menu).toBeHidden();
  await trigger.hover();
  await expect(menu).toBeVisible();
  // Tiles link to the OTHER plugins, not to the current commentable-html page.
  await expect(menu.locator("a[href=\"../multi-duck/\"]")).toHaveCount(1);
  await expect(menu.locator("a[href=\"../urikan-ai-marketplace-auto-updater/\"]")).toHaveCount(1);
  await expect(menu.locator("a[href=\"../commentable-html/\"]")).toHaveCount(0);
  // And an all-plugins link back to the hub.
  await expect(menu.locator("a.switch-tile-all")).toHaveAttribute("href", "../");
});


test("the plugin switcher flyout also reveals on keyboard focus (SITE-SWITCH-01)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const menu = page.locator(".nav-switcher-menu");
  await expect(menu).toBeHidden();
  await page.locator(".nav-switcher-trigger").focus();
  await expect(menu).toBeVisible();
});


test("the plugin page footer credits mermaid and Chart.js (SITE-CREDIT-01)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const credit = page.locator("footer.footer .credit");
  await expect(credit).toHaveCount(1);
  // User-facing content: assert it is actually visible, not merely present in the DOM (a hidden
  // credit would still pass count/text checks) - per the repo testing guidelines.
  await expect(credit).toBeVisible();
  await expect(credit).toContainText("mermaid");
  await expect(credit).toContainText("Chart.js");
  await expect(credit).toContainText("MIT");
  await expect(credit.locator('a[href="https://mermaid.js.org/"]')).toHaveText("mermaid");
  await expect(credit.locator('a[href="https://www.chartjs.org/"]')).toHaveText("Chart.js");
});


test("the plugin page leads with a review-workflow showcase and a real UI screenshot above the feature grid (SITE-PLUGIN-23)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });

  // The hero lead itself lands the one-line value prop, not only the prose lower down.
  await expect(page.locator("header.hero p.lead")).toContainText(/code review for your AI's plans and reports/i);

  const showcase = page.locator("#showcase");
  await expect(showcase).toHaveCount(1);

  // The showcase is a contained CARD (a visible background, a real border, rounded corners, a
  // drop shadow, and padding), so it reads as a cohesive unit instead of floating loose on the page.
  const card = showcase.locator(".showcase-card");
  await expect(card).toHaveCount(1);
  const cardStyle = await card.evaluate((el) => {
    const s = getComputedStyle(el);
    return {
      bg: s.backgroundColor,
      border: parseFloat(s.borderTopWidth),
      pad: parseFloat(s.paddingTop),
      radius: parseFloat(s.borderTopLeftRadius),
      shadow: s.boxShadow,
    };
  });
  expect(cardStyle.bg).not.toBe("rgba(0, 0, 0, 0)");
  expect(cardStyle.border).toBeGreaterThan(0);
  expect(cardStyle.pad).toBeGreaterThan(0);
  expect(cardStyle.radius).toBeGreaterThan(0);
  expect(cardStyle.shadow).not.toBe("none");

  // The gap below the showcase is tight (the card sits close to the next section) - the block's own
  // bottom padding is small AND the following "Why" section's top padding is trimmed, so the visible
  // gap between the showcase card and the "Why" section card is about half the default section gap.
  const showcasePadBottom = await showcase.evaluate((el) => parseFloat(getComputedStyle(el).paddingBottom));
  expect(showcasePadBottom).toBeLessThanOrEqual(16);
  const cardToWhyGap = await page.evaluate(() => {
    const card = document.querySelector("#showcase .showcase-card").getBoundingClientRect();
    const why = document.querySelector("#why .section-block").getBoundingClientRect();
    return why.top - card.bottom;
  });
  expect(cardToWhyGap).toBeGreaterThan(0);
  expect(cardToWhyGap).toBeLessThanOrEqual(36);

  // The showcase leads the page: it is the FIRST element after the hero header (not buried below
  // other blocks), so the value proposition is on the first screen.
  const afterHero = await page.evaluate(() => {
    const showcase = document.querySelector("#showcase");
    return showcase.previousElementSibling === document.querySelector("main > header.hero");
  });
  expect(afterHero).toBe(true);

  // A real product screenshot (the specific landing crop) that shows a report with a HIGHLIGHTED
  // selection and the comment window - not a composer-only image - framed, that decodes.
  const img = showcase.locator("img.showcase-img");
  await expect(img).toBeVisible();
  await expect(img).toHaveAttribute("src", /tutorial\/assets\/landing-composer\.png$/);
  await expect(img).toHaveAttribute("alt", /inline comment window/i);
  await expect(img).toHaveAttribute("alt", /Write your review comment/i);
  await expect(img).toHaveAttribute("alt", /165 million/i);
  await expect(img).toHaveAttribute("alt", /highlighted/i);
  await img.scrollIntoViewIfNeeded();
  await expect.poll(() => img.evaluate((el) => el.naturalWidth)).toBeGreaterThan(0);
  // Pin the replacement asset's intrinsic dimensions so a swap back to a differently-sized
  // (e.g. composer-only) image is caught.
  const natural = await img.evaluate((el) => ({ w: el.naturalWidth, h: el.naturalHeight }));
  expect(natural).toEqual({ w: 1140, h: 500 });

  // The concrete review workflow (Select -> Comment inline -> Copy all -> Reload) renders as four
  // numbered steps, so a first-time visitor sees how they would use it without scrolling.
  await expect(showcase.locator(".showcase-flow .showcase-step")).toHaveCount(4);
  for (const label of ["Select", "Comment inline", "Copy all", "Reload"]) {
    await expect(showcase.locator(".showcase-flow")).toContainText(label);
  }
  // The steps expose explicit ARIA list semantics (role="list" is the VoiceOver safeguard for the
  // list-style:none list, whose implicit role Safari drops); pin the attribute so removing it fails.
  const flow = showcase.locator("ol.showcase-flow");
  await expect(flow).toHaveAttribute("role", "list");
  await expect(flow.getByRole("listitem")).toHaveCount(4);

  // The showcase CTA bridges straight to the live demo.
  await expect(showcase.locator(".showcase-cta")).toHaveAttribute("href", "#demo");

  // The showcase sits ABOVE both Install and the feature grid in document order.
  const placement = await page.evaluate(() => {
    const showcase = document.querySelector("#showcase");
    const install = document.querySelector("#install");
    const features = document.querySelector("#features");
    const FOLLOWING = Node.DOCUMENT_POSITION_FOLLOWING;
    return {
      beforeInstall: Boolean(showcase.compareDocumentPosition(install) & FOLLOWING),
      beforeFeatures: Boolean(showcase.compareDocumentPosition(features) & FOLLOWING),
    };
  });
  expect(placement.beforeInstall).toBe(true);
  expect(placement.beforeFeatures).toBe(true);
});


test("the showcase screenshot scales within a mobile viewport with no horizontal overflow (SITE-PLUGIN-24)", async ({ page }) => {
  await page.setViewportSize({ width: 380, height: 900 });
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });

  const img = page.locator("#showcase img.showcase-img");
  await expect(img).toBeVisible();
  // The image scales down responsively and stays FULLY within the viewport - both its left and
  // right edges are on-screen (not merely narrower than the viewport while shifted off an edge).
  const box = await img.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(380);
  // The showcase block itself introduces no horizontal overflow at phone width.
  const noOverflow = await page
    .locator("#showcase")
    .evaluate((el) => el.scrollWidth <= el.clientWidth + 1);
  expect(noOverflow).toBe(true);
  // The card collapses to a single column: the screenshot stacks above the steps.
  const shot = await page.locator("#showcase .showcase-shot").boundingBox();
  const copy = await page.locator("#showcase .showcase-copy").boundingBox();
  expect(shot.y + shot.height).toBeLessThanOrEqual(copy.y + 1);

  // It also collapses early - at a tablet width (820px, still below the ~900px breakpoint) - so the
  // narrow-copy two-column squeeze in the tablet band is gone, not only at phone width.
  await page.setViewportSize({ width: 820, height: 1100 });
  const tShot = await page.locator("#showcase .showcase-shot").boundingBox();
  const tCopy = await page.locator("#showcase .showcase-copy").boundingBox();
  expect(tShot.y + tShot.height).toBeLessThanOrEqual(tCopy.y + 1);
  // ...and it stays overflow-free with the image within the viewport in that tablet band too.
  const tImg = await page.locator("#showcase img.showcase-img").boundingBox();
  expect(tImg.x).toBeGreaterThanOrEqual(0);
  expect(tImg.x + tImg.width).toBeLessThanOrEqual(820);
  const tNoOverflow = await page
    .locator("#showcase")
    .evaluate((el) => el.scrollWidth <= el.clientWidth + 1);
  expect(tNoOverflow).toBe(true);
});


test("the showcase screenshot renders small and stays crisp on HiDPI (SITE-PLUGIN-25)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });

  const img = page.locator("#showcase img.showcase-img");
  await expect(img).toBeVisible();
  await img.scrollIntoViewIfNeeded();
  await expect.poll(() => img.evaluate((el) => el.naturalWidth)).toBeGreaterThan(0);
  const naturalWidth = await img.evaluate((el) => el.naturalWidth);

  // Check at BOTH the desktop two-column layout AND the single-column tablet layout (below the
  // 900px breakpoint), because the mobile override changes the frame sizing - the small cap and
  // the crispness must hold in both, not just on desktop.
  for (const width of [1280, 820]) {
    await page.setViewportSize({ width, height: 900 });
    const box = await img.boundingBox();
    // Small: the screenshot is a modest supporting visual, capped well below a hero-sized image.
    expect(box.width, `rendered width at ${width}px`).toBeLessThanOrEqual(440);
    // Crisp on HiDPI: the intrinsic pixel width is at least twice the rendered CSS width, so at 2x
    // device-pixel-ratio the image still DOWNSCALES (never upscales, which is what blurred it before).
    expect(naturalWidth, `crispness at ${width}px`).toBeGreaterThanOrEqual(box.width * 2);
  }
});
