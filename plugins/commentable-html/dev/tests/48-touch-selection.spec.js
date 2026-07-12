// Touch / coarse-pointer selection: on phones a selection is made by dragging the native
// selection handles, which never fires `mouseup`, so the desktop popup path never runs.
// A debounced `selectionchange` must raise the SAME "Add comment" popup once the selection
// settles, and hide it when the selection collapses.
import { test, expect } from "@playwright/test";
import { fileUrl, ready, installClipboardCapture, stageContent } from "./helpers.js";

const DOC = `
  <h1>Touch selection test</h1>
  <p id="para">A paragraph of prose that a reader can select by dragging the handles.</p>`;

// Force the layer to treat this session as a coarse pointer by making the coarse/hover
// media query match before the inline layer script computes `_coarsePointer`.
async function openCoarse(page) {
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
  const { html } = stageContent(DOC, { key: "cmh-touch-sel", source: "touch-sel.html" });
  await page.goto(fileUrl(html));
  await ready(page);
}

// Select the paragraph's text WITHOUT dispatching mouseup, so only `selectionchange`
// can raise the popup (proving the touch path, not the mouse path).
async function selectPara(page) {
  await page.evaluate(() => {
    const el = document.getElementById("para");
    const t = el.firstChild;
    const range = document.createRange();
    range.setStart(t, 0);
    range.setEnd(t, t.data.length);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  });
}

test.use({ hasTouch: true });

test("a coarse-pointer text selection raises the Add Comment popup and collapsing it hides it (CMH-SEL-TOUCH-01)", async ({ page }) => {
  await openCoarse(page);
  // Sanity: the layer detected a coarse pointer, so the touch selection path is active.
  expect(await page.evaluate(() => window.matchMedia("(pointer: coarse)").matches)).toBe(true);

  const menu = page.locator("#contextMenu");
  const addBtn = page.locator("#menuComment");
  await expect(menu).toBeHidden();

  await selectPara(page);
  // The popup appears only after the debounce settles (no mouseup was fired).
  await expect(menu).toBeVisible();
  await expect(addBtn).toBeVisible();
  await expect(addBtn).toHaveText("Add Comment");

  // Collapsing the selection dismisses the popup.
  await page.evaluate(() => window.getSelection().removeAllRanges());
  await expect(menu).toBeHidden();
});
