// Auto-open panel on comment: a reviewer preference in the panel header More menu, with a
// cross-document default and a per-document override. With it off, saving a comment still stores
// and highlights the comment - only the panel stays where the reviewer left it.
import { test, expect } from "@playwright/test";
import {
  fileUrl, ready, stageContent, stageDeck, addTextComment, openSidebarMoreMenu,
  openComposerFor, openDeckModeMenu,
} from "./helpers.js";

const DOC = `
  <h1>Auto-open preference</h1>
  <p id="one">The first paragraph carries the text a reviewer selects.</p>
  <p id="two">The second paragraph carries another selectable run of text.</p>`;

const GLOBAL_KEY = "commentable-html::autoOpenPanelDefault";

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
  // The checkable rows sit in a real ARIA menu, so their aria-checked is announced as such.
  await expect(menu).toHaveAttribute("role", "menu");
  await expect(page.locator("#btnMoreMenu")).toHaveAttribute("aria-haspopup", "menu");
  await expect(menu.locator("#btnStorage")).toHaveAttribute("role", "menuitem");
  await expect(menu.locator("#btnClearAll")).toHaveAttribute("role", "menuitem");
  // Toggling EITHER preference keeps the menu open, so both scopes can be set in one visit.
  await def.click();
  await expect(menu).toBeVisible();
  await expect(def).toHaveAttribute("aria-checked", "false");
  await over.click();
  await expect(menu).toBeVisible();
  await expect(over).toHaveAttribute("aria-checked", "true");
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

test("CMH-MENU-PREF-02: with the preference off a quota failure still opens the storage manager", async ({ page }) => {
  // Turning auto-open off must not suppress the RECOVERY surface: a save that fails on quota still
  // opens the storage manager so the pending write can be retried.
  await page.addInitScript((k) => {
    try { localStorage.setItem(k, "0"); } catch (e) { /* ignore */ }
    const real = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (typeof key === "string" && key.indexOf("::z") === key.length - 3) {
        const err = new Error("quota");
        err.name = "QuotaExceededError";
        throw err;
      }
      return real.call(this, key, value);
    };
  }, GLOBAL_KEY);
  await open(page, "cmh-pref-02b");
  await addTextComment(page, "#one", "a comment that cannot be stored");
  await expect(page.locator(".cm-storage-manager")).toBeVisible();
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

test("CMH-MENU-PREF-08: with the preference off a first checklist change no longer opens the panel", async ({ page }) => {
  const doc = DOC + `
  <div class="cmh-checklist" data-cmh-checklist="release" data-cmh-checklist-label="Release readiness">
    <ul>
      <li data-cmh-item="rel" data-cmh-state="blank">Release notes</li>
      <li data-cmh-item="ops" data-cmh-state="blank">Ops sign-off</li>
    </ul>
  </div>`;
  await open(page, "cmh-pref-08c", { content: doc });
  const ctrl = (item) => page.locator(`[data-cmh-item="${item}"] .cmh-check`).first();
  await expect(ctrl("rel")).toBeVisible();
  // On (the default): the first change surfaces its card by opening the panel.
  await ctrl("rel").click();
  expect(await sidebarOpen(page)).toBe(true);

  const menu = await openPrefs(page);
  await menu.locator(DEFAULT_ROW).click();
  await hideSidebar(page);
  // Off: the change is still tracked, but the panel is left alone.
  await ctrl("ops").click();
  expect(await sidebarOpen(page)).toBe(false);
  expect(await page.evaluate(() => {
    const k = document.getElementById("commentRoot").dataset.commentKey + "::cl";
    return localStorage.getItem(k);
  })).toBeTruthy();
});

test("CMH-MENU-PREF-06: a refused preference write reports itself instead of silently snapping back", async ({ page }) => {
  // Refuse ONLY the preference keys, so the rest of the runtime still works: this is the
  // storage-full case, where a silently reverting checkbox would look broken.
  await page.addInitScript(() => {
    const real = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (typeof key === "string" && key.indexOf("autoOpenPanel") >= 0) {
        const err = new Error("quota");
        err.name = "QuotaExceededError";
        throw err;
      }
      return real.call(this, key, value);
    };
  });
  await open(page, "cmh-pref-06b");
  const menu = await openPrefs(page);
  await menu.locator(DEFAULT_ROW).click();
  await expect(page.locator("#toast")).toBeVisible();
  await expect(page.locator("#toast")).toContainText(/Could not save that preference/i);
  await expect(page.locator("#toast").getByRole("button", { name: "Manage storage" })).toBeVisible();
  // The row snapped back because the write never landed, and the effective value is still ON.
  await expect(menu.locator(DEFAULT_ROW)).toHaveAttribute("aria-checked", "true");
});

test("CMH-MENU-PREF-06: a cross-tab change re-syncs an open menu's rows", async ({ page }) => {
  await open(page, "cmh-pref-06c");
  const menu = await openPrefs(page);
  await expect(menu.locator(DEFAULT_ROW)).toHaveAttribute("aria-checked", "true");
  // Another tab turned the shared default off; the open menu must not toggle from a stale state.
  await page.evaluate((k) => {
    localStorage.setItem(k, "0");
    window.dispatchEvent(new StorageEvent("storage", { key: k, newValue: "0" }));
  }, GLOBAL_KEY);
  await expect(menu.locator(DEFAULT_ROW)).toHaveAttribute("aria-checked", "false");
});

test("CMH-MENU-PREF-03: a document keyed 'commentable-html' cannot own the cross-document default", async ({ page }) => {
  // The exact collision the ::autoOpenPanelDefault name exists to prevent: this document's own
  // per-document key is `commentable-html::autoOpenPanel`, which must stay distinct.
  await open(page, "commentable-html");
  const menu = await openPrefs(page);
  await menu.locator(OVERRIDE_ROW).click();
  expect(await docPref(page)).toBe("0");
  expect(await globalPref(page)).toBe(null);      // the shared default is untouched
  await hideSidebar(page);

  // A second document still inherits the (still ON) default.
  const other = stageContent(DOC, { key: "cmh-pref-03c" });
  await page.goto(fileUrl(other.html));
  await ready(page);
  await addTextComment(page, "#one", "follows the untouched default");
  expect(await sidebarOpen(page)).toBe(true);
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
  // The override row is operable from the keyboard too, and also keeps the menu open.
  await over.focus();
  await page.keyboard.press("Enter");
  await expect(over).toHaveAttribute("aria-checked", "true");
  await expect(menu).toBeVisible();
  await page.keyboard.press(" ");
  await expect(over).toHaveAttribute("aria-checked", "false");

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
  // The arrows also reach INTO the menu from the trigger, so the roving focus is usable without
  // first Tabbing past the trigger.
  await page.locator("#btnMoreMenu").press("ArrowDown");
  await expect(menu).toBeVisible();
  await expect(def).toBeFocused();
});

test("CMH-MENU-PREF-05: the menu is one tab stop and dismisses when focus leaves it", async ({ page }) => {
  await open(page, "cmh-pref-05b");
  const menu = await openPrefs(page);
  // Exactly one item is in the sequential tab order at a time; the rest are tabindex="-1".
  const stops = await page.evaluate(() => Array.prototype.map.call(
    document.querySelectorAll("#sidebarMoreMenu button"), (b) => b.getAttribute("tabindex")));
  expect(stops.filter((t) => t === "0").length).toBe(1);
  expect(stops.filter((t) => t === "-1").length).toBe(stops.length - 1);
  // Focusing a later item moves the tab stop with it.
  await menu.locator(OVERRIDE_ROW).focus();
  await expect(menu.locator(OVERRIDE_ROW)).toHaveAttribute("tabindex", "0");
  await expect(menu.locator(DEFAULT_ROW)).toHaveAttribute("tabindex", "-1");
  // Tabbing out of the open menu dismisses it rather than leaving it open behind the caret.
  await page.locator("#btnClearAll").focus();
  await page.keyboard.press("Tab");
  await expect(menu).toBeHidden();
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

test("CMH-MENU-PREF-07: a comment saved in a comments-off deck still surfaces the panel with auto-open off", async ({ page }) => {
  // "Comments off" is only valid with ZERO comments, so a comment landing there must open the
  // panel even with the preference off, or it is stranded behind a lock that contradicts it (#659).
  const slides = '<section class="slide" data-slide-id="s1"><h2>One</h2><p id="one">Slide text to comment on.</p></section>'
    + '<section class="slide" data-slide-id="s2"><h2>Two</h2><p>Second slide.</p></section>';
  const deck = stageDeck(slides, { key: "cmh-pref-deck-off" });
  await page.addInitScript((k) => {
    try { localStorage.setItem(k, "0"); } catch (e) { /* ignore */ }
  }, GLOBAL_KEY);
  await page.goto(fileUrl(deck.html));
  await ready(page);
  // Open the composer FIRST, then switch the deck to "Comments off" behind it, then save - the
  // one flow that can land a comment while the lock is on.
  const composer = await openComposerFor(page, ".slide.active p");
  await openDeckModeMenu(page);
  await page.locator(".cmh-deck-mode-off-item").click();
  expect(await page.evaluate(() => window.__cmhDeck.deckMode())).toBe("off");
  await composer.locator("textarea").fill("saved while off");
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toHaveCount(0);
  expect(await sidebarOpen(page)).toBe(true);
  expect(await page.evaluate(() => window.__cmhDeck.deckMode())).toBe("open");
  expect(await page.locator("mark.cm-hl").count()).toBe(1);
});

test("CMH-MENU-PREF-08: with the preference off a reload of a commented document leaves the panel closed", async ({ page }) => {
  const staged = await open(page, "cmh-pref-08a");
  const menu = await openPrefs(page);
  await menu.locator(DEFAULT_ROW).click();
  await hideSidebar(page);
  await addTextComment(page, "#one", "a comment that outlives the session");
  expect(await sidebarOpen(page)).toBe(false);

  // The reload is the case the preference exists for: the document now HAS a comment, and the
  // load-time restore would otherwise open the panel again forever after.
  await page.goto(fileUrl(staged.html));
  await ready(page);
  expect(await page.locator("mark.cm-hl").count()).toBe(1);
  expect(await sidebarOpen(page)).toBe(false);

  // With the preference back on, the same document opens on load exactly as it always did.
  await page.evaluate((k) => localStorage.setItem(k, "1"), GLOBAL_KEY);
  await page.goto(fileUrl(staged.html));
  await ready(page);
  expect(await sidebarOpen(page)).toBe(true);
});

test("CMH-MENU-PREF-08: with the preference off a first note change no longer opens the panel", async ({ page }) => {
  const doc = DOC + '\n  <div class="cmh-note" data-cmh-note="risk" data-cmh-note-label="Risk">No blocking risks yet.</div>';
  await open(page, "cmh-pref-08b", { content: doc });
  const field = page.locator('[data-cmh-note="risk"] .cmh-note-input');
  await expect(field).toBeVisible();
  // On (the default): the first note change surfaces its card by opening the panel.
  await field.fill("a first change");
  expect(await sidebarOpen(page)).toBe(true);

  const menu = await openPrefs(page);
  await menu.locator(DEFAULT_ROW).click();
  await hideSidebar(page);
  // Off: the change is still tracked, but the panel is left alone.
  await field.fill("");
  await field.fill("a second, later change");
  expect(await sidebarOpen(page)).toBe(false);
  expect(await page.evaluate(() => {
    const k = document.getElementById("commentRoot").dataset.commentKey + "::note";
    return JSON.parse(localStorage.getItem(k) || "{}").risk;
  })).toBe("a second, later change");
});

test("CMH-MENU-PREF-09: the storage manager reclaims a document override and keeps the shared default", async ({ page }) => {
  await open(page, "cmh-pref-09");
  const menu = await openPrefs(page);
  await menu.locator(DEFAULT_ROW).click();      // write the SHARED default
  expect(await globalPref(page)).toBe("0");
  // Seed ANOTHER document's data, including an override of its own, then delete that document from
  // the storage manager: its ::autoOpenPanel subkey must be reclaimed with the rest of its data,
  // while the cross-document default (a shared preference) must survive.
  await page.evaluate(() => {
    localStorage.setItem("commentable-html:/reports/other.html",
      JSON.stringify([{ id: "cother00001", note: "n", quote: "q", start: 0, end: 1 }]));
    localStorage.setItem("commentable-html:/reports/other.html::autoOpenPanel", "1");
  });
  await page.locator("#btnStorage").click();
  await expect(page.locator(".cm-storage-manager")).toBeVisible();
  const otherRow = page.locator(".cm-storage-row", { hasText: "other.html" });
  await otherRow.locator(".cm-storage-danger").click();
  await otherRow.locator(".cm-storage-danger", { hasText: "Confirm" }).click();
  const after = await page.evaluate(() => ({
    otherBase: localStorage.getItem("commentable-html:/reports/other.html"),
    otherPref: localStorage.getItem("commentable-html:/reports/other.html::autoOpenPanel"),
    shared: localStorage.getItem("commentable-html::autoOpenPanelDefault"),
  }));
  expect(after.otherBase).toBeNull();
  expect(after.otherPref).toBeNull();
  expect(after.shared).toBe("0");
});

test("CMH-MENU-PREF-04: with the default off the override pins this document back on", async ({ page }) => {
  await open(page, "cmh-pref-04c");
  const menu = await openPrefs(page);
  await menu.locator(DEFAULT_ROW).click();
  await expect(menu.locator(DEFAULT_ROW)).toHaveAttribute("aria-checked", "false");
  await menu.locator(OVERRIDE_ROW).click();
  await expect(menu.locator(OVERRIDE_ROW)).toHaveText(/Override for this document: On/);
  expect(await docPref(page)).toBe("1");
  await hideSidebar(page);
  await addTextComment(page, "#one", "pinned on here");
  expect(await sidebarOpen(page)).toBe(true);
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
