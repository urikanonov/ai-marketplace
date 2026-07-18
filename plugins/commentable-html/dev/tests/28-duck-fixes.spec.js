import { test, expect } from "@playwright/test";
import fs from "fs";
import os from "os";
import path from "path";
import {
  openInline, ready, fileUrl, INLINE, stageInline, addTextComment, readDownload,
  installClipboardCapture, allCids,
  clickSidebarExport,
} from "./helpers.js";

const CONTENT_END = "<!-- END: commentable-html - CONTENT -->";
function inject(snippet) {
  return (h) => h.replace(CONTENT_END, snippet + "\n" + CONTENT_END);
}
async function openStaged(page, html) {
  await installClipboardCapture(page);
  await page.goto(fileUrl(html));
  await ready(page);
}
function stageNamed(name, source = INLINE) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_named_"));
  const p = path.join(dir, name);
  fs.writeFileSync(p, fs.readFileSync(source, "utf8"));
  return p;
}

test.describe("multi-duck panel regression + reload-persistence coverage", () => {
  // Duck 3: sortable NaN on two empty numeric cells corrupted Array.sort.
  test("sorting a numeric column with multiple empty cells does not scramble (NaN guard)", async ({ page }) => {
    const table = `<section aria-labelledby="nan-h"><h2 id="nan-h">Empty numeric cells</h2>
      <table><thead><tr><th>Name</th><th>Score</th></tr></thead><tbody>
      <tr><td>alpha</td><td>5</td></tr><tr><td>bravo</td><td></td></tr>
      <tr><td>charlie</td><td></td></tr><tr><td>delta</td><td>2</td></tr>
      </tbody></table></section>`;
    const { html } = stageInline({ mutate: inject(table) });
    await openStaged(page, html);
    const tbl = page.locator("#commentRoot table.cmh-sortable").filter({ has: page.locator("th", { hasText: "Score" }) });
    await tbl.locator("thead th", { hasText: "Score" }).locator(".cmh-sort-ctrl").click();
    // Ascending numeric: empties first (stable), then 2, then 5. Not scrambled.
    expect(await tbl.locator("tbody tr td:first-child").allTextContents()).toEqual(["bravo", "charlie", "delta", "alpha"]);
  });

  // Duck 4: a table with colspan/rowspan must NOT be sortable (would reorder wrongly).
  test("a non-rectangular table (colspan) is not made sortable", async ({ page }) => {
    const table = `<section aria-labelledby="span-h"><h2 id="span-h">Spanned table</h2>
      <table id="spanned"><thead><tr><th>A</th><th>B</th></tr></thead><tbody>
      <tr><td colspan="2">merged</td></tr><tr><td>x</td><td>y</td></tr></tbody></table></section>`;
    const { html } = stageInline({ mutate: inject(table) });
    await openStaged(page, html);
    await expect(page.locator("#spanned")).not.toHaveClass(/cmh-sortable/);
    await expect(page.locator("#spanned .cmh-sort-ctrl")).toHaveCount(0);
  });

  // Duck 3: a section whose FIRST heading is nested in cm-skip must still be collapsible
  // via its direct-child heading (:scope > selector).
  test("a section with a nested cm-skip heading before the real heading is still collapsible", async ({ page }) => {
    const sec = `<section aria-labelledby="real-h"><div class="cm-skip"><h3>skip banner heading</h3></div>
      <h2 id="real-h">Real section heading</h2><p id="collapsible-body">body text</p></section>`;
    const { html } = stageInline({ mutate: inject(sec) });
    await openStaged(page, html);
    const caret = page.locator('#commentRoot h2#real-h .cmh-sec-caret');
    await expect(caret).toHaveCount(1);
    await caret.click();
    await expect(page.locator("#collapsible-body")).toBeHidden();
  });

  // Duck 8/5: the runtime diff highlighter must escape crafted content (no XSS). The
  // dangerous chars are authored as entities (the valid escaped form), so they live as
  // TEXT in the pre and the highlighter must re-emit them escaped, not as live markup.
  test("the diff highlighter escapes a crafted line (no script/img injection)", async ({ page }) => {
    const diff = `<pre class="cmh-diff" data-diff-label="evil.js">@@ -1,1 +1,2 @@
 const a = 1;
+const x = "&lt;/script&gt;&lt;img src=x onerror=alert(1)&gt;";</pre>`;
    const { html } = stageInline({ mutate: inject(diff) });
    await openStaged(page, html);
    const evil = page.locator('.cmh-diff-host[data-diff-label="evil.js"]');
    await expect(evil.locator(".cmh-diff-view")).toBeVisible();
    await expect(page.locator("#commentRoot img[onerror]")).toHaveCount(0);
    // The crafted text survives as literal text inside the diff code.
    await expect(evil.locator(".cmh-dl-code").filter({ hasText: "onerror=alert(1)" }).first()).toBeVisible();
  });

  // Duck 3/8: export filename must not stack suffixes.
  test("Export as Portable does not stack suffixes on a *-comments.html file", async ({ page }) => {
    const p = stageNamed("report-comments.html");
    await openStaged(page, p);
    await addTextComment(page, "#commentRoot section p", "note");
    const [dl] = await Promise.all([page.waitForEvent("download"), clickSidebarExport(page, "#btnSaveHtml")]);
    expect(dl.suggestedFilename()).toBe("report-portable.html");
  });

  // Ducks 1+2: a deleted embedded comment must NOT resurrect on reload (tombstone).
  test("deleting an embedded comment keeps it deleted across reload", async ({ page, context }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "embedded then deleted");
    const [dl] = await Promise.all([page.waitForEvent("download"), clickSidebarExport(page, "#btnSaveHtml")]);
    const p = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "cmh_tomb_")), "doc.html");
    fs.writeFileSync(p, await readDownload(dl));
    const p2 = await context.newPage();
    p2.on("dialog", (d) => d.accept());
    await installClipboardCapture(p2);
    await p2.goto(fileUrl(p));
    await ready(p2);
    await expect(p2.locator(".cm-card")).toHaveCount(1);
    await p2.locator(".cm-card [data-act='del']").first().click();
    await expect(p2.locator(".cm-card")).toHaveCount(0);
    await p2.reload();
    await ready(p2);
    await expect(p2.locator(".cm-card")).toHaveCount(0); // did NOT resurrect
    await expect(p2.locator("#cmTypeBadge")).toHaveText("Not portable"); // file still has it embedded
    await p2.close();
  });

  // Duck 2 (blocking): a comment on a SORTED table cell must anchor correctly for a
  // recipient of the exported portable file (offsets canonicalized to original order).
  test("a comment on a sorted table cell exports with a correct anchor", async ({ page, context }) => {
    await openInline(page); // template ships the Service/Requests/p95 sortable table
    await addTextComment(page, '#commentRoot table.cmh-sortable tbody tr td:first-child', "on gateway", 0);
    const markText = await page.$eval("mark.cm-hl", (m) => m.textContent);
    // Sort Requests ascending so the commented row moves.
    await page.locator("#commentRoot table.cmh-sortable thead th", { hasText: "Requests" }).locator(".cmh-sort-ctrl").click();
    const [dl] = await Promise.all([page.waitForEvent("download"), clickSidebarExport(page, "#btnSaveHtml")]);
    const p = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "cmh_canon_")), "doc.html");
    fs.writeFileSync(p, await readDownload(dl));
    const p2 = await context.newPage();
    await installClipboardCapture(p2);
    await p2.goto(fileUrl(p)); // recipient: no sort state, original DOM order
    await ready(p2);
    await expect(p2.locator("mark.cm-hl")).toHaveCount(1);
    expect(await p2.$eval("mark.cm-hl", (m) => m.textContent)).toBe(markText);
    await p2.close();
  });

  // Duck 7/8: heading comment must survive reload.
  test("a heading comment survives reload", async ({ page }) => {
    await openInline(page);
    const h = page.locator("#commentRoot h2.cm-anchored").first();
    await h.hover();
    await page.locator("#headingAddBtn").click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("heading note");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);
    const cid = (await allCids(page))[0];
    await page.reload();
    await ready(page);
    await expect(page.locator(`#commentRoot h2 mark.cm-hl[data-cid="${cid}"]`)).toHaveCount(1);
    await expect(page.locator(".cm-card")).toHaveCount(1);
  });

  // Duck 7/8: diff Syntax toggle choice persists across reload.
  test("the diff Syntax toggle choice persists across reload", async ({ page }) => {
    await openInline(page);
    await page.locator(".cmh-diff-hltoggle").first().click(); // turn OFF
    await expect(page.locator(".cmh-diff-hltoggle").first()).toHaveText("Syntax: off");
    await page.reload();
    await ready(page);
    await expect(page.locator(".cmh-diff-hltoggle").first()).toHaveText("Syntax: off");
    await expect(page.locator(".cmh-diff-view .cmh-dl-code .cmh-code-kw")).toHaveCount(0);
  });
});
