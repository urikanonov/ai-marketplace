import { test, expect } from "@playwright/test";
import { openInline, ready, openToolbarMenu, fileUrl, INLINE, openKitchenSinkNonPortable } from "./helpers.js";

// UI batch 5: searchable/collapsible Help, custom tooltips, compact sidebar header,
// bigger section caret, and icons on the TOC / scroll buttons.

test.describe("Help is grouped, collapsible, and searchable", () => {
  async function openHelp(page) {
    await openInline(page);
    await openToolbarMenu(page);
    await page.click("#btnHelpTop");
    await expect(page.locator(".cm-help")).toBeVisible();
  }

  test("Help has many collapsible topics, a search box that gets focus, and one open by default", async ({ page }) => {
    await openHelp(page);
    const topics = page.locator(".cm-help-topic");
    expect(await topics.count()).toBeGreaterThanOrEqual(10);
    // search input is focused on open
    await expect(page.locator(".cm-help-search-input")).toBeFocused();
    // exactly the first topic is open initially
    expect(await page.locator(".cm-help-topic[open]").count()).toBe(1);
    await expect(page.locator(".cm-help-topic").first()).toHaveAttribute("open", "");
  });

  test("typing in the search box filters topics; a no-match query shows the empty state", async ({ page }) => {
    await openHelp(page);
    const search = page.locator(".cm-help-search-input");
    await search.fill("diff");
    // every visible topic mentions the query; at least one is visible and open
    const visible = page.locator(".cm-help-topic:visible");
    expect(await visible.count()).toBeGreaterThan(0);
    for (const t of await visible.all()) expect((await t.innerText()).toLowerCase()).toContain("diff");
    await expect(page.locator(".cm-help-noresults")).toBeHidden();

    await search.fill("zzzq-nothing-matches");
    expect(await page.locator(".cm-help-topic:visible").count()).toBe(0);
    await expect(page.locator(".cm-help-noresults")).toBeVisible();

    // clearing restores the default (first topic open, all visible)
    await search.fill("");
    expect(await page.locator(".cm-help-topic:visible").count()).toBeGreaterThanOrEqual(10);
    expect(await page.locator(".cm-help-topic[open]").count()).toBe(1);
  });

  test("a collapsed topic expands when its summary is clicked", async ({ page }) => {
    await openHelp(page);
    const second = page.locator(".cm-help-topic").nth(1);
    await expect(second).not.toHaveAttribute("open", "");
    await second.locator("summary").click();
    await expect(second).toHaveAttribute("open", "");
  });

  test("the About block is static (not collapsible) and stays visible while searching", async ({ page }) => {
    await openHelp(page);
    const about = page.locator(".cm-help-about");
    await expect(about).toBeVisible();
    await expect(about).toContainText("Commentable HTML");
    expect(await about.locator("summary").count()).toBe(0); // not a <details> topic
    await page.locator(".cm-help-search-input").fill("diff");
    await expect(about).toBeVisible(); // always shown, never collapsed or filtered out
  });
});

test.describe("custom tooltips (no jQuery/CDN)", () => {
  test("hovering a chrome control shows a styled tooltip and converts title to data-cmh-tip", async ({ page }) => {
    await openInline(page);
    const btn = page.locator("#btnToolbarMenu");
    const titleBefore = await btn.getAttribute("title");
    expect(titleBefore && titleBefore.length).toBeGreaterThan(4);
    await btn.hover();
    const tip = page.locator(".cm-tooltip.is-visible");
    await expect(tip).toBeVisible({ timeout: 2000 });
    expect((await tip.textContent()).trim()).toBe(titleBefore.trim());
    // native title is moved to data-cmh-tip so the browser's own tooltip never doubles up
    expect(await btn.getAttribute("title")).toBeNull();
    expect(await btn.getAttribute("data-cmh-tip")).toBe(titleBefore);
    // moving away hides it
    await page.mouse.move(2, 2);
    await expect(tip).toBeHidden();
  });

  test("keyboard focus shows the tooltip immediately", async ({ page }) => {
    await openInline(page);
    await page.locator("#btnToolbarMenu").focus();
    await expect(page.locator(".cm-tooltip.is-visible")).toBeVisible({ timeout: 1500 });
  });
});

test.describe("compact sidebar header", () => {
  test("the two timestamps share one row and the action buttons wrap into aligned rows", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await openInline(page);
    await page.evaluate(() => document.body.classList.add("sidebar-open"));
    const rects = await page.evaluate(() => {
      const r = (id) => { const e = document.getElementById(id); const b = e.getBoundingClientRect(); return { top: Math.round(b.top), h: b.height }; };
      return { gen: r("cmGenerated"), last: r("cmLastComment"), save: r("btnSaveHtml"), plain: r("btnSavePlain"), md: r("btnExportMd"), clear: r("btnClearAll") };
    });
    // timestamps on one line
    expect(Math.abs(rects.gen.top - rects.last.top)).toBeLessThan(6);
    // the four action buttons stay a compact, aligned grid (one or two rows, never a
    // ragged stack): at most two distinct row tops.
    const tops = [...new Set([rects.save.top, rects.plain.top, rects.md.top, rects.clear.top])];
    expect(tops.length).toBeLessThanOrEqual(2);
    // accessible names stay full even though the visible labels are compact
    await expect(page.locator("#btnSaveHtml")).toHaveAttribute("aria-label", "Export as Portable");
    await expect(page.locator("#btnExportMd")).toHaveAttribute("aria-label", "Export to Markdown");
    await expect(page.locator("#btnClearAll")).toHaveAttribute("aria-label", "Clear Comments");
  });

  test("the runtime footer does not leave a large empty gap above it", async ({ page }) => {
    await openInline(page);
    const info = await page.evaluate(() => {
      const app = document.querySelector(".app");
      return {
        hasFooterClass: document.body.classList.contains("cm-has-footer"),
        padBottom: parseFloat(getComputedStyle(app).paddingBottom),
      };
    });
    expect(info.hasFooterClass).toBe(true); // the footer marks the body so the layout tightens
    expect(info.padBottom).toBeLessThan(40); // 1.25rem (~20px), reduced from the recipe's 4rem
  });
});

test.describe("bigger caret and TOC/scroll icons", () => {
  test("the section collapse caret has a comfortably large click target", async ({ page }) => {
    await openInline(page);
    const box = await page.locator(".cmh-sec-caret").first().boundingBox();
    expect(box.width).toBeGreaterThanOrEqual(20);
    expect(box.height).toBeGreaterThanOrEqual(20);
  });

  test("Expand All, Collapse All, Scroll to Top and Scroll to Bottom each carry an icon", async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 900 });
    await openInline(page);
    const toc = page.locator("#cmSideToc");
    await expect(toc).toBeVisible();
    for (const label of ["Expand All", "Collapse All", "Scroll to Top", "Scroll to Bottom"]) {
      const btn = toc.locator(".cm-side-toc-top", { hasText: label });
      await expect(btn).toBeVisible();
      expect(await btn.locator("svg.cm-ui-ico").count(), label).toBe(1);
    }
  });
});

// Regressions from the batch-5 multi-duck panel.
test.describe("multi-duck panel fixes (batch 5)", () => {
  test("a control whose title changes at runtime shows the fresh tooltip and drops the native title", async ({ page }) => {
    await openInline(page);
    const caret = page.locator(".cmh-sec-caret").first();
    await caret.focus();
    const tip = page.locator(".cm-tooltip.is-visible");
    await expect(tip).toBeVisible({ timeout: 1500 });
    const first = (await tip.textContent()).trim();
    expect(first.length).toBeGreaterThan(0);
    // toggle the section (this reassigns caret.title), then blur + re-focus
    await caret.evaluate((c) => c.click());
    await page.evaluate(() => document.activeElement && document.activeElement.blur());
    await caret.focus();
    await expect(tip).toBeVisible({ timeout: 1500 });
    const second = (await tip.textContent()).trim();
    expect(second).not.toBe(first); // fresh title won over the cached one
    // native title was moved out so the browser tooltip cannot double up
    expect(await caret.getAttribute("title")).toBeNull();
    expect(await caret.getAttribute("data-cmh-tip")).toBe(second);
  });

  test("the tooltip is hidden when its control is removed while visible", async ({ page }) => {
    await openInline(page);
    await page.locator("#btnToolbarMenu").hover();
    await expect(page.locator(".cm-tooltip.is-visible")).toBeVisible({ timeout: 2000 });
    await page.evaluate(() => document.getElementById("btnToolbarMenu").remove());
    // a subsequent pointer move heals the dangling bubble
    await page.mouse.move(3, 3);
    await page.mouse.move(6, 6);
    await expect(page.locator(".cm-tooltip.is-visible")).toBeHidden();
  });

  test("on a no-hover (touch) device, hover shows no tooltip but keyboard focus still does", async ({ page }) => {
    await page.addInitScript(() => {
      const orig = window.matchMedia.bind(window);
      window.matchMedia = (q) => (/hover:\s*none/.test(q)
        ? { matches: true, media: q, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; } }
        : orig(q));
    });
    await openInline(page);
    await page.locator("#btnToolbarMenu").hover();
    await page.waitForTimeout(500);
    expect(await page.locator(".cm-tooltip.is-visible").count()).toBe(0); // no hover tooltips
    await page.locator("#btnToolbarMenu").focus();
    await expect(page.locator(".cm-tooltip.is-visible")).toBeVisible({ timeout: 1500 }); // focus still works
  });

  test("the tooltip does not overwrite a control's existing aria-label", async ({ page }) => {
    await openInline(page);
    await page.click("#btnToggleSidebar"); // open the panel so its buttons are focusable
    const saveBtn = page.locator("#btnSaveHtml");
    await saveBtn.scrollIntoViewIfNeeded();
    const before = await saveBtn.getAttribute("aria-label");
    await saveBtn.focus();
    // Generous timeout: the focus tooltip appears immediately locally but can lag under CI
    // worker contention; the assertion is about correctness, not speed.
    await expect(page.locator(".cm-tooltip.is-visible")).toBeVisible({ timeout: 5000 });
    expect(await saveBtn.getAttribute("aria-label")).toBe(before); // unchanged
  });

  test("the compact action buttons keep their short visible labels", async ({ page }) => {
    await openInline(page);
    await page.evaluate(() => document.body.classList.add("sidebar-open"));
    expect((await page.locator("#btnSaveHtml").innerText()).trim()).toBe("Portable");
    expect((await page.locator("#btnSavePlain").innerText()).trim()).toBe("Plain HTML");
    expect((await page.locator("#btnClearAll").innerText()).trim()).toBe("Clear");
  });

  test("the section caret toggles the section with the keyboard", async ({ page }) => {
    await openInline(page);
    const caret = page.locator(".cmh-sec-caret").first();
    const collapsed = () => caret.evaluate((c) => c.closest("section").classList.contains("cmh-section-collapsed"));
    expect(await collapsed()).toBe(false);
    await caret.focus();
    await page.keyboard.press("Enter");
    expect(await collapsed()).toBe(true);
    expect(await caret.getAttribute("aria-expanded")).toBe("false");
  });

  test("a whitespace-only Help search resets to the default and clears the empty state", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    await page.click("#btnHelpTop");
    const search = page.locator(".cm-help-search-input");
    await search.fill("nothing-here-xyz");
    await expect(page.locator(".cm-help-noresults")).toBeVisible();
    await search.fill("   ");
    await expect(page.locator(".cm-help-noresults")).toBeHidden();
    expect(await page.locator(".cm-help-topic:visible").count()).toBeGreaterThanOrEqual(10);
    expect(await page.locator(".cm-help-topic[open]").count()).toBe(1);
  });

  test("nonportable mode keeps the sidebar Export button's icon and full aria-label", async ({ page }) => {
    await openKitchenSinkNonPortable(page);
    await expect(page.locator("body.cm-nonportable")).toHaveCount(1);
    expect(await page.locator("#btnSaveHtml svg.cm-ui-ico").count()).toBe(1); // icon preserved
    expect((await page.locator("#btnSaveHtml span").innerText()).trim()).toBe("Portable");
    await expect(page.locator("#btnSaveHtml")).toHaveAttribute("aria-label", "Export as Portable");
  });

  test("runtime tooltip and Help DOM never bake into a Plain HTML export", async ({ page }) => {
    await openInline(page);
    await page.locator("#btnToolbarMenu").hover(); // materialize the tooltip element
    await expect(page.locator(".cm-tooltip")).toHaveCount(1);
    await openToolbarMenu(page);
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#btnSavePlainTop")]);
    // load the exported plain copy and prove the runtime chrome DID NOT bake in as DOM
    await page.goto(fileUrl(await dl.path()));
    expect(await page.locator(".cm-tooltip").count()).toBe(0);
    expect(await page.locator(".cm-help-overlay").count()).toBe(0);
    expect(await page.locator(".cm-sidebar").count()).toBe(0);
  });
});
