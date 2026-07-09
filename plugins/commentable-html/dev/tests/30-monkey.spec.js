import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import {
  fileUrl, ready, SKILL, KITCHEN_SINK, storedComments, distinctCids,
  installClipboardCapture, stageInline, startStaticServer, routeMermaidLocal,
} from "./helpers.js";

const EXAMPLE = path.join(SKILL, "examples", "community-garden.html");

// Seeded PRNG so any failure replays deterministically (same generator as 08-noise).
const prngInit = (seed) => `
  let s = ${seed} >>> 0;
  window.__rng = () => {
    s |= 0; s = (s + 0x6D2B79F5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };`;

// Hard-failure watcher: any uncaught exception (pageerror) or genuine console error
// is a monkey-test failure. Network/asset noise (favicon over file://, aborted
// external routes, ResizeObserver loop) is not an app crash, so it is filtered out.
function watchErrors(page) {
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + (e && e.stack ? e.stack : e)));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    if (/favicon|Failed to load resource|net::ERR|ERR_|ResizeObserver loop limit|access to font|CORS/i.test(t)) return;
    errors.push("console.error: " + t);
  });
  return errors;
}

// Every action is best-effort and side-effect-only: it fires a real handler on a random
// visible target and returns any SYNCHRONOUS throw it caused (async throws surface via
// the pageerror listener). A missing target is a no-op, never a failure - the monkey is
// testing that NOTHING the layer does throws, not that a specific control exists.
const ACTIONS = [
  "sort", "codecopy", "kqlcopy", "diffsyntax", "caret", "expandall", "collapseall",
  "scrolltop", "scrollbottom", "sidebar", "menu", "copyall", "help", "closemodal",
  "scroll", "mermaidhover", "charthover", "themetoggle",
];

async function doAction(page, name) {
  return page.evaluate((action) => {
    const rng = window.__rng || Math.random;
    const vis = (sel) => [...document.querySelectorAll(sel)].filter((e) => e.getClientRects().length);
    const pick = (list) => (list.length ? list[Math.floor(rng() * list.length)] : null);
    const byText = (sel, txt) => vis(sel).filter((e) => (e.textContent || "").trim() === txt);
    let hit = false;
    const clk = (e) => { if (e) { e.click(); hit = true; } };
    const hover = (e) => { if (e) { const r = e.getBoundingClientRect(); e.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 })); hit = true; } };
    try {
      switch (action) {
        case "sort": clk(pick(vis("table.cmh-sortable th"))); break;
        case "codecopy": clk(pick(vis(".cm-code-copy"))); break;
        case "kqlcopy": clk(pick(vis(".cmh-kql-title"))); break;
        case "diffsyntax": clk(pick(vis(".cmh-diff-toggle"))); break;
        case "caret": clk(pick(vis(".cmh-sec-caret"))); break;
        case "expandall": clk(pick(byText(".cm-side-toc-top", "Expand All"))); break;
        case "collapseall": clk(pick(byText(".cm-side-toc-top", "Collapse All"))); break;
        case "scrolltop": clk(pick(byText(".cm-side-toc-top", "Scroll to Top"))); break;
        case "scrollbottom": clk(pick(vis(".cm-side-toc-bottom"))); break;
        case "sidebar": clk(document.getElementById("btnToggleSidebar")); break;
        case "menu": { const e = document.getElementById("btnToolbarMenu"); if (e && e.getClientRects().length) clk(e); break; }
        case "copyall": { const e = document.getElementById("btnCopyAll") || document.getElementById("btnCopyAllTop"); if (e && e.getClientRects().length) clk(e); break; }
        case "help": { const e = document.getElementById("btnHelpTop") || document.getElementById("btnHelp"); if (e && e.getClientRects().length) clk(e); break; }
        case "closemodal": clk(document.querySelector(".cm-modal .cm-x, .cm-modal [data-act='close'], .cm-help .cm-x")); break;
        case "scroll": window.scrollTo(0, Math.floor(rng() * Math.max(1, document.body.scrollHeight))); hit = true; break;
        case "themetoggle": { const e = document.getElementById("btnTheme") || document.getElementById("btnThemeTop"); if (e && e.getClientRects().length) clk(e); break; }
        case "mermaidhover": hover(pick(vis(".cm-mermaid-host .node, .cm-mermaid-host .actor, .cm-mermaid-host g.task, .cm-mermaid-host rect"))); break;
        case "charthover": hover(pick(vis("canvas"))); break;
      }
      return { err: null, hit };
    } catch (err) {
      return { err: "sync throw in '" + action + "': " + (err && err.stack ? err.stack : err), hit };
    }
  }, name);
}

// Best-effort comment add on a random not-yet-highlighted paragraph, interleaved with
// the chrome fuzz so comment CRUD races the UI. It NEVER asserts success (that is
// 08-noise's job); it only proves the flow throws nothing and leaves no stuck composer.
async function tryAddComment(page, note) {
  const popped = await page.evaluate(() => {
    const root = document.getElementById("commentRoot");
    const ps = [...root.querySelectorAll("p, li")].filter((p) => {
      if (p.closest(".cm-skip") || p.closest("mark.cm-hl")) return false;
      return (p.textContent || "").trim().length >= 8 && p.getClientRects().length;
    });
    if (!ps.length) return false;
    const p = ps[Math.floor((window.__rng || Math.random)() * ps.length)];
    const tn = [...p.childNodes].find((n) => n.nodeType === 3 && n.data.trim().length >= 6);
    if (!tn) return false;
    const r = document.createRange();
    r.setStart(tn, 1); r.setEnd(tn, Math.min(tn.data.length, 5));
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
    p.scrollIntoView({ block: "center" });
    p.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    return true;
  });
  if (!popped) return;
  await page.waitForTimeout(10);
  const menu = page.locator("#menuComment");
  if (!(await menu.isVisible().catch(() => false))) return;
  await menu.click().catch(() => {});
  const composer = page.locator(".cm-composer").last();
  if (!(await composer.count())) return;
  await composer.locator("textarea").fill(note).catch(() => {});
  await composer.locator('[data-act="save"]').click().catch(() => {});
}

async function closeAnyComposer(page) {
  await page.evaluate(() => {
    document.querySelectorAll(".cm-composer [data-act='cancel']").forEach((b) => b.click());
    document.querySelectorAll(".cm-modal .cm-x, .cm-help .cm-x").forEach((b) => b.click());
  });
}

// The core loop: N random actions, asserting after EACH that the app neither threw nor
// broke its ready flag, then a reload that must come back clean with comments intact.
async function monkey(page, errors, { steps, addEvery, minDistinct }) {
  await ready(page);
  page.on("dialog", (d) => d.accept().catch(() => {}));
  const exercised = new Set();
  for (let i = 0; i < steps; i++) {
    const action = ACTIONS[Math.floor((await page.evaluate(() => (window.__rng || Math.random)())) * ACTIONS.length)];
    const { err, hit } = await doAction(page, action);
    expect(err, `step ${i} (${action}) threw synchronously`).toBeNull();
    if (hit) exercised.add(action);
    if (addEvery && i % addEvery === addEvery - 1) await tryAddComment(page, "monkey " + i);
    await page.waitForTimeout(8);
    expect(errors, `hard error after step ${i} (${action})`).toEqual([]);
    const alive = await page.evaluate(() => window.__commentableHtmlReady === true);
    expect(alive, `layer still alive after step ${i} (${action})`).toBe(true);
  }
  // Guard against a vacuous pass: the fuzz must have actually driven a broad set of
  // real controls, not silently no-op'd because a selector drifted.
  expect(exercised.size, `distinct controls exercised (${[...exercised].join(",")})`).toBeGreaterThanOrEqual(minDistinct);
  await closeAnyComposer(page);
  const before = await distinctCids(page);
  await page.reload();
  await ready(page);
  expect(errors, "hard error after reload").toEqual([]);
  expect(await distinctCids(page), "comments survive the reload").toBe(before);
}

for (const seed of [0xa11ce, 0xf00d1e]) {
  test(`monkey: random chrome + render fuzz never crashes on kitchen-sink (seed ${seed})`, async ({ page }) => {
    const { html, dir } = stageInline({ source: KITCHEN_SINK });
    const errors = watchErrors(page);
    try {
      await installClipboardCapture(page);
      await page.addInitScript(prngInit(seed));
      await page.goto(fileUrl(html));
      await monkey(page, errors, { steps: 50, addEvery: 6, minDistinct: 6 });
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
}

test("monkey: full-feature fuzz including mermaid + chart never crashes (example over http)", async ({ page }) => {
  const { html, dir } = stageInline({ source: EXAMPLE });
  const server = await startStaticServer(dir);
  const errors = watchErrors(page);
  try {
    await installClipboardCapture(page);
    await routeMermaidLocal(page);
    await page.addInitScript(prngInit(0xbead5));
    await page.goto(`${server.url}/${path.basename(html)}`);
    // let mermaid + the chart canvas finish their async render before fuzzing them
    await ready(page);
    await page.waitForTimeout(400);
    await monkey(page, errors, { steps: 30, addEvery: 5, minDistinct: 8 });
  } finally {
    await server.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
