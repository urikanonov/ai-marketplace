import { test, expect } from "@playwright/test";
import fs from "fs";
import os from "os";
import path from "path";
import { PDFParse } from "pdf-parse";
import { PNG } from "pngjs";
import { DEV, EXAMPLES, INLINE, fileUrl, ready } from "./helpers.js";

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
  // Wait for the chart/diagram LAYOUT to stabilize (not just first paint): the single-page print
  // path measures the settled content height, and a chart/mermaid that is still resizing would make
  // the page measure short. Wait until the total content height stays unchanged for a sustained
  // window (a real user has viewed the settled document before printing).
  await page.waitForFunction(() => {
    const h = document.documentElement.scrollHeight;
    const now = Date.now();
    if (window.__cmhStableH !== h) { window.__cmhStableH = h; window.__cmhStableAt = now; return false; }
    return now - (window.__cmhStableAt || now) >= 700;
  }, undefined, { timeout: 6000, polling: 150 }).catch(() => {});
  await page.waitForTimeout(200);
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

// Render like a real "Save as PDF": just drive the browser's native print pipeline (page.pdf) with
// no manual media emulation, so `beforeprint` fires in SCREEN media and Chromium locks the @page to
// that measurement - exactly what interactive Ctrl+P / Save as PDF does. preferCSSPageSize honors
// the dynamic single-page @page the runtime injects, so a flat document collapses onto one page.
async function renderSinglePagePdf(page, htmlFile) {
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
  const pages = shotRes.pages.map((pg) => {
    // Kept so a test that needs a second, more specific measurement (blank-band analysis) can run it
    // without re-rendering the PDF; the ink pass below already decodes the same bitmap.
    const png = Buffer.from(pg.dataUrl.split(",")[1], "base64");
    return { width: pg.width, height: pg.height, ratio: pg.width / pg.height, ink: inkFraction(png), png };
  });
  return { pages, total: textRes.total, text: (textRes.text || "").replace(/\s+/g, " ") };
}

// A page with essentially no ink is a blank/artifact page (a print bug this guards - a phantom
// trailing page, or a diagram/grid pushed onto an otherwise-empty page). Real content bottoms out
// near 0.9% ink (a last page carrying only a short closing paragraph); a truly blank/artifact page
// renders near 0.1%. 0.3% sits cleanly between the two. (Stranded HEADINGS - a heading alone on a
// page - are prevented structurally by the print CSS: `h1..h4 { break-after: avoid }` keeps a
// heading with the content that follows it, so this coarse ink check need not detect them.)
const MIN_INK = 0.003;

// Widest run of consecutive BLANK pixel columns on a page bitmap, as a fraction of the page width.
// A column counts as blank when almost nothing is painted down its whole height, so the ragged right
// edge of prose does not read as blank while a genuine empty vertical band - the tell of a diagram
// printed at a fraction of the column width - does.
function maxBlankColumnBand(pngBuffer) {
  const png = PNG.sync.read(pngBuffer);
  const { data, width, height } = png;
  const threshold = Math.max(4, Math.round(height * 0.02));
  let best = 0, run = 0;
  for (let x = 0; x < width; x++) {
    let inked = 0;
    for (let y = 0; y < height; y++) {
      const i = (y * width + x) * 4;
      if (data[i] < 245 || data[i + 1] < 245 || data[i + 2] < 245) inked++;
    }
    if (inked > threshold) run = 0;
    else { run++; if (run > best) best = run; }
  }
  return best / width;
}

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
      // Per diagram: its rendered size in CSS px (1in = 96px under print media), the width of the
      // column it prints into, and whether it is TALL-NARROW (the aspect the height cap mis-scales,
      // marked by the runtime; see CMH-PRINT-09).
      diagramBoxes: diagrams.map((el) => {
        const host = el.closest("pre.mermaid");
        const r = el.getBoundingClientRect();
        return { h: r.height, w: r.width, hostW: host ? host.clientWidth : 0,
          tall: !!(host && host.classList.contains("cmh-diagram-tall")) };
      }) };
  });
  await page.emulateMedia({ media: null });
  expect(richVisible.charts, "report-metrics has chart canvases").toBeGreaterThan(0);
  expect(richVisible.chartsShown, "every chart canvas stays visible in print").toBe(richVisible.charts);
  expect(richVisible.diagrams, "report-metrics has mermaid diagrams").toBeGreaterThan(0);
  expect(richVisible.diagramsShown, "every mermaid diagram stays visible in print").toBe(richVisible.diagrams);
  // A diagram of normal aspect is CONTAINED on one page (the CMH-PRINT-04 promise): the print CSS
  // caps `pre.mermaid svg` at max-height 8.4in, so a tall state diagram is scaled to fit one page
  // instead of splitting a node across a page break. 8.4in = 806.4 CSS px under print media; allow a
  // small rounding tolerance. 8.4in is well under the printable height of both Letter (~9.8in) and A4
  // (~10.5in) at the 0.6in page margin, so a capped diagram always fits its page. A TALL-NARROW
  // diagram is the documented exception (CMH-PRINT-09): fitting it to the page height would shrink
  // its width to a sliver, so it binds on WIDTH and flows across pages instead - assert that here
  // rather than exempting it silently.
  const CAP_PX = 8.4 * 96 + 4;
  for (let i = 0; i < richVisible.diagramBoxes.length; i++) {
    const box = richVisible.diagramBoxes[i];
    if (box.tall) {
      expect(box.w / box.hostW,
        `tall-narrow mermaid diagram ${i + 1} prints at the full column width (CMH-PRINT-09)`)
        .toBeGreaterThan(0.9);
    } else {
      expect(box.h,
        `mermaid diagram ${i + 1} is capped to fit one page (<= 8.4in), not split across a page break`)
        .toBeLessThanOrEqual(CAP_PX);
    }
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

test("CMH-PRINT-06: an eligible flat document prints as a single continuous no-break page", async ({ page }) => {
  test.setTimeout(180000); // several real page.pdf renders (eligible + guard + deck + narrow + probes) plus settle
  await routeRichContentLocal(page);
  // report-taxi (tables + inline charts) and report-community-garden (prose + a mermaid diagram +
  // a code diff) both paginate to many Letter pages by default; the single-page print path collapses
  // each to ONE tall continuous page (no internal page breaks) with all content present. Render each
  // once and reuse the buffer.
  const taxiPdf = await renderSinglePagePdf(page, path.join(EXAMPLES, "report-taxi.html"));
  const gardenPdf = await renderSinglePagePdf(page, path.join(EXAMPLES, "report-community-garden.html"));
  const taxi = await analyzePdf(taxiPdf);
  const garden = await analyzePdf(gardenPdf);

  for (const [name, report] of [["report-taxi.html", taxi], ["report-community-garden.html", garden]]) {
    // Exactly one page - the whole document is a single no-break canvas.
    expect(report.pages.length, `${name} prints as a single page`).toBe(1);
    const pg = report.pages[0];
    // The page is portrait (a tall continuous canvas), not clipped, and not blank.
    expect(pg.width, `${name} single page is portrait (taller than wide)`).toBeLessThan(pg.height);
    // A continuous multi-section report is far taller than a normal Letter page (792pt), proving
    // the content is not paginated onto standard pages.
    expect(pg.height, `${name} single page is a tall continuous canvas`).toBeGreaterThan(792 * 2);
    expect(pg.ink, `${name} single page is not blank`).toBeGreaterThan(MIN_INK);
  }

  // Nothing is lost off the ends: content from the TOP and the BOTTOM of each report lands on the
  // one page (a too-short page would clip the closing section).
  expect(taxi.text, "taxi single page keeps the opening section").toContain("Executive Summary");
  expect(taxi.text, "taxi single page keeps the closing section").toContain("Recommendations and Next Steps");
  expect(garden.text, "garden single page keeps the opening section").toContain("Overview");
  expect(garden.text, "garden single page keeps the closing section").toContain("Next Steps");

  // The single-page path is generic to EVERY eligible flat example, not just the two long reports
  // above. report-checklist (a review checklist) and report-notes (editable notes) are each taller
  // than one US Letter sheet (792pt), so normal pagination would split them across sheets; the
  // single-page path must keep each on ONE tall portrait page, not blank, with its content present.
  // Getting exactly one page TALLER than a Letter sheet pins the collapse (a doc that trivially fit a
  // single sheet, or that regressed to normal pagination, would not).
  for (const name of ["report-checklist.html", "report-notes.html"]) {
    await page.setViewportSize({ width: 1280, height: 900 });
    const report = await analyzePdf(await renderSinglePagePdf(page, path.join(EXAMPLES, name)));
    expect(report.pages.length, `${name} prints as a single page`).toBe(1);
    const pg = report.pages[0];
    expect(pg.width, `${name} single page is portrait (taller than wide)`).toBeLessThan(pg.height);
    expect(pg.height, `${name} single page is taller than one Letter sheet (genuine collapse, not a short doc)`).toBeGreaterThan(792);
    expect(pg.ink, `${name} single page is not blank`).toBeGreaterThan(MIN_INK);
    expect(report.text.length, `${name} single page carries its content`).toBeGreaterThan(200);

    // Generic across print drivers (not just the honored-@page path): at a standard printable viewport
    // the print layout must not overflow horizontally, so a driver that IGNORES the custom @page
    // (Microsoft Print to PDF, physical printers) reflows into its own printable area rather than
    // downscaling an oversized forced width. 744px approximates a US Letter sheet minus typical default
    // margins. Asserted PER example so checklist/notes content is covered, not only report-taxi.
    await page.setViewportSize({ width: 744, height: 900 });
    await openForPrint(page, path.join(EXAMPLES, name));
    await page.emulateMedia({ media: "print" });
    await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
    const fit = await page.evaluate(() => ({
      scrollW: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
      vw: window.innerWidth,
    }));
    await page.evaluate(() => window.dispatchEvent(new Event("afterprint")));
    await page.emulateMedia({ media: null });
    expect(fit.scrollW, `${name} print layout fits a standard printable width with no forced oversized body width (generic across drivers)`).toBeLessThanOrEqual(fit.vw + 2);
  }
  await page.setViewportSize({ width: 1280, height: 900 });

  // Scope guard: a document with a block-stacking container - report-metrics has multi-column chart
  // galleries (.visual-grid), report-triage has a grid kanban board - is intentionally LEFT ON
  // NORMAL PAGINATION (its grid->block print reflow + async chart resize cannot be measured before
  // Chromium locks the @page), so it must NOT be collapsed to a single page. Content is complete on
  // standard pages, not clipped.
  for (const name of ["report-metrics.html", "report-triage.html"]) {
    const report = await analyzePdf(await renderSinglePagePdf(page, path.join(EXAMPLES, name)));
    expect(report.pages.length, `${name} (block-stacking container) stays on normal pagination`).toBeGreaterThan(1);
    for (let i = 0; i < report.pages.length; i++) {
      expect(report.pages[i].width, `${name} page ${i + 1} is standard portrait paper`).toBeLessThan(report.pages[i].height);
    }
  }

  // A diagram gallery (`.cmh-diagram-gallery`) is ALSO a block-stacking container: print CSS reflows
  // it grid->block and drops its per-card height cap, so its printed height cannot be measured before
  // the @page lock. A document containing one must therefore stay on normal pagination (not collapse
  // to a single page), even when it has no `.visual-grid`. Stage a minimal eligible taxi copy with a
  // bare gallery injected and assert the single-page path does NOT apply (no injected @page).
  await page.setViewportSize({ width: 1280, height: 900 });
  const gallerySrc = fs.readFileSync(path.join(EXAMPLES, "report-taxi.html"), "utf8");
  const gallery = '<section><h2>Diagram gallery</h2><div class="cmh-diagram-gallery">'
    + '<figure><pre class="mermaid cm-skip">flowchart TD\n  A[One] --&gt; B[Two]</pre></figure></div></section>';
  const galleryHtml = gallerySrc.includes("</main>")
    ? gallerySrc.replace("</main>", gallery + "</main>")
    : gallerySrc.replace("</body>", gallery + "</body>");
  const galleryFile = path.join(os.tmpdir(), `cmh-print-gallery-${process.pid}.html`);
  fs.writeFileSync(galleryFile, galleryHtml);
  tmpCopies.push(galleryFile);
  await openForPrint(page, galleryFile);
  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  const galleryApplied = await page.evaluate(() => {
    const el = document.getElementById("cmhPrintSinglePage");
    return !!(el && /@page\{size:/.test(el.textContent || ""));
  });
  await page.emulateMedia({ media: null });
  expect(galleryApplied,
    "a document with a diagram gallery stays on normal pagination (single-page path not applied)").toBe(false);

  // Recheck at PRINT time, not only at setup (pins the apply()-time eligibility recheck): a diagram
  // gallery inserted AFTER runtime setup (so the setup-time guard at registration already passed and
  // the single-page path is wired up) must STILL fall back to normal pagination, because apply()
  // re-checks `hasBlockStackingContainer()` on every print. Without that recheck the late gallery
  // would wrongly receive the single-page @page (its print-time grid->block reflow cannot be
  // pre-measured). First confirm the eligible document DID arm the single-page path (a custom @page
  // applies), so the later fallback is attributable to the apply()-time recheck and not the setup
  // guard, then inject the gallery and print again.
  await page.setViewportSize({ width: 1280, height: 900 });
  await openForPrint(page, path.join(EXAMPLES, "report-taxi.html"));
  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  const baselineApplied = await page.evaluate(() => {
    const el = document.getElementById("cmhPrintSinglePage");
    return !!(el && /@page\{size:/.test(el.textContent || ""));
  });
  await page.evaluate(() => window.dispatchEvent(new Event("afterprint"))); // reset the once-per-print latch
  await page.emulateMedia({ media: null });
  expect(baselineApplied,
    "premise: the eligible document armed the single-page path before a late gallery was added").toBe(true);
  await page.evaluate(() => {
    const root = document.getElementById("commentRoot") || document.body;
    const sec = document.createElement("section");
    sec.innerHTML = '<h2>Late gallery</h2><div class="cmh-diagram-gallery">'
      + '<figure><pre class="mermaid cm-skip">flowchart TD\n  A[One] --&gt; B[Two]</pre></figure></div>';
    root.appendChild(sec);
  });
  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  const lateGalleryApplied = await page.evaluate(() => {
    const el = document.getElementById("cmhPrintSinglePage");
    return !!(el && /@page\{size:/.test(el.textContent || ""));
  });
  await page.emulateMedia({ media: null });
  expect(lateGalleryApplied,
    "a diagram gallery inserted AFTER setup makes apply() re-check and fall back (no custom @page)").toBe(false);

  // The single-page logic is scoped to flat documents: a deck is unaffected and still prints one
  // landscape page PER SLIDE (see CMH-PRINT-03), never collapsed to a single page.
  const deckPdf = await renderSinglePagePdf(page, path.join(EXAMPLES, "deck-showcase.html"));
  const deck = await analyzePdf(deckPdf);
  expect(deck.pages.length, "deck is unaffected: still one page per slide, not a single page").toBeGreaterThan(1);

  // Grow-to-fit (the overflow-growth loop): content with an explicit width ABOVE the shareable cap
  // (816px) must GROW the honored @page past the cap so it is never clipped, instead of staying at the
  // capped/shareable width. This PINS the growth loop: a fixed 1000px-wide block is wider than both the
  // narrow viewport AND the 816px cap, so without the loop apply() would leave the content column
  // capped, the block would overflow it, and apply() would FALL BACK to normal pagination (no custom
  // @page at all). Assert the parsed @page width GREW above the cap and still covers the content.
  await page.setViewportSize({ width: 480, height: 900 });
  await openForPrint(page, path.join(EXAMPLES, "report-taxi.html"));
  await page.evaluate(() => {
    const root = document.getElementById("commentRoot") || document.body;
    const d = document.createElement("div");
    // A fixed width well above the 816px shareable cap, un-capped so it truly overflows the column.
    d.setAttribute("style", "width:1000px;max-width:none;height:40px;background:#eee");
    d.textContent = "wide-probe-content";
    root.appendChild(d);
  });
  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  const narrow = await page.evaluate(() => {
    const el = document.getElementById("cmhPrintSinglePage");
    const css = el ? el.textContent : "";
    const m = css.match(/@page\{size:(\d+(?:\.\d+)?)px/);
    return {
      scrollW: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
      pageW: m ? parseFloat(m[1]) : 0,
    };
  });
  await page.emulateMedia({ media: null });
  expect(narrow.pageW,
    "content wider than the 816px shareable cap grows the honored @page ABOVE the cap (not capped-and-clipped)")
    .toBeGreaterThan(820);
  expect(narrow.scrollW,
    "the grown single @page still covers the widest content (no right-edge clip on the honored page)")
    .toBeLessThanOrEqual(narrow.pageW + 2);

  // Shareable page + generic across ALL drivers: at a WIDE viewport the honored single @page is sized
  // to a standard, shareable page width (US Letter, ~816px) rather than the on-screen reading column
  // (~1280px on a wide screen), AND the injected print CSS uses width:auto - it does NOT force a fixed
  // body width. That progressive degradation is what makes it generic: a browser that HONORS the
  // custom @page (Chromium's native vector "Save as PDF") fills the shareable-width page as one tall
  // page, while a driver that IGNORES it (Microsoft Print to PDF, physical printers, browsers without
  // custom-@page support) reflows the content into its OWN real Letter/A4 printable area instead of
  // being downscaled to fit an oversized forced body width (the old bug: poor quality, side
  // whitespace, stranded diagrams).
  const SHAREABLE_MAX_W = 820; // US Letter width (816px) + slack
  await page.setViewportSize({ width: 1280, height: 900 });
  await openForPrint(page, path.join(EXAMPLES, "report-taxi.html"));
  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  const wide = await page.evaluate(() => {
    const el = document.getElementById("cmhPrintSinglePage");
    const css = el ? el.textContent : "";
    const m = css.match(/@page\{size:(\d+(?:\.\d+)?)px (\d+(?:\.\d+)?)px/);
    return {
      applied: !!(css && /@page\{size:/.test(css)),
      pageW: m ? parseFloat(m[1]) : 0,
      pageH: m ? parseFloat(m[2]) : 0,
      // Genericity contract: content width is auto (flows into the real page), never a forced px width.
      // The only px dimensions allowed are inside the @page rule (the page size and margin).
      usesAutoWidth: /html,body,\.app\{width:auto/.test(css),
      forcesFixedWidth: /width:\s*\d+px/.test(css.replace(/@page\{[^}]*\}/g, "")),
    };
  });
  await page.emulateMedia({ media: null });
  expect(wide.applied, "wide-viewport taxi still uses the single continuous-page path").toBe(true);
  expect(wide.pageW, "the honored single @page is sized to a shareable standard page width")
    .toBeLessThanOrEqual(SHAREABLE_MAX_W);
  expect(wide.pageH, "the honored single @page is still a tall continuous canvas")
    .toBeGreaterThan(SHAREABLE_MAX_W * 3);
  expect(wide.usesAutoWidth,
    "print CSS uses width:auto so honoring and non-honoring drivers alike flow into their real page")
    .toBe(true);
  expect(wide.forcesFixedWidth,
    "print CSS must NOT force a fixed (oversized) body/content width - that is what downscales non-honoring drivers")
    .toBe(false);

  // Non-honoring-driver proxy: at a standard printable viewport width the print layout must not
  // overflow horizontally, i.e. there is no forced oversized body width, so a driver that ignores the
  // custom @page (Microsoft Print to PDF, physical printers) reflows cleanly rather than downscaling.
  // 744px approximates a US Letter sheet minus typical default margins.
  await page.setViewportSize({ width: 744, height: 900 });
  await openForPrint(page, path.join(EXAMPLES, "report-taxi.html"));
  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  const letterFit = await page.evaluate(() => ({
    scrollW: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
    vw: window.innerWidth,
  }));
  await page.emulateMedia({ media: null });
  expect(letterFit.scrollW,
    "print layout fits a standard printable width with no forced oversized body width (generic across drivers)")
    .toBeLessThanOrEqual(letterFit.vw + 2);

  // Fixed-paper cell wrapping (pins the print-only `#commentRoot td,th{overflow-wrap}` rule in
  // 92-print.css): a table cell whose SCREEN styling defeats wrapping (an inline overflow-wrap:normal
  // that overrides the inherited `anywhere`) holds a long unbreakable token, so it overflows on
  // screen. In PRINT media the print stylesheet's `!important` td/th wrap must override that inline
  // rule so the token wraps and the layout stays within a standard printable width - otherwise a
  // driver paginating onto fixed paper (Microsoft Print to PDF, a physical printer) clips the token
  // off the sheet edge. `measureCss` is applied only transiently DURING measurement and is replaced by
  // the final print CSS before this reads the layout, so the wrap here comes from 92-print.css: remove
  // that rule and this goes red.
  await page.setViewportSize({ width: 744, height: 900 });
  const cellSrc = fs.readFileSync(path.join(EXAMPLES, "report-taxi.html"), "utf8");
  const longTok = "X".repeat(240);
  const cellFrag = '<section><h2>Long token</h2><table><tbody><tr>'
    + '<td style="overflow-wrap:normal;word-break:keep-all;">' + longTok + '</td>'
    + '</tr></tbody></table></section>';
  const cellHtml = cellSrc.includes("</main>")
    ? cellSrc.replace("</main>", cellFrag + "</main>")
    : cellSrc.replace("</body>", cellFrag + "</body>");
  const cellFile = path.join(os.tmpdir(), `cmh-print-cell-${process.pid}.html`);
  fs.writeFileSync(cellFile, cellHtml);
  tmpCopies.push(cellFile);
  await openForPrint(page, cellFile);
  // Premise: on SCREEN the inline overflow-wrap:normal wins, so the long token does not wrap and the
  // cell forces the TABLE wider than its box. It no longer forces the whole DOCUMENT sideways -
  // the table's `.cmh-table-scroll` box contains that overflow now (CMH-RESP-11) - so the premise is
  // measured where the non-wrapping actually shows: the table against its own scroll box.
  const screenCellOverflow = await page.evaluate(() => {
    const cell = [...document.querySelectorAll("#commentRoot table td")]
      .find((td) => /^X{200,}$/.test(td.textContent.trim()));
    const table = cell.closest("table");
    const wrap = table.closest(".cmh-table-scroll");
    return Math.round(table.getBoundingClientRect().width - wrap.clientWidth);
  });
  const screenDocOverflow = await page.evaluate(() =>
    Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth);
  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  const printCellFit = await page.evaluate(() => ({
    scrollW: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
    vw: window.innerWidth,
  }));
  await page.emulateMedia({ media: null });
  expect(screenCellOverflow,
    "premise: the synthetic non-wrapping long-token cell makes the table overflow its scroll box").toBeGreaterThan(0);
  expect(screenDocOverflow,
    "and that overflow is contained on screen rather than pushing the document sideways (CMH-RESP-11)")
    .toBeLessThanOrEqual(2);
  expect(printCellFit.scrollW,
    "print media wraps the long-token cell so it fits the printable width (no fixed-paper right-edge clip)")
    .toBeLessThanOrEqual(printCellFit.vw + 2);

  // Comment/reply-heavy document must still print as ONE page: the print-only box model of the
  // comments appendix (per-comment margin/padding/border and the indented replies) is mirrored in the
  // screen-media measurement, so a heavily-commented document is measured accurately and does not
  // under-count its height and spill a near-blank overflow page. Seed many threaded comments, then
  // render like a real Save-as-PDF.
  await page.setViewportSize({ width: 1280, height: 900 });
  await openForPrint(page, path.join(EXAMPLES, "report-taxi.html"));
  await page.evaluate(() => {
    const t = Date.now();
    const rows = [];
    for (let i = 0; i < 12; i++) {
      rows.push({ id: "cprintroot" + i, anchorType: "document",
        note: "Review comment " + i + " with enough text to wrap across a couple of lines in the printed appendix so its box model matters.",
        author: "Reviewer", createdAt: new Date(t + i * 2000).toISOString() });
      rows.push({ id: "cprintrep" + i, parentId: "cprintroot" + i,
        note: "Reply to comment " + i + " END_COMMENT_MARKER_" + i,
        author: "Author", createdAt: new Date(t + i * 2000 + 500).toISOString() });
    }
    window.__cmhStorageCodec.write(rows);
  });
  await page.reload({ waitUntil: "load" });
  await ready(page);
  await waitForRichContent(page);
  const commented = await analyzePdf(await page.pdf({ printBackground: true, preferCSSPageSize: true }));
  expect(commented.total,
    "a comment/reply-heavy eligible document still prints as a single page (appendix measured accurately, no spill)")
    .toBe(1);
  expect(commented.text, "the final seeded review comment lands on the single page")
    .toContain("END_COMMENT_MARKER_11");

  // Oversized eligible document: taller than Chromium's ~200in page clamp (MAX_PAGE_PX = 18000px).
  // The single-page path must FALL BACK to normal pagination rather than clamp/clip the page, so the
  // closing marker survives across multiple standard pages. Stage a tall copy of the (eligible) taxi
  // report by appending ~20000px of filler ending in a unique marker.
  await page.setViewportSize({ width: 1280, height: 900 });
  const taxiSrc = fs.readFileSync(path.join(EXAMPLES, "report-taxi.html"), "utf8");
  const filler = '<section><h2>Oversized filler</h2>'
    + Array.from({ length: 500 }, (_unused, i) =>
      `<p>Filler paragraph ${i} - padding this document past the browser page-size clamp so the single-page path must fall back to normal pagination instead of clipping oversized content.</p>`).join("")
    + '<p>OVERSIZED_TAIL_MARKER_END</p></section>';
  const tallHtml = taxiSrc.includes("</main>")
    ? taxiSrc.replace("</main>", filler + "</main>")
    : taxiSrc.replace("</body>", filler + "</body>");
  const tallFile = path.join(os.tmpdir(), `cmh-print-oversized-${process.pid}.html`);
  fs.writeFileSync(tallFile, tallHtml);
  tmpCopies.push(tallFile);
  const oversized = await analyzePdf(await renderSinglePagePdf(page, tallFile));
  expect(oversized.pages.length, "oversized eligible document falls back to normal pagination").toBeGreaterThan(1);
  for (let i = 0; i < oversized.pages.length; i++) {
    expect(oversized.pages[i].width, `oversized page ${i + 1} is standard portrait paper`).toBeLessThan(oversized.pages[i].height);
  }
  expect(oversized.text, "oversized fallback keeps the closing content (not clipped by the clamp)")
    .toContain("OVERSIZED_TAIL_MARKER_END");
});

// A synthetic TALL-NARROW diagram: a pre-rendered mermaid SVG whose viewBox is 769 x 2197, the
// aspect (w/h ~ 0.35) reported in issue #937. Pre-rendered (`data-processed`) so the fixture needs
// no mermaid run and its geometry is exact. The rows carry ink across the full height, so a page
// that shows only a slice of the diagram is still clearly not blank.
const TALL_VB_W = 769, TALL_VB_H = 2197;
function tallNarrowDiagram(id) {
  const rows = [];
  const step = TALL_VB_H / 20;
  for (let i = 0; i < 20; i++) {
    const y = Math.round(8 + i * step);
    rows.push(`<rect x="90" y="${y}" width="589" height="${Math.round(step * 0.6)}" fill="#e2e2e2" stroke="#222222" stroke-width="4"></rect>`);
    rows.push(`<text x="130" y="${Math.round(y + step * 0.42)}" font-size="38" fill="#111111">Stage ${i + 1}</text>`);
  }
  return `<pre class="mermaid" id="${id}" data-processed="true">`
    + `<svg viewBox="0 0 ${TALL_VB_W} ${TALL_VB_H}" role="img" aria-label="tall narrow flow">${rows.join("")}</svg></pre>`;
}

// Stage a self-contained document (from dist/SHAREABLE.html) carrying the tall-narrow diagram plus
// a heading and lead paragraph before it - the shape that stranded a near-blank page - and enough
// prose after it that the document genuinely paginates. With `paginating`, a small multi-column
// gallery is added so the document is deliberately left on NORMAL pagination (a block-stacking
// container; see CMH-PRINT-06), which is the driver path where a stranded page shows up.
function stageTallDiagramDoc(key, { paginating = false } = {}) {
  const filler = (label, n) => Array.from({ length: n }, (_unused, i) =>
    `<p>${label} paragraph ${i + 1} - narrative text that gives the printed document real body so pagination is realistic.</p>`).join("");
  const gallery = '<section><h2>Gallery</h2><div class="visual-grid">'
    + '<figure><figcaption>Panel one</figcaption></figure>'
    + '<figure><figcaption>Panel two</figcaption></figure></div></section>';
  const content = `
    <header class="cmh-lede"><h1>Tall diagram print</h1><p>A tall-narrow flow diagram in a flat report.</p></header>
    <section><h2>Before the diagram</h2>${filler("Before", 6)}</section>
    <section${paginating ? ' style="break-before:page;page-break-before:always"' : ""}>
      <h2>Pipeline stages</h2>
      <p>The stages below are drawn as a tall-narrow flowchart.</p>
      <p>Each stage names one hop of the ingest pipeline, read top to bottom.</p>
      ${tallNarrowDiagram("tallHost")}
    </section>
    <section><h2>After the diagram</h2>${filler("After", 6)}</section>
    ${paginating ? gallery : ""}`;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_tall_"));
  let html = fs.readFileSync(INLINE, "utf8");
  const contentRe = /(<!-- BEGIN: commentable-html - CONTENT[^>]*-->)[\s\S]*?(<!-- END: commentable-html - CONTENT -->)/;
  html = html.replace(contentRe, (_m, a, b) => a + "\n" + content + "\n" + b);
  html = html.replace('data-comment-key="commentable-html-demo"', 'data-comment-key="' + key + '"');
  html = html.replace('data-doc-source="SHAREABLE.html"', 'data-doc-source="tall-diagram.html"');
  const file = path.join(dir, "tall-diagram.html");
  fs.writeFileSync(file, html);
  tmpCopies.push(file);
  return file;
}

test("CMH-PRINT-09: a tall-narrow diagram prints at column width instead of a sliver beside blank space", async ({ page }) => {
  test.setTimeout(120000); // two real page.pdf renders plus the print-media layout probes
  // The tall-media print cap used to scale by HEIGHT ONLY (`max-height:8.4in;width:auto`), so a
  // tall-narrow diagram's printed WIDTH collapsed to `8.4in * aspect` - here 42% of the column, with
  // the other 58% left empty - and, being an unbreakable ~8.4in block, it could not share a page, so
  // a paginating driver stranded a near-blank page before it. A tall-narrow diagram must instead bind
  // on WIDTH (fill the printable column) and be allowed to fragment.
  const doc = stageTallDiagramDoc("cmh-print-tall-narrow");

  // Print-media layout at a standard printable column (744px ~ a US Letter sheet minus default
  // margins): the rendered SVG must use essentially the whole width of its host, not a fraction.
  await page.setViewportSize({ width: 744, height: 900 });
  await page.goto(fileUrl(doc), { waitUntil: "load" });
  await ready(page);
  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  const printed = await page.evaluate(() => {
    const host = document.getElementById("tallHost");
    const svg = host.querySelector("svg");
    return {
      hostW: host.clientWidth,
      svgW: svg.getBoundingClientRect().width,
      svgH: svg.getBoundingClientRect().height,
    };
  });
  await page.evaluate(() => window.dispatchEvent(new Event("afterprint")));
  await page.emulateMedia({ media: null });
  expect(printed.hostW, "premise: the diagram host spans the printable column").toBeGreaterThan(600);
  // 0.9 is comfortably above the 0.42 the height-only cap produced and below 1.0, so it pins the
  // width binding without asserting sub-pixel exactness.
  expect(printed.svgW / printed.hostW,
    "a tall-narrow diagram prints at (essentially) the full printable column width, not a sliver")
    .toBeGreaterThan(0.9);

  // Paginating driver (a document deliberately left on normal pagination - a block-stacking gallery
  // makes it ineligible for the single continuous page; see CMH-PRINT-06). The section is forced to
  // start a fresh page so the geometry is deterministic. The diagram must now FILL the page it lands
  // on - top to bottom AND edge to edge - continuing onto the next page, instead of printing as a
  // 42%-wide sliver with a full-height empty band beside it.
  const paginatingDoc = stageTallDiagramDoc("cmh-print-tall-narrow-paged", { paginating: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(fileUrl(paginatingDoc), { waitUntil: "load" });
  await ready(page);
  await page.waitForTimeout(300);
  const paginated = await analyzePdf(await page.pdf({ printBackground: true, format: "Letter" }));
  expect(paginated.pages.length, "premise: the document paginates onto standard sheets").toBeGreaterThan(1);
  for (let i = 0; i < paginated.pages.length; i++) {
    expect(paginated.pages[i].ink, `page ${i + 1} is not blank`).toBeGreaterThan(MIN_INK);
  }
  // The busiest page is the one the diagram lands on. Its ink is pure geometry (the fixture's gray
  // rows cover a fixed share of the diagram box), so the threshold is font- and platform-independent:
  // the width-bound diagram measures ~36% ink, the height-capped sliver measured ~14%.
  const busiest = paginated.pages.reduce((a, b) => (b.ink > a.ink ? b : a));
  expect(busiest.ink,
    "the printed tall-narrow diagram fills its page rather than a sliver of it")
    .toBeGreaterThan(0.25);
  expect(maxBlankColumnBand(busiest.png),
    "no full-height empty band is left beside the printed diagram (the sliver left ~30% of the sheet blank)")
    .toBeLessThan(0.2);

  // Single continuous page (the CMH-PRINT-06 path): the whole document is one tall page, and the
  // diagram fills that page's content column rather than leaving a full-height empty band beside it.
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(fileUrl(doc), { waitUntil: "load" });
  await ready(page);
  await page.waitForTimeout(400);
  const single = await analyzePdf(await page.pdf({ printBackground: true, preferCSSPageSize: true }));
  expect(single.pages.length, "the eligible tall-diagram document still prints as a single page").toBe(1);
  expect(single.pages[0].ink, "the single continuous page is not blank").toBeGreaterThan(MIN_INK);
  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  const onSinglePage = await page.evaluate(() => {
    const host = document.getElementById("tallHost");
    const svg = host.querySelector("svg");
    return { hostW: host.clientWidth, svgW: svg.getBoundingClientRect().width };
  });
  await page.evaluate(() => window.dispatchEvent(new Event("afterprint")));
  await page.emulateMedia({ media: null });
  expect(onSinglePage.svgW / onSinglePage.hostW,
    "on the single continuous page the diagram fills the content column (no full-height empty band)")
    .toBeGreaterThan(0.9);
});
