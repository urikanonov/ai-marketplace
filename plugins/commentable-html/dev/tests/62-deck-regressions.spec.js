import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import {
  SKILL,
  copiedBundle,
  installClipboardCapture,
  ready,
  routeMermaidLocal,
  startStaticServer,
  enterCommentMode,
} from "./helpers.js";

const EXAMPLES = path.join(SKILL, "..", "..", "examples");

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

function boxesIntersect(a, b) {
  return !!(a && b
    && a.x < b.x + b.width
    && a.x + a.width > b.x
    && a.y < b.y + b.height
    && a.y + a.height > b.y);
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
    const card = '[data-cm-part="bed8-crop"]';
    const target = '[data-cm-slot="Decide now"]';
    await expect(page.locator(target).locator(card)).toHaveCount(0);

    await dragCardToSlot(page, card, target);

    await expect(page.locator(target).locator(card)).toHaveCount(1);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Not shareable");
    const bundle = await copiedBundle(page);
    await page.evaluate(() => document.getElementById("btnCopyAll").click());
    expect(await copiedBundle(page)).not.toBe(bundle);
    expect(await copiedBundle(page)).toContain('"Bed 8 crop choice" moved from Open to Decide now');
  } finally {
    await server.close();
  }
});

test("CMH-DECK-09: showcase deck Mermaid diagram renders with readable contrast", async ({ page }) => {
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
        edgeStrokeWidth: getComputedStyle(edge).strokeWidth,
        edgeFill: getComputedStyle(edge).fill,
        arrowFills: [...svg.querySelectorAll("marker path")].map((p) => getComputedStyle(p).fill),
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
    expect(Number.parseFloat(metrics.edgeStrokeWidth)).toBeGreaterThanOrEqual(2.4);
    // Edge connectors are stroked, not filled: a curved back-edge must not paint a solid blob by
    // filling the area under its curve with the dark slide color (the regression this guards).
    expect(metrics.edgeFill).toBe("none");
    // Arrowheads still keep a visible fill (so the direction markers do not vanish).
    expect(metrics.arrowFills.length).toBeGreaterThan(0);
    for (const fill of metrics.arrowFills) expect(fill).not.toBe("none");
  } finally {
    await server.close();
  }
});

test("CMH-MMD-08: deck Mermaid node labels are fully visible inside their node box", async ({ page }) => {
  const server = await openShowcaseDeck(page, { mermaid: true });
  try {
    await showSlideWith(page, ".slide pre.mermaid");
    await expect.poll(() => page.locator(".slide.active pre.mermaid svg g.node").count()).toBeGreaterThanOrEqual(5);
    await settle(page);

    const result = await page.evaluate(() => {
      const svg = document.querySelector(".slide.active pre.mermaid svg");
      const labels = [];
      const clipped = [];
      let nodeForeignObjects = 0;
      let svgTextLabels = 0;
      svg.querySelectorAll("g.node").forEach((node) => {
        const text = (node.textContent || "").trim();
        if (text) labels.push(text);
        if (node.querySelector("foreignObject")) nodeForeignObjects += 1;
        if (node.querySelector("text.nodeLabel, .nodeLabel text, tspan.text-outer-tspan, text")) svgTextLabels += 1;
        // HTML-label mode: the label lives in a foreignObject whose box mermaid sizes from a width
        // measurement. Inside a deck's CSS-scaled stage that measurement is wrong, so the box is too
        // small and the content clips - scrollWidth (content) then exceeds clientWidth (box).
        const div = node.querySelector("foreignObject div");
        if (div && div.scrollWidth - div.clientWidth > 1) {
          clipped.push({ text, mode: "html", over: div.scrollWidth - div.clientWidth });
          return;
        }
        // SVG-<text>-label mode: the rendered label must fit within the node shape (user units, so
        // the deck's uniform scale cancels out).
        const label = node.querySelector("text.nodeLabel, .nodeLabel, text");
        const shape = node.querySelector("rect, polygon, circle, ellipse");
        if (label && shape && label.getBBox && shape.getBBox) {
          const lw = label.getBBox().width;
          const sw = shape.getBBox().width;
          if (lw > sw + 2) clipped.push({ text, mode: "svg", labelWidth: Math.round(lw), shapeWidth: Math.round(sw) });
        }
      });
      // Issue #476 covers node AND edge labels. Edge labels also drop out of foreignObject under
      // htmlLabels:false; assert the labeled showcase edge renders and uses SVG text (no foreignObject,
      // and no clipped foreignObject box).
      let edgeForeignObjects = 0;
      const edgeTexts = [];
      svg.querySelectorAll("g.edgeLabel").forEach((edge) => {
        if (edge.querySelector("foreignObject")) edgeForeignObjects += 1;
        const div = edge.querySelector("foreignObject div");
        if (div && div.scrollWidth - div.clientWidth > 1) {
          clipped.push({ text: (edge.textContent || "").trim(), mode: "edge-html", over: div.scrollWidth - div.clientWidth });
        }
        const t = (edge.textContent || "").trim();
        if (t) edgeTexts.push(t);
      });
      return { labels, clipped, nodeForeignObjects, svgTextLabels, edgeForeignObjects, edgeTexts };
    });

    // The deck must actually be in the fixed SVG-<text> label mode (htmlLabels:false), not merely
    // "no clip observed at this viewport": assert node labels carry SVG text and NO foreignObject, so
    // a regression back to HTML labels fails even if the clip does not reproduce on this browser.
    expect(result.nodeForeignObjects, "deck node labels must not use a foreignObject").toBe(0);
    expect(result.svgTextLabels, "deck node labels must be SVG <text>").toBeGreaterThanOrEqual(5);
    // Edge labels are covered too: the showcase's labeled edge renders and uses SVG text.
    expect(result.edgeForeignObjects, "deck edge labels must not use a foreignObject").toBe(0);
    expect(result.edgeTexts.some((t) => t.replace(/\s+/g, "").includes("thenrepeat")),
      "the labeled showcase edge must render its text").toBe(true);
    // A known long label from the showcase flowchart must be rendered (SVG <text> wrapping can drop
    // the space at a wrap point, so compare with whitespace removed)...
    const normalized = result.labels.map((t) => t.replace(/\s+/g, ""));
    expect(normalized, "expected the long showcase node label to be rendered")
      .toContain("Agentwritesthegardenplan");
    // ...and no node or edge label may be clipped by its box.
    expect(result.clipped, "clipped deck labels: " + JSON.stringify(result.clipped)).toEqual([]);
  } finally {
    await server.close();
  }
});

test("CMH-MMD-08: deck mermaid comment labels preserve spaces across SVG-text wrapping", async ({ page }) => {
  const server = await openShowcaseDeck(page, { mermaid: true });
  try {
    await showSlideWith(page, ".slide pre.mermaid");
    await expect.poll(() => page.locator(".slide.active pre.mermaid svg g.node").count()).toBeGreaterThanOrEqual(5);
    await settle(page);
    await enterCommentMode(page);

    // The wrapped node's raw textContent drops the wrap-point space ("Agent writes the garden plan"
    // renders as "Agent writes the garden" + "plan"), so the runtime must rejoin the SVG <text> rows
    // to anchor and label it with the spaced words.
    const idx = await page.evaluate(() => {
      const nodes = [...document.querySelectorAll(".slide.active pre.mermaid svg g.node")];
      return nodes.findIndex((n) => (n.textContent || "").replace(/\s+/g, "").includes("Agentwritesthegardenplan"));
    });
    expect(idx, "expected the wrapped showcase node to be present").toBeGreaterThanOrEqual(0);
    const node = page.locator(".slide.active pre.mermaid svg g.node").nth(idx);
    await node.hover();
    await expect(page.locator("#mermaidAddBtn")).toBeVisible();
    await page.locator("#mermaidAddBtn").click();
    const composer = page.locator(".cm-composer").last();
    await expect(composer).toBeVisible();
    await composer.locator("textarea").fill("label spacing check");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);

    // Copy all quotes the anchored node with its spaces intact, not the space-dropped "gardenplan".
    await page.evaluate(() => document.getElementById("btnCopyAll").click());
    const bundle = await copiedBundle(page);
    expect(bundle).toContain("Agent writes the garden plan");
    expect(bundle).not.toContain("gardenplan");
  } finally {
    await server.close();
  }
});

test("CMH-MMD-08: a legacy deck mermaid anchor whose spacing differs re-attaches after the label mode change", async ({ page }) => {
  const server = await openShowcaseDeck(page, { mermaid: true });
  try {
    await showSlideWith(page, ".slide pre.mermaid");
    await expect.poll(() => page.locator(".slide.active pre.mermaid svg g.node").count()).toBeGreaterThanOrEqual(5);
    await settle(page);
    await enterCommentMode(page);

    const idx = await page.evaluate(() =>
      [...document.querySelectorAll(".slide.active pre.mermaid svg g.node")]
        .findIndex((n) => (n.textContent || "").replace(/\s+/g, "").includes("Agentwritesthegardenplan")));
    expect(idx).toBeGreaterThanOrEqual(0);
    const node = page.locator(".slide.active pre.mermaid svg g.node").nth(idx);
    await node.hover();
    await expect(page.locator("#mermaidAddBtn")).toBeVisible();
    await page.locator("#mermaidAddBtn").click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("legacy anchor");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);
    await expect(node).toHaveClass(/cm-mermaid-hl/);

    // Rewrite the persisted anchor to a space-DROPPED label key (the form an SVG-text deck produced
    // before the rejoin fix, or an HTML deck whose wrapped label concatenated without a space), then
    // reload. The current rendered/rejoined label keeps the space ("Agent writes the garden plan"),
    // so the exact `label:` match fails and only the whitespace-insensitive fallback can re-anchor it.
    const rewrote = await page.evaluate(() => {
      const arr = window.__cmhStorageCodec.read();
      let changed = false;
      arr.forEach((c) => {
        if (c && typeof c.nodeKey === "string" && c.nodeKey.replace(/\s+/g, "") === "label:Agentwritesthegardenplan") {
          c.nodeKey = "label:Agent writes the gardenplan";
          changed = true;
        }
      });
      window.__cmhStorageCodec.write(arr);
      return changed;
    });
    expect(rewrote, "expected a persisted mermaid anchor to rewrite").toBe(true);

    await page.reload();
    await ready(page);
    await showSlideWith(page, ".slide pre.mermaid");
    await expect.poll(() => page.locator(".slide.active pre.mermaid svg g.node").count()).toBeGreaterThanOrEqual(5);
    await settle(page);

    const reanchored = await page.evaluate(() =>
      [...document.querySelectorAll(".slide.active pre.mermaid svg g.node")]
        .some((n) => (n.textContent || "").replace(/\s+/g, "").includes("Agentwritesthegardenplan")
          && n.classList.contains("cm-mermaid-hl")));
    expect(reanchored, "the legacy-keyed comment must re-ring its node via the whitespace-insensitive fallback").toBe(true);
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

test("CMH-DECK-20: showcase deck chart hover shows a clipped-safe tooltip with the point label and value", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, ".showcase-chart-slide");
    await expect(page.locator(".slide.active figure.chart canvas.cmh-chart")).toHaveCount(1);
    const target = await page.evaluate(() => {
      const canvas = document.querySelector(".slide.active #showcaseChart");
      const chart = canvas && canvas._cmhChart;
      if (!canvas || !chart || !chart.points || !chart.points.length) return null;
      const point = chart.points[chart.points.length - 1];
      const rect = canvas.getBoundingClientRect();
      return {
        x: rect.left + point.x * (rect.width / chart.width),
        y: rect.top + Math.max(point.y + 4, point.top + 10) * (rect.height / chart.height),
        text: point.tooltip,
      };
    });
    expect(target).not.toBeNull();
    await page.mouse.move(target.x, target.y);
    const tooltip = page.locator(".cmh-chart-tooltip");
    await expect(tooltip).toHaveText(target.text);
    const metrics = await tooltip.evaluate((el) => {
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return {
        color: style.color,
        background: style.backgroundColor,
        left: rect.left,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        width: window.innerWidth,
        height: window.innerHeight,
      };
    });
    expect(contrast(parseRgb(metrics.color), parseRgb(metrics.background))).toBeGreaterThanOrEqual(4.5);
    expect(metrics.left).toBeGreaterThanOrEqual(0);
    expect(metrics.top).toBeGreaterThanOrEqual(0);
    expect(metrics.right).toBeLessThanOrEqual(metrics.width);
    expect(metrics.bottom).toBeLessThanOrEqual(metrics.height);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-43: showcase deck table cells gain a hover highlight without losing contrast", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, ".showcase-chart-slide");
    await enterCommentMode(page);
    const cell = page.locator(".slide.active table.show-table tbody tr").nth(1).locator("td").nth(2);
    // Perf (CMH-DECK-43): sweeping the mouse across cells felt laggy because each cell animated
    // box-shadow (a per-frame repaint) and a transform lift (which relayouts the table). The hover
    // now eases only the cheap background-color; the highlight ring snaps and no transform is applied.
    // Token-match the comma-separated transition-property list so a substring like transform-origin
    // cannot pass by accident.
    const cellTransitions = (await cell.evaluate((el) => getComputedStyle(el).transitionProperty))
      .split(",").map((s) => s.trim());
    expect(cellTransitions).toContain("background-color");
    expect(cellTransitions).not.toContain("box-shadow");
    expect(cellTransitions).not.toContain("transform");
    const before = await cell.evaluate((el) => {
      const style = getComputedStyle(el);
      return {
        background: style.backgroundColor,
        boxShadow: style.boxShadow,
      };
    });
    await cell.hover();
    await expect.poll(() => cell.evaluate((el) => getComputedStyle(el).boxShadow)).not.toBe(before.boxShadow);
    // No transform lift is applied to the cell on hover (a lift would relayout the table).
    expect(await cell.evaluate((el) => getComputedStyle(el).transform)).toBe("none");
    const hovered = await cell.evaluate((el) => {
      const style = getComputedStyle(el);
      return {
        background: style.backgroundColor,
        color: style.color,
        boxShadow: style.boxShadow,
      };
    });
    expect(hovered.background).not.toBe(before.background);
    expect(hovered.boxShadow).not.toBe("none");
    expect(contrast(parseRgb(hovered.color), parseRgb(hovered.background))).toBeGreaterThanOrEqual(4.5);
  } finally {
    await server.close();
  }
});

test("CMH-HL-05: the deck JSON key token inherits the slide theme's function-token color", async ({ page }) => {
  // The deck rule is `var(--cmh-deck-tok-key, var(--cmh-deck-tok-fn, ...))`. No deck theme declares
  // --cmh-deck-tok-key, so the CHAINED fallback to the theme's own fn token is what keeps a JSON key
  // legible on the light deck themes; the literal fallback would be a pale blue on near-white paper.
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, ".show-code-stack");
    const colors = await page.locator(".slide.active .show-code-stack").evaluate((stack) => {
      const probe = (cls) => {
        const el = document.createElement("span");
        el.className = cls;
        stack.appendChild(el);
        const color = getComputedStyle(el).color;
        el.remove();
        return color;
      };
      return { key: probe("cmh-code-key"), fn: probe("cmh-code-fn") };
    });
    expect(colors.key, "the deck key token resolves through to the theme's fn token").toBe(colors.fn);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-13: showcase deck code, KQL, and diff blocks keep readable contrast", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, ".showcase-diff-slide .cmh-diff-view");
    const diffTokenSelectors = [
      ".slide.active .cmh-diff-view .cmh-code-kw",
      ".slide.active .cmh-diff-view .cmh-code-str",
      ".slide.active .cmh-diff-view .cmh-code-num",
    ];
    const diffTokenColors = [];
    for (const selector of diffTokenSelectors) {
      await expect(page.locator(selector).first()).toBeVisible();
      diffTokenColors.push(await page.locator(selector).first().evaluate((el) => getComputedStyle(el).color));
      expect(await effectiveContrast(page, selector)).toBeGreaterThanOrEqual(4.5);
    }
    expect(new Set(diffTokenColors).size).toBe(diffTokenColors.length);
    await expect(page.locator(".slide.active .cmh-dl-add .cmh-dl-code").first()).toBeVisible();
    expect(await effectiveContrast(page, ".slide.active .cmh-dl-add .cmh-dl-code")).toBeGreaterThanOrEqual(4.5);
    expect(await effectiveContrast(page, ".slide.active .cmh-dl-del .cmh-dl-code")).toBeGreaterThanOrEqual(4.5);

    await showSlideWith(page, ".slide pre code.language-python");
    const codeTokenSelectors = [
      ".slide.active code.language-python .cmh-code-kw",
      ".slide.active code.language-python .cmh-code-str",
      ".slide.active code.language-python .cmh-code-num",
    ];
    const codeTokenColors = [];
    for (const selector of codeTokenSelectors) {
      await expect(page.locator(selector).first()).toBeVisible();
      codeTokenColors.push(await page.locator(selector).first().evaluate((el) => getComputedStyle(el).color));
      expect(await effectiveContrast(page, selector)).toBeGreaterThanOrEqual(4.5);
    }
    expect(new Set(codeTokenColors).size).toBe(codeTokenColors.length);

    await showSlideWith(page, ".slide pre code.language-kusto");
    const kqlTokenSelectors = [
      ".slide.active code.language-kusto .cmh-kql-kw",
      ".slide.active code.language-kusto .cmh-kql-str",
      ".slide.active code.language-kusto .cmh-kql-num",
    ];
    const kqlTokenColors = [];
    for (const selector of kqlTokenSelectors) {
      await expect(page.locator(selector).first()).toBeVisible();
      kqlTokenColors.push(await page.locator(selector).first().evaluate((el) => getComputedStyle(el).color));
      expect(await effectiveContrast(page, selector)).toBeGreaterThanOrEqual(4.5);
    }
    expect(new Set(kqlTokenColors).size).toBe(kqlTokenColors.length);
    await expect(page.locator(".slide.active .cmh-kql-run")).toBeVisible();
    expect(await effectiveContrast(page, ".slide.active .cmh-kql-run")).toBeGreaterThanOrEqual(4.5);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-02: showcase deck mounts in deck mode and is commentable", async ({ page }) => {
  const server = await openShowcaseDeck(page, { mermaid: true });
  try {
    await expect(page).toHaveTitle(/Commentable HTML Showcase/);
    expect(await page.evaluate(() => window.__cmhDeck.slideCount())).toBeGreaterThanOrEqual(14);
    await expect(page.locator(".slide.active .showcase-comment-target")).toContainText(/paste one bundle back/i);
    await expect(page.locator(".cmh-deck-mode-toggle")).toBeVisible();
    await expect(page.locator(".cmh-deck-nav")).toBeVisible();

    await enterCommentMode(page);
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
    await showSlideWith(page, "[data-cmh-checklist]");
    await expect(page.locator(".slide.active [data-cmh-checklist].cmh-checklist-ready")).toHaveCount(1);
    await showSlideWith(page, ".slide pre.mermaid");
    await expect.poll(() => page.locator(".slide.active pre.mermaid svg g.node").count()).toBeGreaterThanOrEqual(5);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-03: an early install CTA shows both agents before the final slide", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    const total = await page.evaluate(() => window.__cmhDeck.slideCount());
    const ids = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".slide")).map((slide) => slide.dataset.slideId),
    );
    const ctaId = "slide-12668385";
    const ctaIndex = ids.indexOf(ctaId);
    expect(ctaIndex).toBeGreaterThan(0);
    expect(ctaIndex).toBeLessThan(total - 1);

    const cta = page.locator(`[data-slide-id="${ctaId}"]`);
    const text = await cta.evaluate((el) => el.textContent);
    expect(text).toContain("copilot plugin marketplace add https://github.com/urikanonov/ai-marketplace");
    expect(text).toContain("copilot plugin install commentable-html@urikan-ai-marketplace");
    expect(text).toContain("claude plugin marketplace add https://github.com/urikanonov/ai-marketplace");
    expect(text).toContain("claude plugin install commentable-html@urikan-ai-marketplace");

    await expect(cta.locator('a[href="https://github.com/urikanonov/ai-marketplace"]')).toHaveCount(1);
    await expect(cta.locator('a[href="https://urikanonov.github.io/ai-marketplace/"]')).toHaveCount(1);
    await expect(cta.locator('a[href="https://urikanonov.github.io/ai-marketplace/commentable-html/tutorial/"]')).toHaveCount(1);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-05: showcase deck front-loads the comparison and prompts, keeps widget defaults, and closes with what's next plus questions", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    const ids = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".slide")).map((slide) => slide.dataset.slideId),
    );
    expect(ids.indexOf("slide-bdd3b1b5")).toBeGreaterThan(ids.indexOf("slide-76b2501c"));
    expect(ids.indexOf("slide-bdd3b1b5")).toBeLessThan(ids.indexOf("slide-4bfbc689"));
    expect(ids.indexOf("slide-4bfbc689")).toBeLessThan(ids.indexOf("slide-7e37216a"));
    expect(ids.indexOf("slide-7e37216a")).toBeLessThan(ids.indexOf("slide-12668385"));
    expect(ids.indexOf("slide-9a891595")).toBe(ids.indexOf("slide-90e72651") - 1);

    await showSlideWith(page, '[data-slide-id="slide-bdd3b1b5"]');
    await expect(page.locator(".slide.active")).toContainText("Chat / terminal");
    await expect(page.locator(".slide.active")).toContainText("Commentable HTML");

    await showSlideWith(page, '[data-cm-widget="showcase-triage-board"]');
    const board = page.locator(".slide.active");
    await expect(board.locator('[data-cm-part="bed8-crop"]')).toContainText("Bed 8 crop choice");
    await expect(board.locator('[data-cm-slot="Open"] .show-ticket')).toHaveCount(2);
    await expect(board.locator('[data-cm-slot="Decide now"] .show-ticket')).toHaveCount(1);
    await expect(board.locator('[data-cm-slot="Locked"] .show-ticket')).toHaveCount(1);

    await showSlideWith(page, '[data-slide-id="slide-9a891595"]');
    await expect(page.locator(".slide.active")).toContainText("What's next?");
    await expect(page.locator(".slide.active .show-next-card")).toHaveCount(5);

    await showSlideWith(page, '[data-slide-id="slide-90e72651"]');
    await expect(page.locator(".slide.active")).toContainText("Questions?");
    await expect(page.locator(".slide.active")).toContainText("use the deck itself as the review surface");
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-06: Act 4 slides explain the deterministic build, shareability, and test model", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, "text=Anatomy of a commentable file.");
    const anatomy = page.locator(".slide.active");
    await expect(anatomy).toContainText("CSS region");
    await expect(anatomy).toContainText("COMMENT UI region");
    await expect(anatomy).toContainText("JS region");
    await expect(anatomy).toContainText("CONTENT region");
    await expect(anatomy).toContainText("That separation is why upgrades stay deterministic");
    await expect(anatomy).toContainText("The build swaps only the layer-owned regions and re-stamps the version");

    await showSlideWith(page, "text=Three shareability modes explain every handoff.");
    const shareability = page.locator(".slide.active");
    await expect(shareability).toContainText("Non-shareable");
    await expect(shareability).toContainText("Shareable");
    await expect(shareability).toContainText("Offline");
    await expect(shareability).toContainText("Styles + runtime");
    await expect(shareability).toContainText("skill folder");
    await expect(shareability).toContainText("CDN");
    await expect(shareability).toContainText("vendored runtimes");
    await expect(shareability).toContainText("browser storage");
    await expect(shareability).toContainText("seeded from HTML");

    await showSlideWith(page, "text=How the skill is built.");
    const build = page.locator(".slide.active");
    await expect(build).toContainText("SKILL.md");
    await expect(build).toContainText("references/document-layout.md");
    await expect(build).toContainText("references/design-decisions.md");
    await expect(build).toContainText("tools/authoring/retrofit.py");
    await expect(build).toContainText("tools/validate/validate.py --strict");
    await expect(build).toContainText("loaded on demand to keep context minimal");

    await showSlideWith(page, "text=Testing and validation keep the HTML honest.");
    const testing = page.locator(".slide.active");
    await expect(testing).toContainText("Playwright");
    await expect(testing).toContainText("plugin-tests.yml");
    await expect(testing).toContainText("Windows, macOS, and Linux");
    await expect(testing).toContainText("Copilot and Claude");
    await expect(testing).toContainText("test_*.py");
  } finally {
    await server.close();
  }
});

test("CMH-DECK-38: cross-card comments do not highlight whitespace-only grid gaps", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await enterCommentMode(page);
    await showSlideWith(page, '[data-slide-id="slide-3d5c8a12"]');

    await page.evaluate(() => {
      const realTexts = (el) => {
        const out = [];
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        let n;
        while ((n = walker.nextNode())) {
          if ((n.textContent || "").trim()) out.push(n);
        }
        return out;
      };
      const cards = document.querySelectorAll('.slide.active .show-card p');
      const left = realTexts(cards[0])[1];
      const right = realTexts(cards[1])[1] || realTexts(cards[1])[0];
      const range = document.createRange();
      range.setStart(left, 1);
      range.setEnd(right, Math.min(right.textContent.length, 24));
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      cards[1].dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 700, clientY: 300 }));
    });
    await page.locator("#menuComment").click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("Keep the strict validator callout together.");
    await composer.locator('[data-act="save"]').click();

    const marks = await page.locator('mark.cm-hl').evaluateAll((els) => els.map((el) => {
      const rect = el.getBoundingClientRect();
      return {
        text: el.textContent || "",
        parentClass: el.parentElement ? el.parentElement.className : "",
        width: rect.width,
        height: rect.height,
      };
    }));
    expect(marks.some((mark) =>
      !mark.text.trim()
      && mark.parentClass.includes("show-two")
      && mark.width > 20
      && mark.height > 20,
    )).toBe(false);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-21: deck chrome keeps distinct overview and slide-count pills", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    const chrome = await page.evaluate(() => {
      const nav = document.querySelector(".cmh-deck-nav");
      const prev = nav.querySelector('button[aria-label="Prev slide"]');
      const overview = nav.querySelector(".cmh-deck-overview-button");
      const count = nav.querySelector(".cmh-deck-count");
      const navStyle = getComputedStyle(nav);
      const prevStyle = getComputedStyle(prev);
      const overviewStyle = getComputedStyle(overview);
      const countStyle = getComputedStyle(count);
      return {
        prevBg: prevStyle.backgroundColor,
        overviewBg: overviewStyle.backgroundColor,
        countBg: countStyle.backgroundColor,
        navBg: navStyle.backgroundColor,
        countRadius: countStyle.borderRadius,
        countPaddingLeft: countStyle.paddingLeft,
      };
    });

    expect(chrome.overviewBg).not.toBe(chrome.prevBg);
    expect(chrome.countBg).not.toBe(chrome.navBg);
    expect(parseFloat(chrome.countRadius)).toBeGreaterThanOrEqual(20);
    expect(parseFloat(chrome.countPaddingLeft)).toBeGreaterThan(0);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-39: the showcase Locked column Add Comment affordance avoids Reset moves", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await enterCommentMode(page);
    await showSlideWith(page, '[data-cm-widget="showcase-triage-board"]');

    await dragCardToSlot(page, '[data-cm-part="bed8-crop"]', '[data-cm-slot="Locked"]');
    await page.locator('[data-cm-part="slot-locked"]').focus();
    await expect(page.locator("#widgetAddBtn")).toBeVisible();
    await expect(page.locator(".show-board .cm-widget-reset")).toBeVisible();

    const addBox = await page.locator("#widgetAddBtn").boundingBox();
    const resetBox = await page.locator(".show-board .cm-widget-reset").boundingBox();
    expect(boxesIntersect(addBox, resetBox)).toBe(false);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-07: the problem, point-at, and install slides use the new visual chrome", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, ".show-static-comment");
    await expect(page.locator(".slide.active .show-static-target")).toHaveCount(1);
    await expect(page.locator(".slide.active .show-static-comment")).toContainText("make it clearer");

    await showSlideWith(page, ".show-card-example");
    const pointAt = page.locator(".slide.active");
    await expect(pointAt.locator(".show-card-example")).toHaveCount(4);
    const titleChrome = await pointAt.locator(".show-four .show-card h3").evaluateAll((els) =>
      els.map((el) => ({
        whiteSpace: getComputedStyle(el).whiteSpace,
        textOverflow: getComputedStyle(el).textOverflow,
      })),
    );
    titleChrome.forEach((item) => {
      expect(item.whiteSpace).toBe("nowrap");
      expect(item.textOverflow).toBe("ellipsis");
    });
    const demo = pointAt.locator('a.show-link-pill[href="https://urikanonov.github.io/ai-marketplace/commentable-html/#demo"]');
    await expect(demo).toContainText("View Live Demo");
    await expect(demo.locator(".show-link-icon")).toHaveCount(1);

    const cta = page.locator('[data-slide-id="slide-12668385"]');
    await expect(cta.locator("a.show-link-pill")).toHaveCount(3);
    await expect(cta.locator(".show-link-pill .show-link-icon")).toHaveCount(3);
    await expect(cta.locator('a.show-link-pill[href="https://github.com/urikanonov/ai-marketplace"]')).toHaveCount(1);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-08: the showcase deck includes supported syntax labels, live editable notes, and a review checklist", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    // Measure with the review panel open (deck comment mode), the state a reviewer actually uses.
    await enterCommentMode(page);
    // Supported syntax labels live on the code / KQL / diff slide (slide 11).
    await showSlideWith(page, ".show-supported-panel");
    const labels = page.locator(".slide.active");
    await expect(labels.locator(".show-supported-pills .show-pill")).toHaveCount(12);
    await expect(labels.locator(".show-supported-panel")).toContainText("Python");
    await expect(labels.locator(".show-supported-panel")).toContainText("TypeScript");
    await expect(labels.locator(".show-supported-panel")).toContainText("PowerShell");
    await expect(labels.locator(".show-supported-panel")).toContainText("Markdown");
    await expect(labels.locator(".show-supported-panel")).toContainText("+50 more");
    // The rebalanced code/diff slide still fits the fixed 1080px stage (no overflow/clipping).
    expect(await labels.evaluate((el) => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(4);
    // Live editable notes and the review checklist share the notes slide (slide 12).
    await showSlideWith(page, ".show-note-live");
    const slide = page.locator(".slide.active");
    await expect(slide.locator("[data-cmh-checklist].cmh-checklist-ready")).toHaveCount(1);
    expect(await slide.evaluate((el) => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(4);
    // The notes demo is the REAL notes feature, not a static mock: two [data-cmh-note] elements the
    // runtime has upgraded into editable textareas.
    await expect(slide.locator(".show-note-live[data-cmh-note]")).toHaveCount(2);
    const inputs = slide.locator(".show-note-live textarea.cmh-note-input");
    await expect(inputs).toHaveCount(2);
    await expect(slide.locator(".cmh-note-label").first()).toContainText("Reviewer summary");
    await expect(slide.locator(".cmh-note-label").nth(1)).toContainText("Meeting follow-up");
    // The second note is foldable (has a fold disclosure button).
    await expect(slide.locator(".show-note-live .cmh-note-fold")).toHaveCount(1);
    // Both notes are multi-line, so each renders a single/multi-line toggle.
    await expect(slide.locator(".show-note-live .cmh-note-toggle")).toHaveCount(2);
    // Editing a note is live and change-tracked: typing surfaces a per-note change card in the sidebar.
    const first = inputs.first();
    await first.click();
    await first.fill("Reviewed - ship it.");
    const card = page.locator('.cm-card-note[data-cmh-note-name="showcase-reviewer-summary"]');
    await expect(card).toHaveCount(1);
    // The note change card's jump is deck-aware: after navigating to another slide, jump returns to
    // the note's owning slide (a plain scrollIntoView cannot reveal an inactive slide).
    const notesSlideId = await slide.evaluate((el) => el.dataset.slideId);
    const otherSlideId = await page.evaluate((skip) => {
      const ids = [...document.querySelectorAll(".slide[data-slide-id]")]
        .map((s) => s.dataset.slideId).filter((id) => id && id !== skip);
      return ids[0];
    }, notesSlideId);
    expect(otherSlideId, "deck needs another slide to navigate to").toBeTruthy();
    await page.evaluate((id) => window.__cmhDeck.showSlideById(id), otherSlideId);
    await expect.poll(() => page.evaluate(() => window.__cmhDeck.activeSlideId())).toBe(otherSlideId);
    await card.locator('[data-act="note-jump"]').click();
    await expect.poll(() => page.evaluate(() => window.__cmhDeck.activeSlideId())).toBe(notesSlideId);
    // The decision-board slide (slide 13) keeps the triage board and, after the checklist moved off
    // it, gained a short widget caption; the checklist is no longer on this slide.
    await showSlideWith(page, '[data-cm-widget="showcase-triage-board"]');
    const board = page.locator(".slide.active");
    await expect(board.locator("[data-cmh-checklist]")).toHaveCount(0);
    await expect(board.locator("p.show-lead")).toContainText("commentable widget");
    expect(await board.evaluate((el) => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(4);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-20: the showcase deck teaches the selective hand-back", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, "text=Send back the comments you choose, not always all of them.");
    const slide = page.locator(".slide.active");
    await expect(slide.locator(".show-kicker")).toHaveText("Act 2 - Hand back only part of it");
    // The four controls the feature ships, named on the slide a viewer can try them from.
    await expect(slide).toContainText("Select");
    await expect(slide).toContainText("Copy selected");
    await expect(slide).toContainText("Clear selection");
    await expect(slide).toContainText("Clear selected comments");
    // ...and WHY a partial hand-back is safe, which is the part a viewer cannot infer from the UI.
    await expect(slide.locator("p.show-lead")).toContainText("partial hand-back");
    // It follows the two-prompt loop slide, so the deck teaches the whole round-trip before
    // narrowing it, and the slide fits its stage.
    const order = await page.evaluate(() => {
      const slides = [...document.querySelectorAll(".slide")];
      const at = (t) => slides.findIndex((s) => (s.textContent || "").includes(t));
      return { loop: at("Two simple prompts cover the"), pick: at("Send back the comments you choose") };
    });
    expect(order.pick, "the selective slide follows the loop slide").toBe(order.loop + 1);
    expect(await slide.evaluate((el) => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(4);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-09: the showcase deck shows a concrete Copy all bundle specimen", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, "text=How a comment finds the same spot on reload.");
    const anchoring = page.locator(".slide.active");
    const bundle = anchoring.locator(".show-bundle-sample");
    await expect(bundle).toBeVisible();
    await expect(bundle).toContainText("Quote:");
    await expect(bundle).toContainText("Pinpoint:");
    await expect(bundle).toContainText("Stable id:");
    await expect(bundle).toContainText("Note:");
    await expect(bundle).toContainText("HANDLED_IDS_JSON:");
    await expect(bundle.locator("code")).toHaveCount(0);

    await showSlideWith(page, "text=Comment on the actual thing, not a screenshot of it.");
    const pointAt = page.locator(".slide.active");
    await expect(pointAt).toContainText('Example: the "Copy all, paste, press Enter" node.');
    await expect(pointAt).not.toContainText("Copy all Markdown bundle");
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-12: showcase slides pin the header and center the body below it", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, ".show-card-example");
    const m = await page.locator(".slide.active").evaluate((slide) => {
      const rect = slide.getBoundingClientRect();
      const style = getComputedStyle(slide);
      const h2 = slide.querySelector(":scope > h2");
      const subtitle = h2 && h2.nextElementSibling && h2.nextElementSibling.classList.contains("show-lead")
        ? h2.nextElementSibling : null;
      const firstBody = (subtitle || h2).nextElementSibling;
      const lastBody = slide.lastElementChild;
      if (!firstBody || !lastBody) {
        return { error: "no body element after the header on " + slide.dataset.slideId };
      }
      const headerBottom = (subtitle || h2).getBoundingClientRect().bottom;
      return {
        display: style.display,
        flexDirection: style.flexDirection,
        justifyContent: style.justifyContent,
        gapTop: firstBody.getBoundingClientRect().top - headerBottom,
        gapBottom: rect.bottom - lastBody.getBoundingClientRect().bottom,
        stageHeight: rect.height,
      };
    });
    expect(m.display).toBe("flex");
    expect(m.flexDirection).toBe("column");
    expect(m.error, m.error || "ok").toBeUndefined();
    // The header (kicker + title + subtitle) is pinned at the top for a stable baseline, so content
    // slides top-align rather than centering the whole slide.
    expect(m.justifyContent).toBe("flex-start");
    // The body is centered in the working area below the header (auto top/bottom margins), so a light
    // slide does not leave a large empty band at the bottom: the space above the body ~= below it.
    expect(m.gapTop).toBeGreaterThan(0);
    expect(m.gapBottom).toBeGreaterThan(0);
    expect(Math.abs(m.gapTop - m.gapBottom)).toBeLessThan(m.stageHeight * 0.06);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-10: every showcase slide has a top-right site brand mark", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    const logo = page.locator('a.show-corner-logo[href="https://urikanonov.github.io/ai-marketplace/commentable-html/"]');
    await expect(logo).toHaveCount(1);
    await expect(logo).toHaveAttribute("href", "https://urikanonov.github.io/ai-marketplace/commentable-html/");
    await expect(logo).toHaveAttribute("target", "_blank");
    await expect(logo).toHaveAttribute("title", "Commentable HTML");
    // The official Commentable HTML logo rendered as a plain image (not the old bordered card).
    const img = logo.locator("img.show-corner-logo-img");
    await expect(img).toHaveCount(1);
    await expect(img).toHaveAttribute("src", /^data:image\/svg\+xml/);
    await expect(logo.locator("svg")).toHaveCount(0);
    const border = await logo.evaluate((el) => getComputedStyle(el).borderTopWidth);
    expect(border).toBe("0px");
    const ids = await page.evaluate(() => Array.from(document.querySelectorAll(".slide")).map((slide) => slide.dataset.slideId));
    for (const id of [ids[0], ids[Math.floor(ids.length / 2)], ids[ids.length - 1]]) {
      await page.evaluate((slideId) => window.__cmhDeck.showSlideById(slideId), id);
      await expect(logo).toBeVisible();
    }
    const pos = await logo.evaluate((el) => {
      const logoRect = el.getBoundingClientRect();
      const slideRect = document.querySelector(".slide.active").getBoundingClientRect();
      return {
        rightGap: slideRect.right - logoRect.right,
        topGap: logoRect.top - slideRect.top,
        slideWidth: slideRect.width,
        slideHeight: slideRect.height,
      };
    });
    expect(pos.rightGap).toBeGreaterThanOrEqual(0);
    expect(pos.rightGap).toBeLessThan(pos.slideWidth * 0.06);
    expect(pos.topGap).toBeGreaterThanOrEqual(0);
    expect(pos.topGap).toBeLessThan(pos.slideHeight * 0.05);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-11: showcase amber title highlights do not paint a halo above the line", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    // Cover EVERY highlight (title h1, header h1, and h2 headings, single- and multi-line), not just
    // the first slide: navigate to each slide that carries a .show-mark and assert the contract on
    // its visible marks (computed styles only resolve reliably on the active, rendered slide).
    const slideIds = await page.evaluate(() => {
      const ids = new Set();
      document.querySelectorAll(".slide .show-mark").forEach((m) => ids.add(m.closest(".slide").dataset.slideId));
      return [...ids];
    });
    expect(slideIds.length).toBeGreaterThan(0);
    let checked = 0;
    for (const id of slideIds) {
      await page.evaluate((x) => window.__cmhDeck.showSlideById(x), id);
      const marks = await page.$$eval(".slide.active .show-mark", (nodes) =>
        nodes.map((el) => {
          const style = getComputedStyle(el);
          return {
            image: style.backgroundImage,
            boxShadow: style.boxShadow,
            posY: parseFloat(style.backgroundPositionY),
            capPx: parseFloat(style.backgroundSize.split(" ")[1]),
            fontPx: parseFloat(style.fontSize),
            linePx: parseFloat(style.lineHeight),
          };
        }),
      );
      expect(marks.length).toBeGreaterThan(0);
      for (const m of marks) {
        // Height-capped linear-gradient, no halo.
        expect(m.image).toContain("linear-gradient");
        expect(m.boxShadow).toBe("none");
        expect(Number.isFinite(m.capPx)).toBe(true);
        // Covers the glyphs...
        expect(m.capPx).toBeGreaterThanOrEqual(m.fontPx * 0.85);
        // ...but never exceeds the heading's line box, so it cannot bleed into the row above.
        expect(m.capPx).toBeLessThanOrEqual(m.linePx + 0.5);
        // Biased downward (not centred), so it hugs the baseline-to-ascender ink and clears the
        // descenders of the row above; a revert to a centred 50% position must fail here.
        expect(m.posY).toBeGreaterThan(50);
        checked++;
      }
    }
    expect(checked).toBeGreaterThan(0);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-13: the title and Act 1 promise slides carry the refreshed copy", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    // Title (header) slide: the refreshed pitch headline replaces the old "Keep comments" line.
    const header = page.locator('[data-slide-id="slide-21860f4e"]');
    await expect(header.locator("h1")).toContainText("Plan with AI, visually rich review inline, repeat.");
    await expect(header.locator("h1")).not.toContainText("Keep");

    // Act 1 promise slide: the paragraph is rephrased and the redundant pill is gone.
    const act1 = page.locator('[data-slide-id="slide-76b2501c"]');
    await expect(act1.locator("p.showcase-comment-target")).toContainText("only the running example");
    await expect(act1.locator("p.showcase-comment-target")).not.toContainText("just the running example");
    await expect(act1).not.toContainText("reviewed end to end");
    // The Copy all control is emphasized inside its pill.
    await expect(act1.locator(".show-byline kbd")).toHaveText("Copy all");
    await expect(act1.locator(".show-pill").first()).toContainText("Copy all handoff");
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-14: the comparison table marks the Commentable HTML row's winning cells", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    const row = page.locator("table.show-compare-table tr.show-best-row");
    await expect(row).toHaveCount(1);
    await expect(row.locator("td").first()).toHaveText("Commentable HTML");
    const best = row.locator("td.show-best");
    await expect(best).toHaveCount(3);
    await expect(best.nth(0)).toContainText("Rich view");
    await expect(best.nth(1)).toContainText("Yes");
    await expect(best.nth(2)).toContainText("Copy all bundle");
    // The winning cells carry a visible check glyph via ::before.
    const marker = await best.first().evaluate((el) => getComputedStyle(el, "::before").content);
    expect(marker).toContain("\u2713");
    // ...and a distinct GREEN fill (green channel dominant, not the default transparent cell).
    const bg = await best.first().evaluate((el) => getComputedStyle(el).backgroundColor);
    const rgb = (bg.match(/\d+(\.\d+)?/g) || []).map(Number);
    expect(bg).not.toBe("rgba(0, 0, 0, 0)");
    expect(rgb[1]).toBeGreaterThan(rgb[0]);
    expect(rgb[1]).toBeGreaterThan(rgb[2]);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-15: the title slide embeds a real UI screenshot of a document and the Add Comment popup", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    const shot = page.locator('[data-slide-id="slide-21860f4e"] figure.show-ui-shot img.show-ui-shot-img');
    await expect(shot).toHaveCount(1);
    await expect(shot).toHaveAttribute("src", /^data:image\/png;base64,/);
    await expect(shot).toHaveAttribute("alt", /Add Comment/i);
    // The embedded PNG decodes to a real, non-trivial raster image.
    const dims = await shot.evaluate((img) => new Promise((res) => {
      if (img.complete && img.naturalWidth) return res({ w: img.naturalWidth, h: img.naturalHeight });
      img.addEventListener("load", () => res({ w: img.naturalWidth, h: img.naturalHeight }), { once: true });
      img.addEventListener("error", () => res({ w: 0, h: 0 }), { once: true });
    }));
    expect(dims.w).toBeGreaterThan(600);
    expect(dims.h).toBeGreaterThan(200);
    // The restructured header slide (text + screenshot) must not overflow the fixed 1080px stage.
    const overflow = await page.evaluate(() => {
      const s = document.querySelector('[data-slide-id="slide-21860f4e"]');
      return { scroll: s.scrollHeight, client: s.clientHeight };
    });
    expect(overflow.scroll).toBeLessThanOrEqual(overflow.client + 2);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-16: showcase byline pills lift on hover", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    const pill = page.locator(".slide.active .show-pill").first();
    await expect(pill).toBeVisible();
    const transition = await pill.evaluate((el) => getComputedStyle(el).transitionProperty);
    expect(transition).toContain("transform");
    expect(await pill.evaluate((el) => getComputedStyle(el).transform)).toBe("none");
    await pill.hover();
    await expect(pill).not.toHaveCSS("transform", "none");
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-19: link pills stay rounded on hover in comment mode, the primary pill label stays legible, and slide-9 feature cards lift on hover", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await enterCommentMode(page);
    // Navigate to the slide carrying the primary "View Live Demo" pill (slide 9).
    await showSlideWith(page, ".show-link-pill-primary");
    const pill = page.locator(".slide.active .show-link-pill-primary").first();
    await expect(pill).toBeVisible();

    // The runtime makes author links commentable (cm-link-commentable) and its hover affordance
    // squares the corners to 2px; the authored deck CSS overrides that back to the 999px pill radius
    // so the dashed comment-hover outline hugs the rounded shape instead of boxing it.
    await pill.hover();
    await expect(pill).toHaveClass(/cm-link-commentable/);
    const radius = await pill.evaluate((el) => Number.parseFloat(getComputedStyle(el).borderTopLeftRadius));
    expect(radius, "the pill must stay rounded on hover, not go square").toBeGreaterThanOrEqual(100);

    // The primary "View Live Demo" label reads clearly on the crimson accent (WCAG AA for large text).
    const c = await pill.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { color: cs.color, bg: cs.backgroundColor };
    });
    const ratio = contrast(composite(parseRgb(c.color), parseRgb(c.bg)), parseRgb(c.bg));
    expect(ratio, "View Live Demo label contrast").toBeGreaterThanOrEqual(4.5);

    // The four feature cards on slide 9 lift on hover (translateY + shadow), matching the pill's lift.
    const card = page.locator(".slide.active .show-four .show-card").first();
    await expect(card).toBeVisible();
    const cardTransition = await card.evaluate((el) => getComputedStyle(el).transitionProperty);
    expect(cardTransition).toContain("transform");
    expect(cardTransition).toContain("box-shadow");
    expect(await card.evaluate((el) => getComputedStyle(el).transform)).toBe("none");
    const restShadow = await card.evaluate((el) => getComputedStyle(el).boxShadow);
    await card.hover();
    await expect(card).not.toHaveCSS("transform", "none");
    await expect(card).not.toHaveCSS("box-shadow", restShadow);

    // AC1 is deck-wide: the non-primary link pills on the install slide (slide 14) also keep their
    // rounded shape on hover, confirming the fix is not scoped to the slide-9 primary pill.
    await page.evaluate(() => window.__cmhDeck.showSlideById("slide-12668385"));
    const ghPill = page.locator('.slide.active a.show-link-pill[href="https://github.com/urikanonov/ai-marketplace"]');
    await expect(ghPill).toBeVisible();
    await ghPill.hover();
    await expect(ghPill).toHaveClass(/cm-link-commentable/);
    expect(await ghPill.evaluate((el) => Number.parseFloat(getComputedStyle(el).borderTopLeftRadius))).toBeGreaterThanOrEqual(100);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-17: the shareability-modes slide tags parts with colorful source pills", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, ".show-mode-table");
    const slide = page.locator(".slide.active");
    const pills = slide.locator("td .show-src");
    // Exactly 11 source pills: 3 modes x 3 part-columns = 9 cells, and the Shareable + Offline
    // "Comments" cells each carry a 2-pill "seed + storage" pair (+2). Asserting the exact total
    // (not just >= 9) makes dropping a storage pill from those cells fail the test.
    await expect(pills.first()).toBeVisible();
    await expect(pills).toHaveCount(11);
    // The Shareable and Offline "Comments" cells each show BOTH the seed and the storage pill, so the
    // "seeded from HTML, then browser storage" handoff is not misrepresented as seed-only.
    const dualCells = slide.locator("tbody tr").filter({ hasText: /Shareable|Offline/ }).locator("td:last-child");
    await expect(dualCells.nth(0).locator(".show-src")).toHaveCount(2);
    await expect(dualCells.nth(1).locator(".show-src")).toHaveCount(2);
    await expect(dualCells.nth(0)).toContainText("seeded from HTML");
    await expect(dualCells.nth(0)).toContainText("browser storage");
    // All five source variants appear across the table.
    for (const variant of ["folder", "cdn", "inline", "storage", "seed"]) {
      await expect(slide.locator(".show-src.show-src-" + variant).first()).toBeVisible();
    }
    // A pill is a rounded chip with a distinct (non-transparent) fill and a colored leading dot.
    const styled = await slide.locator(".show-src.show-src-cdn").first().evaluate((el) => ({
      radius: getComputedStyle(el).borderTopLeftRadius,
      bg: getComputedStyle(el).backgroundColor,
      dot: getComputedStyle(el, "::before").backgroundColor,
    }));
    expect(Number.parseFloat(styled.radius)).toBeGreaterThanOrEqual(20);
    expect(styled.bg).not.toBe("rgba(0, 0, 0, 0)");
    expect(styled.dot).not.toBe("rgba(0, 0, 0, 0)");
    // Distinct variants use distinct fills (not one flat color).
    const cdnBg = await slide.locator(".show-src.show-src-cdn").first().evaluate((el) => getComputedStyle(el).backgroundColor);
    const inlineBg = await slide.locator(".show-src.show-src-inline").first().evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(cdnBg).not.toBe(inlineBg);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-41: the loop slide's diagram fills the stage instead of a thin clipped band", async ({ page }) => {
  const server = await openShowcaseDeck(page, { mermaid: true });
  try {
    // The "Act 1 - The loop" slide.
    const slideId = "slide-efe04d9f";
    await page.evaluate((id) => window.__cmhDeck.showSlideById(id), slideId);
    await settle(page);
    await expect
      .poll(() => page.locator(`[data-slide-id="${slideId}"] pre.mermaid svg g.node`).count())
      .toBeGreaterThanOrEqual(5);
    const m = await page.evaluate((id) => {
      const slide = document.querySelector(`[data-slide-id="${id}"]`);
      const stage = document.querySelector(".deck-stage");
      const scale = stage.getBoundingClientRect().width / 1920;
      const svg = slide.querySelector("pre.mermaid svg");
      const sb = svg.getBoundingClientRect();
      const slb = slide.getBoundingClientRect();
      return {
        svgH: sb.height / scale,
        aspect: sb.width / sb.height,
        rightGap: (slb.right - sb.right) / scale,
      };
    }, slideId);
    // Fills the vertical space rather than a ~80px horizontal band.
    expect(m.svgH).toBeGreaterThan(360);
    // Not an extreme wide-thin ribbon (the old flowchart LR was ~15:1).
    expect(m.aspect).toBeLessThan(3);
    // The diagram stays clear of the slide's right edge, so no node is clipped or overlapped by
    // the top-right comment affordance.
    expect(m.rightGap).toBeGreaterThan(40);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-42: content-slide titles and subtitles share a stable header baseline", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    // Slides stay laid out even when inactive (visibility, not display, toggles), so every
    // content slide's header can be measured in one pass. Section/divider slides center on
    // purpose and are excluded.
    const rows = await page.evaluate(() => {
      const stage = document.querySelector(".deck-stage");
      const rect = stage.getBoundingClientRect();
      const scale = rect.width / 1920;
      const top = rect.top;
      const out = [];
      const slides = Array.from(document.querySelectorAll(".slide")).filter(
        (s) => !s.matches(".show-header, .show-title, .show-close, .show-question"),
      );
      for (const s of slides) {
        const h2 = s.querySelector(":scope > h2");
        if (!h2) continue;
        const b = h2.getBoundingClientRect();
        // A subtitle placed immediately under the title (the deck's lead/lede), if present.
        const sub = h2.nextElementSibling;
        const isSub = sub && sub.matches(".show-lead, .cmh-slide-lede");
        out.push({
          id: s.dataset.slideId,
          h2Top: Math.round((b.top - top) / scale),
          h2Bottom: Math.round((b.bottom - top) / scale),
          subTop: isSub ? Math.round((sub.getBoundingClientRect().top - top) / scale) : null,
        });
      }
      return out;
    });
    expect(rows.length).toBeGreaterThanOrEqual(10);
    // Assumes every content-slide title fits within the reserved two-line band (<= 2.8em); a 3-line
    // title would push its h2 bottom below the others and (correctly) fail the tolerance below.
    const tops = rows.map((r) => r.h2Top);
    const bottoms = rows.map((r) => r.h2Bottom);
    // The title starts at the same height on every content slide (the header does not jump).
    expect(Math.max(...tops) - Math.min(...tops)).toBeLessThanOrEqual(8);
    // The title reserves a uniform band, so whatever follows it (a subtitle/lead or the body)
    // starts at the same height regardless of how many lines the title wraps to.
    expect(Math.max(...bottoms) - Math.min(...bottoms)).toBeLessThanOrEqual(8);
    // The RENDERED subtitle top (not just the h2 box) is stable too: a subtitle placed directly
    // under the title takes its top from the title's margin-bottom, not its own margin, so every
    // content slide that has one puts it at the same height.
    const subTops = rows.map((r) => r.subTop).filter((v) => v != null);
    expect(subTops.length).toBeGreaterThanOrEqual(2);
    expect(Math.max(...subTops) - Math.min(...subTops)).toBeLessThanOrEqual(8);
  } finally {
    await server.close();
  }
});

// CMH-DECK-04 / CMH-BUILD-22 (issue #1179): the deck gate used to treat the legacy `lowsrc`
// attribute as a fetch on ANY element, with a comment asserting it "still loads", while the strict
// layer gate carried no `lowsrc` rule at all and the offline export stripped none - so the three
// media load-attribute lists disagreed and nothing said which belief was current. This MEASURES it
// rather than replacing one unmeasured claim with another. Two boundaries make the negative
// assertion mean something: the `lowsrc` image is FIRST in the document, so a parse-time fetch
// would be requested before either control's, and the page is then settled to network-idle, so a
// fetch DEFERRED past the controls is caught too (every request is aborted, so idle arrives at
// once and the test reaches no network). The controls are asserted as "at least two" rather than
// exactly two, since a duplicate request must not turn a real result into a timeout. If a future
// engine ever revives `lowsrc` this goes red, which is the signal to move ALL THREE lists together
// rather than any one of them.
test("a legacy lowsrc is not a load, so no egress gate needs a rule for it (CMH-DECK-04)", async ({ page }) => {
  const requested = [];
  await page.route(/^https?:\/\//, async (route) => {
    requested.push(route.request().url());
    await route.abort();
  });
  await page.setContent(
    '<img lowsrc="https://cmh.invalid/lowsrc-probe.png" alt="lowsrc probe">'
    + '<img src="https://cmh.invalid/control-src.png" alt="src control">'
    + '<table><tr><td background="https://cmh.invalid/control-background.png">cell</td></tr></table>'
  );
  await expect
    .poll(() => requested.filter((url) => /control-/.test(url)).length, { timeout: 10000 })
    .toBeGreaterThanOrEqual(2);
  await page.waitForLoadState("networkidle");
  expect(requested.filter((url) => /lowsrc-probe/.test(url))).toEqual([]);
});



// CMH-VAL-08 / CMH-OFFLINE-04 / CMH-BUILD-22 (issue #1186): an SVG PRESENTATION ATTRIBUTE whose
// value is a `url(...)` reference fetches on open, and no egress surface read it - the CSS reads
// take a `style=` attribute and a `<style>` body, and the element rules are keyed on attributes
// whose WHOLE value is a URL. WHICH attributes carry the channel is decided HERE, by measurement,
// rather than from the list of properties the specs say accept a `<url>`: this test is what the
// gate's `SVG_URL_PRESENTATION_ATTRS` / `SVG_IMAGE_SET_PRESENTATION_ATTRS` and the offline export's
// strip list are derived from, and it reads those lists back so a widening on either side has to be
// measured first.
//
// It sits beside the `lowsrc` measurement above because it answers the same question for the same
// three-list contract, and it is built the same way: every request is routed and aborted (so the
// test reaches no network and idle arrives at once), the NEGATIVE probes are FIRST in the document
// so a parse-time fetch would be requested before either control's, and the page is settled to
// network-idle so a fetch deferred past the controls is caught too.
//
// The probe SHAPE is per attribute, not one shape for all, because a shape a browser rejects
// measures nothing: `cursor` needs a fallback keyword (`url(...), auto`) to be a valid declaration
// at all, and a bare-url probe made it look INERT when a valid one is requested and
// `getComputedStyle` shows the value honoured (round-1 panel, and the reason `cursor` is in the
// enforced list). Each probe below is therefore written the way the property is actually used, and
// the positives double as the evidence that the shape works.
const PRESENTATION_PROBES = {
  "clip-path": (u) => `<rect width="20" height="20" clip-path="url(${u}.svg#c)"/>`,
  "mask": (u) => `<rect width="20" height="20" mask="url(${u}.svg#m)"/>`,
  "fill": (u) => `<rect width="20" height="20" fill="url(${u}.svg#g)"/>`,
  "stroke": (u) => `<rect width="20" height="20" stroke="url(${u}.svg#g)"/>`,
  "marker-start": (u) => `<path d="M0 0 L10 10 L20 20" stroke="black" marker-start="url(${u}.svg#m)"/>`,
  "marker-mid": (u) => `<path d="M0 0 L10 10 L20 20" stroke="black" marker-mid="url(${u}.svg#m)"/>`,
  "marker-end": (u) => `<path d="M0 0 L10 10 L20 20" stroke="black" marker-end="url(${u}.svg#m)"/>`,
  // A cursor image needs the fallback keyword to be a valid declaration.
  "cursor": (u) => `<rect width="20" height="20" cursor="url(${u}.cur), auto"/>`,
  // The measured negatives. `filter` is a real presentation attribute Chromium honours but whose
  // EXTERNAL references it removed, so this negative can change with an engine and is the tripwire
  // the enforced list carries `filter` for anyway. The rest are not presentation attributes in this
  // engine at all, so their silence is structural rather than a behavioural tripwire - they are
  // asserted so that "the gate must not grow an attribute rule for them" stays a tested statement.
  "filter": (u) => `<rect width="20" height="20" filter="url(${u}.svg#f)"/>`,
  "mask-image": (u) => `<rect width="20" height="20" mask-image="url(${u}.png)"/>`,
  "mask-border-source": (u) => `<rect width="20" height="20" mask-border-source="url(${u}.png)"/>`,
  "marker": (u) => `<path d="M0 0 L10 10 L20 20" stroke="black" marker="url(${u}.svg#m)"/>`,
  "color-profile": (u) => `<image width="20" height="20" color-profile="url(${u}.icc)" href="data:image/gif;base64,R0lGODlhAQABAAAAACw="/>`,
};
const PRESENTATION_FETCHES = ["clip-path", "mask", "fill", "stroke", "marker-start", "marker-mid",
                              "marker-end", "cursor"];
const PRESENTATION_INERT = ["filter", "mask-image", "mask-border-source", "marker", "color-profile"];
// Carried by the gate and the strip DESPITE measuring inert here, with the reason recorded beside
// the list in checks/resources.py.
const PRESENTATION_CARRIED_ANYWAY = ["filter"];
// `image-set(...)` takes a BARE remote string with no `url()` wrapper, so the shared `url()` pattern
// cannot see it. Only an attribute that takes an IMAGE fetches one, which is why the gate's
// image-set reading is narrower than its url() reading - reading it on a paint or a shape reference
// would REJECT a document that fetches nothing. The shape is per attribute here for the same reason
// it is above: `cursor` needs its fallback keyword, and probing it without one measured the leak
// away (round-2 panel, 4 of 8 ducks). EVERY enforced attribute is answered in one direction or the
// other, so the list cannot grow a member the measurement says nothing about.
const IMAGE_SET_PROBES = {
  "mask": (u) => `<rect width="20" height="20" mask="image-set(&quot;${u}&quot; 1x)"/>`,
  "cursor": (u) => `<rect width="20" height="20" cursor="image-set(&quot;${u}&quot; 1x), auto"/>`,
  "fill": (u) => `<rect width="20" height="20" fill="image-set(&quot;${u}&quot; 1x)"/>`,
  "stroke": (u) => `<rect width="20" height="20" stroke="image-set(&quot;${u}&quot; 1x)"/>`,
  "clip-path": (u) => `<rect width="20" height="20" clip-path="image-set(&quot;${u}&quot; 1x)"/>`,
  "filter": (u) => `<rect width="20" height="20" filter="image-set(&quot;${u}&quot; 1x)"/>`,
  "marker-start": (u) => `<path d="M0 0 L10 10 L20 20" stroke="black" marker-start="image-set(&quot;${u}&quot; 1x)"/>`,
  "marker-mid": (u) => `<path d="M0 0 L10 10 L20 20" stroke="black" marker-mid="image-set(&quot;${u}&quot; 1x)"/>`,
  "marker-end": (u) => `<path d="M0 0 L10 10 L20 20" stroke="black" marker-end="image-set(&quot;${u}&quot; 1x)"/>`,
};
const IMAGE_SET_FETCHES = ["mask", "cursor"];
const IMAGE_SET_INERT = ["fill", "stroke", "clip-path", "filter", "marker-start", "marker-mid",
                         "marker-end"];

function presentationSvg(markup) {
  return `<svg width="30" height="30">${markup}</svg>`;
}

test("which SVG presentation attributes fetch is measured, and both egress lists match (CMH-VAL-08)", async ({ page }) => {
  const requested = [];
  await page.route(/^https?:\/\//, async (route) => {
    requested.push(route.request().url());
    await route.abort();
  });
  const probe = (attr) => presentationSvg(PRESENTATION_PROBES[attr](`https://cmh.invalid/probe-${attr}`));
  const imageSetProbe = (attr) => presentationSvg(
    IMAGE_SET_PROBES[attr](`https://cmh.invalid/iset-${attr}.png`));
  await page.setContent(
    PRESENTATION_INERT.map(probe).join("")
    + IMAGE_SET_INERT.map(imageSetProbe).join("")
    + PRESENTATION_FETCHES.map(probe).join("")
    + IMAGE_SET_FETCHES.map(imageSetProbe).join("")
    + '<img src="https://cmh.invalid/control-src.png" alt="src control">'
    + '<svg width="20" height="20"><image href="https://cmh.invalid/control-href.png" width="20" height="20"/></svg>'
  );
  await expect
    .poll(() => requested.filter((url) => /control-/.test(url)).length, { timeout: 10000 })
    .toBeGreaterThanOrEqual(2);
  // A cursor image is fetched when the cursor applies, so the pointer is moved INTO each cursor
  // probe's own box rather than swept across the page - a sweep that missed the element would make
  // a cursor negative mean "the pointer never got there" instead of "this does not fetch".
  for (const el of await page.locator("body > svg").all()) {
    const box = await el.boundingBox();
    if (box) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  }
  await page.waitForLoadState("networkidle");
  const hit = (name) => requested.filter((url) => url.includes(`/${name}.`)).length > 0;
  expect(PRESENTATION_FETCHES.filter((attr) => !hit(`probe-${attr}`))).toEqual([]);
  expect(PRESENTATION_INERT.filter((attr) => hit(`probe-${attr}`))).toEqual([]);
  expect(IMAGE_SET_FETCHES.filter((attr) => !hit(`iset-${attr}`))).toEqual([]);
  expect(IMAGE_SET_INERT.filter((attr) => hit(`iset-${attr}`))).toEqual([]);
  // Both gate lists are the measured ones, plus only what is explicitly carried anyway.
  const source = fs.readFileSync(
    path.join(SKILL, "tools", "validate", "checks", "resources.py"), "utf8");
  const declared = (name) => {
    const match = source.match(new RegExp(`${name} = \\(([^)]*)\\)`));
    expect(match, `the gate no longer declares ${name}`).toBeTruthy();
    return Array.from(match[1].matchAll(/"([^"]+)"/g)).map((m) => m[1]).sort();
  };
  expect(declared("SVG_URL_PRESENTATION_ATTRS"))
    .toEqual([...PRESENTATION_FETCHES, ...PRESENTATION_CARRIED_ANYWAY].sort());
  expect(declared("SVG_IMAGE_SET_PRESENTATION_ATTRS")).toEqual([...IMAGE_SET_FETCHES].sort());
  // ... and every enforced attribute is answered by the image-set measurement in one direction or
  // the other, so the narrower list can never again exclude one nobody probed.
  expect([...IMAGE_SET_FETCHES, ...IMAGE_SET_INERT].sort())
    .toEqual(declared("SVG_URL_PRESENTATION_ATTRS"));
});