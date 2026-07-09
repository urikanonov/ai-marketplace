import { test, expect } from "@playwright/test";
import { fileUrl, ready, KITCHEN_SINK, distinctCids, markTextForCid, storedComments } from "./helpers.js";

// UI batch 4: anchoring robustness for block/triple-click selections whose end lands
// on injected cm-skip chrome (the section carets), plus heading Add-Comment placement.

test.describe("anchoring: a selection whose end lands on a cm-skip caret still anchors", () => {
  test("triple-click-style selection ending on a section caret anchors to the real text", async ({ page }) => {
    await page.goto(fileUrl(KITCHEN_SINK));
    await ready(page);

    // Reproduce the exact failing boundary the browser produces for a triple-click on
    // the paragraph just before a collapsible section: start in the last real text
    // node, end at (sectionCaret, 0). Before the fix, offsetWithin(caret,0) returned
    // -1 and the save aborted with "Could not anchor that selection".
    const expected = await page.evaluate(() => {
      const root = document.getElementById("commentRoot");
      const caret = document.querySelector(".cmh-sec-caret");
      if (!caret) return { ok: false, reason: "no caret" };
      const accept = (n) => (n.nodeValue && !(n.parentElement && n.parentElement.closest(".cm-skip")));
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode: (n) => (accept(n) && n.nodeValue.trim().length >= 4) ? 1 : 3,
      });
      let prev = null, n;
      while ((n = walker.nextNode())) {
        if (caret.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_PRECEDING) prev = n; else break;
      }
      if (!prev) return { ok: false, reason: "no preceding text" };
      const r = document.createRange();
      r.setStart(prev, 0);
      r.setEnd(caret, 0);
      const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
      prev.parentElement.scrollIntoView({ block: "center" });
      prev.parentElement.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
      // the heading that owns the caret - its text must NOT end up inside the comment
      const headingText = (caret.parentElement.textContent || "").trim();
      return { ok: true, prevStart: prev.nodeValue.trim().slice(0, 12), headingText };
    });
    expect(expected.ok, expected.reason).toBe(true);

    await page.waitForTimeout(10);
    await expect(page.locator("#menuComment")).toBeVisible();
    await page.locator("#menuComment").click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("boundary anchor");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);

    // No error toast, exactly one comment, and its highlight covers real text that
    // begins where the selection began and stops before the next section heading
    // (it did not sweep the cm-skip caret / following heading into the anchor).
    const toast = await page.evaluate(() => {
      const t = document.getElementById("toast");
      return t && t.classList.contains("show") ? t.textContent : "";
    });
    expect(toast).not.toContain("Could not anchor");
    expect(await distinctCids(page)).toBe(1);
    const cid = (await storedComments(page))[0].id;
    const covered = await markTextForCid(page, cid);
    expect(covered.trim().length).toBeGreaterThan(0);
    expect(covered.trim().startsWith(expected.prevStart)).toBe(true);
    if (expected.headingText) expect(covered.includes(expected.headingText)).toBe(false);

    // and it round-trips through a reload with the identical covered text (valid offsets)
    await page.reload();
    await ready(page);
    expect(await distinctCids(page)).toBe(1);
    expect(await markTextForCid(page, cid)).toBe(covered);
  });
});

test.describe("heading Add Comment placement and header layout", () => {
  test("the heading Add Comment button sits just after the title text, not at the far right", async ({ page }) => {
    await page.goto(fileUrl(KITCHEN_SINK));
    await ready(page);
    // pick a heading whose text is much shorter than its (full-width) block, so
    // "next to the text" and "far right of the block" are clearly distinguishable
    const picked = await page.evaluate(() => {
      const hs = [...document.querySelectorAll("#commentRoot h2, #commentRoot h3")];
      for (const h of hs) {
        if (!(h.textContent || "").trim()) continue;
        const range = document.createRange(); range.selectNodeContents(h);
        const rects = [...range.getClientRects()].filter((r) => r.width > 0.5);
        if (!rects.length) continue;
        const textRight = Math.max(...rects.map((r) => r.right));
        const hr = h.getBoundingClientRect();
        if (hr.right - textRight > 200) { h.id = h.id || "cmh-test-h"; h.scrollIntoView({ block: "center" }); h.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true })); return { id: h.id }; }
      }
      return null;
    });
    expect(picked, "a short section heading with slack to the right").not.toBeNull();
    await expect(page.locator("#headingAddBtn")).toBeVisible();
    const m = await page.evaluate((id) => {
      const h = document.getElementById(id);
      const range = document.createRange(); range.selectNodeContents(h);
      const textRight = Math.max(...[...range.getClientRects()].filter((r) => r.width > 0.5).map((r) => r.right));
      const hr = h.getBoundingClientRect();
      const b = document.getElementById("headingAddBtn").getBoundingClientRect();
      return { textRight, blockRight: hr.right, btnLeft: b.left };
    }, picked.id);
    // the button begins right after the title text (small gap), and is nowhere near
    // the far right of the heading block
    expect(m.btnLeft - m.textRight).toBeGreaterThan(-6);
    expect(m.btnLeft - m.textRight).toBeLessThan(40);
    expect(m.blockRight - m.btnLeft).toBeGreaterThan(120);
  });

  test("Help and Hide are a grouped pair with a small gap, and Hide has a right chevron", async ({ page }) => {
    await page.goto(fileUrl(KITCHEN_SINK));
    await ready(page);
    await page.evaluate(() => document.body.classList.add("sidebar-open"));
    const info = await page.evaluate(() => {
      const help = document.getElementById("btnHelp");
      const hide = document.getElementById("btnCloseSidebar");
      const group = help.closest(".cm-head-actions");
      const chevron = hide.querySelector(".cm-btn-chevron");
      const hr = help.getBoundingClientRect(), dr = hide.getBoundingClientRect();
      return {
        grouped: !!(group && group.contains(hide)),
        hasChevron: !!chevron,
        sameRow: Math.abs(hr.top - dr.top) < 3,
        gap: dr.left - hr.right,
      };
    });
    expect(info.grouped).toBe(true);
    expect(info.hasChevron).toBe(true);
    expect(info.sameRow).toBe(true);
    expect(info.gap).toBeGreaterThanOrEqual(0);
    expect(info.gap).toBeLessThan(14);
  });
});
