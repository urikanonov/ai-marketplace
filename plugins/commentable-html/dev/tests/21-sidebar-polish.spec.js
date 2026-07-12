import { test, expect } from "@playwright/test";
import { openKitchenSink, addTextComment, lastCopied, ready, storedComments } from "./helpers.js";

async function openSidebarPanel(page) {
  if (!(await page.evaluate(() => document.body.classList.contains("sidebar-open")))) {
    await page.click("#btnToggleSidebar");
  }
  await expect(page.locator("body")).toHaveClass(/sidebar-open/);
}


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
    const olderCreatedAt = (await storedComments(page))[0].createdAt;
    await page.waitForFunction((createdAt) => Date.now() > Date.parse(createdAt), olderCreatedAt);
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


  test("the sidebar resize handle persists width and reserves matching page space", async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 800 });
    await openKitchenSink(page);
    await openSidebarPanel(page);
    const handle = page.locator("#sidebarResizeHandle");
    await expect(handle).toHaveClass(/cm-skip/);
    await expect(handle).toHaveAttribute("role", "separator");
    await expect(handle).toHaveAttribute("tabindex", "0");

    const box = await handle.boundingBox();
    expect(box).toBeTruthy();
    const targetWidth = 520;
    await page.evaluate((width) => {
      const h = document.getElementById("sidebarResizeHandle");
      const y = h.getBoundingClientRect().top + 40;
      const pointerId = 7;
      h.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, pointerId, clientX: window.innerWidth - 400, clientY: y }));
      document.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId, clientX: window.innerWidth - width, clientY: y }));
      document.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId, clientX: window.innerWidth - width, clientY: y }));
    }, targetWidth);

    const metrics = await page.evaluate(() => {
      const sidebar = document.getElementById("sidebar");
      const app = document.querySelector(".app");
      return {
        sidebarWidth: sidebar.getBoundingClientRect().width,
        appPaddingRight: parseFloat(getComputedStyle(app).paddingRight),
        stored: localStorage.getItem("commentable-html::sidebarWidth"),
        ariaNow: document.getElementById("sidebarResizeHandle").getAttribute("aria-valuenow"),
      };
    });
    expect(Math.abs(metrics.sidebarWidth - targetWidth)).toBeLessThanOrEqual(4);
    expect(metrics.appPaddingRight).toBeGreaterThan(targetWidth);
    expect(Number(metrics.stored)).toBeCloseTo(metrics.sidebarWidth, 0);
    expect(Number(metrics.ariaNow)).toBeCloseTo(metrics.sidebarWidth, 0);

    await page.reload();
    await ready(page);
    await openSidebarPanel(page);
    const restored = await page.evaluate(() => document.getElementById("sidebar").getBoundingClientRect().width);
    expect(restored).toBeCloseTo(metrics.sidebarWidth, 0);
  });

  test("the sidebar header wraps without overflowing when resized narrow", async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 800 });
    await openKitchenSink(page);
    await openSidebarPanel(page);
    await page.locator("#sidebarResizeHandle").focus();
    await page.keyboard.press("Home");

    const metrics = await page.evaluate(() => {
      const sidebar = document.getElementById("sidebar");
      const header = sidebar.querySelector("header").getBoundingClientRect();
      const buttons = Array.from(sidebar.querySelectorAll("header button")).filter((b) => b.offsetParent !== null);
      const overflowing = buttons.filter((b) => {
        const r = b.getBoundingClientRect();
        return r.left < header.left - 1 || r.right > header.right + 1;
      }).length;
      const actionRows = new Set(Array.from(sidebar.querySelectorAll(".head-actions button")).map((b) => Math.round(b.getBoundingClientRect().top))).size;
      return { width: sidebar.getBoundingClientRect().width, narrow: sidebar.classList.contains("is-narrow"), overflowing, actionRows };
    });
    expect(metrics.width).toBeLessThanOrEqual(340);
    expect(metrics.narrow).toBe(true);
    expect(metrics.overflowing).toBe(0);
    expect(metrics.actionRows).toBeGreaterThan(1);
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
