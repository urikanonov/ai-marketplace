import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { spawnSync } from "child_process";
import {
  fileUrl, ready, installClipboardCapture, stageContent, copiedBundle, readDownload,
  clickSidebarExport, clickClearAll, addTextComment, openComposerFor, openSearch, routeExampleLibsLocal, SKILL, PYTHON,
} from "./helpers.js";

const DOC = `<h1>Editable table</h1><p id="before">Leading reviewable prose.</p>
<table data-cmh-table="agenda" data-cmh-table-label="Discussion items">
<thead><tr><th data-cmh-column="question">Discussion item</th><th data-cmh-column="owner">Owner</th>
<th data-cmh-column="status" data-cmh-column-type="choice" data-cmh-options='["Open","Done"]' data-cmh-default="Open">Status</th></tr></thead>
<tbody><tr data-cmh-row="first"><td>Decide launch</td><td>Alex</td><td>Open</td></tr>
<tr data-cmh-row="second"><td>Review evidence</td><td></td><td>Done</td></tr></tbody></table>
<p id="after">Trailing reviewable prose.</p>`;
const table = page => page.locator('[data-cmh-table="agenda"]');
const cell = (page, row = "first", col = "question") =>
  table(page).locator(`[data-cmh-row="${row}"] [data-cmh-edit-column="${col}"]`);
const action = (page, name) => page.locator(".cmh-editable-table").getByRole("button", { name, exact: true });

async function open(page, content = DOC, key = "cmh-table-test") {
  await installClipboardCapture(page);
  const staged = stageContent(content, { key });
  await page.goto(fileUrl(staged.html));
  await ready(page);
  return staged;
}
async function bundle(page) {
  await page.locator("#btnCopyAll").click();
  const text = await copiedBundle(page);
  const payload = JSON.parse(text.match(/^TABLES_STATE_JSON: (.+)$/m)[1]);
  return { text, payload };
}
async function addColumn(page, label, type = "text", options = "") {
  await action(page, "Add column").click();
  const dialog = page.getByRole("dialog", { name: "Add column" });
  await dialog.getByLabel("Column name", { exact: true }).fill(label);
  await dialog.getByLabel("Column type").selectOption(type);
  if (type === "choice") await dialog.getByLabel("Choices (one per line)").fill(options);
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
}

const columnIds = page => table(page).locator("thead th[data-cmh-column]").evaluateAll(headers => headers.map(h => h.dataset.cmhColumn));
const grip = (page, id) => table(page).locator(`[data-cmh-column="${id}"] .cmh-table-drag`);

async function dragColumn(page, from, to, after = true) {
  await expect(grip(page, from)).toBeVisible();
  const start = await grip(page, from).boundingBox();
  const end = await table(page).locator(`[data-cmh-column="${to}"]`).boundingBox();
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  await page.mouse.move(end.x + end.width * (after ? .8 : .2), end.y + end.height / 2, { steps: 8 });
  await page.mouse.up();
}

test("dragging columns moves schema and values together with stable comments and history (CMH-TABLE-15)", async ({ page }) => {
  await open(page);
  await table(page).locator('[data-cmh-column="owner"] .cmh-table-column-comment').click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("Keep this ownership discussion.");
  await composer.locator('[data-act="save"]').click();
  await table(page).getByRole("button", { name: "Sort by Discussion item, column 1", exact: true }).click();
  await dragColumn(page, "question", "status");
  expect(await columnIds(page)).toEqual(["owner", "status", "question"]);
  await expect(cell(page, "first", "question")).toHaveValue("Decide launch");
  await expect(cell(page, "first", "owner")).toHaveValue("Alex");
  await expect(cell(page, "second", "status")).toHaveValue("Done");
  await expect(table(page).locator('[data-cmh-column="owner"] .cmh-table-title')).toHaveAttribute("data-cids", /c/);
  await expect(table(page).getByRole("button", { name: "Sort by Discussion item, column 3", exact: true })).toHaveAttribute("data-dir", "asc");
  const { text, payload } = await bundle(page);
  expect(text).toContain("Column order:");
  expect(payload.tables[0].to.rows[0].cells).toEqual(["Alex", "Open", "Decide launch"]);
  await expect(page.locator(".cm-card-table")).toHaveCount(1);
  await expect(page.locator(".cm-card-table .note").first()).toHaveText("1 cumulative change(s)");
  await action(page, "Undo").click();
  expect(await columnIds(page)).toEqual(["question", "owner", "status"]);
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
  await action(page, "Redo").click();
  expect(await columnIds(page)).toEqual(["owner", "status", "question"]);
  await expect(table(page).locator("thead th").first()).toHaveClass("cmh-table-number");
  await expect(table(page).locator("thead th").last()).toHaveClass("cmh-table-remove-cell");
  await expect(table(page).locator(".cmh-table-number .cmh-table-drag, .cmh-table-remove-cell .cmh-table-drag")).toHaveCount(0);
});

test("mouse-only column moves persist through reload and export (CMH-TABLE-15)", async ({ page }) => {
  const staged = await open(page);
  await expect(grip(page, "question")).toBeVisible();
  await grip(page, "question").focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
  await dragColumn(page, "status", "owner", false);
  expect(await columnIds(page)).toEqual(["question", "status", "owner"]);
  await expect(grip(page, "status")).toBeFocused();
  const header = table(page).locator('[data-cmh-column="owner"]');
  await header.locator("summary").click();
  await expect(header.getByRole("button", { name: /Move column/ })).toHaveCount(0);
  await header.locator("summary").click();
  await dragColumn(page, "owner", "status", false);
  expect(await columnIds(page)).toEqual(["question", "owner", "status"]);
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
  await dragColumn(page, "status", "owner", false);
  await page.goto(fileUrl(staged.html));
  await ready(page);
  expect(await columnIds(page)).toEqual(["question", "status", "owner"]);
  const download = page.waitForEvent("download");
  await clickSidebarExport(page, "#btnSaveHtml");
  const output = path.join(path.dirname(staged.html), "reordered.html");
  fs.writeFileSync(output, await readDownload(await download));
  await page.goto(fileUrl(output));
  await ready(page);
  expect(await columnIds(page)).toEqual(["question", "status", "owner"]);
  await expect(cell(page, "second", "status")).toHaveValue("Done");
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
});

test("cancelled and invalid column drops are no-ops (CMH-TABLE-15)", async ({ page }) => {
  await open(page);
  await expect(grip(page, "owner")).toBeVisible();
  for (const cancel of ["Escape", "outside", "self"]) {
    const start = await grip(page, "owner").boundingBox();
    await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
    await page.mouse.down();
    await page.mouse.move(start.x + 15, start.y + start.height / 2, { steps: 3 });
    if (cancel === "Escape") await page.keyboard.press("Escape");
    if (cancel === "outside") await page.mouse.move(2, 2, { steps: 3 });
    await page.mouse.up();
    expect(await columnIds(page)).toEqual(["question", "owner", "status"]);
    await expect(page.locator(".cm-card-table")).toHaveCount(0);
    await expect(table(page).locator(".cmh-table-drop-before, .cmh-table-drop-after")).toHaveCount(0);
  }
});

test("touch gestures leave mouse-only column order unchanged (CMH-TABLE-15)", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 900 });
  await open(page);
  await expect(grip(page, "owner")).toBeVisible();
  const start = await grip(page, "owner").boundingBox(), end = await table(page).locator('[data-cmh-column="question"]').boundingBox();
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setTouchEmulationEnabled", { enabled: true });
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: start.x + start.width / 2, y: start.y + start.height / 2 }] });
  await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: end.x + 8, y: end.y + end.height / 2 }] });
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  expect(await columnIds(page)).toEqual(["question", "owner", "status"]);
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
  await expect(table(page).locator("thead th").first()).toHaveClass("cmh-table-number");
  await cdp.detach();
});

test("table dialogs are compact branded and give Save a contrasting primary color (CMH-TABLE-16)", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 900 });
  await open(page);
  for (const theme of ["light", "dark"]) {
    await page.evaluate(value => document.documentElement.dataset.theme = value, theme);
    await action(page, "Add column").click();
    const dialog = page.getByRole("dialog", { name: "Add column" });
    const icon = dialog.getByRole("img", { name: /Commentable HTML/ });
    await expect(icon).toBeVisible();
    const bounds = await dialog.boundingBox(), mark = await icon.boundingBox();
    expect(bounds.height).toBeLessThan(310);
    expect(mark.x + mark.width).toBeGreaterThan(bounds.x + bounds.width - 44);
    const save = dialog.getByRole("button", { name: "Save", exact: true });
    const colors = await save.evaluate(el => [getComputedStyle(el).backgroundColor, getComputedStyle(el).color]);
    expect(colors[0]).not.toBe(await dialog.getByRole("button", { name: "Cancel", exact: true }).evaluate(el => getComputedStyle(el).backgroundColor));
    const luminance = value => {
      const rgb = value.match(/[\d.]+/g).slice(0, 3).map(Number).map(v => {
        const n = v / 255; return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4;
      });
      return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
    };
    const light = colors.map(luminance).sort((a, b) => b - a);
    expect((light[0] + .05) / (light[1] + .05)).toBeGreaterThanOrEqual(4.5);
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  }
});

test("whole-cell hover feedback is immediate without stealing click-based editing focus (CMH-TABLE-09)", async ({ page }) => {
  await open(page);
  for (const theme of ["light", "dark"]) {
    await page.evaluate(value => document.documentElement.dataset.theme = value, theme);
    await page.mouse.move(0, 0);
    const other = cell(page, "second", "owner"), td = other.locator("..");
    await td.evaluate((el, theme) => { el.style.backgroundColor = theme === "light" ? "#d8f2df" : "#233d51"; }, theme);
    await cell(page).focus();
    const before = await td.evaluate(el => getComputedStyle(el).backgroundColor);
    const editorBefore = await other.evaluate(el => getComputedStyle(el).backgroundColor);
    const bounds = await td.boundingBox();
    await page.mouse.move(bounds.x + 3, bounds.y + 3);
    expect(await td.evaluate(el => getComputedStyle(el).backgroundColor)).toBe(before);
    expect(await other.evaluate(el => getComputedStyle(el).backgroundColor)).toBe(editorBefore);
    expect(await td.evaluate(el => getComputedStyle(el).boxShadow)).toContain("rgba(128, 128, 128, 0.08)");
    expect(await td.locator(".cmh-table-cell-comment").evaluate(el => getComputedStyle(el).opacity)).toBe("1");
    await expect(td.locator(".cmh-table-cell-comment svg")).toHaveCount(1);
    await expect(td).toHaveCSS("transition-duration", "0s");
    await expect(cell(page)).toBeFocused();
    await expect(other).not.toBeFocused();
    await other.hover();
    expect(await other.evaluate(el => getComputedStyle(el).backgroundColor)).toBe(editorBefore);
    await other.click();
    await expect(other).toBeFocused();
  }
});

test("table action icons use accent hover styling and history tooltips describe the next edit (CMH-TABLE-17)", async ({ page }) => {
  await open(page);
  for (const theme of ["light", "dark"]) {
    await page.evaluate(value => document.documentElement.dataset.theme = value, theme);
    await page.mouse.move(0, 0);
    const reference = await page.locator("#btnToggleSidebar").evaluate(el => getComputedStyle(el).backgroundColor);
    for (const label of ["Add row", "Add column", "Undo", "Redo"]) {
      await expect(action(page, label).locator('svg[aria-hidden="true"]')).toHaveCount(1);
      await expect(action(page, label)).toHaveCSS("background-color", reference);
    }
    const before = await action(page, "Add row").evaluate(el => getComputedStyle(el).backgroundColor);
    await action(page, "Add row").hover();
    expect(await action(page, "Add row").evaluate(el => getComputedStyle(el).backgroundColor)).not.toBe(before);
  }
  await action(page, "Add row").click();
  await action(page, "Undo").hover();
  await expect(page.getByRole("tooltip")).toContainText("Undo: Added row");
  await action(page, "Undo").click();
  await action(page, "Redo").hover();
  await expect(page.getByRole("tooltip")).toContainText("Redo: Added row");
  await cell(page).fill("Updated <table>");
  await expect(action(page, "Undo")).toHaveAttribute("data-cmh-tip", /Discussion item.*Decide launch.*Updated <table>/);
  await expect(action(page, "Redo")).toBeDisabled();
  await action(page, "Undo").hover();
  await expect(page.getByRole("tooltip")).toContainText("Updated <table>");
  await action(page, "Undo").click();
  await expect(cell(page)).toHaveValue("Decide launch");
});

test("column menu icons preserve readable labels and working actions (CMH-TABLE-17)", async ({ page }) => {
  await open(page);
  const header = table(page).locator('[data-cmh-column="owner"]');
  await header.locator("summary").click();
  for (const name of ["Rename column", "Insert column before", "Insert column after", "Remove column"]) {
    const button = header.getByRole("button", { name, exact: true });
    await expect(button).toBeVisible();
    await expect(button.locator('svg[aria-hidden="true"]')).toBeVisible();
    await expect(button).toHaveText(name);
  }
  await header.getByRole("button", { name: "Rename column", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Rename column" });
  await dialog.getByLabel("Column name", { exact: true }).fill("Responsible person");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(header.locator(".cmh-table-title")).toHaveText("Responsible person");
});

test("row-boundary plus appears only near number-column borders (CMH-TABLE-18)", async ({ page }) => {
  await open(page);
  const row = table(page).locator('[data-cmh-row="second"]');
  const insert = row.getByRole("button", { name: "Insert row before row 2", exact: true });
  const number = await row.locator(".cmh-table-number").boundingBox();
  for (const target of [row.locator(".cmh-table-number"), row.locator("td").first(), row.locator("td").last()]) {
    const rect = await target.boundingBox();
    await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2);
    await expect(insert).toHaveCSS("opacity", "0");
  }
  const data = await row.locator("td").first().boundingBox();
  await page.mouse.move(data.x + data.width / 2, data.y + 1);
  await expect(insert).toHaveCSS("opacity", "0");
  await page.mouse.move(number.x + number.width / 2, number.y + 1);
  await expect(insert).toHaveCSS("opacity", "1");
  await page.mouse.move(data.x + data.width / 2, data.y + 1);
  await expect(insert).toHaveCSS("opacity", "0");
  await insert.focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(insert).toBeFocused();
  await expect(insert).toHaveCSS("opacity", "1");
  await page.keyboard.press("Enter");
  await expect(table(page).locator("tbody tr")).toHaveCount(3);
});

test("column headers highlight on hover and comment only through their icon (CMH-TABLE-14)", async ({ page }) => {
  await open(page);
  const header = table(page).locator('[data-cmh-column="owner"]');
  await header.locator(".cmh-table-title").click();
  await expect(page.locator(".cm-composer")).toHaveCount(0);
  const cells = table(page).locator('[data-cmh-cell-column="owner"]');
  await expect(cells.first()).not.toHaveCSS("box-shadow", "none");
  await page.locator("#after").hover();
  await expect(cells.first()).toHaveCSS("box-shadow", "none");
  await header.getByRole("button", { name: "Comment on Owner, column 2", exact: true }).click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("An explicit column discussion");
  await composer.locator('[data-act="save"]').click();
  await header.locator(".cmh-table-title").click();
  await expect(page.locator(".cm-composer")).toHaveCount(0);
  await expect(header.locator(".cmh-table-title")).toHaveAttribute("data-cids", /c/);
});

test("header dragging shows the landing boundary throughout the target column (CMH-TABLE-15)", async ({ page }) => {
  await open(page);
  const source = table(page).locator('[data-cmh-column="question"]');
  const target = table(page).locator('[data-cmh-column="owner"]');
  const start = await source.locator(".cmh-table-title").boundingBox();
  const end = await target.boundingBox();
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  await page.mouse.move(end.x + end.width * .8, end.y + end.height / 2, { steps: 8 });
  await expect(target).toHaveClass(/cmh-table-drop-after/);
  const landing = table(page).locator('[data-cmh-cell-column="owner"]');
  await expect(landing).toHaveCount(2);
  for (const td of await landing.all()) await expect(td).toHaveCSS("box-shadow", /6px/);
  await page.mouse.up();
  expect(await columnIds(page)).toEqual(["owner", "question", "status"]);
  await expect(table(page).locator(".cmh-table-drop-before, .cmh-table-drop-after")).toHaveCount(0);
  await expect(page.locator(".cm-composer")).toHaveCount(0);
  await expect(grip(page, "question")).toBeVisible();
  await table(page).getByRole("button", { name: "Sort by Discussion item, column 2", exact: true }).click();
  expect(await columnIds(page)).toEqual(["owner", "question", "status"]);
});

test("title dragging keeps a clipped grip from scrolling the table (CMH-TABLE-15)", async ({ page }) => {
  await page.setViewportSize({ width: 700, height: 900 });
  await open(page, DOC.replace('data-cmh-column="question"', 'data-cmh-column="question" data-cmh-width="700"'));
  const scroll = table(page).locator("..");
  await scroll.evaluate(el => { el.scrollLeft = 200; });
  const viewport = await scroll.boundingBox();
  const handle = await grip(page, "question").boundingBox();
  const title = await table(page).locator('[data-cmh-column="question"] .cmh-table-title').boundingBox();
  expect(handle.x + handle.width).toBeLessThan(viewport.x);
  const before = await scroll.evaluate(el => el.scrollLeft);
  await page.mouse.move(viewport.x + 80, title.y + title.height / 2);
  await page.mouse.down();
  expect(await scroll.evaluate(el => el.scrollLeft)).toBe(before);
  await page.mouse.up();
  expect(await scroll.evaluate(el => el.scrollLeft)).toBe(before);
  expect(await columnIds(page)).toEqual(["question", "owner", "status"]);
  await expect(page.locator(".cm-composer, .cm-card-table")).toHaveCount(0);
});

test("boundary insertion clears sorting and inserts beside the stable target row (CMH-TABLE-18)", async ({ page }) => {
  await open(page);
  const sort = table(page).getByRole("button", { name: "Sort by row number", exact: true });
  await sort.click(); await sort.click();
  await table(page).getByRole("button", { name: "Insert row before row 2", exact: true }).click();
  const rows = table(page).locator("tbody tr"), inserted = await rows.nth(1).getAttribute("data-cmh-row");
  expect(await rows.evaluateAll(items => items.map(row => row.dataset.cmhRow))).toEqual(["first", inserted, "second"]);
  await expect(cell(page, inserted)).toBeFocused();
  await expect(cell(page, inserted, "status")).toHaveValue("Open");
  await expect(sort).not.toHaveAttribute("data-dir", /asc|desc/);
  const { payload } = await bundle(page);
  expect(payload.tables[0].to.rows[1]).toEqual({ id: inserted, cells: ["", "", "Open"] });
  await action(page, "Undo").click();
  await expect(rows).toHaveCount(2);
  await action(page, "Redo").click();
  expect(await rows.nth(1).getAttribute("data-cmh-row")).toBe(inserted);
});

test("bottom New appends a row on mobile and works in an empty table (CMH-TABLE-18)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, DOC.replace(/<tbody>[\s\S]*?<\/tbody>/, "<tbody></tbody>"));
  const bottom = page.locator(".cmh-table-add-bottom");
  await expect(bottom).toBeVisible();
  await expect(bottom).toHaveAccessibleName("Add row at bottom");
  await bottom.click();
  await expect(table(page).locator("tbody tr")).toHaveCount(1);
  await expect(table(page).locator("textarea").first()).toBeFocused();
  await bottom.click();
  await expect(table(page).locator("tbody tr")).toHaveCount(2);
  await expect(table(page).locator("tbody tr").last().locator("textarea").first()).toBeFocused();
});

test("sort and column menu stay grouped at the header end (CMH-TABLE-19)", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await open(page);
  await table(page).evaluate(el => el.style.width = "1300px");
  const header = table(page).locator('[data-cmh-column="question"]');
  const th = await header.boundingBox(), menu = await header.locator("summary").boundingBox();
  const sort = await header.locator(".cmh-sort-ctrl").boundingBox();
  expect(th.x + th.width - menu.x - menu.width).toBeLessThanOrEqual(12);
  expect(sort.x + sort.width).toBeLessThanOrEqual(menu.x + 1);
  await header.locator(".cmh-table-column-comment").click();
  await expect(page.locator(".cm-composer").last()).toBeVisible();
});

test("column border resizing tracks width through history persistence and export (CMH-TABLE-20)", async ({ page }) => {
  const staged = await open(page);
  const header = table(page).locator('[data-cmh-column="question"]');
  const handle = header.getByRole("separator", { name: "Resize Discussion item, column 1", exact: true });
  await expect(handle).toBeVisible();
  const original = await header.boundingBox(), edge = await handle.boundingBox();
  await page.mouse.move(edge.x + edge.width / 2, edge.y + edge.height / 2);
  await page.mouse.down();
  await page.mouse.move(edge.x + 85, edge.y + edge.height / 2, { steps: 8 });
  await page.mouse.up();
  const resized = await header.boundingBox();
  expect(resized.width).toBeGreaterThan(original.width + 40);
  await expect(page.locator(".cm-card-table")).toHaveCount(1);
  const { text, payload } = await bundle(page);
  expect(text).toMatch(/width.*px/i);
  expect(payload.tables[0].to.columns[0].width).toBeGreaterThan(0);
  await action(page, "Undo").click();
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
  await action(page, "Redo").click();
  await page.goto(fileUrl(staged.html)); await ready(page);
  expect((await header.boundingBox()).width).toBeCloseTo(resized.width, 0);
  const download = page.waitForEvent("download");
  await clickSidebarExport(page, "#btnSaveHtml");
  const output = path.join(path.dirname(staged.html), "resized.html");
  fs.writeFileSync(output, await readDownload(await download));
  await page.goto(fileUrl(output)); await ready(page);
  expect((await header.boundingBox()).width).toBeCloseTo(resized.width, 0);
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
});

test("recovery cannot be bypassed by dragging a disabled column grip (CMH-TABLE-08)", async ({ page }) => {
  await open(page);
  await cell(page).fill("Saved stale draft");
  await page.evaluate(() => {
    const data = JSON.parse(localStorage.getItem("cmh-table-test::tables"));
    data.tables[0].from.rows[0].cells[0] = "Old source";
    localStorage.setItem("cmh-table-test::tables", JSON.stringify(data));
  });
  await page.reload(); await ready(page);
  const saved = await page.evaluate(() => localStorage.getItem("cmh-table-test::tables"));
  await dragColumn(page, "question", "status");
  expect(await columnIds(page)).toEqual(["question", "owner", "status"]);
  await expect(cell(page)).toBeDisabled();
  expect(await page.evaluate(() => localStorage.getItem("cmh-table-test::tables"))).toBe(saved);
});

test("hovered Undo tooltip refreshes while editing continues (CMH-TABLE-17)", async ({ page }) => {
  await open(page);
  await cell(page).fill("First revision");
  await action(page, "Undo").hover();
  await expect(page.getByRole("tooltip")).toContainText("First revision");
  await page.keyboard.type(" plus another edit");
  await expect(page.getByRole("tooltip")).toContainText("plus another edit");
});

test("whole-cell highlighting also works with the body fallback root (CMH-TABLE-09)", async ({ page }) => {
  await open(page, '<script>document.getElementById("commentRoot").removeAttribute("id");</script>' + DOC);
  await page.mouse.move(0, 0);
  const td = cell(page).locator(".."), before = await td.evaluate(el => getComputedStyle(el).boxShadow);
  const bounds = await td.boundingBox();
  await page.mouse.move(bounds.x + 3, bounds.y + 3);
  expect(await td.evaluate(el => getComputedStyle(el).boxShadow)).not.toBe(before);
});

test("numeric columns sort signed decimals and exponents and reject invalid edits (CMH-TABLE-21)", async ({ page }) => {
  await open(page);
  await addColumn(page, "Estimate", "number");
  const numeric = table(page).locator("thead th[data-cmh-column]").last(), id = await numeric.getAttribute("data-cmh-column");
  await cell(page, "first", id).fill("1e2");
  await cell(page, "second", id).fill("-2.5");
  await numeric.getByRole("button", { name: /Sort by Estimate/ }).click();
  expect(await table(page).locator("tbody tr").evaluateAll(rows => rows.map(row => row.dataset.cmhRow))).toEqual(["second", "first"]);
  await cell(page, "second", id).fill("not a number");
  await expect(cell(page, "second", id)).toHaveAttribute("aria-invalid", "true");
  await cell(page).focus();
  await expect(cell(page, "second", id)).toHaveValue("-2.5");
  const { payload } = await bundle(page);
  expect(payload.tables[0].to.columns.at(-1).type).toBe("number");
  expect(payload.tables[0].to.rows[0].cells.at(-1)).toBe("1e2");
  expect(payload.tables[0].to.rows[1].cells.at(-1)).toBe("-2.5");
});

test("autofit width is a tracked undoable column-menu action (CMH-TABLE-20)", async ({ page }) => {
  await open(page);
  const header = table(page).locator('[data-cmh-column="owner"]');
  await header.locator("summary").click();
  await header.getByRole("button", { name: "Autofit width", exact: true }).click();
  const { payload } = await bundle(page);
  expect(payload.tables[0].to.columns[1].width).toBeGreaterThan(0);
  await expect(header.getByRole("separator")).toHaveAttribute("aria-valuenow", String(payload.tables[0].to.columns[1].width));
  await action(page, "Undo").click();
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
});

test("cell comments follow stable row and column identities and survive removal undo and export (CMH-TABLE-22)", async ({ page }) => {
  const staged = await open(page);
  const target = table(page).getByRole("button", { name: "Comment on Owner, column 2, row 1", exact: true });
  await expect(target).toBeVisible();
  await target.click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("Cell decision: confirm this owner.");
  await composer.locator('[data-act="save"]').click();
  await cell(page, "first", "owner").fill("Casey");
  await dragColumn(page, "owner", "status");
  await expect(cell(page, "first", "owner")).toHaveValue("Casey");
  await expect(cell(page, "first", "status")).toHaveValue("Open");
  await expect(cell(page, "first", "owner").locator("..")).toHaveAttribute("data-cids", /c/);
  const { text } = await bundle(page);
  expect(text).toContain("Cell decision: confirm this owner.");
  await table(page).getByRole("button", { name: "Remove row 1", exact: true }).click();
  await page.locator(".cm-modal").getByRole("button", { name: "Remove", exact: true }).click();
  await expect(page.locator(".cm-card").filter({ hasText: "Cell decision:" })).toContainText("removed or unavailable");
  await action(page, "Undo").click();
  await expect(cell(page, "first", "owner").locator("..")).toHaveAttribute("data-cids", /c/);
  const download = page.waitForEvent("download");
  await clickSidebarExport(page, "#btnSaveHtml");
  const exported = path.join(path.dirname(staged.html), "cell-comment.html");
  fs.writeFileSync(exported, await readDownload(await download));
  await page.goto(fileUrl(exported)); await ready(page);
  await expect(cell(page, "first", "owner").locator("..")).toHaveAttribute("data-cids", /c/);
  await expect(page.locator(".cm-card").filter({ hasText: "Cell decision:" })).toBeVisible();
  const embedded = await page.locator("#embeddedComments").textContent();
  expect(JSON.parse(embedded)).toEqual(expect.arrayContaining([expect.objectContaining({ anchorType: "table-cell", tableId: "agenda", columnId: "owner", rowId: "first", quote: "Alex" })]));
});

test("table tooltips match the Add Comment accent and pill treatment (CMH-TABLE-23)", async ({ page }) => {
  await open(page);
  await table(page).locator(".cmh-table-column-comment").first().hover();
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toBeVisible();
  const accent = await page.locator("#btnCopyAllTop").evaluate(el => getComputedStyle(el).backgroundColor);
  await expect(tooltip).toHaveCSS("background-color", accent);
  const shape = await tooltip.evaluate(el => getComputedStyle(el).borderRadius);
  expect(parseFloat(shape)).toBeGreaterThanOrEqual(20);
});

test("cell threads retain row context through replies copy search Markdown print and deletion (CMH-TABLE-22)", async ({ page }) => {
  await open(page);
  const td = cell(page, "first", "owner").locator("..");
  await td.getByRole("button", { name: /Comment on Owner/ }).click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("Cell discussion with precise context.");
  await composer.locator('[data-act="save"]').click();
  await page.mouse.move(0, 0);
  const marker = await td.evaluate(el => getComputedStyle(el).boxShadow);
  expect(marker).not.toBe("none");
  await td.hover();
  expect(await td.evaluate(el => getComputedStyle(el).boxShadow)).toContain(marker);
  const card = page.locator(".cm-card").filter({ hasText: "Cell discussion with precise context." });
  await card.locator(".cm-reply-btn").click();
  await card.locator(".cm-reply-compose textarea").fill("Confirm the allocation.");
  await card.locator(".cm-reply-save").click();
  await page.locator("#btnCopyAll").click();
  const copied = await copiedBundle(page);
  expect(copied).toContain('Anchor: table "agenda", row "first", column "owner"');
  expect(copied).toContain("Confirm the allocation.");
  expect(await page.evaluate(() => window.__cmhToMarkdown())).toContain('table "agenda" / row "first" / column "owner"');
  await openSearch(page);
  await page.locator("#cmSearchInput").fill("precise context");
  await expect(card).toBeVisible();
  await page.locator("#cmSearchInput").fill("");
  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  await expect(page.locator("#cmhPrintComments")).toContainText("Table agenda - row first - column owner");
  await page.emulateMedia({ media: "screen" });
  await page.evaluate(() => window.dispatchEvent(new Event("afterprint")));
  page.once("dialog", dialog => dialog.accept());
  await card.getByTitle("Delete this comment and its replies", { exact: true }).click();
  await expect(td).not.toHaveAttribute("data-cids", /c/);
  await page.reload(); await ready(page);
  await expect(page.locator(".cm-card").filter({ hasText: "Cell discussion with precise context." })).toHaveCount(0);
});

test("authored column widths reject noncanonical numeric spellings (CMH-TABLE-08)", async ({ page }) => {
  for (const width of ["1e2", "100.0", " 100 ", "+100"]) {
    await open(page, DOC.replace('data-cmh-column="owner"', `data-cmh-column="owner" data-cmh-width="${width}"`));
    await expect(page.locator(".cmh-editable-table")).toHaveCount(0);
    await expect(table(page).locator("tbody td").first()).toHaveText("Decide launch");
  }
});

test("column dragging dismisses an already visible grip tooltip (CMH-TABLE-15)", async ({ page }) => {
  await open(page);
  const start = await grip(page, "question").boundingBox();
  await grip(page, "question").hover();
  await expect(page.getByRole("tooltip")).toBeVisible();
  await page.mouse.down();
  await page.mouse.move(start.x + start.width + 20, start.y + start.height / 2, { steps: 3 });
  await expect(page.getByRole("tooltip")).toHaveCSS("opacity", "0");
  await page.keyboard.press("Escape"); await page.mouse.up();
});

test("resize cancellation and keyboard bounds preserve one tracked operation (CMH-TABLE-20)", async ({ page }) => {
  await open(page);
  const header = table(page).locator('[data-cmh-column="question"]'), handle = header.getByRole("separator");
  const original = await header.boundingBox(), edge = await handle.boundingBox(), aria = await handle.getAttribute("aria-valuenow");
  await page.mouse.move(edge.x + edge.width / 2, edge.y + edge.height / 2); await page.mouse.down();
  await page.mouse.move(edge.x + 100, edge.y + edge.height / 2, { steps: 3 });
  await page.keyboard.press("Escape"); await page.mouse.up();
  expect((await header.boundingBox()).width).toBeCloseTo(original.width, 0);
  await expect(handle).toHaveAttribute("aria-valuenow", aria);
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
  await handle.focus(); await page.keyboard.press("ArrowRight");
  const { payload } = await bundle(page);
  expect(payload.tables[0].to.columns[0].width).toBeGreaterThanOrEqual(96);
  await action(page, "Undo").click();
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
});

test("numeric whitespace has identical browser and author-tool interpretation (CMH-TABLE-21)", async ({ page }) => {
  await open(page);
  await addColumn(page, "Estimate", "number");
  const id = await table(page).locator("thead th[data-cmh-column]").last().getAttribute("data-cmh-column");
  for (const value of ["\uFEFF12", "\u00a0-.25e2\u2029", "\uFEFF"]) {
    await cell(page, "first", id).fill(value);
    await expect(cell(page, "first", id)).not.toHaveAttribute("aria-invalid", "true");
    const { payload } = await bundle(page);
    const check = spawnSync(PYTHON, ["-c",
      "import json,sys; sys.path.insert(0,sys.argv[1]); from tables_common import validate_payload; print(json.dumps(validate_payload(json.loads(sys.stdin.buffer.read().decode('utf-8')))))",
      path.join(SKILL, "tools", "tables")], { encoding: "utf8", input: JSON.stringify(payload) });
    expect(check.stderr).toBe("");
    expect(check.status).toBe(0);
    expect(JSON.parse(check.stdout).tables[0].to.rows[0].cells.at(-1)).toBe(value);
  }
});

test("invalid sequential numeric edits restore the pre-edit value without history (CMH-TABLE-21)", async ({ page }) => {
  await open(page, DOC.replace('data-cmh-column="question"', 'data-cmh-column="question" data-cmh-column-type="number"')
    .replace("Decide launch", "500").replace("Review evidence", "2"));
  const input = cell(page);
  for (const value of ["1,000", "25$", "10%", "1e999", "1e"]) {
    await cell(page, "first", "owner").fill("Temporary owner");
    await action(page, "Undo").click();
    await expect(action(page, "Redo")).toBeEnabled();
    await input.focus(); await input.press("ControlOrMeta+A");
    await input.pressSequentially(value);
    await expect(input).toHaveAttribute("aria-invalid", "true");
    await page.locator("#after").click();
    await expect(input).toHaveValue("500");
    await expect(page.locator(".cm-card-table")).toHaveCount(0);
    await expect(action(page, "Undo")).toBeDisabled();
    await expect(action(page, "Redo")).toBeEnabled();
    await page.reload(); await ready(page);
    await expect(cell(page)).toHaveValue("500");
  }
});

test("removing the last sized column clears baked layout on export (CMH-TABLE-20)", async ({ page }) => {
  const staged = await open(page, DOC.replace('<table data-cmh-table=', '<table style="table-layout:fixed;width:793px" data-cmh-table=')
    .replace('data-cmh-column="question"', 'data-cmh-column="question" data-cmh-width="300"'));
  const header = table(page).locator('[data-cmh-column="question"]');
  await header.locator("summary").click();
  await header.getByRole("button", { name: "Remove column", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove", exact: true }).click();
  const [download] = await Promise.all([page.waitForEvent("download"), clickSidebarExport(page, "#btnSaveHtml")]);
  const html = await readDownload(download);
  const sizing = await page.evaluate(source => {
    const table = new DOMParser().parseFromString(source, "text/html").querySelector('[data-cmh-table="agenda"]');
    return [table.style.tableLayout, table.style.width];
  }, html);
  expect(sizing).toEqual(["", ""]);
  const exported = path.join(path.dirname(staged.html), "unsized.html");
  fs.writeFileSync(exported, html);
  await page.goto(fileUrl(exported)); await ready(page);
  expect(await columnIds(page)).toEqual(["owner", "status"]);
});

test("missing cell anchors identify the cell rather than its surviving column (CMH-TABLE-22)", async ({ page }) => {
  await open(page);
  await table(page).getByRole("button", { name: "Comment on Owner, column 2, row 1", exact: true }).click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("Keep this cell discussion.");
  await composer.locator('[data-act="save"]').click();
  const card = page.locator(".cm-card").filter({ hasText: "Keep this cell discussion." });
  await expect(card.getByRole("button", { name: "jump", exact: true })).toHaveAttribute("title", "Scroll to highlighted table cell");
  await table(page).getByRole("button", { name: "Remove row 1", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove", exact: true }).click();
  await expect(card.locator(".pin")).toContainText('cell (removed or unavailable)');
  await card.getByRole("button", { name: "jump", exact: true }).click();
  await expect(page.locator(".cm-toast")).toContainText("This table cell was removed or is unavailable.");
  await expect(table(page).locator('[data-cmh-column="owner"]')).toBeVisible();
});

test("cell comment ordering is row-major with column titles before cells (CMH-TABLE-22)", async ({ page }) => {
  await open(page);
  for (const [label, note] of [
    ["Comment on Discussion item, column 1, row 2", "Second row discussion"],
    ["Comment on Owner, column 2, row 1", "First row discussion"],
    ["Comment on Owner, column 2", "Header discussion"],
  ]) {
    await table(page).getByRole("button", { name: label, exact: true }).click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill(note);
    await composer.locator('[data-act="save"]').click();
  }
  await page.locator("#btnCopyAll").click();
  const text = await copiedBundle(page);
  expect(text.indexOf("Header discussion")).toBeLessThan(text.indexOf("First row discussion"));
  expect(text.indexOf("First row discussion")).toBeLessThan(text.indexOf("Second row discussion"));
  const cards = await page.locator('.cm-card:not(.cm-card-table) .note').allTextContents();
  expect(cards.filter(note => /discussion$/.test(note))).toEqual(["Header discussion", "First row discussion", "Second row discussion"]);
});

test("empty cell comments preserve an empty original quote (CMH-TABLE-22)", async ({ page }) => {
  await open(page);
  await table(page).getByRole("button", { name: "Comment on Owner, column 2, row 2", exact: true }).click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("Who owns this empty assignment?");
  await composer.locator('[data-act="save"]').click();
  await expect(page.locator(".cm-card .quote")).toContainText("(empty)");
  const [download] = await Promise.all([page.waitForEvent("download"), clickSidebarExport(page, "#btnSaveHtml")]);
  const html = await readDownload(download);
  const embedded = JSON.parse(html.match(/<script[^>]*id="embeddedComments"[^>]*>([\s\S]*?)<\/script>/)[1]);
  expect(embedded[0]).toMatchObject({ anchorType: "table-cell", rowId: "second", columnId: "owner", quote: "" });
});

test("unspecified column widths remain responsive beside an explicitly resized column (CMH-TABLE-20)", async ({ page }) => {
  await page.setViewportSize({ width: 1300, height: 900 });
  await open(page, '<div style="width:70vw">' + DOC + "</div>");
  const header = table(page).locator('[data-cmh-column="question"]');
  await header.getByRole("separator").focus(); await page.keyboard.press("ArrowRight");
  await page.getByRole("button", { name: "Hide", exact: true }).click();
  await page.evaluate(() => Promise.all(document.getAnimations().map(a => a.finished.catch(() => {}))));
  const owner = table(page).locator('[data-cmh-column="owner"]'), before = await owner.boundingBox();
  const fixed = await header.boundingBox();
  await page.setViewportSize({ width: 1800, height: 900 });
  await expect.poll(async () => (await owner.boundingBox()).width).toBeGreaterThan(before.width + 10);
  expect((await header.boundingBox()).width).toBeCloseTo(fixed.width, 0);
});

test("utility columns fit compact controls and multi-digit row numbers (CMH-TABLE-09)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const rows = Array.from({ length: 12 }, (_, i) =>
    `<tr data-cmh-row="r${i}"><td>Item ${i}</td><td>Owner</td><td>Open</td></tr>`).join("");
  await open(page, DOC.replace(/<tbody>[\s\S]*?<\/tbody>/, `<tbody>${rows}</tbody>`));
  const row = table(page).locator("tbody tr").last();
  const remove = row.getByRole("button", { name: "Remove row 12", exact: true });
  await expect(remove.locator("svg")).toBeVisible();
  const button = await remove.boundingBox(), actionCell = await remove.locator("..").boundingBox();
  const number = await row.locator("th").boundingBox();
  expect(button.width).toBeLessThanOrEqual(36);
  expect(actionCell.width).toBeLessThanOrEqual(button.width + 18);
  expect(number.width).toBeLessThanOrEqual(64);
  await expect(row.locator("th")).toHaveText("12");
});

test("column actions use a vertical ellipsis menu with insertion on either side (CMH-TABLE-04)", async ({ page }) => {
  await open(page);
  const header = table(page).locator('[data-cmh-column="owner"]');
  const trigger = header.locator("summary");
  await expect(trigger.locator("svg")).toBeVisible();
  await expect(trigger).not.toContainText("Column");
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(header.getByRole("button", { name: "Insert column before", exact: true })).toBeVisible();
  const rename = await header.getByRole("button", { name: "Rename column", exact: true }).boundingBox();
  const before = await header.getByRole("button", { name: "Insert column before", exact: true }).boundingBox();
  expect(before.y).toBeGreaterThanOrEqual(rename.y + rename.height - 1);
  await header.getByRole("button", { name: "Insert column before", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Add column" });
  await dialog.getByLabel("Column name", { exact: true }).fill("Before owner");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(table(page).locator("thead th[data-cmh-column]")).toHaveText([
    /Discussion item/, /Before owner/, /Owner/, /Status/,
  ]);
});

test("column menus stay attached to their trigger inside scaled containers (CMH-TABLE-04)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await open(page, `<div style="transform:translate(80px,120px) scale(.7);transform-origin:top left">${DOC}</div>`);
  const header = table(page).locator('[data-cmh-column="owner"]');
  await header.locator("summary").click();
  const panel = header.locator(".cmh-table-column-menu");
  await expect(panel).toBeVisible();
  await expect.poll(async () => {
    const trigger = await header.locator("summary").boundingBox(), menu = await panel.boundingBox();
    return Math.abs(menu.y - trigger.y - trigger.height - 4);
  }).toBeLessThan(2);
  const trigger = await header.locator("summary").boundingBox(), menu = await panel.boundingBox();
  expect(Math.abs(menu.x + menu.width - trigger.x - trigger.width)).toBeLessThan(2);
  await header.getByRole("button", { name: "Insert column before", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Add column" })).toBeVisible();
});

test("column menus close on keyboard departure without discarding a composer draft (CMH-TABLE-04)", async ({ page }) => {
  await open(page);
  const composer = await openComposerFor(page, "#after");
  await composer.locator("textarea").fill("Keep this draft");
  const header = table(page).locator('[data-cmh-column="owner"]'), details = header.locator("details");
  await header.locator("summary").focus();
  await page.keyboard.press("Enter");
  await header.getByRole("button", { name: "Remove column", exact: true }).focus();
  await page.keyboard.press("Tab");
  await expect(details).not.toHaveAttribute("open", "");
  await expect(composer.locator("textarea")).toHaveValue("Keep this draft");
});

test("column menus leave authored caption disclosures untouched (CMH-TABLE-04)", async ({ page }) => {
  const captionHtml = '<caption><details id="caption-details" open><summary>Authored context</summary><p>Keep this explanation visible.</p></details></caption>';
  await open(page, DOC.replace("<thead>", captionHtml + "<thead>"));
  const caption = page.locator("#caption-details"), authored = caption.locator("summary");
  await expect(caption).toHaveAttribute("open", "");
  await page.locator("#after").click();
  await expect(caption).toHaveAttribute("open", "");
  await authored.focus();
  await page.keyboard.press("Escape");
  await expect(caption).toHaveAttribute("open", "");
  await page.setViewportSize({ width: 1440, height: 1100 });
  await expect(caption).toHaveAttribute("open", "");
  const header = table(page).locator('[data-cmh-column="owner"]');
  await header.locator("summary").click();
  await expect(header.locator(".cmh-table-column-menu")).toBeVisible();
  await expect(caption).toHaveAttribute("open", "");
  await authored.click();
  await expect(header.locator("details")).not.toHaveAttribute("open", "");
  await expect(caption).not.toHaveAttribute("open", "");
  await authored.click();
  await expect(caption).toHaveAttribute("open", "");
  await page.emulateMedia({ media: "print" });
  await expect(caption.getByText("Keep this explanation visible.")).toBeVisible();
});

test("column titles inherit authored contrasting header colors (CMH-TABLE-09)", async ({ page }) => {
  await open(page, '<style>#commentRoot [data-cmh-table] thead th{background:#17233b;color:#f8fafc}</style>' + DOC);
  const header = table(page).locator('[data-cmh-column="owner"]');
  await expect(header.locator(".cmh-table-title")).toHaveCSS("color", await header.evaluate(el => getComputedStyle(el).color));
});

test("column comments retain section context when their column disappears before save (CMH-TABLE-14)", async ({ page }) => {
  await open(page, DOC.replace("<h1>", '<h1 id="table-section">'));
  const header = table(page).locator('[data-cmh-column="owner"]');
  await header.locator(".cmh-table-column-comment").click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("Discuss this removed column");
  await header.locator("summary").focus();
  await page.keyboard.press("Enter");
  await header.getByRole("button", { name: "Remove column", exact: true }).focus();
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await composer.locator('[data-act="save"]').click();
  await expect(page.locator("#table-section .cmh-review-badge")).toHaveAttribute("data-cmh-label", "Commented");
  await page.locator("#btnCopyAll").click();
  expect(await copiedBundle(page)).toContain('Where: H1 "Editable table"');
});

test("row numbers and data columns use ordinary numeric sort chevrons without changing the model (CMH-TABLE-05)", async ({ page }) => {
  await open(page, DOC.replace("Decide launch", "$1,000").replace("Review evidence", "$20")
    + '<table id="ordinary"><thead><tr><th>Native number</th></tr></thead><tbody><tr><td>10</td></tr><tr><td>2</td></tr></tbody></table>');
  const sort = table(page).getByRole("button", { name: "Sort by Discussion item, column 1", exact: true });
  const nativeStyle = await page.locator("#ordinary .cmh-sort-ctrl").evaluate(el => {
    const style = getComputedStyle(el);
    return { font: style.fontSize, line: style.lineHeight, color: style.color };
  });
  await expect(sort).toHaveCSS("font-size", nativeStyle.font);
  await expect(sort).toHaveCSS("line-height", nativeStyle.line);
  await expect(sort).toHaveCSS("color", nativeStyle.color);
  await expect(sort.locator(".cmh-sort-up")).toHaveCount(1);
  await expect(sort.locator(".cmh-sort-dn")).toHaveCount(1);
  await sort.click();
  expect(await table(page).locator("tbody tr").evaluateAll(rows => rows.map(row => row.dataset.cmhRow))).toEqual(["second", "first"]);
  await expect(table(page).locator("tbody th")).toHaveText(["2", "1"]);
  const numbers = table(page).getByRole("button", { name: "Sort by row number", exact: true });
  await numbers.click();
  await expect(table(page).locator("tbody th")).toHaveText(["1", "2"]);
  await numbers.click();
  await expect(table(page).locator("tbody th")).toHaveText(["2", "1"]);
  await numbers.click();
  await expect(table(page).locator("tbody th")).toHaveText(["1", "2"]);
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
});

test("editable cells reveal hover and keyboard-focus feedback in both themes (CMH-TABLE-09)", async ({ page }) => {
  await open(page);
  for (const theme of ["light", "dark"]) {
    await page.evaluate(value => document.documentElement.dataset.theme = value, theme);
    await page.mouse.move(0, 0);
    const editor = cell(page);
    const colors = () => editor.evaluate(el => {
      const style = getComputedStyle(el);
      return [getComputedStyle(el.parentElement).boxShadow, style.borderTopColor];
    });
    const idle = await colors();
    await editor.hover();
    expect(await colors()).not.toEqual(idle);
    await editor.focus();
    await page.mouse.move(0, 0);
    expect(await colors()).not.toEqual(idle);
    await editor.blur();
  }
});

test("column-title comments retain identity through rename sort reload and export (CMH-TABLE-14)", async ({ page }) => {
  const staged = await open(page);
  await addTextComment(page, "#after", "Keep this prose anchor.");
  const title = table(page).getByRole("button", { name: "Comment on Owner, column 2", exact: true });
  await title.click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("Who owns this decision?");
  await composer.locator('[data-act="save"]').click();
  const header = table(page).locator('[data-cmh-column="owner"]');
  await expect(header.locator(".cmh-table-title")).toHaveAttribute("data-cids", /c/);
  await header.locator("summary").click();
  await header.getByRole("button", { name: "Rename column", exact: true }).click();
  await page.getByRole("dialog").getByLabel("Column name", { exact: true }).fill("Accountable owner");
  await page.getByRole("dialog").getByRole("button", { name: "Save", exact: true }).click();
  await header.locator("summary").click();
  await header.getByRole("button", { name: "Insert column before", exact: true }).click();
  await page.getByRole("dialog").getByLabel("Column name", { exact: true }).fill("Reviewer");
  await page.getByRole("dialog").getByRole("button", { name: "Save", exact: true }).click();
  await table(page).getByRole("button", { name: "Sort by Discussion item, column 1", exact: true }).click();
  await page.goto(fileUrl(staged.html));
  await ready(page);
  await expect(header.locator(".cmh-table-title")).toHaveAttribute("data-cids", /c/);
  await expect(page.locator("#after mark.cm-hl")).toHaveText("railing reviewable prose.");
  const { text } = await bundle(page);
  expect(text).toContain('Anchor: table "agenda", column "owner"');
  expect(text).toContain("Who owns this decision?");
  const download = page.waitForEvent("download");
  await clickSidebarExport(page, "#btnSaveHtml");
  const html = await readDownload(await download);
  const output = path.join(path.dirname(staged.html), "title-export.html");
  fs.writeFileSync(output, html);
  const validation = spawnSync(PYTHON, [path.join(SKILL, "tools/validate/validate.py"), "--strict", "--no-stamp", output], { encoding: "utf8" });
  expect(validation.stdout + validation.stderr).toContain("OK");
  expect(validation.status).toBe(0);
  await page.goto(fileUrl(output));
  await ready(page);
  await expect(header.locator(".cmh-table-title")).toHaveAttribute("data-cids", /c/);
  await expect(header.locator(".cmh-table-title")).toHaveText("Accountable owner");
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
});

test("removing a commented column preserves its thread and Undo restores its title anchor (CMH-TABLE-14)", async ({ page }) => {
  await open(page);
  const title = table(page).getByRole("button", { name: "Comment on Owner, column 2", exact: true });
  await title.focus();
  await page.keyboard.press("Enter");
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("Keep this column discussion.");
  await composer.locator('[data-act="save"]').click();
  const header = table(page).locator('[data-cmh-column="owner"]');
  await header.locator("summary").click();
  await header.getByRole("button", { name: "Remove column", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove", exact: true }).click();
  await expect(page.locator(".cm-card").filter({ hasText: "Keep this column discussion." })).toBeVisible();
  await expect(table(page).locator(".cmh-table-title[data-cids]")).toHaveCount(0);
  await addColumn(page, "Owner");
  await expect(table(page).locator(".cmh-table-title[data-cids]")).toHaveCount(0);
  await action(page, "Undo").click();
  await action(page, "Undo").click();
  await expect(header.locator(".cmh-table-title")).toHaveAttribute("data-cids", /c/);
  await expect(page.locator(".cm-card").filter({ hasText: "Keep this column discussion." })).toHaveCount(1);
});

test("exported orphan column comments never attach to newly allocated column ids (CMH-TABLE-14)", async ({ page }) => {
  const { dir } = await open(page);
  await addColumn(page, "Temporary");
  const header = table(page).locator("thead th[data-cmh-column]").last();
  const id = await header.getAttribute("data-cmh-column");
  await header.getByRole("button", { name: "Comment on Temporary, column 4", exact: true }).click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("Retain this removed-column discussion.");
  await composer.locator('[data-act="save"]').click();
  await header.locator("summary").click();
  await header.getByRole("button", { name: "Remove column", exact: true }).click();
  const [download] = await Promise.all([page.waitForEvent("download"), clickSidebarExport(page, "#btnSaveHtml")]);
  const output = path.join(dir, "orphan-export.html");
  fs.writeFileSync(output, await readDownload(download));
  await page.goto(fileUrl(output));
  await ready(page);
  await addColumn(page, "Replacement");
  await expect(table(page).locator("thead th[data-cmh-column]").last()).not.toHaveAttribute("data-cmh-column", id);
  await expect(table(page).locator(".cmh-table-title[data-cids]")).toHaveCount(0);
  await expect(page.locator(".cm-card").filter({ hasText: "Retain this removed-column discussion." })).toContainText("removed or unavailable");
});

test("column-title threads support replies individual deletion copy and print (CMH-TABLE-14)", async ({ page }) => {
  await open(page);
  const comment = table(page).getByRole("button", { name: "Comment on Owner, column 2", exact: true });
  const title = table(page).locator('[data-cmh-column="owner"] .cmh-table-title');
  for (const note of ["First title discussion.", "Second title discussion."]) {
    await comment.click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill(note);
    await composer.locator('[data-act="save"]').click();
  }
  const ids = await title.getAttribute("data-cids");
  expect(ids.split(" ")).toHaveLength(2);
  const second = page.locator(".cm-card").filter({ hasText: "Second title discussion." });
  await second.locator(".cm-reply-btn").click();
  await second.locator(".cm-reply-compose textarea").fill("A reply about the accountable owner.");
  await second.locator(".cm-reply-save").click();
  await expect(second).toContainText("A reply about the accountable owner.");
  await page.locator("#btnCopyAll").click();
  const copied = await copiedBundle(page);
  expect(copied).toContain('Anchor: table "agenda", column "owner"');
  expect(copied).toContain("A reply about the accountable owner.");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain('table "agenda" / column "owner"');
  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  await expect(page.locator("#cmhPrintComments")).toContainText("Table agenda - column owner");
  await page.emulateMedia({ media: "screen" });
  await page.evaluate(() => window.dispatchEvent(new Event("afterprint")));
  page.once("dialog", dialog => dialog.accept());
  await page.locator(".cm-card").filter({ hasText: "First title discussion." }).getByRole("button", { name: "delete", exact: true }).click();
  await expect(title).toHaveAttribute("data-cids", ids.split(" ")[1]);
  await page.reload();
  await ready(page);
  await expect(title).toHaveAttribute("data-cids", ids.split(" ")[1]);
  await expect(page.locator(".cm-card").filter({ hasText: "First title discussion." })).toHaveCount(0);
  await expect(second).toContainText("A reply about the accountable owner.");
});

test("editing tracks one cumulative card and exact net changes (CMH-TABLE-01)", async ({ page }) => {
  const staged = await open(page);
  await expect(cell(page)).toHaveValue("Decide launch");
  await cell(page).fill("  New  text < &\nsecond line  ");
  await cell(page).fill("Final text");
  await expect(page.locator(".cm-card-table")).toHaveCount(1);
  await expect(page.locator("#sidebarCount")).toHaveText("1");
  await expect(page.locator("#cmTypeBadge")).toHaveText("Not shareable");
  const { text, payload } = await bundle(page);
  expect(text).toContain('## Table "agenda"');
  expect(payload.tables[0].from.rows[0].cells[0]).toBe("Decide launch");
  expect(payload.tables[0].to.rows[0].cells[0]).toBe("Final text");
  await page.goto(fileUrl(staged.html));
  await ready(page);
  await expect(cell(page)).toHaveValue("Final text");
  await cell(page).fill("Decide launch");
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("cmh-table-test::tables"))).toBeNull();
});

test("rows and columns support choice values, empty state and cancelling additions (CMH-TABLE-02)", async ({ page }) => {
  await open(page);
  await action(page, "Add row").click();
  const last = table(page).locator("tbody tr").last();
  await expect(last.locator("select")).toHaveValue("Open");
  await last.getByRole("button", { name: /Remove row/ }).click();
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
  await addColumn(page, "Priority", "choice", "Low\nHigh");
  await expect(table(page).locator("thead")).toContainText("Priority");
  const addedId = await table(page).locator("thead th[data-cmh-column]").last().getAttribute("data-cmh-column");
  await table(page).locator(`[data-cmh-edit-column="${addedId}"]`).first().selectOption("High");
  const { payload } = await bundle(page);
  expect(payload.tables[0].to.columns[3]).toMatchObject({ label: "Priority", type: "choice", options: ["Low", "High"] });
  expect(payload.tables[0].to.rows[0].cells[3]).toBe("High");
});

test("the blank choice stays distinguishable from authored option labels (CMH-TABLE-02)", async ({ page }) => {
  await open(page, DOC.replace('["Open","Done"]', '["Open","(empty)","(empty) (no value)"]')
    .replace("<td>Done</td>", "<td>Open</td>"));
  const select = cell(page, "first", "status");
  await expect(select.getByRole("option", { name: "(empty)", exact: true })).toHaveCount(1);
  const blankLabel = await select.locator('option[value=""]').textContent();
  expect(["Open", "(empty)", "(empty) (no value)"]).not.toContain(blankLabel);
  await select.selectOption({ label: "(empty)" });
  expect((await bundle(page)).payload.tables[0].to.rows[0].cells[2]).toBe("(empty)");
  await select.selectOption("");
  expect((await bundle(page)).payload.tables[0].to.rows[0].cells[2]).toBe("");
});

test("deletion confirms safely and undo redo restore structure and data (CMH-TABLE-03)", async ({ page }) => {
  await open(page);
  await table(page).getByRole("button", { name: "Remove row 1", exact: true }).click();
  await expect(page.locator(".cm-modal")).toContainText("Remove row");
  await expect(page.locator(".cm-modal").getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(cell(page)).toHaveValue("Decide launch");
  await table(page).getByRole("button", { name: "Remove row 1", exact: true }).click();
  await page.locator(".cm-modal").getByRole("button", { name: "Remove" }).click();
  await expect(table(page).locator("tbody tr")).toHaveCount(1);
  await expect(cell(page, "second")).toBeFocused();
  await action(page, "Undo").click();
  await expect(cell(page)).toHaveValue("Decide launch");
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
  await action(page, "Redo").click();
  await expect(table(page).locator("tbody tr")).toHaveCount(1);
  await action(page, "Undo").click();
  await cell(page).fill("Changed");
  await cell(page).blur();
  await action(page, "Undo").click();
  await expect(cell(page)).toHaveValue("Decide launch");
  await cell(page, "first", "status").focus();
  await cell(page, "first", "status").selectOption("Done");
  await cell(page, "first", "status").selectOption("Open");
  await action(page, "Undo").click();
  await expect(cell(page, "first", "status")).toHaveValue("Done");
});

test("focused edits enable Undo immediately and invalidate branching Redo (CMH-TABLE-03)", async ({ page }) => {
  await open(page);
  await cell(page).fill("First edit");
  await expect(cell(page)).toBeFocused();
  await expect(action(page, "Undo")).toBeEnabled();
  await action(page, "Undo").click();
  await expect(cell(page)).toHaveValue("Decide launch");
  await expect(action(page, "Redo")).toBeEnabled();
  await cell(page).fill("Branch edit");
  await expect(action(page, "Undo")).toBeEnabled();
  await expect(action(page, "Redo")).toBeDisabled();
  await action(page, "Undo").click();
  await expect(cell(page)).toHaveValue("Decide launch");
  await action(page, "Redo").click();
  await expect(cell(page)).toHaveValue("Branch edit");
});

test("column rename insertion removal and the last column guard preserve identities (CMH-TABLE-04)", async ({ page }) => {
  await open(page);
  const firstHeader = table(page).locator('th[data-cmh-column="question"]');
  await firstHeader.locator("summary").click();
  await firstHeader.getByRole("button", { name: "Rename column" }).click();
  const dialog = page.getByRole("dialog", { name: "Rename column" });
  await dialog.getByLabel("Column name", { exact: true }).fill("Topic");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(cell(page)).toHaveValue("Decide launch");
  expect((await bundle(page)).payload.tables[0].to.columns[0].id).toBe("question");
  await firstHeader.locator("summary").click();
  await firstHeader.getByRole("button", { name: "Insert column after", exact: true }).click();
  const insertion = page.getByRole("dialog", { name: "Add column" });
  await insertion.getByLabel("Column name", { exact: true }).fill("Inserted");
  await insertion.getByRole("button", { name: "Save", exact: true }).click();
  await expect(table(page).locator("thead th[data-cmh-column]").nth(1)).toContainText("Inserted");
  const added = table(page).locator("thead th[data-cmh-column]").nth(1);
  await added.locator("summary").click();
  await added.getByRole("button", { name: "Remove column", exact: true }).click();
  expect((await bundle(page)).payload.tables[0].to.columns).toHaveLength(3);
  for (const id of ["status", "owner"]) {
    const header = table(page).locator(`th[data-cmh-column="${id}"]`);
    await header.locator("summary").click();
    await header.getByRole("button", { name: "Remove column" }).click();
    await page.locator(".cm-modal").getByRole("button", { name: "Remove" }).click();
    const neighbor = id === "status" ? "Owner" : "Topic";
    await expect(table(page).getByRole("button", { name: "Sort by " + neighbor + ", column " + (id === "status" ? 2 : 1), exact: true })).toBeFocused();
  }
  await firstHeader.locator("summary").click();
  await expect(firstHeader.getByRole("button", { name: "Remove column" })).toBeDisabled();
});

test("sorting is a pure view and edited row identity survives additions (CMH-TABLE-05)", async ({ page }) => {
  await open(page);
  const sort = table(page).getByRole("button", { name: "Sort by Discussion item, column 1", exact: true });
  await sort.click();
  await sort.click();
  await expect(table(page).locator("tbody tr").first()).toHaveAttribute("data-cmh-row", "second");
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
  await cell(page, "first", "owner").fill("Morgan");
  await action(page, "Add row").click();
  const { payload } = await bundle(page);
  expect(payload.tables[0].to.rows[0]).toMatchObject({ id: "first", cells: ["Decide launch", "Morgan", "Open"] });
  expect(payload.tables[0].to.rows).toHaveLength(3);
});

test("undoing a sorted column keeps editors and persistence connected (CMH-TABLE-03)", async ({ page }) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const staged = await open(page);
  await addColumn(page, "Temporary");
  await table(page).getByRole("button", { name: "Sort by Temporary, column 4", exact: true }).click();
  await action(page, "Undo").click();
  await expect(table(page).locator("thead th[data-cmh-column]")).toHaveCount(3);
  await cell(page).fill("Saved after undo");
  expect((await bundle(page)).payload.tables[0].to.rows[0].cells[0]).toBe("Saved after undo");
  await page.goto(fileUrl(staged.html));
  await ready(page);
  await expect(cell(page)).toHaveValue("Saved after undo");
  expect(errors).toEqual([]);
});

test("new rows and columns never reuse deleted baseline identities (CMH-TABLE-04)", async ({ page }) => {
  await open(page, DOC.replace('data-cmh-row="first"', 'data-cmh-row="new-1"')
    .replace('data-cmh-column="owner"', 'data-cmh-column="new-2"'));
  await table(page).getByRole("button", { name: "Remove row 1", exact: true }).click();
  await page.locator(".cm-modal").getByRole("button", { name: "Remove", exact: true }).click();
  const header = table(page).locator('th[data-cmh-column="new-2"]');
  await header.locator("summary").click();
  await header.getByRole("button", { name: "Remove column", exact: true }).click();
  await action(page, "Add row").click();
  await addColumn(page, "Replacement");
  const { text, payload } = await bundle(page);
  expect.soft(payload.tables[0].to.rows.map(row => row.id)).not.toContain("new-1");
  expect.soft(payload.tables[0].to.columns.map(column => column.id)).not.toContain("new-2");
  expect(text).toContain("Removed row new-1");
  expect(text).toContain('Removed column "Owner"');
});

test("choice metadata normalizes newlines through export and saved replay (CMH-TABLE-06)", async ({ page }) => {
  const content = `<h1>Choice normalization</h1>
    <table data-cmh-table="agenda" data-cmh-table-label="Choices"><thead><tr>
    <th data-cmh-column="status" data-cmh-column-type="choice"
      data-cmh-options='["A\\rB"]' data-cmh-default="A&#13;B">Status</th>
    </tr></thead><tbody></tbody></table>`;
  const { dir } = await open(page, content);
  await action(page, "Add row").click();
  const { payload } = await bundle(page);
  expect(payload.tables[0].to.columns[0].options).toEqual(["A\nB"]);
  expect(payload.tables[0].to.columns[0].default).toBe("A\nB");
  expect(payload.tables[0].to.rows[0].cells[0]).toBe("A\nB");
  await page.evaluate(() => {
    const data = JSON.parse(localStorage.getItem("cmh-table-test::tables"));
    for (const model of [data.tables[0].from, data.tables[0].to]) {
      model.columns[0].options = ["A\rB"];
      model.columns[0].default = "A\rB";
      model.rows.forEach(row => { row.cells[0] = "A\rB"; });
    }
    localStorage.setItem("cmh-table-test::tables", JSON.stringify(data));
  });
  await page.reload();
  await ready(page);
  await expect(cell(page, "new-1", "status")).toBeEnabled();
  await expect(cell(page, "new-1", "status")).toHaveValue("A\nB");
  const [download] = await Promise.all([page.waitForEvent("download"), clickSidebarExport(page, "#btnSaveHtml")]);
  const out = path.join(dir, "normalized-choice.html");
  fs.writeFileSync(out, await readDownload(download), "utf8");
  await page.goto(fileUrl(out));
  await ready(page);
  await expect(cell(page, "new-1", "status")).toHaveValue("A\nB");
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
});

test("export bakes live data safely and reopens without pending changes (CMH-TABLE-06)", async ({ page }) => {
  const { dir } = await open(page);
  await cell(page).fill("  <script>literal & text</script>\n tail  ");
  await addColumn(page, "Next step");
  const [download] = await Promise.all([page.waitForEvent("download"), clickSidebarExport(page, "#btnSaveHtml")]);
  const html = await readDownload(download);
  const out = path.join(dir, "table-export.html");
  fs.writeFileSync(out, html, "utf8");
  await page.goto(fileUrl(out));
  await ready(page);
  await expect(cell(page)).toHaveValue("  <script>literal & text</script>\n tail  ");
  await expect(table(page).locator("thead")).toContainText("Next step");
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
});

test("clear and search include table-only changes without affecting normal comments (CMH-TABLE-07)", async ({ page }) => {
  await open(page);
  await addTextComment(page, "#after", "Keep this anchor");
  await cell(page).fill("Unique table change");
  await expect(page.locator("#sidebarCount")).toHaveText("2");
  await openSearch(page);
  await page.locator("#cmSearchInput").fill("Unique table change");
  await expect(page.locator(".cm-card-table")).toBeVisible();
  await page.locator("#cmSearchInput").fill("");
  await clickClearAll(page);
  await expect(page.locator(".cm-modal")).toContainText(/table/i);
  await page.locator(".cm-modal").getByRole("button", { name: "OK", exact: true }).click();
  await expect(cell(page)).toHaveValue("Decide launch");
  await expect(page.locator("#sidebarCount")).toHaveText("0");
});

test("table cards retain identity focus across rebuilds and jump from their body (CMH-TABLE-07)", async ({ page }) => {
  const leading = DOC.match(/<table[\s\S]*?<\/table>/)[0].replace('data-cmh-table="agenda"', 'data-cmh-table="leading"');
  await open(page, leading + DOC);
  await cell(page).fill("Agenda edit");
  const jump = page.locator('.cm-card-table [data-act="table-jump"][data-cmh-table-name="agenda"]');
  await expect(jump).toBeVisible();
  await jump.focus();
  await page.evaluate(() => {
    const field = document.querySelector('[data-cmh-table="leading"] textarea');
    field.value = "Background leading edit";
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect(page.locator(".cm-card-table")).toHaveCount(2);
  await expect(jump).toBeFocused();
  await page.locator("#before").click();
  await page.locator('.cm-card-table[data-cmh-table-name="agenda"] .section').click();
  await expect(cell(page)).toBeFocused();
});

test("stale drafts are recoverable and malformed tables stay unmodified (CMH-TABLE-08)", async ({ page }) => {
  await open(page);
  await cell(page).fill("Recover this draft");
  await page.evaluate(() => {
    const key = "cmh-table-test::tables";
    const data = JSON.parse(localStorage.getItem(key));
    data.tables[0].from.rows[0].cells[0] = "Different baseline";
    localStorage.setItem(key, JSON.stringify(data));
  });
  await page.reload();
  await ready(page);
  await expect(cell(page)).toHaveValue("Decide launch");
  await expect(page.getByRole("button", { name: "Copy saved draft", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Copy saved draft", exact: true }).click();
  expect(await copiedBundle(page)).toContain("Recover this draft");
  await open(page, DOC.replace("<td>Alex</td>", "<td><strong>Alex</strong></td>"), "malformed-table");
  await expect(table(page).locator("strong")).toHaveText("Alex");
  await expect(table(page).locator("textarea")).toHaveCount(0);
});

test("empty rows, keyboard focus and mobile overflow remain usable (CMH-TABLE-09)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, DOC.replace(/<tbody>[\s\S]*?<\/tbody>/, "<tbody></tbody>"));
  await expect(page.locator(".cmh-table-empty")).toBeVisible();
  await action(page, "Add row").click();
  await expect(table(page).locator("textarea").first()).toBeFocused();
  await expect(page.locator(".cmh-table-empty")).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("recovery stays locked through global reset and malformed drafts unlock together (CMH-TABLE-08)", async ({ page }) => {
  const second = DOC.match(/<table[\s\S]*?<\/table>/)[0].replace('data-cmh-table="agenda"', 'data-cmh-table="other"');
  await open(page, DOC + second);
  await cell(page).fill("Saved stale draft");
  await page.evaluate(() => {
    const data = JSON.parse(localStorage.getItem("cmh-table-test::tables"));
    data.tables[0].from.rows[0].cells[0] = "Old source";
    localStorage.setItem("cmh-table-test::tables", JSON.stringify(data));
  });
  await page.reload();
  await ready(page);
  await page.locator('[data-cmh-table="other"] textarea').first().fill("Reset this edit");
  await clickClearAll(page);
  await page.locator(".cm-modal").getByRole("button", { name: "OK", exact: true }).click();
  await expect(cell(page)).toBeDisabled();
  await expect(page.getByRole("button", { name: "Copy saved draft", exact: true })).toBeVisible();
  await page.evaluate(() => localStorage.setItem("cmh-table-test::tables", "{malformed saved draft"));
  await page.reload();
  await ready(page);
  await expect(page.locator(".cmh-editable-table textarea:enabled")).toHaveCount(0);
  await page.getByRole("button", { name: "Discard saved draft", exact: true }).first().click();
  await page.locator(".cm-modal").getByRole("button", { name: "Discard", exact: true }).click();
  await expect(page.locator(".cmh-table-recovery")).toHaveCount(0);
  await expect(cell(page)).toBeEnabled();
  await expect(page.locator('[data-cmh-table="other"] textarea').first()).toBeEnabled();
});

test("quota failures preserve live changes for copy and export (CMH-TABLE-06)", async ({ page }) => {
  await open(page);
  await page.evaluate(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function(key, value) {
      if (key.endsWith("::tables")) throw new DOMException("Test quota", "QuotaExceededError");
      return original.call(this, key, value);
    };
  });
  await cell(page).fill("Keep this unsaved value");
  await expect(page.locator(".cmh-table-save-status")).toContainText("Not saved");
  expect((await bundle(page)).payload.tables[0].to.rows[0].cells[0]).toBe("Keep this unsaved value");
  const [download] = await Promise.all([page.waitForEvent("download"), clickSidebarExport(page, "#btnSaveHtml")]);
  expect(await readDownload(download)).toContain("Keep this unsaved value");
});

test("plain Markdown and print show current values without editor chrome (CMH-TABLE-10)", async ({ page }) => {
  await open(page);
  await cell(page).fill("Updated | value\nnext line");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("Updated \\| value<br>next line");
  expect(md).not.toContain("Add row");
  await page.emulateMedia({ media: "print" });
  await expect(table(page).locator(".cmh-table-title").first()).toBeVisible();
  await expect(table(page).locator(".cmh-table-title").first()).toHaveText("Discussion item");
  await expect(cell(page)).toBeHidden();
  await expect(table(page).locator(".cmh-table-print-value").first()).toHaveText("Updated | value\nnext line");
  await expect(table(page).locator(".cmh-table-print-value").first()).toBeVisible();
  await page.emulateMedia({ media: "screen" });
  const [download] = await Promise.all([page.waitForEvent("download"), clickSidebarExport(page, "#btnSavePlain")]);
  const html = await readDownload(download);
  expect(html).toContain("Updated | value");
  const content = html.match(/<table\b[\s\S]*?<\/table>/)[0];
  expect(content).not.toMatch(/<(textarea|select|button)\b/);
});

test("Markdown unwraps layout tables without duplicating editable descendants (CMH-TABLE-10)", async ({ page }) => {
  await open(page, `<table><thead><tr><th>Layout heading</th><th>Notes</th></tr></thead>
    <tbody><tr><td><p>Layout before</p>${DOC}<p>Layout after</p></td><td>Other notes</td></tr></tbody></table>`);
  await cell(page).fill("Edited | wrapped\nnext line");
  await cell(page, "first", "status").selectOption("Done");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("Edited \\| wrapped<br>next line");
  expect(md).toContain("Layout heading");
  expect(md).toContain("Layout before");
  expect(md).toContain("Layout after");
  expect(md).toContain("Other notes");
  expect(md.match(/Review evidence/g)).toHaveLength(1);
  expect(md.match(/\| Done \|/g)).toHaveLength(2);
  expect(md).not.toMatch(/Add row|Remove row|Sort by|\(empty\)|Open/);
});

test("table tools apply a real browser bundle atomically and preserve nearby anchors (CMH-TABLE-11)", async ({ page }) => {
  const { html, dir } = await open(page);
  await addTextComment(page, "#after", "Preserve prose");
  const quote = await page.locator("#after mark.cm-hl").textContent();
  await cell(page).fill("Applied from browser < &");
  await addColumn(page, "Follow-up");
  const { text } = await bundle(page);
  const input = path.join(dir, "table-bundle.txt");
  fs.writeFileSync(input, text, "utf8");
  const result = spawnSync(PYTHON, [path.join(SKILL, "tools", "tables", "tables_apply.py"), html, "--from-bundle", input], { encoding: "utf8" });
  expect(result.status, result.stdout + result.stderr).toBe(0);
  await page.reload();
  await ready(page);
  await expect(cell(page)).toHaveValue("Applied from browser < &");
  await expect(page.locator(".cm-card-table")).toHaveCount(0);
  await expect(page.locator("#after mark.cm-hl")).toHaveText(quote);
  await expect(page.locator(".cm-card[data-cid]")).toContainText("Preserve prose");
});

test("layout wrappers and implied bodies preserve the browser to tool handoff (CMH-TABLE-11)", async ({ page }) => {
  for (const [label, content] of [
    ["layout", `<table><tbody><tr><td>${DOC}</td></tr></tbody></table>`],
    ["implied-body", DOC.replace("<tbody>", "").replace("</tbody>", "")],
    ["inert-template", `<template>${DOC}</template>${DOC}`],
    ["inert-caption", DOC.replace("<thead>", '<caption>Live caption<template><table data-cmh-table="agenda"><tr><td data-cmh-note="inert">Hidden</td></tr></table></template></caption><thead>')],
  ]) {
    await test.step(label, async () => {
      const { html, dir } = await open(page, content, "table-handoff-" + label);
      await cell(page).fill("Cement " + label);
      const { text } = await bundle(page);
      const input = path.join(dir, "table-bundle.txt");
      fs.writeFileSync(input, text, "utf8");
      const result = spawnSync(PYTHON, [path.join(SKILL, "tools", "tables", "tables_apply.py"), html, "--from-bundle", input], { encoding: "utf8" });
      expect(result.status, result.stdout + result.stderr).toBe(0);
      await page.reload();
      await ready(page);
      await expect(cell(page)).toHaveValue("Cement " + label);
      await expect(page.locator(".cm-card-table")).toHaveCount(0);
    });
  }
});

test("the shipped playground supports the complete editable-table review loop (CMH-TABLE-12)", async ({ page }) => {
  await installClipboardCapture(page);
  await routeExampleLibsLocal(page);
  const demo = path.resolve(SKILL, "..", "..", "examples", "report-editable-table.html");
  await page.goto(fileUrl(demo));
  await ready(page);
  const field = page.locator('[data-cmh-table="discussion"] textarea').first();
  await field.fill("A new discussion topic");
  await page.locator(".cmh-editable-table").getByRole("button", { name: "Add row", exact: true }).click();
  await expect(page.locator('[data-cmh-table="discussion"] tbody tr')).toHaveCount(4);
  await expect(page.locator(".cm-card-table")).toHaveCount(1);
  await page.locator("#btnCopyAll").click();
  expect(await copiedBundle(page)).toContain("A new discussion topic");
  expect(page.__external).toEqual([]);
});

test("adding a column focuses its first editor (CMH-TABLE-09)", async ({ page }) => {
  await open(page);
  await addColumn(page, "Next action");
  const id = await table(page).locator("thead th[data-cmh-column]").last().getAttribute("data-cmh-column");
  await expect(cell(page, "first", id)).toBeFocused();
});

test("column dialog cancellation restores menu focus and isolates Escape (CMH-TABLE-09)", async ({ page }) => {
  await open(page);
  const header = table(page).locator('th[data-cmh-column="question"]');
  for (const name of ["Rename column", "Insert column after"]) {
    await header.locator("summary").click();
    await header.getByRole("button", { name, exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Cancel", exact: true }).click();
    await expect.soft(header.locator("summary")).toBeFocused();
  }
  await header.locator("summary").click();
  await header.getByRole("button", { name: "Remove column", exact: true }).click();
  await page.locator(".cm-modal").getByRole("button", { name: "Cancel", exact: true }).click();
  await expect.soft(header.locator("summary")).toBeFocused();
  const composer = await openComposerFor(page, "#after");
  await composer.locator("textarea").fill("Keep this composer draft");
  await action(page, "Add column").focus();
  await page.keyboard.press("Enter");
  await expect(composer).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(composer).toBeVisible();
  await expect(composer.locator("textarea")).toHaveValue("Keep this composer draft");
});

test("cemented drafts are pruned while unmatched recovery stays intact (CMH-TABLE-08)", async ({ page }) => {
  const { html, dir } = await open(page);
  await cell(page).fill("Cemented value");
  const { text } = await bundle(page);
  await page.evaluate(() => {
    const data = JSON.parse(localStorage.getItem("cmh-table-test::tables"));
    data.tables.push({ ...data.tables[0], id: "missing" });
    localStorage.setItem("cmh-table-test::tables", JSON.stringify(data));
  });
  const input = path.join(dir, "table-bundle.txt");
  fs.writeFileSync(input, text, "utf8");
  const result = spawnSync(PYTHON, [path.join(SKILL, "tools", "tables", "tables_apply.py"), html, "--from-bundle", input], { encoding: "utf8" });
  expect(result.status, result.stdout + result.stderr).toBe(0);
  await page.reload();
  await ready(page);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("cmh-table-test::tables")).tables.map(entry => entry.id))).toEqual(["missing"]);
  const content = fs.readFileSync(html, "utf8");
  expect(content).toContain("<td>Cemented value</td>");
  fs.writeFileSync(html, content.replace("<td>Cemented value</td>", "<td>Author revision</td>"), "utf8");
  await page.reload();
  await ready(page);
  await expect(cell(page)).toHaveValue("Author revision");
  await expect(cell(page)).toBeEnabled();
  await expect(page.locator(".cmh-editable-table .cmh-table-recovery")).toHaveCount(0);
  await expect(page.locator(".cmh-table-recovery")).toHaveCount(1);
});

test("invalid metadata and diff ownership remain outside the editable-table runtime (CMH-TABLE-08)", async ({ page }) => {
  for (const [label, transform] of [
    ["missing label", html => html.replace(' data-cmh-table-label="Discussion items"', "")],
    ["blank label", html => html.replace('data-cmh-table-label="Discussion items"', 'data-cmh-table-label="   "')],
    ["diff ownership", html => html.replace('<table data-cmh-table=', '<table class="cmh-diff" data-cmh-table=')],
    ["duplicate header", html => html.replace("</thead>", '</thead><thead><tr><th data-cmh-column="extra">Extra header</th></tr></thead>')],
  ]) {
    await test.step(label, async () => {
      await open(page, transform(DOC));
      await expect(table(page).locator("textarea, select")).toHaveCount(0);
      await expect(table(page).locator("tbody tr").first()).toContainText("Decide launch");
    });
  }
});

test("malformed saved metadata pauses editing without replaying the draft (CMH-TABLE-08)", async ({ page }) => {
  await open(page);
  await cell(page).fill("Do not replay invalid state");
  await page.evaluate(() => {
    const data = JSON.parse(localStorage.getItem("cmh-table-test::tables"));
    data.tables[0].label = 0;
    localStorage.setItem("cmh-table-test::tables", JSON.stringify(data));
  });
  await page.reload();
  await ready(page);
  await expect(cell(page)).toBeDisabled();
  await expect(cell(page)).toHaveValue("Decide launch");
  await page.getByRole("button", { name: "Copy saved draft", exact: true }).click();
  expect(await copiedBundle(page)).toContain("Do not replay invalid state");
});

test("extra saved schema keys pause editing at every payload level (CMH-TABLE-08)", async ({ page }) => {
  for (const level of ["root", "entry", "model", "column", "row"]) {
    await test.step(level, async () => {
      const key = "table-extra-" + level;
      await open(page, DOC, key);
      await cell(page).fill("Protect malformed draft");
      await page.evaluate(({ key, level }) => {
        const data = JSON.parse(localStorage.getItem(key + "::tables"));
        const entry = data.tables[0];
        const target = { root: data, entry, model: entry.to, column: entry.to.columns[0], row: entry.to.rows[0] }[level];
        target.unexpected = "Do not silently discard";
        localStorage.setItem(key + "::tables", JSON.stringify(data));
      }, { key, level });
      await page.reload();
      await ready(page);
      await expect(cell(page)).toBeDisabled();
      await expect(cell(page)).toHaveValue("Decide launch");
      await page.getByRole("button", { name: "Copy saved draft", exact: true }).click();
      expect(await copiedBundle(page)).toContain("Do not silently discard");
    });
  }
});

test("duplicate column names have distinct accessible header controls (CMH-TABLE-09)", async ({ page }) => {
  await open(page);
  await addColumn(page, "Status");
  await expect(table(page).getByRole("button", { name: "Sort by Status, column 3", exact: true })).toHaveCount(1);
  await expect(table(page).getByRole("button", { name: "Sort by Status, column 4", exact: true })).toHaveCount(1);
  await expect(table(page).locator('summary[aria-label="Actions for Status, column 3"]')).toHaveCount(1);
  await expect(table(page).locator('summary[aria-label="Actions for Status, column 4"]')).toHaveCount(1);
});

test("global reset refreshes every table storage status (CMH-TABLE-07)", async ({ page }) => {
  const second = DOC.match(/<table[\s\S]*?<\/table>/)[0].replace('data-cmh-table="agenda"', 'data-cmh-table="other"');
  await open(page, DOC + second);
  await page.evaluate(() => {
    window.tableQuotaFailure = true;
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function(key, value) {
      if (key.endsWith("::tables") && window.tableQuotaFailure) throw new DOMException("Test quota", "QuotaExceededError");
      return original.call(this, key, value);
    };
  });
  await cell(page).fill("First unsaved edit");
  await page.locator('[data-cmh-table="other"] textarea').first().fill("Second unsaved edit");
  await page.locator('[data-cmh-table="other"] textarea').first().blur();
  await expect(page.locator(".cmh-table-save-status", { hasText: "Not saved" })).toHaveCount(2);
  await page.evaluate(() => { window.tableQuotaFailure = false; });
  await clickClearAll(page);
  await page.locator(".cm-modal").getByRole("button", { name: "OK", exact: true }).click();
  await expect(page.locator(".cmh-table-save-status", { hasText: "Not saved" })).toHaveCount(0);
  await expect(cell(page)).toHaveValue("Decide launch");
});
