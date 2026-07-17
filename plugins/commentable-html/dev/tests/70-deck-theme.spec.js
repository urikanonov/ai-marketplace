import { test, expect } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";
import { fileUrl, ready, addTextComment, installClipboardCapture, enterCommentMode, PYTHON, SKILL } from "./helpers.js";

// A reference deck authored ONLY from public recipe classes and standard content - no per-deck CSS,
// no inline style attributes - so a passing render proves the theme + recipe layer alone produce a
// coherent, themed deck (CMH-DECK-THEME-01/03). Slide text is commentable for the anchor regression.
const RECIPE_SLIDES =
  '<section class="slide cmh-slide-section"><p class="cmh-slide-kicker">Overview</p>' +
  '<h2>Terminal reference deck</h2>' +
  '<p class="cmh-slide-lede">Built only from native recipes and the terminal theme.</p>' +
  '<span class="cmh-pill">shipped</span></section>' +
  '<section class="slide"><h2>Metrics</h2><div class="cmh-metric-grid">' +
  '<div class="cmh-metric"><span class="cmh-metric-value">99.9%</span><span class="cmh-metric-label">uptime here</span></div>' +
  '<div class="cmh-metric"><span class="cmh-metric-value">12ms</span><span class="cmh-metric-label">median latency</span></div>' +
  '</div></section>' +
  '<section class="slide"><h2>Code and data</h2><div class="cmh-cols-2">' +
  '<div><pre><code class="language-python">def greet(name):\n    return f"hi {name}"</code></pre></div>' +
  '<div><table><thead><tr><th>Metric</th><th>Value</th></tr></thead>' +
  '<tbody><tr><td>Rows</td><td>forty two here</td></tr></tbody></table></div></div></section>';

// Page-side WCAG contrast ratio between two computed rgb() strings.
const CONTRAST_FN = `(a, b) => {
  const rgb = (s) => (s.match(/\\d+(\\.\\d+)?/g) || []).slice(0, 3).map(Number);
  const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  const L = (s) => { const [r, g, bl] = rgb(s); return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(bl); };
  const l1 = L(a), l2 = L(b);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}`;

function scaffold(dir, name, slides, extraArgs) {
  const frag = path.join(dir, name + "-frag.html");
  fs.writeFileSync(frag, slides);
  const out = path.join(dir, name + ".html");
  const r = spawnSync(PYTHON, [path.join(SKILL, "tools", "deck", "deck_scaffold.py"),
    "--content", frag, "--label", name, "--source", out, "--out", out, ...(extraArgs || [])],
    { encoding: "utf8" });
  expect(r.status, r.stderr).toBe(0);
  return out;
}

let tmpDir;
let themedDeck;

test.beforeAll(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_deck_theme_"));
  themedDeck = scaffold(tmpDir, "terminal-ref", RECIPE_SLIDES, ["--theme", "terminal"]);
});

async function computed(page, selector, prop) {
  return page.evaluate(([s, p]) => {
    const el = document.querySelector(s);
    return el ? getComputedStyle(el).getPropertyValue(p) : null;
  }, [selector, prop]);
}

test.describe("deck theme presets (CMH-DECK-THEME)", () => {
  test("CMH-DECK-THEME-01: the terminal theme recolours the stage, slides, code, and tables", async ({ page }) => {
    await installClipboardCapture(page);
    await page.goto(fileUrl(themedDeck));
    await ready(page);
    // The authored fragment carries no per-deck CSS: no inline style attributes on the slides.
    expect(await page.locator(".slide[style]").count()).toBe(0);
    // Theme block is present and cm-skip (anchor-neutral).
    expect(await page.locator('style#cmh-deck-theme.cm-skip').count()).toBe(1);
    // Terminal tokens are actually applied (computed colors), not just declared.
    expect(await computed(page, ".slide.active", "background-color")).toBe("rgb(13, 17, 23)"); // --slide-bg
    expect(await computed(page, ".slide pre", "background-color")).toBe("rgb(1, 4, 9)"); // code bg
    expect(await computed(page, ".slide table thead th", "background-color")).toBe("rgb(22, 27, 34)");
    // Recipe accent is theme-driven (terminal green on the section kicker and the pill).
    expect(await computed(page, ".cmh-slide-kicker", "color")).toBe("rgb(57, 211, 83)");
    expect(await computed(page, ".cmh-pill", "background-color")).toBe("rgb(57, 211, 83)");
    expect(await computed(page, ".cmh-pill", "color")).toBe("rgb(1, 4, 9)"); // accent-fg
  });

  test("CMH-DECK-THEME-03: themed surfaces keep AA contrast in closed and open mode", async ({ page }) => {
    await installClipboardCapture(page);
    await page.goto(fileUrl(themedDeck));
    await ready(page);
    const checkAll = async (label) => {
      const pairs = await page.evaluate(() => {
        const g = (s, p) => { const e = document.querySelector(s); return e ? getComputedStyle(e).getPropertyValue(p) : null; };
        return [
          [g(".slide.active h2", "color"), g(".slide.active", "background-color")],
          [g(".slide pre code", "color"), g(".slide pre", "background-color")],
          [g(".slide table thead th", "color"), g(".slide table thead th", "background-color")],
          [g(".cmh-metric-value", "color"), g(".slide.active", "background-color")],
          [g(".cmh-slide-kicker", "color"), g(".slide.active", "background-color")],
          [g(".cmh-pill", "color"), g(".cmh-pill", "background-color")],
        ];
      });
      const ratio = await page.evaluate(([fn, ps]) => {
        const f = eval("(" + fn + ")");
        return ps.map(([a, b]) => (a && b ? f(a, b) : 0)); // missing element -> 0 -> hard fail
      }, [CONTRAST_FN, pairs]);
      for (const [a, b] of pairs) { expect(a, label + " fg present").toBeTruthy(); expect(b, label + " bg present").toBeTruthy(); }
      for (const r of ratio) expect(r, label + " pair ratio " + r).toBeGreaterThanOrEqual(4.5);
    };
    await checkAll("present");
    // Open the review panel and re-check (theme is mode-independent, but the stage insets).
    await enterCommentMode(page);
    await checkAll("comment");
  });

  test("CMH-DECK-THEME-02: re-theming a commented deck keeps every anchor on its original text and slide", async ({ page }) => {
    await installClipboardCapture(page);
    await page.goto(fileUrl(themedDeck));
    await ready(page);
    // Comment on slide-3 text (navigate there first so it is the active slide).
    await page.evaluate(() => window.__cmhDeck.showSlide(2));
    // Open the review panel before authoring so the saved card is immediately reviewable.
    await enterCommentMode(page);
    await addTextComment(page, ".slide.active td", "check this cell");
    const before = await page.evaluate(() => {
      const m = document.querySelector("mark.cm-hl");
      return m ? { text: m.textContent, slide: m.closest(".slide").dataset.slideId } : null;
    });
    expect(before).not.toBeNull();
    expect(before.text.trim().length).toBeGreaterThan(0);

    // Re-theme the file on disk to a DIFFERENT-length preset, then reload the same URL.
    const small = path.join(tmpDir, "small.theme.json");
    fs.writeFileSync(small, JSON.stringify({ label: "small", tokens: { "--slide-bg": "#101010", "--slide-fg": "#fafafa" } }));
    const r = spawnSync(PYTHON, [path.join(SKILL, "tools", "deck", "deck_theme.py"),
      "apply", themedDeck, "--theme", small], { encoding: "utf8" });
    expect(r.status, r.stderr).toBe(0);

    await page.goto(fileUrl(themedDeck));
    await ready(page);
    const after = await page.evaluate(() => {
      const m = document.querySelector("mark.cm-hl");
      return m ? { text: m.textContent, slide: m.closest(".slide").dataset.slideId } : null;
    });
    expect(after, "the comment highlight restored after re-theme").not.toBeNull();
    // The anchor lands on the SAME text and SAME slide - proof the re-theme did not shift offsets.
    expect(after.text).toBe(before.text);
    expect(after.slide).toBe(before.slide);
  });

  test("CMH-DECK-THEME-03: an unthemed deck keeps its original component colors (fallback golden)", async ({ page }) => {
    const plain = scaffold(tmpDir, "plain-ref", RECIPE_SLIDES);
    await installClipboardCapture(page);
    await page.goto(fileUrl(plain));
    await ready(page);
    expect(await page.locator('style#cmh-deck-theme').count()).toBe(0);
    // The var(--token, default) rewrite must be byte-exact: an unthemed code block keeps #0f172a.
    expect(await computed(page, ".slide pre", "background-color")).toBe("rgb(15, 23, 42)");
    expect(await computed(page, ".slide table thead th", "background-color")).toBe("rgba(15, 23, 42, 0.92)");
  });
});
