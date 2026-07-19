import { test, expect } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";
import { fileUrl, ready, PYTHON, SKILL } from "./helpers.js";

// A deck authored ONLY from the public recipe classes exercised by this spec: the status-pill
// variants, the metric hover-lift + value cap, the reference row, the flex-column flow slide, and
// the default prose spacing. No per-deck CSS, so a pass proves the deck layer (90-deck.css) alone
// produces these behaviours (CMH-DECK-RECIPE-01/02/03/04).
const RECIPE_SLIDES =
  '<section class="slide cmh-slide-flow"><h2>Statuses</h2>' +
  '<p><span class="cmh-pill is-available">Available</span> ' +
  '<span class="cmh-pill is-wip">WIP</span> ' +
  '<span class="cmh-pill is-planned">Planned</span></p>' +
  '<ul><li>First bullet point</li><li>Second bullet point</li></ul>' +
  '<div class="cmh-metric-grid">' +
  '<div class="cmh-metric"><span class="cmh-metric-value">IncidentRefinementLatencyP95Milliseconds</span><span class="cmh-metric-label">a longer label here</span></div>' +
  '<div class="cmh-metric"><span class="cmh-metric-value">Alerts</span><span class="cmh-metric-label">short label here</span></div>' +
  '</div>' +
  '<p class="cmh-refs"><span class="cmh-refs-label">Ref</span> ' +
  '<a href="https://example.com/doc.md">doc.md</a> ' +
  '<a href="https://example.com/other.md">other.md</a></p></section>';

// Page-side WCAG contrast ratio between two computed rgb() strings.
const CONTRAST_FN = `(a, b) => {
  const rgb = (s) => (s.match(/\\d+(\\.\\d+)?/g) || []).slice(0, 3).map(Number);
  const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  const L = (s) => { const [r, g, bl] = rgb(s); return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(bl); };
  const l1 = L(a), l2 = L(b);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}`;

function scaffold(dir, name, slides) {
  const frag = path.join(dir, name + "-frag.html");
  fs.writeFileSync(frag, slides);
  const out = path.join(dir, name + ".html");
  const r = spawnSync(PYTHON, [path.join(SKILL, "tools", "deck", "deck_scaffold.py"),
    "--content", frag, "--label", name, "--source", out, "--out", out],
    { encoding: "utf8" });
  expect(r.status, r.stderr).toBe(0);
  return out;
}

async function computed(page, selector, prop) {
  return page.evaluate(([s, p]) => {
    const el = document.querySelector(s);
    return el ? getComputedStyle(el).getPropertyValue(p) : null;
  }, [selector, prop]);
}

let tmpDir;
let deck;

test.beforeAll(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_deck_recipes_"));
  deck = scaffold(tmpDir, "recipes-ref", RECIPE_SLIDES);
});

test.describe("deck recipe classes (CMH-DECK-RECIPE)", () => {
  test("CMH-DECK-RECIPE-01: status-pill variants recolour distinctly and keep AA text contrast", async ({ page }) => {
    await page.goto(fileUrl(deck));
    await ready(page);
    const avail = await computed(page, ".cmh-pill.is-available", "background-color");
    const wip = await computed(page, ".cmh-pill.is-wip", "background-color");
    const planned = await computed(page, ".cmh-pill.is-planned", "background-color");
    // Each variant is a distinct, non-default colour (the base pill uses the theme accent).
    expect(avail).not.toBe(wip);
    expect(wip).not.toBe(planned);
    expect(avail).not.toBe(planned);
    // Available reads green (more green than red/blue channel).
    const availRgb = (avail.match(/\d+/g) || []).map(Number);
    expect(availRgb[1]).toBeGreaterThan(availRgb[0]);
    expect(availRgb[1]).toBeGreaterThan(availRgb[2]);
    // WIP reads amber/warm (more red than blue) so it cannot be confused with the slate Planned pill.
    const wipRgb = (wip.match(/\d+/g) || []).map(Number);
    expect(wipRgb[0]).toBeGreaterThan(wipRgb[2]);
    expect(wipRgb[0]).toBeGreaterThan(availRgb[0]);
    // White pill text keeps >= 4.5:1 on every variant.
    for (const sel of [".cmh-pill.is-available", ".cmh-pill.is-wip", ".cmh-pill.is-planned"]) {
      const fg = await computed(page, sel, "color");
      const bg = await computed(page, sel, "background-color");
      const ratio = await page.evaluate(([fn, a, b]) => eval(`(${fn})`)(a, b), [CONTRAST_FN, fg, bg]);
      expect(ratio, sel).toBeGreaterThanOrEqual(4.5);
    }
  });

  test("CMH-DECK-RECIPE-02: metric tiles hover-lift and cap the value so long labels do not overflow", async ({ page }) => {
    await page.goto(fileUrl(deck));
    await ready(page);
    // Hover-lift is wired through a transform transition on the tile.
    const transition = await computed(page, ".cmh-metric", "transition-property");
    expect(transition).toContain("transform");
    // Perf: the lift must NOT animate box-shadow (per-frame repaint that made hover feel laggy);
    // box-shadow snaps while the compositor-friendly transform eases. Token-match the list.
    expect(transition.split(",").map((s) => s.trim())).not.toContain("box-shadow");
    // Hovering actually applies a lift transform (proves the :hover rule fires, not just the transition).
    const beforeHover = await computed(page, ".cmh-metric", "transform");
    expect(beforeHover).toBe("none");
    await page.hover(".cmh-metric");
    // Auto-retrying assertion (no fixed wait): the transform lands once the hover transition runs.
    await expect(page.locator(".cmh-metric").first()).not.toHaveCSS("transform", "none");
    // The metric value font is a FIXED stage size (not a vw-coupled clamp that would shrink on a
    // narrow browser inside the transform-scaled 1920x1080 stage), capped well below the legacy 64px.
    const fontSize = parseFloat(await computed(page, ".cmh-metric .cmh-metric-value", "font-size"));
    expect(fontSize).toBe(44);
    // The long-label tile does not overflow its card horizontally.
    const overflow = await page.evaluate(() => {
      const tile = document.querySelector(".cmh-metric");
      return tile ? tile.scrollWidth <= tile.clientWidth + 1 : null;
    });
    expect(overflow).toBe(true);
  });

  test("CMH-DECK-RECIPE-03: reference rows render as horizontal pills pinned to the slide bottom", async ({ page }) => {
    await page.goto(fileUrl(deck));
    await ready(page);
    // The row is a horizontal flex container...
    expect(await computed(page, ".cmh-refs", "display")).toBe("flex");
    // ...that declares margin-top: auto so it pins to the bottom of a flex-column slide.
    const declaresAutoTop = await page.evaluate(() => {
      for (const sheet of document.styleSheets) {
        let rules;
        try { rules = sheet.cssRules; } catch { continue; }
        if (!rules) continue;
        for (const r of rules) {
          if (r.selectorText && r.selectorText.includes(".cmh-refs") &&
              !r.selectorText.includes(" a") && r.style && r.style.marginTop === "auto") {
            return true;
          }
        }
      }
      return false;
    });
    expect(declaresAutoTop).toBe(true);
    // Each reference link is a pill (fully rounded).
    const radius = await computed(page, ".cmh-refs a", "border-radius");
    expect(radius).toBe("999px");
    // Perf: the reference-pill hover lift does not animate box-shadow.
    expect((await computed(page, ".cmh-refs a", "transition-property")).split(",").map((s) => s.trim()))
      .not.toContain("box-shadow");
    // Two links sit side by side on one row (same top offset).
    const sameRow = await page.evaluate(() => {
      const links = document.querySelectorAll(".cmh-refs a");
      if (links.length < 2) return false;
      return Math.abs(links[0].getBoundingClientRect().top - links[1].getBoundingClientRect().top) < 2;
    });
    expect(sameRow).toBe(true);
    // Behavioural proof of the pin: on the flex-column slide the reference row is actually pushed
    // into the bottom region of the fixed slide box (margin-top:auto wins), not left just under the
    // preceding content. The slide holds little content, so without the auto margin the row would sit
    // in the top half; with it, the row's top is well past the slide's vertical midpoint.
    const pinnedLow = await page.evaluate(() => {
      const slide = document.querySelector(".slide.cmh-slide-flow");
      const refs = document.querySelector(".cmh-refs");
      if (!slide || !refs) return null;
      const s = slide.getBoundingClientRect();
      const r = refs.getBoundingClientRect();
      // Fraction of the slide height at which the reference row begins.
      return (r.top - s.top) / s.height;
    });
    expect(pinnedLow).toBeGreaterThan(0.5);
  });

  test("CMH-DECK-RECIPE-04: deck prose gets generous default spacing without per-deck CSS", async ({ page }) => {
    await page.goto(fileUrl(deck));
    await ready(page);
    // Paragraphs collapse their top margin (the recipe sets `margin: 0 0 0.75em`), unlike the UA
    // default that adds a top margin - proof the deck prose rule is applied, not the browser default.
    const pTop = await computed(page, ".slide p", "margin-top");
    expect(parseFloat(pTop)).toBe(0);
    const pBottom = parseFloat(await computed(page, ".slide p", "margin-bottom"));
    expect(pBottom).toBeGreaterThan(0);
    // List items gain bottom spacing (the UA default is 0), so bullets breathe without per-deck CSS.
    const liBottom = parseFloat(await computed(page, ".slide li", "margin-bottom"));
    expect(liBottom).toBeGreaterThan(0);
  });
});
