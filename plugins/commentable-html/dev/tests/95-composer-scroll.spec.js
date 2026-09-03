import { test, expect } from "@playwright/test";
import path from "path";
import { EXAMPLES, fileUrl, ready, routeVendoredLibs } from "./helpers.js";

// CMH-CORE-20: working a comment composer must never move the document. Chromium scroll anchoring
// reacts to the layout change composer creation makes and shifts window.scrollY a frame LATER -
// after the composer has already been placed from the anchor's rect - which slid the selected text
// toward the top of the viewport while the fixed composer stayed put (#838). Closing and saving are
// the same class of mutation in reverse, so they are measured here too. The jump is
// position-dependent (an anchor near the middle of the viewport moved, the same one near the top or
// bottom did not), so the sweep drives every commentable block in a long report at several viewport
// offsets rather than trusting one placement.
const EXAMPLE = path.join(EXAMPLES, "report-community-garden.html");
const OFFSETS = [150, 400, 650];

// The example renders charts and diagrams after the runtime reports ready, and that content does its
// own legitimate scroll anchoring. Wait for the document to stop moving and growing before measuring
// anything, so a settling report is never charged to the composer.
async function settle(page) {
  await page.evaluate(async () => {
    const frame = () => new Promise((r) => requestAnimationFrame(r));
    let steady = 0;
    let seenY = -1, seenH = -1;
    for (let i = 0; i < 600 && steady < 30; i += 1) {
      await frame();
      const y = Math.round(window.scrollY);
      const h = Math.round(document.documentElement.scrollHeight);
      steady = (y === seenY && h === seenH) ? steady + 1 : 0;
      seenY = y;
      seenH = h;
    }
  });
}

// The example loads Chart.js from the pinned CDN (CMH-SIZE-09). Serve it from the vendored copy -
// the bytes its `integrity` names - so the chart cannot land AFTER `settle()` and grow the document
// mid-measurement, which would be charged to the composer.
async function openExample(page) {
  await routeVendoredLibs(page);
  await page.goto(fileUrl(EXAMPLE));
}

test.describe("working a composer preserves the document scroll (CMH-CORE-20)", () => {
  test("opening and closing a text composer leaves window.scrollY and the anchor's viewport position untouched (CMH-CORE-20)", async ({ page }) => {
    test.setTimeout(180000);
    // The reproduction needs a document several viewports tall and an anchor mid-viewport.
    await page.setViewportSize({ width: 2000, height: 1000 });
    await openExample(page);
    await ready(page);
    await settle(page);
    expect(await page.evaluate(() => document.documentElement.scrollHeight),
      "the example is tall enough for scroll anchoring to have a candidate").toBeGreaterThan(5000);

    const result = await page.evaluate(async (offsets) => {
      const nextFrame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      const macrotask = () => new Promise((r) => setTimeout(r, 0));
      const anchors = [...document.querySelectorAll("#commentRoot p, #commentRoot td, #commentRoot li")]
        .filter((el) => (el.textContent || "").trim().length > 60
          && !el.closest(".cm-skip")
          // An element that already carries a highlight would re-open that comment for editing,
          // which deliberately scrolls its anchor into view.
          && !el.querySelector("mark"));
      const moved = [];
      const perOffset = {};
      let opened = 0, closed = 0;
      const at = (el) => ({ y: Math.round(window.scrollY), top: Math.round(el.getBoundingClientRect().top) });
      for (let i = 0; i < anchors.length; i += 1) {
        const el = anchors[i];
        for (const want of offsets) {
          window.scrollTo(0, Math.round(window.scrollY + el.getBoundingClientRect().top - want));
          await nextFrame();
          // Bucket by where the anchor ACTUALLY landed: near the ends of the document the scroll
          // clamps, so a requested offset is not proof the anchor was placed there.
          const placed = Math.round(el.getBoundingClientRect().top);
          if (Math.abs(placed - want) > 25) continue;
          // Select the block's text the way a drag does, then raise the Add-comment popup.
          const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
          const first = walker.nextNode();
          if (!first) continue;
          let last = first, n;
          while ((n = walker.nextNode())) last = n;
          const range = document.createRange();
          range.setStart(first, first.data.length > 2 ? 1 : 0);
          range.setEnd(last, last.data.length);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
          const rect = el.getBoundingClientRect();
          el.dispatchEvent(new MouseEvent("mouseup", {
            bubbles: true,
            clientX: Math.round(rect.left + 8),
            clientY: Math.round(rect.top + 8),
          }));
          await macrotask();
          const addBtn = document.getElementById("menuComment");
          if (!addBtn || !addBtn.getClientRects().length) continue;

          // OPEN: a fresh baseline immediately before the click, so only this action is measured.
          const beforeOpen = at(el);
          addBtn.click();
          const composer = [...document.querySelectorAll(".cm-composer")].pop();
          if (!composer) continue;
          opened += 1;
          perOffset[want] = (perOffset[want] || 0) + 1;
          // The browser's adjustment lands asynchronously, so settle a couple of frames and a
          // macrotask (the composer focuses its textarea on one) before measuring.
          await nextFrame();
          await macrotask();
          const afterOpen = at(el);
          if (afterOpen.y !== beforeOpen.y || afterOpen.top !== beforeOpen.top) {
            moved.push({ action: "open", index: i, offset: want, scrollDelta: afterOpen.y - beforeOpen.y });
          }

          // CLOSE: the reverse mutation (the preview marks come out, the surface is removed) is
          // just as anchorable, and is measured on its own baseline.
          const beforeClose = at(el);
          composer.querySelector('[data-act="cancel"]').click();
          closed += 1;
          await nextFrame();
          await macrotask();
          const afterClose = at(el);
          if (afterClose.y !== beforeClose.y || afterClose.top !== beforeClose.top) {
            moved.push({ action: "close", index: i, offset: want, scrollDelta: afterClose.y - beforeClose.y });
          }
        }
      }
      return { opened, closed, perOffset, moved: moved.slice(0, 10), movedCount: moved.length };
    }, OFFSETS);

    // Guard against a vacuous pass: the sweep must actually have opened and closed composers, and it
    // must have done so at EVERY offset - the jump is position-dependent, so coverage at one
    // placement is not coverage of the behavior.
    expect(result.opened, "the sweep opened composers to measure").toBeGreaterThan(40);
    expect(result.closed, "the sweep closed those composers to measure").toBe(result.opened);
    for (const want of OFFSETS) {
      expect(result.perOffset[want] || 0, `composers opened with the anchor ${want}px down the viewport`).toBeGreaterThan(10);
    }
    expect(result.moved, `working a composer moved the document ${result.movedCount} time(s)`).toEqual([]);
  });

  test("saving a comment leaves the document where it was (CMH-CORE-20)", async ({ page }) => {
    await page.setViewportSize({ width: 2000, height: 1000 });
    await openExample(page);
    await ready(page);
    await settle(page);

    const result = await page.evaluate(async () => {
      const nextFrame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      const macrotask = () => new Promise((r) => setTimeout(r, 0));
      const anchors = [...document.querySelectorAll("#commentRoot p, #commentRoot td, #commentRoot li")]
        .filter((el) => (el.textContent || "").trim().length > 60
          && !el.closest(".cm-skip") && !el.querySelector("mark"));
      const moved = [];
      let saved = 0;
      for (let i = 0; i < anchors.length; i += 1) {
        const el = anchors[i];
        window.scrollTo(0, Math.round(window.scrollY + el.getBoundingClientRect().top - 400));
        await nextFrame();
        if (Math.abs(Math.round(el.getBoundingClientRect().top) - 400) > 25) continue;
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        const first = walker.nextNode();
        if (!first) continue;
        let last = first, n;
        while ((n = walker.nextNode())) last = n;
        const range = document.createRange();
        range.setStart(first, first.data.length > 2 ? 1 : 0);
        range.setEnd(last, last.data.length);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        const rect = el.getBoundingClientRect();
        el.dispatchEvent(new MouseEvent("mouseup", {
          bubbles: true,
          clientX: Math.round(rect.left + 8),
          clientY: Math.round(rect.top + 8),
        }));
        await macrotask();
        const addBtn = document.getElementById("menuComment");
        if (!addBtn || !addBtn.getClientRects().length) continue;
        addBtn.click();
        const composer = [...document.querySelectorAll(".cm-composer")].pop();
        if (!composer) continue;
        await nextFrame();
        await macrotask();
        composer.querySelector("textarea").value = "scroll guard save " + i;
        composer.querySelector("textarea").dispatchEvent(new Event("input", { bubbles: true }));
        const before = { y: Math.round(window.scrollY), top: Math.round(el.getBoundingClientRect().top) };
        composer.querySelector('[data-act="save"]').click();
        saved += 1;
        await nextFrame();
        await macrotask();
        const after = { y: Math.round(window.scrollY), top: Math.round(el.getBoundingClientRect().top) };
        if (after.y !== before.y || after.top !== before.top) {
          moved.push({ index: i, scrollDelta: after.y - before.y, anchorDelta: after.top - before.top });
        }
      }
      return { saved, moved: moved.slice(0, 10), movedCount: moved.length };
    });

    expect(result.saved, "the sweep saved comments to measure").toBeGreaterThan(10);
    expect(result.moved, `saving moved the document ${result.movedCount} time(s)`).toEqual([]);
  });

  test("the scroll guard is re-entrant and leaves no lingering overflow-anchor override (CMH-CORE-20)", async ({ page }) => {
    await page.setViewportSize({ width: 2000, height: 1000 });
    await openExample(page);
    await ready(page);
    await settle(page);

    const result = await page.evaluate(async () => {
      const frame = () => new Promise((r) => requestAnimationFrame(r));
      const macrotask = () => new Promise((r) => setTimeout(r, 0));
      const contentRoot = document.getElementById("commentRoot");
      const openOn = (el) => {
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        const first = walker.nextNode();
        let last = first, n;
        while ((n = walker.nextNode())) last = n;
        const range = document.createRange();
        range.setStart(first, 0);
        range.setEnd(last, last.data.length);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        const rect = el.getBoundingClientRect();
        el.dispatchEvent(new MouseEvent("mouseup", {
          bubbles: true,
          clientX: Math.round(rect.left + 8),
          clientY: Math.round(rect.top + 8),
        }));
      };
      const blocks = [...contentRoot.querySelectorAll("p")]
        .filter((el) => (el.textContent || "").trim().length > 60 && !el.querySelector("mark"));
      const a = blocks[Math.floor(blocks.length * 0.5)];
      const b = blocks[Math.floor(blocks.length * 0.5) + 1];

      window.scrollTo(0, Math.round(window.scrollY + a.getBoundingClientRect().top - 400));
      await frame();
      await frame();
      const before = Math.round(window.scrollY);
      openOn(a);
      await macrotask();
      document.getElementById("menuComment").click();
      // A SECOND composer opened while the first is still up must be guarded in its own right. Let
      // the first composer take focus first (it does so on a macrotask), since that is what clears
      // the document selection.
      await macrotask();
      await frame();
      const mid = Math.round(window.scrollY);
      // The first composer now holds focus in its textarea; a real reviewer starting a second
      // selection leaves it, so drop focus before selecting again.
      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
      openOn(b);
      await macrotask();
      const menuShown = document.getElementById("menuComment").getClientRects().length > 0;
      const beforeSecond = Math.round(window.scrollY);
      document.getElementById("menuComment").click();
      await frame();
      await frame();
      await macrotask();
      const afterSecond = Math.round(window.scrollY);
      const composers = document.querySelectorAll(".cm-composer").length;
      // Both guards have expired by now, so the inline override must be gone.
      await frame();
      await frame();
      await frame();
      await macrotask();
      const leftover = contentRoot.style.getPropertyValue("overflow-anchor");
      document.querySelectorAll('.cm-composer [data-act="cancel"]').forEach((btn) => btn.click());
      return { before, mid, beforeSecond, afterSecond, composers, leftover, menuShown };
    });

    expect(result.menuShown, "the second selection raised the Add-comment popup").toBe(true);
    expect(result.composers, "two composers were open at once").toBe(2);
    expect(result.mid, "the first composer left the document where it was").toBe(result.before);
    expect(result.afterSecond, "the second composer left the document where it was").toBe(result.beforeSecond);
    expect(result.leftover, "the guard removes its inline overflow-anchor once it expires").toBe("");
  });

  test("the guard puts back a host document's own inline overflow-anchor, value and priority (CMH-CORE-20)", async ({ page }) => {
    await page.setViewportSize({ width: 2000, height: 1000 });
    await openExample(page);
    await ready(page);
    await settle(page);

    const result = await page.evaluate(async () => {
      const frame = () => new Promise((r) => requestAnimationFrame(r));
      const macrotask = () => new Promise((r) => setTimeout(r, 0));
      const contentRoot = document.getElementById("commentRoot");
      // A host document that had its own say about anchoring must get it back verbatim.
      contentRoot.style.setProperty("overflow-anchor", "auto", "important");
      const el = [...contentRoot.querySelectorAll("p")]
        .filter((p) => (p.textContent || "").trim().length > 60 && !p.querySelector("mark"))[3];
      window.scrollTo(0, Math.round(window.scrollY + el.getBoundingClientRect().top - 400));
      await frame();
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const first = walker.nextNode();
      let last = first, n;
      while ((n = walker.nextNode())) last = n;
      const range = document.createRange();
      range.setStart(first, 0);
      range.setEnd(last, last.data.length);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      const rect = el.getBoundingClientRect();
      el.dispatchEvent(new MouseEvent("mouseup", {
        bubbles: true,
        clientX: Math.round(rect.left + 8),
        clientY: Math.round(rect.top + 8),
      }));
      await macrotask();
      document.getElementById("menuComment").click();
      const during = {
        value: contentRoot.style.getPropertyValue("overflow-anchor"),
        priority: contentRoot.style.getPropertyPriority("overflow-anchor"),
      };
      await frame();
      await frame();
      await frame();
      await macrotask();
      const after = {
        value: contentRoot.style.getPropertyValue("overflow-anchor"),
        priority: contentRoot.style.getPropertyPriority("overflow-anchor"),
      };
      document.querySelectorAll('.cm-composer [data-act="cancel"]').forEach((btn) => btn.click());
      return { during, after };
    });

    expect(result.during, "the guard suppresses anchoring while the composer is built").toEqual({ value: "none", priority: "important" });
    expect(result.after, "the host's own inline declaration comes back exactly").toEqual({ value: "auto", priority: "important" });
  });
});
