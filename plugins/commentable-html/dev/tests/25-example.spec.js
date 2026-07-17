import { test, expect } from "@playwright/test";
import path from "path";
import {
  SKILL, fileUrl, ready, lastCopied, installClipboardCapture,
  startStaticServer, routeMermaidLocal,
} from "./helpers.js";

// The shipped showcase example must exercise every feature end to end, so these tests
// run directly against examples/report-community-garden.html (not a fixture).
const EXAMPLE = path.join(SKILL, "..", "..", "examples", "report-community-garden.html");

async function openExample(page) {
  await installClipboardCapture(page);
  await page.goto(fileUrl(EXAMPLE));
  await ready(page);
}

test.describe("showcase example: features work on the shipped example HTML", () => {
  test("ships highlighted Python and C# snippets", async ({ page }) => {
    await openExample(page);
    await expect(page.locator('#commentRoot pre code.language-python')).toHaveCount(1);
    await expect(page.locator('#commentRoot pre code.language-csharp')).toHaveCount(1);
    await expect(page.locator('#commentRoot code.language-csharp .cmh-code-kw').first()).toBeVisible();
  });

  test("the runtime attribution footer appears", async ({ page }) => {
    await openExample(page);
    await expect(page.locator("#cmFooter")).toBeVisible();
    await expect(page.locator("#cmFooter")).toContainText(/Commentable HTML v\d+\.\d+\.\d+/);
  });

  test("section headings are deep-link anchors", async ({ page }) => {
    await openExample(page);
    const h = page.locator("#commentRoot h2.cm-anchored, #commentRoot h2 a").first();
    await expect(h).toBeVisible();
  });

  test("a Kusto cluster chip copies to the clipboard", async ({ page }) => {
    await openExample(page);
    const chip = page.locator(".cmh-kql-cluster").first();
    await expect(chip).toBeVisible();
    const expected = (await chip.getAttribute("data-cmh-copy")) || (await chip.textContent());
    await chip.click();
    expect(await lastCopied(page)).toBe(expected.trim());
  });

  test("a code block Copy button copies its exact text", async ({ page }) => {
    await openExample(page);
    const wrap = page.locator("#commentRoot .cmh-code-wrap:has(code.language-python)").first();
    const btn = wrap.locator(".cm-code-copy");
    await expect(btn).toBeVisible();
    await btn.click();
    const expected = await wrap.locator("pre code").evaluate((c) => c.textContent.replace(/\n$/, ""));
    expect(await lastCopied(page)).toBe(expected);
  });

  test("tables are sortable with per-column chevrons", async ({ page }) => {
    await openExample(page);
    const firstTable = page.locator("#commentRoot table.cmh-sortable").first();
    await expect(firstTable).toBeVisible();
    await expect(firstTable.locator("thead th .cmh-sort-ctrl").first()).toHaveCount(1);
    const before = await firstTable.locator("tbody tr td:first-child").allTextContents();
    await firstTable.locator("thead th .cmh-sort-ctrl").first().click();
    const after = await firstTable.locator("tbody tr td:first-child").allTextContents();
    await expect(firstTable.locator('thead th .cmh-sort-ctrl[data-dir="asc"]')).toHaveCount(1);
    // Not presence-only: the result is a permutation of the input AND ascending-sorted
    // by the first column (so a no-op / all-rows-collapsed bug would fail).
    expect([...after].sort()).toEqual([...before].sort());
    expect(after).toEqual([...after].sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" })));
  });

  test("a code diff is syntax-highlighted with a Syntax toggle", async ({ page }) => {
    await openExample(page);
    // watering_schedule.py -> python is inferred, so tokens appear by default.
    const view = page.locator('.cmh-diff-host[data-diff-lang="python"]').first();
    await expect(view).toBeVisible();
    await expect(view.locator(".cmh-dl-code .cmh-code-kw").first()).toBeVisible();
    const toggle = view.locator(".cmh-diff-hltoggle");
    await expect(toggle).toHaveText("Syntax: on");
  });

  test("the chart is commentable and mermaid gantt/flowchart nodes are commentable (served over http)", async ({ page }) => {
    test.setTimeout(60000);
    const server = await startStaticServer(path.join(SKILL, "..", ".."));
    try {
      await routeMermaidLocal(page);
      await installClipboardCapture(page);
      await page.goto(server.url + "/examples/report-community-garden.html");
      await ready(page);
      // Chart canvas is commentable media.
      const canvas = page.locator("#wateringNeedsChart");
      await expect(canvas).toHaveClass(/cm-img-commentable/, { timeout: 20000 });
      // A mermaid gantt task label renders and is commentable. Narrow bars put the
      // label outside the bar (.taskTextOutside*), wide ones inside (.taskText).
      const taskLabel = page.locator("#commentRoot .mermaid svg .taskText, #commentRoot .mermaid svg .taskTextOutsideRight, #commentRoot .mermaid svg .taskTextOutsideLeft").first();
      await expect(taskLabel).toBeVisible({ timeout: 20000 });
      await taskLabel.hover();
      await expect(page.locator("#mermaidAddBtn")).toBeVisible();
      // The report now also ships a zone flowchart with subgraphs (rendered as clusters).
      await expect(page.locator("#commentRoot .mermaid svg .cluster").first()).toBeVisible({ timeout: 20000 });
    } finally {
      await server.close();
    }
  });
});
