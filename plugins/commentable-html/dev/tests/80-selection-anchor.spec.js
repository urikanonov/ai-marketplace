// Add-Comment popup anchoring: a whole-line selection is normalized by the browser PAST the end
// of its block, so range.getClientRects() ends with a rect covering the WHOLE following block (a
// chart figure, an image, a table). The popup must anchor to the selected TEXT, not that trailing
// block rect, on both the desktop mouseup path and the coarse-pointer selectionchange path.
import { test, expect } from "@playwright/test";
import { fileUrl, ready, installClipboardCapture, stageContent } from "./helpers.js";

const DOC = `
  <h1>Quarterly incident review</h1>
  <p id="lead">Open incidents rose sharply in the final week.</p>
  <figure class="chart" aria-labelledby="chart-cap">
    <div class="chart-wrap cm-skip" style="position: relative; height: 400px;">
      <canvas id="anchor-canvas" style="width: 100%; height: 100%;"></canvas>
    </div>
    <figcaption id="chart-cap">Open incidents by queue and severity.</figcaption>
  </figure>`;

// Reproduce the browser's whole-line/paragraph normalization: the range starts inside the
// paragraph's text node and ENDS in the following block at offset 0, so getClientRects()
// returns the words' rect PLUS a rect covering the entire chart block.
async function selectWholeLineSpillingIntoChart(page) {
  return page.evaluate(() => {
    const p = document.getElementById("lead");
    const cap = document.getElementById("chart-cap");
    const range = document.createRange();
    range.setStart(p.firstChild, 0);
    range.setEnd(cap, 0);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    const rects = [...range.getClientRects()];
    return {
      text: sel.toString(),
      rectCount: rects.length,
      lastRectBottom: rects.length ? rects[rects.length - 1].bottom : null,
    };
  });
}

// The bounds of the selected WORDS themselves (not the paragraph's full-width box).
function textRect(page) {
  return page.evaluate(() => {
    const t = document.getElementById("lead").firstChild;
    const r = document.createRange();
    r.setStart(t, 0);
    r.setEnd(t, t.data.length);
    const box = r.getBoundingClientRect();
    return { top: box.top, bottom: box.bottom, right: box.right };
  });
}

async function menuBox(page) {
  return page.locator("#contextMenu").evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { top: r.top, left: r.left };
  });
}

test("a whole-line selection above a tall chart anchors the Add Comment popup to the selected text, not the chart (CMH-SEL-03)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await installClipboardCapture(page);
  const { html } = stageContent(DOC, { key: "cmh-sel-anchor", source: "sel-anchor.html" });
  await page.goto(fileUrl(html));
  await ready(page);

  const words = await textRect(page);
  const sel = await selectWholeLineSpillingIntoChart(page);
  // Premise of the regression: the raw range really does carry a trailing rect for the whole
  // chart block, far below the selected words. Without it the test would prove nothing.
  expect(sel.text.trim()).toBe("Open incidents rose sharply in the final week.");
  expect(sel.rectCount).toBeGreaterThan(1);
  expect(sel.lastRectBottom).toBeGreaterThan(words.bottom + 200);

  await page.evaluate(() => {
    document.getElementById("lead").dispatchEvent(
      new MouseEvent("mouseup", { bubbles: true, button: 0, clientX: 100, clientY: 100 }));
  });
  await expect(page.locator("#contextMenu")).toBeVisible();

  const box = await menuBox(page);
  expect(box.top).toBeGreaterThanOrEqual(words.top - 4);
  expect(box.top).toBeLessThanOrEqual(words.bottom + 24);
  expect(Math.abs(box.left - words.right)).toBeLessThanOrEqual(24);
});

test("the popup anchors to the last selected line, and to the words when the range ends at offset 0 of a following text node (CMH-SEL-03)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await installClipboardCapture(page);
  const { html } = stageContent(DOC, { key: "cmh-sel-anchor-edge", source: "sel-anchor-edge.html" });
  await page.goto(fileUrl(html));
  await ready(page);

  // The end boundary is offset 0 of the NEXT block's own text node (the other shape the browser
  // normalizes a whole-line selection into), so the walk must still find the paragraph's words.
  const words = await textRect(page);
  await page.evaluate(() => {
    const p = document.getElementById("lead");
    const cap = document.getElementById("chart-cap");
    const range = document.createRange();
    range.setStart(p.firstChild, 0);
    range.setEnd(cap.firstChild, 0);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    document.getElementById("lead").dispatchEvent(
      new MouseEvent("mouseup", { bubbles: true, button: 0, clientX: 100, clientY: 100 }));
  });
  await expect(page.locator("#contextMenu")).toBeVisible();
  let box = await menuBox(page);
  expect(box.top).toBeLessThanOrEqual(words.bottom + 24);
  expect(Math.abs(box.left - words.right)).toBeLessThanOrEqual(24);

  // A selection that spans the paragraph AND the caption still anchors to its LAST line (the
  // caption), not the first - the fix must not pull the popup back to the start of the selection.
  const capRect = await page.evaluate(() => {
    const t = document.getElementById("chart-cap").firstChild;
    const r = document.createRange();
    r.setStart(t, 0);
    r.setEnd(t, t.data.length);
    const box = r.getBoundingClientRect();
    return { top: box.top, bottom: box.bottom, right: box.right };
  });
  await page.evaluate(() => {
    const p = document.getElementById("lead");
    const cap = document.getElementById("chart-cap");
    const range = document.createRange();
    range.setStart(p.firstChild, 0);
    range.setEnd(cap.firstChild, cap.firstChild.data.length);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    document.getElementById("chart-cap").dispatchEvent(
      new MouseEvent("mouseup", { bubbles: true, button: 0, clientX: 100, clientY: 100 }));
  });
  await expect(page.locator("#contextMenu")).toBeVisible();
  box = await menuBox(page);
  expect(box.top).toBeGreaterThanOrEqual(capRect.top - 4);
  expect(box.top).toBeLessThanOrEqual(capRect.bottom + 24);
  expect(Math.abs(box.left - capRect.right)).toBeLessThanOrEqual(24);
});

test.describe("coarse pointer", () => {
  test.use({ hasTouch: true });

  test("the touch selectionchange path anchors the popup to the selected text too (CMH-SEL-03)", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.addInitScript(() => {
      const orig = window.matchMedia.bind(window);
      window.matchMedia = (q) => {
        if (/pointer:\s*coarse|hover:\s*none/.test(q)) {
          return {
            matches: true, media: q, onchange: null,
            addEventListener() {}, removeEventListener() {},
            addListener() {}, removeListener() {}, dispatchEvent() { return false; },
          };
        }
        return orig(q);
      };
    });
    await installClipboardCapture(page);
    const { html } = stageContent(DOC, { key: "cmh-sel-anchor-touch", source: "sel-anchor-touch.html" });
    await page.goto(fileUrl(html));
    await ready(page);
    expect(await page.evaluate(() => window.matchMedia("(pointer: coarse)").matches)).toBe(true);

    const words = await textRect(page);
    await selectWholeLineSpillingIntoChart(page);
    // No mouseup: only the debounced selectionchange path can raise the popup.
    await expect(page.locator("#contextMenu")).toBeVisible();

    const box = await menuBox(page);
    expect(box.top).toBeGreaterThanOrEqual(words.top - 4);
    expect(box.top).toBeLessThanOrEqual(words.bottom + 24);
    expect(Math.abs(box.left - words.right)).toBeLessThanOrEqual(24);
  });
});
