import fs from "node:fs";
import { test, expect } from "@playwright/test";
import { ready, startStaticServer, routeMermaidLocal, routeExampleLibsLocal, awaitMermaidRendered, stageContent, EXAMPLES } from "./helpers.js";

const OLD = `flowchart TB
  A["Request a window"] --> B["Check raw cache"]
  B -->|miss| C["Read missing data"]
  C --> D["Merge and cache raw data"]
  D --> E["Prepare sequence"]
  B -->|hit| E
  E --> F["Return fresh result"]`;
const NEW = `flowchart TB
  A["Request a window"] --> B["Check prepared cache"]
  B -->|miss| C["Check raw cache"]
  C -->|miss| D["Read missing data"]
  D --> E["Merge and cache raw data"]
  E --> F["Prepare sequence"]
  C -->|hit| F
  F --> G["Cache prepared result"]
  G --> H["Return shared result"]
  B -->|hit| H`;

async function comparison(page, bare = false) {
  const left = `<pre class="mermaid cm-skip">${OLD}</pre>`;
  const right = `<div class="mermaid cm-skip">${NEW}</div>`;
  const { dir } = stageContent(`<h1>Flow comparison</h1>
    <div class="cmh-diagram-comparison" tabindex="0" role="region" aria-label="Flow comparison">
      ${bare ? left + right : `<figure><figcaption>Before</figcaption>${left}</figure><figure><figcaption>After</figcaption>${right}</figure>`}
    </div>`, { key: "paired-diagrams-regression" });
  const server = await startStaticServer(dir);
  try {
    await routeMermaidLocal(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await awaitMermaidRendered(page);
    return { async close() { await server.close(); fs.rmSync(dir, { recursive: true, force: true }); } };
  } catch (e) {
    await server.close();
    fs.rmSync(dir, { recursive: true, force: true });
    throw e;
  }
}

async function sizes(page) {
  return page.locator(".cmh-diagram-comparison > figure, .cmh-diagram-comparison > .mermaid").evaluateAll((cards) => cards.map((card) => {
    const host = card.matches(".mermaid") ? card : card.querySelector(".mermaid"), svg = host.querySelector("svg");
    const c = card.getBoundingClientRect(), h = host.getBoundingClientRect(), s = svg.getBoundingClientRect();
    const vb = svg.viewBox.baseVal;
    const labels = [...svg.querySelectorAll(".nodeLabel")].map((n) => n.getBoundingClientRect().height);
    return { x: c.x, y: c.y, width: c.width, svgWidth: s.width, svgHeight: s.height,
      topGap: s.top - h.top, bottomGap: h.bottom - s.bottom,
      aspect: s.width / s.height, naturalAspect: vb.width / vb.height, scale: s.width / vb.width,
      labelHeight: Math.min(...labels) };
  }));
}

test("paired tall diagrams fill equal columns without a gallery height cap (CMH-COMPARE-01)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const server = await comparison(page);
  try {
    const cards = await sizes(page);
    expect(Math.abs(cards[0].y - cards[1].y)).toBeLessThan(2);
    expect(cards[1].x).toBeGreaterThan(cards[0].x + cards[0].width);
    expect(Math.abs(cards[0].width - cards[1].width)).toBeLessThan(2);
    expect(Math.abs(cards[0].scale - cards[1].scale)).toBeLessThan(0.01);
    for (const card of cards) {
      expect(card.svgWidth).toBeGreaterThan(280);
      expect(card.svgHeight).toBeGreaterThan(550);
      expect(card.labelHeight).toBeGreaterThan(12);
      expect(Math.abs(card.aspect - card.naturalAspect)).toBeLessThan(0.01);
      expect(card.topGap).toBeLessThan(3);
      expect(card.bottomGap).toBeLessThan(3);
    }
    await page.setViewportSize({ width: 1100, height: 1000 });
    await expect.poll(async () => {
      const resized = await sizes(page);
      return Math.abs(resized[0].scale - resized[1].scale);
    }).toBeLessThan(0.01);
    await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
    expect(await page.locator("#cmhPrintSinglePage").count()).toBe(0);
    await page.emulateMedia({ media: "print" });
    const printed = await sizes(page);
    expect(printed[1].y).toBeGreaterThan(printed[0].y);
    expect(await page.locator(".cmh-diagram-comparison").evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    await page.evaluate(() => window.dispatchEvent(new Event("afterprint")));
    await page.emulateMedia({ media: "screen" });
    await expect.poll(async () => {
      const restored = await sizes(page);
      return Math.abs(restored[0].scale - restored[1].scale);
    }).toBeLessThan(0.01);
    await expect(page.locator(".cmh-diagram-comparison .cmh-diagram-narrow, .cmh-diagram-comparison .cmh-diagram-wide")).toHaveCount(0);
  } finally { await server.close(); }
});

test("direct comparison hosts keep shared scale after a Mermaid rerender (CMH-COMPARE-01)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const server = await comparison(page, true);
  try {
    let cards = await sizes(page);
    expect(Math.abs(cards[0].y - cards[1].y)).toBeLessThan(2);
    expect(Math.abs(cards[0].scale - cards[1].scale)).toBeLessThan(0.01);
    expect(await page.evaluate(() =>
      window.__cmhMermaidRerender(document.querySelector(".cmh-diagram-comparison > .mermaid"), { htmlLabels: false })
    )).toBe(true);
    await expect.poll(async () => {
      cards = await sizes(page);
      return Math.abs(cards[0].scale - cards[1].scale);
    }).toBeLessThan(0.01);
    expect(cards.every((card) => card.svgWidth > 280 && card.labelHeight > 12)).toBe(true);
  } finally { await server.close(); }
});

test("the shipped comparison demo renders two readable commentable flows (CMH-DEMO-COMPARE-01)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const server = await startStaticServer(EXAMPLES);
  try {
    await routeExampleLibsLocal(page);
    await page.goto(server.url + "/report-comparison.html");
    await ready(page);
    await awaitMermaidRendered(page);
    const cards = await sizes(page);
    expect(cards).toHaveLength(2);
    expect(Math.abs(cards[0].y - cards[1].y)).toBeLessThan(2);
    for (const card of cards) {
      expect(card.svgWidth).toBeGreaterThan(280);
      expect(card.labelHeight).toBeGreaterThan(12);
    }
    await page.locator(".cmh-diagram-comparison .mermaid").first().focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".cm-composer").last()).toBeVisible();
    expect(page.__external || []).toEqual([]);
  } finally { await server.close(); }
});

test("paired diagrams stay readable and keyboard-scroll sideways on phones (CMH-COMPARE-01)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const server = await comparison(page);
  try {
    const cards = await sizes(page);
    expect(Math.abs(cards[0].y - cards[1].y)).toBeLessThan(2);
    expect(cards[1].x).toBeGreaterThan(cards[0].x + cards[0].width);
    expect(cards[0].svgWidth).toBeGreaterThan(280);
    expect(Math.abs(cards[0].scale - cards[1].scale)).toBeLessThan(0.01);
    const region = page.getByRole("region", { name: "Flow comparison" });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await region.focus();
    await page.keyboard.press("ArrowRight");
    await expect.poll(() => region.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0);
    await page.locator(".cmh-diagram-comparison .mermaid").first().locator("g.node").first().hover();
    await expect(page.locator("#mermaidAddBtn")).toBeVisible();
    await region.evaluate((el) => { el.scrollLeft = el.scrollWidth; });
    await expect(page.locator("#mermaidAddBtn")).toBeHidden();
    const second = page.locator(".cmh-diagram-comparison .mermaid").nth(1);
    await second.focus();
    await page.keyboard.press("Enter");
    const composer = page.locator(".cm-composer").last();
    await expect(composer).toBeVisible();
    await composer.locator("textarea").fill("Keep the prepared path explicit");
    await composer.locator('[data-act="save"]').click();
    await expect(page.locator("#commentList")).toContainText("Keep the prepared path explicit");
  } finally { await server.close(); }
});
