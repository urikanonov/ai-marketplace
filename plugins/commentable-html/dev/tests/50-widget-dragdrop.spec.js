import { test, expect } from "@playwright/test";
import path from "path";
import fs from "fs";
import {
  DEV, SKILL, fileUrl, ready, installClipboardCapture, copiedBundle, stageContent, readDownload,
  addTextComment,
} from "./helpers.js";

const TRIAGE = path.join(SKILL, "..", "..", "examples", "report-triage.html");

async function settle(page) {
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function boxCenter(locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error("element is not visible");
  return { x: box.x + box.width / 2, y: box.y + box.height / 2, box };
}

async function slotDropPoint(locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error("slot is not visible");
  return { x: box.x + box.width / 2, y: box.y + Math.min(box.height - 12, 80) };
}

async function dragFromTo(page, sourceSelector, target, { button = "left", release = true } = {}) {
  const source = page.locator(sourceSelector);
  const start = await boxCenter(source);
  const end = typeof target === "string" ? await slotDropPoint(page.locator(target)) : target;
  await page.mouse.move(start.x, start.y);
  await page.mouse.down({ button });
  await page.mouse.move(end.x, end.y, { steps: 12 });
  if (release) await page.mouse.up({ button });
  await settle(page);
  return { start, end };
}

async function dragCardToSlot(page, cardSelector, slotSelector) {
  return dragFromTo(page, cardSelector, slotSelector);
}

async function expectCleanDragState(page, partSelector = null) {
  await expect(page.locator(".cm-widget-drop-target")).toHaveCount(0);
  expect(await page.locator("body").evaluate((body) => body.classList.contains("cm-widget-dragging"))).toBe(false);
  if (partSelector) {
    expect(await page.locator(partSelector).first().evaluate((part) => part.classList.contains("cm-widget-drag-source"))).toBe(false);
  }
}

async function copyAll(page) {
  await page.evaluate(() => document.getElementById("btnCopyAll").click());
  return copiedBundle(page);
}

async function expectNoLayoutChange(page) {
  await settle(page);
  await expect(page.locator("#cmTypeBadge")).toHaveText("Portable");
  await expect(page.locator(".cm-card-state")).toHaveCount(0);
  const before = await copiedBundle(page);
  await copyAll(page);
  expect(await copiedBundle(page)).toBe(before);
}

function makeBoard({ draggable = true, slotDraggable = false, interactive = false } = {}) {
  const widgetAttr = draggable ? " data-cm-draggable" : "";
  const slotAttr = slotDraggable ? " data-cm-draggable" : "";
  const controls = interactive ? `
      <div style="display: grid; gap: 8px; margin-top: 52px; max-width: 130px;">
        <button id="controlButton" type="button" onclick="window.__controlClicks.button++">Button</button>
        <a id="controlLink" href="#control-target" onclick="window.__controlClicks.link++">Link</a>
        <input id="controlInput" value="input" onclick="window.__controlClicks.input++">
        <textarea id="controlTextarea" onclick="window.__controlClicks.textarea++">textarea</textarea>
        <select id="controlSelect" onclick="window.__controlClicks.select++"><option>one</option></select>
        <div id="controlEditable" contenteditable="true" onclick="window.__controlClicks.editable++">Editable</div>
        <span id="control-target"></span>
      </div>` : "";
  return `
<h1>Widget drag board</h1>
<div class="drag-board cm-skip" data-cm-widget="drag-board"${widgetAttr}
  style="display: grid; grid-template-columns: repeat(3, 180px); gap: 16px; align-items: start;">
  <div class="drag-col" data-cm-slot="New" id="slotNew"${slotAttr} style="min-height: 180px; padding: 12px; border: 1px solid #999;">
    <article class="drag-card" data-cm-part="one" data-cm-part-label="One" id="cardOne" style="min-height: ${interactive ? "360" : "76"}px; padding: 10px; border: 1px solid #666; background: #fff;">One${controls}</article>
    <article class="drag-card" data-cm-part="two" data-cm-part-label="Two" id="cardTwo" style="min-height: 76px; padding: 10px; border: 1px solid #666; background: #fff;">Two</article>
  </div>
  <div class="drag-col" data-cm-slot="Doing" id="slotDoing" style="min-height: 180px; padding: 12px; border: 1px solid #999;"></div>
  <div class="drag-col" data-cm-slot="Done" id="slotDone" style="min-height: 180px; padding: 12px; border: 1px solid #999;"></div>
</div>
<div id="outsideDrop" style="margin-top: 40px; height: 120px; border: 1px dashed #999;">Outside any widget slot</div>`;
}

function makeCrossWidgetBoard() {
  return `
<h1>Cross widget board</h1>
<div style="display: grid; grid-template-columns: repeat(2, 220px); gap: 24px;">
  <div class="board-a cm-skip" data-cm-widget="board-a" data-cm-draggable style="padding: 12px; border: 1px solid #777;">
    <div data-cm-slot="A-New" id="slotANew" style="min-height: 150px; padding: 12px;">
      <article data-cm-part="alpha" data-cm-part-label="Alpha" id="cardAlpha" style="min-height: 70px; padding: 10px; border: 1px solid #666;">Alpha</article>
    </div>
  </div>
  <div class="board-b cm-skip" data-cm-widget="board-b" data-cm-draggable style="padding: 12px; border: 1px solid #777;">
    <div data-cm-slot="B-New" id="slotBNew" style="min-height: 150px; padding: 12px;">
      <article data-cm-part="beta" data-cm-part-label="Beta" id="cardBeta" style="min-height: 70px; padding: 10px; border: 1px solid #666;">Beta</article>
    </div>
  </div>
</div>`;
}

function makeNestedSlotBoard() {
  return `
<h1>Nested slot board</h1>
<div class="board cm-skip" data-cm-widget="nested-board" data-cm-draggable>
  <div class="col" data-cm-slot="Todo" id="nestedTodo" style="min-height: 220px; padding: 16px;">
    <div class="card" data-cm-part="one" data-cm-part-label="One" id="nestedCard" style="min-height: 150px; padding: 16px;">
      <strong>One</strong>
      <div class="col" data-cm-slot="Inner" id="innerSlot" style="margin-top: 24px; min-height: 72px; padding: 12px;">Inner slot</div>
    </div>
  </div>
  <div class="col" data-cm-slot="Done" id="nestedDone" style="min-height: 180px; padding: 16px;"></div>
</div>`;
}

function makeOffsetBoard() {
  return `
<h1>Widget text offset board</h1>
<section data-cm-widget="offset-board" data-cm-draggable>
  <div data-cm-slot="Before" id="offsetBefore" style="min-height: 110px; padding: 12px; border: 1px solid #999;">
    <article data-cm-part="alpha" data-cm-part-label="Alpha card" id="offsetCard"
      style="min-height: 70px; padding: 10px; border: 1px solid #666;">Alpha card text that changes text offsets.</article>
  </div>
  <p id="offsetTarget">The correct review sentence should stay highlighted after export.</p>
  <div data-cm-slot="After" id="offsetAfter" style="min-height: 110px; padding: 12px; border: 1px solid #999;"></div>
</section>`;
}

async function stageBoard(page, content, key) {
  const staged = stageContent(content, { key, source: key + ".html" });
  await page.goto(fileUrl(staged.html));
  await ready(page);
  return staged;
}

async function addWidgetComment(page, partSelector, note) {
  await page.locator(partSelector).hover();
  await expect(page.locator("#widgetAddBtn")).toBeVisible();
  await page.locator("#widgetAddBtn").click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toHaveCount(0);
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
  await expect(page.locator(".cm-card-state")).toContainText("API saturation");

  const bundle = await copyAll(page);
  expect(bundle).toContain("## Widget layout changes");
  expect(bundle).toContain('"API saturation" moved from New to Investigating');
});

test("widget drag-and-drop requires an explicit data-cm-draggable opt-in (CMH-WIDGET-03)", async ({ page }) => {
  const staged = await stageBoard(page, makeBoard({ draggable: false, slotDraggable: false }), "cmh-widget-drag-opt-in");
  try {
    await dragCardToSlot(page, "#cardOne", "#slotDone");
    await expect(page.locator("#slotNew > #cardOne")).toHaveCount(1);
    await expect(page.locator("#slotDone > #cardOne")).toHaveCount(0);
    await expectNoLayoutChange(page);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("a sub-threshold click on a draggable card still opens the widget comment composer (CMH-WIDGET-04)", async ({ page }) => {
  await page.goto(fileUrl(TRIAGE));
  await ready(page);

  const card = page.locator('[data-cm-part="api-saturation"]');
  const { x, y } = await boxCenter(card);
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 2, y + 2, { steps: 2 });
  await page.mouse.up();
  await settle(page);

  await expect(page.locator("#widgetAddBtn")).toBeVisible();
  await page.locator("#widgetAddBtn").click();
  const composer = page.locator(".cm-composer").last();
  await expect(composer).toBeVisible();
  await expect(composer.locator("textarea")).toBeFocused();
});

test("dropping a card back on its origin slot emits no layout-change bundle line (CMH-WIDGET-05)", async ({ page }) => {
  await installClipboardCapture(page);
  await page.goto(fileUrl(TRIAGE));
  await ready(page);

  await dragCardToSlot(page, '[data-cm-part="api-saturation"]', '[data-cm-slot="New"]');
  await expect(page.locator('[data-cm-slot="New"] [data-cm-part="api-saturation"]')).toHaveCount(1);
  await expectNoLayoutChange(page);
});

test("dropping a widget part onto its own nested slot is a no-op and clears drag state (CMH-WIDGET-06)", async ({ page }) => {
  const staged = await stageBoard(page, makeNestedSlotBoard(), "cmh-widget-nested-slot");
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await dragCardToSlot(page, "#nestedCard", "#innerSlot");

    expect(pageErrors).toEqual([]);
    await expect(page.locator("#nestedTodo > #nestedCard")).toHaveCount(1);
    await expectNoLayoutChange(page);
    await expectCleanDragState(page, "#nestedCard");

    await dragCardToSlot(page, "#nestedCard", "#nestedDone");
    await expect(page.locator("#nestedDone > #nestedCard")).toHaveCount(1);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("dropping outside any slot cancels the drag without moving or leaving state (CMH-WIDGET-07)", async ({ page }) => {
  const staged = await stageBoard(page, makeBoard(), "cmh-widget-outside-drop");
  try {
    const outside = await boxCenter(page.locator("#outsideDrop"));
    await dragFromTo(page, "#cardOne", { x: outside.x, y: outside.y });

    await expect(page.locator("#slotNew > #cardOne")).toHaveCount(1);
    await expectNoLayoutChange(page);
    await expectCleanDragState(page, "#cardOne");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("cross-widget drops are ignored because the target slot is outside the dragged widget (CMH-WIDGET-08)", async ({ page }) => {
  const staged = await stageBoard(page, makeCrossWidgetBoard(), "cmh-widget-cross-drop");
  try {
    await dragCardToSlot(page, "#cardAlpha", "#slotBNew");

    await expect(page.locator("#slotANew > #cardAlpha")).toHaveCount(1);
    await expect(page.locator("#slotBNew > #cardAlpha")).toHaveCount(0);
    await expectNoLayoutChange(page);
    await expectCleanDragState(page, "#cardAlpha");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("interactive descendants do not start drags and still receive clicks (CMH-WIDGET-09)", async ({ page }) => {
  const staged = await stageBoard(page, makeBoard({ interactive: true }), "cmh-widget-interactive-guards");
  await page.evaluate(() => {
    window.__controlClicks = { button: 0, link: 0, input: 0, textarea: 0, select: 0, editable: 0 };
  });
  const controls = [
    ["#controlButton", "button"],
    ["#controlLink", "link"],
    ["#controlInput", "input"],
    ["#controlTextarea", "textarea"],
    ["#controlSelect", "select"],
    ["#controlEditable", "editable"],
  ];
  try {
    for (const [selector, key] of controls) {
      await dragFromTo(page, selector, "#slotDone");
      await expect(page.locator("#slotNew > #cardOne")).toHaveCount(1);
      await page.locator(selector).click({ force: true });
      expect(await page.evaluate((k) => window.__controlClicks[k], key)).toBeGreaterThan(0);
      await expectNoLayoutChange(page);
    }
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("non-primary mouse buttons do not start widget drags (CMH-WIDGET-10)", async ({ page }) => {
  const staged = await stageBoard(page, makeBoard(), "cmh-widget-non-primary");
  try {
    await dragFromTo(page, "#cardOne", "#slotDone", { button: "right" });

    await expect(page.locator("#slotNew > #cardOne")).toHaveCount(1);
    await expectNoLayoutChange(page);
    await expectCleanDragState(page, "#cardOne");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("touch and pen pointer events do not start widget drags (CMH-WIDGET-11)", async ({ page }) => {
  const staged = await stageBoard(page, makeBoard(), "cmh-widget-non-mouse");
  try {
    for (const pointerType of ["touch", "pen"]) {
      await page.evaluate((type) => {
        const card = document.getElementById("cardOne");
        const slot = document.getElementById("slotDone");
        const c = card.getBoundingClientRect();
        const s = slot.getBoundingClientRect();
        const init = { bubbles: true, cancelable: true, pointerId: type === "touch" ? 41 : 42, pointerType: type, button: 0, clientX: c.left + c.width / 2, clientY: c.top + c.height / 2 };
        card.dispatchEvent(new PointerEvent("pointerdown", init));
        document.dispatchEvent(new PointerEvent("pointermove", { ...init, clientX: s.left + s.width / 2, clientY: s.top + 40 }));
        document.dispatchEvent(new PointerEvent("pointerup", { ...init, clientX: s.left + s.width / 2, clientY: s.top + 40 }));
      }, pointerType);
      await settle(page);
      await expect(page.locator("#slotNew > #cardOne")).toHaveCount(1);
      await expectNoLayoutChange(page);
    }
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("pointercancel during a widget drag clears state and leaves the DOM unchanged (CMH-WIDGET-12)", async ({ page }) => {
  const staged = await stageBoard(page, makeBoard(), "cmh-widget-pointercancel");
  try {
    await dragFromTo(page, "#cardOne", "#slotDone", { release: false });
    await expect(page.locator("body")).toHaveClass(/cm-widget-dragging/);
    await page.evaluate(() => document.dispatchEvent(new PointerEvent("pointercancel", { bubbles: true, pointerId: 1, pointerType: "mouse" })));
    await page.mouse.up();
    await settle(page);

    await expect(page.locator("#slotNew > #cardOne")).toHaveCount(1);
    await expectNoLayoutChange(page);
    await expectCleanDragState(page, "#cardOne");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("dragging applies and clears the drop-target affordance classes (CMH-WIDGET-13)", async ({ page }) => {
  const staged = await stageBoard(page, makeBoard(), "cmh-widget-affordance");
  try {
    await dragFromTo(page, "#cardOne", "#slotDone", { release: false });
    await expect(page.locator("body")).toHaveClass(/cm-widget-dragging/);
    await expect(page.locator("#cardOne")).toHaveClass(/cm-widget-drag-source/);
    await expect(page.locator("#slotDone")).toHaveClass(/cm-widget-drop-target/);

    await page.mouse.up();
    await settle(page);
    await expect(page.locator("#slotDone > #cardOne")).toHaveCount(1);
    await expectCleanDragState(page, "#cardOne");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("multiple sequential widget drags work without stuck listeners or state (CMH-WIDGET-14)", async ({ page }) => {
  await page.goto(fileUrl(TRIAGE));
  await ready(page);

  await dragCardToSlot(page, '[data-cm-part="api-saturation"]', '[data-cm-slot="Investigating"]');
  await expect(page.locator('[data-cm-slot="Investigating"] [data-cm-part="api-saturation"]')).toHaveCount(1);
  await expectCleanDragState(page, '[data-cm-part="api-saturation"]');

  await dragCardToSlot(page, '[data-cm-part="worker-lag"]', '[data-cm-slot="Fixed"]');
  await expect(page.locator('[data-cm-slot="Fixed"] [data-cm-part="worker-lag"]')).toHaveCount(1);
  await expectCleanDragState(page, '[data-cm-part="worker-lag"]');
  await expect(page.locator(".cm-card-state")).toContainText("API saturation");
  await expect(page.locator(".cm-card-state")).toContainText("Worker lag");
});

test("moving a card away and back to its baseline slot leaves no net widget state change (CMH-WIDGET-15)", async ({ page }) => {
  await installClipboardCapture(page);
  await page.goto(fileUrl(TRIAGE));
  await ready(page);

  await dragCardToSlot(page, '[data-cm-part="api-saturation"]', '[data-cm-slot="Investigating"]');
  await expect(page.locator('[data-cm-slot="Investigating"] [data-cm-part="api-saturation"]')).toHaveCount(1);
  await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable");

  await dragCardToSlot(page, '[data-cm-part="api-saturation"]', '[data-cm-slot="New"]');
  await expect(page.locator('[data-cm-slot="New"] [data-cm-part="api-saturation"]')).toHaveCount(1);
  await expectNoLayoutChange(page);
});

test("exporting after a move persists the new DOM order and keeps widget comments anchored (CMH-WIDGET-16)", async ({ page, browser }) => {
  await installClipboardCapture(page);
  await page.goto(fileUrl(TRIAGE));
  await ready(page);

  await addWidgetComment(page, '[data-cm-part="api-saturation"]', "follow this card");
  await expect(page.locator('[data-cm-part="api-saturation"]')).toHaveClass(/cm-part-hl/);
  await dragCardToSlot(page, '[data-cm-part="api-saturation"]', '[data-cm-slot="Investigating"]');
  await expect(page.locator('[data-cm-slot="Investigating"] [data-cm-part="api-saturation"]')).toHaveClass(/cm-part-hl/);

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#btnSaveHtml").click(),
  ]);
  const html = await readDownload(download);
  expect(html).toMatch(/data-cm-slot="Investigating"[\s\S]*data-cm-part="api-saturation"/);
  expect(html).not.toMatch(/data-cm-slot="New"[\s\S]*data-cm-part="api-saturation"[\s\S]*data-cm-slot="Investigating"/);

  const exportedPath = path.join(path.resolve(DEV, "..", "..", "..", "tmp"), "cmh-widget-exported.html");
  fs.mkdirSync(path.dirname(exportedPath), { recursive: true });
  fs.writeFileSync(exportedPath, html);
  const ctx = await browser.newContext();
  try {
    const page2 = await ctx.newPage();
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    await expect(page2.locator('[data-cm-slot="Investigating"] [data-cm-part="api-saturation"]')).toHaveCount(1);
    await expect(page2.locator('[data-cm-slot="Investigating"] [data-cm-part="api-saturation"]')).toHaveClass(/cm-part-hl/);
    await expect(page2.locator("#commentList")).toContainText("follow this card");
  } finally {
    await ctx.close();
    fs.rmSync(exportedPath, { force: true });
  }
});

test("exporting after a widget move refreshes later prose text comment offsets (CMH-WIDGET-17)", async ({ page, browser }) => {
  const staged = await stageBoard(page, makeOffsetBoard(), "cmh-widget-export-text-offsets");
  const exportedPath = path.join(path.resolve(DEV, "..", "..", "..", "tmp"), "cmh-widget-text-offset-exported.html");
  try {
    await addTextComment(page, "#offsetTarget", "plain text near a widget move");
    await expect(page.locator("#offsetTarget mark.cm-hl")).toContainText("correct review sentence should stay highlighted after export.");
    await dragCardToSlot(page, "#offsetCard", "#offsetAfter");
    await expect(page.locator("#offsetAfter > #offsetCard")).toHaveCount(1);

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnSaveHtml").click(),
    ]);
    const html = await readDownload(download);
    fs.mkdirSync(path.dirname(exportedPath), { recursive: true });
    fs.writeFileSync(exportedPath, html);

    const ctx = await browser.newContext();
    try {
      const page2 = await ctx.newPage();
      await page2.goto(fileUrl(exportedPath));
      await ready(page2);
      await expect(page2.locator("#offsetAfter > #offsetCard")).toHaveCount(1);
      await expect(page2.locator("#offsetTarget mark.cm-hl")).toContainText("correct review sentence should stay highlighted after export.");
      await expect(page2.locator("#commentList")).toContainText("plain text near a widget move");
    } finally {
      await ctx.close();
    }
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(exportedPath, { force: true });
  }
});
