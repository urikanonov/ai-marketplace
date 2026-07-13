// Document-wide comments: right-clicking empty space offers an unanchored, whole-document
// comment that carries no highlight and no offsets.
import { test, expect } from "@playwright/test";
import { fileUrl, ready, installClipboardCapture, stageContent, copiedBundle, storedComments } from "./helpers.js";

const DOC = `
  <h1>Doc-wide test</h1>
  <p id="para">Some prose with <a href="https://example.com" id="lnk">a link</a> in it.</p>`;

async function open(page) {
  await installClipboardCapture(page);
  const { html } = stageContent(DOC, { key: "cmh-docwide-test", source: "doc-wide.html" });
  await page.goto(fileUrl(html));
  await ready(page);
}

async function rightClick(page, selector) {
  await page.evaluate((sel) => {
    const el = sel === "root" ? document.getElementById("commentRoot") : document.querySelector(sel);
    el.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 40, clientY: 200 }));
  }, selector);
}

test("right-click empty space shows the document-comment menu item", async ({ page }) => {
  await open(page);
  await rightClick(page, "root");
  await expect(page.locator("#contextMenu")).toBeVisible();
  await expect(page.locator("#menuDocComment")).toBeVisible();
  await expect(page.locator("#menuComment")).toBeHidden();
});

test("a real right-click (mousedown, mouseup, then contextmenu) keeps the doc-comment menu open (CMH-DOCCMT regression)", async ({ page }) => {
  await open(page);
  // A real desktop right-click fires mousedown -> mouseup -> contextmenu. The mouseup path
  // must not clear the document-comment menu that the contextmenu handler just opened.
  // The synthetic-only test above dispatches contextmenu alone, so it never fires the
  // mouseup and cannot catch this race (the menu flickered open then vanished).
  await page.evaluate(() => {
    const root = document.getElementById("commentRoot");
    const opts = { bubbles: true, cancelable: true, clientX: 40, clientY: 200, button: 2 };
    root.dispatchEvent(new MouseEvent("mousedown", opts));
    root.dispatchEvent(new MouseEvent("mouseup", opts));
    root.dispatchEvent(new MouseEvent("contextmenu", opts));
  });
  // Let the mouseup's queued setTimeout(0) run: the menu must still be visible.
  await page.waitForTimeout(40);
  await expect(page.locator("#contextMenu")).toBeVisible();
  await expect(page.locator("#menuDocComment")).toBeVisible();
});

test("right-click on a link leaves the native menu (no context menu shown)", async ({ page }) => {
  await open(page);
  await rightClick(page, "#lnk");
  await expect(page.locator("#contextMenu")).toBeHidden();
});

test("creating a document-wide comment stores an unanchored comment", async ({ page }) => {
  await open(page);
  await rightClick(page, "root");
  await page.click("#menuDocComment");
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("Overall: tighten the intro.");
  await composer.locator('[data-act="save"]').click();
  const stored = await storedComments(page);
  expect(stored.length).toBe(1);
  expect(stored[0].anchorType).toBe("document");
  expect(stored[0].quote).toBe("(document-wide)");
  // No text highlight is created for a document-wide comment.
  expect(await page.locator("mark.cm-hl").count()).toBe(0);
});

test("the sidebar card reads document-wide and has no jump button", async ({ page }) => {
  await open(page);
  await rightClick(page, "root");
  await page.click("#menuDocComment");
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("doc note");
  await composer.locator('[data-act="save"]').click();
  const card = page.locator(".cm-card.cm-card-doc");
  await expect(card).toHaveCount(1);
  await expect(card).toContainText("document-wide");
  await expect(card.locator('[data-act="jump"]')).toHaveCount(0);
  await expect(card.locator('[data-act="edit"]')).toHaveCount(1);
});

test("Copy all describes the document-wide anchor", async ({ page }) => {
  await open(page);
  await rightClick(page, "root");
  await page.click("#menuDocComment");
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("bundle doc note");
  await composer.locator('[data-act="save"]').click();
  await page.click("#btnCopyAll");
  const bundle = await copiedBundle(page);
  expect(bundle).toContain("(document)");
  expect(bundle).toContain("Anchor: document-wide (not tied to a specific element)");
  expect(bundle).toContain("bundle doc note");
});

const RICH_DOC = `
  <h1>Exclusions</h1>
  <p id="para">Prose here.</p>
  <p><a href="https://e.com" id="lnk">link</a> <button id="btn">b</button>
     <img id="img" src="x.png" alt="x" width="20" height="20"></p>
  <div class="w cm-skip" data-cm-widget="wd"><span data-cm-part="p1" data-cm-part-label="P1">P1</span></div>`;

async function openRichDoc(page, extraInit) {
  await installClipboardCapture(page);
  if (extraInit) await page.addInitScript(extraInit);
  const { html } = stageContent(RICH_DOC, { key: "cmh-docwide-rich", source: "doc-rich.html" });
  await page.goto(fileUrl(html));
  await ready(page);
}

for (const sel of ["#lnk", "#btn", "#img", '[data-cm-part="p1"]']) {
  test(`right-click on ${sel} leaves the native menu (no doc-comment menu)`, async ({ page }) => {
    await openRichDoc(page);
    await page.evaluate((s) => {
      document.querySelector(s).dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 30, clientY: 120 }));
    }, sel);
    await expect(page.locator("#contextMenu")).toBeHidden();
  });
}

test("on a coarse pointer the doc-comment menu never appears", async ({ page }) => {
  await openRichDoc(page, () => {
    const orig = window.matchMedia;
    window.matchMedia = (q) => (/coarse|hover: none/.test(q) ? { matches: true, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} } : orig.call(window, q));
  });
  await page.evaluate(() => document.getElementById("commentRoot").dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 30, clientY: 120 })));
  await expect(page.locator("#contextMenu")).toBeHidden();
});

test("menu mode resets to text after a document-wide right-click", async ({ page }) => {
  await openRichDoc(page);
  // First a document-wide right-click sets document mode.
  await page.evaluate(() => document.getElementById("commentRoot").dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 30, clientY: 120 })));
  await expect(page.locator("#menuDocComment")).toBeVisible();
  await page.keyboard.press("Escape");
  // Then a real text selection + right-click must show the text "Add Comment", not the doc item.
  await page.evaluate(() => {
    const p = document.getElementById("para");
    const r = document.createRange(); r.selectNodeContents(p);
    const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    p.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 20, clientY: 60 }));
  });
  await expect(page.locator("#menuComment")).toBeVisible();
  await expect(page.locator("#menuDocComment")).toBeHidden();
});
