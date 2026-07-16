// Deterministic tutorial screenshot capture for the commentable-html plugin (dev-only, not shipped).
// With no arguments it regenerates every tutorial screenshot (the garden-*.png images that
// docs/TUTORIAL.md embeds) from the shipped community-garden example into docs/assets. Use --check
// to capture into repo-root tmp/ and compare against the committed docs/assets images without
// writing them. Optional positional overrides let it capture any example:
//   node capture_tutorial.mjs [--check] [example.html] [outDir] [prefix]
// Defaults: example = pkg/.../examples/report-community-garden.html, outDir = pkg/.../docs/assets,
// prefix = "garden". From dev/, run `npm run shots` or `npm run shots:check`.
import { chromium } from "@playwright/test";
import path from "path";
import fs from "fs";
import { fileURLToPath, pathToFileURL } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SKILL = path.resolve(HERE, "..", "..", "pkg", "skills", "commentable-html");
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
const htmlArg = positional[0] || path.join(SKILL, "examples", "report-community-garden.html");
const outDir = positional[1] || path.join(SKILL, "docs", "assets");
const prefix = path.basename(positional[2] || "garden");
const SHOTS = [
  "01-top-light", "02-kql", "03-chart", "04-diff", "05-composer",
  "06-comment-saved", "07-help", "08-top-dark", "09-copyall",
];
const PNG_QUANTIZE_STEP = 64;
const PNG_DOWNSAMPLE = 2;
const PIXEL_CHANNEL_TOLERANCE = 96;
const MAX_PIXEL_DIFF_RATIO = 0.2;
const MAX_DIMENSION_DELTA = 2;
const ELEMENT_SHOT_TOP = 24;

if (printPaths) {
  console.log(JSON.stringify({ example: htmlArg, outDir, prefix, check: checkMode }));
  process.exit(0);
}

if (!fs.existsSync(htmlArg)) {
  console.error("capture_tutorial: example not found:", htmlArg);
  process.exit(2);
}
const url = pathToFileURL(path.resolve(htmlArg)).href;

function shotPath(dir, name) { return path.join(dir, `${prefix}-${name}.png`); }
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
    await route.continue();
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

async function writeNormalizedPng(normalizer, buffer, pathName) {
  const png = await normalizer.evaluate(async ({ base64, step, scale }) => {
    const img = new Image();
    img.src = "data:image/png;base64," + base64;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    if (scale > 1) {
      const small = document.createElement("canvas");
      small.width = Math.max(1, Math.ceil(canvas.width / scale));
      small.height = Math.max(1, Math.ceil(canvas.height / scale));
      const sctx = small.getContext("2d");
      sctx.imageSmoothingEnabled = true;
      sctx.drawImage(canvas, 0, 0, small.width, small.height);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(small, 0, 0, canvas.width, canvas.height);
    }
    const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
    for (let i = 0; i < image.data.length; i += 4) {
      image.data[i] = Math.round(image.data[i] / step) * step;
      image.data[i + 1] = Math.round(image.data[i + 1] / step) * step;
      image.data[i + 2] = Math.round(image.data[i + 2] / step) * step;
      if (image.data[i] === image.data[i + 1] && image.data[i + 1] === image.data[i + 2] && image.data[i] >= 192) {
        image.data[i] = 255;
        image.data[i + 1] = 255;
        image.data[i + 2] = 255;
      }
    }
    ctx.putImageData(image, 0, 0);
    return canvas.toDataURL("image/png").split(",", 2)[1];
  }, { base64: buffer.toString("base64"), step: PNG_QUANTIZE_STEP, scale: PNG_DOWNSAMPLE });
  fs.writeFileSync(pathName, Buffer.from(png, "base64"));
}

async function writeScreenshot(page, normalizer, pathName, extra = {}) {
  const buffer = await page.screenshot(screenshotOptions(extra));
  await writeNormalizedPng(normalizer, buffer, pathName);
}

async function screenshotLocator(page, normalizer, locator, pathName) {
  if (!await locator.count()) return;
  await locator.first().waitFor({ state: "visible", timeout: 10000 });
  await scrollLocatorToTop(locator, ELEMENT_SHOT_TOP);
  await page.mouse.move(1, 1);
  await settlePaint(page);
  await waitForStableElement(locator);
  const box = await locator.boundingBox();
  if (!box) return;
  const size = await locator.evaluate((el) => ({ width: el.offsetWidth, height: el.offsetHeight }));
  await writeScreenshot(page, normalizer, pathName, { clip: roundedClip(box, size, ELEMENT_SHOT_TOP) });
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

async function captureAll(targetDir) {
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
      permissions: ["clipboard-read", "clipboard-write"],
    });
    await freezeClock(context);
    await freezeRandom(context);
    await routeVendoredMermaid(context);
    const normalizer = await context.newPage();
    const page = await context.newPage();
    await page.goto(url);
    await ready(page);
    await freezeMotion(page);
    await stabilizeCharts(page);
    await settlePaint(page);

    await writeScreenshot(page, normalizer, shotPath(targetDir, "01-top-light"),
      { clip: { x: 0, y: 0, width: 1320, height: 900 } });
    await page.addStyleTag({
      content: ".cm-toolbar{visibility:hidden !important;}"
        + ".cm-code-lang,.cm-code-copy{box-shadow:none !important;"
        + "backdrop-filter:none !important;-webkit-backdrop-filter:none !important;}"
        + "#diffAddBtn{display:none !important;}",
    });

    await screenshotLocator(page, normalizer, page.locator("figure.cmh-kql").first(),
      shotPath(targetDir, "02-kql"));

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
        await writeScreenshot(page, normalizer, shotPath(targetDir, "03-chart"),
          { clip: roundedClip(box, size, ELEMENT_SHOT_TOP) });
      }
    }

    await screenshotLocator(page, normalizer, page.locator(".cmh-diff-host, pre.cmh-diff").first(),
      shotPath(targetDir, "04-diff"));

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
      await writeScreenshot(page, normalizer, shotPath(targetDir, "05-composer"),
        { clip: { x: 0, y: 0, width: 1320, height: 900 } });
      await composer.locator("textarea").first().fill("Does this section read clearly? Consider adding one more example.");
      await composer.locator("button:has-text('Comment'), button:has-text('Save'), button.cm-save").first().click();
      await page.locator("#commentRoot mark.cm-hl").first().waitFor({ state: "visible", timeout: 5000 });
      await expectNoComposer(page);
      await waitForStableLayout(page);
    }

    await writeScreenshot(page, normalizer, shotPath(targetDir, "06-comment-saved"),
      { clip: { x: 0, y: 0, width: 1320, height: 900 } });

    await page.evaluate(() => { window.prompt = () => ""; });
    const copyBtn = page.locator("#btnCopyAll");
    if (await copyBtn.count()) {
      await copyBtn.click().catch(() => {});
      await page.locator("#toast.show").waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
      await waitForStableLayout(page);
      await writeScreenshot(page, normalizer, shotPath(targetDir, "09-copyall"),
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
    await waitForStableLayout(page);
    await writeScreenshot(page, normalizer, shotPath(targetDir, "07-help"),
      { clip: { x: 0, y: 0, width: 1320, height: 900 } });

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
    await writeScreenshot(page, normalizer, shotPath(targetDir, "08-top-dark"),
      { clip: { x: 0, y: 0, width: 1320, height: 900 } });
  } finally {
    if (context) await context.close().catch(() => {});
    await browser.close();
  }
}

async function imagesMatch(comparePage, expected, actual) {
  if (!fs.existsSync(expected) || !fs.existsSync(actual)) return false;
  const ratio = await comparePage.evaluate(async ({ expectedBase64, actualBase64, tolerance, maxDimensionDelta }) => {
    async function decode(base64) {
      const img = new Image();
      img.src = "data:image/png;base64," + base64;
      await img.decode();
      return img;
    }
    try {
      const expectedImg = await decode(expectedBase64);
      const actualImg = await decode(actualBase64);
      const widthDelta = Math.abs(expectedImg.naturalWidth - actualImg.naturalWidth);
      const heightDelta = Math.abs(expectedImg.naturalHeight - actualImg.naturalHeight);
      if (widthDelta > maxDimensionDelta || heightDelta > maxDimensionDelta) return 1;
      const width = Math.min(expectedImg.naturalWidth, actualImg.naturalWidth);
      const height = Math.min(expectedImg.naturalHeight, actualImg.naturalHeight);
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(expectedImg, 0, 0);
      const expectedData = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(actualImg, 0, 0);
      const actualData = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      let different = 0;
      const total = canvas.width * canvas.height;
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
  });
  return ratio <= MAX_PIXEL_DIFF_RATIO;
}

async function checkScreenshots() {
  const checkDir = path.join(REPO, "tmp", "tutorial-shots-check", String(process.pid));
  fs.rmSync(checkDir, { recursive: true, force: true });
  let stale = false;
  try {
    await captureAll(checkDir);
    const compareBrowser = await chromium.launch();
    const comparePage = await compareBrowser.newPage();
    const problems = [];
    try {
      for (const name of SHOTS) {
        const file = `${prefix}-${name}.png`;
        const expected = path.join(outDir, file);
        const actual = path.join(checkDir, file);
        if (!fs.existsSync(expected)) problems.push(`${file} missing`);
        else if (!await imagesMatch(comparePage, expected, actual)) problems.push(`${file} differs`);
      }
    } finally {
      await comparePage.close().catch(() => {});
      await compareBrowser.close();
    }
    if (problems.length) {
      stale = true;
      for (const problem of problems) console.error(problem);
      console.error("capture_tutorial: tutorial screenshots are stale. Run npm run shots from plugins/commentable-html/dev.");
      console.error("capture_tutorial: fresh screenshots were kept in", checkDir);
      return 1;
    }
    console.log("tutorial screenshots are in sync");
    return 0;
  } finally {
    if (!stale) fs.rmSync(checkDir, { recursive: true, force: true });
  }
}

async function regenerateScreenshots() {
  const freshDir = path.join(REPO, "tmp", "tutorial-shots-generate", String(process.pid));
  fs.rmSync(freshDir, { recursive: true, force: true });
  try {
    await captureAll(freshDir);
    fs.mkdirSync(outDir, { recursive: true });
    let compareBrowser = null;
    let comparePage = null;
    let written = 0;
    try {
      for (const name of SHOTS) {
        const file = `${prefix}-${name}.png`;
        const target = path.join(outDir, file);
        const fresh = path.join(freshDir, file);
        if (fs.existsSync(target) && !comparePage) {
          compareBrowser = await chromium.launch();
          comparePage = await compareBrowser.newPage();
        }
        if (!fs.existsSync(target) || !await imagesMatch(comparePage, target, fresh)) {
          fs.copyFileSync(fresh, target);
          written += 1;
        }
      }
    } finally {
      if (comparePage) await comparePage.close().catch(() => {});
      if (compareBrowser) await compareBrowser.close();
    }
    console.log("captured shots with prefix", prefix, "->", outDir, `(${written} updated)`);
  } finally {
    fs.rmSync(freshDir, { recursive: true, force: true });
  }
}

const run = async () => {
  if (checkMode) {
    process.exitCode = await checkScreenshots();
    return;
  }
  await regenerateScreenshots();
};

run().catch((e) => { console.error(e); process.exit(1); });
