import { test, expect } from "@playwright/test";
import fs from "fs";
import os from "os";
import path from "path";
import { openInline, ready, lastCopied, addTextComment, stageContent, fileUrl, clickSidebarExport, readDownload, storedComments } from "./helpers.js";

// Requests column values in the template demo table, keyed by Service, so a test can
// assert numeric (not lexicographic) ordering.
const REQ = { gateway: 1200, auth: 340, catalog: 9800 };

// An OUTER sortable table whose body cells each hold their OWN sortable table. Sorting the outer
// table moves the nested tables to a different DOCUMENT index, which is exactly what makes a
// positional table key disagree between the reader's click, a reload, and the export pass (#976).
const NESTED_TABLES = [
  "<h1>Regions</h1>",
  "<p>Regional load overview.</p>",
  '<table id="outer">',
  "  <thead>",
  "    <tr><th>Region</th><th>Hosts</th></tr>",
  "  </thead>",
  "  <tbody>",
  "    <tr><td>West</td><td>",
  '      <table id="west">',
  "        <thead><tr><th>West host</th><th>Load</th></tr></thead>",
  "        <tbody>",
  "          <tr><td>wb</td><td>2</td></tr>",
  "          <tr><td>wa</td><td>1</td></tr>",
  "        </tbody>",
  "      </table>",
  "    </td></tr>",
  "    <tr><td>East</td><td>",
  '      <table id="east">',
  "        <thead><tr><th>East host</th><th>Load</th></tr></thead>",
  "        <tbody>",
  "          <tr><td>eb</td><td>2</td></tr>",
  "          <tr><td>ea</td><td>1</td></tr>",
  "        </tbody>",
  "      </table>",
  "    </td></tr>",
  "  </tbody>",
  "</table>",
].join("\n");

const firstCells = (page, selector) =>
  page.$$eval(selector, (tds) => tds.map((t) => t.textContent.trim()));
const outerOrder = (page) => firstCells(page, "#outer > tbody > tr > td:first-child");
const westOrder = (page) => firstCells(page, "#west > tbody > tr > td:first-child");
const sortCtrl = (page, id, col = 1) => page.locator(`#${id} > thead > tr > th:nth-child(${col}) .cmh-sort-ctrl`);

// An outer table sorted on the column that HOLDS the nested tables: which row wins depends on the
// nested tables' own row order, so replaying the persisted sorts outer-first and innermost-first
// give different answers.
const NESTED_SORT_KEY_TABLES = [
  "<h1>Hosts</h1>",
  '<table id="outer">',
  "  <thead><tr><th>Group</th><th>Hosts</th></tr></thead>",
  "  <tbody>",
  "    <tr><td>Alpha</td><td>",
  '      <table id="n1">',
  "        <thead><tr><th>Host</th><th>Load</th></tr></thead>",
  "        <tbody><tr><td>zz</td><td>2</td></tr><tr><td>aa</td><td>1</td></tr></tbody>",
  "      </table>",
  "    </td></tr>",
  "    <tr><td>Beta</td><td>",
  '      <table id="n2">',
  "        <thead><tr><th>Host</th><th>Load</th></tr></thead>",
  "        <tbody><tr><td>mm</td><td>1</td></tr><tr><td>nn</td><td>2</td></tr></tbody>",
  "      </table>",
  "    </td></tr>",
  "  </tbody>",
  "</table>",
].join("\n");

async function serviceOrder(page) {
  return page.$$eval("#commentRoot table.cmh-sortable tbody tr td:first-child", (tds) => tds.map((t) => t.textContent.trim()));
}

test.describe("copy buttons + sortable tables", () => {
  test("sorting and unsorting a whitespace-formatted table leaves the document text unchanged (CMH-CONTENT-20)", async ({ page }) => {
    // A real authored table has newlines between its rows, so the tbody holds whitespace text nodes
    // BETWEEN the rows. Reordering must permute the rows through their existing slots: appending
    // them stranded that whitespace ahead of the rows, permanently changing the document text (and
    // therefore its content hash) even after the sort was cleared (#952).
    const staged = stageContent([
      "<h1>Rows</h1>",
      "<table>",
      "  <thead>",
      "    <tr><th>Name</th><th>Count</th></tr>",
      "  </thead>",
      "  <tbody>",
      "    <tr><td>Bravo</td><td>2</td></tr>",
      "    <tr><td>Alpha</td><td>1</td></tr>",
      "    <tr><td>Charlie</td><td>3</td></tr>",
      "  </tbody>",
      "</table>",
    ].join("\n"), { key: "cmh-sort-ws-neutral" });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const shape = () => page.$eval("#commentRoot table tbody", (b) =>
      [...b.childNodes].map((n) => (n.nodeType === 1 ? n.tagName : JSON.stringify(n.nodeValue))).join(","));
    const text = () => page.$eval("#commentRoot", (el) => el.textContent);
    const shapeBefore = await shape();
    const textBefore = await text();
    expect(shapeBefore).toMatch(/^"[^"]*",TR,/);   // whitespace really does sit between the rows

    const btn = page.locator("#commentRoot table.cmh-sortable th .cmh-sort-ctrl").first();
    await btn.click();                              // asc
    await expect(page.locator("#commentRoot table tbody tr td:first-child"))
      .toHaveText(["Alpha", "Bravo", "Charlie"]);
    // Rows moved, but every non-row node kept its slot: the shape is unchanged.
    expect(await shape()).toBe(shapeBefore);

    await btn.click();                              // desc
    await expect(page.locator("#commentRoot table tbody tr td:first-child"))
      .toHaveText(["Charlie", "Bravo", "Alpha"]);
    expect(await shape()).toBe(shapeBefore);

    await btn.click();                              // cleared: back to source order AND source text
    await expect(page.locator("#commentRoot table tbody tr td:first-child"))
      .toHaveText(["Bravo", "Alpha", "Charlie"]);
    expect(await shape()).toBe(shapeBefore);
    expect(await text()).toBe(textBefore);
  });

  // #976: the export pass canonicalizes comments by unsorting EVERY sortable table and then putting
  // each one back. The table key is positional, so a sortable table nested in a sorted table's cell
  // must not be looked up by an index the unsort itself changed.
  test("a sortable table nested in a sorted table keeps its own sort across an export (CMH-CONTENT-08)", async ({ page, browser }) => {
    const staged = stageContent(NESTED_TABLES, { key: "cmh-nested-sort-export" });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    expect(await outerOrder(page)).toEqual(["West", "East"]);
    expect(await westOrder(page)).toEqual(["wb", "wa"]);
    // Anchor the comment INSIDE the nested table, so its exported offsets differ between the
    // reader's sorted view and the authored order the export must serialize.
    await addTextComment(page, "#west > tbody > tr > td:first-child", "nested note", 0);
    const markText = await page.$eval("mark.cm-hl", (m) => m.textContent.trim());
    expect(markText).toBe("wb");

    // Sort the OUTER table so the nested tables swap document position, then reload: the persisted
    // sort is re-applied BEFORE the sort controls are wired, so from here the live document order
    // and the authored order disagree about which index each nested table has.
    await sortCtrl(page, "outer").click();
    expect(await outerOrder(page)).toEqual(["East", "West"]);
    await page.reload();
    await ready(page);
    expect(await outerOrder(page)).toEqual(["East", "West"]);

    await sortCtrl(page, "west").click();
    expect(await westOrder(page)).toEqual(["wa", "wb"]);

    const [dl] = await Promise.all([page.waitForEvent("download"), clickSidebarExport(page, "#btnSaveHtml")]);
    expect(await westOrder(page)).toEqual(["wa", "wb"]);
    expect(await outerOrder(page)).toEqual(["East", "West"]);

    // And the reader's own sorts still survive the next reload.
    await page.reload();
    await ready(page);
    expect(await outerOrder(page)).toEqual(["East", "West"]);
    expect(await westOrder(page)).toEqual(["wa", "wb"]);

    // The exported file anchors correctly for a recipient with no sort state of their own: the
    // canonical pass only produces authored-order offsets if the nested table was really unsorted
    // while the snapshot was taken.
    const p = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "cmh_nested_")), "doc.html");
    fs.writeFileSync(p, await readDownload(dl));
    const ctx2 = await browser.newContext();
    const p2 = await ctx2.newPage();
    await p2.goto(fileUrl(p));
    await ready(p2);
    await expect(p2.locator("mark.cm-hl")).toHaveCount(1);
    expect(await p2.$eval("mark.cm-hl", (m) => m.textContent.trim())).toBe("wb");
    await ctx2.close();
  });

  // #976: the canonical pass unsorts first, so a throw between the unsort and the restore would
  // leave the reader looking at a permanently unsorted document.
  test("a throw during the export canonical pass never strands the reader's tables unsorted (CMH-CONTENT-08)", async ({ page }) => {
    const staged = stageContent(NESTED_TABLES, { key: "cmh-sort-export-throw" });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "regional note");
    await sortCtrl(page, "outer").click();
    await sortCtrl(page, "west").click();
    expect(await outerOrder(page)).toEqual(["East", "West"]);
    expect(await westOrder(page)).toEqual(["wa", "wb"]);

    // Make the offset recompute inside the canonical pass throw: it walks the content root, and
    // nothing else in an export click does. Record the live row order AT THE THROW, so the test
    // cannot go green on a throw that fires before the pass ever unsorted anything.
    await page.evaluate(() => {
      const orig = document.createTreeWalker.bind(document);
      window.__cmhWalkerThrows = 0;
      window.__cmhWalkerBoom = true;
      document.createTreeWalker = function (node, ...rest) {
        if (window.__cmhWalkerBoom && node && node.id === "commentRoot") {
          window.__cmhWalkerThrows++;
          window.__cmhOrderAtThrow = [...document.querySelectorAll("#outer > tbody > tr > td:first-child")]
            .map((td) => td.textContent.trim());
          throw new Error("recompute boom");
        }
        return orig(node, ...rest);
      };
    });
    // Register the download waiter BEFORE the click, or it could time out on an export that really
    // did produce a file and the assertion would hold for the wrong reason.
    const downloaded = page.waitForEvent("download", { timeout: 2000 }).then(() => true).catch(() => false);
    try {
      await clickSidebarExport(page, "#btnSaveHtml");
      expect(await downloaded).toBe(false);   // the export really did fail
      expect(await page.evaluate(() => window.__cmhWalkerThrows)).toBeGreaterThan(0);
      // The throw landed BETWEEN the unsort and the restore: the tables were in authored order then.
      expect(await page.evaluate(() => window.__cmhOrderAtThrow)).toEqual(["West", "East"]);
    } finally {
      await page.evaluate(() => { window.__cmhWalkerBoom = false; });
    }

    expect(await outerOrder(page)).toEqual(["East", "West"]);
    expect(await westOrder(page)).toEqual(["wa", "wb"]);
  });

  // #976: the canonical pass rewrites live comment offsets into authored-row coordinates. A throw
  // part-way through must not leave those offsets behind for the next ordinary save to persist.
  test("a failed export leaves the reader's live comment offsets untouched (CMH-CONTENT-08)", async ({ page }) => {
    const staged = stageContent(NESTED_TABLES, { key: "cmh-sort-export-offsets" });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    // Two comments inside the OUTER table's moving rows, so their offsets differ between the
    // reader's sorted view and the authored order.
    await addTextComment(page, "#outer > tbody > tr > td:first-child", "west note", 0);
    await addTextComment(page, "#outer > tbody > tr > td:first-child", "east note", 1);
    await sortCtrl(page, "outer").click();
    expect(await outerOrder(page)).toEqual(["East", "West"]);
    const before = (await storedComments(page)).map((c) => [c.id, c.start, c.end]);
    expect(before).toHaveLength(2);
    // The exact text each comment is anchored on, so the reload assertion below is independent of
    // how much of the cell the selection helper grabbed.
    const anchoredText = Object.fromEntries(
      await page.$$eval("mark.cm-hl", (ms) => ms.map((m) => [m.dataset.cid, m.textContent])));
    expect(Object.keys(anchoredText)).toHaveLength(2);

    // Throw on the SECOND comment's mark walk, so the first comment's offsets have already been
    // rewritten into authored coordinates when the pass unwinds. Count the FIRST comment's walks
    // too: without that sentinel the test would still pass if the pass threw before touching any
    // comment, which is not the state the revert exists to undo.
    const cids = before.map((c) => c[0]);
    await page.evaluate(([firstCid, secondCid]) => {
      const orig = document.createTreeWalker.bind(document);
      window.__cmhWalkerBoom = true;
      window.__cmhWalkerThrows = 0;
      window.__cmhFirstWalks = 0;
      document.createTreeWalker = function (node, ...rest) {
        const cid = window.__cmhWalkerBoom && node && node.nodeType === 1 && node.dataset
          ? node.dataset.cid : null;
        if (cid === firstCid) window.__cmhFirstWalks++;
        if (cid === secondCid) {
          window.__cmhWalkerThrows++;
          throw new Error("recompute boom");
        }
        return orig(node, ...rest);
      };
    }, [cids[0], cids[1]]);
    const downloaded = page.waitForEvent("download", { timeout: 2000 }).then(() => true).catch(() => false);
    try {
      await clickSidebarExport(page, "#btnSaveHtml");
      expect(await downloaded).toBe(false);
      expect(await page.evaluate(() => window.__cmhWalkerThrows)).toBeGreaterThan(0);
      // The first comment really was re-anchored before the throw, so the revert had work to do.
      expect(await page.evaluate(() => window.__cmhFirstWalks)).toBeGreaterThan(0);
    } finally {
      await page.evaluate(() => { window.__cmhWalkerBoom = false; });
    }
    expect(await outerOrder(page)).toEqual(["East", "West"]);

    // Any ordinary next action persists the whole in-memory set, so a corrupted offset would be
    // written to storage here and mis-anchor on the next load.
    await addTextComment(page, "#commentRoot p", "later note");
    const after = (await storedComments(page)).filter((c) => cids.includes(c.id))
      .map((c) => [c.id, c.start, c.end]);
    expect(after).toEqual(before);

    await page.reload();
    await ready(page);
    expect(await outerOrder(page)).toEqual(["East", "West"]);
    const marks = await page.$$eval("mark.cm-hl", (ms) => ms.map((m) => [m.dataset.cid, m.textContent]));
    expect(Object.fromEntries(marks.filter((m) => cids.includes(m[0])))).toEqual(anchoredText);
  });

  // #976: an outer table sorted on the column that HOLDS the nested tables ranks its rows by that
  // cell's text, so replaying the persisted sorts outer-first would rank it against nested tables
  // that are not back in their own order yet.
  test("persisted sorts replay innermost-first, so an outer sort keyed on a nested table survives a reload (CMH-CONTENT-08)", async ({ page }) => {
    const staged = stageContent(NESTED_SORT_KEY_TABLES, { key: "cmh-nested-sort-key" });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    expect(await outerOrder(page)).toEqual(["Alpha", "Beta"]);

    // Sort the nested table FIRST (aa now leads its cell), then the outer table on the Hosts
    // column: "aa..." now ranks before "mm...", so Alpha leads.
    await sortCtrl(page, "n1").click();
    expect(await firstCells(page, "#n1 > tbody > tr > td:first-child")).toEqual(["aa", "zz"]);
    await sortCtrl(page, "outer", 2).click();
    expect(await outerOrder(page)).toEqual(["Alpha", "Beta"]);

    // Replaying outer-first would compare the authored "zz..." cell and put Beta on top.
    await page.reload();
    await ready(page);
    expect(await firstCells(page, "#n1 > tbody > tr > td:first-child")).toEqual(["aa", "zz"]);
    expect(await outerOrder(page)).toEqual(["Alpha", "Beta"]);

    // The export borrows the authored order and must hand back the order it borrowed, not one
    // re-derived by re-sorting (which would compare the same cells all over again).
    await addTextComment(page, "#commentRoot h1", "title note");
    await Promise.all([page.waitForEvent("download"), clickSidebarExport(page, "#btnSaveHtml")]);
    expect(await outerOrder(page)).toEqual(["Alpha", "Beta"]);
    expect(await firstCells(page, "#n1 > tbody > tr > td:first-child")).toEqual(["aa", "zz"]);
  });

  test("each code block has an always-visible Copy button that copies its exact text", async ({ page }) => {
    await openInline(page);
    const wrap = page.locator('#commentRoot .cmh-code-wrap:has(code.language-python)').first();
    const btn = wrap.locator(".cm-code-copy");
    // Always visible (no hover needed) and inside a wrap (cm-skip, offset-safe).
    await expect(btn).toBeVisible();
    await expect(btn).toHaveClass(/cm-skip/);
    await btn.click();
    const copied = await lastCopied(page);
    const expected = await wrap.locator("pre code").evaluate((c) => c.textContent.replace(/\n$/, ""));
    expect(copied).toBe(expected);
    await expect(page.locator("#toast")).toContainText(/copied/i);
  });

  test("the Kusto caption cluster name copies to the clipboard", async ({ page }) => {
    await openInline(page);
    const chip = page.locator(".cmh-kql-cluster").first();
    await expect(chip).toBeVisible();
    await chip.click();
    expect(await lastCopied(page)).toBe("help.kusto.windows.net");
    await expect(page.locator("#toast")).toContainText(/cluster copied/i);
  });

  test("code and KQL blocks render line rows with CSS-generated counters (CMH-CODE-04)", async ({ page }) => {
    await openInline(page);
    const pyLine = page.locator('#commentRoot .cmh-code-wrap:has(code.language-python) code .cmh-code-line').first();
    await expect(pyLine).toBeVisible();
    const py = await pyLine.evaluate((line) => ({
      text: line.textContent,
      before: getComputedStyle(line, "::before").content,
    }));
    expect(py.before).toContain("counter(");
    expect(py.text.trim().startsWith("1")).toBe(false);

    const kqlLine = page.locator("figure.cmh-kql code .cmh-code-line.cmh-kql-line").first();
    await expect(kqlLine).toBeVisible();
    const kql = await kqlLine.evaluate((line) => ({
      text: line.textContent,
      before: getComputedStyle(line, "::before").content,
    }));
    expect(kql.before).toContain("counter(");
    expect(kql.text.trim().startsWith("1")).toBe(false);
  });

  test("code and KQL line gutters stay aligned when the ambient line-height is 'normal' (CMH-CODE-07)", async ({ page }) => {
    // A container whose line-height is the keyword `normal` - AND a direct `code { line-height:
    // normal }` theme reset, which beats the inherited <pre> value on the <code> the gutter actually
    // measures - used to leave getComputedStyle(...).lineHeight === "normal"; setupCodeLineNumbers()
    // then fell back to a hardcoded 20px per line and the gutter numbers drifted down a tall block.
    // The pinned numeric line-height on both the code <pre> and its <code> makes the computed value a
    // stable px so the gutter step tracks the real text line height even against that reset. A large
    // font makes a `normal` line box clearly taller than the old 20px fallback, so the drift (and its
    // absence after the fix) is measurable, and over 24 lines any per-line drift is amplified.
    const codeLines = Array.from({ length: 24 }, (_, i) => `row_${i + 1}=compute(${i + 1});`).join("\n");
    const kqlLines = Array.from({ length: 24 }, (_, i) => `| where Step==${i + 1}`).join("\n");
    const nestedLines = Array.from({ length: 24 }, (_, i) => `nested_${i + 1}=step(${i + 1});`).join("\n");
    const content =
      "<style>.cmh-lh-probe code { line-height: normal; }</style>"
      + '<div class="cmh-lh-probe" style="line-height: normal; font-size: 24px;">'
      + '<pre><code class="language-python">' + codeLines + "</code></pre>"
      + '<figure class="cmh-kql"><figcaption class="cmh-kql-cap"><span class="cmh-kql-title">Q</span></figcaption>'
      + '<pre><code class="language-kusto">' + kqlLines + "</code></pre></figure>"
      // A <code> nested below the <pre> (not a direct child): setupCodeLineNumbers() still measures it
      // via pre.querySelector("code"), so the pin must reach it as a descendant, not just `> code`.
      + '<pre class="cmh-nested-probe"><span><code class="language-python">' + nestedLines + "</code></span></pre>"
      + "</div>";
    const { html } = stageContent(content, { key: "cmh-code-lineheight-normal" });
    await page.goto(fileUrl(html));
    await ready(page);

    for (const sel of ["#commentRoot code.language-python", "#commentRoot figure.cmh-kql code.language-kusto"]) {
      const code = page.locator(sel).first();
      await expect(code).toBeVisible();
      const m = await code.evaluate((el) => {
        const cs = getComputedStyle(el);
        const gutterLines = [...el.querySelectorAll(".cmh-code-gutter > .cmh-code-line")];
        const first = parseFloat(gutterLines[0].style.top);
        const last = parseFloat(gutterLines[gutterLines.length - 1].style.top);
        const lineH = parseFloat(gutterLines[0].style.height);
        const step = gutterLines.length > 1 ? (last - first) / (gutterLines.length - 1) : lineH;
        // Rendered per-line height of the code text itself (a block with no vertical padding).
        const rendered = el.clientHeight / gutterLines.length;
        // Cumulative bottom of the gutter (last line top + its height) vs the rendered text height:
        // a per-line drift of even ~1.5px would compound to tens of px over 24 lines and fail here.
        const gutterBottom = last + lineH;
        return { lineHeight: cs.lineHeight, step, rendered, count: gutterLines.length,
          gutterBottom, clientHeight: el.clientHeight };
      });
      expect(m.count).toBe(24);
      // The pinned CSS line-height means getComputedStyle never returns the keyword `normal` - even
      // with a direct `code { line-height: normal }` reset - so the gutter never falls back to 20px.
      expect(m.lineHeight).not.toBe("normal");
      expect(parseFloat(m.lineHeight)).toBeGreaterThan(0);
      // The gutter's per-line step matches the computed line-height and the actual rendered text
      // line height, and its cumulative bottom lands on the block's rendered text height (no drift).
      expect(Math.abs(m.step - m.rendered)).toBeLessThan(1.5);
      expect(Math.abs(m.step - parseFloat(m.lineHeight))).toBeLessThan(1.5);
      expect(Math.abs(m.gutterBottom - m.clientHeight)).toBeLessThan(2);
    }

    // The nested <code> (measured via pre.querySelector("code")) is pinned as a descendant, so it
    // computes a numeric px line-height and its gutter never falls back to 20px either.
    const nested = page.locator("#commentRoot pre.cmh-nested-probe code.language-python").first();
    await expect(nested).toBeVisible();
    const n = await nested.evaluate((el) => ({
      lineHeight: getComputedStyle(el).lineHeight,
      count: el.querySelectorAll(".cmh-code-gutter > .cmh-code-line").length,
    }));
    expect(n.count).toBe(24);
    expect(n.lineHeight).not.toBe("normal");
    expect(parseFloat(n.lineHeight)).toBeGreaterThan(0);
  });


  test("selection and Copy buttons exclude generated line numbers (CMH-CODE-04)", async ({ page }) => {
    await openInline(page);
    const pyCode = page.locator('#commentRoot .cmh-code-wrap code.language-python').first();
    const pyText = await pyCode.evaluate((el) => el.textContent);
    const pySel = await pyCode.evaluate((el) => {
      const r = document.createRange();
      r.selectNodeContents(el);
      const s = window.getSelection();
      s.removeAllRanges();
      s.addRange(r);
      return s.toString();
    });
    expect(pySel).toBe(pyText);
    await page.locator('#commentRoot .cmh-code-wrap:has(code.language-python) .cm-code-copy').first().click();
    expect(await lastCopied(page)).toBe(pyText.replace(/\n$/, ""));

    const kqlCode = page.locator("figure.cmh-kql code.language-kusto").first();
    const kqlText = await kqlCode.evaluate((el) => el.textContent);
    const kqlSel = await kqlCode.evaluate((el) => {
      const r = document.createRange();
      r.selectNodeContents(el);
      const s = window.getSelection();
      s.removeAllRanges();
      s.addRange(r);
      return s.toString();
    });
    expect(kqlSel).toBe(kqlText);
    await page.locator("figure.cmh-kql .cm-code-copy").first().click();
    expect(await lastCopied(page)).toBe(kqlText.replace(/\n$/, ""));
  });

  test("every table column header gets sort chevrons", async ({ page }) => {
    await openInline(page);
    const heads = page.locator("#commentRoot table.cmh-sortable thead th");
    const n = await heads.count();
    expect(n).toBeGreaterThanOrEqual(3);
    for (let i = 0; i < n; i++) {
      await expect(heads.nth(i).locator(".cmh-sort-ctrl")).toHaveCount(1);
    }
  });

  test("a numeric column sorts numerically, cycling asc -> desc -> original", async ({ page }) => {
    await openInline(page);
    const original = await serviceOrder(page);
    expect(original).toEqual(["gateway", "auth", "catalog"]);

    const reqHeader = page.locator("#commentRoot table.cmh-sortable thead th", { hasText: "Requests" });
    const ctrl = reqHeader.locator(".cmh-sort-ctrl");

    await ctrl.click(); // ascending
    let order = await serviceOrder(page);
    expect(order.map((s) => REQ[s])).toEqual([340, 1200, 9800]);
    await expect(ctrl).toHaveAttribute("data-dir", "asc");

    await ctrl.click(); // descending
    order = await serviceOrder(page);
    expect(order.map((s) => REQ[s])).toEqual([9800, 1200, 340]);
    await expect(ctrl).toHaveAttribute("data-dir", "desc");

    await ctrl.click(); // back to authored order
    expect(await serviceOrder(page)).toEqual(original);
    await expect(ctrl).toHaveAttribute("data-dir", "");
  });

  test("a text column sorts lexicographically", async ({ page }) => {
    await openInline(page);
    const svcHeader = page.locator("#commentRoot table.cmh-sortable thead th", { hasText: "Service" });
    await svcHeader.locator(".cmh-sort-ctrl").click();
    expect(await serviceOrder(page)).toEqual(["auth", "catalog", "gateway"]);
  });

  // CMH-A11Y-12: the sorted header cell announces its direction to assistive tech via aria-sort.
  test("the sorted column header reflects direction via aria-sort (CMH-A11Y-12)", async ({ page }) => {
    await openInline(page);
    const reqHeader = page.locator("#commentRoot table.cmh-sortable thead th", { hasText: "Requests" });
    const svcHeader = page.locator("#commentRoot table.cmh-sortable thead th", { hasText: "Service" });
    const ctrl = reqHeader.locator(".cmh-sort-ctrl");
    // Unsorted columns carry no aria-sort at all (not "none"), matching the "no chevron dir" state.
    expect(await reqHeader.getAttribute("aria-sort")).toBeNull();

    await ctrl.click(); // ascending
    await expect(reqHeader).toHaveAttribute("aria-sort", "ascending");
    await expect(ctrl).toHaveAttribute("aria-pressed", "true");

    await ctrl.click(); // descending
    await expect(reqHeader).toHaveAttribute("aria-sort", "descending");

    // Sorting a DIFFERENT column clears the stale aria-sort on the first (only one column is sorted).
    await svcHeader.locator(".cmh-sort-ctrl").click();
    await expect(svcHeader).toHaveAttribute("aria-sort", "ascending");
    expect(await reqHeader.getAttribute("aria-sort")).toBeNull();

    // Cycling back to the authored order removes aria-sort entirely.
    await svcHeader.locator(".cmh-sort-ctrl").click(); // descending
    await svcHeader.locator(".cmh-sort-ctrl").click(); // authored order
    expect(await svcHeader.getAttribute("aria-sort")).toBeNull();
  });

  test("sorting keeps comment anchors attached, and the sort survives reload", async ({ page }) => {
    const warnings = [];
    page.on("console", (m) => { if (m.type() === "warning") warnings.push(m.text()); });
    await openInline(page);

    // Comment a cell in the sortable table, then sort by another column so its row moves.
    await addTextComment(page, '#commentRoot table.cmh-sortable tbody tr td:first-child', "gateway note", 0);
    const cid = await page.$eval("mark.cm-hl", (m) => m.dataset.cid);
    const before = await page.$eval(`mark.cm-hl[data-cid="${cid}"]`, (m) => m.textContent);

    const reqHeader = page.locator("#commentRoot table.cmh-sortable thead th", { hasText: "Requests" });
    await reqHeader.locator(".cmh-sort-ctrl").click(); // ascending: gateway row moves to the middle
    // The mark rode along with its row, still covering the same text.
    expect(await page.$eval(`mark.cm-hl[data-cid="${cid}"]`, (m) => m.textContent)).toBe(before);

    await page.reload();
    await ready(page);
    // The persisted sort was re-applied and the recomputed offset re-anchored the mark.
    expect(await page.$eval(`mark.cm-hl[data-cid="${cid}"]`, (m) => m.textContent)).toBe(before);
    expect(await serviceOrder(page)).toEqual(["auth", "gateway", "catalog"]);
    // The chevron UI also reflects the persisted sort after reload (not just the rows).
    await expect(reqHeader.locator(".cmh-sort-ctrl")).toHaveAttribute("data-dir", "asc");
    expect(warnings).toEqual([]);
  });

  // CMH-CORE-11 (sort-staleness): a multi-row highlight left DISCONTIGUOUS by a sort has stale
  // stored offsets (recomputeTextOffsets skips it), but its marks are still live. A new selection
  // overlapping one of those live marks must still be rejected (never nested) - the overlap guard
  // derives intervals from the live DOM, not the stale offsets.
  test("a sort that scatters a multi-row highlight still blocks an overlapping new comment (CMH-CORE-11)", async ({ page }) => {
    await openInline(page);
    // Select across the auth and catalog service rows (adjacent in authored order) so ONE comment's
    // marks span both. Sorting Requests ascending reorders to auth, gateway, catalog - gateway slides
    // between the two commented rows, making the highlight discontiguous.
    const spanRows = await page.evaluate(() => {
      const cells = {};
      document.querySelectorAll("#commentRoot table.cmh-sortable tbody tr td:first-child")
        .forEach((c) => { cells[c.textContent.trim()] = c; });
      const a = document.createTreeWalker(cells["auth"], NodeFilter.SHOW_TEXT).nextNode();
      const b = document.createTreeWalker(cells["catalog"], NodeFilter.SHOW_TEXT).nextNode();
      if (!a || !b) return false;
      cells["auth"].closest("table").scrollIntoView({ block: "center" });
      const r = document.createRange();
      r.setStart(a, 0); r.setEnd(b, b.data.length);
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
      cells["auth"].closest("table").dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 30, clientY: 30 }));
      return true;
    });
    expect(spanRows).toBe(true);
    await expect(page.locator("#menuComment")).toBeVisible();
    await page.locator("#menuComment").click();
    let composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("multi-row note");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);
    const cid = await page.$eval("mark.cm-hl", (m) => m.dataset.cid);
    // The highlight must actually span both rows for this test to exercise discontiguity.
    const rowsSpanned = await page.$$eval(`mark.cm-hl[data-cid="${cid}"]`,
      (marks) => new Set(marks.map((m) => m.closest("tr"))).size);
    expect(rowsSpanned, "the multi-row selection anchored across both rows").toBeGreaterThanOrEqual(2);

    // Sort so gateway slides between the two commented rows -> the highlight is now discontiguous
    // and recomputeTextOffsets leaves its stored offsets stale.
    const reqHeader = page.locator("#commentRoot table.cmh-sortable thead th", { hasText: "Requests" });
    await reqHeader.locator(".cmh-sort-ctrl").click();
    expect(await serviceOrder(page)).toEqual(["auth", "gateway", "catalog"]);

    // Select the catalog cell's now-moved marked text (which overlaps the existing highlight) and
    // try to comment it. With stale stored offsets a numeric guard would miss this and nest; the
    // live-interval guard rejects it.
    const opened = await page.evaluate(() => {
      const cell = [...document.querySelectorAll("#commentRoot table.cmh-sortable tbody tr td:first-child")]
        .find((c) => c.textContent.trim() === "catalog");
      const tn = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT).nextNode();
      if (!tn) return false;
      cell.scrollIntoView({ block: "center" });
      const r = document.createRange();
      r.setStart(tn, 0); r.setEnd(tn, tn.data.length);
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
      cell.closest("table").dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 30, clientY: 30 }));
      return true;
    });
    expect(opened).toBe(true);
    await expect(page.locator("#menuComment")).toBeVisible();
    await page.locator("#menuComment").click();
    composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("overlapping the scattered highlight");
    await composer.locator('[data-act="save"]').click();
    // Rejected: not-saved toast, no second comment, no nested mark.
    await expect(page.locator("#toast")).toContainText("Comment was not saved");
    const stored = await page.evaluate(() => {
      return window.__cmhStorageCodec.read();
    });
    expect(stored).toHaveLength(1);
    const nested = await page.evaluate(() => document.querySelectorAll("mark.cm-hl mark.cm-hl").length);
    expect(nested, "the scattered highlight is never nested into").toBe(0);
  });

  test("a scattered multi-row table highlight does not restore onto unrelated rows after reload (CMH-CONTENT-08)", async ({ page }) => {
    await openInline(page);
    const spanRows = await page.evaluate(() => {
      const cells = {};
      document.querySelectorAll("#commentRoot table.cmh-sortable tbody tr td:first-child")
        .forEach((c) => { cells[c.textContent.trim()] = c; });
      const a = document.createTreeWalker(cells["auth"], NodeFilter.SHOW_TEXT).nextNode();
      const b = document.createTreeWalker(cells["catalog"], NodeFilter.SHOW_TEXT).nextNode();
      if (!a || !b) return false;
      cells["auth"].closest("table").scrollIntoView({ block: "center" });
      const r = document.createRange();
      r.setStart(a, 0); r.setEnd(b, b.data.length);
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
      cells["auth"].closest("table").dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 30, clientY: 30 }));
      return true;
    });
    expect(spanRows).toBe(true);
    await expect(page.locator("#menuComment")).toBeVisible();
    await page.locator("#menuComment").click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("multi-row reload note");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);
    const cid = await page.$eval("mark.cm-hl", (m) => m.dataset.cid);

    const reqHeader = page.locator("#commentRoot table.cmh-sortable thead th", { hasText: "Requests" });
    await reqHeader.locator(".cmh-sort-ctrl").click();
    expect(await serviceOrder(page)).toEqual(["auth", "gateway", "catalog"]);
    const afterSort = await page.evaluate((id) => {
      return window.__cmhStorageCodec.read().find((c) => c.id === id);
    }, cid);
    expect(afterSort).toBeTruthy();
    expect(afterSort.start).toBeUndefined();
    expect(afterSort.end).toBeUndefined();

    await reqHeader.locator(".cmh-sort-ctrl").click();
    await reqHeader.locator(".cmh-sort-ctrl").click();
    expect(await serviceOrder(page)).toEqual(["gateway", "auth", "catalog"]);
    const afterUnsort = await page.evaluate((id) => {
      return window.__cmhStorageCodec.read().find((c) => c.id === id);
    }, cid);
    expect(afterUnsort.start).toEqual(expect.any(Number));
    expect(afterUnsort.end).toEqual(expect.any(Number));

    await reqHeader.locator(".cmh-sort-ctrl").click();
    expect(await serviceOrder(page)).toEqual(["auth", "gateway", "catalog"]);

    await page.reload();
    await ready(page);
    expect(await serviceOrder(page)).toEqual(["auth", "gateway", "catalog"]);
    await expect(page.locator(".cm-card").filter({ hasText: "multi-row reload note" })).toHaveCount(1);
    await expect(page.locator(`mark.cm-hl[data-cid="${cid}"]`)).toHaveCount(0);
    await expect(page.locator("#commentRoot table.cmh-sortable tbody tr", { hasText: "gateway" }).locator("mark.cm-hl")).toHaveCount(0);
    await page.locator("#btnCopyAll").click();
    const copied = await lastCopied(page);
    expect(copied).toContain("Offsets: unavailable");
    expect(copied).not.toContain("Offsets: [0, 0]");
  });

  test("a chart canvas is commentable like an image", async ({ page }) => {
    await openInline(page);
    const canvas = page.locator("#demoChart");
    await expect(canvas).toHaveClass(/cm-img-commentable/);
    await canvas.hover();
    const addBtn = page.locator("#imageAddBtn");
    await expect(addBtn).toBeVisible();
    await expect(addBtn).toHaveAttribute("title", /chart/i);
    await addBtn.click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("check the trend");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);
    // The card labels it as a chart, and the canvas gets the highlight ring.
    await expect(page.locator(".cm-card .quote")).toContainText(/chart/i);
    await expect(canvas).toHaveClass(/cm-img-hl/);
  });

  test("diffs are syntax-highlighted by default with a toggle to turn it off", async ({ page }) => {
    await openInline(page);
    const view = page.locator(".cmh-diff-view").first();
    await expect(view).toBeVisible();
    // The template diff is src/reducer.py -> python is inferred (attr on the host).
    await expect(page.locator(".cmh-diff-host").first()).toHaveAttribute("data-diff-lang", "python");
    // Highlighting is ON by default: token spans exist in the diff code.
    await expect(view.locator(".cmh-dl-code .cmh-code-kw").first()).toBeVisible();
    const hlToggle = view.locator(".cmh-diff-hltoggle");
    await expect(hlToggle).toHaveText("Syntax: on");

    await hlToggle.click();
    await expect(page.locator(".cmh-diff-view .cmh-diff-hltoggle").first()).toHaveText("Syntax: off");
    await expect(page.locator(".cmh-diff-view .cmh-dl-code .cmh-code-kw")).toHaveCount(0);

    // Turning it back on restores the tokens.
    await page.locator(".cmh-diff-view .cmh-diff-hltoggle").first().click();
    await expect(page.locator(".cmh-diff-view .cmh-dl-code .cmh-code-kw").first()).toBeVisible();
  });

  test("the side TOC reserves gutter space when expanded and reclaims it when collapsed", async ({ page }) => {
    await page.setViewportSize({ width: 1500, height: 900 });
    await openInline(page);
    await expect(page.locator("#cmSideToc")).toBeVisible();
    await expect(page.locator("body")).toHaveClass(/cm-side-toc-on/);
    const padded = await page.evaluate(() => parseFloat(getComputedStyle(document.body).paddingLeft));
    expect(padded).toBeGreaterThan(0);

    await page.locator("#cmSideToc .cm-side-toc-toggle").click();
    await expect(page.locator("body")).toHaveClass(/cm-side-toc-collapsed/);
    const collapsed = await page.evaluate(() => parseFloat(getComputedStyle(document.body).paddingLeft));
    expect(collapsed).toBe(0);
  });
});
