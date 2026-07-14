import { test, expect } from "@playwright/test";
import path from "path";
import {
  SKILL,
  copiedBundle,
  installClipboardCapture,
  ready,
  routeMermaidLocal,
  startStaticServer,
} from "./helpers.js";

const EXAMPLES = path.join(SKILL, "examples");

function parseRgb(value) {
  const match = String(value || "").match(/rgba?\(([^)]+)\)/);
  if (!match) throw new Error("unsupported color: " + value);
  const parts = match[1].split(",").map((part) => Number(part.trim()));
  return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
}

function composite(fg, bg) {
  const a = fg.a == null ? 1 : fg.a;
  return {
    r: fg.r * a + bg.r * (1 - a),
    g: fg.g * a + bg.g * (1 - a),
    b: fg.b * a + bg.b * (1 - a),
    a: 1,
  };
}

function luminance(color) {
  const channel = (value) => {
    const s = value / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
}

function contrast(a, b) {
  const l1 = luminance(a);
  const l2 = luminance(b);
  const hi = Math.max(l1, l2);
  const lo = Math.min(l1, l2);
  return (hi + 0.05) / (lo + 0.05);
}

async function openRoadmapDeck(page, { mermaid = false } = {}) {
  await installClipboardCapture(page);
  if (mermaid) await routeMermaidLocal(page);
  const server = await startStaticServer(EXAMPLES);
  await page.goto(server.url + "/deck-roadmap.html");
  await ready(page);
  return server;
}

async function settle(page) {
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function boxCenter(locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error("element is not visible");
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

async function slotDropPoint(locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error("slot is not visible");
  return { x: box.x + box.width / 2, y: box.y + Math.min(box.height - 12, 80) };
}

async function dragCardToSlot(page, cardSelector, slotSelector) {
  const start = await boxCenter(page.locator(cardSelector));
  const end = await slotDropPoint(page.locator(slotSelector));
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(end.x, end.y, { steps: 12 });
  await page.mouse.up();
  await settle(page);
}

test("CMH-DECK-08: roadmap deck risk cards drag between columns", async ({ page }) => {
  const server = await openRoadmapDeck(page);
  try {
    await page.evaluate(() => window.__cmhDeck.showSlideById("slide-56c4080c"));
    const card = '[data-cm-part="risk-exporter-perf"]';
    const target = '[data-cm-slot="Next"]';
    await expect(page.locator(target).locator(card)).toHaveCount(0);

    await dragCardToSlot(page, card, target);

    await expect(page.locator(target).locator(card)).toHaveCount(1);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable");
    const bundle = await copiedBundle(page);
    await page.evaluate(() => document.getElementById("btnCopyAll").click());
    expect(await copiedBundle(page)).not.toBe(bundle);
    expect(await copiedBundle(page)).toContain('"Exporter freeze" moved from Now to Next');
  } finally {
    await server.close();
  }
});

test("CMH-DECK-09: roadmap deck Mermaid diagram renders with dark-slide contrast", async ({ page }) => {
  const server = await openRoadmapDeck(page, { mermaid: true });
  try {
    await page.evaluate(() => window.__cmhDeck.showSlideById("slide-fc4dabb7"));
    await expect.poll(() => page.locator(".slide.active pre.mermaid svg g.node").count()).toBeGreaterThanOrEqual(5);

    const metrics = await page.evaluate(() => {
      const active = document.querySelector(".slide.active");
      const svg = active.querySelector("pre.mermaid svg");
      const node = svg.querySelector("g.node");
      const shape = node.querySelector("rect, polygon, circle, ellipse, path");
      const label = node.querySelector("foreignObject, .nodeLabel, text, span");
      const edge = svg.querySelector("g.edgePath path, .edgePaths path, path.flowchart-link");
      return {
        nodeCount: svg.querySelectorAll("g.node").length,
        edgeCount: svg.querySelectorAll("g.edgePath path, .edgePaths path, path.flowchart-link").length,
        slideBg: getComputedStyle(active).backgroundColor,
        nodeFill: getComputedStyle(shape).fill,
        labelColor: getComputedStyle(label).color || getComputedStyle(label).fill,
        edgeStroke: getComputedStyle(edge).stroke,
      };
    });
    const slideBg = parseRgb(metrics.slideBg);
    const nodeFill = composite(parseRgb(metrics.nodeFill), slideBg);
    const labelColor = parseRgb(metrics.labelColor);
    const edgeStroke = parseRgb(metrics.edgeStroke);
    expect(metrics.nodeCount).toBeGreaterThanOrEqual(5);
    expect(metrics.edgeCount).toBeGreaterThanOrEqual(5);
    expect(contrast(labelColor, nodeFill)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(edgeStroke, slideBg)).toBeGreaterThanOrEqual(3);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-10: roadmap deck table headers have readable contrast", async ({ page }) => {
  const server = await openRoadmapDeck(page);
  try {
    await page.evaluate(() => window.__cmhDeck.showSlideById("slide-6440fe2b"));
    const colors = await page.locator(".slide.active table thead th").first().evaluate((th) => {
      const slide = th.closest(".slide");
      const thStyle = getComputedStyle(th);
      return {
        slideBg: getComputedStyle(slide).backgroundColor,
        background: thStyle.backgroundColor,
        color: thStyle.color,
      };
    });
    const bg = composite(parseRgb(colors.background), parseRgb(colors.slideBg));
    const fg = parseRgb(colors.color);
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(4.5);
  } finally {
    await server.close();
  }
});
