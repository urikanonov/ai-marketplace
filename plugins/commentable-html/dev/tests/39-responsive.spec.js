import { test, expect } from "@playwright/test";
import path from "path";
import { SKILL, fileUrl, ready } from "./helpers.js";

// Mobile responsiveness regression for the two shipped showcase examples. A narrow
// phone viewport must never produce a content box that spills past the viewport: wide
// tables scroll inside their own box, the KQL caption stacks, code blocks reserve
// headroom for the floating pills, and figures/images fit the column. We assert against
// the committed examples/*.html so the shipped artifacts are proven responsive.
const EXAMPLES = {
  "report-taxi.html": path.join(SKILL, "examples", "report-taxi.html"),
  "report-community-garden.html": path.join(SKILL, "examples", "report-community-garden.html"),
};
const WIDTHS = [360, 390];

// Elements that live inside a horizontal-scroll container (or are themselves scroll
// containers) are allowed to be wider than the viewport: their overflow is contained.
// UI chrome (.cm-skip) is off-canvas by design and is not author content.
function scanOverflow() {
  const vw = document.documentElement.clientWidth;
  const root = document.getElementById("commentRoot");
  function inScrollContainer(el) {
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      const ox = getComputedStyle(a).overflowX;
      if (ox === "auto" || ox === "scroll" || ox === "hidden") return true;
    }
    return false;
  }
  const bad = [];
  root.querySelectorAll("*").forEach((el) => {
    if (el.closest(".cm-skip")) return;
    if (inScrollContainer(el)) return;
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.right > vw + 1) {
      bad.push((el.tagName + "." + (el.className || "")).trim().slice(0, 60) + " right=" + Math.round(r.right));
    }
  });
  return { vw, bad };
}

for (const [name, file] of Object.entries(EXAMPLES)) {
  for (const width of WIDTHS) {
    test.describe(`${name} at ${width}px is responsive`, () => {
      test.use({ viewport: { width, height: 780 } });

      test.beforeEach(async ({ page }) => {
        await page.goto(fileUrl(file));
        await ready(page);
      });

      test("no author content box overflows the viewport", async ({ page }) => {
        const { vw, bad } = await page.evaluate(scanOverflow);
        expect(vw, "viewport is the narrow width under test").toBeLessThanOrEqual(width);
        expect(bad, "every #commentRoot content box fits the viewport").toEqual([]);
      });

      test("every table fits the viewport and scrolls internally when wide", async ({ page }) => {
        const tables = await page.evaluate(() => {
          const vw = document.documentElement.clientWidth;
          return [...document.querySelectorAll("#commentRoot table")].map((t) => ({
            fits: t.getBoundingClientRect().right <= vw + 1,
            scrollable: t.scrollWidth > t.clientWidth ? getComputedStyle(t).overflowX : "n/a",
          }));
        });
        for (const t of tables) {
          expect(t.fits, "table box stays within the viewport").toBe(true);
          if (t.scrollable !== "n/a") {
            expect(["auto", "scroll"], "an overflowing table scrolls internally").toContain(t.scrollable);
          }
        }
      });

      test("KQL captions stack the title and Run link", async ({ page }) => {
        const dirs = await page.evaluate(() =>
          [...document.querySelectorAll("#commentRoot figure.cmh-kql .cmh-kql-cap")].map(
            (c) => getComputedStyle(c).flexDirection));
        for (const d of dirs) {
          expect(d, "KQL caption is stacked at mobile width").toBe("column");
        }
      });

      test("code blocks reserve headroom so the Copy/language pills clear the text", async ({ page }) => {
        const pads = await page.evaluate(() =>
          [...document.querySelectorAll("#commentRoot .cmh-code-wrap > pre")].map(
            (p) => parseFloat(getComputedStyle(p).paddingTop)));
        for (const pt of pads) {
          expect(pt, "code block top padding leaves room for the floating pills").toBeGreaterThanOrEqual(32);
        }
      });
    });
  }
}
