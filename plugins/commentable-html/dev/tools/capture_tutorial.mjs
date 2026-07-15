// Deterministic tutorial screenshot capture for the commentable-html plugin (dev-only, not shipped).
// With no arguments it regenerates every tutorial screenshot (the garden-*.png images that
// docs/TUTORIAL.md embeds) from the shipped community-garden example into docs/assets. Optional
// positional overrides let it capture any example:
//   node capture_tutorial.mjs [example.html] [outDir] [prefix]
// Defaults: example = pkg/.../examples/report-community-garden.html, outDir = pkg/.../docs/assets,
// prefix = "garden". From dev/, run it as `npm run shots`. It pins the capture clock and disables CSS
// animations and transitions (and emulates reduced motion), so the capture is reproducible: the
// full-page shots are byte-identical across runs on the same environment. (The element-cropped figure
// shots (kql/chart/diff) and the dark-theme shot can vary by sub-pixel antialiasing - visually
// equivalent, not byte-stable.)
import { chromium } from "@playwright/test";
import path from "path";
import fs from "fs";
import { fileURLToPath, pathToFileURL } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SKILL = path.resolve(HERE, "..", "..", "pkg", "skills", "commentable-html");
const argv = process.argv.slice(2);
const printPaths = argv.includes("--print-paths");
const positional = argv.filter((a) => !a.startsWith("--"));
const htmlArg = positional[0] || path.join(SKILL, "examples", "report-community-garden.html");
const outDir = positional[1] || path.join(SKILL, "docs", "assets");
const prefix = path.basename(positional[2] || "garden");

// --print-paths resolves and prints the defaults without launching a browser or writing any files,
// so the no-argument (npm run shots) contract can be tested hermetically.
if (printPaths) {
  console.log(JSON.stringify({ example: htmlArg, outDir, prefix }));
  process.exit(0);
}

if (!fs.existsSync(htmlArg)) {
  console.error("capture_tutorial: example not found:", htmlArg);
  process.exit(2);
}
fs.mkdirSync(outDir, { recursive: true });
const url = pathToFileURL(path.resolve(htmlArg)).href;

function shotPath(name) { return path.join(outDir, `${prefix}-${name}.png`); }

async function ready(page) {
  await page.waitForFunction(() => window.__commentableHtmlReady === true, null, { timeout: 15000 });
  await page.waitForTimeout(300);
}

// Disable CSS animations and transitions so a shot taken while a panel, toast, or theme is settling
// is stable (the timed waits below already let them finish; this is belt-and-suspenders). The caret
// rule is redundant with Playwright's default caret:"hide" on screenshots but is harmless. Best-effort:
// a document CSP that forbids the injected style is reported (degraded mode), not silently swallowed.
async function freezeMotion(page) {
  await page.addStyleTag({ content:
    "*,*::before,*::after{animation-duration:0s !important;animation-delay:0s !important;"
    + "transition-duration:0s !important;transition-delay:0s !important;caret-color:transparent !important;}"
  }).catch((e) => console.warn("capture_tutorial: freezeMotion blocked (degraded determinism):", e.message));
}

// Pin the clock so any wall-clock content (a saved comment's timestamp, the "Generated on / Last
// comment" meta line) renders the same on every run - otherwise a capture that straddles a minute
// boundary would differ. Explicit-argument Date construction and parsing are preserved.
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

const run = async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1320, height: 900 },
    deviceScaleFactor: 2,
    reducedMotion: "reduce",
    permissions: ["clipboard-read", "clipboard-write"],
  });
  const page = await context.newPage();
  await freezeClock(context);
  await page.goto(url);
  await ready(page);
  await freezeMotion(page);

  // 1. Top of the document, light theme.
  await page.screenshot({ path: shotPath("01-top-light"), clip: { x: 0, y: 0, width: 1320, height: 900 } });

  // 2. The KQL figure with its Run-in-Kusto link.
  const kql = page.locator("figure.cmh-kql").first();
  if (await kql.count()) { await kql.scrollIntoViewIfNeeded(); await page.waitForTimeout(150); await kql.screenshot({ path: shotPath("02-kql") }); }

  // 3. The chart.
  const chart = page.locator("figure.chart").first();
  if (await chart.count()) { await chart.scrollIntoViewIfNeeded(); await page.waitForTimeout(400); await chart.screenshot({ path: shotPath("03-chart") }); }

  // 4. The diff / code-review block.
  const diff = page.locator(".cmh-diff-host, pre.cmh-diff").first();
  if (await diff.count()) { await diff.scrollIntoViewIfNeeded(); await page.waitForTimeout(150); await diff.screenshot({ path: shotPath("04-diff") }); }

  // 5. A comment composer open on the first prose paragraph (the core workflow).
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
  await page.waitForTimeout(300);
  const addBtn = page.locator(".cm-add-comment, [data-cm-add], button:has-text('Add comment')").first();
  if (await addBtn.count()) {
    // Fail loudly if the compose/save flow does not actually happen: otherwise 05/06 would be
    // captured in the wrong state yet still look "successful" (and would even be byte-stable across
    // two equally-broken runs). The outer count() guard still skips examples without the add flow.
    await addBtn.click();
    const composer = page.locator(".cm-composer").first();
    await composer.waitFor({ state: "visible", timeout: 5000 });
    await page.waitForTimeout(300);
    await page.screenshot({ path: shotPath("05-composer"), clip: { x: 0, y: 0, width: 1320, height: 900 } });
    await composer.locator("textarea").first().fill("Does this section read clearly? Consider adding one more example.");
    await page.waitForTimeout(150);
    await composer.locator("button:has-text('Comment'), button:has-text('Save'), button.cm-save").first().click();
    await page.locator("#commentRoot mark.cm-hl").first().waitFor({ state: "visible", timeout: 5000 });
    await page.waitForTimeout(400);
  }

  // 6. The comments panel with a saved comment.
  await page.screenshot({ path: shotPath("06-comment-saved"), clip: { x: 0, y: 0, width: 1320, height: 900 } });

  // 9. "Copy all" - the review bundle copied back to the agent (step 3 of the review loop).
  await page.evaluate(() => { window.prompt = () => ""; });
  const copyBtn = page.locator("#btnCopyAll");
  if (await copyBtn.count()) {
    await copyBtn.click().catch(() => {});
    await page.waitForTimeout(500);
    await page.screenshot({ path: shotPath("09-copyall"), clip: { x: 0, y: 0, width: 1320, height: 900 } });
  }

  // 7. The help panel.
  await page.evaluate(() => {
    const b = document.getElementById("btnHelp");
    if (b && b.offsetParent !== null) { b.click(); return; }
    const m = document.getElementById("btnToolbarMenu");
    if (m) m.click();
    const t = document.getElementById("btnHelpTop");
    if (t) t.click();
  });
  await page.waitForTimeout(400);
  await page.screenshot({ path: shotPath("07-help"), clip: { x: 0, y: 0, width: 1320, height: 900 } });

  // 8. Dark theme, top of the document.
  await page.keyboard.press("Escape").catch(() => {});
  await page.evaluate(() => { document.documentElement.setAttribute("data-theme", "dark"); window.scrollTo(0, 0); });
  await page.waitForTimeout(300);
  await page.screenshot({ path: shotPath("08-top-dark"), clip: { x: 0, y: 0, width: 1320, height: 900 } });

  await browser.close();
  console.log("captured shots with prefix", prefix, "->", outDir);
};

run().catch((e) => { console.error(e); process.exit(1); });
