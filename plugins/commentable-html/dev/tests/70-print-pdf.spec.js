import { test, expect } from "@playwright/test";
import fs from "fs";
import os from "os";
import path from "path";
import { PDFParse } from "pdf-parse";
import { PNG } from "pngjs";
import { DEV, EXAMPLES, fileUrl, ready } from "./helpers.js";

// Real rendered-PDF checks: these drive the browser's native print (page.pdf, the same path a
// user's "Save as PDF" / Ctrl+P takes) and inspect the produced PDF - page count, page geometry,
// and per-page ink coverage - so a print-layout regression (a clipped deck slide, an oversized
// diagram, a grid that strands its heading on a near-blank page) fails CI. The @media print
// computed-style checks in 68-print.spec.js cannot see any of that because they never paginate.

// Route the CDN mermaid/Chart.js loaders to the vendored copies and abort every other external
// request, so diagrams and charts render for the coverage checks without touching the network.
async function routeRichContentLocal(page) {
  const mermaidRoot = path.join(DEV, "node_modules", "mermaid");
  const chartRoot = path.join(DEV, "node_modules", "chart.js");
  await page.route(/^https?:\/\//, async (route) => {
    const url = route.request().url();
    if (/^https?:\/\/(localhost|127\.0\.0\.1)(:|\/)/.test(url)) return route.fallback();
    const u = new URL(url);
    if (/cdn\.jsdelivr\.net\/npm\/mermaid@/.test(url)) {
      const rel = u.pathname.replace(/^\/npm\/mermaid@[^/]+\//, "");
      try {
        return route.fulfill({ body: fs.readFileSync(path.join(mermaidRoot, rel)), contentType: "text/javascript", headers: { "access-control-allow-origin": "*" } });
      } catch (e) { return route.abort(); }
    }
    if (/cdn\.jsdelivr\.net\/npm\/chart\.js@/.test(url)) {
      return route.fulfill({ body: fs.readFileSync(path.join(chartRoot, "dist", "chart.umd.js")), contentType: "text/javascript", headers: { "access-control-allow-origin": "*" } });
    }
    return route.abort();
  });
}

// Wait for the concrete render signals (mermaid diagrams have an <svg>, Chart.js canvases are
// painted) instead of a fixed sleep, so the capture is not a flaky race under CI load.
async function waitForRichContent(page) {
  await page.waitForFunction(() => {
    const mermaidReady = [...document.querySelectorAll("pre.mermaid")].every((m) => m.querySelector("svg"));
    // A chart canvas (CMH wraps every chart in .chart-wrap) is ready once it has actually PAINTED -
    // a small downscaled sample of it has non-blank pixels. This is a real paint signal that works
    // whether Chart.js is the CDN global (reports) or an inline vendored copy not exposed on window
    // (the deck), and a chart that never renders stays blank so the wait times out (the test fails)
    // rather than capturing an empty chart region. (Reading back from the same-origin canvas does
    // not taint it.)
    const painted = (c) => {
      try {
        const t = document.createElement("canvas");
        t.width = 24;
        t.height = 24;
        const ctx = t.getContext("2d");
        ctx.drawImage(c, 0, 0, 24, 24);
        const d = ctx.getImageData(0, 0, 24, 24).data;
        for (let i = 0; i < d.length; i += 4) {
          if (d[i + 3] !== 0 && (d[i] < 250 || d[i + 1] < 250 || d[i + 2] < 250)) return true;
        }
        return false;
      } catch (e) {
        return false; // a chart canvas we cannot sample is not proven painted - keep waiting (a
        // genuinely-unrenderable chart then fails via the 20s timeout rather than passing blank)
      }
    };
    const chartsReady = [...document.querySelectorAll(".chart-wrap canvas")].every(painted);
    return mermaidReady && chartsReady;
  }, undefined, { timeout: 20000 });
  await page.waitForTimeout(600); // let charts finish their first paint/animation before capture
}

// Temp SRI-stripped example copies created for a test run, cleaned up in afterAll.
const tmpCopies = [];
test.afterAll(() => {
  for (const p of tmpCopies) {
    try { fs.rmSync(p, { force: true }); } catch { /* best effort */ }
  }
  tmpCopies.length = 0;
});

// Render an example under print, routing its CDN libs to the vendored node_modules copies. Some
// examples pin a Chart.js CDN build with a Subresource-Integrity hash; the vendored node_modules
// build is a different version, so its bytes fail that SRI check and the browser blocks the script
// (Chart.js never loads and every chart canvas stays blank). Strip the integrity attribute from a
// throwaway copy of the example so the routed vendored build is accepted - the copy is only used to
// render a PDF, never shipped. (Mermaid is loaded via an ESM import with no SRI, and the vendored
// mermaid version matches the pinned one, so it needs no rewrite.)
async function openForPrint(page, htmlFile) {
  const html = fs.readFileSync(htmlFile, "utf8").replace(/\s+integrity=("|')[^"']*\1/g, "");
  const tmp = path.join(os.tmpdir(), `cmh-print-${path.basename(htmlFile, ".html")}-${process.pid}-${tmpCopies.length}.html`);
  fs.writeFileSync(tmp, html);
  tmpCopies.push(tmp);
  await page.goto(fileUrl(tmp), { waitUntil: "load" });
  await ready(page);
  await waitForRichContent(page);
}

async function renderPdf(page, htmlFile) {
  await openForPrint(page, htmlFile);
  return await page.pdf({ printBackground: true, preferCSSPageSize: true });
}

// Fraction of non-white pixels on a rendered page bitmap (a coarse "is there ink here" measure
// that is robust to anti-aliasing / platform font differences).
function inkFraction(pngBuffer) {
  const png = PNG.sync.read(pngBuffer);
  const { data, width, height } = png;
  let ink = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i] < 245 || data[i + 1] < 245 || data[i + 2] < 245) ink++;
  }
  return ink / (width * height);
}

async function analyzePdf(pdfBuffer) {
  const parser = new PDFParse({ data: pdfBuffer });
  const textRes = await parser.getText();
  const shotRes = await parser.getScreenshot();
  await parser.destroy();
  const pages = shotRes.pages.map((pg) => ({
    width: pg.width,
    height: pg.height,
    ratio: pg.width / pg.height,
    ink: inkFraction(Buffer.from(pg.dataUrl.split(",")[1], "base64")),
  }));
  return { pages, total: textRes.total, text: (textRes.text || "").replace(/\s+/g, " ") };
}

// A page with essentially no ink is a blank/artifact page (a print bug this guards - a phantom
// trailing page, or a diagram/grid pushed onto an otherwise-empty page). Real content bottoms out
// near 0.9% ink (a last page carrying only a short closing paragraph); a truly blank/artifact page
// renders near 0.1%. 0.3% sits cleanly between the two. (Stranded HEADINGS - a heading alone on a
// page - are prevented structurally by the print CSS: `h1..h4 { break-after: avoid }` keeps a
// heading with the content that follows it, so this coarse ink check need not detect them.)
const MIN_INK = 0.003;

test("CMH-PRINT-03: the deck prints one landscape 16:9 page per slide, none clipped or blank", async ({ page }) => {
  const deck = path.join(EXAMPLES, "deck-showcase.html");
  await routeRichContentLocal(page);
  await openForPrint(page, deck);
  const slideCount = await page.locator('#commentRoot[data-cmh-mode="deck"] .slide').count();

  // Under print media no slide's content overflows its fixed 1920x1080 box - a slide keeps its own
  // authored grid/flex layout (83-print.js pins each slide's on-screen display for print), so a
  // multi-column slide is NOT flattened to a block whose stacked columns overflow and clip.
  // scrollHeight/scrollWidth report the FULL content extent (even the part clipped by
  // overflow:hidden, and even under the slide's justify-content:center), so a tight ratio threshold
  // is an honest anti-clipping guard in both axes (the flattened header overflowed vertically ~1.57).
  await page.emulateMedia({ media: "print" });
  // The Save as PDF action and Ctrl/Cmd+P both fire `beforeprint`, which is what applies the
  // print-scoped deck slide display-pin (the pin is not permanent - a slide carries no inline style
  // under normal media). Fire it here so this measurement and the page.pdf below exercise the real
  // print path.
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  const slideRatios = await page.locator('#commentRoot[data-cmh-mode="deck"] .slide').evaluateAll((els) =>
    els.map((s) => {
      const r = s.getBoundingClientRect();
      return { v: s.scrollHeight / r.height, h: s.scrollWidth / r.width, display: getComputedStyle(s).display };
    }));
  // The pin must actually preserve authored flex/grid slide layouts in print - if it silently
  // no-ops (or is removed), the vendored engine's `.slide{display:block!important}` wins and EVERY
  // slide computes `display:block`, flattening multi-column slides. Requiring at least one flex/grid
  // slide keeps the overflow guard below meaningful (a deck of only block slides would never
  // exercise the flattening the pin prevents). Verified: with the pin the showcase's slides compute
  // grid/flex (max overflow ~1.01); without it slide 1 flattens to block and overflows to ~1.57.
  expect(slideRatios.some((s) => s.display === "flex" || s.display === "grid"),
    "the display-pin preserves authored flex/grid slide layouts in print").toBe(true);
  for (let i = 0; i < slideRatios.length; i++) {
    expect(slideRatios[i].v, `deck slide ${i + 1} content fits its box vertically (not flattened/clipped)`).toBeLessThan(1.05);
    expect(slideRatios[i].h, `deck slide ${i + 1} content fits its box horizontally (not clipped)`).toBeLessThan(1.05);
  }

  // A deck keeps its own designed DARK code/KQL/diff backgrounds in print (with bright tokens that
  // are legible on them) - the report-only "reset code backgrounds to light paper" and dark-theme
  // token re-light rules are scoped away from decks, so they must never leak in and strand a deck's
  // bright tokens on a white background. Guard that every syntax block in the deck keeps a dark
  // background under print (in the dark theme, the worst case for a leak).
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
  const darkBlockBgs = await page.locator(
    '#commentRoot[data-cmh-mode="deck"] .cmh-diff-view, #commentRoot[data-cmh-mode="deck"] figure.cmh-kql'
  ).evaluateAll((els) => els.map((el) => {
    const m = getComputedStyle(el).backgroundColor.match(/(\d+(?:\.\d+)?)/g).map(Number);
    // relative luminance of the block background (0 = black, 1 = white)
    const lin = m.slice(0, 3).map((v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); });
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
  }));
  await page.evaluate(() => document.documentElement.removeAttribute("data-theme"));
  expect(darkBlockBgs.length, "deck exposes syntax-highlighted code/KQL/diff blocks").toBeGreaterThan(0);
  for (const l of darkBlockBgs) {
    expect(l, "deck syntax block keeps its designed dark background in print (report light-reset must not leak in)").toBeLessThan(0.2);
  }
  await page.emulateMedia({ media: null });

  const pdf = await page.pdf({ printBackground: true, preferCSSPageSize: true });
  const { pages, total } = await analyzePdf(pdf);

  // Exactly one page per slide - no phantom trailing blank page, no slide split across two pages.
  expect(total).toBe(slideCount);
  expect(pages.length).toBe(slideCount);
  for (let i = 0; i < pages.length; i++) {
    const pg = pages[i];
    // Each slide fills its own landscape 16:9 page (the named-page fix), so a fixed 1920x1080
    // slide is never clipped by a portrait paper page.
    expect(pg.width, `deck page ${i + 1} is landscape`).toBeGreaterThan(pg.height);
    expect(pg.ratio, `deck page ${i + 1} is ~16:9`).toBeGreaterThan(1.6);
    expect(pg.ratio, `deck page ${i + 1} is ~16:9`).toBeLessThan(1.9);
    expect(pg.ink, `deck page ${i + 1} is not blank`).toBeGreaterThan(MIN_INK);
  }
});

test("CMH-PRINT-04: reports print with no blank/stranded pages and dense widgets/galleries survive", async ({ page }) => {
  // report-triage carries the draggable kanban board; report-metrics carries a tall mermaid state
  // diagram plus multi-chart galleries - the two content shapes that used to strand a heading on a
  // near-blank page or split a diagram across a page break. Render each once and reuse the buffer.
  await routeRichContentLocal(page);
  const triagePdf = await renderPdf(page, path.join(EXAMPLES, "report-triage.html"));
  const metricsPdf = await renderPdf(page, path.join(EXAMPLES, "report-metrics.html"));
  const triage = await analyzePdf(triagePdf);
  const metrics = await analyzePdf(metricsPdf);

  for (const [name, report] of [["report-triage.html", triage], ["report-metrics.html", metrics]]) {
    expect(report.pages.length, `${name} has pages`).toBeGreaterThan(0);
    for (let i = 0; i < report.pages.length; i++) {
      // Report pages stay portrait (default paper), and none is blank.
      expect(report.pages[i].width, `${name} page ${i + 1} is portrait`).toBeLessThan(report.pages[i].height);
      expect(report.pages[i].ink, `${name} page ${i + 1} is not blank`).toBeGreaterThan(MIN_INK);
    }
  }

  // The kanban board columns and cards actually make it into the printed triage PDF (the board is
  // block-stacked for print rather than relying on a grid track layout Chromium fragments badly).
  for (const card of ["API saturation", "Auth retries", "Cache patch", "Log sampling restored"]) {
    expect(triage.text, `triage PDF contains "${card}"`).toContain(card);
  }

  // Rich content (Chart.js canvases, mermaid diagrams) is not accidentally HIDDEN by the print CSS -
  // otherwise a report could still satisfy the per-page ink check purely on its body text while its
  // charts/diagrams silently vanished from the PDF. The page is still on report-metrics (the last
  // render), which carries both a multi-chart gallery and a tall mermaid diagram.
  await page.emulateMedia({ media: "print" });
  const richVisible = await page.evaluate(() => {
    const shown = (el) => {
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return cs.display !== "none" && cs.visibility !== "hidden" && r.width > 1 && r.height > 1;
    };
    const charts = [...document.querySelectorAll(".chart-wrap canvas")];
    const diagrams = [...document.querySelectorAll("pre.mermaid svg")];
    return { charts: charts.length, chartsShown: charts.filter(shown).length,
      diagrams: diagrams.length, diagramsShown: diagrams.filter(shown).length,
      // Rendered height of each mermaid diagram in CSS px (1in = 96px under print media).
      diagramHeights: diagrams.map((el) => el.getBoundingClientRect().height) };
  });
  await page.emulateMedia({ media: null });
  expect(richVisible.charts, "report-metrics has chart canvases").toBeGreaterThan(0);
  expect(richVisible.chartsShown, "every chart canvas stays visible in print").toBe(richVisible.charts);
  expect(richVisible.diagrams, "report-metrics has mermaid diagrams").toBeGreaterThan(0);
  expect(richVisible.diagramsShown, "every mermaid diagram stays visible in print").toBe(richVisible.diagrams);
  // Each mermaid diagram is CONTAINED on one page (the CMH-PRINT-04 promise): the print CSS caps
  // `pre.mermaid svg` at max-height 8.4in, so a tall state diagram is scaled to fit one page instead
  // of splitting a node across a page break. 8.4in = 806.4 CSS px under print media; allow a small
  // rounding tolerance. 8.4in is well under the printable height of both Letter (~9.8in) and A4
  // (~10.5in) at the 0.6in page margin, so a capped diagram always fits its page.
  const CAP_PX = 8.4 * 96 + 4;
  for (let i = 0; i < richVisible.diagramHeights.length; i++) {
    expect(richVisible.diagramHeights[i],
      `mermaid diagram ${i + 1} is capped to fit one page (<= 8.4in), not split across a page break`)
      .toBeLessThanOrEqual(CAP_PX);
  }
});

// Relative luminance (WCAG) of an "rgb(r, g, b)" color string.
function relLuminance(rgb) {
  const m = rgb.match(/(\d+(?:\.\d+)?)/g).map(Number);
  const lin = m.slice(0, 3).map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}
// Contrast ratio of a foreground color string against white.
function contrastOnWhite(rgb) {
  const l = relLuminance(rgb);
  return (1.0 + 0.05) / (l + 0.05);
}

test("CMH-PRINT-05: print re-lights dark-theme code/KQL tokens so they stay legible on the paper background", async ({ page }) => {
  // A dark-theme reader keeps html[data-theme="dark"] set when printing. Print forces code/KQL
  // backgrounds to the light paper surface, so the dark-mode token colors (light-green strings,
  // etc.) would otherwise print near-invisibly on white. report-metrics carries a KQL block and a
  // highlighted code block. Set dark theme, enter print media, and assert every tinted token has
  // real contrast against the white print background (the un-relit pastels sit near 1.3-1.9:1).
  await routeRichContentLocal(page);
  await openForPrint(page, path.join(EXAMPLES, "report-metrics.html"));
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
  await page.emulateMedia({ media: "print" });
  const printState = await page.evaluate(() => {
    const sel = [".cmh-kql-kw", ".cmh-kql-fn", ".cmh-kql-str", ".cmh-kql-num",
      ".cmh-code-kw", ".cmh-code-fn", ".cmh-code-str", ".cmh-code-num"];
    const colors = {};
    for (const s of sel) {
      const el = document.querySelector("#commentRoot " + s);
      if (el) colors[s] = getComputedStyle(el).color;
    }
    return {
      colors,
      colorScheme: getComputedStyle(document.documentElement).colorScheme,
      bodyBg: getComputedStyle(document.body).backgroundColor,
    };
  });
  await page.emulateMedia({ media: null });
  // The document prints on light paper regardless of the dark on-screen theme: the color-scheme is
  // reset to light (otherwise the browser paints the page canvas / @page margins dark) and the body
  // background is white.
  expect(printState.colorScheme, "dark-theme document prints with a light color-scheme").toContain("light");
  expect(printState.bodyBg, "dark-theme document prints on a white body background").toBe("rgb(255, 255, 255)");
  const colors = printState.colors;
  const present = Object.keys(colors);
  expect(present.length, "report-metrics exposes highlighted KQL/code tokens").toBeGreaterThan(0);
  for (const s of present) {
    expect(contrastOnWhite(colors[s]), `${s} (${colors[s]}) is legible on the white print background`)
      .toBeGreaterThanOrEqual(4.5);
  }
});
