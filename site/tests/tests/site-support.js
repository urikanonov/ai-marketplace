const { test, expect } = require("@playwright/test");

function contrastRatio(foreground, background) {
  const channel = (value) => {
    const normalized = value / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : Math.pow((normalized + 0.055) / 1.055, 2.4);
  };
  const luminance = (color) => {
    const r = channel(color.r);
    const g = channel(color.g);
    const b = channel(color.b);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

async function compositedContrast(page, selector) {
  return page.locator(selector).first().evaluate((el) => {
    const parseColor = (value) => {
      const raw = (value || "").trim().toLowerCase();
      if (!raw || raw === "transparent") return { r: 0, g: 0, b: 0, a: 0 };
      const hex = raw.match(/^#([0-9a-f]{6})$/i);
      if (hex) {
        return {
          r: parseInt(hex[1].slice(0, 2), 16),
          g: parseInt(hex[1].slice(2, 4), 16),
          b: parseInt(hex[1].slice(4, 6), 16),
          a: 1,
        };
      }
      const rgb = raw.match(/^rgba?\((.*)\)$/);
      if (rgb) {
        const parts = rgb[1].replace(/\//g, " ").split(/[,\s]+/).filter(Boolean);
        const channel = (part) => part.endsWith("%") ? Number(part.slice(0, -1)) * 2.55 : Number(part);
        return {
          r: channel(parts[0]),
          g: channel(parts[1]),
          b: channel(parts[2]),
          a: parts[3] === undefined ? 1 : Number(parts[3]),
        };
      }
      const srgb = raw.match(/^color\(srgb\s+(.+)\)$/);
      if (srgb) {
        const parts = srgb[1].replace(/\//g, " ").split(/\s+/).filter(Boolean);
        return {
          r: Number(parts[0]) * 255,
          g: Number(parts[1]) * 255,
          b: Number(parts[2]) * 255,
          a: parts[3] === undefined ? 1 : Number(parts[3]),
        };
      }
      throw new Error("unsupported color format: " + value);
    };
    const blend = (top, bottom) => {
      const alpha = top.a + bottom.a * (1 - top.a);
      if (alpha === 0) return { r: 0, g: 0, b: 0, a: 0 };
      return {
        r: (top.r * top.a + bottom.r * bottom.a * (1 - top.a)) / alpha,
        g: (top.g * top.a + bottom.g * bottom.a * (1 - top.a)) / alpha,
        b: (top.b * top.a + bottom.b * bottom.a * (1 - top.a)) / alpha,
        a: alpha,
      };
    };
    let background = { r: 0, g: 0, b: 0, a: 0 };
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE) {
      background = blend(background, parseColor(getComputedStyle(node).backgroundColor));
      if (background.a >= 0.999) break;
      node = node.parentElement;
    }
    if (background.a < 0.999) {
      background = blend(background, { r: 255, g: 255, b: 255, a: 1 });
    }
    return {
      foreground: parseColor(getComputedStyle(el).color),
      background: background,
    };
  });
}

// Keep the suite hermetic and deterministic: block every request that is not our
// local static server so a flaky GitHub API, the star-widget CDN, or the mermaid
// CDN can never fail the deploy gate. We validate the built static output only.
test.beforeEach(async ({ context }) => {
  await context.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.protocol === "data:" || url.hostname === "127.0.0.1" || url.hostname === "localhost") {
      return route.continue();
    }
    return route.abort();
  });
});


const PROD = "https://urikanonov.github.io/ai-marketplace/";

module.exports = { test, expect, contrastRatio, compositedContrast, PROD };
