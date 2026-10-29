import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { spawnSync } from "child_process";
import {
  fileUrl, ready, installClipboardCapture, stageContent, copiedBundle, readDownload,
  clickSidebarExport, clickClearAll, addTextComment, openSearch, routeExampleLibsLocal, SKILL, PYTHON,
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
    await expect(table(page).getByRole("button", { name: "Sort by " + neighbor, exact: true })).toBeFocused();
  }
  await firstHeader.locator("summary").click();
  await expect(firstHeader.getByRole("button", { name: "Remove column" })).toBeDisabled();
});

test("sorting is a pure view and edited row identity survives additions (CMH-TABLE-05)", async ({ page }) => {
  await open(page);
  const sort = table(page).getByRole("button", { name: "Sort by Discussion item", exact: true });
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

test("invalid metadata and diff ownership remain outside the editable-table runtime (CMH-TABLE-08)", async ({ page }) => {
  for (const [label, transform] of [
    ["missing label", html => html.replace(' data-cmh-table-label="Discussion items"', "")],
    ["blank label", html => html.replace('data-cmh-table-label="Discussion items"', 'data-cmh-table-label="   "')],
    ["diff ownership", html => html.replace('<table data-cmh-table=', '<table class="cmh-diff" data-cmh-table=')],
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
