import { test, expect } from "@playwright/test";
import { openKitchenSink, addTextComment, lastCopied } from "./helpers.js";

test.describe("sidebar polish: 24h time, hidden prose pin, sort, info rows", () => {
  test("comment timestamps are 24-hour (no AM/PM) on the card", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "time check");
    const meta = await page.locator(".cm-card .meta").first().innerText();
    expect(meta).not.toMatch(/\bAM\b|\bPM\b/i);
  });

  test("comment timestamps use an unambiguous month name (not a numeric M/D)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "date check");
    const meta = await page.locator(".cm-card .meta").first().innerText();
    // A 3-letter month like Jan..Dec must be present, and there must be no NN/NN date.
    expect(meta).toMatch(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/);
    expect(meta).not.toMatch(/\b\d{1,2}\/\d{1,2}\/\d{2,4}\b/);
  });

  test("a prose comment card hides the internal pinpoint but Copy all keeps it", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "no pin please");
    // The sidebar card must not show the internal "in <tag> - match N of M" pin.
    await expect(page.locator(".cm-card .pin")).toHaveCount(0);
    const cardText = await page.locator(".cm-card").first().innerText();
    expect(cardText).not.toMatch(/match \d+ of \d+/);
    // ...but the agent-facing Copy bundle still carries the Pinpoint line.
    await page.click("#btnCopyAll");
    const bundle = await lastCopied(page);
    expect(bundle).toMatch(/Pinpoint:/);
  });

  test("sort arrows order comments oldest/newest first and toggle aria-pressed", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "older one", 0);
    await page.waitForTimeout(80); // ensure a distinct createdAt millisecond
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "newer one", 0);

    const firstCardText = () => page.locator(".cm-card").first().innerText();

    await page.click("#btnSortAsc");
    await expect(page.locator("#btnSortAsc")).toHaveAttribute("aria-pressed", "true");
    expect(await firstCardText()).toContain("older one");

    await page.click("#btnSortDesc");
    await expect(page.locator("#btnSortDesc")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("#btnSortAsc")).toHaveAttribute("aria-pressed", "false");
    expect(await firstCardText()).toContain("newer one");

    // Clicking the active arrow again returns to document (position) order.
    await page.click("#btnSortDesc");
    await expect(page.locator("#btnSortDesc")).toHaveAttribute("aria-pressed", "false");
  });

  test("the sort choice persists across reload", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "persist sort");
    await page.click("#btnSortDesc");
    await page.reload();
    await expect(page.locator("#btnSortDesc")).toHaveAttribute("aria-pressed", "true");
  });

  test("the sidebar shows Generated-on and Last-comment info rows", async ({ page }) => {
    await openKitchenSink(page);
    await expect(page.locator("#cmGenerated")).toContainText("Generated on:");
    await expect(page.locator("#cmLastComment")).toContainText("Last comment: none yet");
    await addTextComment(page, "#commentRoot section p", "sets last comment");
    await expect(page.locator("#cmLastComment")).toContainText("Last comment:");
    await expect(page.locator("#cmLastComment")).not.toContainText("none yet");
  });

  test("clicking a section heading deep-links it in the URL", async ({ page }) => {
    await openKitchenSink(page);
    const h = page.locator("#commentRoot h2").first();
    await expect(h).toHaveClass(/cm-anchored/);
    const id = await h.getAttribute("id");
    expect(id).toBeTruthy();
    await h.click();
    expect(await page.evaluate(() => location.hash)).toBe("#" + id);
  });

  test("long content <pre> wraps instead of overflowing", async ({ page }) => {
    await openKitchenSink(page);
    const pre = page.locator("#commentRoot pre:not(.mermaid):not(.cmh-diff):not(.cmh-diff-raw)").first();
    if (await pre.count()) {
      const ws = await pre.evaluate(el => getComputedStyle(el).whiteSpace);
      expect(ws).toBe("pre-wrap");
    }
  });
});
