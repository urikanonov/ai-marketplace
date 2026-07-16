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
</section>`;

async function openDoc(page) {
  const { html } = stageContent(CONTENT, { key: "cmh-callout-a11y", source: "callout.html" });
  await page.goto(fileUrl(html));
  await ready(page);
}

async function beforeContent(page, sel) {
  return page.evaluate((s) => getComputedStyle(document.querySelector(s), "::before").content, sel);
}

test("each callout variant exposes a role and a variant accessible name (CMH-CALLOUT-03)", async ({ page }) => {
  await openDoc(page);
  for (const id of ["c-info", "c-success", "c-warning", "c-danger"]) {
    await expect(page.locator("#" + id)).toHaveAttribute("role", "note");
    const label = await page.locator("#" + id).getAttribute("aria-label");
    expect(label, id + " has a non-empty aria-label").toBeTruthy();
  }
  // The accessible names differ per variant, so a screen reader distinguishes them.
  const names = {};
  for (const id of ["c-info", "c-success", "c-warning", "c-danger"]) {
    names[id] = await page.locator("#" + id).getAttribute("aria-label");
  }
  const unique = new Set(Object.values(names));
  expect(unique.size, "variant aria-labels are distinct").toBe(4);
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
  // A grayscale reader tells variants apart by shape, so the glyphs are not all identical.
  expect(new Set(Object.values(glyphs)).size, "glyphs differ across variants").toBeGreaterThan(1);
});

test("an authored leading strong label suppresses the aria-label (CMH-CALLOUT-03)", async ({ page }) => {
  await openDoc(page);
  // The labelled callout keeps role=note but has no aria-label, so the visible <strong>
  // is not announced twice.
  await expect(page.locator("#c-labelled")).toHaveAttribute("role", "note");
  expect(await page.locator("#c-labelled").getAttribute("aria-label")).toBeNull();
});
