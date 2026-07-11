// Commentable widgets and SVG nodes (generic data-cm-widget / data-cm-part opt-in).
import { test, expect } from "@playwright/test";
import { fileUrl, ready, installClipboardCapture, stageContent, copiedBundle, storedComments } from "./helpers.js";

const WIDGET_CONTENT = `
  <h1>Widget test</h1>
  <div class="board cm-skip" data-cm-widget="triage" id="board">
    <div class="col" data-cm-slot="Now">
      <div class="card" data-cm-part="a" data-cm-part-label="Card A">Card A</div>
      <div class="card" data-cm-part="b" data-cm-part-label="Card B">Card B</div>
    </div>
    <div class="col" data-cm-slot="Later">
      <div class="card" data-cm-part="c" data-cm-part-label="Card C">Card C</div>
    </div>
  </div>
  <figure>
    <svg viewBox="0 0 120 40" data-cm-widget="diagram">
      <g data-cm-part="n1" data-cm-part-label="Node 1"><rect x="2" y="2" width="50" height="34" fill="none" stroke="currentColor"></rect></g>
    </svg>
    <figcaption>An inline SVG figure.</figcaption>
  </figure>
  <p>Prose after the board.</p>`;

async function open(page) {
  await installClipboardCapture(page);
  const { html } = stageContent(WIDGET_CONTENT, { key: "cmh-widget-test" });
  await page.goto(fileUrl(html));
  await ready(page);
  return html;
}

async function commentOnPart(page, partSelector, note) {
  await page.hover(partSelector);
  await expect(page.locator("#widgetAddBtn")).toBeVisible();
  await page.click("#widgetAddBtn");
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toHaveCount(0);
}

test("parts are marked commentable and focusable", async ({ page }) => {
  await open(page);
  const info = await page.$$eval("[data-cm-part]", (els) => els.map((e) => ({
    part: e.getAttribute("data-cm-part"),
    commentable: e.classList.contains("cm-part-commentable"),
    tabindex: e.getAttribute("tabindex"),
  })));
  expect(info.length).toBe(4);
  expect(info.every((i) => i.commentable && i.tabindex === "0")).toBe(true);
});

test("hovering a card shows the widget Add Comment button and creates a widget comment", async ({ page }) => {
  await open(page);
  await commentOnPart(page, '[data-cm-part="a"]', "Reconsider Card A priority");
  const stored = await storedComments(page);
  expect(stored.length).toBe(1);
  const c = stored[0];
  expect(c.anchorType).toBe("widget");
  expect(c.widget).toBe("triage");
  expect(c.part).toBe("a");
  expect(c.partLabel).toBe("Card A");
  expect(c.slot).toBe("Now");
  // The part carries the highlight class + its data-cid.
  const hl = await page.$eval('[data-cm-part="a"]', (e) => ({ hl: e.classList.contains("cm-part-hl"), cid: e.getAttribute("data-cid") }));
  expect(hl.hl).toBe(true);
  expect(hl.cid).toBe(c.id);
});

test("an SVG <g> node is commentable via the same mechanism", async ({ page }) => {
  await open(page);
  await page.focus('[data-cm-part="n1"]');
  await page.keyboard.press("Enter");
  const composer = page.locator(".cm-composer").last();
  await expect(composer).toBeVisible();
  await composer.locator("textarea").fill("This node needs a label");
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toHaveCount(0);
  const stored = await storedComments(page);
  expect(stored[0].widget).toBe("diagram");
  expect(stored[0].part).toBe("n1");
  expect(stored[0].partLabel).toBe("Node 1");
});

test("keyboard: focus a part and press Enter to open the composer", async ({ page }) => {
  await open(page);
  await page.focus('[data-cm-part="b"]');
  await page.keyboard.press("Enter");
  const composer = page.locator(".cm-composer").last();
  await expect(composer).toBeVisible();
  await composer.locator("textarea").fill("keyboard comment");
  await composer.locator('[data-act="save"]').click();
  const stored = await storedComments(page);
  expect(stored[0].part).toBe("b");
});

test("the sidebar card shows the widget/part pinpoint", async ({ page }) => {
  await open(page);
  await commentOnPart(page, '[data-cm-part="a"]', "note");
  const card = page.locator(".cm-card").first();
  await expect(card).toContainText("triage");
  await expect(card).toContainText("Card A");
  await expect(card.locator('[data-act="jump"]')).toHaveCount(1);
});

test("Copy all includes the widget anchor line", async ({ page }) => {
  await open(page);
  await commentOnPart(page, '[data-cm-part="c"]', "widget bundle note");
  await page.click("#btnCopyAll");
  const bundle = await copiedBundle(page);
  expect(bundle).toContain("(widget)");
  expect(bundle).toContain('Anchor: widget "triage", part "Card C"');
  expect(bundle).toContain("widget bundle note");
});

test("widget highlight survives reload", async ({ page }) => {
  await open(page);
  await commentOnPart(page, '[data-cm-part="a"]', "persist me");
  await page.reload();
  await ready(page);
  const hl = await page.$eval('[data-cm-part="a"]', (e) => e.classList.contains("cm-part-hl"));
  expect(hl).toBe(true);
});

test("deleting a widget comment clears the highlight", async ({ page }) => {
  await open(page);
  await commentOnPart(page, '[data-cm-part="a"]', "to be deleted");
  page.on("dialog", (d) => d.accept());
  await page.locator('.cm-card [data-act="del"]').first().click();
  await expect(page.locator(".cm-card")).toHaveCount(0);
  const hl = await page.$eval('[data-cm-part="a"]', (e) => e.classList.contains("cm-part-hl"));
  expect(hl).toBe(false);
});

const WIDGET2 = `
  <h1>W2</h1>
  <div class="cm-skip" data-cm-widget="w2">
    <div data-cm-part="only">Bare label from text</div>
    <div data-cm-part="dup" data-cm-part-label="First">First</div>
    <div data-cm-part="dup" data-cm-part-label="Dup">Dup ignored</div>
    <div data-cm-part="">Empty id ignored</div>
  </div>`;

async function open2(page) {
  await installClipboardCapture(page);
  const { html } = stageContent(WIDGET2, { key: "cmh-widget2" });
  await page.goto(fileUrl(html));
  await ready(page);
}

test("Space key on a focused part opens the composer", async ({ page }) => {
  await open(page);
  await page.focus('[data-cm-part="b"]');
  await page.keyboard.press(" ");
  const composer = page.locator(".cm-composer").last();
  await expect(composer).toBeVisible();
  await composer.locator("textarea").fill("space works");
  await composer.locator('[data-act="save"]').click();
  const stored = await storedComments(page);
  expect(stored[0].part).toBe("b");
});

test("a part with no data-cm-part-label falls back to its text", async ({ page }) => {
  await open2(page);
  await page.focus('[data-cm-part="only"]');
  await page.keyboard.press("Enter");
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("n");
  await composer.locator('[data-act="save"]').click();
  const stored = await storedComments(page);
  expect(stored[0].partLabel).toBe("Bare label from text");
});

test("duplicate and empty data-cm-part ids are ignored", async ({ page }) => {
  await open2(page);
  // Only the first "dup" and the "only" part are commentable; the duplicate and the empty id are skipped.
  const commentable = await page.$$eval("[data-cm-part].cm-part-commentable", (els) => els.map((e) => e.getAttribute("data-cm-part")));
  expect(commentable.sort()).toEqual(["dup", "only"]);
});

test("two comments on one part: deleting the first keeps the second highlighted", async ({ page }) => {
  await open(page);
  await commentOnPart(page, '[data-cm-part="a"]', "first");
  await commentOnPart(page, '[data-cm-part="a"]', "second");
  const stored = await storedComments(page);
  expect(stored.length).toBe(2);
  const secondId = stored[1].id;
  page.on("dialog", (d) => d.accept());
  await page.locator('.cm-card [data-act="del"]').first().click();
  const part = page.locator('[data-cm-part="a"]');
  await expect(part).toHaveClass(/cm-part-hl/);
  expect((await part.getAttribute("data-cids")).split(/\s+/)).toContain(secondId);
});

test("a part node replaced in the same slot is re-wired for commenting", async ({ page }) => {
  await open(page);
  await page.evaluate(() => {
    const old = document.querySelector('[data-cm-part="a"]');
    const fresh = document.createElement("div");
    fresh.className = "card";
    fresh.setAttribute("data-cm-part", "a");
    fresh.setAttribute("data-cm-part-label", "Card A");
    fresh.textContent = "Card A (new node)";
    old.replaceWith(fresh);
  });
  await page.waitForTimeout(90);
  const part = page.locator('[data-cm-part="a"]');
  await expect(part).toHaveClass(/cm-part-commentable/);
  await part.hover();
  await expect(page.locator("#widgetAddBtn")).toBeVisible();
});
