const { test, expect, contrastRatio, compositedContrast, PROD } = require("./site-support");

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
  // "reload and repeat" loop-back, so on mobile step 4 reads like the other numbered actions
  // instead of a plain italic caption. The old italic caption class is gone.
  await expect(vertical.locator(".loop-fig-badge")).toHaveCount(4);
  await expect(vertical.locator(".loop-fig-repeat")).toHaveCount(0);
  await expect(vertical).toContainText("Generates HTML");
  await expect(vertical).toContainText("Copy all back");
  await expect(vertical).toContainText("Comment inline");
  await expect(vertical).toContainText("reload and repeat");
});

test("the comparison table's Markdown-file verdict reads 'OK / need viewer' (SITE-WHY-08)", async ({ page }) => {
  await page.goto("/commentable-html/", { waitUntil: "domcontentloaded" });
  const markdownRow = page.locator("table.compare tbody tr", { hasText: "Markdown file" });
  const bigPlan = markdownRow.locator('td[data-label="Handles a big plan"] .cmp-v');
  await expect(bigPlan).toHaveText("OK / need viewer");
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
