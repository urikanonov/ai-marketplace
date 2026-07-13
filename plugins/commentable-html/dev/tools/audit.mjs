#!/usr/bin/env node
// audit.mjs - AI-driven UX audit harness for any commentable HTML document.
//
// Opens a target commentable HTML (a deck or a flat document) in a headless browser, drives a
// scripted tour of its features across several viewports and both colour schemes, and records
// screenshots plus machine observations (console errors, external network requests, layout
// overflow, and chrome that overlaps content). The output is meant to be reviewed by an AI agent:
// it reads observations.json and looks at the screenshots, then writes a UX audit. Because the run
// is deterministic and fully parameterised, several agents can run the same audit (on the same or
// different targets) and their findings compared. See dev/AUDIT.md for the full workflow.
//
// Usage (run from plugins/commentable-html/dev):
//   node tools/audit.mjs --target <file.html> --out <dir> [--label NAME] [--max-slides N]
//
// Exit code is 0 even when issues are found (issues are DATA in observations.json, not a failure);
// it is non-zero only when the harness itself cannot run (bad target, browser launch failure).

import { chromium } from "@playwright/test";
import { pathToFileURL } from "url";
import fs from "fs";
import path from "path";

function parseArgs(argv) {
  const a = { target: null, out: null, label: null, maxSlides: 8 };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (k === "--target") a.target = argv[++i];
    else if (k === "--out") a.out = argv[++i];
    else if (k === "--label") a.label = argv[++i];
    else if (k === "--max-slides") {
      const n = parseInt(argv[++i], 10);
      a.maxSlides = Number.isNaN(n) ? 8 : Math.max(1, Math.min(200, n));
    }
  }
  return a;
}

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "laptop", width: 1280, height: 720 },
  { name: "mobile", width: 390, height: 844 },
];

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.target || !fs.existsSync(args.target)) {
    console.error("audit: --target <existing file.html> is required");
    return 1;
  }
  const outDir = args.out || path.join(path.dirname(args.target),
    "audit-" + path.basename(args.target).replace(/\W+/g, "-"));
  const shotsDir = path.join(outDir, "screenshots");
  fs.mkdirSync(shotsDir, { recursive: true });
  const url = pathToFileURL(path.resolve(args.target)).href;
  const label = args.label || path.basename(args.target);

  // Store only the basename in the shared artifact: observations.json and report.md are meant to
  // travel to other reviewing agents, so they must not leak an absolute path (which embeds the OS
  // username). The absolute file:// url stays a local variable used only to drive the browser.
  const obs = {
    target: path.basename(args.target), label, generatedAt: new Date().toISOString(),
    isDeck: false, slideCount: 0, steps: [], console: [], pageErrors: [],
    externalRequests: [], issues: [],
  };
  const shots = [];

  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();

  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") obs.console.push({ type: m.type(), text: m.text() });
  });
  page.on("pageerror", (e) => obs.pageErrors.push(String(e)));
  page.on("request", (r) => {
    const u = r.url();
    if (/^https?:\/\//.test(u) && !/^https?:\/\/(localhost|127\.0\.0\.1)/.test(u)) obs.externalRequests.push(u);
  });

  async function shot(name, note) {
    const file = String(shots.length + 1).padStart(2, "0") + "-" + name + ".png";
    await page.screenshot({ path: path.join(shotsDir, file) });
    shots.push({ file, name, note: note || "" });
    obs.steps.push({ name, note: note || "", screenshot: "screenshots/" + file });
    return file;
  }

  async function detectOverflow() {
    return page.evaluate(() => {
      const root = document.getElementById("commentRoot") || document.body;
      const issues = [];
      root.querySelectorAll("*").forEach((el) => {
        if (el.closest(".cm-skip")) return;
        const cs = getComputedStyle(el);
        const t = (el.tagName + "." + (el.className || "").toString().split(/\s+/)[0]).slice(0, 40);
        if (el.scrollWidth - el.clientWidth > 4 && cs.overflowX !== "auto" && cs.overflowX !== "scroll") {
          if (el.clientWidth > 40) issues.push({ kind: "overflow-x", el: t, by: el.scrollWidth - el.clientWidth });
        }
        // Vertical clipping: content taller than a CLIPPED (overflow:hidden/clip) box is silently
        // cut off - the dominant fixed-stage deck defect (a slide taller than 1080px). Only flag
        // genuinely clipped boxes so a normally-scrolling flat document is not falsely flagged.
        if (el.scrollHeight - el.clientHeight > 4 && (cs.overflowY === "hidden" || cs.overflowY === "clip")) {
          if (el.clientHeight > 40) issues.push({ kind: "clip-y", el: t, by: el.scrollHeight - el.clientHeight });
        }
      });
      return issues.slice(0, 20);
    });
  }

  async function tourDeck() {
    const info = await page.evaluate((max) => {
      const n = window.__cmhDeck.slideCount();
      return { n, ids: Array.from({ length: Math.min(n, max) }, (_, i) => i) };
    }, args.maxSlides);
    obs.slideCount = info.n;
    for (const i of info.ids) {
      await page.evaluate((idx) => window.__cmhDeck.showSlide(idx), i);
      await page.waitForTimeout(150);
      await shot("slide-" + (i + 1), "slide " + (i + 1) + " of " + info.n);
    }
    // comment mode
    const toggle = page.locator(".cmh-deck-mode-toggle");
    if (await toggle.count()) {
      await toggle.click();
      await page.waitForTimeout(150);
      await shot("comment-mode", "comment mode enabled (force-reveal on)");
    }
    // a sample comment on the current slide's text, then the deck-aware jump back
    await page.evaluate(() => window.__cmhDeck.showSlideById(window.__cmhDeck.activeSlideId()));
    const added = await tryAddComment(".slide.active p, .slide.active li, .slide.active h1, .slide.active h2");
    if (added) {
      await shot("comment-added", "a comment added on a slide; sidebar open");
      await page.evaluate(() => window.__cmhDeck.showSlide(0));
      await page.waitForTimeout(120);
      const card = page.locator(".cm-card").first();
      if (await card.count()) { await card.click(); await page.waitForTimeout(200); await shot("card-jump", "clicking the card jumped to the owning slide"); }
    }
  }

  async function tourFlat() {
    await shot("top", "top of the document");
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight * 0.5));
    await page.waitForTimeout(120);
    await shot("mid-scroll", "mid document");
    const added = await tryAddComment("#commentRoot p, #commentRoot li");
    if (added) await shot("comment-added", "a text comment added; sidebar open");
    // toolbar overflow menu / help
    const help = page.locator("#btnHelp, [data-act='help']").first();
    if (await help.count()) { try { await help.click({ timeout: 1000 }); await page.waitForTimeout(150); await shot("help", "help modal"); await page.keyboard.press("Escape"); } catch (e) { /* best effort */ } }
  }

  async function tryAddComment(selector) {
    try {
      const ok = await page.evaluate((sel) => {
        const el = document.querySelector(sel);
        if (!el) return false;
        const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        const first = w.nextNode(); let last = first, n;
        while ((n = w.nextNode())) last = n;
        if (!first) return false;
        const r = document.createRange();
        r.setStart(first, Math.min(1, first.data.length)); r.setEnd(last, last.data.length);
        const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
        el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 60, clientY: 60 }));
        return true;
      }, selector);
      if (!ok) return false;
      const menu = page.locator("#menuComment");
      await menu.click({ timeout: 1500 });
      const composer = page.locator(".cm-composer").last();
      await composer.locator("textarea").fill("Audit sample comment.");
      await composer.locator('[data-act="save"]').click();
      await page.waitForTimeout(200);
      return true;
    } catch (e) { obs.issues.push({ kind: "comment-flow", detail: String(e).slice(0, 200) }); return false; }
  }

  for (const vp of VIEWPORTS) {
    for (const scheme of ["light", "dark"]) {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(url);
      try { await page.waitForFunction(() => window.__commentableHtmlReady === true, null, { timeout: 8000 }); }
      catch (e) { obs.issues.push({ kind: "not-ready", viewport: vp.name, detail: "layer did not signal ready in 8s" }); }
      obs.isDeck = await page.evaluate(() => typeof window.__cmhDeck === "object");
      await shot(vp.name + "-" + scheme + "-load", vp.name + " " + vp.width + "x" + vp.height + " / " + scheme);
      const overflow = await detectOverflow();
      if (overflow.length) obs.issues.push({ kind: "overflow", viewport: vp.name, scheme, items: overflow });
      // Full feature tour only once, on the primary laptop/light pass, to keep the run fast.
      if (vp.name === "laptop" && scheme === "light") {
        if (obs.isDeck) await tourDeck(); else await tourFlat();
      }
    }
  }

  await browser.close();

  fs.writeFileSync(path.join(outDir, "observations.json"), JSON.stringify(obs, null, 2));
  fs.writeFileSync(path.join(outDir, "report.md"), buildReport(obs, shots));
  console.log("audit: " + shots.length + " screenshot(s) -> " + shotsDir);
  console.log("audit: observations -> " + path.join(outDir, "observations.json"));
  console.log("audit: isDeck=" + obs.isDeck + " slides=" + obs.slideCount
    + " console=" + obs.console.length + " pageErrors=" + obs.pageErrors.length
    + " externalRequests=" + new Set(obs.externalRequests).size + " issues=" + obs.issues.length);
  return 0;
}

function buildReport(obs, shots) {
  const lines = [];
  lines.push("# UX audit input: " + obs.label, "");
  lines.push("- Target: `" + obs.target + "`");
  lines.push("- Type: " + (obs.isDeck ? "deck (" + obs.slideCount + " slides)" : "flat document"));
  lines.push("- Console errors/warnings: " + obs.console.length);
  lines.push("- Uncaught page errors: " + obs.pageErrors.length);
  lines.push("- Distinct external requests (egress): " + new Set(obs.externalRequests).size);
  lines.push("- Auto-detected issues: " + obs.issues.length, "");
  lines.push("## Screenshots (review each for UX problems)", "");
  for (const s of shots) lines.push("- `screenshots/" + s.file + "` - " + s.name + (s.note ? " (" + s.note + ")" : ""));
  lines.push("", "## Machine observations", "");
  if (obs.pageErrors.length) lines.push("### Page errors", ...obs.pageErrors.map((e) => "- " + e), "");
  if (obs.console.length) lines.push("### Console", ...obs.console.slice(0, 30).map((c) => "- [" + c.type + "] " + c.text), "");
  if (obs.externalRequests.length) lines.push("### External requests", ...[...new Set(obs.externalRequests)].map((u) => "- " + u), "");
  if (obs.issues.length) lines.push("### Detected issues", ...obs.issues.map((i) => "- " + JSON.stringify(i)), "");
  lines.push("", "## What the reviewing agent should do", "");
  lines.push("Open each screenshot and judge the experience: does chrome overlap content, is the",
    "stage/text legible and correctly sized, is navigation clear (slide counter, prev/next), does",
    "comment mode read well, are light and dark both acceptable, and is mobile usable. Cross-check",
    "the machine observations (egress should be empty for an Export-Offline deck; there should be no",
    "page errors). Produce a findings list (severity + fix) and, ideally, a commentable-html audit",
    "report so the findings can themselves be reviewed and iterated.");
  return lines.join("\n") + "\n";
}

main().then((c) => process.exit(c)).catch((e) => { console.error(e); process.exit(2); });
