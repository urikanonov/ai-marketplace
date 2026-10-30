import { test, expect } from "@playwright/test";
import path from "path";
import {
  stageContent, stageDeck, fileUrl, ready, denyExternalNetwork, openToolbarMenu, readDownload,
  routeExampleLibsLocal, awaitMermaidRendered, EXAMPLES,
} from "./helpers.js";

const KEY = "cmh-width-test";
const WIDTH_KEY = KEY + "::documentWidth";
const controls = (page) => page.locator(".cm-toolbar .cm-document-width");
const plus = (page) => controls(page).getByRole("button", { name: "Increase document width" });
const minus = (page) => controls(page).getByRole("button", { name: "Decrease document width" });
const readout = (page) => controls(page).getByRole("status");
const appWidth = (page) => page.locator(".app").evaluate((el) => el.getBoundingClientRect().width);

async function openDoc(page, { key = KEY, custom = "", headings = false } = {}) {
  const staged = stageContent(
    custom + '<section><h' + (headings ? "2" : "1") + '>Width demo</h' + (headings ? "2" : "1")
    + '><p>Responsive document content.</p></section>'
    + (headings ? '<section><h2>More details</h2><p>Second section.</p></section>' : ""),
    { key },
  );
  await page.goto(fileUrl(staged.html));
  await ready(page);
  return staged;
}

test.beforeEach(async ({ page }) => {
  await denyExternalNetwork(page);
  await page.setViewportSize({ width: 2560, height: 900 });
});

test("flow templates default to a responsive 1800px body (CMH-WIDTH-01)", async ({ page }) => {
  await openDoc(page);
  expect(await appWidth(page)).toBe(1800);
  await expect(readout(page)).toHaveText("1800px");
  await page.setViewportSize({ width: 700, height: 900 });
  expect(await appWidth(page)).toBeLessThanOrEqual(700);
});

test("width buttons step by 100px and stop at 800 and 3000px (CMH-WIDTH-02)", async ({ page }) => {
  await openDoc(page);
  await minus(page).focus();
  await page.keyboard.press("Enter");
  expect(await appWidth(page)).toBe(1700);
  await plus(page).click();
  expect(await appWidth(page)).toBe(1800);
  for (let i = 0; i < 10; i++) await minus(page).click();
  await expect(readout(page)).toHaveText("800px");
  await expect(minus(page)).toBeDisabled();
  for (let i = 0; i < 22; i++) await plus(page).click();
  await expect(readout(page)).toHaveText("3000px");
  await expect(plus(page)).toBeDisabled();
  expect(await appWidth(page)).toBeLessThanOrEqual(2560);
});

test("the garden demo demonstrates adjustable reading width (CMH-WIDTH-02)", async ({ page }) => {
  await routeExampleLibsLocal(page);
  await page.goto(fileUrl(path.join(EXAMPLES, "report-community-garden.html")));
  await ready(page);
  await awaitMermaidRendered(page);
  await expect(page.locator("#commentRoot")).toContainText("Width");
  await expect(readout(page)).toHaveText("1800px");
  await minus(page).click();
  await expect(readout(page)).toHaveText("1700px");
  expect(await appWidth(page)).toBe(1700);
  await page.screenshot({ path: test.info().outputPath("garden-width-desktop.png") });
  await page.setViewportSize({ width: 375, height: 812 });
  await plus(page).click();
  await expect(readout(page)).toHaveText("1800px");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: test.info().outputPath("garden-width-mobile.png") });
});

test("width survives reload and is isolated by document identity (CMH-WIDTH-03)", async ({ page }) => {
  const first = await openDoc(page);
  await minus(page).click();
  await page.reload();
  await ready(page);
  await expect(readout(page)).toHaveText("1700px");
  expect(await appWidth(page)).toBe(1700);
  await openDoc(page, { key: KEY + "-other" });
  await expect(readout(page)).toHaveText("1800px");
  await page.goto(fileUrl(first.html));
  await ready(page);
  await expect(readout(page)).toHaveText("1700px");
});

test("invalid saved widths are ignored and blocked storage does not break controls (CMH-WIDTH-03)", async ({ page }) => {
  await page.addInitScript(({ key }) => {
    localStorage.setItem(key, "9000");
    Storage.prototype.setItem = function () { throw new DOMException("Blocked", "SecurityError"); };
  }, { key: WIDTH_KEY });
  await openDoc(page);
  await expect(readout(page)).toHaveText("1800px");
  await minus(page).click();
  expect(await appWidth(page)).toBe(1700);
  await expect(page.locator("#toast")).toContainText("Could not save");
  await page.reload();
  await ready(page);
  await expect(readout(page)).toHaveText("1800px");
});

test("width remains usable with TOC and sidebar and keeps the footer aligned (CMH-WIDTH-04)", async ({ page }) => {
  await openDoc(page, { headings: true });
  for (let i = 0; i < 10; i++) await minus(page).click();
  await page.locator("#btnToggleSidebar").click();
  const panelControl = page.locator("#sidebar .cm-document-width");
  await expect(panelControl).toBeVisible();
  await panelControl.getByRole("button", { name: "Increase document width" }).click();
  await expect(panelControl.getByRole("status")).toHaveText("900px");
  await expect.poll(() => page.evaluate(() => {
    const root = document.getElementById("commentRoot").getBoundingClientRect();
    const footer = document.querySelector(".cm-footer").getBoundingClientRect();
    const toc = document.querySelector(".cm-side-toc").getBoundingClientRect();
    const sidebar = document.getElementById("sidebar").getBoundingClientRect();
    return Math.abs(root.left - footer.left) < 1 && Math.abs(root.right - footer.right) < 1
      && root.left >= toc.right && root.right <= sidebar.left
      && Math.abs(root.width - (900 - 48)) < 1;
  })).toBe(true);
  await page.locator("#btnCloseSidebar").click();
  await page.setViewportSize({ width: 1000, height: 900 });
  await page.locator("#btnToggleSidebar").click();
  expect(await appWidth(page)).toBe(900);
  await panelControl.getByRole("button", { name: "Decrease document width" }).click();
  expect(await appWidth(page)).toBe(800);
  expect(await page.evaluate(() => {
    const root = document.getElementById("commentRoot").getBoundingClientRect();
    const footer = document.querySelector(".cm-footer").getBoundingClientRect();
    return Math.abs(root.left - footer.left) + Math.abs(root.right - footer.right);
  })).toBeLessThan(1);
  await panelControl.getByRole("button", { name: "Increase document width" }).click();
  await page.locator("#btnCloseSidebar").click();
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(plus(page)).toBeVisible();
  await plus(page).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await expect(readout(page)).toHaveText("1000px");
});

test("custom authored width stays intact until explicitly adjusted (CMH-WIDTH-04)", async ({ page }) => {
  await openDoc(page, { custom: "<style>body .app { max-width: 1200px; }</style>" });
  expect(await appWidth(page)).toBe(1200);
  await expect(readout(page)).toHaveText("1200px");
  await plus(page).click();
  expect(await appWidth(page)).toBe(1300);
  await openDoc(page, { custom: "<style>body .app { max-width: 1250px; }</style>", key: KEY + "-off-grid" });
  await plus(page).click();
  await expect(readout(page)).toHaveText("1300px");
});

test("relative authored widths keep an accurate readout and aligned footer (CMH-WIDTH-04)", async ({ page }) => {
  for (const value of ["90%", "min(100%, 72rem)", "clamp(800px, 90vw, 1800px)"]) {
    await page.setViewportSize({ width: 2560, height: 900 });
    await openDoc(page, { custom: `<style>body .app { max-width: ${value}; }</style>`, key: KEY + value });
    await expect(readout(page)).toHaveText(Math.round(await appWidth(page)) + "px");
    await page.setViewportSize({ width: 1260, height: 900 });
    await expect.poll(async () => readout(page).textContent()).toBe(Math.round(await appWidth(page)) + "px");
    expect(await page.evaluate(() => {
      const root = document.getElementById("commentRoot").getBoundingClientRect();
      const footer = document.querySelector(".cm-footer").getBoundingClientRect();
      return Math.abs(root.left - footer.left) + Math.abs(root.right - footer.right);
    })).toBeLessThan(1);
    const expected = Math.min(3000, (Math.floor(await appWidth(page) / 100) + 1) * 100);
    await plus(page).click();
    await expect(readout(page)).toHaveText(expected + "px");
  }
});

test("width controls leave nested authored app containers unchanged (CMH-WIDTH-04)", async ({ page }) => {
  await openDoc(page, { custom: '<style>#nested-width { max-width: 320px; }</style><div class="app" id="nested-width">A narrow authored card.</div>' });
  await minus(page).click();
  await expect(page.locator("#nested-width")).toHaveCSS("max-width", "320px");
});

test("width preference stays out of exports and print and never affects decks (CMH-WIDTH-04)", async ({ page }) => {
  await openDoc(page);
  await minus(page).click();
  await openToolbarMenu(page);
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#btnSaveHtmlTop").click();
  const html = await readDownload(await downloadPromise);
  expect(html).not.toMatch(/<style[^>]*class="cm-document-width-style"/);
  expect(html).not.toMatch(/<[^>]*class="cm-document-width cm-skip"/);
  expect(html).not.toMatch(/<[^>]*class="[^"]*\bcm-document-width-shell\b/);
  await page.emulateMedia({ media: "print" });
  await expect(controls(page)).toBeHidden();
  expect(await page.locator(".app").evaluate((el) => getComputedStyle(el).maxWidth)).not.toBe("1700px");
  await page.emulateMedia({ media: "screen" });
  const deck = stageDeck('<section class="slide active"><h1>Deck</h1></section>', { key: KEY });
  await page.goto(fileUrl(deck.html));
  await ready(page);
  await expect(page.locator(".cm-document-width")).toHaveCount(0);
  await expect(page.locator(".deck-stage")).toHaveCSS("width", "1920px");
  expect(await page.evaluate(() => localStorage.getItem("cmh-width-test::documentWidth"))).toBe("1700");
});
