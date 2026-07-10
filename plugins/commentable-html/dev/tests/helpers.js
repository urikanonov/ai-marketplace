// Shared helpers for the commentable-html E2E suite.
import { pathToFileURL, fileURLToPath } from "url";
import path from "path";
import os from "os";
import fs from "fs";
import http from "http";
import { spawnSync } from "child_process";
import { expect } from "@playwright/test";

// The Python interpreter name varies by platform: Linux and most CI runners expose only
// `python3`, while Windows dev boxes usually expose `python`. Resolve it once so the
// subprocess specs (mark_handled.py / validate.py) run on both without a spawn ENOENT.
export const PYTHON = (() => {
  for (const cmd of ["python3", "python"]) {
    try { if (spawnSync(cmd, ["--version"]).status === 0) return cmd; } catch (e) { /* try next */ }
  }
  return "python";
})();

// Marketplace pkg/dev split: this suite lives under dev/tests, but the runtime skill it
// exercises (TEMPLATE.html, dist/, examples/, tools/) ships under pkg. Test-only assets
// (fixtures) and node_modules stay under dev. SKILL points at the shipped skill root; DEV
// points at this dev tree.
export const DEV = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const SKILL = path.resolve(DEV, "..", "pkg", "skills", "commentable-html");
export const INLINE = path.join(SKILL, "TEMPLATE.html");
export const DIST = path.join(SKILL, "dist");
export const ECONOMY = path.join(DIST, "ECONOMY.html");
export const FIXTURES = path.join(DEV, "tests", "fixtures");
export const KITCHEN_SINK = path.join(FIXTURES, "kitchen-sink.html");
export const KITCHEN_SINK_ECONOMY = path.join(FIXTURES, "economy", "kitchen-sink.html");
export const fileUrl = (p) => pathToFileURL(p).href;

// The layer copies via navigator.clipboard.writeText; capture it deterministically
// so clipboard assertions do not depend on file:// clipboard permissions.
export async function installClipboardCapture(page) {
  await page.addInitScript(() => {
    window.__copied = [];
    try {
      const c = navigator.clipboard;
      if (c && c.writeText) {
        const orig = c.writeText.bind(c);
        c.writeText = (t) => { window.__copied.push(String(t)); try { return orig(t).catch(() => {}); } catch (e) { return Promise.resolve(); } };
      }
    } catch (e) { /* ignore */ }
  });
}

export const ready = (page) =>
  page.waitForFunction(() => window.__commentableHtmlReady === true, null, { timeout: 8000 });

// Prove the offline guarantee: abort and RECORD every non-local HTTP(S) request
// (including the mermaid CDN) so a test can assert the page reached out to nothing.
// file:// and localhost/127.0.0.1 (the static server) are allowed through. Mermaid is
// only ever served locally by routeMermaidLocal (which fulfills from vendored files),
// never by falling through to the network here.
export async function denyExternalNetwork(page) {
  page.__external = [];
  await page.route(/^https?:\/\//, async (route) => {
    const url = route.request().url();
    if (/^https?:\/\/(localhost|127\.0\.0\.1)(:|\/)/.test(url)) return route.fallback();
    page.__external.push(url);
    await route.abort();
  });
}

// The most recent toast text while it is showing (empty string if none).
export async function currentToast(page) {
  return page.evaluate(() => {
    const t = document.getElementById("toast");
    return t && t.classList.contains("show") ? (t.textContent || "") : "";
  });
}

// Distinct data-cid values in creation order (newest last), for picking a specific comment.
export async function allCids(page) {
  return page.$$eval("mark.cm-hl", (els) => [...new Set(els.map((e) => e.dataset.cid))]);
}

// The full Copy-all bundle text (via the captured clipboard). Requires a prior
// installClipboardCapture(page) and a Copy-all click.
export function copiedBundle(page) {
  return page.evaluate(() => (window.__copied && window.__copied.length ? window.__copied[window.__copied.length - 1] : null));
}

export async function openInline(page) {
  await installClipboardCapture(page);
  await page.goto(fileUrl(INLINE));
  await ready(page);
}

export async function openEconomy(page) {
  await installClipboardCapture(page);
  await page.goto(fileUrl(ECONOMY));
  await ready(page);
}

export async function openKitchenSink(page) {
  await installClipboardCapture(page);
  await page.goto(fileUrl(KITCHEN_SINK));
  await ready(page);
}

export async function openKitchenSinkEconomy(page) {
  await installClipboardCapture(page);
  await page.goto(fileUrl(KITCHEN_SINK_ECONOMY));
  await ready(page);
}

// Select an element's text (a real drag) and fire `event` (mouseup or contextmenu),
// which is what pops the "Add comment" menu. Returns without opening the composer.
export async function selectText(page, selector, { index = 0, event = "mouseup" } = {}) {
  await page.evaluate(({ sel, i, ev }) => {
    const el = document.querySelectorAll(sel)[i];
    if (!el) throw new Error("no element for selector " + sel + " [" + i + "]");
    el.scrollIntoView({ block: "center" });
    const range = document.createRange();
    // Anchor inside real text nodes (a user dragging across text), not on the
    // element edge - a block-boundary range can normalize just outside the block
    // and lose e.g. the isCode classification.
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const first = walker.nextNode();
    if (first) {
      let last = first, n;
      while ((n = walker.nextNode())) last = n;
      range.setStart(first, first.data.length > 2 ? 1 : 0);
      range.setEnd(last, last.data.length);
    } else {
      range.selectNodeContents(el);
    }
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(range);
    el.dispatchEvent(new MouseEvent(ev, { bubbles: true, clientX: 40, clientY: 40 }));
  }, { sel: selector, i: index, ev: event });
}

// Open the composer for a selection (menu -> Add comment), returning the composer.
export async function openComposerFor(page, selector, { index = 0, event = "mouseup" } = {}) {
  await selectText(page, selector, { index, event });
  await page.locator("#menuComment").click();
  return page.locator(".cm-composer").last();
}

// Full flow: select -> popup -> composer -> save. `index` picks among matches.
export async function addTextComment(page, selector, note, index = 0) {
  const composer = await openComposerFor(page, selector, { index });
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toHaveCount(0);
}

export async function openToolbarMenu(page) {
  if (await page.locator("#toolbarMenu").isHidden()) await page.click("#btnToolbarMenu");
  await expect(page.locator("#toolbarMenu")).toBeVisible();
}

export async function lastCopied(page) {
  return page.evaluate(() => (window.__copied && window.__copied.length ? window.__copied[window.__copied.length - 1] : null));
}

// A REAL mouse drag across an element's text (down -> move -> up), producing a
// genuine browser selection + native mouseup. Returns a point inside the
// selection so callers can also issue a real right-click. Falls back is not
// needed: every fixture target has laid-out text.
export async function realDragSelect(page, selector, { index = 0 } = {}) {
  const box = await page.evaluate(({ sel, i }) => {
    const el = document.querySelectorAll(sel)[i];
    if (!el) throw new Error("no element for selector " + sel + " [" + i + "]");
    el.scrollIntoView({ block: "center" });
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const first = walker.nextNode();
    let last = first, n;
    while ((n = walker.nextNode())) last = n;
    const r = document.createRange();
    r.setStart(first, Math.min(1, first.data.length));
    r.setEnd(last, last.data.length);
    const rects = [...r.getClientRects()].filter((x) => x.width > 0 && x.height > 0);
    const a = rects[0], b = rects[rects.length - 1];
    return { x1: a.left + 1, y1: a.top + a.height / 2, x2: b.right - 1, y2: b.top + b.height / 2 };
  }, { sel: selector, i: index });
  await page.mouse.move(box.x1, box.y1);
  await page.mouse.down();
  await page.mouse.move((box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2, { steps: 6 });
  await page.mouse.move(box.x2, box.y2, { steps: 6 });
  await page.mouse.up();
  return { midX: (box.x1 + box.x2) / 2, midY: (box.y1 + box.y2) / 2 };
}

// One comment can paint several <mark> spans (a selection crossing inline
// elements), so count distinct data-cid groups, not raw marks.
export async function distinctCids(page) {
  return page.$$eval("mark.cm-hl", (els) => new Set(els.map((e) => e.dataset.cid)).size);
}

// Concatenated text of every <mark> that shares a data-cid, i.e. the text the
// highlight currently covers - used to prove a comment re-anchored to the SAME text.
export async function markTextForCid(page, cid) {
  return page.$$eval("mark.cm-hl", (els, id) =>
    els.filter((e) => e.dataset.cid === id).map((e) => e.textContent).join(""), cid);
}

// The comments array persisted in localStorage for the open document.
export async function storedComments(page) {
  return page.evaluate(() => {
    const k = (document.getElementById("commentRoot") || document.body).dataset.commentKey
      || ("commentable-html:" + location.pathname);
    return JSON.parse(localStorage.getItem(k) || "[]");
  });
}

export function readDownload(download) {
  return download.path().then((p) => fs.readFileSync(p, "utf8"));
}

// Copy dist/ECONOMY.html (+ optionally its companions) into a fresh temp dir and
// return the path to the copied HTML. `companions=false` simulates a broken share.
export function stageEconomy({ companions = true, mutate = null } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_e2e_"));
  let html = fs.readFileSync(ECONOMY, "utf8");
  if (mutate) html = mutate(html);
  fs.writeFileSync(path.join(dir, "ECONOMY.html"), html);
  if (companions) {
    for (const f of fs.readdirSync(DIST)) {
      if (/^commentable-html\.v.*\.(css|js)$/.test(f)) fs.copyFileSync(path.join(DIST, f), path.join(dir, f));
    }
  }
  return { dir, html: path.join(dir, "ECONOMY.html") };
}

// Copy a self-contained inline document (TEMPLATE.html by default, or any other
// fixture) into a fresh temp dir so a test can mutate it (e.g. append a handled id)
// without touching the committed file.
export function stageInline({ mutate = null, source = INLINE } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_e2e_"));
  let html = fs.readFileSync(source, "utf8");
  if (mutate) html = mutate(html);
  const p = path.join(dir, "doc.html");
  fs.writeFileSync(p, html);
  return { dir, html: p };
}

// A tiny static server. Needed for the mermaid path only: mermaid loads via an ES
// module dynamic import from a CDN, which browsers block over file://, so the
// diagram only renders when the page is served over http.
export async function startStaticServer(dir) {
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(req.url.split("?")[0]);
    const p = path.normalize(path.join(dir, rel));
    if (!p.startsWith(dir)) { res.writeHead(403); res.end(); return; }
    fs.readFile(p, (e, data) => {
      if (e) { res.writeHead(404); res.end(); return; }
      const ext = path.extname(p);
      const ct = ext === ".html" ? "text/html" : ext === ".js" ? "text/javascript"
        : ext === ".css" ? "text/css" : "application/octet-stream";
      res.writeHead(200, { "Content-Type": ct });
      res.end(data);
    });
  });
  await new Promise((r) => server.listen(0, r));
  const port = server.address().port;
  return { url: `http://localhost:${port}`, close: () => new Promise((r) => server.close(r)) };
}

// Serve mermaid's CDN import (and its chunk imports) from the locally vendored
// node_modules/mermaid/dist, so mermaid renders with NO network access. The local
// main module imports its own relative chunks, which resolve against the CDN base
// and are intercepted here too - fully self-consistent regardless of CDN version.
export async function routeMermaidLocal(page) {
  const distRoot = path.join(DEV, "node_modules", "mermaid");
  const vendored = JSON.parse(fs.readFileSync(path.join(distRoot, "package.json"), "utf8")).version;
  await page.route(/cdn\.jsdelivr\.net\/npm\/mermaid@/, async (route) => {
    const u = new URL(route.request().url());
    const reqMajor = (u.pathname.match(/mermaid@(\d+)/) || [])[1];
    if (reqMajor && reqMajor !== String(vendored).split(".")[0]) {
      throw new Error(`mermaid version mismatch: template requests @${reqMajor}, vendored is ${vendored}`);
    }
    const rel = u.pathname.replace(/^\/npm\/mermaid@[^/]+\//, "");
    try {
      const body = fs.readFileSync(path.join(distRoot, rel));
      await route.fulfill({ body, contentType: "text/javascript", headers: { "access-control-allow-origin": "*" } });
    } catch (e) {
      await route.abort();
    }
  });
  // The suite must be fully offline: deny any other remote request, but allow the
  // local static server (localhost/127.0.0.1) and file:// documents through.
  await page.route(/^https?:\/\//, async (route) => {
    const url = route.request().url();
    if (/cdn\.jsdelivr\.net\/npm\/mermaid@/.test(url)) return route.fallback();
    if (/^https?:\/\/(localhost|127\.0\.0\.1)(:|\/)/.test(url)) return route.fallback();
    await route.abort();
  });
}
