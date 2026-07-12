import { test, expect } from "@playwright/test";
import path from "path";
import fs from "fs";
import { SKILL, fileUrl, ready, installClipboardCapture, copiedBundle, stageContent } from "./helpers.js";

const TRIAGE = path.join(SKILL, "examples", "report-triage.html");

async function dragCardToSlot(page, cardSelector, slotSelector) {
  const card = page.locator(cardSelector);
  const slot = page.locator(slotSelector);
  await card.scrollIntoViewIfNeeded();
  await slot.scrollIntoViewIfNeeded();
  const cardBox = await card.boundingBox();
  const slotBox = await slot.boundingBox();
  if (!cardBox || !slotBox) throw new Error("card or slot is not visible");
  await page.mouse.move(cardBox.x + cardBox.width / 2, cardBox.y + cardBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(slotBox.x + slotBox.width / 2, slotBox.y + Math.min(slotBox.height - 12, 80), { steps: 12 });
  await page.mouse.up();
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

test("triage cards can be dragged between opted-in slots and copied as layout changes (CMH-WIDGET-02, CMH-WIDGET-03)", async ({ page }) => {
  await installClipboardCapture(page);
  await page.goto(fileUrl(TRIAGE));
  await ready(page);

  const cardSelector = '[data-cm-part="api-saturation"]';
  const targetSlotSelector = '[data-cm-slot="Investigating"]';
  await expect(page.locator(cardSelector)).toHaveCount(1);
  await expect(page.locator(targetSlotSelector).locator(cardSelector)).toHaveCount(0);

  await dragCardToSlot(page, cardSelector, targetSlotSelector);

  await expect(page.locator(targetSlotSelector).locator(cardSelector)).toHaveCount(1);
  await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable");

  await page.click("#btnCopyAll");
  const bundle = await copiedBundle(page);
  expect(bundle).toContain("## Widget layout changes");
  expect(bundle).toContain('"API saturation" moved from New to Investigating');
});

test("widget drag-and-drop requires an explicit data-cm-draggable opt-in (CMH-WIDGET-03)", async ({ page }) => {
  const board = `
<h1>Static board</h1>
<div class="board cm-skip" data-cm-widget="static-board">
  <div class="col" data-cm-slot="Todo" id="staticTodo">
    <div class="card" data-cm-part="one" data-cm-part-label="One">One</div>
  </div>
  <div class="col" data-cm-slot="Done" id="staticDone"></div>
</div>`;
  const staged = stageContent(board, { key: "cmh-widget-drag-opt-in", source: "widget-drag-opt-in.html" });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await dragCardToSlot(page, '[data-cm-part="one"]', "#staticDone");
    await expect(page.locator("#staticTodo").locator('[data-cm-part="one"]')).toHaveCount(1);
    await expect(page.locator("#staticDone").locator('[data-cm-part="one"]')).toHaveCount(0);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Portable");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});
