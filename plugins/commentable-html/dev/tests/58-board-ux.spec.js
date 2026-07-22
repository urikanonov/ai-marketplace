// Triage-board UX: caption commentability near a cm-skip chart, content-aligned footer,
// and the runtime board Reset / per-widget state cards with jump + Reset + first-change time.
import { test, expect } from "@playwright/test";
import { fileUrl, ready, installClipboardCapture, stageContent, openInline } from "./helpers.js";

async function waitForWidgetMutationFrame(page) {
  await page.evaluate(() => new Promise((resolve) => {
    if (typeof requestAnimationFrame !== "function") { resolve(); return; }
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  }));
}

// ---- Item 6: chart caption stays commentable when the pointer lifts over the chart ----

const CHART = `
  <h1>Chart</h1>
  <figure class="chart" aria-labelledby="cap">
    <div class="chart-wrap cm-skip" style="position: relative; height: 360px;">
      <canvas id="cap-canvas" style="width: 100%; height: 100%;"></canvas>
    </div>
    <figcaption id="cap">Open incidents by queue and severity.</figcaption>
  </figure>`;

test("selecting a chart caption offers Add Comment even when the release lands on the adjacent cm-skip chart (CMH-SEL-01)", async ({ page }) => {
  const { html } = stageContent(CHART, { key: "cmh-caption-sel" });
  await page.goto(fileUrl(html));
  await ready(page);
  await page.evaluate(() => {
    const cap = document.getElementById("cap");
    const range = document.createRange();
    range.selectNodeContents(cap);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    // The pointer releases over the tall cm-skip canvas that sits above the caption.
    const canvas = document.getElementById("cap-canvas");
    canvas.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, button: 0, clientX: 60, clientY: 60 }));
  });
  await expect(page.locator("#contextMenu")).toBeVisible();
  await expect(page.locator("#menuComment")).toBeVisible();
});

// ---- Item 7: the runtime footer aligns to the content column in both panel states ----

function measure(page, sel) {
  return page.locator(sel).evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { left: r.left, right: r.right, width: r.width };
  });
}

test("the runtime footer aligns to the content column in normal and sidebar-open states (CMH-FOOT-03)", async ({ page }) => {
  await page.setViewportSize({ width: 1800, height: 1000 });
  const { html } = stageContent('<section id="probe"><h2>Probe</h2><p>Body text goes here.</p></section>', { key: "cmh-footer-align" });
  await page.goto(fileUrl(html));
  await ready(page);

  // Normal (panel closed): the footer box tracks the #commentRoot content column.
  await expect(page.locator("body")).not.toHaveClass(/sidebar-open/);
  let root = await measure(page, "#commentRoot");
  let footer = await measure(page, "#cmFooter");
  expect(Math.abs(footer.left - root.left)).toBeLessThanOrEqual(2);
  expect(Math.abs(footer.right - root.right)).toBeLessThanOrEqual(2);

  // Sidebar-open: the footer follows the shifted content column, not the full page width.
  await page.click("#btnToggleSidebar");
  await expect(page.locator("body")).toHaveClass(/sidebar-open/);
  await waitForWidgetMutationFrame(page);
  root = await measure(page, "#commentRoot");
  footer = await measure(page, "#cmFooter");
  expect(Math.abs(footer.left - root.left)).toBeLessThanOrEqual(2);
  expect(Math.abs(footer.right - root.right)).toBeLessThanOrEqual(2);
});

test("the runtime footer aligns to the content column when the side TOC pane is present and the sidebar is closed (CMH-FOOT-03)", async ({ page }) => {
  // TOC-on + sidebar-closed at a width where the pane's left inset shrinks the .app shell below
  // its 1480px max: the footer must inset to match the .app content box, not span the full body.
  await page.setViewportSize({ width: 1750, height: 1000 });
  await openInline(page);
  await expect(page.locator("#cmSideToc")).toBeVisible();
  await expect(page.locator("body")).toHaveClass(/cm-side-toc-on/);
  await expect(page.locator("body")).not.toHaveClass(/cm-side-toc-collapsed/);
  await expect(page.locator("body")).not.toHaveClass(/sidebar-open/);

  const root = await measure(page, "#commentRoot");
  const footer = await measure(page, "#cmFooter");
  expect(Math.abs(footer.left - root.left)).toBeLessThanOrEqual(2);
  expect(Math.abs(footer.right - root.right)).toBeLessThanOrEqual(2);
});

test("wide screens give the sidebar-open content column extra width (CMH-CONTENT-18)", async ({ page }) => {
  // On a wide monitor the sidebar-open recipe targets a 1600px content column (up from 1300px),
  // so at 2200px with a 400px sidebar the body fills clearly more than the old cap.
  await page.setViewportSize({ width: 2200, height: 1000 });
  const { html } = stageContent('<section id="probe"><h2>Probe</h2><p>Body text goes here.</p></section>', { key: "cmh-wide-content" });
  await page.goto(fileUrl(html));
  await ready(page);

  await page.click("#btnToggleSidebar");
  await expect(page.locator("body")).toHaveClass(/sidebar-open/);
  await waitForWidgetMutationFrame(page);

  const root = await measure(page, "#commentRoot");
  // The old 1300px target yielded a ~1300px column here; the widened target lands near 1600px.
  expect(root.width).toBeGreaterThan(1450);
});

test("the widened content column reaches its full target with the side TOC pane present (CMH-CONTENT-18)", async ({ page }) => {
  // The user's three-column view: nav pane (side TOC) | content | comments sidebar. The centered
  // gutter must subtract the nav pane's width, or the pane's inset squeezes the column (~1296px).
  await page.setViewportSize({ width: 2400, height: 1000 });
  await openInline(page);
  await expect(page.locator("#cmSideToc")).toBeVisible();
  await expect(page.locator("body")).toHaveClass(/cm-side-toc-on/);
  await expect(page.locator("body")).not.toHaveClass(/cm-side-toc-collapsed/);

  if (!(await page.evaluate(() => document.body.classList.contains("sidebar-open")))) {
    await page.click("#btnToggleSidebar");
  }
  await expect(page.locator("body")).toHaveClass(/sidebar-open/);
  await waitForWidgetMutationFrame(page);

  const root = await measure(page, "#commentRoot");
  // With the nav-pane inset subtracted the column reaches ~1600px; before the fix it was ~1296px.
  expect(root.width).toBeGreaterThan(1450);
  // The footer mirrors the same TOC-aware recipe, so it stays flush with the content column.
  const footer = await measure(page, "#cmFooter");
  expect(Math.abs(footer.left - root.left)).toBeLessThanOrEqual(2);
  expect(Math.abs(footer.right - root.right)).toBeLessThanOrEqual(2);
});

// ---- Items 1/2/3: board Reset button, per-widget state cards, meta parity ----

const BOARD = `
  <h1>Triage</h1>
  <div class="board cm-skip" data-cm-widget="triage" data-cm-draggable aria-label="Triage board" id="board">
    <div class="col" data-cm-slot="Now" id="now">
      <div class="card" data-cm-part="a" data-cm-part-label="Card A">Card A</div>
    </div>
    <div class="col" data-cm-slot="Later" id="later">
      <div class="card" data-cm-part="b" data-cm-part-label="Card B">Card B</div>
    </div>
  </div>`;

const TWO_BOARDS = `
  <h1>Two boards</h1>
  <div class="board cm-skip" data-cm-widget="triage" data-cm-draggable aria-label="Triage board" id="board1">
    <div class="col" data-cm-slot="Now" id="now1"><div class="card" data-cm-part="a" data-cm-part-label="Card A">Card A</div></div>
    <div class="col" data-cm-slot="Later" id="later1"><div class="card" data-cm-part="b" data-cm-part-label="Card B">Card B</div></div>
  </div>
  <div class="board cm-skip" data-cm-widget="other" data-cm-draggable aria-label="Other board" id="board2">
    <div class="col" data-cm-slot="Todo" id="todo2"><div class="card" data-cm-part="x" data-cm-part-label="Card X">Card X</div></div>
    <div class="col" data-cm-slot="Done" id="done2"></div>
  </div>`;

const STATIC_BOARD = `
  <h1>Static</h1>
  <div class="board cm-skip" data-cm-widget="frozen" aria-label="Frozen board" id="frozen">
    <div class="col" data-cm-slot="Now" id="fnow"><div class="card" data-cm-part="a" data-cm-part-label="Card A">Card A</div></div>
    <div class="col" data-cm-slot="Later" id="flater"></div>
  </div>`;

const SLOT_DRAGGABLE_TWO_BOARDS = `
  <h1>Slot draggable boards</h1>
  <div class="board cm-skip" data-cm-widget="slot-board" aria-label="Slot board" id="slotBoard">
    <div class="col" data-cm-slot="Open" data-cm-draggable id="slotOpen">
      <div class="card" data-cm-part="alpha" data-cm-part-label="Alpha" id="cardAlpha">Alpha</div>
      <div class="divider" id="openDivider">Divider</div>
      <div class="card" data-cm-part="beta" data-cm-part-label="Beta" id="cardBeta">Beta</div>
    </div>
    <div class="col" data-cm-slot="Review" data-cm-draggable id="slotReview"></div>
    <div class="col" data-cm-slot="Done" data-cm-draggable id="slotDone"></div>
  </div>
  <div class="board cm-skip" data-cm-widget="untouched" data-cm-draggable aria-label="Untouched board" id="untouchedBoard">
    <div class="col" data-cm-slot="Todo" id="untouchedTodo">
      <div class="card" data-cm-part="first" data-cm-part-label="First" id="untouchedFirst">First</div>
      <div class="divider" id="untouchedDivider">Divider</div>
      <div class="card" data-cm-part="second" data-cm-part-label="Second" id="untouchedSecond">Second</div>
    </div>
    <div class="col" data-cm-slot="Done" id="untouchedDone"></div>
  </div>`;

async function openContent(page, content, key) {
  await installClipboardCapture(page);
  const { html } = stageContent(content, { key });
  await page.goto(fileUrl(html));
  await ready(page);
}

async function move(page, part, widget, targetId) {
  await page.evaluate(({ part, widget, targetId }) => {
    const card = document.querySelector('[data-cm-widget="' + widget + '"] [data-cm-part="' + part + '"]');
    document.getElementById(targetId).appendChild(card);
  }, { part, widget, targetId });
  await waitForWidgetMutationFrame(page);
}

function childElementOrder(page, selector) {
  return page.locator(selector).evaluate((el) => Array.from(el.children).map((child) => child.id).join("|"));
}

test("a moved draggable board grows a Reset moves button that restores it (CMH-BOARD-01)", async ({ page }) => {
  await openContent(page, BOARD, "cmh-board-reset");
  await expect(page.locator(".cm-widget-reset")).toHaveCount(0);

  await move(page, "a", "triage", "later");
  const reset = page.locator("#board .cm-widget-reset");
  await expect(reset).toHaveCount(1);
  await expect(reset).toHaveText("Reset moves");
  await expect(reset).toHaveAttribute("title", "Return cards to their original positions");
  await expect(page.locator('#later [data-cm-part="a"]')).toHaveCount(1);

  await reset.click();
  await waitForWidgetMutationFrame(page);
  await expect(page.locator('#now [data-cm-part="a"]')).toHaveCount(1);
  await expect(page.locator(".cm-widget-reset")).toHaveCount(0);
  await expect(page.locator(".cm-card-state")).toHaveCount(0);
  await expect(page.locator("#cmTypeBadge")).toHaveText("Portable");
});

test("the Reset moves button is only for draggable boards, not static widgets (CMH-BOARD-01)", async ({ page }) => {
  await openContent(page, STATIC_BOARD, "cmh-board-static");
  await move(page, "a", "frozen", "flater");
  await expect(page.locator(".cm-card-state")).toHaveCount(1);
  await expect(page.locator(".cm-widget-reset")).toHaveCount(0);
});

test("each changed board gets its own state card with jump and Reset changes (CMH-BOARD-02)", async ({ page }) => {
  await openContent(page, TWO_BOARDS, "cmh-board-two");
  await move(page, "a", "triage", "later1");
  await move(page, "x", "other", "done2");

  const cards = page.locator(".cm-card-state");
  await expect(cards).toHaveCount(2);
  await expect(page.locator('.cm-card-state[data-cm-widget-name="triage"]')).toHaveCount(1);
  await expect(page.locator('.cm-card-state[data-cm-widget-name="other"]')).toHaveCount(1);
  await expect(page.locator('.cm-card-state [data-act="state-jump"]')).toHaveCount(2);
  await expect(page.locator('.cm-card-state [data-act="state-reset"]').first()).toHaveText("Reset changes");

  // Reset only the triage board via its own card; the other board's change survives.
  await page.locator('.cm-card-state[data-cm-widget-name="triage"] [data-act="state-reset"]').click();
  await waitForWidgetMutationFrame(page);
  await expect(page.locator(".cm-card-state")).toHaveCount(1);
  await expect(page.locator('.cm-card-state[data-cm-widget-name="other"]')).toHaveCount(1);
  await expect(page.locator('#now1 [data-cm-part="a"]')).toHaveCount(1);
});

test("a state card jump focuses and flashes its own board (CMH-BOARD-02)", async ({ page }) => {
  await openContent(page, BOARD, "cmh-board-jump");
  await move(page, "a", "triage", "later");
  await page.locator('.cm-card-state[data-cm-widget-name="triage"] [data-act="state-jump"]').click();
  await expect(page.locator("#board")).toHaveClass(/cm-widget-flash/);
});

test("a state card carries an in:<board> title, jump, and a first-change timestamp (CMH-BOARD-03)", async ({ page }) => {
  await openContent(page, BOARD, "cmh-board-meta");
  await move(page, "a", "triage", "later");
  const card = page.locator(".cm-card-state");
  await expect(card).toHaveCount(1);
  // The title uses the board's aria-label, matching a regular comment card's "in:" line.
  await expect(card.locator(".section")).toContainText("Triage board");
  await expect(card.locator('[data-act="state-jump"]')).toHaveCount(1);
  // The meta line shows the first-change time formatted by formatTime (contains a 4-digit year).
  const metaText = (await card.locator(".meta span").first().innerText()).trim();
  expect(metaText).toMatch(/\d{4}/);
});

test("Clear restores draggable board moves to the authored baseline (CMH-BOARD-04)", async ({ page }) => {
  await openContent(page, BOARD, "cmh-board-clear");
  await move(page, "a", "triage", "later");
  await expect(page.locator('#later [data-cm-part="a"]')).toHaveCount(1);
  await expect(page.locator(".cm-card-state")).toHaveCount(1);

  await page.click("#btnClearAll");
  await page.locator(".cm-modal .danger").click();
  await waitForWidgetMutationFrame(page);
  await expect(page.locator('#now [data-cm-part="a"]')).toHaveCount(1);
  await expect(page.locator(".cm-card-state")).toHaveCount(0);
  await expect(page.locator("#cmTypeBadge")).toHaveText("Portable");
});

test("Clear restores slot-level draggable boards in exact order without touching clean boards (CMH-BOARD-05)", async ({ page }) => {
  await openContent(page, SLOT_DRAGGABLE_TWO_BOARDS, "cmh-board-slot-clear-order");
  const initialOpen = await childElementOrder(page, "#slotOpen");
  const initialReview = await childElementOrder(page, "#slotReview");
  const initialDone = await childElementOrder(page, "#slotDone");
  const untouchedInitial = await childElementOrder(page, "#untouchedTodo");

  await move(page, "alpha", "slot-board", "slotReview");
  await move(page, "beta", "slot-board", "slotDone");
  await expect(page.locator('#slotReview [data-cm-part="alpha"]')).toHaveCount(1);
  await expect(page.locator('#slotDone [data-cm-part="beta"]')).toHaveCount(1);
  await expect(page.locator(".cm-card-state")).toHaveCount(1);

  await page.click("#btnClearAll");
  await page.locator(".cm-modal .danger").click();
  await waitForWidgetMutationFrame(page);
  await expect.poll(() => childElementOrder(page, "#slotOpen")).toBe(initialOpen);
  await expect.poll(() => childElementOrder(page, "#slotReview")).toBe(initialReview);
  await expect.poll(() => childElementOrder(page, "#slotDone")).toBe(initialDone);
  await expect.poll(() => childElementOrder(page, "#untouchedTodo")).toBe(untouchedInitial);
  await expect(page.locator(".cm-card-state")).toHaveCount(0);
  await expect(page.locator("#cmTypeBadge")).toHaveText("Portable");
});
