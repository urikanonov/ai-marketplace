// Deterministic tutorial screenshot capture for the commentable-html plugin (dev-only, not shipped).
// With no arguments it regenerates every tutorial screenshot (the garden-*.png images that
// docs/TUTORIAL.md embeds) from the shipped community-garden example into docs/assets. Optional
// positional overrides let it capture any example:
//   node capture_tutorial.mjs [example.html] [outDir] [prefix]
// Defaults: example = pkg/.../examples/report-community-garden.html, outDir = pkg/.../docs/assets,
// prefix = "garden". From dev/, run it as `npm run shots`. Animations, transitions, and the text
// caret are disabled and reduced motion is emulated, so re-running produces byte-identical images.
import { chromium } from "@playwright/test";
import path from "path";
import fs from "fs";
import { fileURLToPath, pathToFileURL } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SKILL = path.resolve(HERE, "..", "..", "pkg", "skills", "commentable-html");
const htmlArg = process.argv[2] || path.join(SKILL, "examples", "report-community-garden.html");
const outDir = process.argv[3] || path.join(SKILL, "docs", "assets");
const prefix = process.argv[4] || "garden";

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

// Kill anything that varies frame to frame - CSS animations/transitions and the blinking text
// caret - so two runs render identically. Best-effort: a document CSP that forbids inline styles
// just ignores it, and the static shots stay deterministic regardless.
async function freezeMotion(page) {
  await page.addStyleTag({ content:
    "*,*::before,*::after{animation-duration:0s !important;animation-delay:0s !important;"
    + "transition-duration:0s !important;transition-delay:0s !important;caret-color:transparent !important;}"
  }).catch(() => {});
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
    await addBtn.click().catch(() => {});
    await page.waitForTimeout(300);
    await page.screenshot({ path: shotPath("05-composer"), clip: { x: 0, y: 0, width: 1320, height: 900 } });
    const ta = page.locator(".cm-composer textarea, textarea.cm-comment-input").first();
    if (await ta.count()) { await ta.fill("Does this section read clearly? Consider adding one more example."); await page.waitForTimeout(150); }
    const save = page.locator(".cm-composer button:has-text('Comment'), .cm-composer button:has-text('Save'), button.cm-save").first();
    if (await save.count()) { await save.click().catch(() => {}); await page.waitForTimeout(400); }
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
