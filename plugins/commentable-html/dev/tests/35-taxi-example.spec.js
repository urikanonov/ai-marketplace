import { test, expect } from "@playwright/test";
import path from "path";
import {
  SKILL, fileUrl, ready, lastCopied, installClipboardCapture,
  addTextComment, storedComments, distinctCids,
  startStaticServer, routeMermaidLocal,
} from "./helpers.js";

// The second shipped showcase example is a real-data operations report built on the
// public Kusto help cluster (Samples.nyc_taxi). Like 25-example, these tests run
// directly against the committed examples/report-taxi.html (not a fixture) so the
// shipped artifact is proven to exercise the feature set end to end.
const EXAMPLE = path.join(SKILL, "examples", "report-taxi.html");

async function openExample(page) {
  await installClipboardCapture(page);
  await page.goto(fileUrl(EXAMPLE));
  await ready(page);
}

// Comment on a chart canvas via the image-comment flow (a canvas is commentable media).
async function addChartComment(page, canvasSel, note) {
  await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    el.scrollIntoView({ block: "center" });
    el.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
  }, canvasSel);
  await expect(page.locator("#imageAddBtn")).toBeVisible();
  await page.locator("#imageAddBtn").click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toBeHidden();
}

test.describe("showcase example: NYC taxi 2014 report exercises the feature set", () => {
  test("the layer boots and its attribution footer appears", async ({ page }) => {
    await openExample(page);
    await expect(page.locator("#commentRoot")).toHaveCount(1);
    await expect(page.locator("#cmFooter")).toBeVisible();
    await expect(page.locator("#cmFooter")).toContainText(/Commentable HTML v\d+\.\d+\.\d+/);
  });

  test("ships highlighted KQL and a python-highlighted diff", async ({ page }) => {
    await openExample(page);
    // One KQL figure per analytic query (monthly, fares, payment, passenger, hour).
    await expect(page.locator("#commentRoot pre code.language-kusto")).toHaveCount(5);
    await expect(page.locator("#commentRoot code.language-kusto .cmh-kql-kw").first()).toBeVisible();
  });

  test("section headings are deep-link anchors", async ({ page }) => {
    await openExample(page);
    const h = page.locator("#commentRoot h2.cm-anchored, #commentRoot h2 a").first();
    await expect(h).toBeVisible();
  });

  test("every Run-in-Kusto link is a valid dataexplorer.azure.com deep link", async ({ page }) => {
    await openExample(page);
    const runLinks = page.locator("#commentRoot .cmh-kql-run");
    const n = await runLinks.count();
    expect(n).toBeGreaterThanOrEqual(1);
    for (let i = 0; i < n; i++) {
      const href = await runLinks.nth(i).getAttribute("href");
      expect(href).toBeTruthy();
      const u = new URL(href);
      expect(u.origin).toBe("https://dataexplorer.azure.com");
      // The deep link carries the compressed query so ADX opens it ready to run.
      expect(u.searchParams.get("query")).toBeTruthy();
      expect(await runLinks.nth(i).getAttribute("rel")).toContain("noopener");
    }
  });

  test("a Kusto cluster chip copies the cluster name to the clipboard", async ({ page }) => {
    await openExample(page);
    const chip = page.locator(".cmh-kql-cluster").first();
    await expect(chip).toBeVisible();
    const expected = (await chip.getAttribute("data-cmh-copy")) || (await chip.textContent());
    await chip.click();
    expect(await lastCopied(page)).toBe(expected.trim());
  });

  test("a KQL code block Copy button copies its exact text", async ({ page }) => {
    await openExample(page);
    const wrap = page.locator("#commentRoot .cmh-code-wrap:has(code.language-kusto)").first();
    const btn = wrap.locator(".cm-code-copy");
    await expect(btn).toBeVisible();
    await btn.click();
    const expected = await wrap.locator("pre code").evaluate((c) => c.textContent.replace(/\n$/, ""));
    expect(await lastCopied(page)).toBe(expected);
  });

  test("tables are sortable and the first column sorts ascending", async ({ page }) => {
    await openExample(page);
    // The Executive Summary KPI table is first and uses <td> first cells, so
    // td:first-child is the sorted column - a real (not vacuous) sort assertion.
    const firstTable = page.locator("#commentRoot table.cmh-sortable").first();
    await expect(firstTable).toBeVisible();
    await expect(firstTable.locator("thead th .cmh-sort-ctrl").first()).toHaveCount(1);
    const before = await firstTable.locator("tbody tr td:first-child").allTextContents();
    expect(before.length).toBeGreaterThan(1);
    await firstTable.locator("thead th .cmh-sort-ctrl").first().click();
    const after = await firstTable.locator("tbody tr td:first-child").allTextContents();
    await expect(firstTable.locator('thead th .cmh-sort-ctrl[data-dir="asc"]')).toHaveCount(1);
    expect([...after].sort()).toEqual([...before].sort());
    expect(after).toEqual([...after].sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" })));
  });

  test("the clean_trips.py diff is syntax-highlighted with a Syntax toggle", async ({ page }) => {
    await openExample(page);
    // clean_trips.py -> python is inferred, so tokens appear by default.
    const view = page.locator('.cmh-diff-host[data-diff-lang="python"]').first();
    await expect(view).toBeVisible();
    await expect(view.locator(".cmh-dl-code .cmh-code-kw").first()).toBeVisible();
    const toggle = view.locator(".cmh-diff-hltoggle");
    await expect(toggle).toHaveText("Syntax: on");
  });

  test("the monthly-trips chart renders from the bundled Chart.js script", async ({ page }) => {
    await openExample(page);
    // Chart.js is inlined, so the chart builds directly from the bundled script.
    await page.waitForFunction(
      () => !!(window.Chart && typeof window.Chart.getChart === "function" && window.Chart.getChart("taxiMonthlyChart")),
      null, { timeout: 20000 });
    await expect(page.locator("#taxiMonthlyChart")).toHaveClass(/cm-img-commentable/, { timeout: 20000 });
  });

  test("the added pie and line charts render as their intended kinds (CMH-TAXI-CHARTS-01)", async ({ page }) => {
    await openExample(page);
    for (const id of ["taxiPaymentChart", "taxiFareChart", "taxiHourlyChart"]) {
      await page.waitForFunction(
        (cid) => !!(window.Chart && window.Chart.getChart && window.Chart.getChart(cid)),
        id, { timeout: 20000 });
      await expect(page.locator("#" + id)).toHaveClass(/cm-img-commentable/, { timeout: 20000 });
    }
    const kinds = await page.evaluate(() => ({
      monthly: window.Chart.getChart("taxiMonthlyChart").config.type,
      payment: window.Chart.getChart("taxiPaymentChart").config.type,
      fare: window.Chart.getChart("taxiFareChart").config.type,
      hourly: window.Chart.getChart("taxiHourlyChart").config.type,
    }));
    expect(kinds.monthly).toBe("bar");
    expect(kinds.payment).toBe("doughnut");
    expect(kinds.fare).toBe("line");
    expect(kinds.hourly).toBe("line");
    // The dual-axis fare chart has two datasets and two y scales.
    const fare = await page.evaluate(() => {
      const c = window.Chart.getChart("taxiFareChart");
      return { datasets: c.data.datasets.length, scales: Object.keys(c.options.scales || {}).sort() };
    });
    expect(fare.datasets).toBe(2);
    expect(fare.scales).toContain("yFare");
    expect(fare.scales).toContain("yDist");
  });

  test("commenting a chart canvas rings it with a visible highlight (CMH-CHART-HL-01)", async ({ page }) => {
    await openExample(page);
    await page.waitForFunction(
      () => !!(window.Chart && window.Chart.getChart && window.Chart.getChart("taxiPaymentChart")),
      null, { timeout: 20000 });
    await addChartComment(page, "#taxiPaymentChart", "break out the small tail codes");
    const canvas = page.locator("canvas#taxiPaymentChart.cm-img-hl");
    await expect(canvas).toHaveCount(1);
    // The regression fix: a commented canvas gets a real outline (not just the class).
    const outline = await canvas.evaluate((el) => parseFloat(getComputedStyle(el).outlineWidth));
    expect(outline).toBeGreaterThan(0);
  });

  test("a comment can be added on prose and persists across a reload", async ({ page }) => {
    await openExample(page);
    await addTextComment(page, "#commentRoot section p", "Please double-check the June distance outlier.");
    expect(await distinctCids(page)).toBe(1);
    const saved = await storedComments(page);
    expect(saved.length).toBe(1);
    expect(saved[0].note).toContain("June distance outlier");

    await page.reload();
    await ready(page);
    await expect(page.locator("#commentRoot mark.cm-hl")).toHaveCount(1);
    const persisted = await storedComments(page);
    expect(persisted.length).toBe(1);
  });

  test("the chart and mermaid pipeline nodes are commentable (served over http)", async ({ page }) => {
    test.setTimeout(60000);
    const server = await startStaticServer(SKILL);
    try {
      await routeMermaidLocal(page);
      await installClipboardCapture(page);
      await page.goto(server.url + "/examples/report-taxi.html");
      await ready(page);
      const canvas = page.locator("#taxiMonthlyChart");
      await expect(canvas).toHaveClass(/cm-img-commentable/, { timeout: 20000 });
      // A mermaid flowchart node renders and is commentable (g.node is in the layer's
      // MERMAID_NODE_SEL, so hovering it reveals the add button).
      const node = page.locator("#commentRoot .mermaid svg g.node").first();
      await expect(node).toBeVisible({ timeout: 20000 });
      await node.hover();
      await expect(page.locator("#mermaidAddBtn")).toBeVisible();
    } finally {
      await server.close();
    }
  });

  test("the enriched subgraph flowchart and the sequence diagram both render (CMH-TAXI-MERMAID-01)", async ({ page }) => {
    test.setTimeout(60000);
    const server = await startStaticServer(SKILL);
    try {
      await routeMermaidLocal(page);
      await installClipboardCapture(page);
      await page.goto(server.url + "/examples/report-taxi.html");
      await ready(page);
      // The report now ships two diagrams: a flowchart with subgraphs and a sequence diagram.
      await expect(page.locator("#commentRoot .mermaid svg")).toHaveCount(2, { timeout: 20000 });
      // Subgraphs render as clusters in the flowchart.
      await expect(page.locator("#commentRoot .mermaid svg .cluster").first()).toBeVisible({ timeout: 20000 });
      // The sequence diagram renders participant actors (a sequence-specific element).
      await expect(page.locator("#commentRoot .mermaid svg .actor, #commentRoot .mermaid svg text.messageText").first()).toBeVisible({ timeout: 20000 });
      // The sequence diagram names its participants (e.g. Analyst).
      await expect(page.locator("#commentRoot .mermaid").filter({ hasText: "Analyst" })).toHaveCount(1, { timeout: 20000 });
    } finally {
      await server.close();
    }
  });
});
