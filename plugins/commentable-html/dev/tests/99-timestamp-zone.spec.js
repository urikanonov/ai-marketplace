// Timestamp timezone labelling and the "Show times in UTC" reviewer preference. Every rendered
// instant names the zone it is in, so two reviewers in different zones read the same comment the
// same way; the More menu preference normalizes every instant to UTC and labels it UTC instead.
import fs from "node:fs";
import { test, expect } from "@playwright/test";
import {
  fileUrl, ready, stageContent, addTextComment, openSidebarMoreMenu, mutateStoredComments,
  installClipboardCapture, lastCopied, allCids, clickSidebarExport, readDownload,
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
  const local = await page.locator("#cmGenerated").innerText();
  expect(local).toContain("Generated on: Jan 15, 2026");
  expect(local).not.toMatch(/\d{1,2}:\d{2}/);
  expect(local).not.toMatch(/PST|PDT|UTC|GMT/);
  // A calendar date is not an instant, so UTC mode must not give it a time or a zone either.
  const menu = await openPrefs(page);
  await menu.locator(UTC_ROW).click();
  await page.keyboard.press("Escape");
  const utc = await page.locator("#cmGenerated").innerText();
  expect(utc).toContain("Generated on: Jan 15, 2026");
  expect(utc).not.toMatch(/\d{1,2}:\d{2}/);
  expect(utc).not.toMatch(/PST|PDT|UTC|GMT/);
});

test("CMH-SIDE-13: replies and the print appendix carry the zone too", async ({ page }) => {
  // One formatter feeds every surface, so these pin that no call site bypasses it.
  await seedComment(page, "cmh-tz-13");
  await page.locator(".cm-card .cm-reply-btn").first().click();
  await page.locator(".cm-reply-compose").last().locator("textarea").fill("a reply");
  await page.locator(".cm-reply-compose").last().locator(".cm-reply-save").click();
  await expect(page.locator(".cm-reply .meta > span").first()).toContainText(/PST|PDT/);

  // The print appendix is materialized for print media and uses the same formatter.
  await page.emulateMedia({ media: "print" });
  const appendix = page.locator("#cmhPrintComments");
  await expect(appendix).toHaveCount(1);
  expect(await appendix.innerText()).toContain(LOCAL_TEXT);
  await page.emulateMedia({ media: "screen" });
});

test("CMH-SIDE-13: the zone formatter is built once per formatting pass, not once per timestamp", async ({ page }) => {
  // Reusing one Intl.DateTimeFormat for a whole pass is the perf contract; dropping it between
  // passes is what lets a changed OS timezone be picked up without a reload.
  await page.addInitScript(() => {
    const Real = Intl.DateTimeFormat;
    window.__cmhZoneFmtCount = 0;
    function Patched(locale, opts) {
      if (opts && opts.timeZoneName && !opts.year) window.__cmhZoneFmtCount++;
      return new Real(locale, opts);
    }
    Patched.prototype = Real.prototype;
    Patched.supportedLocalesOf = Real.supportedLocalesOf.bind(Real);
    Intl.DateTimeFormat = Patched;
  });
  await seedComment(page, "cmh-tz-14");
  await page.locator(".cm-card .cm-reply-btn").first().click();
  await page.locator(".cm-reply-compose").last().locator("textarea").fill("a reply");
  await page.locator(".cm-reply-compose").last().locator(".cm-reply-save").click();

  const before = await page.evaluate(() => { window.__cmhZoneFmtCount = 0; return 0; });
  expect(before).toBe(0);
  // One render pass draws a card, a reply and both metadata rows - and builds ONE formatter.
  await page.click("#btnSort");
  expect(await page.evaluate(() => window.__cmhZoneFmtCount)).toBe(1);
  await page.click("#btnSort");
  expect(await page.evaluate(() => window.__cmhZoneFmtCount)).toBe(2);

  // The on-demand passes start fresh too, so neither can print a stale zone name after the host
  // timezone changes without an intervening render.
  await installClipboardCapture(page);
  await page.click("#btnCopyAll");
  expect(await page.evaluate(() => window.__cmhZoneFmtCount)).toBe(3);
  await page.emulateMedia({ media: "print" });
  await expect(page.locator("#cmhPrintComments")).toHaveCount(1);
  expect(await page.evaluate(() => window.__cmhZoneFmtCount)).toBeGreaterThan(3);
  await page.emulateMedia({ media: "screen" });
});

test("CMH-SIDE-13: an engine with no zone-name part falls back to a computed UTC offset", async ({ page }) => {
  // Some engines resolve no timeZoneName part at all; the label must still be true, never absent.
  await page.addInitScript(() => {
    const Real = Intl.DateTimeFormat;
    function Patched(locale, opts) {
      const f = new Real(locale, opts);
      if (opts && opts.timeZoneName) {
        return { formatToParts: () => [{ type: "literal", value: "" }], format: (d) => f.format(d) };
      }
      return f;
    }
    Patched.prototype = Real.prototype;
    Patched.supportedLocalesOf = Real.supportedLocalesOf.bind(Real);
    Intl.DateTimeFormat = Patched;
  });
  await seedComment(page, "cmh-tz-15");
  // America/Los_Angeles in January is UTC-08:00.
  expect(await cardTime(page)).toContain("Jan 15, 2026, 12:30 UTC-08:00");
});

test("CMH-MENU-PREF-11: an exported copy carries the instant, not the exporter's zone", async ({ page }) => {
  // An export must not bake the exporter's display zone into the recipient's copy: the embedded
  // store keeps the raw ISO instant, so the recipient's own preference decides how it renders.
  await seedComment(page, "cmh-tz-16");
  const menu = await openPrefs(page);
  await menu.locator(UTC_ROW).click();
  await page.keyboard.press("Escape");
  expect(await cardTime(page)).toContain(UTC_TEXT);

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    clickSidebarExport(page, "#btnSaveHtml"),
  ]);
  const html = await readDownload(download);
  expect(html).toContain(INSTANT);
  expect(html).not.toContain(UTC_TEXT);
  expect(html).not.toContain(LOCAL_TEXT);
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

test("CMH-MENU-PREF-11: an OPEN comment dialog re-stamps in place when another tab changes the zone", async ({ page }) => {
  // Clicking the More menu would dismiss the dialog, so the reachable way an open dialog sees a
  // zone change is a cross-tab write. This is the assertion that actually exercises the refresh.
  await seedComment(page, "cmh-tz-08");
  const cid = (await allCids(page))[0];
  await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
  await page.locator("#hlBubble").click();
  await expect(page.locator(".cm-comment-popover-meta")).toContainText(LOCAL_TEXT);

  await page.evaluate((k) => {
    localStorage.setItem(k, "1");
    window.dispatchEvent(new StorageEvent("storage", { key: k, newValue: "1" }));
  }, UTC_KEY);
  await expect(page.locator(".cm-comment-popover-meta")).toContainText(UTC_TEXT);
  expect(await cardTime(page)).toContain(UTC_TEXT);
});

test("CMH-MENU-PREF-11: a storage event that does not move the zone leaves the list alone", async ({ page }) => {
  // On file:// every document shares one localStorage origin, and a clear() reports a null key, so
  // an unrelated write must not rebuild the comment list - a rebuild would throw a reader who is
  // scrolled deep into a long list back to the top.
  await seedComment(page, "cmh-tz-09");
  // Identity, not appearance: renderComments() replaces the list wholesale, so a card element that
  // is still connected proves no rebuild happened.
  await page.evaluate(() => { window.__cmhProbeCard = document.querySelector(".cm-card"); });
  // Force the list to actually scroll, so the restore has something to preserve.
  await page.evaluate(() => {
    const l = document.getElementById("commentList");
    l.style.maxHeight = "40px";
    l.style.overflowY = "auto";
    l.scrollTop = 20;
  });
  const before = await page.evaluate(() => document.getElementById("commentList").scrollTop);
  expect(before).toBeGreaterThan(0);

  await page.evaluate(() => {
    localStorage.setItem("commentable-html::somethingElse", "x");
    window.dispatchEvent(new StorageEvent("storage", { key: null, newValue: null }));
  });
  expect(await page.evaluate(() => window.__cmhProbeCard.isConnected)).toBe(true);
  expect(await page.evaluate(() => document.getElementById("commentList").scrollTop)).toBe(before);

  // A real zone change DOES rebuild and re-stamp - and still keeps the reader's place in the list.
  await page.evaluate((k) => {
    localStorage.setItem(k, "1");
    window.dispatchEvent(new StorageEvent("storage", { key: k, newValue: "1" }));
  }, UTC_KEY);
  expect(await page.evaluate(() => window.__cmhProbeCard.isConnected)).toBe(false);
  expect(await page.evaluate(() => document.getElementById("commentList").scrollTop)).toBe(before);
  expect(await cardTime(page)).toContain(UTC_TEXT);
});

test("CMH-MENU-PREF-11: deleting the shared preferences re-stamps every surface back to local time", async ({ page }) => {
  // The storage manager's "Other / shared data" row owns the display-zone key, and a same-document
  // removeItem fires no storage event - so without an explicit re-stamp the footer would keep
  // reading UTC beside cards drawn in local time.
  await seedComment(page, "cmh-tz-10", { generated: INSTANT });
  const menu = await openPrefs(page);
  await menu.locator(UTC_ROW).click();
  await page.keyboard.press("Escape");
  expect(await cardTime(page)).toContain(UTC_TEXT);

  await openSidebarMoreMenu(page);
  await page.click("#btnStorage");
  const row = page.locator(".cm-storage-global");
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: /Delete shared preferences/ }).click();
  await page.locator(".cm-storage-confirm .cm-storage-danger").click();

  expect(await page.evaluate((k) => localStorage.getItem(k), UTC_KEY)).toBe(null);
  expect(await cardTime(page)).toContain(LOCAL_TEXT);
  expect(await page.locator("#cmGenerated").innerText()).toContain(LOCAL_TEXT);
  expect(await page.locator("#cmFooter .cm-footer-gen").innerText()).toContain(LOCAL_TEXT);
});

test("CMH-SIDE-13: a missing or padded timestamp formats sanely instead of leaking Invalid Date", async ({ page }) => {
  await seedComment(page, "cmh-tz-11");
  const setCreated = async (value) => {
    await mutateStoredComments(page, (arr) => {
      arr.forEach((c) => { delete c.updatedAt; if (value === undefined) delete c.createdAt; else c.createdAt = value; });
    });
    await page.reload();
    await ready(page);
    await showSidebar(page);
    return cardTime(page);
  };

  // No timestamp at all renders an EMPTY time - never "undefined", "Invalid Date", or
  // new Date(null)'s Unix epoch - and drops the dangling "#1 - " separator with it.
  for (const missing of [undefined, null, "", "   "]) {
    const shown = await setCreated(missing);
    expect(shown, String(missing)).not.toMatch(/undefined|Invalid Date|1970|NaN/);
    expect(shown.trim(), String(missing)).toBe("#1");
  }

  // Whitespace around a real ISO instant is benign: it must still format, not be echoed raw.
  expect(await setCreated("  " + INSTANT + "  ")).toContain(LOCAL_TEXT);
  // An epoch-milliseconds NUMBER is a perfectly good instant and must not be stringified first.
  expect(await setCreated(Date.parse(INSTANT))).toContain(LOCAL_TEXT);
  // Something that is genuinely not a date is handed back as its own text, with no zone attached.
  const junk = await setCreated("  not a date  ");
  expect(junk).toContain("not a date");
  expect(junk).not.toMatch(/PST|PDT|UTC|GMT|Invalid Date/);

  // An updatedAt that is present but UNUSABLE must not hide a good createdAt, nor claim "(edited)"
  // with nothing to show for it.
  await mutateStoredComments(page, (arr) => {
    arr.forEach((c) => { c.createdAt = INSTANT; c.updatedAt = "   "; });
  });
  await page.reload();
  await ready(page);
  await showSidebar(page);
  const fallback = await cardTime(page);
  expect(fallback).toContain(LOCAL_TEXT);
  expect(fallback).not.toContain("edited");
});

test("CMH-SIDE-13: an engine that ignores the timeZone option never labels local time as UTC", async ({ page }) => {
  // toLocaleString is allowed to drop its options where Intl is unusable. Claiming UTC over a local
  // clock would be a false statement, so the runtime falls back to a fixed-format UTC rendering.
  await page.addInitScript(() => {
    const real = Date.prototype.toLocaleString;
    Date.prototype.toLocaleString = function () { return real.call(this); };
  });
  await seedComment(page, "cmh-tz-12");
  const menu = await openPrefs(page);
  await menu.locator(UTC_ROW).click();
  await page.keyboard.press("Escape");
  const shown = await cardTime(page);
  expect(shown).toContain("20:30:00 UTC");     // the instant's real UTC clock time
  expect(shown).not.toContain("12:30");        // never the local clock under a UTC label
  expect(shown).not.toContain("GMT");
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
