import { test, expect } from "@playwright/test";
import { openInline, ready, lastCopied, addTextComment } from "./helpers.js";

// Requests column values in the template demo table, keyed by Service, so a test can
// assert numeric (not lexicographic) ordering.
const REQ = { gateway: 1200, auth: 340, catalog: 9800 };

async function serviceOrder(page) {
  return page.$$eval("#commentRoot table.cmh-sortable tbody tr td:first-child", (tds) => tds.map((t) => t.textContent.trim()));
}

test.describe("copy buttons + sortable tables", () => {
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
      const root = document.getElementById("commentRoot") || document.body;
      const key = root.dataset.commentKey || ("commentable-html:" + location.pathname);
      return JSON.parse(localStorage.getItem(key) || "[]");
    });
    expect(stored).toHaveLength(1);
    const nested = await page.evaluate(() => document.querySelectorAll("mark.cm-hl mark.cm-hl").length);
    expect(nested, "the scattered highlight is never nested into").toBe(0);
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
