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

  test("the Copy all button is a prominent primary action, larger and bolder than the small controls (CMH-SIDE-07)", async ({ page }) => {
    await openKitchenSink(page);
    await openSidebarPanel(page);
    const copy = page.locator("#btnCopyAll");
    await expect(copy).toBeVisible();
    const font = await copy.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    const weight = await copy.evaluate((el) => Number(getComputedStyle(el).fontWeight));
    // Bigger, bolder text so the most-used action is easy to find and click (was ~0.78rem, normal weight).
    expect(font).toBeGreaterThanOrEqual(14);
    expect(weight).toBeGreaterThanOrEqual(700);
    // A larger click target than the small sort arrows beside it.
    const copyBox = await copy.boundingBox();
    const sortBox = await page.locator("#btnSortAsc").boundingBox();
    expect(copyBox.height).toBeGreaterThan(sortBox.height);
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

  test("the sidebar minimum width keeps every action button label legible (CMH-SIDE-06)", async ({ page }) => {
    // The resize floor is 256px - the empirically measured minimum at which the two-per-row export
    // button labels ("Portable", "Offline", "Markdown", "Plain HTML") and Copy all stay fully shown
    // (below ~240px they clip). The same floor applies on wide and narrow viewports.
    for (const vw of [1400, 640]) {
      await page.setViewportSize({ width: vw, height: 800 });
      await openKitchenSink(page);
      await openSidebarPanel(page);
      const handle = page.locator("#sidebarResizeHandle");
      await handle.focus();
      await page.keyboard.press("Home");
      const m = await page.evaluate(() => {
        const sidebar = document.getElementById("sidebar");
        const clip = (el) => Math.max(0, el.scrollWidth - el.clientWidth);
        const spanClips = Array.from(sidebar.querySelectorAll(".head-actions button > span")).map(clip);
        return {
          width: sidebar.getBoundingClientRect().width,
          min: Number(document.getElementById("sidebarResizeHandle").getAttribute("aria-valuemin")),
          maxSpanClip: Math.max(0, ...spanClips),
          copyClip: clip(document.getElementById("btnCopyAll")),
          narrow: sidebar.classList.contains("is-narrow"),
        };
      });
      expect(m.min).toBe(256);
      expect(Math.abs(m.width - 256)).toBeLessThanOrEqual(2);
      // No action-button label (nor Copy all) clips at the enforced minimum width.
      expect(m.maxSpanClip).toBeLessThanOrEqual(0.5);
      expect(m.copyClip).toBeLessThanOrEqual(0.5);
      // At the minimum the panel is in the compact two-per-row layout.
      expect(m.narrow).toBe(true);
    }
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

  test("the sidebar export buttons are two-per-row in narrow layout (CMH-SIDE-08)", async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 800 });
    await openKitchenSink(page);
    await openSidebarPanel(page);
    await page.locator("#sidebarResizeHandle").focus();
    await page.keyboard.press("Home");

    const layout = await page.evaluate(() => {
      const sidebar = document.getElementById("sidebar");
      const actions = sidebar.querySelector(".head-actions");
      const rect = (id) => document.getElementById(id).getBoundingClientRect();
      const r = {
        portable: rect("btnSaveHtml"),
        offline: rect("btnExportOffline"),
        markdown: rect("btnExportMd"),
        plain: rect("btnSavePlain"),
        clear: rect("btnClearAll"),
      };
      const round = (f) => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, Math.round(f(v))]));
      return {
        narrow: sidebar.classList.contains("is-narrow"),
        containerWidth: actions.getBoundingClientRect().width,
        top: round((v) => v.top),
        left: round((v) => v.left),
        width: Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v.width])),
      };
    });

    expect(layout.narrow).toBe(true);
    // Row 1: Portable and Offline share a row, Portable on the left.
    expect(layout.top.portable).toBe(layout.top.offline);
    expect(layout.left.portable).toBeLessThan(layout.left.offline);
    // Row 2: Markdown and Plain HTML share the next row down, Markdown on the left.
    expect(layout.top.markdown).toBe(layout.top.plain);
    expect(layout.left.markdown).toBeLessThan(layout.left.plain);
    expect(layout.top.markdown).toBeGreaterThan(layout.top.portable);
    // Clear sits on its own row below, spanning the full width (a destructive action kept apart).
    expect(layout.top.clear).toBeGreaterThan(layout.top.markdown);
    expect(layout.width.clear).toBeGreaterThan(layout.containerWidth * 0.9);
    // Each export button is about half a row, so two fit side by side.
    for (const key of ["portable", "offline", "markdown", "plain"]) {
      expect(layout.width[key]).toBeLessThan(layout.containerWidth * 0.75);
    }
    expect(layout.width.portable + layout.width.offline).toBeLessThanOrEqual(layout.containerWidth + 2);
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
