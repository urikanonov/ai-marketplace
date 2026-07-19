// Deterministic tutorial screenshot capture for the commentable-html plugin (dev-only, not shipped).
// With no arguments it regenerates every tutorial screenshot from four scenes: the community-garden
// walkthrough (garden-*.png), the incident triage board (triage-*.png), a review checklist
// (checklist-*.png), and an editable note (note-*.png), writing into docs/assets.
// Use --check to capture into repo-root tmp/ and compare against the committed docs/assets images
// without writing them. Optional positional overrides capture ONLY the scene named by the prefix
// (default "garden") from any example:
//   node capture_tutorial.mjs [--check] [example.html] [outDir] [prefix]
// Defaults: example = pkg/.../examples/report-community-garden.html, outDir = pkg/.../docs/assets,
// prefix = "garden". From dev/, run `npm run shots` or `npm run shots:check`.
import { chromium } from "@playwright/test";
import path from "path";
import fs from "fs";
import { fileURLToPath, pathToFileURL } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
// The tutorial example and screenshots live at the plugin top level (not shipped, not in the zip).
const PLUGIN = path.resolve(HERE, "..", "..");
const REPO = path.resolve(HERE, "..", "..", "..", "..");
const argv = process.argv.slice(2);
const printPaths = argv.includes("--print-paths");
const checkMode = argv.includes("--check");
const knownFlags = new Set(["--print-paths", "--check"]);
const unknownFlag = argv.find((a) => a.startsWith("--") && !knownFlags.has(a));
if (unknownFlag) {
  console.error("capture_tutorial: unknown option:", unknownFlag);
  process.exit(2);
}
const positional = argv.filter((a) => !a.startsWith("--"));
const DEFAULT_GARDEN = path.join(PLUGIN, "examples", "report-community-garden.html");
const DEFAULT_TRIAGE = path.join(PLUGIN, "examples", "report-triage.html");
const DEFAULT_CHECKLIST = path.join(PLUGIN, "examples", "report-checklist.html");
const DEFAULT_NOTES = path.join(PLUGIN, "examples", "report-notes.html");
const DEFAULT_OUT = path.join(PLUGIN, "docs", "assets");
const htmlArg = positional[0] || DEFAULT_GARDEN;
const outDir = positional[1] || DEFAULT_OUT;
const prefix = path.basename(positional[2] || "garden");
// The community-garden walkthrough shots (docs/TUTORIAL.md embeds them as garden-*.png).
const GARDEN_SHOTS = [
  "01-top-light", "02-kql", "03-chart", "04-diff", "05-composer",
  "06-comment-saved", "07-help", "08-top-dark", "09-copyall",
  "10-review-badge", "11-side-toc", "12-export-menu", "13-comment-search",
];
// Checklists, notes, and the incident triage board render in their own example reports, so each
// gets a small scene of its own (checklist-*.png, note-*.png, triage-*.png).
const CHECKLIST_SHOTS = ["01-checklist"];
const NOTE_SHOTS = ["01-note"];
const TRIAGE_SHOTS = ["01-board"];
// Single source of truth for the scene set and each scene's shot names, used by BOTH the default
// multi-scene run (buildScenes) and the --print-paths registry, so the drift-guard test cannot pass
// while a scene has been dropped from SCENE_ORDER.
const SCENE_SHOTS = { garden: GARDEN_SHOTS, triage: TRIAGE_SHOTS, checklist: CHECKLIST_SHOTS, note: NOTE_SHOTS };
const SCENE_ORDER = ["garden", "triage", "checklist", "note"];
const PNG_QUANTIZE_STEP = 64;
const PNG_DOWNSAMPLE = 2;
const PIXEL_CHANNEL_TOLERANCE = 96;
const MAX_PIXEL_DIFF_RATIO = 0.2;
const MAX_DIMENSION_DELTA = 2;
const ELEMENT_SHOT_TOP = 24;

if (printPaths) {
  // Emit the authoritative scene -> shot-names registry, derived from SCENE_ORDER so the drift-guard
  // test consumes exactly the scene set the default run captures (dropping a scene from SCENE_ORDER
  // drops it here too, failing the test) instead of re-declaring the shot lists.
  const scenes = {};
  for (const key of SCENE_ORDER) scenes[key] = SCENE_SHOTS[key];
  console.log(JSON.stringify({ example: htmlArg, outDir, prefix, check: checkMode, scenes }));
  process.exit(0);
}

function sceneUrl(scene) { return pathToFileURL(path.resolve(scene.example)).href; }

function shotPath(dir, pfx, name) { return path.join(dir, `${pfx}-${name}.png`); }
function screenshotOptions(extra = {}) { return { animations: "disabled", caret: "hide", ...extra }; }

async function settlePaint(page) {
  await page.evaluate(async () => {
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
}

async function waitForStableElement(locator, frames = 3) {
  await locator.evaluate(async (el, wantedFrames) => {
    const snapshot = () => {
      const rect = el.getBoundingClientRect();
      return [
        Math.round(rect.x * 100) / 100,
        Math.round(rect.y * 100) / 100,
        Math.round(rect.width * 100) / 100,
        Math.round(rect.height * 100) / 100,
        el.scrollWidth,
        el.scrollHeight,
        document.documentElement.scrollWidth,
        document.documentElement.scrollHeight,
      ].join("|");
    };
    let previous = snapshot();
    let stable = 0;
    const deadline = performance.now() + 5000;
    while (stable < wantedFrames) {
      await new Promise((resolve) => requestAnimationFrame(resolve));
      const next = snapshot();
      stable = next === previous ? stable + 1 : 0;
      previous = next;
      if (performance.now() > deadline) throw new Error("element layout did not settle");
    }
  }, frames);
}

async function scrollLocatorToTop(locator, topMargin) {
  await locator.evaluate(async (el, margin) => {
    const wanted = Math.max(0, Math.round(window.scrollY + el.getBoundingClientRect().top - margin));
    window.scrollTo(0, wanted);
    const deadline = performance.now() + 5000;
    let stable = 0;
    let previous = "";
    while (stable < 3) {
      await new Promise((resolve) => requestAnimationFrame(resolve));
      const rect = el.getBoundingClientRect();
      const current = [
        Math.round(window.scrollY * 100) / 100,
        Math.round(rect.top * 100) / 100,
        Math.round(rect.left * 100) / 100,
      ].join("|");
      stable = current === previous && Math.abs(window.scrollY - wanted) < 1 ? stable + 1 : 0;
      previous = current;
      if (performance.now() > deadline) throw new Error("scroll did not settle");
    }
  }, topMargin);
}

async function waitForStableLayout(page, frames = 2) {
  await page.evaluate(async (wantedFrames) => {
    const snapshot = () => {
      const root = document.documentElement;
      const body = document.body;
      return [
        root.scrollWidth,
        root.scrollHeight,
        body ? body.scrollWidth : 0,
        body ? body.scrollHeight : 0,
        window.scrollX,
        window.scrollY,
        document.querySelectorAll("pre.mermaid[data-processed='true'] svg, div.mermaid[data-processed='true'] svg").length,
        document.querySelectorAll("figure.chart canvas, canvas.cmh-chart").length,
        document.querySelectorAll(".cm-composer, .cm-help-overlay, #toast.show, mark.cm-hl, .cmh-dl-hl").length,
      ].join("|");
    };
    let previous = snapshot();
    let stable = 0;
    const deadline = performance.now() + 3000;
    while (stable < wantedFrames) {
      await new Promise((resolve) => requestAnimationFrame(resolve));
      const next = snapshot();
      stable = next === previous ? stable + 1 : 0;
      previous = next;
      if (performance.now() > deadline) throw new Error("page layout did not settle");
    }
  }, frames);
}

async function waitForFonts(page) {
  await page.evaluate(async () => {
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
  });
}

async function waitForMermaid(page) {
  await page.waitForFunction(() => {
    const hosts = Array.from(document.querySelectorAll("pre.mermaid, div.mermaid"));
    return hosts.every((host) => {
      const svg = host.querySelector("svg");
      return !host.textContent.trim() || (host.dataset.processed === "true" && svg && svg.querySelector("g, path, rect, text, circle, polygon, foreignObject"));
    });
  }, null, { timeout: 15000 });
}

async function routeVendoredMermaid(context) {
  const dist = path.resolve(HERE, "..", "node_modules", "mermaid", "dist");
  await context.route("https://cdn.jsdelivr.net/npm/mermaid@11.16.0/dist/**", async (route) => {
    const requestPath = new URL(route.request().url()).pathname;
    const relative = decodeURIComponent(requestPath.replace(/^.*\/dist\//, "")).replace(/\//g, path.sep);
    const fileName = path.resolve(dist, relative);
    if (fileName.startsWith(dist + path.sep) && fs.existsSync(fileName)) {
      await route.fulfill({ path: fileName, contentType: "application/javascript" });
      return;
    }
    // Fail closed: if the vendored file is missing, abort rather than reach the network, so the
    // capture never silently depends on CDN reachability (it must stay hermetic and deterministic).
    await route.abort();
  });
}

async function expectNoComposer(page) {
  await page.locator(".cm-composer").waitFor({ state: "hidden", timeout: 5000 }).catch(() => {});
}

function roundedClip(box, size, top = Math.floor(box.y)) {
  return {
    x: Math.floor(box.x),
    y: top,
    width: Math.max(1, size.width),
    height: Math.max(1, size.height),
  };
}

// Save the raw, full-resolution screenshot. The committed tutorial images must stay crisp and
// true-color for the published tutorial, so the cross-platform determinism normalization (downsample
// plus color quantize) is applied only when comparing images (see imagesMatch), never to disk.
async function writeScreenshot(page, pathName, extra = {}) {
  const buffer = await page.screenshot(screenshotOptions(extra));
  fs.writeFileSync(pathName, buffer);
}

async function screenshotLocator(page, locator, pathName) {
  if (!await locator.count()) return;
  await locator.first().waitFor({ state: "visible", timeout: 10000 });
  await scrollLocatorToTop(locator, ELEMENT_SHOT_TOP);
  await page.mouse.move(1, 1);
  await settlePaint(page);
  await waitForStableElement(locator);
  const box = await locator.boundingBox();
  if (!box) return;
  const size = await locator.evaluate((el) => ({ width: el.offsetWidth, height: el.offsetHeight }));
  await writeScreenshot(page, pathName, { clip: roundedClip(box, size, ELEMENT_SHOT_TOP) });
}

async function ready(page) {
  await page.waitForFunction(() => window.__commentableHtmlReady === true, null, { timeout: 15000 });
  await waitForFonts(page);
  await waitForMermaid(page);
  await waitForStableLayout(page);
}

async function freezeMotion(page) {
  await page.addStyleTag({ content:
    "html,body{scroll-behavior:auto !important;}"
    + "*,*::before,*::after{animation-duration:0s !important;animation-delay:0s !important;"
    + "transition-duration:0s !important;transition-delay:0s !important;caret-color:transparent !important;}"
    + "html,body,#commentRoot,.cm-sidebar,button,input,textarea{font-family:Arial,sans-serif !important;}"
    + "pre,code,kbd,samp,.cmh-code-wrap,.cmh-diff-view{font-family:Consolas,'Courier New',monospace !important;}"
  }).catch((e) => console.warn("capture_tutorial: freezeMotion blocked (degraded determinism):", e.message));
}

async function freezeClock(context) {
  await context.addInitScript(() => {
    const OriginalDate = Date;
    const FIXED = OriginalDate.parse("2024-01-01T12:00:00.000Z");
    function FrozenDate(...args) {
      return args.length === 0 ? new OriginalDate(FIXED) : new OriginalDate(...args);
    }
    FrozenDate.now = () => FIXED;
    FrozenDate.parse = OriginalDate.parse.bind(OriginalDate);
    FrozenDate.UTC = OriginalDate.UTC.bind(OriginalDate);
    FrozenDate.prototype = OriginalDate.prototype;
    window.Date = FrozenDate;
  });
}

async function freezeRandom(context) {
  await context.addInitScript(() => { Math.random = () => 0.123456789; });
}

async function stabilizeCharts(page) {
  await page.waitForFunction(() => {
    const canvases = Array.from(document.querySelectorAll("figure.chart canvas, canvas.cmh-chart"));
    if (!canvases.length) return true;
    const Chart = window.Chart;
    if (!Chart || !Chart.instances) return false;
    const charts = Object.values(Chart.instances).filter(Boolean);
    return canvases.every((canvas) => charts.some((chart) => chart.canvas === canvas));
  }, null, { timeout: 15000 }).catch(() => {});
  await page.evaluate(() => {
    const Chart = window.Chart;
    if (!Chart || !Chart.instances) return;
    for (const chart of Object.values(Chart.instances)) {
      if (!chart) continue;
      chart.stop();
      if (chart.options) {
        chart.options.animation = false;
        chart.options.animations = {};
        chart.options.transitions = {};
      }
      chart.update("none");
    }
  }).catch(() => {});
  await settlePaint(page);
  await waitForStableLayout(page);
}

async function captureScene(scene, targetDir) {
  fs.mkdirSync(targetDir, { recursive: true });
  const browser = await chromium.launch({
    args: [
      "--disable-gpu",
      "--disable-lcd-text",
      "--disable-font-subpixel-positioning",
      "--font-render-hinting=none",
    ],
  });
  let context;
  try {
    context = await browser.newContext({
      viewport: { width: 1320, height: 900 },
      deviceScaleFactor: 2,
      colorScheme: "light",
      locale: "en-US",
      timezoneId: "UTC",
      reducedMotion: "reduce",
      // Only clipboard-WRITE is needed (the Copy-all shot writes to the clipboard); the capture never
      // READS it, so do not grant clipboard-read (narrower exposure when run on an arbitrary example).
      permissions: ["clipboard-write"],
    });
    await freezeClock(context);
    await freezeRandom(context);
    // Fail closed: block every remote fetch so capture is hermetic and deterministic. The vendored
    // mermaid route is registered AFTER this (Playwright matches the most-recently-added route
    // first), so mermaid is still served from node_modules while every other egress - e.g. the
    // triage example's SRI-pinned Chart.js CDN, which the board shot does not need - is aborted.
    await context.route(/^https?:\/\//, (route) => route.abort());
    await routeVendoredMermaid(context);
    const page = await context.newPage();
    await page.goto(sceneUrl(scene));
    await ready(page);
    await freezeMotion(page);
    await stabilizeCharts(page);
    await settlePaint(page);

    await scene.capture({ page, targetDir, scene });
  } finally {
    if (context) await context.close().catch(() => {});
    await browser.close();
  }
}

// Capture a region of a FIXED element (the side TOC, the sidebar, the export menu) by clipping its
// current viewport box - screenshotLocator's scroll-to-top math assumes an in-flow element, so it
// mis-clips a position:fixed one. The clip is clamped inside the viewport.
async function screenshotFixedRegion(page, locator, pathName, pad = 8) {
  const target = locator.first();
  if (!await target.count()) return;
  await target.waitFor({ state: "visible", timeout: 10000 });
  await page.mouse.move(1, 1);
  await settlePaint(page);
  await waitForStableElement(target);
  const box = await target.boundingBox();
  if (!box) return;
  const view = page.viewportSize() || { width: 1320, height: 900 };
  const x = Math.max(0, Math.floor(box.x) - pad);
  const y = Math.max(0, Math.floor(box.y) - pad);
  const width = Math.max(1, Math.min(Math.ceil(box.width) + pad * 2, view.width - x));
  const height = Math.max(1, Math.min(Math.ceil(box.height) + pad * 2, view.height - y));
  await writeScreenshot(page, pathName, { clip: { x, y, width, height } });
}

// Select a block and save a comment on it via the same composer flow the tutorial demonstrates.
async function addComment(page, locator, text) {
  const el = locator.first();
  if (!await el.count()) return false;
  await el.scrollIntoViewIfNeeded();
  await el.evaluate((node) => {
    const r = document.createRange();
    r.selectNodeContents(node);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
    node.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  });
  const addBtn = page.locator(".cm-add-comment, [data-cm-add], button:has-text('Add comment')").first();
  if (!await addBtn.count()) return false;
  await addBtn.waitFor({ state: "visible", timeout: 5000 });
  await addBtn.click();
  const composer = page.locator(".cm-composer").first();
  await composer.waitFor({ state: "visible", timeout: 5000 });
  await composer.locator("textarea").first().fill(text);
  await composer.locator("button:has-text('Comment'), button:has-text('Save'), button.cm-save").first().click();
  await expectNoComposer(page);
  await waitForStableLayout(page);
  return true;
}

async function captureGarden(ctx) {
  const { page, targetDir, scene } = ctx;
  const P = scene.prefix;

  await writeScreenshot(page, shotPath(targetDir, P, "01-top-light"),
    { clip: { x: 0, y: 0, width: 1320, height: 900 } });
  await page.addStyleTag({
    content: ".cm-toolbar{visibility:hidden !important;}"
      + ".cm-code-lang,.cm-code-copy{box-shadow:none !important;"
      + "backdrop-filter:none !important;-webkit-backdrop-filter:none !important;}"
      + "#diffAddBtn{display:none !important;}",
  });

  await screenshotLocator(page, page.locator("figure.cmh-kql").first(),
    shotPath(targetDir, P, "02-kql"));

  const chart = page.locator("figure.chart").first();
  if (await chart.count()) {
    await chart.waitFor({ state: "visible", timeout: 10000 });
    await scrollLocatorToTop(chart, ELEMENT_SHOT_TOP);
    await page.mouse.move(1, 1);
    await stabilizeCharts(page);
    await settlePaint(page);
    await waitForStableElement(chart);
    const box = await chart.boundingBox();
    if (box) {
      const size = await chart.evaluate((el) => ({ width: el.offsetWidth, height: el.offsetHeight }));
      await writeScreenshot(page, shotPath(targetDir, P, "03-chart"),
        { clip: roundedClip(box, size, ELEMENT_SHOT_TOP) });
    }
  }

  await screenshotLocator(page, page.locator(".cmh-diff-host, pre.cmh-diff").first(),
    shotPath(targetDir, P, "04-diff"));

  // Section review tracking: mark a below-the-fold heading reviewed so the top viewport shots stay
  // unchanged, then shoot that heading's green Reviewed badge. Doing it before the side-TOC shot
  // also lights the section's status dot there.
  await page.evaluate(() => window.scrollTo(0, 0));
  await waitForStableLayout(page);
  const reviewedId = await page.evaluate(() => {
    const root = document.getElementById("commentRoot") || document.body;
    const headings = Array.from(root.querySelectorAll("h2[id], h3[id]"));
    const target = headings.find((h) => h.getBoundingClientRect().top > window.innerHeight)
      || headings[headings.length - 1];
    if (!target) return null;
    const badge = target.querySelector(":scope > .cmh-review-badge");
    if (badge) badge.click();
    return target.id;
  });
  if (reviewedId) {
    // No .catch here: if the badge never reaches the reviewed state, fail the capture loudly rather
    // than silently baking an unreviewed shot that then passes --check and drift checks forever.
    await page.waitForFunction((id) => window.__cmhReview
      && window.__cmhReview.stateOf(id) === "reviewed", reviewedId, { timeout: 5000 });
    await screenshotLocator(page, page.locator('[id="' + reviewedId + '"]').first(),
      shotPath(targetDir, P, "10-review-badge"));
  }

  // Side table-of-contents nav renders only at wide widths; widen the viewport for this one shot.
  // Its element clip covers doc-search, the review-status filter, section fold/expand, and go
  // top/bottom together.
  await page.setViewportSize({ width: 1500, height: 900 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await waitForStableLayout(page);
  await settlePaint(page);
  await screenshotFixedRegion(page, page.locator("#cmSideToc, .cm-side-toc"),
    shotPath(targetDir, P, "11-side-toc"));
  await page.setViewportSize({ width: 1320, height: 900 });
  await waitForStableLayout(page);

  await page.evaluate(() => window.scrollTo(0, 0));
  const para = page.locator("#commentRoot p").first();
  await para.scrollIntoViewIfNeeded();
  await para.evaluate((el) => {
    const r = document.createRange();
    r.selectNodeContents(el);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
    el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  });
  const addBtn = page.locator(".cm-add-comment, [data-cm-add], button:has-text('Add comment')").first();
  if (await addBtn.count()) {
    await addBtn.waitFor({ state: "visible", timeout: 5000 });
    await addBtn.click();
    const composer = page.locator(".cm-composer").first();
    await composer.waitFor({ state: "visible", timeout: 5000 });
    await waitForStableLayout(page);
    await writeScreenshot(page, shotPath(targetDir, P, "05-composer"),
      { clip: { x: 0, y: 0, width: 1320, height: 900 } });
    await composer.locator("textarea").first().fill("Does this section read clearly? Consider adding one more example.");
    await composer.locator("button:has-text('Comment'), button:has-text('Save'), button.cm-save").first().click();
    await page.locator("#commentRoot mark.cm-hl").first().waitFor({ state: "visible", timeout: 5000 });
    await expectNoComposer(page);
    await waitForStableLayout(page);
  }

  await writeScreenshot(page, shotPath(targetDir, P, "06-comment-saved"),
    { clip: { x: 0, y: 0, width: 1320, height: 900 } });

  await page.evaluate(() => { window.prompt = () => ""; });
  const copyBtn = page.locator("#btnCopyAll");
  if (await copyBtn.count()) {
    await copyBtn.click().catch(() => {});
    await page.locator("#toast.show").waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
    await waitForStableLayout(page);
    await writeScreenshot(page, shotPath(targetDir, P, "09-copyall"),
      { clip: { x: 0, y: 0, width: 1320, height: 900 } });
  }

  await page.evaluate(() => {
    const b = document.getElementById("btnHelp");
    if (b && b.offsetParent !== null) { b.click(); return; }
    const m = document.getElementById("btnToolbarMenu");
    if (m) m.click();
    const t = document.getElementById("btnHelpTop");
    if (t) t.click();
  });
  await page.locator(".cm-help-overlay .cm-help").waitFor({ state: "visible", timeout: 5000 });
  // Capture the Help dialog cleanly (issue #462): the .cm-help-overlay backdrop dims and blurs the
  // whole page behind the dialog, which reads as faded and blurry. Neutralize the backdrop dim/blur
  // and clip to the dialog bounds instead of shooting the full dimmed page.
  await page.addStyleTag({ content: ".cm-help-overlay{background:transparent !important;"
    + "backdrop-filter:none !important;-webkit-backdrop-filter:none !important;}" });
  await waitForStableLayout(page);
  await screenshotFixedRegion(page, page.locator(".cm-help-overlay .cm-help"),
    shotPath(targetDir, P, "07-help"), 0);

  await page.keyboard.press("Escape").catch(() => {});
  await page.evaluate(() => {
    const menu = document.getElementById("toolbarMenu");
    if (menu) menu.hidden = true;
    const menuButton = document.getElementById("btnToolbarMenu");
    if (menuButton) menuButton.setAttribute("aria-expanded", "false");
    const toastEl = document.getElementById("toast");
    if (toastEl) toastEl.classList.remove("show");
    document.querySelectorAll(".cm-tooltip").forEach((el) => el.remove());
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    document.documentElement.setAttribute("data-theme", "dark");
    window.scrollTo(0, 0);
  });
  await page.mouse.move(1, 1);
  await page.locator(".cm-help-overlay").waitFor({ state: "hidden", timeout: 5000 }).catch(() => {});
  await waitForStableLayout(page);
  await writeScreenshot(page, shotPath(targetDir, P, "08-top-dark"),
    { clip: { x: 0, y: 0, width: 1320, height: 900 } });

  // Comment search + sort and the export menu need saved comments and the open sidebar in light
  // theme, so capture them last: restore the theme, make sure the panel is open, and add two more
  // comments so a query filters the list to a subset.
  await page.evaluate(() => {
    document.documentElement.setAttribute("data-theme", "light");
    const menu = document.getElementById("sidebarExportMenu");
    if (menu) menu.hidden = true;
    if (!document.body.classList.contains("sidebar-open")) {
      const t = document.getElementById("btnToggleSidebar");
      if (t) t.click();
    }
    window.scrollTo(0, 0);
  });
  await waitForStableLayout(page);
  // The comment-search shot needs these two comments (plus the earlier one) so a query filters to a
  // subset; treat seeding as a required precondition and fail loudly rather than bake a shot of an
  // empty/wrong list that then passes --check forever.
  if (!await addComment(page, page.locator("#commentRoot p").nth(2),
    "Frost risk: call out the last spring frost date near here.")) {
    throw new Error("capture: could not seed the first search/sort comment (garden-13-comment-search)");
  }
  if (!await addComment(page, page.locator("#commentRoot p").nth(3),
    "Can we track the compost delivery schedule too?")) {
    throw new Error("capture: could not seed the second search/sort comment (garden-13-comment-search)");
  }

  // Type a query that filters the list; the sidebar shot shows the search box, the shown/total
  // count, and the sort controls together.
  await page.evaluate(() => {
    const input = document.getElementById("cmSearchInput");
    if (input) {
      input.value = "frost";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  });
  await page.mouse.move(1, 1);
  await waitForStableLayout(page);
  // Clip the sidebar down to the bottom of its populated content (search controls plus the visible
  // comment cards, plus a little padding) so the shot is tight instead of padded out with the empty
  // rest of the full-height fixed panel. Fail loudly if the panel is missing or the search matched no
  // visible card, rather than silently writing a degenerate sliver or skipping the shot.
  const searchClip = await page.evaluate(() => {
    const sidebar = document.getElementById("sidebar");
    if (!sidebar) return { error: "#sidebar is missing" };
    const sb = sidebar.getBoundingClientRect();
    const cards = Array.from(sidebar.querySelectorAll(".cm-card"))
      .filter((card) => card.getBoundingClientRect().height > 0);
    if (!cards.length) return { error: "no visible .cm-card (the search query matched nothing)" };
    let contentBottom = sb.top;
    const searchInput = document.getElementById("cmSearchInput");
    if (searchInput) contentBottom = Math.max(contentBottom, searchInput.getBoundingClientRect().bottom);
    for (const card of cards) contentBottom = Math.max(contentBottom, card.getBoundingClientRect().bottom);
    const pad = 16;
    const height = Math.min(sb.height, Math.max(1, contentBottom - sb.top + pad));
    return {
      clip: {
        x: Math.max(0, Math.floor(sb.left)),
        y: Math.max(0, Math.floor(sb.top)),
        width: Math.ceil(sb.width),
        height: Math.ceil(height),
      },
    };
  });
  if (searchClip.error) {
    throw new Error("capture: cannot capture garden-13-comment-search: " + searchClip.error);
  }
  await writeScreenshot(page, shotPath(targetDir, P, "13-comment-search"), { clip: searchClip.clip });

  // Clear the query, then open and shoot the sidebar export menu.
  await page.evaluate(() => {
    const input = document.getElementById("cmSearchInput");
    if (input) {
      input.value = "";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    const btn = document.getElementById("btnSidebarExportMenu");
    if (btn) btn.click();
  });
  await page.locator("#sidebarExportMenu").first().waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
  await page.mouse.move(1, 1);
  await waitForStableLayout(page);
  await screenshotFixedRegion(page, page.locator("#sidebarExportMenu"),
    shotPath(targetDir, P, "12-export-menu"), 0);
}

async function captureChecklist(ctx) {
  const { page, targetDir, scene } = ctx;
  const P = scene.prefix;
  await page.addStyleTag({ content: ".cm-toolbar{visibility:hidden !important;}#diffAddBtn{display:none !important;}" });
  await page.mouse.move(1, 1);
  await settlePaint(page);
  await screenshotLocator(page, page.locator(".cmh-checklist").first(),
    shotPath(targetDir, P, "01-checklist"));
}

async function captureNote(ctx) {
  const { page, targetDir, scene } = ctx;
  const P = scene.prefix;
  await page.addStyleTag({ content: ".cm-toolbar{visibility:hidden !important;}#diffAddBtn{display:none !important;}" });
  await page.mouse.move(1, 1);
  await settlePaint(page);
  await screenshotLocator(page, page.locator(".cmh-note").first(),
    shotPath(targetDir, P, "01-note"));
}

async function captureBoard(ctx) {
  const { page, targetDir, scene } = ctx;
  const P = scene.prefix;
  await page.addStyleTag({ content: ".cm-toolbar{visibility:hidden !important;}#diffAddBtn{display:none !important;}" });
  await page.mouse.move(1, 1);
  await settlePaint(page);
  await screenshotLocator(page,
    page.locator(".triage-board-demo, [data-cm-widget='incident-triage-board']").first(),
    shotPath(targetDir, P, "01-board"));
}

// Each scene renders a feature in the example that actually contains it. The default no-argument run
// regenerates every scene into docs/assets; a positional override runs one scene chosen by prefix.
// Shot lists come from SCENE_SHOTS (the single source of truth shared with --print-paths).
const SCENE_DEFS = {
  garden: { example: DEFAULT_GARDEN, shots: SCENE_SHOTS.garden, capture: captureGarden },
  triage: { example: DEFAULT_TRIAGE, shots: SCENE_SHOTS.triage, capture: captureBoard },
  checklist: { example: DEFAULT_CHECKLIST, shots: SCENE_SHOTS.checklist, capture: captureChecklist },
  note: { example: DEFAULT_NOTES, shots: SCENE_SHOTS.note, capture: captureNote },
};

function buildScenes() {
  if (positional.length > 0) {
    if (positional.length > 3) {
      console.error("capture_tutorial: too many positional args (expected [example] [outDir] [prefix]):", positional.join(" "));
      process.exit(2);
    }
    // A 3rd positional arg names the scene; reject an unknown one instead of silently capturing the
    // wrong scene's shots. Own-property lookup so "constructor"/"__proto__" cannot resolve to an
    // inherited Object member (and the 2-arg default keeps prefix "garden", a real own key).
    const known = Object.prototype.hasOwnProperty.call(SCENE_DEFS, prefix);
    if (positional.length >= 3 && !known) {
      console.error("capture_tutorial: unknown scene prefix:", prefix, "(known:", SCENE_ORDER.join(", ") + ")");
      process.exit(2);
    }
    const def = known ? SCENE_DEFS[prefix] : SCENE_DEFS.garden;
    return [{ prefix, example: htmlArg, outDir, shots: def.shots, capture: def.capture }];
  }
  return SCENE_ORDER.map((key) => ({
    prefix: key,
    example: SCENE_DEFS[key].example,
    outDir: DEFAULT_OUT,
    shots: SCENE_DEFS[key].shots,
    capture: SCENE_DEFS[key].capture,
  }));
}

async function imagesMatch(comparePage, expected, actual) {
  if (!fs.existsSync(expected) || !fs.existsSync(actual)) return false;
  const ratio = await comparePage.evaluate(async ({ expectedBase64, actualBase64, tolerance, maxDimensionDelta, scale, step }) => {
    async function decode(base64) {
      const img = new Image();
      img.src = "data:image/png;base64," + base64;
      await img.decode();
      return img;
    }
    // Normalize BOTH images the same way before diffing: downsample then upsample nearest (to erase
    // the sub-pixel font antialiasing that differs across platforms) and quantize colors. This keeps
    // the --check comparison deterministic across OSes WITHOUT degrading the committed PNGs, which
    // are written to disk raw and crisp.
    function normalize(img, width, height) {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      if (scale > 1) {
        const small = document.createElement("canvas");
        small.width = Math.max(1, Math.ceil(width / scale));
        small.height = Math.max(1, Math.ceil(height / scale));
        const sctx = small.getContext("2d");
        sctx.imageSmoothingEnabled = true;
        sctx.drawImage(canvas, 0, 0, small.width, small.height);
        ctx.clearRect(0, 0, width, height);
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(small, 0, 0, width, height);
      }
      const image = ctx.getImageData(0, 0, width, height);
      const d = image.data;
      for (let i = 0; i < d.length; i += 4) {
        d[i] = Math.round(d[i] / step) * step;
        d[i + 1] = Math.round(d[i + 1] / step) * step;
        d[i + 2] = Math.round(d[i + 2] / step) * step;
        if (d[i] === d[i + 1] && d[i + 1] === d[i + 2] && d[i] >= 192) {
          d[i] = 255;
          d[i + 1] = 255;
          d[i + 2] = 255;
        }
      }
      return d;
    }
    try {
      const expectedImg = await decode(expectedBase64);
      const actualImg = await decode(actualBase64);
      const widthDelta = Math.abs(expectedImg.naturalWidth - actualImg.naturalWidth);
      const heightDelta = Math.abs(expectedImg.naturalHeight - actualImg.naturalHeight);
      if (widthDelta > maxDimensionDelta || heightDelta > maxDimensionDelta) return 1;
      const width = Math.min(expectedImg.naturalWidth, actualImg.naturalWidth);
      const height = Math.min(expectedImg.naturalHeight, actualImg.naturalHeight);
      const expectedData = normalize(expectedImg, width, height);
      const actualData = normalize(actualImg, width, height);
      let different = 0;
      const total = width * height;
      for (let i = 0; i < expectedData.length; i += 4) {
        const maxChannelDelta = Math.max(
          Math.abs(expectedData[i] - actualData[i]),
          Math.abs(expectedData[i + 1] - actualData[i + 1]),
          Math.abs(expectedData[i + 2] - actualData[i + 2]),
          Math.abs(expectedData[i + 3] - actualData[i + 3]),
        );
        if (maxChannelDelta > tolerance) {
          different += 1;
        }
      }
      return different / total;
    } catch (e) {
      return 1;
    }
  }, {
    expectedBase64: fs.readFileSync(expected).toString("base64"),
    actualBase64: fs.readFileSync(actual).toString("base64"),
    tolerance: PIXEL_CHANNEL_TOLERANCE,
    maxDimensionDelta: MAX_DIMENSION_DELTA,
    scale: PNG_DOWNSAMPLE,
    step: PNG_QUANTIZE_STEP,
  });
  return ratio <= MAX_PIXEL_DIFF_RATIO;
}

async function checkScreenshots(scenes) {
  const checkRoot = path.join(REPO, "tmp", "tutorial-shots-check", String(process.pid));
  fs.rmSync(checkRoot, { recursive: true, force: true });
  let stale = false;
  try {
    const problems = [];
    const compareBrowser = await chromium.launch();
    const comparePage = await compareBrowser.newPage();
    try {
      for (const scene of scenes) {
        const checkDir = path.join(checkRoot, scene.prefix);
        await captureScene(scene, checkDir);
        for (const name of scene.shots) {
          const file = `${scene.prefix}-${name}.png`;
          const expected = path.join(scene.outDir, file);
          const actual = path.join(checkDir, file);
          if (!fs.existsSync(expected)) problems.push(`${file} missing`);
          else if (!await imagesMatch(comparePage, expected, actual)) problems.push(`${file} differs`);
        }
      }
    } finally {
      await comparePage.close().catch(() => {});
      await compareBrowser.close();
    }
    if (problems.length) {
      stale = true;
      for (const problem of problems) console.error(problem);
      console.error("capture_tutorial: tutorial screenshots are stale. Run npm run shots from plugins/commentable-html/dev.");
      console.error("capture_tutorial: fresh screenshots were kept in", checkRoot);
      return 1;
    }
    console.log("tutorial screenshots are in sync");
    return 0;
  } finally {
    if (!stale) fs.rmSync(checkRoot, { recursive: true, force: true });
  }
}

async function regenerateScreenshots(scenes) {
  const freshRoot = path.join(REPO, "tmp", "tutorial-shots-generate", String(process.pid));
  fs.rmSync(freshRoot, { recursive: true, force: true });
  try {
    let compareBrowser = null;
    let comparePage = null;
    try {
      for (const scene of scenes) {
        const freshDir = path.join(freshRoot, scene.prefix);
        await captureScene(scene, freshDir);
        fs.mkdirSync(scene.outDir, { recursive: true });
        let written = 0;
        for (const name of scene.shots) {
          const file = `${scene.prefix}-${name}.png`;
          const target = path.join(scene.outDir, file);
          const fresh = path.join(freshDir, file);
          if (!fs.existsSync(fresh)) {
            console.error(`${scene.prefix} scene did not capture ${file} (a shot's target element may be missing)`);
            process.exitCode = 1;
            continue;
          }
          if (fs.existsSync(target) && !comparePage) {
            compareBrowser = await chromium.launch();
            comparePage = await compareBrowser.newPage();
          }
          if (!fs.existsSync(target) || !await imagesMatch(comparePage, target, fresh)) {
            fs.copyFileSync(fresh, target);
            written += 1;
          }
        }
        console.log("captured shots with prefix", scene.prefix, "->", scene.outDir, `(${written} updated)`);
      }
    } finally {
      if (comparePage) await comparePage.close().catch(() => {});
      if (compareBrowser) await compareBrowser.close();
    }
    // A per-shot capture miss set process.exitCode above; surface it as a clear final failure so a
    // reader does not mistake the per-scene "captured shots ..." trailer for full success.
    if (process.exitCode === 1) {
      console.error("capture_tutorial: one or more shots were not captured (see errors above); the committed images may be incomplete.");
    }
  } finally {
    fs.rmSync(freshRoot, { recursive: true, force: true });
  }
}

const run = async () => {
  const scenes = buildScenes();
  for (const scene of scenes) {
    if (!fs.existsSync(scene.example)) {
      console.error("capture_tutorial: example not found:", scene.example);
      process.exit(2);
    }
  }
  if (checkMode) {
    process.exitCode = await checkScreenshots(scenes);
    return;
  }
  await regenerateScreenshots(scenes);
};

run().catch((e) => { console.error(e); process.exit(1); });
