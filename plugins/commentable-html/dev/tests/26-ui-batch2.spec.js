import { test, expect } from "@playwright/test";
import { openInline, ready, SKILL, startStaticServer, routeMermaidLocal } from "./helpers.js";

test.describe("UI batch 2: headings, whole-diagram, scroll bubble, code box, icon", () => {
  test("a heading shows an Add Comment affordance and can be commented", async ({ page }) => {
    await openInline(page);
    const h = page.locator("#commentRoot h2.cm-anchored").first();
    await h.hover();
    const btn = page.locator("#headingAddBtn");
    await expect(btn).toBeVisible();
    await btn.click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("comment on this section");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);
    // The comment anchors to the heading text (a normal text highlight inside the heading).
    await expect(page.locator("#commentRoot h2 mark.cm-hl").first()).toBeVisible();
    await expect(page.locator(".cm-card")).toHaveCount(1);
  });

  test("a heading still deep-links on a plain click", async ({ page }) => {
    await openInline(page);
    const h = page.locator("#commentRoot h2[id].cm-anchored").first();
    const id = await h.getAttribute("id");
    await h.click({ position: { x: 5, y: 5 } });
    await expect(page).toHaveURL(new RegExp("#" + id + "$"));
  });

  test("the scroll-progress bubble reflects scroll position", async ({ page }) => {
    await openInline(page);
    const bubble = page.locator("#cmScrollProgress");
    await expect(bubble).toBeVisible();
    await expect(bubble).toHaveText("0%");
    // Intermediate: scrolling to the middle shows a mid-range percent (not just 0/100).
    await page.evaluate(() => {
      const doc = document.documentElement;
      window.scrollTo(0, (doc.scrollHeight - window.innerHeight) / 2);
    });
    await expect(bubble).toHaveText(/^(4[0-9]|5[0-9]|60)%$/);
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await expect(bubble).toHaveText("100%");
  });

  test("standalone code blocks are boxed", async ({ page }) => {
    await openInline(page);
    const pre = page.locator("#commentRoot pre:has(code.language-python)").first();
    const border = await pre.evaluate((el) => getComputedStyle(el).borderTopWidth);
    expect(parseFloat(border)).toBeGreaterThan(0);
    // The mermaid host is not boxed.
    const mmBorder = await page.locator("#commentRoot pre.mermaid").first().evaluate((el) => getComputedStyle(el).borderTopWidth);
    expect(parseFloat(mmBorder)).toBe(0);
  });

  test("the brand icon carries a versioned styled tooltip", async ({ page }) => {
    await openInline(page);
    await page.click("#btnToggleSidebar"); // open the panel; the meta icon is at the top (no scroll)
    const icon = page.locator(".cm-sidebar .head-meta .cm-brand-icon");
    await expect(icon).toHaveAttribute("aria-label", /^Commentable HTML v\d+\.\d+\.\d+$/);
    await icon.hover();
    const tip = page.locator(".cm-tooltip.is-visible");
    await expect(tip).toBeVisible({ timeout: 2000 });
    expect((await tip.textContent()).trim()).toMatch(/^Commentable HTML v\d+\.\d+\.\d+$/);
  });

  test("the Hide button sits next to Help in the sidebar header", async ({ page }) => {
    await openInline(page);
    const meta = page.locator(".cm-sidebar .head-meta");
    await expect(meta.locator("#btnHelp")).toHaveCount(1);
    await expect(meta.locator("#btnCloseSidebar")).toHaveCount(1);
  });
  test("whole-diagram comment: hover empty area, create, and it survives reload (http)", async ({ page }) => {
    test.setTimeout(60000);
    const server = await startStaticServer(SKILL);
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/dist/PORTABLE.html");
      await ready(page);
      const host = page.locator("#commentRoot pre.mermaid").nth(1); // the gantt
      await expect(host.locator("svg .taskText, svg .taskTextOutsideRight, svg .taskTextOutsideLeft").first()).toBeVisible({ timeout: 20000 });
      // The gantt title is empty of task nodes, so hovering it offers the whole-diagram comment.
      await host.locator("svg .titleText").first().hover();
      // Deterministic wait (no fixed timeout): the button shows the whole-diagram label.
      await page.waitForFunction(() => {
        const b = document.getElementById("mermaidAddBtn");
        return b && !b.hidden && /diagram/i.test(b.textContent || "");
      }, null, { timeout: 5000 });
      await page.locator("#mermaidAddBtn").click();
      const composer = page.locator(".cm-composer").last();
      await composer.locator("textarea").fill("whole gantt note");
      await composer.locator('[data-act="save"]').click();
      await expect(composer).toHaveCount(0);
      // The whole-diagram anchor rings the host and the card labels it "mermaid diagram:".
      await expect(host).toHaveClass(/cm-mermaid-hl/);
      await expect(page.locator(".cm-card .quote")).toContainText(/mermaid diagram/i);
      // Survives reload: the __diagram__ anchor rehydrates onto the host.
      await page.reload();
      await ready(page);
      const host2 = page.locator("#commentRoot pre.mermaid").nth(1);
      await expect(host2.locator("svg .taskText, svg .taskTextOutsideRight, svg .taskTextOutsideLeft").first()).toBeVisible({ timeout: 20000 });
      await expect(host2).toHaveClass(/cm-mermaid-hl/, { timeout: 10000 });
      await expect(page.locator(".cm-card")).toHaveCount(1);
    } finally {
      await server.close();
    }
  });
});
