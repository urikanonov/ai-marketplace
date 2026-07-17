// Visual-audit driver: opens every commentable-html example in a real browser
// (Chromium via Playwright), in desktop AND mobile viewports, exercises the
// interactive UI (comment mode, selecting text, adding and saving comments,
// the toolbar menu, deck navigation and overview), captures screenshots at each
// meaningful state, records console/page errors and per-state horizontal
// overflow, and writes a JSON transcript plus a commentable-html report (built
// with the plugin's new_document.py) so the audit itself is reviewable. Nothing
// is checked in - all output lands in the gitignored out-dir. Re-run any time:
// node tools/audit.mjs --open.
//
// Playwright is resolved via createRequire from the commentable-html dev install
// (ESM ignores NODE_PATH, so no env var is needed - see loadPlaywright below).
//
// Usage:
//   node tools/audit.mjs \
//     --examples-dir <dir of *.html>   (default: the commentable-html examples)
//     --out-dir <output dir>           (default: <repo>/tmp/visual-audit, gitignored)
//     --report <html path>             (default: <out-dir>/audit-report.html, commentable-html)
//     --only <substring>               (optional: audit only matching example names)
//     --open                           (open the commentable-html report in the browser)
//     --from-transcript [path]         (regenerate the reports from an existing
//                                       transcript.json without a browser run)
//
// Screens land under <out-dir>/<example>/<viewport>/NN-state.png. The report is a
// portable commentable-html document that embeds each screenshot as a figure; a
// plain Markdown sidecar (audit-report.md) is written alongside for text tools.

import { pathToFileURL, fileURLToPath } from "url";
import { createRequire } from "module";
import { spawnSync } from "child_process";
import path from "path";
import fs from "fs";
import os from "os";
import http from "http";

const HERE = path.dirname(fileURLToPath(import.meta.url));
// Repo root is four levels up from .github/skills/visual-audit/tools.
const REPO = path.resolve(HERE, "..", "..", "..", "..");
const DEV = path.join(REPO, "plugins", "commentable-html", "dev");

// Playwright is not a dependency of this skill; it is reused from the
// commentable-html dev install (or any node_modules on the way up). Resolve it
// dynamically so the ESM loader (which ignores NODE_PATH) can still find it.
const requireFrom = createRequire(import.meta.url);
function loadPlaywright() {
  const candidates = [
    path.join(DEV, "node_modules"),
    path.join(HERE, "node_modules"),
    path.join(REPO, "node_modules"),
  ];
  for (const pkg of ["@playwright/test", "playwright", "playwright-core"]) {
    try {
      const entry = requireFrom.resolve(pkg, { paths: candidates });
      const mod = requireFrom(entry);
      if (mod && (mod.chromium || (mod.default && mod.default.chromium))) return mod.chromium || mod.default.chromium;
    } catch (e) { /* try next */ }
  }
  throw new Error(
    "Playwright not found. Install it once in the commentable-html dev tree:\n" +
    "  cd plugins/commentable-html/dev && npm ci && npx playwright install chromium",
  );
}
// Resolved lazily (only for the browser-audit path) so --from-transcript can
// regenerate the reports on a machine without Playwright installed.
let chromium = null;

// Accept both "--key value" and "--key=value"; a known-string key with no value
// errors out rather than silently collapsing to boolean true.
const STRING_KEYS = new Set(["examples-dir", "out-dir", "report", "only"]);
function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) continue;
    const eq = a.indexOf("=");
    if (eq > 2) { out[a.slice(2, eq)] = a.slice(eq + 1); continue; }
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith("--")) { out[key] = argv[++i]; }
    else if (STRING_KEYS.has(key)) { throw new Error(`Option --${key} requires a value`); }
    else { out[key] = true; }
  }
  return out;
}
const args = parseArgs(process.argv.slice(2));

const EXAMPLES_DIR = args["examples-dir"]
  ? path.resolve(String(args["examples-dir"]))
  : path.join(REPO, "plugins", "commentable-html", "examples");
const OUT_DIR = args["out-dir"] ? path.resolve(String(args["out-dir"])) : path.join(REPO, "tmp", "visual-audit");
// The report is a commentable-html document (so the audit itself is reviewable and
// commentable) written into the gitignored out-dir - it is NOT checked in. A plain
// Markdown sidecar is written alongside for text tools.
const REPORT = args["report"] ? path.resolve(String(args["report"])) : path.join(OUT_DIR, "audit-report.html");
const MD_REPORT = path.join(OUT_DIR, "audit-report.md");
const ONLY = typeof args.only === "string" ? args.only : null;

// The commentable-html authoring tool that wraps a content fragment into a portable
// commentable document, and a Python interpreter to run it. Resolved best-effort;
// if either is missing the report falls back to a plain (non-commentable) HTML file.
const NEW_DOC = path.join(REPO, "plugins", "commentable-html", "dev", "skill", "tools", "authoring", "new_document.py");
const PYTHON = (() => {
  for (const cmd of ["python3", "python"]) {
    try { if (spawnSync(cmd, ["--version"]).status === 0) return cmd; } catch (e) { /* try next */ }
  }
  return "python";
})();

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900, deviceScaleFactor: 1, isMobile: false },
  { name: "mobile", width: 390, height: 844, deviceScaleFactor: 2, isMobile: true },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function ensureDir(d) { fs.mkdirSync(d, { recursive: true }); }
function rel(from, to) { return path.relative(path.dirname(from), to).split(path.sep).join("/"); }
// Sanitize any text destined for a Markdown table cell or bullet: strip
// newlines (which would split the row) and pipes/backticks (which would break it).
function cell(s) { return String(s == null ? "" : s).replace(/[\r\n]+/g, " ").replace(/\|/g, "/").replace(/`/g, "'").trim(); }
// Coerce a value expected to be numeric (from a transcript that could be hand-fed
// via --from-transcript) to a finite number, so a string never lands raw in HTML.
function num(x) { return Number.isFinite(Number(x)) ? Number(x) : 0; }

function discoverExamples() {
  const files = fs.readdirSync(EXAMPLES_DIR).filter((f) => f.endsWith(".html")).sort();
  return files
    .filter((f) => !ONLY || f.includes(ONLY))
    .map((f) => ({ name: f.replace(/\.html$/, ""), file: path.join(EXAMPLES_DIR, f) }));
}

// A tiny static server so pages load over http://localhost (not file://). The
// examples import mermaid as an ES module, which browsers block over file://;
// http lets it load, and routeMermaidLocal makes it hermetic besides.
function startStaticServer(dir) {
  const root = fs.realpathSync(path.resolve(dir));
  const server = http.createServer((req, res) => {
    try {
      const rel0 = decodeURIComponent((req.url || "/").split("?")[0]);
      if (rel0.includes("\0")) { res.writeHead(400); res.end(); return; }
      // Containment barrier: resolve the request under the served root and reject
      // anything that escapes it. path.relative yields "" (root itself) or a
      // relative path with NO leading ".." segment for a contained target; a
      // leading ".." or an absolute result means traversal, so 403 it. This is a
      // sanitizer the tainted request path must pass before touching the fs.
      const p = path.resolve(root, "." + path.sep + rel0);
      const relToRoot = path.relative(root, p);
      const escapes = (rp) => rp === ".." || rp.startsWith(".." + path.sep) || path.isAbsolute(rp);
      if (escapes(relToRoot)) { res.writeHead(403); res.end(); return; }
      // Resolve symlinks/junctions and re-check containment so a link inside the
      // served dir cannot escape the root and expose arbitrary local files.
      fs.realpath(p, (er, real) => {
        if (er) { res.writeHead(404); res.end(); return; }
        const realRel = path.relative(root, real);
        if (realRel !== "" && escapes(realRel)) { res.writeHead(403); res.end(); return; }
        fs.readFile(real, (e, data) => {
          if (e) { res.writeHead(404); res.end(); return; }
          const ext = path.extname(real);
          const ct = ext === ".html" ? "text/html" : ext === ".js" || ext === ".mjs" ? "text/javascript"
            : ext === ".css" ? "text/css" : ext === ".svg" ? "image/svg+xml" : "application/octet-stream";
          res.writeHead(200, { "Content-Type": ct });
          res.end(data);
        });
      });
    } catch (err) { res.writeHead(400); res.end(); }
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve({ url: `http://127.0.0.1:${server.address().port}`, close: () => new Promise((r) => server.close(r)) }));
  });
}

// Fulfill the mermaid CDN import from the vendored dev copy (version-matched to the
// examples), so diagrams render deterministically. Chart.js and any other resources
// load from their own pinned CDNs, so a chart pass needs network; the examples are
// this repo's own trusted content, so no request is blocked.
async function routeMermaidLocal(page) {
  const distRoot = path.join(DEV, "node_modules", "mermaid");
  let vendored = null;
  try { vendored = JSON.parse(fs.readFileSync(path.join(distRoot, "package.json"), "utf8")).version; } catch (e) { vendored = null; }
  if (!vendored) {
    if (!routeMermaidLocal._warned) {
      routeMermaidLocal._warned = true;
      console.warn("[visual-audit] vendored mermaid not found under " + distRoot + "; mermaid will load from the CDN instead.");
    }
    return;
  }
  await page.route(/cdn\.jsdelivr\.net\/npm\/mermaid@/, async (route) => {
    const u = new URL(route.request().url());
    const relPath = u.pathname.replace(/^\/npm\/mermaid@[^/]+\//, "");
    try {
      const body = fs.readFileSync(path.join(distRoot, relPath));
      await route.fulfill({ body, contentType: "text/javascript", headers: { "access-control-allow-origin": "*" } });
    } catch (e) { await route.fallback(); }
  });
}

async function detectMode(page) {
  return page.evaluate(() => {
    const root = document.getElementById("commentRoot");
    return root && root.getAttribute("data-cmh-mode") === "deck" ? "deck" : "report";
  }).catch(() => "report");
}

// Returns true when the runtime signalled ready; false on timeout so the caller
// can record a load failure instead of auditing a page that never initialized.
async function waitReady(page) {
  try {
    await page.waitForFunction(() => window.__commentableHtmlReady === true, null, { timeout: 12000 });
    return true;
  } catch (e) { return false; }
}

// Wait until EVERY mermaid/rich block has rendered an svg (not just the first),
// so a screenshot never catches later diagrams still in source/loading state.
async function waitForRichContent(page) {
  try {
    await page.waitForFunction(
      () => {
        const figs = document.querySelectorAll(".mermaid, figure.cmh-mermaid, .cmh-diagram");
        if (!figs.length) return true;
        return [...figs].every((f) => f.querySelector("svg"));
      },
      null,
      { timeout: 9000 },
    );
  } catch (e) { /* diagrams may be absent or slow; proceed */ }
  await sleep(600);
}

// Real, NATURAL text selection: start at the first real character (not mid-word)
// and end at a sentence or word boundary, so the composer/comment screenshots
// look like a genuine user selection (never a stray-quote mid-word artifact).
async function selectTextIn(page, selector) {
  return page.evaluate((sel) => {
    const els = [...document.querySelectorAll(sel)];
    const el = els.find((e) => (e.textContent || "").trim().length > 40) || els[0];
    if (!el) return false;
    el.scrollIntoView({ block: "center" });
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let n;
    while ((n = walker.nextNode())) { if (n.data && n.data.trim()) nodes.push(n); }
    if (!nodes.length) return false;
    let full = "";
    const map = [];
    for (const node of nodes) { map.push({ node, start: full.length }); full += node.data; }
    let startChar = 0;
    while (startChar < full.length && /\s/.test(full[startChar])) startChar++;
    let endChar;
    const dot = full.indexOf(". ", startChar + 20);
    if (dot > 0 && dot - startChar <= 220) {
      endChar = dot + 1;
    } else {
      const cap = Math.min(full.length, startChar + 160);
      const e = full.lastIndexOf(" ", cap);
      endChar = e > startChar + 30 ? e : cap;
    }
    endChar = Math.min(endChar, full.length);
    const locate = (ch) => {
      for (let i = map.length - 1; i >= 0; i--) if (ch >= map[i].start) return { node: map[i].node, offset: ch - map[i].start };
      return { node: nodes[0], offset: 0 };
    };
    const a = locate(startChar);
    const b = locate(endChar);
    const range = document.createRange();
    range.setStart(a.node, Math.min(a.offset, a.node.data.length));
    range.setEnd(b.node, Math.min(b.offset, b.node.data.length));
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(range);
    el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 60, clientY: 60 }));
    return true;
  }, selector);
}

async function addComment(page, selector) {
  const ok = await selectTextIn(page, selector);
  if (!ok) return false;
  const menu = page.locator("#menuComment");
  try { await menu.waitFor({ state: "visible", timeout: 2500 }); } catch (e) { return false; }
  await menu.click();
  const composer = page.locator(".cm-composer").last();
  try { await composer.waitFor({ state: "visible", timeout: 2500 }); } catch (e) { return false; }
  return composer;
}

// Horizontal-overflow probe across the WHOLE document (content plus chrome:
// toolbar, sidebar, deck nav) - not just #commentRoot - so overflow that lives
// in the chrome is caught too. Returns the doc width vs viewport and offenders.
async function checkOverflow(page) {
  return page.evaluate(() => {
    const doc = document.documentElement;
    const innerWidth = window.innerWidth;
    const docScrollWidth = Math.max(doc.scrollWidth, document.body ? document.body.scrollWidth : 0);
    const offenders = [];
    for (const el of document.querySelectorAll("body *")) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.right > innerWidth + 2) {
        offenders.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.getAttribute("class") || "").slice(0, 60),
          right: Math.round(r.right),
        });
        if (offenders.length >= 12) break;
      }
    }
    return { innerWidth, docScrollWidth, overflowX: docScrollWidth > innerWidth + 2, offenders };
  });
}

async function shoot(page, ctx, label, { fullPage } = {}) {
  const dir = path.join(OUT_DIR, ctx.example, ctx.viewport);
  ensureDir(dir);
  const idx = String(ctx.step).padStart(2, "0");
  const file = path.join(dir, `${idx}-${label}.png`);
  let ok = false;
  try { await page.screenshot({ path: file, fullPage: !!fullPage }); ok = true; }
  catch (e) {
    try { await page.screenshot({ path: file, fullPage: false }); ok = true; ctx.warnings.push(label + ": fullPage failed, captured viewport"); }
    catch (e2) { ctx.warnings.push(label + ": screenshot failed: " + e2.message); }
  }
  if (!ok || !fs.existsSync(file)) {
    ctx.steps.push({ action: label, screenshot: null, note: ctx.pendingNote || "", failed: true });
    ctx.pendingNote = "";
    return null;
  }
  ctx.step++;
  const overflow = await checkOverflow(page).catch(() => null);
  ctx.steps.push({ action: label, screenshot: file, note: ctx.pendingNote || "", overflow });
  ctx.pendingNote = "";
  return file;
}
function note(ctx, text) { ctx.pendingNote = text; }

async function auditReport(page, ctx) {
  await shoot(page, ctx, "initial-top", { fullPage: false });
  note(ctx, "Full-page render of the whole report.");
  await shoot(page, ctx, "full-page", { fullPage: true });

  try {
    const btn = page.locator("#btnToolbarMenu");
    if (await btn.count()) {
      await btn.click();
      await page.locator("#toolbarMenu").waitFor({ state: "visible", timeout: 2000 });
      note(ctx, "Toolbar menu open: save/export/help actions and mode badge.");
      await shoot(page, ctx, "toolbar-menu", { fullPage: false });
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(350); // let the menu finish closing before the next shot
    }
  } catch (e) { ctx.warnings.push("toolbar-menu: " + e.message); }

  try {
    const composer = await addComment(page, "#commentRoot p");
    if (composer) {
      note(ctx, "Comment composer open over a real text selection.");
      await shoot(page, ctx, "composer-open", { fullPage: false });
      await composer.locator("textarea").fill("Visual audit: is this section clear and well spaced?");
      await composer.locator('[data-act="save"]').click();
      await page.waitForTimeout(500);
      note(ctx, "After saving a comment: highlight in content, entry in the sidebar.");
      await shoot(page, ctx, "comment-saved", { fullPage: false });
    } else { ctx.warnings.push("could not open comment composer on a paragraph"); }
  } catch (e) { ctx.warnings.push("add-comment: " + e.message); }

  try {
    const toggle = page.locator("#btnToggleSidebar");
    const hidden = await page.locator("#sidebar").isHidden().catch(() => false);
    if (await toggle.count() && hidden) { await toggle.click(); await page.waitForTimeout(300); }
    if (await page.locator("#sidebar").count()) {
      note(ctx, "Comments sidebar with the saved comment.");
      await shoot(page, ctx, "sidebar", { fullPage: false });
    }
  } catch (e) { ctx.warnings.push("sidebar: " + e.message); }

  try {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(400);
    note(ctx, "Bottom of the report (footer, late tables/diagrams).");
    await shoot(page, ctx, "scrolled-bottom", { fullPage: false });
    await page.evaluate(() => window.scrollTo(0, 0));
  } catch (e) { ctx.warnings.push("scroll: " + e.message); }
}

const activeSlideIndex = (page) => page.evaluate(() => {
  const slides = [...document.querySelectorAll("#commentRoot .slide")];
  return slides.findIndex((s) => s.classList.contains("active"));
});

async function auditDeck(page, ctx) {
  note(ctx, "Deck: opening slide.");
  await shoot(page, ctx, "slide-1", { fullPage: false });

  const slideCount = await page.evaluate(() => document.querySelectorAll("#commentRoot .slide").length);
  const advances = Math.min(3, Math.max(0, slideCount - 1));
  for (let i = 0; i < advances; i++) {
    try {
      const before = await activeSlideIndex(page);
      await page.keyboard.press("ArrowRight");
      await page.waitForTimeout(650);
      const after = await activeSlideIndex(page);
      if (after === before) ctx.warnings.push(`deck-advance: slide did not change at step ${i + 1} (stuck on ${before})`);
      await waitForRichContent(page);
      note(ctx, `Deck slide ${i + 2} of ${slideCount}.`);
      await shoot(page, ctx, `slide-${i + 2}`, { fullPage: false });
    } catch (e) { ctx.warnings.push("deck-advance: " + e.message); }
  }

  try {
    await page.keyboard.press("o");
    await page.waitForTimeout(600);
    if (await page.evaluate(() => document.body.classList.contains("cmh-deck-overview-open"))) {
      note(ctx, "Deck overview grid (all slides at a glance).");
      await shoot(page, ctx, "overview", { fullPage: false });
      await page.keyboard.press("Escape");
      await page.waitForTimeout(400);
      await page.evaluate(() => document.activeElement && document.activeElement.blur());
    }
  } catch (e) { ctx.warnings.push("deck-overview: " + e.message); }

  try {
    const toggle = page.locator(".cmh-deck-mode-toggle");
    if (await toggle.count()) {
      await toggle.first().click();
      await page.waitForTimeout(500);
      note(ctx, "Deck comment mode on (chrome revealed for review).");
      await shoot(page, ctx, "comment-mode", { fullPage: false });
      const composer = await addComment(page, "#commentRoot .slide.active :is(p,li,h1,h2,h3,td)");
      if (composer) {
        await composer.locator("textarea").fill("Visual audit: does this slide read well?");
        await composer.locator('[data-act="save"]').click();
        await page.waitForTimeout(500);
        note(ctx, "Deck slide with a saved comment.");
        await shoot(page, ctx, "deck-comment-saved", { fullPage: false });
      }
    }
  } catch (e) { ctx.warnings.push("deck-comment: " + e.message); }
}

// Aggregate the per-state overflow into one viewport verdict: overflowX is true
// if ANY captured state overflowed; offenders/label come from the first such state.
function summarizeOverflow(steps) {
  const bad = steps.find((s) => s.overflow && s.overflow.overflowX);
  if (!bad) {
    const any = steps.find((s) => s.overflow);
    return any ? { overflowX: false, innerWidth: any.overflow.innerWidth } : null;
  }
  return { overflowX: true, at: bad.action, innerWidth: bad.overflow.innerWidth, docScrollWidth: bad.overflow.docScrollWidth, offenders: bad.overflow.offenders };
}

async function auditExample(browser, server, ex) {
  const record = { name: ex.name, mode: ex.mode || "report", viewports: [] };
  for (const vp of VIEWPORTS) {
    const context = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      deviceScaleFactor: vp.deviceScaleFactor,
      isMobile: vp.isMobile,
      hasTouch: vp.isMobile,
    });
    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text().slice(0, 300)); });
    page.on("pageerror", (e) => pageErrors.push(String(e.message).slice(0, 300)));
    await routeMermaidLocal(page);

    const ctx = { example: ex.name, viewport: vp.name, step: 1, steps: [], warnings: [], pendingNote: "" };
    let loaded = false;
    try {
      await page.goto(server.url + "/" + encodeURIComponent(path.basename(ex.file)), { waitUntil: "load", timeout: 30000 });
      loaded = await waitReady(page);
      if (!loaded) ctx.warnings.push("runtime never signalled ready (__commentableHtmlReady); auditing partial render");
      record.mode = await detectMode(page);
      await waitForRichContent(page);
      if (record.mode === "deck") await auditDeck(page, ctx);
      else await auditReport(page, ctx);
    } catch (e) {
      ctx.warnings.push("fatal: " + e.message);
    }
    const overflow = loaded ? summarizeOverflow(ctx.steps) : null;
    record.viewports.push({ viewport: vp, loaded, steps: ctx.steps, warnings: ctx.warnings, consoleErrors, pageErrors, overflow });
    await context.close();
    const ofl = !loaded ? "load-failed" : overflow && overflow.overflowX ? `YES@${overflow.at}` : "no";
    console.log(`  [${ex.name}] ${vp.name}: ${ctx.steps.filter((s) => !s.failed).length} shots, ${consoleErrors.length} console errors, overflowX=${ofl}`);
  }
  return record;
}

function writeMarkdown(transcript) {
  ensureDir(path.dirname(REPORT));
  const L = [];
  L.push("# Commentable-HTML examples - visual audit");
  L.push("");
  L.push("Generated by the `visual-audit` skill (`.github/skills/visual-audit`). It drives every");
  L.push("example in a real Chromium browser (via Playwright) in desktop and mobile viewports,");
  L.push("exercises the interactive UI (comment mode, selecting text, adding and saving comments,");
  L.push("the toolbar menu, and deck navigation/overview), and captures a screenshot at each state.");
  L.push("");
  L.push("- Generated on: " + String(transcript.generatedAt || "").slice(0, 10));
  L.push("- Examples audited: " + transcript.examples.length);
  L.push("- Screenshots (gitignored): `" + rel(REPORT, OUT_DIR) + "` (regenerate with `node .github/skills/visual-audit/tools/audit.mjs`)");
  L.push("");
  L.push("## Automated findings summary");
  L.push("");
  L.push("| Example | Viewport | Steps | Console errors | Page errors | Horizontal overflow |");
  L.push("| --- | --- | ---: | ---: | ---: | --- |");
  for (const ex of transcript.examples) {
    for (const v of ex.viewports) {
      let of;
      if (!v.loaded) of = "load failed (n/a)";
      else if (v.overflow && v.overflow.overflowX) {
        of = "YES @" + cell(v.overflow.at) + " (" + v.overflow.offenders.map((o) => o.tag + (o.cls ? "." + o.cls.split(" ")[0] : "")).slice(0, 4).join(", ") + ")";
      } else of = "no";
      const shots = v.steps.filter((s) => !s.failed).length;
      L.push(`| ${cell(ex.name)} | ${cell(v.viewport.name)} | ${shots} | ${v.consoleErrors.length} | ${v.pageErrors.length} | ${cell(of)} |`);
    }
  }
  L.push("");
  for (const ex of transcript.examples) {
    L.push("## " + ex.name + " (" + ex.mode + ")");
    L.push("");
    for (const v of ex.viewports) {
      L.push("### " + v.viewport.name + " - " + v.viewport.width + "x" + v.viewport.height);
      L.push("");
      if (!v.loaded) { L.push("> Runtime never signalled ready; this viewport shows only a partial render."); L.push(""); }
      if (v.overflow && v.overflow.overflowX) {
        L.push("> Horizontal overflow at state `" + cell(v.overflow.at) + "` (docScrollWidth " + v.overflow.docScrollWidth + " > innerWidth " + v.overflow.innerWidth + "). Offenders: " +
          v.overflow.offenders.map((o) => "`" + cell(o.tag + (o.cls ? "." + o.cls.split(" ")[0] : "")) + "`@" + o.right).join(", "));
        L.push("");
      }
      if (v.consoleErrors.length) {
        L.push("Console errors:");
        for (const e of v.consoleErrors.slice(0, 6)) L.push("- `" + cell(e) + "`");
        L.push("");
      }
      if (v.pageErrors.length) {
        L.push("Page errors:");
        for (const e of v.pageErrors.slice(0, 6)) L.push("- `" + cell(e) + "`");
        L.push("");
      }
      L.push("| # | Action | Screenshot | Note |");
      L.push("| ---: | --- | --- | --- |");
      v.steps.forEach((s, i) => {
        const shot = s.screenshot ? "`" + path.relative(REPO, s.screenshot).split(path.sep).join("/") + "`" : "(screenshot failed)";
        L.push(`| ${i + 1} | ${cell(s.action)} | ${shot} | ${cell(s.note)} |`);
      });
      if (v.warnings.length) {
        L.push("");
        L.push("Warnings: " + v.warnings.map((w) => "`" + cell(w) + "`").join("; "));
      }
      L.push("");
    }
  }
  fs.writeFileSync(MD_REPORT, L.join("\n") + "\n", "utf8");
}

// HTML-escape text for the commentable-html fragment.
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// Build a content fragment (the document body) for the commentable-html report:
// an intro, an automated findings-summary table, and one figure per captured
// screenshot (so every shot is a commentable image anchor), grouped by example
// and viewport. Images are referenced by a path relative to the report file.
function buildCmhFragment(transcript) {
  const H = [];
  H.push('<h1>Commentable-HTML examples - visual audit</h1>');
  H.push('<p>Generated by the <code>visual-audit</code> skill: every example driven in a real Chromium browser (via Playwright) in desktop and mobile viewports, exercising the interactive UI (comment mode, selecting text, adding and saving comments, the toolbar menu, and deck navigation/overview), with a screenshot at each state. Select any screenshot, table cell, or line to leave a review comment.</p>');
  H.push('<p>Generated on: ' + esc(String(transcript.generatedAt || "").slice(0, 10)) + ' &middot; Examples audited: ' + transcript.examples.length + '</p>');

  H.push('<h2>Automated findings summary</h2>');
  H.push('<table><thead><tr><th>Example</th><th>Viewport</th><th>Steps</th><th>Console errors</th><th>Page errors</th><th>Horizontal overflow</th></tr></thead><tbody>');
  for (const ex of transcript.examples) {
    for (const v of ex.viewports) {
      let of;
      if (!v.loaded) of = "load failed (n/a)";
      else if (v.overflow && v.overflow.overflowX) of = "YES @" + v.overflow.at + " (" + v.overflow.offenders.map((o) => o.tag + (o.cls ? "." + o.cls.split(" ")[0] : "")).slice(0, 4).join(", ") + ")";
      else of = "no";
      const shots = v.steps.filter((s) => !s.failed).length;
      H.push('<tr><td>' + esc(ex.name) + '</td><td>' + esc(v.viewport.name) + '</td><td>' + shots + '</td><td>' + v.consoleErrors.length + '</td><td>' + v.pageErrors.length + '</td><td>' + esc(of) + '</td></tr>');
    }
  }
  H.push('</tbody></table>');

  for (const ex of transcript.examples) {
    H.push('<h2>' + esc(ex.name) + ' (' + esc(ex.mode) + ')</h2>');
    for (const v of ex.viewports) {
      H.push('<h3>' + esc(v.viewport.name) + ' - ' + num(v.viewport.width) + 'x' + num(v.viewport.height) + '</h3>');
      if (!v.loaded) H.push('<p><strong>Runtime never signalled ready; this viewport shows only a partial render.</strong></p>');
      if (v.overflow && v.overflow.overflowX) {
        H.push('<p><strong>Horizontal overflow</strong> at state <code>' + esc(v.overflow.at) + '</code> (docScrollWidth ' + num(v.overflow.docScrollWidth) + ' &gt; innerWidth ' + num(v.overflow.innerWidth) + '). Offenders: ' +
          v.overflow.offenders.map((o) => '<code>' + esc(o.tag + (o.cls ? "." + o.cls.split(" ")[0] : "")) + '</code>@' + num(o.right)).join(', ') + '</p>');
      }
      if (v.consoleErrors.length) H.push('<p>Console errors: ' + v.consoleErrors.slice(0, 6).map((e) => '<code>' + esc(e) + '</code>').join('; ') + '</p>');
      if (v.pageErrors.length) H.push('<p>Page errors: ' + v.pageErrors.slice(0, 6).map((e) => '<code>' + esc(e) + '</code>').join('; ') + '</p>');
      for (const s of v.steps) {
        if (!s.screenshot) { H.push('<p><em>' + esc(s.action) + ': screenshot failed</em></p>'); continue; }
        const src = path.relative(path.dirname(REPORT), s.screenshot).split(path.sep).join('/');
        H.push('<figure><img src="' + esc(src) + '" alt="' + esc(ex.name + ' ' + v.viewport.name + ' ' + s.action) + '" loading="lazy" style="max-width:100%;border:1px solid #ddd;border-radius:6px;">' +
          '<figcaption><strong>' + esc(s.action) + '</strong>' + (s.note ? ' - ' + esc(s.note) : '') + '</figcaption></figure>');
      }
      if (v.warnings.length) H.push('<p>Warnings: ' + v.warnings.map((w) => '<code>' + esc(w) + '</code>').join('; ') + '</p>');
    }
  }
  return H.join("\n");
}

// Write the commentable-html report by wrapping the fragment with the plugin's
// new_document.py (a single portable, commentable file). Falls back to a plain
// standalone HTML file if the tool or Python is unavailable.
function writeCmhReport(transcript) {
  ensureDir(path.dirname(REPORT));
  const fragment = buildCmhFragment(transcript);
  const fragDir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh-audit-"));
  const fragFile = path.join(fragDir, "fragment.html");
  fs.writeFileSync(fragFile, fragment, "utf8");
  try {
    if (fs.existsSync(NEW_DOC)) {
      const r = spawnSync(PYTHON, [
        NEW_DOC, "--content", fragFile, "--key", "cmh-visual-audit", "--label", "Commentable-HTML examples - visual audit",
        "--kind", "report", "--source", "visual-audit", "--portable", "--out", REPORT, "--force", "--no-session-id",
      ], { encoding: "utf8" });
      if (r.status === 0 && fs.existsSync(REPORT)) return true;
      console.warn("new_document.py did not produce the report (status " + r.status + "): " + String(r.stderr || "").slice(0, 400));
    } else {
      console.warn("new_document.py not found at " + NEW_DOC + "; writing a plain HTML report instead.");
    }
  } catch (e) {
    console.warn("commentable-html report build failed (" + e.message + "); writing a plain HTML report instead.");
  } finally {
    try { fs.rmSync(fragDir, { recursive: true, force: true }); } catch (e) { /* ignore */ }
  }
  // Fallback: a plain, non-commentable standalone HTML file so the audit still opens.
  fs.writeFileSync(REPORT, "<!doctype html><html><head><meta charset=\"utf-8\"><title>visual audit</title></head><body>" + fragment + "</body></html>", "utf8");
  return false;
}

// Open a file in the OS default browser (best-effort, non-blocking).
function openInBrowser(file) {
  const url = pathToFileURL(file).href;
  const plt = process.platform;
  const cmd = plt === "win32" ? "cmd" : plt === "darwin" ? "open" : "xdg-open";
  const cargs = plt === "win32" ? ["/c", "start", "", url] : [url];
  try { spawnSync(cmd, cargs, { stdio: "ignore", detached: true }); }
  catch (e) { console.warn("could not open the browser: " + e.message); }
}

async function main() {
  // Regenerate the report(s) from an existing transcript.json without a browser
  // run. --from-transcript <path> reads that file; bare uses out-dir.
  if (args["from-transcript"]) {
    const tp = args["from-transcript"] === true ? path.join(OUT_DIR, "transcript.json") : path.resolve(String(args["from-transcript"]));
    const transcript = JSON.parse(fs.readFileSync(tp, "utf8"));
    writeMarkdown(transcript);
    const cmhOk = writeCmhReport(transcript);
    console.log("Report (from transcript): " + REPORT + (cmhOk ? " (commentable-html)" : " (plain HTML fallback)"));
    if (args.open) openInBrowser(REPORT);
    return;
  }
  const examples = discoverExamples();
  if (!examples.length) { console.error("No examples found in " + EXAMPLES_DIR); process.exit(1); }
  if (!chromium) chromium = loadPlaywright();
  ensureDir(OUT_DIR);
  console.log("Auditing " + examples.length + " examples in " + EXAMPLES_DIR);
  const server = await startStaticServer(EXAMPLES_DIR);
  let browser;
  const transcript = { generatedAt: new Date().toISOString(), examplesDir: EXAMPLES_DIR, examples: [] };
  try {
    browser = await chromium.launch();
    for (const ex of examples) {
      console.log("- " + ex.name);
      const record = await auditExample(browser, server, ex);
      console.log("  mode: " + record.mode);
      transcript.examples.push(record);
    }
  } finally {
    if (browser) await browser.close();
    await server.close();
  }
  fs.writeFileSync(path.join(OUT_DIR, "transcript.json"), JSON.stringify(transcript, null, 2), "utf8");
  writeMarkdown(transcript);
  const cmhOk = writeCmhReport(transcript);
  console.log("\nTranscript:      " + path.join(OUT_DIR, "transcript.json"));
  console.log("Report (CMH):    " + REPORT + (cmhOk ? "" : " (plain HTML fallback - commentable-html tool unavailable)"));
  console.log("Report (md):     " + MD_REPORT);
  if (args.open) openInBrowser(REPORT);
  // A degraded run (any viewport whose runtime never signalled ready) is a real
  // audit failure, so exit non-zero: automation can trust the exit status.
  const failed = transcript.examples.flatMap((ex) => ex.viewports).filter((v) => !v.loaded);
  if (failed.length) {
    console.error("\n" + failed.length + " viewport(s) failed to load; the audit is degraded.");
    process.exitCode = 1;
  }
}

main().catch((e) => { console.error(e); process.exit(1); });




