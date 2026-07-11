// Add-comment affordances: unified "Add Comment" label + accent-pill styling across
// the text-selection menu and the floating image/diff/mermaid buttons, and the image
// button tracking its image on scroll instead of drifting to a stale fixed position.
import { test, expect } from "@playwright/test";
import { openInline, selectText, ready, fileUrl, INLINE, startStaticServer, routeMermaidLocal, installClipboardCapture, SKILL } from "./helpers.js";

const IMG = "#commentRoot img.cm-img-commentable";

test.describe("add-comment affordances", () => {
  test("every add-comment control reads \"Add Comment\"", async ({ page }) => {
    await openInline(page);
    for (const id of ["menuComment", "imageAddBtn", "diffAddBtn", "mermaidAddBtn"]) {
      const txt = (await page.locator("#" + id).evaluate((el) => el.textContent)).trim();
      expect(txt, id).toBe("Add Comment");
    }
  });

  test("the text menu button shares the accent-pill look of the image button", async ({ page }) => {
    await openInline(page);
    // Reveal the text-selection menu.
    await selectText(page, "#commentRoot p");
    await expect(page.locator("#menuComment")).toBeVisible();
    const menuBg = await page.locator("#menuComment").evaluate((el) => getComputedStyle(el).backgroundColor);
    // Reveal the image button.
    await page.locator(IMG).first().scrollIntoViewIfNeeded();
    await page.locator(IMG).first().hover();
    await expect(page.locator("#imageAddBtn")).toBeVisible();
    const imgBg = await page.locator("#imageAddBtn").evaluate((el) => getComputedStyle(el).backgroundColor);
    // Both use the same accent background, and it is not transparent.
    expect(menuBg).toBe(imgBg);
    expect(menuBg).not.toBe("rgba(0, 0, 0, 0)");
  });

  test("the menu button has a hover effect (background changes)", async ({ page }) => {
    await openInline(page);
    await selectText(page, "#commentRoot p");
    const btn = page.locator("#menuComment");
    await expect(btn).toBeVisible();
    const base = await btn.evaluate((el) => getComputedStyle(el).backgroundColor);
    await btn.hover();
    const hovered = await btn.evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(hovered).not.toBe(base);
  });

  test("the image add button stays pinned to the image on scroll (no drift)", async ({ page }) => {
    await openInline(page);
    const img = page.locator(IMG).first();
    await img.scrollIntoViewIfNeeded();
    await img.hover();
    await expect(page.locator("#imageAddBtn")).toBeVisible();
    const gap = () => page.evaluate((sel) => {
      const b = document.getElementById("imageAddBtn");
      if (b.hidden) return null;
      const br = b.getBoundingClientRect();
      const ir = document.querySelector(sel).getBoundingClientRect();
      return br.top - ir.top; // offset of the button from the image top
    }, IMG);
    const before = await gap();
    expect(before).not.toBeNull();
    // Scroll a small amount while the button is showing.
    await page.evaluate(() => window.scrollBy(0, 40));
    // Wait for the rAF-based reposition to settle instead of a fixed sleep (which loses the
    // race under CI worker contention): the button either hides or stays pinned within tolerance.
    await expect.poll(async () => { const a = await gap(); return a === null || Math.abs(a - before) < 4; },
      { timeout: 3000 }).toBe(true);
  });

  test("the image add button hides when the image scrolls off-screen", async ({ page }) => {
    await openInline(page);
    const img = page.locator(IMG).first();
    await img.scrollIntoViewIfNeeded();
    await img.hover();
    await expect(page.locator("#imageAddBtn")).toBeVisible();
    // Move the image's target out of the viewport. The demo image sits near the end of
    // the document, so scrolling to the top pushes it far below the fold; the button
    // must hide (the other half of the pin behavior), not clamp to a viewport edge.
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(100);
    await expect(page.locator("#imageAddBtn")).toBeHidden();
  });

  test("clicking the reshaped menu button still opens the composer and saves a comment", async ({ page }) => {
    await openInline(page);
    await selectText(page, "#commentRoot p");
    await page.locator("#menuComment").click();
    const composer = page.locator(".cm-composer").last();
    await expect(composer).toBeVisible();
    await composer.locator("textarea").fill("unified add-comment button works");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);
    await expect(page.locator("#commentList .cm-card")).toHaveCount(1);
  });

  test("the add-comment pill is themed (opaque bg, contrasting label) in dark mode", async ({ page }) => {
    await page.goto(fileUrl(INLINE) + "?clawpilotTheme=dark");
    await ready(page);
    await selectText(page, "#commentRoot p");
    const btn = page.locator("#menuComment");
    await expect(btn).toBeVisible();
    const css = await btn.evaluate((el) => {
      const c = getComputedStyle(el);
      return { bg: c.backgroundColor, fg: c.color };
    });
    expect(css.bg).not.toBe("rgba(0, 0, 0, 0)"); // opaque accent, not transparent
    expect(css.fg).not.toBe(css.bg);              // label contrasts the background
  });

  test("the diff add button stays pinned to its line on scroll (no drift)", async ({ page }) => {
    await openInline(page);
    await page.evaluate(() => {
      const el = document.querySelector("#commentRoot .cmh-dl-add");
      el.scrollIntoView({ block: "center" });
      el.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: 50, clientY: 50 }));
    });
    await expect(page.locator("#diffAddBtn")).toBeVisible();
    const gap = () => page.evaluate(() => {
      const b = document.getElementById("diffAddBtn");
      if (b.hidden) return null;
      const br = b.getBoundingClientRect();
      const lr = document.querySelector("#commentRoot .cmh-dl-add").getBoundingClientRect();
      return br.top - lr.top;
    });
    const before = await gap();
    expect(before).not.toBeNull();
    await page.evaluate(() => window.scrollBy(0, 40));
    // Distinct code path from the image button (positionDiffAdd); it must pin the
    // same way - either it hid (target moved out) or it tracked the line exactly.
    // Poll for the rAF reposition to settle (deterministic; not flaky under contention).
    await expect.poll(async () => { const a = await gap(); return a === null || Math.abs(a - before) < 4; },
      { timeout: 10000 }).toBe(true);
  });

  test("the mermaid add button stays pinned to its node on scroll (no drift)", async ({ page }) => {
    // Served over http with mermaid routed to the local vendored copy (network-isolated), and
    // ?mermaid=1 opts the demo into rendering.
    const server = await startStaticServer(SKILL);
    try {
      await routeMermaidLocal(page);
      await installClipboardCapture(page);
      await page.goto(server.url + "/dist/PORTABLE.html?mermaid=1");
      await ready(page);
      const node = page.locator("#commentRoot .mermaid svg g.node").first();
      await expect(node).toBeVisible({ timeout: 20000 });
      await node.hover();
      await expect(page.locator("#mermaidAddBtn")).toBeVisible();
      const gap = () => page.evaluate(() => {
        const b = document.getElementById("mermaidAddBtn");
        if (b.hidden) return null;
        const br = b.getBoundingClientRect();
        const nr = document.querySelector("#commentRoot .mermaid svg g.node").getBoundingClientRect();
        return br.top - nr.top;
      });
      const before = await gap();
      expect(before).not.toBeNull();
      await page.evaluate(() => window.scrollBy(0, 40));
      // Distinct code path (positionMermaidAdd); same pin invariant as image/diff.
      // Poll for the rAF reposition to settle (deterministic; not flaky under contention).
      await expect.poll(async () => { const a = await gap(); return a === null || Math.abs(a - before) < 4; },
        { timeout: 10000 }).toBe(true);
    } finally {
      await server.close();
    }
  });
});
