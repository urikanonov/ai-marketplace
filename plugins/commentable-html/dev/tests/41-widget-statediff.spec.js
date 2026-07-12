// Widget layout state-change tracking: a drag/drop move vs the load-time baseline is
// surfaced as a synthetic record in the sidebar and Copy-all, and flips portability.
import { test, expect } from "@playwright/test";
import { fileUrl, ready, installClipboardCapture, stageContent, copiedBundle } from "./helpers.js";

const BOARD = `
  <h1>Board</h1>
  <div class="board cm-skip" data-cm-widget="triage" id="board">
    <div class="col" data-cm-slot="Now" id="now">
      <div class="card" data-cm-part="a" data-cm-part-label="Card A">Card A</div>
    </div>
    <div class="col" data-cm-slot="Later" id="later">
      <div class="card" data-cm-part="b" data-cm-part-label="Card B">Card B</div>
    </div>
  </div>`;

async function open(page) {
  await installClipboardCapture(page);
  const { html } = stageContent(BOARD, { key: "cmh-statediff-test" });
  await page.goto(fileUrl(html));
  await ready(page);
  return html;
}

async function waitForWidgetMutationFrame(page) {
  await page.evaluate(() => new Promise((resolve) => {
    if (typeof requestAnimationFrame !== "function") {
      resolve();
      return;
    }
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  }));
}

async function moveCard(page, part, targetSlotId) {
  await page.evaluate(({ part, targetSlotId }) => {
    const card = document.querySelector('[data-cm-part="' + part + '"]');
    document.getElementById(targetSlotId).appendChild(card);
  }, { part, targetSlotId });
  await waitForWidgetMutationFrame(page);
}

test("no state card and Portable when nothing moved", async ({ page }) => {
  await open(page);
  await expect(page.locator(".cm-card-state")).toHaveCount(0);
  await expect(page.locator("#cmTypeBadge")).toHaveText("Portable");
});

test("moving a card surfaces a layout-change card and flips to Not portable", async ({ page }) => {
  await open(page);
  await moveCard(page, "a", "later");
  const stateCard = page.locator(".cm-card-state");
  await expect(stateCard).toHaveCount(1);
  await expect(stateCard).toContainText("Card A");
  await expect(stateCard).toContainText("Now");
  await expect(stateCard).toContainText("Later");
  await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable");
  const reason = await page.getAttribute("#cmTypeBadge", "title");
  expect(reason).toContain("layout was changed");
});

test("Copy all includes a Widget layout changes section", async ({ page }) => {
  await open(page);
  await moveCard(page, "a", "later");
  await page.click("#btnCopyAll");
  const bundle = await copiedBundle(page);
  expect(bundle).toContain("## Widget layout changes");
  expect(bundle).toContain('"Card A" moved from Now to Later');
});

test("moving the card back clears the change and restores Portable", async ({ page }) => {
  await open(page);
  await moveCard(page, "a", "later");
  await expect(page.locator(".cm-card-state")).toHaveCount(1);
  await moveCard(page, "a", "now");
  await expect(page.locator(".cm-card-state")).toHaveCount(0);
  await expect(page.locator("#cmTypeBadge")).toHaveText("Portable");
});

test("a layout change alone (no comments) is still copyable", async ({ page }) => {
  await open(page);
  await moveCard(page, "b", "now");
  await page.click("#btnCopyAll");
  const bundle = await copiedBundle(page);
  expect(bundle).toContain("Widget layout changes");
  expect(bundle).toContain('"Card B" moved from Later to Now');
});

const BOARD2 = `
  <h1>Board2</h1>
  <div class="board cm-skip" data-cm-widget="triage" id="board2">
    <div class="col" data-cm-slot="Now" id="s-now"><div class="card" data-cm-part="a" data-cm-part-label="Card A">Card A</div></div>
    <div class="col" data-cm-slot="Later" id="s-later"><div class="card" data-cm-part="b" data-cm-part-label="Card B">Card B</div></div>
    <div class="loose" id="loose"></div>
  </div>
  <div class="board cm-skip" data-cm-widget="other" id="board3">
    <div class="col" data-cm-slot="Todo" id="o-todo"><div class="card" data-cm-part="a" data-cm-part-label="Other A">Other A</div></div>
    <div class="col" data-cm-slot="Done" id="o-done"></div>
  </div>`;

async function open2(page) {
  await installClipboardCapture(page);
  const { html } = stageContent(BOARD2, { key: "cmh-statediff2" });
  await page.goto(fileUrl(html));
  await ready(page);
  return html;
}
async function move(page, part, widget, targetId) {
  await page.evaluate(({ part, widget, targetId }) => {
    const card = document.querySelector('[data-cm-widget="' + widget + '"] [data-cm-part="' + part + '"]');
    document.getElementById(targetId).appendChild(card);
  }, { part, widget, targetId });
  await waitForWidgetMutationFrame(page);
}

test("moving a part out of any slot reports a move to (no slot)", async ({ page }) => {
  await open2(page);
  await move(page, "a", "triage", "loose");
  await expect(page.locator(".cm-card-state")).toContainText("(no slot)");
  await page.click("#btnCopyAll");
  const bundle = await page.evaluate(() => window.__copied.at(-1));
  expect(bundle).toContain('"Card A" moved from Now to (no slot)');
});

test("removing a part after load reports it as removed", async ({ page }) => {
  await open2(page);
  await page.evaluate(() => document.querySelector('[data-cm-widget="triage"] [data-cm-part="b"]').remove());
  await waitForWidgetMutationFrame(page);
  await expect(page.locator(".cm-card-state")).toContainText("(removed)");
});

test("adding a part after load is not reported as a change", async ({ page }) => {
  await open2(page);
  await page.evaluate(() => {
    const d = document.createElement("div");
    d.className = "card"; d.setAttribute("data-cm-part", "z"); d.setAttribute("data-cm-part-label", "New");
    d.textContent = "New"; document.getElementById("s-later").appendChild(d);
  });
  await waitForWidgetMutationFrame(page);
  await expect(page.locator(".cm-card-state")).toHaveCount(0);
});

test("same part id in two widgets is tracked independently", async ({ page }) => {
  await open2(page);
  await move(page, "a", "other", "o-done"); // move 'a' in the 'other' widget only
  await expect(page.locator(".cm-card-state")).toContainText("Other A");
  await expect(page.locator(".cm-card-state")).not.toContainText("Card A");
});

test("the sidebar auto-opens once on the first layout change, not again after close", async ({ page }) => {
  await open2(page);
  await expect(page.locator("body")).not.toHaveClass(/sidebar-open/);
  await move(page, "a", "triage", "s-later");
  await expect(page.locator("body")).toHaveClass(/sidebar-open/);
  await page.click("#btnCloseSidebar");
  await expect(page.locator("body")).not.toHaveClass(/sidebar-open/);
  await move(page, "b", "triage", "s-now"); // another change, but not a 0->>0 transition
  await expect(page.locator("body")).not.toHaveClass(/sidebar-open/);
});

test("the state card is not a comment: no id, no actions, count stays 0, not in HANDLED_IDS", async ({ page }) => {
  await open2(page);
  await move(page, "a", "triage", "s-later");
  const card = page.locator(".cm-card-state");
  await expect(card).toHaveCount(1);
  expect(await card.getAttribute("data-cid")).toBeNull();
  await expect(card.locator("[data-act]")).toHaveCount(0);
  await expect(page.locator("#sidebarCount")).toHaveText("0");
  await page.click("#btnCopyAll");
  const bundle = await page.evaluate(() => window.__copied.at(-1));
  expect(bundle).toContain("HANDLED_IDS_JSON: []");
});
