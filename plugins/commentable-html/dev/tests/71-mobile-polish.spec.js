import { test, expect } from "@playwright/test";
import path from "path";
import fs from "fs";
import { EXAMPLES, INLINE, fileUrl, ready, stageContent } from "./helpers.js";

// Mobile-polish fixes surfaced by the visual-audit skill. Each test pins a distinct
// behavior on a phone viewport (unless noted) and would fail on the pre-fix build.
const MOBILE = { width: 390, height: 844 };

test.describe("visual-audit mobile polish", () => {
  test.use({ viewport: MOBILE });

  test("a flush top heading clears the fixed toolbar on mobile (CMH-RESP-03)", async ({ page }) => {
    const staged = stageContent(`<h1 id="flush">Flush title that would sit under the pill</h1><p>Body.</p>`,
      { key: "cmh-mobile-toolbar-clear", source: "toolbar-clear.html" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      const r = await page.evaluate(() => {
        const h1 = document.querySelector("#commentRoot > h1:first-child");
        const tb = document.querySelector(".cm-toolbar");
        return {
          isFirst: !!h1,
          marginTop: h1 ? parseFloat(getComputedStyle(h1).marginTop) : 0,
          h1Top: h1 ? h1.getBoundingClientRect().top : 0,
          toolbarBottom: tb ? tb.getBoundingClientRect().bottom : 0,
        };
      });
      expect(r.isFirst, "injected h1 is the first child of #commentRoot").toBe(true);
      expect(r.marginTop, "mobile reserves top space under the toolbar").toBeGreaterThanOrEqual(40);
      expect(r.h1Top, "the title renders below the toolbar pill, not under it").toBeGreaterThanOrEqual(r.toolbarBottom - 1);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("the comments sidebar is a full-width sheet with no resize handle on mobile (CMH-RESP-04)", async ({ page }) => {
    await page.goto(fileUrl(INLINE));
    await ready(page);
    await page.locator("#btnToggleSidebar").click();
    const r = await page.evaluate(() => {
      const sb = document.querySelector(".cm-sidebar");
      const handle = document.querySelector(".cm-sidebar-resize");
      return {
        width: sb.getBoundingClientRect().width,
        vw: document.documentElement.clientWidth,
        handleDisplay: handle ? getComputedStyle(handle).display : "none",
      };
    });
    expect(r.width, "sidebar spans the full viewport width (no document sliver)").toBeGreaterThanOrEqual(r.vw - 2);
    expect(r.handleDisplay, "the resize handle is removed at full width").toBe("none");
  });

  test("the scroll-progress bubble is hidden on narrow viewports (CMH-RESP-05)", async ({ page }) => {
    await page.goto(fileUrl(INLINE));
    await ready(page);
    const display = await page.evaluate(() => {
      const el = document.querySelector(".cm-scroll-progress");
      return el ? getComputedStyle(el).display : "missing";
    });
    expect(display, "the 0% scroll bubble does not float over mobile content").toBe("none");
  });

  test("the compact checklist control has a >=44px touch target on mobile (CMH-RESP-06)", async ({ page }) => {
    const staged = stageContent(`<h1>Touch</h1><p><button type="button" class="cmh-check" id="chk">x</button> item</p>`,
      { key: "cmh-mobile-touch", source: "touch.html" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      const size = await page.evaluate(() => {
        const el = document.getElementById("chk");
        const after = getComputedStyle(el, "::after");
        return { w: parseFloat(after.width), h: parseFloat(after.height) };
      });
      expect(size.w, "tap target width is >=44px").toBeGreaterThanOrEqual(44);
      expect(size.h, "tap target height is >=44px").toBeGreaterThanOrEqual(44);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("the reopen control is labeled Comments, not the ambiguous Show (CMH-CHROME-11)", async ({ page }) => {
    await page.goto(fileUrl(INLINE));
    await ready(page);
    const labels = await page.evaluate(() => {
      const toggle = document.getElementById("btnToggleSidebar");
      const menu = document.getElementById("btnShowTop");
      return {
        toggle: (toggle && toggle.textContent || "").trim(),
        menu: (menu && menu.querySelector("span") ? menu.querySelector("span").textContent : "").trim(),
      };
    });
    expect(labels.toggle, "the closed-state toolbar toggle reads Comments").toBe("Comments");
    expect(labels.menu, "the overflow-menu reopen item reads Comments").toBe("Comments");
  });
});

test("the disabled deck nav button keeps a readable contrast (CMH-DECK-NAV-01)", async ({ page }) => {
  await page.setViewportSize({ width: 1200, height: 800 });
  await page.goto(fileUrl(path.join(EXAMPLES, "deck-showcase.html")));
  await ready(page);
  const opacity = await page.evaluate(() => {
    const btns = [...document.querySelectorAll(".cmh-deck-nav button")];
    const disabled = btns.find((b) => b.disabled);
    return disabled ? parseFloat(getComputedStyle(disabled).opacity) : null;
  });
  expect(opacity, "a disabled deck nav button exists on the opening slide").not.toBeNull();
  expect(opacity, "the disabled label is not near-invisible").toBeGreaterThanOrEqual(0.9);
});

test("report-checklist does not repeat its document title as the first section heading (CMH-CONTENT-17)", async ({ page }) => {
  await page.goto(fileUrl(path.join(EXAMPLES, "report-checklist.html")));
  await ready(page);
  const count = await page.evaluate(() => {
    const root = document.getElementById("commentRoot");
    const label = (root.getAttribute("data-doc-label") || "").trim();
    return [...root.querySelectorAll("h1, h2, h3")].filter((h) => h.textContent.trim() === label).length;
  });
  expect(count, "the title text appears once (the lede h1), not duplicated as a section heading").toBe(1);
});
