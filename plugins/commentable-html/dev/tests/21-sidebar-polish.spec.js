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
    // Copy all is more prominent than the compact Sort ribbon button beside it: a larger label.
    const sortCapFont = await page.locator("#btnSort .cm-ribbon-cap").evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(font).toBeGreaterThan(sortCapFont);
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

  test("the Sort button cycles document -> newest -> oldest -> document and the tooltip tracks state (CMH-SIDE-02)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "older one", 0);
    const olderCreatedAt = (await storedComments(page))[0].createdAt;
    await page.waitForFunction((createdAt) => Date.now() > Date.parse(createdAt), olderCreatedAt);
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "newer one", 0);

    const firstCardText = () => page.locator(".cm-card").first().innerText();
    const sort = page.locator("#btnSort");
    // The shared tooltip layer may hold the tip in `title` (until adopted) or in `data-cmh-tip`.
    const tip = () => sort.evaluate((el) => el.getAttribute("data-cmh-tip") || el.getAttribute("title") || "");

    // Default: document position order; the accessible name + tooltip name the current state.
    await expect(sort).toHaveAttribute("data-sort", "pos");
    await expect(sort).toHaveAttribute("aria-label", /document order/i);
    expect(await tip()).toMatch(/document position\. Click to sort newest first/i);

    // 1st click -> newest first.
    await sort.click();
    await expect(sort).toHaveAttribute("data-sort", "time-desc");
    await expect(sort).toHaveAttribute("aria-label", /newest first/i);
    expect(await tip()).toMatch(/newest first\. Click to sort oldest first/i);
    expect(await firstCardText()).toContain("newer one");

    // 2nd click -> oldest first.
    await sort.click();
    await expect(sort).toHaveAttribute("data-sort", "time-asc");
    await expect(sort).toHaveAttribute("aria-label", /oldest first/i);
    expect(await tip()).toMatch(/oldest first\. Click to return to document order/i);
    expect(await firstCardText()).toContain("older one");

    // 3rd click -> back to document order. It never uses aria-pressed (it is a cycle, not a toggle).
    await sort.click();
    await expect(sort).toHaveAttribute("data-sort", "pos");
    await expect(sort).toHaveAttribute("aria-label", /document order/i);
    expect(await sort.getAttribute("aria-pressed")).toBeNull();
  });

  test("the sort choice persists across reload (CMH-SIDE-02)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "persist sort");
    await page.click("#btnSort"); // -> newest first (time-desc)
    await page.reload();
    await expect(page.locator("#btnSort")).toHaveAttribute("data-sort", "time-desc");
    await expect(page.locator("#btnSort")).toHaveAttribute("aria-label", /newest first/i);
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
    // The resize floor is 256px - the empirically measured minimum at which the captioned action
    // ribbon (Export, Sort, More, Help, Hide), the Copy all / Search primary row, and the search
    // placeholder stay fully shown. The same floor applies on wide and narrow viewports. Below the
    // 640px phone breakpoint the sidebar is instead a non-resizable full-width sheet (CMH-RESP-04),
    // so the narrow-viewport case uses 700px, where the panel is still a resizable side panel.
    for (const vw of [1400, 700]) {
      await page.setViewportSize({ width: vw, height: 800 });
      await openKitchenSink(page);
      await openSidebarPanel(page);
      const handle = page.locator("#sidebarResizeHandle");
      await handle.focus();
      await page.keyboard.press("Home");
      const m = await page.evaluate(() => {
        const sidebar = document.getElementById("sidebar");
        const clip = (el) => Math.max(0, el.scrollWidth - el.clientWidth);
        // Every captioned ribbon action plus the two primary-row button labels must stay legible.
        const labels = Array.from(sidebar.querySelectorAll(
          ".head-ribbon .cm-ribbon-cap, .head-primary button > span"));
        const spanClips = labels.map(clip);
        return {
          width: sidebar.getBoundingClientRect().width,
          min: Number(document.getElementById("sidebarResizeHandle").getAttribute("aria-valuemin")),
          labelCount: labels.length,
          maxSpanClip: Math.max(0, ...spanClips),
          copyClip: clip(document.getElementById("btnCopyAll")),
          narrow: sidebar.classList.contains("is-narrow"),
        };
      });
      expect(m.min).toBe(256);
      expect(Math.abs(m.width - 256)).toBeLessThanOrEqual(2);
      // The retargeted query must actually match the new labels (guards against a vacuous pass):
      // 5 ribbon captions (Export, Sort, More, Help, Hide) + 2 primary labels (Copy all, Search).
      expect(m.labelCount).toBe(7);
      // No ribbon caption nor primary label (nor Copy all) clips at the enforced minimum width.
      expect(m.maxSpanClip).toBeLessThanOrEqual(0.5);
      expect(m.copyClip).toBeLessThanOrEqual(0.5);
      // At the minimum the panel is in the compact layout.
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
      const ribbon = sidebar.querySelector(".head-ribbon").getBoundingClientRect();
      const primary = sidebar.querySelector(".head-primary").getBoundingClientRect();
      const headerRows = new Set([Math.round(ribbon.top), Math.round(primary.top)]).size;
      return { width: sidebar.getBoundingClientRect().width, narrow: sidebar.classList.contains("is-narrow"), overflowing, headerRows };
    });
    expect(metrics.width).toBeLessThanOrEqual(340);
    expect(metrics.narrow).toBe(true);
    expect(metrics.overflowing).toBe(0);
    expect(metrics.headerRows).toBeGreaterThan(1);
  });

  test("the sidebar action ribbon stays on one row at narrow width (CMH-SIDE-08)", async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 800 });
    await openKitchenSink(page);
    await openSidebarPanel(page);
    await page.locator("#sidebarResizeHandle").focus();
    await page.keyboard.press("Home");

    const layout = await page.evaluate(() => {
      const sidebar = document.getElementById("sidebar");
      const ribbon = sidebar.querySelector(".head-ribbon");
      const cells = Array.from(ribbon.children);
      const rb = ribbon.getBoundingClientRect();
      const tops = cells.map((c) => Math.round(c.getBoundingClientRect().top));
      const overflow = cells.some((c) => {
        const r = c.getBoundingClientRect();
        return r.left < rb.left - 1 || r.right > rb.right + 1;
      });
      return {
        narrow: sidebar.classList.contains("is-narrow"),
        cells: cells.length,
        rows: new Set(tops).size,
        overflow,
      };
    });

    expect(layout.narrow).toBe(true);
    expect(layout.cells).toBe(5); // Export, Sort, More, Help, Hide
    expect(layout.rows).toBe(1);
    expect(layout.overflow).toBe(false);
  });

  test("the sidebar shows Generated-on and Last-comment info rows", async ({ page }) => {
    await openKitchenSink(page);
    await expect(page.locator("#cmGenerated")).toContainText("Generated on:");
    await expect(page.locator("#cmLastComment")).toContainText("Last comment: none yet");
    await addTextComment(page, "#commentRoot section p", "sets last comment");
    await expect(page.locator("#cmLastComment")).toContainText("Last comment:");
    await expect(page.locator("#cmLastComment")).not.toContainText("none yet");
  });

  test("the three metadata lines are evenly spaced (CMH-SIDE-03)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "spacing note");
    await openSidebarPanel(page);
    const gaps = await page.evaluate(() => {
      const textRect = (el) => { const r = document.createRange(); r.selectNodeContents(el); return r.getBoundingClientRect(); };
      const gen = textRect(document.getElementById("cmGenerated"));
      const last = textRect(document.getElementById("cmLastComment"));
      const ident = textRect(document.querySelector(".cm-sidebar .cm-identity .cm-identity-label"));
      return { a: last.top - gen.bottom, b: ident.top - last.bottom };
    });
    // The visible whitespace gap Generated -> Last comment and Last comment -> Commenting-as match
    // (both are the header's flex gap); the old layout differed by ~8px.
    expect(Math.abs(gaps.a - gaps.b)).toBeLessThanOrEqual(3);
  });

  test("the identity edit input stays legible and is not shrunk to the tiny metadata size (CMH-SIDE-03)", async ({ page }) => {
    await openKitchenSink(page);
    await openSidebarPanel(page);
    // The display line matches the tiny metadata rows, but the edit-mode input keeps a larger,
    // legible size (it must not inherit the tiny display font).
    const tinyFont = await page.evaluate(() =>
      parseFloat(getComputedStyle(document.getElementById("cmGenerated")).fontSize));
    if (await page.locator("#cmIdentityEdit").isHidden()) await page.click("#btnEditIdentity");
    const inputFont = await page.evaluate(() =>
      parseFloat(getComputedStyle(document.getElementById("cmIdentityInput")).fontSize));
    expect(inputFont).toBeGreaterThan(tinyFont);
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
