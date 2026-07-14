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

async function openShowcaseDeck(page, { mermaid = false } = {}) {
  await installClipboardCapture(page);
  if (mermaid) await routeMermaidLocal(page);
  const server = await startStaticServer(EXAMPLES);
  await page.goto(server.url + "/deck-showcase.html");
  await ready(page);
  return server;
}

async function showSlideWith(page, selector) {
  const slideId = await page.locator(selector).first().evaluate((el) => el.closest(".slide").dataset.slideId);
  await page.evaluate((id) => window.__cmhDeck.showSlideById(id), slideId);
  return slideId;
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

async function effectiveContrast(page, selector) {
  const colors = await page.locator(selector).first().evaluate((el) => {
    function rgba(value) {
      const match = String(value || "").match(/rgba?\(([^)]+)\)/);
      if (!match) return { r: 0, g: 0, b: 0, a: 0 };
      const parts = match[1].split(",").map((part) => Number(part.trim()));
      return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
    }
    function over(top, bottom) {
      const a = top.a + bottom.a * (1 - top.a);
      if (a <= 0) return { r: 0, g: 0, b: 0, a: 0 };
      return {
        r: (top.r * top.a + bottom.r * bottom.a * (1 - top.a)) / a,
        g: (top.g * top.a + bottom.g * bottom.a * (1 - top.a)) / a,
        b: (top.b * top.a + bottom.b * bottom.a * (1 - top.a)) / a,
        a,
      };
    }
    let background = { r: 0, g: 0, b: 0, a: 0 };
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const color = rgba(getComputedStyle(node).backgroundColor);
      if (color.a > 0) background = over(background, color);
      if (background.a >= 0.99) break;
    }
    return { color: rgba(getComputedStyle(el).color), background };
  });
  return contrast(colors.color, colors.background);
}

test("CMH-DECK-08: showcase deck triage cards drag between columns", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, '[data-cm-widget="showcase-triage-board"]');
    const card = '[data-cm-part="risk-demo-weak"]';
    const target = '[data-cm-slot="Fix next"]';
    await expect(page.locator(target).locator(card)).toHaveCount(0);

    await dragCardToSlot(page, card, target);

    await expect(page.locator(target).locator(card)).toHaveCount(1);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable");
    const bundle = await copiedBundle(page);
    await page.evaluate(() => document.getElementById("btnCopyAll").click());
    expect(await copiedBundle(page)).not.toBe(bundle);
    expect(await copiedBundle(page)).toContain('"Weak demo deck" moved from Watch live to Fix next');
  } finally {
    await server.close();
  }
});

test("CMH-DECK-09: showcase deck Mermaid diagram renders with dark-slide contrast", async ({ page }) => {
  const server = await openShowcaseDeck(page, { mermaid: true });
  try {
    await showSlideWith(page, ".slide pre.mermaid");
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

test("CMH-DECK-10: showcase deck table headers have readable contrast", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, ".slide table thead th");
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

test("CMH-DECK-12: showcase deck code, KQL, and diff blocks keep dark-slide contrast", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, ".slide pre code.language-markdown");
    await expect(page.locator(".slide.active pre code.language-markdown")).toBeVisible();
    expect(await effectiveContrast(page, ".slide.active pre code.language-markdown")).toBeGreaterThanOrEqual(4.5);

    await showSlideWith(page, ".slide pre code.language-kusto");
    await expect(page.locator(".slide.active pre code.language-kusto")).toBeVisible();
    expect(await effectiveContrast(page, ".slide.active pre code.language-kusto")).toBeGreaterThanOrEqual(4.5);

    await showSlideWith(page, ".showcase-diff-slide .cmh-diff-view");
    await expect(page.locator(".slide.active .cmh-dl-add .cmh-dl-code").first()).toBeVisible();
    expect(await effectiveContrast(page, ".slide.active .cmh-dl-add .cmh-dl-code")).toBeGreaterThanOrEqual(4.5);
    expect(await effectiveContrast(page, ".slide.active .cmh-dl-del .cmh-dl-code")).toBeGreaterThanOrEqual(4.5);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-02: showcase deck mounts in deck mode and is commentable", async ({ page }) => {
  const server = await openShowcaseDeck(page, { mermaid: true });
  try {
    await expect(page).toHaveTitle(/Commentable HTML Showcase/);
    expect(await page.evaluate(() => window.__cmhDeck.slideCount())).toBeGreaterThanOrEqual(14);
    await expect(page.locator(".slide.active .showcase-comment-target")).toContainText(/review loop/i);
    await expect(page.locator(".cmh-deck-mode-toggle")).toBeVisible();
    await expect(page.locator(".cmh-deck-nav")).toBeVisible();

    await page.locator(".cmh-deck-mode-toggle").click();
    await expect(page.locator("#sidebar")).toBeVisible();
    await page.evaluate(() => {
      const el = document.querySelector(".slide.active .showcase-comment-target");
      const range = document.createRange();
      const text = el.firstChild;
      range.setStart(text, 0);
      range.setEnd(text, Math.min(text.textContent.length, 42));
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 220, clientY: 420 }));
    });
    await page.locator("#menuComment").click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("Tighten the opening proof point.");
    await composer.locator('[data-act="save"]').click();
    await expect(page.locator(".cm-card")).toContainText("Tighten the opening proof point.");

    await showSlideWith(page, ".showcase-chart-slide");
    await expect(page.locator(".slide.active figure.chart canvas.cmh-chart")).toHaveCount(1);
    await showSlideWith(page, ".showcase-diff-slide");
    await expect(page.locator(".slide.active .cmh-diff-host")).toBeVisible();
    await expect(page.locator(".slide.active .cmh-code-line").first()).toBeVisible();
    await showSlideWith(page, ".showcase-checklist-slide");
    await expect(page.locator(".slide.active [data-cmh-checklist].cmh-checklist-ready")).toHaveCount(1);
    await showSlideWith(page, ".slide pre.mermaid");
    await expect.poll(() => page.locator(".slide.active pre.mermaid svg g.node").count()).toBeGreaterThanOrEqual(5);
  } finally {
    await server.close();
  }
});
