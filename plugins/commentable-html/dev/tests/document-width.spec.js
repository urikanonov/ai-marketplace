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

async function openDoc(page, { key = KEY, custom = "", headings = false, menu = true } = {}) {
  const staged = stageContent(
    custom + '<section><h' + (headings ? "2" : "1") + '>Width demo</h' + (headings ? "2" : "1")
    + '><p>Responsive document content.</p></section>'
    + (headings ? '<section><h2>More details</h2><p>Second section.</p></section>' : ""),
    { key },
  );
  await page.goto(fileUrl(staged.html));
  await ready(page);
  if (menu) await openToolbarMenu(page);
  return staged;
}

test.beforeEach(async ({ page }) => {
  await denyExternalNetwork(page);
  await page.setViewportSize({ width: 2560, height: 900 });
});

async function checkWidthMenus(page, viewport) {
    await page.setViewportSize(viewport);
    await page.addInitScript(() => localStorage.setItem("commentable-html::sidebarWidth", "256"));
    await openDoc(page, { menu: false });
    await expect(page.locator(".cm-document-width").first()).toBeHidden();
    await openToolbarMenu(page);
    const toolbarWidth = page.locator("#toolbarMenu .cm-document-width");
    await expect(toolbarWidth).toBeVisible();
    await expect(toolbarWidth.getByLabel("Decrease document width", { exact: true })).toHaveAccessibleDescription("1800px");
    await toolbarWidth.getByLabel("Decrease document width", { exact: true }).click();
    await expect(toolbarWidth.getByRole("status")).toHaveText("1700px");
    await expect(page.locator("#toolbarMenu")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(toolbarWidth).toBeHidden();
    await expect(page.locator("#btnToolbarMenu")).toBeFocused();
    await page.locator("#btnToggleSidebar").click();
    const panelWidth = page.locator("#sidebarMoreMenu .cm-document-width");
    await expect(panelWidth).toBeHidden();
    await expect(page.locator("#sidebar .head-aux .cm-document-width")).toHaveCount(0);
    await page.locator("#btnMoreMenu").click();
    await expect(panelWidth).toBeVisible();
    await panelWidth.getByLabel("Increase document width", { exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(panelWidth.getByRole("status")).toHaveText("1800px");
    await expect(page.locator("#sidebarMoreMenu")).toBeVisible();
    await page.keyboard.press("ArrowUp");
    await expect(panelWidth.getByLabel("Decrease document width", { exact: true })).toBeFocused();
    await expect(panelWidth.getByLabel("Decrease document width", { exact: true })).toHaveCSS("outline-style", "solid");
    for (const theme of ["light", "dark"]) {
      await page.locator("html").evaluate((el, value) => el.setAttribute("data-theme", value), theme);
      for (const name of ["Decrease document width", "Increase document width"]) {
        const button = panelWidth.getByLabel(name, { exact: true });
        await expect(button).toBeVisible();
        const style = await button.evaluate((el) => {
          const css = getComputedStyle(el), box = el.getBoundingClientRect();
          return {
            border: css.borderTopStyle, borderWidth: parseFloat(css.borderTopWidth),
            color: css.color, background: css.backgroundColor,
            weight: Number(css.fontWeight), width: box.width, height: box.height,
          };
        });
        expect(style.border).toBe("solid");
        expect(style.borderWidth).toBeGreaterThanOrEqual(1);
        expect(style.background).not.toBe("rgba(0, 0, 0, 0)");
        expect(style.color).not.toBe(style.background);
        expect(style.weight).toBeGreaterThanOrEqual(600);
        expect(style.width).toBeGreaterThanOrEqual(viewport.width < 640 ? 44 : 32);
        expect(style.height).toBeGreaterThanOrEqual(viewport.width < 640 ? 44 : 32);
      }
    }
    await page.keyboard.press("Escape");
    await expect(panelWidth).toBeHidden();
    await expect(page.locator("#btnMoreMenu")).toBeFocused();
    if (viewport.width > 640) {
      await page.locator("#sidebarResizeHandle").focus();
      await page.keyboard.press("Home");
    }
    await page.locator("#btnMoreMenu").click();
    await expect(panelWidth).toBeVisible();
    const menuBox = await page.locator("#sidebarMoreMenu").boundingBox();
    expect(menuBox.x).toBeGreaterThanOrEqual(0);
    expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(viewport.width);
    expect(await page.locator("#sidebarMoreMenu").evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
    await panelWidth.getByLabel("Decrease document width", { exact: true }).click();
    await expect(panelWidth.getByRole("status")).toHaveText("1700px");
    await page.screenshot({ path: test.info().outputPath(`width-menu-${viewport.width}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
}

test("width controls live in More menus with distinct buttons at 1440px (CMH-WIDTH-02)", async ({ page }) => {
  await checkWidthMenus(page, { width: 1440, height: 900 });
});

test("width controls live in More menus with distinct buttons at 375px (CMH-WIDTH-02)", async ({ page }) => {
  await checkWidthMenus(page, { width: 375, height: 812 });
});

test("width menu keyboard focus survives both limits (CMH-WIDTH-02)", async ({ page }) => {
  await openDoc(page);
  await page.locator("#btnToggleSidebar").click();
  await page.locator("#btnMoreMenu").click();
  const group = page.locator("#sidebarMoreMenu .cm-document-width");
  const decrease = group.getByLabel("Decrease document width", { exact: true });
  const increase = group.getByLabel("Increase document width", { exact: true });
  for (let i = 0; i < 9; i++) await decrease.click();
  await decrease.focus();
  await page.keyboard.press("Enter");
  await expect(decrease).toBeDisabled();
  await expect(increase).toBeFocused();
  await expect(increase).toHaveAccessibleDescription("800px");
  for (let i = 0; i < 21; i++) await increase.click();
  await increase.focus();
  await page.keyboard.press("Enter");
  await expect(increase).toBeDisabled();
  await expect(decrease).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.locator("#btnUtcTimes")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator("#btnMoreMenu")).toBeFocused();
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
  await openToolbarMenu(page);
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
  await openToolbarMenu(page);
  await expect(readout(page)).toHaveText("1700px");
  expect(await appWidth(page)).toBe(1700);
  await openDoc(page, { key: KEY + "-other" });
  await expect(readout(page)).toHaveText("1800px");
  await page.goto(fileUrl(first.html));
  await ready(page);
  await openToolbarMenu(page);
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
  await openToolbarMenu(page);
  await expect(readout(page)).toHaveText("1800px");
});

test("width remains usable with TOC and sidebar and keeps the footer aligned (CMH-WIDTH-04)", async ({ page }) => {
  await openDoc(page, { headings: true });
  for (let i = 0; i < 10; i++) await minus(page).click();
  await page.locator("#btnToggleSidebar").click();
  await page.locator("#btnMoreMenu").click();
  const panelControl = page.locator("#sidebar .cm-document-width");
  await expect(panelControl).toBeVisible();
  await panelControl.getByLabel("Increase document width", { exact: true }).click();
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
  await page.locator("#btnMoreMenu").click();
  expect(await appWidth(page)).toBe(900);
  await panelControl.getByLabel("Decrease document width", { exact: true }).click();
  expect(await appWidth(page)).toBe(800);
  expect(await page.evaluate(() => {
    const root = document.getElementById("commentRoot").getBoundingClientRect();
    const footer = document.querySelector(".cm-footer").getBoundingClientRect();
    return Math.abs(root.left - footer.left) + Math.abs(root.right - footer.right);
  })).toBeLessThan(1);
  await panelControl.getByLabel("Increase document width", { exact: true }).click();
  await page.locator("#btnCloseSidebar").click();
  await page.setViewportSize({ width: 375, height: 812 });
  await openToolbarMenu(page);
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

test("width changes remeasure charts and dismiss stale hover tooltips (CMH-WIDTH-04)", async ({ page }) => {
  await openDoc(page, { custom: '<figure class="chart"><div class="chart-wrap" style="height:240px"><canvas id="width-chart" class="cmh-chart" width="760" height="240" data-cmh-chart-points=\'[{"label":"A","value":10},{"label":"B","value":24}]\'></canvas></div></figure>' });
  const chart = page.locator("#width-chart");
  await expect.poll(() => chart.evaluate((el) => !!el._cmhChart)).toBe(true);
  const point = await chart.evaluate((el) => el._cmhChart.points[0]);
  await chart.hover({ position: { x: point.x, y: (point.top + point.bottom) / 2 } });
  await expect(page.locator(".cmh-chart-tooltip")).toBeVisible();
  await minus(page).evaluate((el) => el.click());
  await expect(page.locator(".cmh-chart-tooltip")).not.toHaveClass(/is-visible/);
  await expect.poll(() => chart.evaluate((el) => Math.abs(el.width / devicePixelRatio - el.clientWidth))).toBeLessThanOrEqual(1);
  const moved = await chart.evaluate((el) => el._cmhChart.points[0]);
  await chart.hover({ position: { x: moved.x, y: (moved.top + moved.bottom) / 2 } });
  await expect(page.locator(".cmh-chart-tooltip")).toContainText("A: 10");
});

test("panel-open relative widths refresh on resize and preference removal (CMH-WIDTH-04)", async ({ page }) => {
  await openDoc(page, { custom: "<style>body .app { max-width: 90%; }</style>" });
  await page.locator("#btnToggleSidebar").click();
  await page.locator("#btnMoreMenu").click();
  const panelReadout = page.locator("#sidebar .cm-document-width").getByRole("status");
  await page.setViewportSize({ width: 1000, height: 900 });
  await expect(panelReadout).toHaveText("900px");
  await page.locator("#sidebar .cm-document-width").getByLabel("Decrease document width", { exact: true }).click();
  await page.evaluate((key) => {
    localStorage.removeItem(key);
    window.dispatchEvent(new StorageEvent("storage", { key }));
  }, WIDTH_KEY);
  await expect(panelReadout).toHaveText("900px");
  await expect.poll(() => page.evaluate(() => {
    const root = document.getElementById("commentRoot").getBoundingClientRect();
    const footer = document.querySelector(".cm-footer").getBoundingClientRect();
    return Math.abs(root.left - footer.left) + Math.abs(root.right - footer.right);
  })).toBeLessThan(1);
  await page.setViewportSize({ width: 2000, height: 900 });
  await expect(panelReadout).toHaveText("1800px");
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
