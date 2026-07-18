import { test, expect } from "@playwright/test";
import path from "path";
import {
  SKILL,
  copiedBundle,
  installClipboardCapture,
  ready,
  routeMermaidLocal,
  startStaticServer,
  openDeckModeMenu,
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
    await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable");
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

test("CMH-DECK-21: showcase deck table cells gain a hover highlight without losing contrast", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, ".showcase-chart-slide");
    await enterCommentMode(page);
    const cell = page.locator(".slide.active table.show-table tbody tr").nth(1).locator("td").nth(2);
    const before = await cell.evaluate((el) => {
      const style = getComputedStyle(el);
      return {
        background: style.backgroundColor,
        boxShadow: style.boxShadow,
      };
    });
    await cell.hover();
    await expect.poll(() => cell.evaluate((el) => getComputedStyle(el).boxShadow)).not.toBe(before.boxShadow);
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
    await showSlideWith(page, ".showcase-checklist-slide");
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

test("CMH-DECK-SHOWCASE-06: Act 4 slides explain the deterministic build, portability, and test model", async ({ page }) => {
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

    await showSlideWith(page, "text=Three portability modes explain every handoff.");
    const portability = page.locator(".slide.active");
    await expect(portability).toContainText("Non-portable");
    await expect(portability).toContainText("Portable");
    await expect(portability).toContainText("Offline");
    await expect(portability).toContainText("Styles + runtime");
    await expect(portability).toContainText("skill folder");
    await expect(portability).toContainText("CDN");
    await expect(portability).toContainText("vendored runtimes");
    await expect(portability).toContainText("browser storage");
    await expect(portability).toContainText("seeded from HTML");

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

test("CMH-DECK-20: slide 16 cross-card comments do not highlight the grid gap", async ({ page }) => {
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

test("CMH-DECK-21: deck chrome exposes the project link and distinct overview/count pills", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    const menu = await openDeckModeMenu(page);
    const site = menu.locator(".cmh-deck-mode-site");
    await expect(site).toHaveAttribute("href", "https://urikanonov.github.io/ai-marketplace/commentable-html/");
    await expect(site).toHaveAttribute("target", "_blank");
    await expect(site).toHaveText("Commentable HTML site");
    await expect(page.locator(".cmh-deck-brand-link")).toHaveCount(0);

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

test("CMH-BOARD-06: the showcase Locked column Add Comment affordance avoids Reset moves", async ({ page }) => {
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

test("CMH-DECK-SHOWCASE-08: the showcase deck includes supported languages and a notes demo slide", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, ".show-note-field");
    const slide = page.locator(".slide.active");
    await expect(slide.locator(".show-supported-pills .show-pill")).toHaveCount(11);
    await expect(slide.locator(".show-supported-panel")).toContainText("Python");
    await expect(slide.locator(".show-supported-panel")).toContainText("TypeScript");
    await expect(slide.locator(".show-supported-panel")).toContainText("PowerShell");
    await expect(slide.locator(".show-supported-panel")).toContainText("+37 more");
    await expect(slide.locator(".show-note-field")).toHaveCount(2);
    await expect(slide.locator(".show-note-field").first()).toContainText("Reviewer summary");
    await expect(slide.locator(".show-note-field").nth(1)).toContainText("Meeting follow-up");
    await expect(slide.locator(".show-note-toggle")).toHaveCount(2);
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
    await expect(pointAt).toContainText('Example: the "Paste the Copy all bundle" node.');
    await expect(pointAt).not.toContainText("Copy all Markdown bundle");
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-12: showcase slides vertically center their content", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, ".show-card-example");
    const metrics = await page.locator(".slide.active").evaluate((slide) => {
      const rect = slide.getBoundingClientRect();
      const content = slide.querySelector(".show-card-example").getBoundingClientRect();
      const style = getComputedStyle(slide);
      return {
        display: style.display,
        flexDirection: style.flexDirection,
        justifyContent: style.justifyContent,
        stageCenterY: rect.top + rect.height / 2,
        contentCenterY: content.top + content.height / 2,
        stageHeight: rect.height,
      };
    });
    expect(metrics.display).toBe("flex");
    expect(metrics.flexDirection).toBe("column");
    expect(metrics.justifyContent).toBe("center");
    expect(Math.abs(metrics.contentCenterY - metrics.stageCenterY)).toBeLessThan(metrics.stageHeight * 0.2);
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
    await expect(logo.locator("svg")).toHaveCount(1);
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
    expect(pos.rightGap).toBeLessThan(pos.slideWidth * 0.08);
    expect(pos.topGap).toBeGreaterThanOrEqual(0);
    expect(pos.topGap).toBeLessThan(pos.slideHeight * 0.12);
  } finally {
    await server.close();
  }
});

test("CMH-DECK-SHOWCASE-11: showcase amber title highlights do not paint a halo above the line", async ({ page }) => {
  const server = await openShowcaseDeck(page);
  try {
    await showSlideWith(page, ".show-mark");
    await expect(page.locator(".slide.active .show-mark").first()).toBeVisible();
    await expect(page.locator(".slide.active .show-mark").first()).toHaveCSS("box-shadow", "none");
  } finally {
    await server.close();
  }
});
