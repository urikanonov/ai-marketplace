// Auto-open panel on comment: a reviewer preference in the panel header More menu, with a
// cross-document default and a per-document override. With it off, saving a comment still stores
// and highlights the comment - only the panel stays where the reviewer left it.
import { test, expect } from "@playwright/test";
import {
  fileUrl, ready, stageContent, stageDeck, addTextComment, openSidebarMoreMenu,
} from "./helpers.js";

const DOC = `
  <h1>Auto-open preference</h1>
  <p id="one">The first paragraph carries the text a reviewer selects.</p>
  <p id="two">The second paragraph carries another selectable run of text.</p>`;

const GLOBAL_KEY = "commentable-html::autoOpenPanel";

const DEFAULT_ROW = "#btnAutoOpenPanel";
const OVERRIDE_ROW = "#btnAutoOpenPanelOverride";

async function open(page, key, { content = DOC } = {}) {
  const staged = stageContent(content, { key });
  await page.goto(fileUrl(staged.html));
  await ready(page);
  return staged;
}

const sidebarOpen = (page) => page.evaluate(() => document.body.classList.contains("sidebar-open"));
const globalPref = (page) => page.evaluate((k) => localStorage.getItem(k), GLOBAL_KEY);
const docPref = (page) => page.evaluate(() =>
  localStorage.getItem(document.getElementById("commentRoot").dataset.commentKey + "::autoOpenPanel"));

async function showSidebar(page) {
  if (!(await sidebarOpen(page))) await page.click("#btnToggleSidebar");
  await expect(page.locator("#sidebar")).toBeVisible();
}
async function hideSidebar(page) {
  if (await sidebarOpen(page)) await page.click("#btnCloseSidebar");
  expect(await sidebarOpen(page)).toBe(false);
}
// Open the More menu and return it (the panel must be open to reach the header ribbon).
async function openPrefs(page) {
  await showSidebar(page);
  await openSidebarMoreMenu(page);
  return page.locator("#sidebarMoreMenu");
}

test("CMH-MENU-PREF-01: the More menu carries a Preferences group with a default row and a nested override row", async ({ page }) => {
  await open(page, "cmh-pref-01");
  const menu = await openPrefs(page);
  await expect(menu.locator(".cm-menu-group", { hasText: "Preferences" })).toHaveCount(1);
  const def = menu.locator(DEFAULT_ROW);
  const over = menu.locator(OVERRIDE_ROW);
  await expect(def).toBeVisible();
  await expect(over).toBeVisible();
  await expect(def).toHaveAttribute("role", "menuitemcheckbox");
  await expect(over).toHaveAttribute("role", "menuitemcheckbox");
  // Nothing stored: the default is ON and the document inherits it.
  await expect(def).toHaveAttribute("aria-checked", "true");
  await expect(over).toHaveAttribute("aria-checked", "false");
  await expect(def).toHaveText(/Auto-open panel on comment/);
  await expect(over).toHaveText(/Override for this document/);
  // The override reads as nested UNDER the default: it follows it and is indented.
  const boxes = await page.evaluate(([a, b]) => {
    const d = document.querySelector(a), o = document.querySelector(b);
    return {
      after: !!(d.compareDocumentPosition(o) & Node.DOCUMENT_POSITION_FOLLOWING),
      dLeft: d.getBoundingClientRect().left,
      oLeft: o.querySelector(".cm-menu-check-label").getBoundingClientRect().left,
      dLabelLeft: d.querySelector(".cm-menu-check-label").getBoundingClientRect().left,
    };
  }, [DEFAULT_ROW, OVERRIDE_ROW]);
  expect(boxes.after).toBe(true);
  expect(boxes.oLeft).toBeGreaterThan(boxes.dLabelLeft);
  // Toggling a preference keeps the menu open, so both scopes can be set in one visit.
  await def.click();
  await expect(menu).toBeVisible();
  await expect(def).toHaveAttribute("aria-checked", "false");
});

test("CMH-MENU-PREF-02: with the default off a saved comment is stored and highlighted but the panel stays put", async ({ page }) => {
  await open(page, "cmh-pref-02");
  // On (the default when nothing is stored): saving opens the panel, exactly as before.
  await addTextComment(page, "#one", "first note");
  expect(await sidebarOpen(page)).toBe(true);

  const menu = await openPrefs(page);
  await menu.locator(DEFAULT_ROW).click();
  await expect(menu.locator(DEFAULT_ROW)).toHaveAttribute("aria-checked", "false");
  expect(await globalPref(page)).toBe("0");
  await hideSidebar(page);

  await addTextComment(page, "#two", "second note");
  expect(await sidebarOpen(page)).toBe(false);
  expect(await page.locator("mark.cm-hl").count()).toBe(2);
  expect(await page.evaluate(() => document.querySelectorAll("#commentList .cm-card").length)).toBe(2);
});

test("CMH-MENU-PREF-03: the default persists across a reload and applies to every document", async ({ page }) => {
  const staged = await open(page, "cmh-pref-03a");
  const menu = await openPrefs(page);
  await menu.locator(DEFAULT_ROW).click();
  await hideSidebar(page);

  await page.goto(fileUrl(staged.html));
  await ready(page);
  const reopened = await openPrefs(page);
  await expect(reopened.locator(DEFAULT_ROW)).toHaveAttribute("aria-checked", "false");
  await hideSidebar(page);
  await addTextComment(page, "#one", "after reload");
  expect(await sidebarOpen(page)).toBe(false);

  // A DIFFERENT document in the same browser inherits the cross-document default.
  const other = stageContent(DOC, { key: "cmh-pref-03b" });
  await page.goto(fileUrl(other.html));
  await ready(page);
  await addTextComment(page, "#one", "other document");
  expect(await sidebarOpen(page)).toBe(false);
});

test("CMH-MENU-PREF-04: the override pins a per-document value and unchecking re-inherits the default", async ({ page }) => {
  const staged = await open(page, "cmh-pref-04a");
  const menu = await openPrefs(page);
  const def = menu.locator(DEFAULT_ROW);
  const over = menu.locator(OVERRIDE_ROW);

  // Default is ON; the override pins this document to the value that differs from it.
  await over.click();
  await expect(over).toHaveAttribute("aria-checked", "true");
  await expect(over).toHaveText(/Override for this document: Off/);
  // The default row keeps showing the untouched default - the two scopes never look the same.
  await expect(def).toHaveAttribute("aria-checked", "true");
  expect(await globalPref(page)).toBe(null);
  expect(await docPref(page)).toBe("0");

  await hideSidebar(page);
  await addTextComment(page, "#one", "pinned off here");
  expect(await sidebarOpen(page)).toBe(false);

  // Another document still follows the (unchanged) default.
  const other = stageContent(DOC, { key: "cmh-pref-04b" });
  await page.goto(fileUrl(other.html));
  await ready(page);
  await addTextComment(page, "#one", "still follows the default");
  expect(await sidebarOpen(page)).toBe(true);

  // Back on the pinned document: the override survives a reload, and unchecking drops the key.
  await page.goto(fileUrl(staged.html));
  await ready(page);
  const back = await openPrefs(page);
  await expect(back.locator(OVERRIDE_ROW)).toHaveAttribute("aria-checked", "true");
  await back.locator(OVERRIDE_ROW).click();
  await expect(back.locator(OVERRIDE_ROW)).toHaveAttribute("aria-checked", "false");
  await expect(back.locator(OVERRIDE_ROW)).toHaveText(/^Override for this document$/);
  expect(await docPref(page)).toBe(null);
  await hideSidebar(page);
  await addTextComment(page, "#two", "re-inherited");
  expect(await sidebarOpen(page)).toBe(true);
});

test("CMH-MENU-PREF-05: both rows are keyboard operable and take part in the menu roving focus", async ({ page }) => {
  await open(page, "cmh-pref-05");
  const menu = await openPrefs(page);
  const def = menu.locator(DEFAULT_ROW);
  const over = menu.locator(OVERRIDE_ROW);

  await def.focus();
  await page.keyboard.press("Enter");
  await expect(def).toHaveAttribute("aria-checked", "false");
  await expect(menu).toBeVisible();
  await page.keyboard.press(" ");
  await expect(def).toHaveAttribute("aria-checked", "true");

  // Roving focus: Down/Up walk the menu's items, Home/End jump to the ends.
  await def.focus();
  await page.keyboard.press("ArrowDown");
  await expect(over).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(def).toBeFocused();
  await page.keyboard.press("Home");
  await expect(def).toBeFocused();
  await page.keyboard.press("End");
  await expect(menu.locator("#btnClearAll")).toBeFocused();
  // Escape still closes the menu and returns focus to its trigger.
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(page.locator("#btnMoreMenu")).toBeFocused();
});

test("CMH-MENU-PREF-06: a browser that throws on storage degrades to the default instead of failing", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.addInitScript(() => {
    const boom = () => { throw new DOMException("denied", "SecurityError"); };
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get: () => ({ getItem: boom, setItem: boom, removeItem: boom, key: boom, clear: boom, length: 0 }),
    });
  });
  await open(page, "cmh-pref-06");
  const menu = await openPrefs(page);
  await expect(menu.locator(DEFAULT_ROW)).toHaveAttribute("aria-checked", "true");
  await expect(menu.locator(OVERRIDE_ROW)).toHaveAttribute("aria-checked", "false");
  await menu.locator(DEFAULT_ROW).click();
  await menu.locator(OVERRIDE_ROW).click();
  await hideSidebar(page);
  // Nothing could be stored, so the effective value stays the ON default and the panel opens.
  await addTextComment(page, "#one", "private mode note");
  expect(await sidebarOpen(page)).toBe(true);
  expect(errors).toEqual([]);
});

test("CMH-MENU-PREF-07: the deck runtime honors the preference when a slide comment is saved", async ({ page }) => {
  const slides = '<section class="slide" data-slide-id="s1"><h2>One</h2><p id="one">Slide text to comment on.</p></section>'
    + '<section class="slide" data-slide-id="s2"><h2>Two</h2><p>Second slide.</p></section>';
  const deck = stageDeck(slides, { key: "cmh-pref-deck" });
  await page.addInitScript((k) => {
    try { localStorage.setItem(k, "0"); } catch (e) { /* ignore */ }
  }, GLOBAL_KEY);
  await page.goto(fileUrl(deck.html));
  await ready(page);
  expect(await page.evaluate(() => window.__cmhDeck.deckMode())).toBe("closed");
  await addTextComment(page, ".slide.active p", "deck note with auto-open off");
  expect(await sidebarOpen(page)).toBe(false);
  expect(await page.evaluate(() => window.__cmhDeck.deckMode())).toBe("closed");
  expect(await page.locator("mark.cm-hl").count()).toBe(1);
});
