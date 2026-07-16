const { test, expect, contrastRatio, compositedContrast, PROD } = require("./site-support");

test("a plugin card is clickable across its body, navigating to the plugin page (SITE-HUB-06)", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const card = page.locator(".plugin-card", { hasText: "commentable-html" }).first();
  const desc = card.locator(".desc");
  await desc.scrollIntoViewIfNeeded();
  const box = await desc.boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page).toHaveURL(/\/commentable-html\/$/);
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

test("the plugin page footer links to contribute, feature request, issues, source, and the author's LinkedIn", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const footer = page.locator("footer.footer");
  await expect(footer.locator("a", { hasText: "Contribute" })).toHaveAttribute("href", /\/CONTRIBUTING\.md$/);
  await expect(footer.locator("a", { hasText: "Request a feature" })).toHaveAttribute("href", /feature-request\.yml$/);
  await expect(footer.locator("a", { hasText: "File an issue" })).toHaveAttribute("href", /\/issues\/new\/choose$/);
  await expect(footer.locator("a", { hasText: "Plugin source" })).toHaveAttribute("href", /\/plugins\/commentable-html$/);
  await expect(footer.locator("a", { hasText: "Uri Kanonov" })).toHaveAttribute("href", /linkedin\.com\/in\/uri-kanonov/);
});
