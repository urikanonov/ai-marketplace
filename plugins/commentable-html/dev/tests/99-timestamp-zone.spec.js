// Timestamp timezone labelling and the "Show times in UTC" reviewer preference. Every rendered
// instant names the zone it is in, so two reviewers in different zones read the same comment the
// same way; the More menu preference normalizes every instant to UTC and labels it UTC instead.
import fs from "node:fs";
import { test, expect } from "@playwright/test";
import {
  fileUrl, ready, stageContent, addTextComment, openSidebarMoreMenu, mutateStoredComments,
  installClipboardCapture, lastCopied, allCids,
} from "./helpers.js";

// A fixed zone west of UTC (PST in January), so both the local and the UTC rendering of one
// instant are exact strings rather than whatever the runner's machine happens to be set to.
test.use({ timezoneId: "America/Los_Angeles", locale: "en-US" });

const DOC = `
  <h1>Timestamps</h1>
  <p id="one">The first paragraph carries the text a reviewer selects.</p>`;

const UTC_KEY = "commentable-html::utcTimes";
const UTC_ROW = "#btnUtcTimes";

// 2026-01-15T20:30:00Z is 12:30 PST on the same calendar day, so a missing zone label cannot be
// disguised by the two renderings agreeing.
const INSTANT = "2026-01-15T20:30:00.000Z";
const LOCAL_TEXT = "Jan 15, 2026, 12:30 PST";
const UTC_TEXT = "Jan 15, 2026, 20:30 UTC";

// Stage a document, optionally stamping data-generated INTO the file so the startup footer (built
// once, before any test code runs) reads it.
async function open(page, key, { generated = null } = {}) {
  const staged = stageContent(DOC, { key });
  if (generated) {
    const html = fs.readFileSync(staged.html, "utf8")
      .replace(`data-comment-key="${key}"`, `data-comment-key="${key}" data-generated="${generated}"`);
    fs.writeFileSync(staged.html, html);
  }
  await page.goto(fileUrl(staged.html));
  await ready(page);
  return staged;
}

async function showSidebar(page) {
  if (!(await page.evaluate(() => document.body.classList.contains("sidebar-open")))) {
    await page.click("#btnToggleSidebar");
  }
  await expect(page.locator("#sidebar")).toBeVisible();
}

// One comment whose createdAt is the fixed INSTANT, reloaded so the card renders from the store.
async function seedComment(page, key, { generated = null } = {}) {
  await open(page, key, { generated });
  await addTextComment(page, "#one", "zone check");
  await mutateStoredComments(page, (arr) => {
    arr.forEach((c) => { c.createdAt = INSTANT; delete c.updatedAt; });
  });
  await page.reload();
  await ready(page);
  await showSidebar(page);
}

async function openPrefs(page) {
  await showSidebar(page);
  await openSidebarMoreMenu(page);
  return page.locator("#sidebarMoreMenu");
}

const cardTime = (page) => page.locator(".cm-card .cm-entry-root .meta > span").first().innerText();

test("CMH-SIDE-13: a comment card timestamp names the local timezone", async ({ page }) => {
  await seedComment(page, "cmh-tz-01");
  expect(await cardTime(page)).toContain(LOCAL_TEXT);
});

test("CMH-SIDE-13: the sidebar Generated-on row and the footer name the timezone", async ({ page }) => {
  await open(page, "cmh-tz-02", { generated: INSTANT });
  await showSidebar(page);
  expect(await page.locator("#cmGenerated").innerText()).toContain(LOCAL_TEXT);
  expect(await page.locator("#cmFooter .cm-footer-gen").innerText()).toContain(LOCAL_TEXT);
});

test("CMH-SIDE-13: a date-only generated value stays a bare calendar date with no zone", async ({ page }) => {
  await open(page, "cmh-tz-03", { generated: "2026-01-15" });
  await showSidebar(page);
  const text = await page.locator("#cmGenerated").innerText();
  expect(text).toContain("Generated on: Jan 15, 2026");
  expect(text).not.toMatch(/\d{1,2}:\d{2}/);
  expect(text).not.toMatch(/PST|PDT|UTC|GMT/);
});

test("CMH-MENU-PREF-10: the More menu carries a Show times in UTC row that toggles in place and persists", async ({ page }) => {
  await open(page, "cmh-tz-04");
  const menu = await openPrefs(page);
  const row = menu.locator(UTC_ROW);
  await expect(row).toBeVisible();
  await expect(row).toHaveAttribute("role", "menuitemcheckbox");
  await expect(row).toHaveText(/Show times in UTC/);
  // It sits in the Preferences group, above the Manage actions.
  await expect(menu.locator(".cm-menu-group", { hasText: "Preferences" })).toHaveCount(1);
  expect(await row.evaluate((el) =>
    !!(el.compareDocumentPosition(document.querySelector("#btnStorage")) & Node.DOCUMENT_POSITION_FOLLOWING)))
    .toBe(true);
  // Local time is the default: nothing stored, nothing checked.
  await expect(row).toHaveAttribute("aria-checked", "false");
  expect(await page.evaluate((k) => localStorage.getItem(k), UTC_KEY)).toBe(null);

  await row.click();
  await expect(row).toHaveAttribute("aria-checked", "true");
  await expect(menu).toBeVisible();                       // toggling leaves the menu open
  expect(await page.evaluate((k) => localStorage.getItem(k), UTC_KEY)).toBe("1");

  // The preference is CROSS-DOCUMENT: another document opens already in UTC mode.
  const other = stageContent(DOC, { key: "cmh-tz-04b" });
  await page.goto(fileUrl(other.html));
  await ready(page);
  const otherMenu = await openPrefs(page);
  await expect(otherMenu.locator(UTC_ROW)).toHaveAttribute("aria-checked", "true");
});

test("CMH-MENU-PREF-10: the UTC row is keyboard operable and re-syncs on a cross-tab change", async ({ page }) => {
  await open(page, "cmh-tz-05");
  const menu = await openPrefs(page);
  const row = menu.locator(UTC_ROW);
  await row.focus();
  await page.keyboard.press("Enter");
  await expect(row).toHaveAttribute("aria-checked", "true");
  await expect(menu).toBeVisible();
  await page.keyboard.press(" ");
  await expect(row).toHaveAttribute("aria-checked", "false");

  // Another tab turned it on while this menu is open; the row must not toggle from a stale state.
  await page.evaluate((k) => {
    localStorage.setItem(k, "1");
    window.dispatchEvent(new StorageEvent("storage", { key: k, newValue: "1" }));
  }, UTC_KEY);
  await expect(row).toHaveAttribute("aria-checked", "true");
});

test("CMH-MENU-PREF-10: a refused UTC-preference write reports itself instead of silently snapping back", async ({ page }) => {
  // A storage-full browser refuses the write; a silently reverting checkbox would look broken.
  await page.addInitScript(() => {
    const real = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (typeof key === "string" && key.indexOf("utcTimes") !== -1) {
        const err = new Error("quota");
        err.name = "QuotaExceededError";
        throw err;
      }
      return real.call(this, key, value);
    };
  });
  await open(page, "cmh-tz-05b");
  const menu = await openPrefs(page);
  await menu.locator(UTC_ROW).click();
  await expect(page.locator("#toast")).toContainText(/Could not save that preference/i);
  await expect(page.locator("#toast").getByRole("button", { name: "Manage storage" })).toBeVisible();
  // The row snapped back because the write never landed, and times are still local.
  await expect(menu.locator(UTC_ROW)).toHaveAttribute("aria-checked", "false");
});

test("CMH-MENU-PREF-11: turning UTC on re-labels every rendered timestamp without a reload", async ({ page }) => {
  await seedComment(page, "cmh-tz-06", { generated: INSTANT });
  expect(await cardTime(page)).toContain(LOCAL_TEXT);
  expect(await page.locator("#cmFooter .cm-footer-gen").innerText()).toContain(LOCAL_TEXT);

  const menu = await openPrefs(page);
  await menu.locator(UTC_ROW).click();
  await page.keyboard.press("Escape");

  // Card, both side-info rows, and the footer all re-stamp in place - no reload.
  expect(await cardTime(page)).toContain(UTC_TEXT);
  expect(await page.locator("#cmGenerated").innerText()).toContain(UTC_TEXT);
  expect(await page.locator("#cmLastComment").innerText()).toContain(UTC_TEXT);
  expect(await page.locator("#cmFooter .cm-footer-gen").innerText()).toContain(UTC_TEXT);

  // The in-document comment dialog reads the same clock.
  const cid = (await allCids(page))[0];
  await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
  await page.locator("#hlBubble").click();
  await expect(page.locator(".cm-comment-popover-meta")).toContainText(UTC_TEXT);
});

test("CMH-MENU-PREF-11: the Copy all bundle carries the UTC-labelled time", async ({ page }) => {
  await installClipboardCapture(page);
  await seedComment(page, "cmh-tz-07");
  await page.click("#btnCopyAll");
  expect(await lastCopied(page)).toContain(LOCAL_TEXT);

  const menu = await openPrefs(page);
  await menu.locator(UTC_ROW).click();
  await page.keyboard.press("Escape");
  await page.click("#btnCopyAll");
  expect(await lastCopied(page)).toContain(UTC_TEXT);
});
