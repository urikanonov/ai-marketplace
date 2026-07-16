// A3 / CMH-CALLOUT-03: callouts carry a NON-COLOR affordance so their meaning survives
// grayscale printing and color-blindness, and screen readers announce the variant. Each
// variant gets a ::before glyph and a role="note" with a variant aria-label; an authored
// leading <strong> label suppresses the aria-label to avoid a double announcement.
import { test, expect } from "@playwright/test";
import { stageContent, fileUrl, ready } from "./helpers.js";

const CONTENT = `
<section aria-labelledby="h"><h2 id="h">Callouts</h2>
  <div class="cmh-callout cmh-callout-info" id="c-info"><p>Plain info aside.</p></div>
  <div class="cmh-callout cmh-callout-success" id="c-success"><p>Good outcome.</p></div>
  <div class="cmh-callout cmh-callout-warning" id="c-warning"><p>A caution.</p></div>
  <div class="cmh-callout cmh-callout-danger" id="c-danger"><p>The key takeaway.</p></div>
  <div class="cmh-callout cmh-callout-danger" id="c-labelled"><p><strong>Bottom line.</strong> Authored label.</p></div>
  <div class="cmh-callout cmh-callout-warning" id="c-midbold"><p>Heads up, <strong>not a leading label.</strong></p></div>
  <div class="cmh-callout cmh-callout-info" id="c-explicit" aria-label="Custom label"><p>Author set the label.</p></div>
  <div class="cmh-callout cmh-callout-danger" id="c-emptylead"><p></p><p><strong>Bottom line.</strong> After an empty node.</p></div>
</section>`;

async function openDoc(page) {
  const { html } = stageContent(CONTENT, { key: "cmh-callout-a11y", source: "callout.html" });
  await page.goto(fileUrl(html));
  await ready(page);
}

async function beforeContent(page, sel) {
  return page.evaluate((s) => getComputedStyle(document.querySelector(s), "::before").content, sel);
}

test("each callout variant exposes role=note and the correct variant accessible name (CMH-CALLOUT-03)", async ({ page }) => {
  await openDoc(page);
  const EXPECT = { "c-info": "Note", "c-success": "Success", "c-warning": "Warning", "c-danger": "Danger" };
  for (const id in EXPECT) {
    await expect(page.locator("#" + id)).toHaveAttribute("role", "note");
    await expect(page.locator("#" + id)).toHaveAttribute("aria-label", EXPECT[id]);
  }
});

test("an explicit author aria-label is respected (CMH-CALLOUT-03)", async ({ page }) => {
  await openDoc(page);
  await expect(page.locator("#c-explicit")).toHaveAttribute("aria-label", "Custom label");
});

test("each callout variant renders a distinct non-color glyph (CMH-CALLOUT-03)", async ({ page }) => {
  await openDoc(page);
  const glyphs = {};
  for (const id of ["c-info", "c-success", "c-warning", "c-danger"]) {
    const c = await beforeContent(page, "#" + id);
    expect(c, id + " has a ::before glyph").toBeTruthy();
    expect(["none", "normal", '""', ""].includes(c), id + " glyph is not empty").toBeFalsy();
    glyphs[id] = c;
  }
  // A grayscale reader tells variants apart by shape, so EACH variant's glyph is distinct.
  expect(new Set(Object.values(glyphs)).size, "each variant glyph is distinct").toBe(4);
});

test("an authored leading strong label suppresses the aria-label (CMH-CALLOUT-03)", async ({ page }) => {
  await openDoc(page);
  // The labelled callout keeps role=note but has no aria-label, so the visible <strong>
  // is not announced twice.
  await expect(page.locator("#c-labelled")).toHaveAttribute("role", "note");
  expect(await page.locator("#c-labelled").getAttribute("aria-label")).toBeNull();
});

test("mid-sentence bold does NOT suppress the aria-label (CMH-CALLOUT-03)", async ({ page }) => {
  await openDoc(page);
  // A <strong> that is not the leading label (text precedes it) must keep the variant label.
  await expect(page.locator("#c-midbold")).toHaveAttribute("role", "note");
  expect(await page.locator("#c-midbold").getAttribute("aria-label")).toBe("Warning");
});

test("an empty leading element does not defeat strong-label suppression (CMH-CALLOUT-03)", async ({ page }) => {
  await openDoc(page);
  // A stray empty <p> before the labelled paragraph still counts as a leading <strong> label.
  await expect(page.locator("#c-emptylead")).toHaveAttribute("role", "note");
  expect(await page.locator("#c-emptylead").getAttribute("aria-label")).toBeNull();
});
