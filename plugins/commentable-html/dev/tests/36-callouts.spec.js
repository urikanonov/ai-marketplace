// Callouts and the lead paragraph must stay readable in BOTH light and dark themes.
// This guards the regression where a report hardcoded dark-theme colors on its top
// block (dark text on a dark background in light mode, washed-out lede) because the
// skill shipped no theme-aware callout utilities. See references/content-conventions.md.
import { test, expect } from "@playwright/test";
import { openInline, ready, addTextComment } from "./helpers.js";

const BOXES = [
  ".cmh-lede",
  ".cmh-callout-info",
  ".cmh-callout-success",
  ".cmh-callout-warning",
  ".cmh-callout-danger",
];

// Compute the WCAG contrast ratio between an element's text color and the real
// background rendered behind it (compositing every translucent ancestor layer).
async function contrastFor(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const parse = (c) => {
      const m = c && c.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const p = m[1].split(",").map((s) => parseFloat(s.trim()));
      return { r: p[0], g: p[1], b: p[2], a: p.length === 4 ? p[3] : 1 };
    };
    const effectiveBg = (node) => {
      const layers = [];
      for (let n = node; n && n.nodeType === 1; n = n.parentElement) {
        const c = parse(getComputedStyle(n).backgroundColor);
        if (c && c.a > 0) layers.push(c);
      }
      let base = { r: 255, g: 255, b: 255 };
      for (let i = layers.length - 1; i >= 0; i--) {
        const L = layers[i];
        base = {
          r: L.r * L.a + base.r * (1 - L.a),
          g: L.g * L.a + base.g * (1 - L.a),
          b: L.b * L.a + base.b * (1 - L.a),
        };
      }
      return base;
    };
    const lum = (c) => {
      const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
    };
    const fg = parse(getComputedStyle(el).color);
    const bg = effectiveBg(el);
    const L1 = lum(fg), L2 = lum(bg);
    return (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
  }, selector);
}

for (const theme of ["light", "dark"]) {
  test(`callouts and lede stay readable in ${theme} theme (CMH-CALLOUT-01)`, async ({ page }) => {
    await openInline(page);
    await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
    await ready(page);
    for (const sel of BOXES) {
      const ratio = await contrastFor(page, sel);
      expect(ratio, `${sel} must exist in the demo`).not.toBeNull();
      // 4.5:1 is the WCAG AA threshold for body text; the dark-on-dark bug scores ~1.2.
      expect(ratio, `${sel} text contrast in ${theme} theme`).toBeGreaterThanOrEqual(4.5);
    }
  });
}

test("every callout variant renders as a bordered box (CMH-CALLOUT-01)", async ({ page }) => {
  await openInline(page);
  for (const sel of [".cmh-callout-info", ".cmh-callout-success", ".cmh-callout-warning", ".cmh-callout-danger"]) {
    const box = await page.evaluate((s) => {
      const el = document.querySelector(s);
      if (!el) return null;
      const cs = getComputedStyle(el);
      return { border: parseFloat(cs.borderTopWidth), radius: parseFloat(cs.borderTopLeftRadius) };
    }, sel);
    expect(box, `${sel} exists`).not.toBeNull();
    expect(box.border, `${sel} has a border`).toBeGreaterThan(0);
    expect(box.radius, `${sel} is rounded`).toBeGreaterThan(0);
  }
});

test("callout prose is commentable (CMH-CALLOUT-02)", async ({ page }) => {
  await openInline(page);
  await addTextComment(page, ".cmh-callout-danger", "review this takeaway");
  expect(await page.locator("mark.cm-hl").count()).toBeGreaterThan(0);
});
