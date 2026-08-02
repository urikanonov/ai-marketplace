import { test, expect } from "@playwright/test";
import { openInline, ready, openToolbarMenu, openSidebarExportMenu, openSidebarMoreMenu, addTextComment, fileUrl, INLINE, openKitchenSinkNonPortable } from "./helpers.js";

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

  test("the About block links to the project website and live demo (CMH-HELP-SITE-01)", async ({ page }) => {
    await openHelp(page);
    const site = page.locator(".cm-help-about a", { hasText: "Website and live demo" });
    await expect(site).toHaveCount(1);
    await expect(site).toHaveAttribute("href", /urikanonov\.github\.io\/ai-marketplace\/commentable-html\//);
    await expect(site).toHaveAttribute("rel", /noopener/);
  });

  test("the Self-contained and privacy topic explains localStorage privacy and portable bundling (CMH-PRIVACY-01)", async ({ page }) => {
    await openHelp(page);
    const topic = page.locator(".cm-help-topic", { hasText: "Self-contained and privacy" });
    await expect(topic).toHaveCount(1);
    await topic.locator("summary").click(); // expand the collapsed topic
    const body = topic.locator(".cm-help-topic-body");
    await expect(body).toContainText("localStorage");
    await expect(body).toContainText(/private/i);
    // The review layer is described as embedded only in Portable mode, not always bundled.
    await expect(body).toContainText(/Portable/);
    await expect(body).not.toContainText("bundled into this file");
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
  test("the two timestamps stack on separate rows and the action ribbon sits on one row", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await openInline(page);
    await page.evaluate(() => document.body.classList.add("sidebar-open"));
    const rects = await page.evaluate(() => {
      const r = (id) => { const e = document.getElementById(id); const b = e.getBoundingClientRect(); return { top: Math.round(b.top), h: b.height }; };
      const ribbon = document.querySelector(".cm-sidebar .head-ribbon");
      const tops = Array.from(ribbon.children).map((c) => Math.round(c.getBoundingClientRect().top));
      return { gen: r("cmGenerated"), last: r("cmLastComment"), ribbonRows: new Set(tops).size };
    });
    // The metadata stacks: Last comment sits on its own row below Generated (proposal-9 layout).
    expect(rects.last.top).toBeGreaterThan(rects.gen.top + 4);
    // the action ribbon stays on one compact row.
    expect(rects.ribbonRows).toBe(1);
    // The compact Export control is a disclosure, not an ARIA menu button.
    const exportButton = page.locator("#btnSidebarExportMenu");
    await expect(exportButton).toHaveAttribute("aria-controls", "sidebarExportMenu");
    await expect(exportButton).toHaveAttribute("aria-expanded", "false");
    expect(await exportButton.getAttribute("aria-haspopup")).toBeNull();
    // The accessible name comes from the visible label - no aria-label override that would
    // announce a shorter, different name than the one a voice-control user can read (WCAG 2.5.3).
    expect(await page.locator("#btnClearAll").getAttribute("aria-label")).toBeNull();
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
    await page.clock.install();
    await openInline(page);
    await page.locator("#btnToolbarMenu").hover();
    await page.clock.fastForward(400);
    expect(await page.locator(".cm-tooltip.is-visible").count()).toBe(0); // no hover tooltips
    await page.locator("#btnToolbarMenu").focus();
    await expect(page.locator(".cm-tooltip.is-visible")).toBeVisible({ timeout: 1500 }); // focus still works
  });

  test("the tooltip does not overwrite a control's existing aria-label", async ({ page }) => {
    await openInline(page);
    await page.click("#btnToggleSidebar"); // open the panel so its buttons are focusable
    await openSidebarExportMenu(page);
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
    expect((await page.locator("#btnSidebarExportMenu").innerText()).trim()).toBe("Export");
    // Clear now lives in the More menu as a full menu item.
    expect((await page.locator("#btnClearAll").textContent()).trim()).toBe("Clear all comments");
  });

  test("the sidebar More menu holds Manage storage and Clear all (CMH-SIDE-11)", async ({ page }) => {
    await openInline(page);
    await page.evaluate(() => {
      document.body.classList.add("sidebar-open");
      const sb = document.getElementById("sidebar");
      if (sb) sb.inert = false;
    });
    const menu = page.locator("#sidebarMoreMenu");
    await expect(menu).toBeHidden();
    await page.click("#btnMoreMenu");
    await expect(menu).toBeVisible();
    await expect(menu.locator("#btnStorage")).toBeVisible();
    await expect(menu.locator("#btnClearAll")).toBeVisible();
    // The Export menu no longer carries Storage (it holds only the file formats).
    await expect(page.locator("#sidebarExportMenu #btnStorage")).toHaveCount(0);
  });

  test("the sidebar More menu is content-width, anchored to its toggle, and clear of the Export button (CMH-SIDE-11)", async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 900 });
    await openInline(page);
    await page.evaluate(() => {
      document.body.classList.add("sidebar-open");
      const sb = document.getElementById("sidebar");
      if (sb) sb.inert = false;
    });
    const measure = async () => {
      await page.click("#btnMoreMenu");
      await expect(page.locator("#sidebarMoreMenu")).toBeVisible();
      const m = await page.evaluate(() => {
        const ribbon = document.querySelector(".cm-sidebar .head-ribbon");
        const menu = document.getElementById("sidebarMoreMenu");
        const btn = menu.querySelector("button");
        const toggle = document.getElementById("btnMoreMenu");
        const exp = document.getElementById("btnSidebarExportMenu");
        const clip = (el) => Math.max(0, el.scrollWidth - el.clientWidth);
        const rr = ribbon.getBoundingClientRect();
        const mr = menu.getBoundingClientRect();
        const tr = toggle.getBoundingClientRect();
        const er = exp.getBoundingClientRect();
        return {
          ribbonWidth: rr.width, menuWidth: mr.width,
          menuRight: mr.right, toggleRight: tr.right,
          viewportWidth: window.innerWidth,
          btnBg: getComputedStyle(btn).backgroundColor,
          exportCenterX: (er.left + er.right) / 2,
          storageClip: clip(document.getElementById("btnStorage")),
          clearClip: clip(document.getElementById("btnClearAll")),
        };
      });
      await page.click("#btnMoreMenu"); // close before the next case
      return m;
    };
    // At the default width AND at the sidebar's enforced minimum width, the menu must stay readable
    // (labels not clipped - the regression this guards), anchored to its toggle's right edge,
    // viewport-safe, and clear of the Export button's center so the two disclosures can swap.
    for (const shrinkToMin of [false, true]) {
      if (shrinkToMin) {
        await page.locator("#sidebarResizeHandle").focus();
        await page.keyboard.press("Home");
      }
      const m = await measure();
      expect(m.menuWidth).toBeLessThan(m.ribbonWidth - 8);
      expect(["rgba(0, 0, 0, 0)", "transparent"]).toContain(m.btnBg);
      expect(m.storageClip, "Manage storage label must not be clipped").toBeLessThanOrEqual(0.5);
      expect(m.clearClip, "Clear all comments label must not be clipped").toBeLessThanOrEqual(0.5);
      expect(Math.abs(m.menuRight - m.toggleRight)).toBeLessThanOrEqual(1);
      expect(m.menuRight).toBeLessThanOrEqual(m.viewportWidth + 1);
      expect(m.menuRight).toBeLessThan(m.exportCenterX);
    }
  });

  test("opening either sidebar disclosure closes the sibling one (CMH-SIDE-11)", async ({ page }) => {
    await openInline(page);
    await page.evaluate(() => {
      document.body.classList.add("sidebar-open");
      const sb = document.getElementById("sidebar");
      if (sb) sb.inert = false;
    });
    const exportMenu = page.locator("#sidebarExportMenu");
    const moreMenu = page.locator("#sidebarMoreMenu");
    // Export open, then More: Export closes and its toggle resets aria-expanded.
    await page.click("#btnSidebarExportMenu");
    await expect(exportMenu).toBeVisible();
    await page.click("#btnMoreMenu");
    await expect(moreMenu).toBeVisible();
    await expect(exportMenu).toBeHidden();
    await expect(page.locator("#btnSidebarExportMenu")).toHaveAttribute("aria-expanded", "false");
    // The reverse direction: opening Export again closes More.
    await page.click("#btnSidebarExportMenu");
    await expect(exportMenu).toBeVisible();
    await expect(moreMenu).toBeHidden();
    await expect(page.locator("#btnMoreMenu")).toHaveAttribute("aria-expanded", "false");
  });

  test("on a phone the Sort button and the primary-row actions expose a >=44px touch target (CMH-SIDE-12)", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openInline(page);
    await page.evaluate(() => {
      document.body.classList.add("sidebar-open");
      const sb = document.getElementById("sidebar");
      if (sb) sb.inert = false;
    });
    // The Sort/Search ribbon buttons and both primary-row actions (Copy all and the Export toggle,
    // which is no longer a ribbon button) must each meet the 44px touch-target minimum on phones.
    for (const sel of ["#btnSort", "#btnSearchToggle", "#btnCopyAll", "#btnSidebarExportMenu"]) {
      const b = await page.locator(sel).evaluate((el) => {
        const r = el.getBoundingClientRect();
        return { w: r.width, h: r.height };
      });
      expect(b.w, `${sel} width`).toBeGreaterThanOrEqual(44);
      expect(b.h, `${sel} height`).toBeGreaterThanOrEqual(44);
    }
  });

  test("the Search button reveals and focuses the filter field (CMH-SEARCH-08)", async ({ page }) => {
    await openInline(page);
    await page.evaluate(() => {
      document.body.classList.add("sidebar-open");
      const sb = document.getElementById("sidebar");
      if (sb) sb.inert = false;
    });
    const row = page.locator(".head-search");
    await expect(row).toBeHidden();
    await page.click("#btnSearchToggle");
    await expect(row).toBeVisible();
    await expect(page.locator("#cmSearchInput")).toBeFocused();
    await expect(page.locator("#btnSearchToggle")).toHaveAttribute("aria-expanded", "true");
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

  test("nonportable mode keeps the sidebar Export button's icon and menu contract", async ({ page }) => {
    await openKitchenSinkNonPortable(page);
    await expect(page.locator("body.cm-nonportable")).toHaveCount(1);
    expect(await page.locator("#btnSidebarExportMenu svg.cm-ui-ico").count()).toBe(1); // icon preserved
    expect((await page.locator("#btnSidebarExportMenu span").innerText()).trim()).toBe("Export");
    await expect(page.locator("#btnSidebarExportMenu")).toHaveAttribute("aria-controls", "sidebarExportMenu");
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

// Clear all comments is reachable from the toolbar overflow menu too, so a reviewer working with
// the comments panel hidden does not have to re-open the panel to clear. It is a second ENTRY
// POINT into the one clear-all flow, never a second implementation.
test.describe("Clear all comments from the toolbar overflow menu (CMH-UI-13)", () => {
  async function seedComment(page) {
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "clear me from the collapsed toolbar");
    await expect(page.locator("#commentList .cm-card")).toHaveCount(1);
  }

  async function hidePanel(page) {
    await page.click("#btnCloseSidebar");
    await expect(page.locator("body.sidebar-open")).toHaveCount(0);
    await expect(page.locator("#btnToolbarMenu")).toBeVisible();
  }

  test("the overflow menu groups Clear all comments beside Manage storage (CMH-UI-13)", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    const item = page.locator("#toolbarMenu #btnClearAllTop");
    await expect(item).toBeVisible();
    expect((await item.textContent()).trim()).toBe("Clear all comments");
    await expect(item).toHaveClass(/danger/);
    expect(await item.locator("svg.cm-ui-ico").count()).toBe(1);
    const tip = (await item.getAttribute("title")) || (await item.getAttribute("data-cmh-tip"));
    expect((tip || "").length).toBeGreaterThan(8);
    // Both entry points take their accessible name from the visible label (no aria-label override
    // announcing a different, shorter name than a voice-control user reads - WCAG 2.5.3).
    expect(await item.getAttribute("aria-label")).toBeNull();
    expect(await page.locator("#btnClearAll").getAttribute("aria-label")).toBeNull();
    // ...and the COMPUTED accessible name really is the visible label, not just the absence of an
    // override (an aria-labelledby could still rename it).
    await expect(page.locator("#toolbarMenu").getByRole("button", { name: "Clear all comments" })).toHaveCount(1);
    // The two data-management actions stay together: Clear sits right after Manage storage.
    const next = await page.locator("#toolbarMenu #btnStorageTop")
      .evaluate((el) => el.nextElementSibling && el.nextElementSibling.id);
    expect(next).toBe("btnClearAllTop");
    // Adding the item leaves the menu's Escape/focus contract intact (CMH-UI-10).
    await page.keyboard.press("Escape");
    await expect(page.locator("#toolbarMenu")).toBeHidden();
    await expect(page.locator("#btnToolbarMenu")).toBeFocused();
  });

  test("clearing from the overflow menu works with the panel hidden (CMH-UI-13)", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    const pristineMode = (await page.locator("#cmhModeBadge").textContent()).trim();
    // Pin the premise so the round-trip below cannot degrade into asserting the same value twice.
    expect(pristineMode).toBe("Portable");
    await page.keyboard.press("Escape");
    await addTextComment(page, "#commentRoot p", "clear me from the collapsed toolbar");
    await expect(page.locator("#commentList .cm-card")).toHaveCount(1);
    await hidePanel(page);
    await expect(page.locator("#toolbarCount")).toHaveText("1");

    await openToolbarMenu(page);
    // With something to clear, both items are live again and carry the destructive tooltip.
    for (const sel of ["#btnClearAllTop", "#btnClearAll"]) {
      const b = page.locator(sel);
      await expect(b, sel).toHaveAttribute("aria-disabled", "false");
      const tip = (await b.getAttribute("title")) || (await b.getAttribute("data-cmh-tip"));
      expect(tip, sel).toMatch(/Delete every comment/);
    }
    await expect(page.locator("#cmhModeBadge")).toHaveText("Not portable");
    await page.click("#btnClearAllTop");
    // The menu closes on the action and its trigger's expanded state follows.
    await expect(page.locator("#toolbarMenu")).toBeHidden();
    await expect(page.locator("#btnToolbarMenu")).toHaveAttribute("aria-expanded", "false");
    const modal = page.locator(".cm-modal");
    await expect(modal).toBeVisible();
    await expect(page.locator("#commentList .cm-card")).toHaveCount(1); // nothing cleared yet
    await modal.locator("button.danger").click(); // OK

    await expect(page.locator(".cm-modal")).toHaveCount(0);
    await expect(page.locator("body.sidebar-open")).toHaveCount(0); // the panel never re-opened
    await expect(page.locator("#commentList .cm-card")).toHaveCount(0);
    await expect(page.locator("#commentRoot .cm-hl")).toHaveCount(0);
    await expect(page.locator("#toolbarCount")).toHaveText("0");
    // Focus lands on the still-visible overflow trigger, not the now-hidden menu item.
    await expect(page.locator("#btnToolbarMenu")).toBeFocused();
    await openToolbarMenu(page);
    await expect(page.locator("#cmhModeBadge")).toHaveText(pristineMode);
    // ...and the item goes back to its empty state without needing the panel.
    await expect(page.locator("#btnClearAllTop")).toHaveAttribute("aria-disabled", "true");
  });

  test("the overflow menu Clear all runs the same confirmed flow as the sidebar item (CMH-UI-13)", async ({ page }) => {
    await seedComment(page);
    // Sidebar entry point: capture the confirmation text, then cancel.
    await openSidebarMoreMenu(page);
    await page.click("#btnClearAll");
    const sidebarMsg = await page.locator(".cm-modal-msg").textContent();
    await page.keyboard.press("Escape");
    await expect(page.locator(".cm-modal")).toHaveCount(0);
    await expect(page.locator("#btnMoreMenu")).toBeFocused(); // cancel restores to the sidebar trigger
    // Toolbar entry point with the panel hidden: byte-identical confirmation text.
    await hidePanel(page);
    await openToolbarMenu(page);
    await page.click("#btnClearAllTop");
    expect(await page.locator(".cm-modal-msg").textContent()).toBe(sidebarMsg);
    await page.keyboard.press("Escape");
    await expect(page.locator(".cm-modal")).toHaveCount(0);
    await expect(page.locator("#btnToolbarMenu")).toBeFocused(); // ...and to the toolbar trigger
    await expect(page.locator("#commentList .cm-card")).toHaveCount(1); // cancel kept everything
  });

  test("with nothing to clear both entry points are inert and keep focus on their trigger (CMH-UI-13)", async ({ page }) => {
    await openInline(page);
    // Pristine document: no comments, and no widget / checklist / note change tracked yet, so the
    // shared guard sees nothing to clear. (The count pill is deliberately NOT the premise here - it
    // excludes widget-layout changes, so it can read 0 while the guard is non-empty.) The proof the
    // guard is empty is that no confirmation opens below.
    await expect(page.locator("#commentList .cm-card")).toHaveCount(0);
    expect(await page.evaluate(() => window.__cmhStorageCodec.read().length)).toBe(0);
    await openToolbarMenu(page);
    // Both items advertise the empty state identically, so the two entry points never disagree.
    for (const sel of ["#btnClearAllTop", "#btnClearAll"]) {
      const b = page.locator(sel);
      await expect(b, sel).toHaveAttribute("aria-disabled", "true");
      const tip = (await b.getAttribute("title")) || (await b.getAttribute("data-cmh-tip"));
      expect(tip, sel).toMatch(/Nothing to clear/);
    }
    // Activate with the keyboard (an aria-disabled control is not "actionable" for a synthetic
    // click, but a real user - and a real keyboard - can still fire it).
    await page.locator("#btnClearAllTop").focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".cm-modal")).toHaveCount(0); // no confirm dialog for an empty set
    // The menu still closed on the click, so focus must land on its trigger, not <body>.
    await expect(page.locator("#toolbarMenu")).toBeHidden();
    await expect(page.locator("#btnToolbarMenu")).toBeFocused();
    // The sidebar item behaves identically - the guard is shared, and so is the focus contract.
    await page.click("#btnToggleSidebar");
    await openSidebarMoreMenu(page);
    await page.locator("#btnClearAll").focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".cm-modal")).toHaveCount(0);
    await expect(page.locator("#sidebarMoreMenu")).toBeHidden();
    await expect(page.locator("#btnMoreMenu")).toBeFocused();
  });

  test("a repeat activation while the confirm dialog is open does not pull focus out of it (CMH-UI-13)", async ({ page }) => {
    await seedComment(page);
    await hidePanel(page);
    await openToolbarMenu(page);
    await page.click("#btnClearAllTop");
    const modal = page.locator(".cm-modal");
    await expect(modal).toBeVisible();
    // Re-activate the (now hidden) item programmatically: the re-entrancy guard must return
    // WITHOUT restoring focus, or the caret would land behind the aria-modal overlay.
    await page.locator("#btnClearAllTop").evaluate((b) => b.click());
    await expect(modal).toBeVisible();
    const inside = await page.evaluate(() => document.querySelector(".cm-modal").contains(document.activeElement));
    expect(inside).toBe(true);
    await page.keyboard.press("Escape");
    await expect(page.locator(".cm-modal")).toHaveCount(0);
    await expect(page.locator("#commentList .cm-card")).toHaveCount(1);
  });
});
