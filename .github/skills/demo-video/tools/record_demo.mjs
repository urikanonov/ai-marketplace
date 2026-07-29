#!/usr/bin/env node
// Demo video recorder for this marketplace: films short, publishable clips of the things this repo
// ships, so a reader can SEE them instead of reading about them.
//
// Two subjects, one video pipeline (Chromium via Playwright, so both clips come out as the same
// .webm):
//
//   report    drive a commentable-html example in a browser and film a paced montage of the skill's
//             abilities, with a synthetic cursor so a viewer can follow what is being clicked.
//   capture   run a REAL command (a live Copilot CLI session, multi-duck and all) in a ConPTY,
//             proxying stdin and stdout so the session is genuinely interactive, and tee every
//             output chunk with its timestamp into a cast file.
//   render    replay a cast into a real terminal emulator on a COMPRESSED clock - the long waits a
//             model or a test run costs collapse into a short "skipping ahead" beat - and film it.
//   scan      re-check a cast or transcript for anything that must not be published.
//
// Capture and render are separate on purpose: a live recording cannot fast-forward time that has not
// happened yet, and splitting them means one real session can be re-rendered at any length or speed
// without running Copilot again.
//
// NOTHING it produces is committed. Casts, transcripts and clips all land in the gitignored tmp/.
//
// Privacy: a real session is full of things a published clip must not carry. Output is scrubbed
// (tools/redact.mjs) BEFORE it is written to disk, a plain transcript is always written for a human
// to read, and `render` refuses to film a cast that still scans dirty. That is a safety net, not a
// substitute for watching the clip before you publish it.
//
// Usage:
//   node record_demo.mjs report  [--seconds 10] [--example <file>] [--out <file.webm>] [--list]
//   node record_demo.mjs loop    --cast <file.cast.json> --example <report.html> [--split paste]
//   node record_demo.mjs capture [--out <file.cast.json>] [--cols 120] [--rows 30] [--script <f.json>] -- <command...>
//   node record_demo.mjs render  --cast <file.cast.json> [--seconds 45] [--out <file.webm>]
//   node record_demo.mjs scan    --cast <file.cast.json>

import { pathToFileURL, fileURLToPath } from "url";
import { createRequire } from "module";
import path from "path";
import fs from "fs";
import os from "os";
import http from "http";

import { planBeats, fitTimeline, compressTimeline, coalesceEvents, applySpeedWindows, parseSpeedWindows, MIN_BEAT_MS } from "./timeline.mjs";
import { REPORT_BEATS } from "./report-beats.mjs";
import { DEFAULT_RULES, homeRules, scanText, scrubEvents, scrubText, createScrubber } from "./redact.mjs";
import { readScript, stepReady, stepPayload, stepSubmit } from "./script.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SKILL = path.resolve(HERE, "..");
const REPO = path.resolve(SKILL, "..", "..", "..");
const DEV = path.join(REPO, "plugins", "commentable-html", "dev");
const EXAMPLES = path.join(REPO, "plugins", "commentable-html", "examples");
const OUT_ROOT = path.join(REPO, "tmp", "demo-video");

// A montage that has to be readable, not just short: every beat is a real interaction - three
// comments, a reply and a delete among them - so packing them into ten seconds made the clip feel
// like a fast-forward of itself.
export const DEFAULT_SECONDS = 30;
const DEMO_AUTHOR = "Demo Reviewer";

const requireFrom = createRequire(import.meta.url);
const sleep = (ms) => new Promise((r) => setTimeout(r, Math.max(0, ms)));
const ensureDir = (d) => fs.mkdirSync(d, { recursive: true });

// Playwright is not a dependency of this skill; it is reused from the commentable-html dev install,
// resolved dynamically because the ESM loader ignores NODE_PATH.
function loadPlaywright() {
  const paths = [path.join(DEV, "node_modules"), path.join(SKILL, "node_modules"), path.join(REPO, "node_modules")];
  for (const pkg of ["@playwright/test", "playwright", "playwright-core"]) {
    try {
      const mod = requireFrom(requireFrom.resolve(pkg, { paths }));
      const chromium = mod.chromium || (mod.default && mod.default.chromium);
      if (chromium) return chromium;
    } catch (e) { /* try the next candidate */ }
  }
  throw new Error(
    "Playwright not found. Install the commentable-html dev tree once:\n"
    + "  python scripts/setup_dev.py",
  );
}

// node-pty and xterm are only needed for the terminal subject, and node-pty is a native module, so
// they stay OPTIONAL and local to this skill rather than becoming dependencies of the plugin dev
// tree (which CI installs with --ignore-scripts).
function loadOptional(pkg) {
  const paths = [path.join(SKILL, "node_modules"), path.join(HERE, "node_modules")];
  try {
    return requireFrom(requireFrom.resolve(pkg, { paths }));
  } catch (e) {
    throw new Error(
      `${pkg} is not installed. The terminal subject needs it; install it once, in this skill:\n`
      + `  cd ${path.relative(REPO, SKILL) || SKILL} && npm install`,
    );
  }
}

function resolveOptionalPath(pkg, ...rest) {
  const paths = [path.join(SKILL, "node_modules"), path.join(HERE, "node_modules")];
  for (const base of paths) {
    const candidate = path.join(base, pkg, ...rest);
    if (fs.existsSync(candidate)) return candidate;
  }
  throw new Error(`${pkg} is not installed. Run: cd ${SKILL} && npm install`);
}

const STRING_KEYS = new Set([
  "example", "out", "cast", "clip", "seconds", "cols", "rows", "idle", "hold",
  "width", "height", "count", "font", "frames-dir", "scale", "tail", "head", "end-hold", "intro", "ask",
  "script", "review-out", "snapshot-out", "split", "speed-windows", "example-after", "seconds-resolved", "seconds-gen", "seconds-apply", "seconds-review", "tail-gen", "tail-apply", "dpr",
]);
const KNOWN_FLAGS = new Set([...STRING_KEYS, "list", "allow-findings", "help"]);
// Which options each subject actually reads. Validating against the union instead means
// `scan --out x` or `capture --seconds 10` is accepted and then silently ignored - the caller is
// told nothing, and gets a clip that is not what they asked for.
const SUBJECT_FLAGS = {
  report: ["example", "out", "seconds", "width", "height", "scale", "list", "review-out", "snapshot-out"],
  capture: ["out", "cols", "rows", "script"],
  render: ["cast", "out", "seconds", "idle", "hold", "width", "height", "font", "scale", "tail", "head", "end-hold", "intro", "ask", "speed-windows", "allow-findings"],
  loop: ["cast", "example", "example-after", "seconds-resolved", "out", "split", "seconds-gen", "seconds-apply", "seconds-review", "tail-gen", "tail-apply", "idle", "hold", "width", "height", "font", "scale", "dpr", "intro", "end-hold", "ask", "allow-findings"],
  scan: ["cast"],
  frames: ["clip", "out", "count", "frames-dir"],
};

// The video is recorded at `scale` times the layout size. Playwright scales the page DOWN to fit a
// smaller video, so this trades pixels for file size without reflowing anything: the clip keeps the
// same layout and line breaks, just fewer pixels to encode. A terminal full of scrolling text is
// expensive to encode, and resolution is the biggest lever on it.
function videoSize(width, height, args) {
  const scale = numberOpt(args, "scale", 1);
  if (scale > 1) throw new Error("--scale must be 1 or less; it only shrinks the recording");
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

function checkSubjectFlags(args, subject) {
  const allowed = SUBJECT_FLAGS[subject];
  if (!allowed) return;
  const used = Object.keys(args).filter((k) => k !== "_" && k !== "passthrough");
  const stray = used.filter((k) => !allowed.includes(k));
  if (stray.length) {
    throw new Error(`${subject} does not use ${stray.map((k) => `--${k}`).join(", ")}`);
  }
}
function parseArgs(argv) {
  const out = { _: [], passthrough: [] };
  let afterDashes = false;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (afterDashes) { out.passthrough.push(a); continue; }
    if (a === "--") { afterDashes = true; continue; }
    if (!a.startsWith("--")) { out._.push(a); continue; }
    const eq = a.indexOf("=");
    const key = eq > 2 ? a.slice(2, eq) : a.slice(2);
    // An unknown flag is a typo, and silently ignoring it means silently ignoring what the operator
    // asked for - a clip of the wrong thing, or an unredacted cast rendered anyway.
    if (!KNOWN_FLAGS.has(key)) throw new Error(`unknown option --${key}`);
    if (Object.prototype.hasOwnProperty.call(out, key)) throw new Error(`option --${key} was given twice`);
    if (eq > 2) { out[key] = a.slice(eq + 1); continue; }
    const next = argv[i + 1];
    if (next !== undefined && !next.startsWith("--")) { out[key] = argv[++i]; }
    else if (STRING_KEYS.has(key)) { throw new Error(`Option --${key} requires a value`); }
    else { out[key] = true; }
  }
  return out;
}

function numberOpt(args, key, fallback) {
  if (args[key] == null) return fallback;
  const value = Number(args[key]);
  if (!Number.isFinite(value)) throw new Error(`Option --${key} must be a number`);
  if (value <= 0) throw new Error(`Option --${key} must be greater than zero`);
  return value;
}

function stamp() {
  return new Date().toISOString().replace(/[:.]/g, "-").replace("Z", "");
}

// Serialize a value for embedding inside a <script> block. JSON.stringify does NOT escape "<", so a
// recorded session that printed "</script>" (a tool dumping HTML, a diff of a template) would close
// the block early: the page stops parsing, the replay never signals done, and render hangs until its
// timeout with an error that says nothing about the real cause - or, worse, the markup after it runs
// as script in the render page. Captured output is arbitrary bytes, so it is escaped as data.
function scriptJson(value) {
  return JSON.stringify(value)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

// Every rule set carries the machine-identifying rules for whoever is recording, so a home path or
// an account name never reaches a published clip.
function rulesForThisMachine() {
  return [...DEFAULT_RULES, ...homeRules({ home: os.homedir(), user: os.userInfo().username })];
}

async function startStaticServer(root, routes = {}) {
  const types = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml", ".webm": "video/webm" };
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent((req.url || "/").split("?")[0]);
    // Virtual routes let a caller serve a generated page from the SAME origin as the files it
    // needs, which is what makes a file:// media element loadable at all.
    if (Object.prototype.hasOwnProperty.call(routes, rel)) {
      res.writeHead(200, { "content-type": routes[rel].type || "text/html" });
      res.end(routes[rel].body);
      return;
    }
    // `startsWith(root)` alone lets a SIBLING through: with a root of /x/examples, the path
    // /x/examples-private/secret resolves outside the root yet still starts with it. Resolve
    // against the root and compare the RELATIVE path, which is escaping or absolute for anything
    // that is not a genuine descendant. A NUL byte would truncate the path at the syscall, so it
    // is rejected outright rather than normalized away.
    const rootDir = path.resolve(root);
    if (rel.includes("\0")) { res.writeHead(400).end(); return; }
    const file = path.resolve(rootDir, path.normalize(rel).replace(/^([/\\]|[a-zA-Z]:)+/, ""));
    const within = path.relative(rootDir, file);
    if (!within || within.startsWith("..") || path.isAbsolute(within)) { res.writeHead(403).end(); return; }
    fs.readFile(file, (err, body) => {
      if (err) { res.writeHead(404).end(); return; }
      res.writeHead(200, { "content-type": types[path.extname(file).toLowerCase()] || "application/octet-stream" });
      res.end(body);
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  return {
    origin: `http://127.0.0.1:${port}`,
    async close() {
      if (server.closeAllConnections) server.closeAllConnections();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}

// A recorded video has no mouse pointer in it, so the clip gets a synthetic one: every helper that
// clicks or drags moves this dot first, which is what makes the montage readable.
const CURSOR_SCRIPT = `(() => {
  const install = () => {
    // Init scripts run in EVERY frame, and the loop clip puts the report in an iframe. A second dot
    // inside that frame would sit wherever it was left, because the driver only ever moves the top
    // one - a stray blue circle parked in the middle of the report. One cursor, on the page that
    // owns the mouse.
    if (window.top !== window) return;
    if (document.getElementById("__demoCursor")) return;
    const dot = document.createElement("div");
    dot.id = "__demoCursor";
    dot.setAttribute("aria-hidden", "true");
    dot.style.cssText = [
      "position:fixed", "left:0", "top:0", "width:22px", "height:22px", "z-index:2147483647",
      "pointer-events:none", "border-radius:50%", "background:rgba(56,139,253,0.35)",
      "border:2px solid #388bfd", "box-shadow:0 0 0 4px rgba(56,139,253,0.15)",
      "transform:translate(-50%,-50%)", "transition:transform 90ms linear, opacity 150ms linear",
      "opacity:0",
    ].join(";");
    document.documentElement.appendChild(dot);
    window.__demoCursorTo = (x, y, pressed) => {
      dot.style.opacity = "1";
      dot.style.transform = "translate(-50%,-50%) scale(" + (pressed ? 0.7 : 1) + ")";
      dot.style.left = x + "px";
      dot.style.top = y + "px";
    };
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
})();`;

// Two more things injected into every recorded page, for the same reason the cursor is: a video has
// no narrator. The TOAST names what is happening ("Commenting on an image") so a viewer can follow a
// fast montage without guessing, and the clipboard shim records what Copy all copied - reading the
// real clipboard needs a permission grant that does not exist for a file:// origin, which is exactly
// where a generated report has to be loaded from.
const OVERLAY_SCRIPT = `(() => {
  // The TOAST belongs to the top frame only - it is chrome over the whole clip, and a second copy
  // inside the report would sit behind it saying something stale.
  if (window.top === window) {
    const install = () => {
      if (document.getElementById("__demoToast")) return;
      const el = document.createElement("div");
      el.id = "__demoToast";
      el.setAttribute("aria-hidden", "true");
      // Bottom centre, not top: the report's own toolbar owns the top right, the table of contents
      // the top left, and in the loop clip the phase caption sits top centre. Sized and coloured to
      // survive being recorded at 0.6-0.75 scale - a translucent dark pill at 17px was legible in a
      // full-size frame and nearly invisible in the finished clip.
      el.style.cssText = [
        "position:fixed", "left:50%", "bottom:104px", "transform:translateX(-50%) translateY(10px)",
        "z-index:2147483646", "pointer-events:none", "padding:16px 34px", "border-radius:999px",
        "background:#b3234a", "color:#ffffff", "border:2px solid rgba(255,255,255,0.55)",
        "font:700 27px/1.15 'Segoe UI', system-ui, sans-serif", "letter-spacing:0.3px",
        "box-shadow:0 14px 40px rgba(0,0,0,0.45), 0 0 0 6px rgba(179,35,74,0.22)",
        "white-space:nowrap", "opacity:0",
        "transition:opacity 200ms ease, transform 200ms ease",
      ].join(";");
      document.documentElement.appendChild(el);
      window.__demoToast = (text) => {
        if (!text) { el.style.opacity = "0"; el.style.transform = "translateX(-50%) translateY(10px)"; return; }
        el.textContent = text;
        el.style.opacity = "1";
        el.style.transform = "translateX(-50%) translateY(0)";
      };
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
    else install();
  }

  // Record what was copied instead of reading the clipboard back. This runs in EVERY frame: in the
  // loop clip Copy all is clicked inside the report iframe, so a shim confined to the top frame
  // would record nothing and the review that gets pasted back would be empty.
  window.__demoCopied = "";
  try {
    const clip = navigator.clipboard;
    if (clip && clip.writeText) {
      const original = clip.writeText.bind(clip);
      clip.writeText = (text) => { window.__demoCopied = String(text == null ? "" : text); return original(text); };
    }
  } catch (e) { /* no clipboard in this context */ }
  // Older paths copy through a hidden textarea and execCommand.
  try {
    const exec = document.execCommand && document.execCommand.bind(document);
    if (exec) {
      document.execCommand = (cmd, ...rest) => {
        if (String(cmd).toLowerCase() === "copy") {
          const active = document.activeElement;
          if (active && typeof active.value === "string" && active.value) window.__demoCopied = active.value;
          else {
            const sel = String(window.getSelection() || "");
            if (sel) window.__demoCopied = sel;
          }
        }
        return exec(cmd, ...rest);
      };
    }
  } catch (e) { /* execCommand is not writable here */ }
})();`;

// `page` is the RECORDED page and owns the mouse and the synthetic cursor; `scope` is whatever
// holds the document being reviewed. They are the same thing for the standalone montage, and differ
// for the loop clip, where the report lives in a full-viewport iframe so the terminal can share the
// stage. Playwright reports bounding boxes relative to the MAIN frame, so page coordinates and the
// cursor keep lining up with a frame's elements without any offset arithmetic.
function makeContext(page, budgetMs, warnings, scope = page) {
  const beatStarted = Date.now();
  const moveCursor = async (x, y, pressed = false) => {
    await page.evaluate(([cx, cy, down]) => {
      if (window.__demoCursorTo) window.__demoCursorTo(cx, cy, down);
    }, [x, y, pressed]).catch(() => {});
    await page.mouse.move(x, y).catch(() => {});
  };
  const ctx = {
    budgetMs,
    warn(message) { warnings.push(message); },
    sleep,
    settle: (ms = 250) => sleep(ms),
    // Stay on the current state for whatever is left of this beat's budget, so a beat that finishes
    // early keeps its result on screen instead of handing the time to a blank pacing sleep.
    holdRemaining: (reserveMs = 0) => sleep(budgetMs - (Date.now() - beatStarted) - reserveMs),
    moveCursor,
    // The keyboard belongs to the PAGE, not to the document being reviewed - a Frame has no
    // keyboard - so beats reach it through the context rather than through their scope.
    async pressKey(key) { await page.keyboard.press(key).catch(() => {}); },
    // Names the moment on screen. A montage moves fast and a viewer who cannot tell an image comment
    // from a diagram comment learns nothing from either.
    async toast(text) {
      await page.evaluate((t) => { if (window.__demoToast) window.__demoToast(t); }, text).catch(() => {});
    },
    // Beat one opens on a still document while the runtime finishes booting. Teleporting the
    // cursor into place wastes that moment; gliding it in from the edge means the very first
    // frames after paint already have motion in them.
    async glideCursor(x, y, durationMs = 420, from = null) {
      const start = from || { x: -40, y: y + 90 };
      // Animated IN THE PAGE. Stepping it from node costs a round trip per frame, which made a
      // 420ms glide eat a second of the beat's budget; a single evaluate driving rAF is free.
      await page.evaluate(async ([sx, sy, tx, ty, ms]) => {
        if (!window.__demoCursorTo) return;
        const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - ((-2 * t + 2) ** 2) / 2);
        const begun = performance.now();
        await new Promise((done) => {
          const step = () => {
            const t = Math.min(1, (performance.now() - begun) / ms);
            const e = ease(t);
            window.__demoCursorTo(sx + (tx - sx) * e, sy + (ty - sy) * e, false);
            if (t < 1) requestAnimationFrame(step); else done();
          };
          requestAnimationFrame(step);
        });
      }, [start.x, start.y, x, y, durationMs]).catch(() => {});
      await page.mouse.move(x, y).catch(() => {});
    },
    async scrollTo(y) {
      await scope.evaluate((to) => window.scrollTo(0, to), y).catch(() => {});
    },
    // A jump cut is unreadable at speed; a short eased glide reads as a real person scrolling.
    async glideTo(y, durationMs) {
      await scope.evaluate(async ([to, ms]) => {
        const from = window.scrollY;
        const start = performance.now();
        const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - ((-2 * t + 2) ** 2) / 2);
        await new Promise((done) => {
          const step = (now) => {
            const t = Math.min(1, (now - start) / Math.max(1, ms));
            window.scrollTo(0, from + (to - from) * ease(t));
            if (t < 1) requestAnimationFrame(step); else done();
          };
          requestAnimationFrame(step);
        });
      }, [Math.max(0, y), durationMs]).catch(() => {});
    },
    // Selectors are tried IN ORDER and the first element below `after` wins. A plain comma-joined
    // querySelector cannot express that: it returns whichever match comes first in the document, so
    // asking for "a diff, else a diagram" would keep landing on an early figure instead.
    async offsetOf(selectors, { after = 0 } = {}) {
      const list = Array.isArray(selectors) ? selectors : [selectors];
      return scope.evaluate(([sels, floor]) => {
        for (const sel of sels) {
          for (const el of document.querySelectorAll(sel)) {
            const top = Math.round(window.scrollY + el.getBoundingClientRect().top);
            if (top > floor) return top;
          }
        }
        return null;
      }, [list, after]).catch(() => null);
    },
    async scrollIntoView(locator) {
      await locator.scrollIntoViewIfNeeded({ timeout: 1500 }).catch(() => {});
    },
    // Non-prose blocks (an image, a diff line, a diagram node, a chart) float their own add-comment
    // button on hover. The synthetic cursor is moved there too, and the pointer events are
    // dispatched directly as well: a canvas or an SVG node does not always react to a bare
    // mouse.move at its centre, and a beat that silently fails to hover films nothing.
    async hoverBlock(selector) {
      // Same split as dragSelect: scroll in one turn, measure and dispatch in the next, so a
      // smooth-scrolling document cannot hand back stale coordinates.
      const found = await scope.evaluate((sel) => {
        const el = [...document.querySelectorAll(sel)].find((e) => {
          const r = e.getBoundingClientRect();
          return r.width > 8 && r.height > 8;
        });
        if (!el) return false;
        const previous = document.documentElement.style.scrollBehavior;
        document.documentElement.style.scrollBehavior = "auto";
        el.scrollIntoView({ block: "center", behavior: "instant" });
        document.documentElement.style.scrollBehavior = previous;
        window.__demoHoverTarget = el;
        return true;
      }, selector).catch(() => false);
      if (!found) return false;
      await sleep(160);
      const box = await scope.evaluate(() => {
        const el = window.__demoHoverTarget;
        if (!el) return null;
        const r = el.getBoundingClientRect();
        for (const type of ["mouseenter", "mouseover", "mousemove"]) {
          el.dispatchEvent(new MouseEvent(type, {
            bubbles: true,
            clientX: r.left + r.width / 2,
            clientY: r.top + r.height / 2,
          }));
        }
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      }).catch(() => null);
      if (!box) return false;
      await moveCursor(box.x, box.y);
      await page.mouse.move(box.x, box.y).catch(() => {});
      await sleep(180);
      return true;
    },
    async waitVisible(target, timeout = 2000) {
      const locator = typeof target === "string" ? scope.locator(target) : target;
      try { await locator.waitFor({ state: "visible", timeout }); return true; } catch (e) { return false; }
    },
    async click(locator) {
      const box = await locator.boundingBox().catch(() => null);
      if (box) {
        await moveCursor(box.x + box.width / 2, box.y + box.height / 2);
        await sleep(120);
        await moveCursor(box.x + box.width / 2, box.y + box.height / 2, true);
      }
      await locator.click({ timeout: 2500 }).catch((e) => ctx.warn("click failed: " + e.message));
      if (box) await moveCursor(box.x + box.width / 2, box.y + box.height / 2);
    },
    // Typing is spread across the beat's own budget, so the montage stays on schedule whatever the
    // clip length: a 10 second cut types fast, a 30 second cut types at a readable pace.
    async type(locator, text, withinMs) {
      const delay = Math.max(8, Math.min(60, withinMs / Math.max(1, text.length)));
      await locator.click({ timeout: 2000 }).catch(() => {});
      await locator.type(text, { delay }).catch((e) => ctx.warn("typing failed: " + e.message));
    },
    async dragSelect(selector, { index = 0 } = {}) {
      // Scroll FIRST, measure second. A document that sets `scroll-behavior: smooth` (generated
      // reports often do) animates scrollIntoView, so measuring in the same turn returns rectangles
      // from before the scroll landed and the drag happens over whatever used to be there - the
      // selection silently comes back empty and a required beat films nothing.
      const found = await scope.evaluate(([sel, nth]) => {
        const els = [...document.querySelectorAll(sel)];
        const candidates = els.filter((e) => (e.textContent || "").trim().length > 80);
        const pool = candidates.length ? candidates : els;
        const el = pool[nth % Math.max(1, pool.length)];
        if (!el) return false;
        const previous = document.documentElement.style.scrollBehavior;
        document.documentElement.style.scrollBehavior = "auto";
        el.scrollIntoView({ block: "center", behavior: "instant" });
        document.documentElement.style.scrollBehavior = previous;
        window.__demoDragTarget = el;
        return true;
      }, [selector, index]).catch(() => false);
      if (!found) return false;
      await sleep(160);
      const box = await scope.evaluate(() => {
        const el = window.__demoDragTarget;
        if (!el) return null;
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        const first = walker.nextNode();
        if (!first) return null;
        let last = first, node;
        while ((node = walker.nextNode())) last = node;
        const range = document.createRange();
        range.setStart(first, Math.min(1, first.data.length));
        range.setEnd(last, last.data.length);
        const rects = [...range.getClientRects()].filter((r) => r.width > 4 && r.height > 4);
        if (!rects.length) return null;
        const a = rects[0], b = rects[rects.length - 1];
        return { x1: a.left + 2, y1: a.top + a.height / 2, x2: b.right - 2, y2: b.top + b.height / 2 };
      }).catch(() => null);
      if (!box) return false;
      await moveCursor(box.x1, box.y1);
      await sleep(120);
      await page.mouse.down();
      await moveCursor(box.x1, box.y1, true);
      const steps = 14;
      for (let i = 1; i <= steps; i++) {
        const t = i / steps;
        await moveCursor(box.x1 + (box.x2 - box.x1) * t, box.y1 + (box.y2 - box.y1) * t, true);
        await sleep(10);
      }
      await page.mouse.up();
      await moveCursor(box.x2, box.y2);
      return true;
    },
  };
  return ctx;
}

async function saveVideo(page, context, outFile) {
  const video = page.video();
  await context.close();
  if (!video) throw new Error("playwright recorded no video for this context");
  ensureDir(path.dirname(outFile));
  await video.saveAs(outFile);
  await video.delete().catch(() => {});
  return outFile;
}

// Wait for the commentable-html runtime to say it is up. The clip is filmed from
// `domcontentloaded` so the opening is not three seconds of a motionless page, but a big report
// (one 1.4 MB standalone file with mermaid and Chart.js vendored inline) does not finish booting by
// then - it signals ready only after `load`. Waiting a short beat first keeps a light report fast;
// falling back to `load` is what makes a heavy one work at all. Without this the layer was never up,
// every beat found nothing, and the only clue was a single "never signalled ready" line.
async function waitForRuntime(scope, warnings, page = null) {
  const ready = () => window.__commentableHtmlReady === true;
  if (await scope.waitForFunction(ready, null, { timeout: 4000 }).then(() => true).catch(() => false)) return true;
  await (page || scope).waitForLoadState("load").catch(() => {});
  if (await scope.waitForFunction(ready, null, { timeout: 20000 }).then(() => true).catch(() => false)) return true;
  warnings.push("the runtime never signalled ready");
  return false;
}

// Match the frame by its EXACT url. A prefix match picks the wrong document the moment two
// navigations share a prefix - which is exactly what the closing phase does, reloading the same
// file with a cache-busting query - so the montage would drive the document it had just left.
function findFrame(page, url) {
  return page.frames().find((f) => f.url() === url)
    || page.frames().find((f) => f.url().split("#")[0] === url.split("#")[0]);
}

// A diagram or chart draws asynchronously after the runtime is ready. This is awaited immediately// before the first beat that needs one, never up front - see the call site.
async function diagramsReady(page) {
  await page.waitForFunction(() => {
    const figs = document.querySelectorAll(".mermaid, figure.cmh-mermaid, .cmh-diagram");
    return !figs.length || [...figs].every((f) => f.querySelector("svg"));
  }, null, { timeout: 9000 }).catch(() => {});
}

// The montage itself, shared by both subjects that show it. `page` owns the mouse and the synthetic
// cursor; `scope` holds the document (the page itself for the standalone montage, a full-viewport
// iframe for the loop clip). The loop reuses this rather than restating the demo, so a beat added to
// the montage shows up in both clips automatically.
async function runBeats({ page, scope, paced, warnings, failures }) {
  for (const beat of REPORT_BEATS) {
    // Diagrams and charts render asynchronously and cost real CPU. Waiting for them up front put
    // three seconds of a motionless document at the head of every clip; waiting for them here
    // costs nothing, because by the time a diagram beat runs they have long since drawn.
    if (beat.needsDiagrams) await diagramsReady(scope);
    const budgetMs = paced.find((p) => p.id === beat.id).budgetMs;
    const before = warnings.length;
    const ctx = makeContext(page, budgetMs, warnings, scope);
    await ctx.toast(beat.toast || beat.label);
    const started = Date.now();
    try {
      await beat.run(scope, ctx);
    } catch (e) {
      warnings.push(`${beat.id}: ${e.message}`);
    }
    // A beat marked `required` carries the demo: if `select`, `compose` or `save` shows nothing,
    // the clip is seconds of a cursor waving at a document and must not be published as a demo.
    // Optional beats stay best-effort, so a runtime change costs one moment, not the whole run.
    if (beat.required && warnings.length > before) failures.push(beat.id);
    const spent = Date.now() - started;
    if (spent > budgetMs) warnings.push(`${beat.id} overran its ${budgetMs}ms budget by ${spent - budgetMs}ms`);
    await sleep(budgetMs - spent);
  }
}

async function recordReport(args) {
  const seconds = numberOpt(args, "seconds", DEFAULT_SECONDS);

  const example = args.example
    ? path.resolve(String(args.example))
    : path.join(EXAMPLES, "report-community-garden.html");
  const width = numberOpt(args, "width", 1440);
  const height = numberOpt(args, "height", 900);
  const totalMs = Math.round(seconds * 1000);
  const plan = planBeats(REPORT_BEATS, totalMs);
  const outFile = args.out
    ? path.resolve(String(args.out))
    : path.join(OUT_ROOT, `commentable-html-${stamp()}.webm`);

  if (!fs.existsSync(example)) throw new Error(`example not found: ${example}`);
  if (args.list) {
    console.log(JSON.stringify({ subject: "report", seconds, example, output: outFile, beats: plan }, null, 2));
    return;
  }

  const chromium = loadPlaywright();
  const videoDir = path.join(OUT_ROOT, "raw", `report-${process.pid}`);
  // Every handle is acquired INSIDE the try, so a failure to launch (a missing browser binary, an
  // out-of-memory) cannot leak the HTTP server or the video directory behind it.
  let server = null;
  let browser = null;
  let context = null;
  const warnings = [];
  const failures = [];
  let preludeReport = 0;
  try {
    ensureDir(videoDir);
    browser = await chromium.launch();
    context = await browser.newContext({
      viewport: { width, height },
      deviceScaleFactor: 1,
      recordVideo: { dir: videoDir, size: videoSize(width, height, args) },
    });
    // Loaded from FILE, not from a local http server. A report the skill generates in "not portable"
    // mode links its runtime with absolute `file:///` URLs into the installed plugin, and an http
    // page is not allowed to load a file:// subresource - so the layer never booted, every beat
    // found nothing, and the only clue was one "never signalled ready" line. A portable report works
    // either way, so file:// is simply the setting that films both.
    const url = pathToFileURL(example).href;
    // Playwright records PER PAGE, starting when the page is created. Warming the document in a
    // throwaway page first pays the one-off font/diagram cost off camera, so the filmed page opens
    // fast and the clip is mostly montage rather than loading.
    const warmup = await context.newPage();
    await warmup.goto(url, { waitUntil: "load" }).catch(() => {});
    await warmup.waitForFunction(() => window.__commentableHtmlReady === true, null, { timeout: 20000 })
      .catch(() => {});
    await warmup.close().catch(() => {});

    const recordingStarted = Date.now();
    const page = await context.newPage();
    // Deleting a comment asks for confirmation through a native dialog. Playwright DISMISSES those
    // by default, which would cancel the delete and film nothing happening, so the recorder accepts
    // them. The dialog is browser chrome and never appears in the video; the visible result is the
    // comment leaving the sidebar.
    page.on("dialog", (dialog) => { dialog.accept().catch(() => {}); });
    // The reviewer identity is a real person's name in a real install; the clip gets a demo one.
    await page.addInitScript(`try { localStorage.setItem("cmh::author", ${JSON.stringify(DEMO_AUTHOR)}); } catch (e) {}`);
    await page.addInitScript(CURSOR_SCRIPT);
    await page.addInitScript(OVERLAY_SCRIPT);
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await waitForRuntime(page, warnings);

    const preludeMs = Date.now() - recordingStarted;
    preludeReport = preludeMs;
    // Closing the context and finalizing the file also lands in the clip, so hold a little back.
    const tailMs = 350;
    const beatBudget = totalMs - preludeMs - tailMs;
    const floor = MIN_BEAT_MS * REPORT_BEATS.length;
    if (beatBudget < floor) {
      warnings.push(`the ${(preludeMs / 1000).toFixed(1)}s page load leaves too little of a ${seconds}s clip; the montage will overrun`);
    }
    const paced = planBeats(REPORT_BEATS, Math.max(floor, beatBudget));
    await runBeats({ page, scope: page, paced, warnings, failures });
    // The loop capture waits on this file: the montage IS what produces the review that gets pasted
    // back into the session, so writing it here is what closes the loop without hand-assembling a
    // bundle that no reviewer actually made.
    if (args["review-out"]) {
      const bundle = await copyAllBundle(page, page, warnings);
      const dest = path.resolve(String(args["review-out"]));
      ensureDir(path.dirname(dest));
      // Written atomically: the capture polls for this path, and a half-written bundle would be
      // pasted into the session as a truncated review.
      const tmpDest = `${dest}.partial`;
      fs.writeFileSync(tmpDest, reviewPreamble() + bundle);
      fs.renameSync(tmpDest, dest);
      console.log(`review bundle: ${dest} (${bundle.length} chars)`);
      // Snapshot the report AS REVIEWED. The agent edits the file in place when the review goes
      // back, so without a copy taken at this exact moment the "before" version is gone - and the
      // loop clip would show the already-answered document during the review phase and again at the
      // end, which makes the round trip look like nothing happened.
      if (args["snapshot-out"]) {
        const snap = path.resolve(String(args["snapshot-out"]));
        ensureDir(path.dirname(snap));
        fs.copyFileSync(example, snap);
        console.log(`reviewed snapshot: ${snap}`);
      }
    }
    // Spend the tail INSIDE the recording: closing the context stops the video immediately, so
    // without this the reserved time is simply cut off and the clip ends mid-gesture.
    await sleep(tailMs);
    await saveVideo(page, context, outFile);
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) await server.close().catch(() => {});
    try { fs.rmSync(videoDir, { recursive: true, force: true }); } catch (e) { /* best effort */ }
  }
  console.log(`clip: ${outFile}`);
  console.log(`  opening dead time before the first beat: ${preludeReport}ms`);
  for (const warning of warnings) console.warn(`  warning: ${warning}`);
  if (failures.length) {
    console.error(`\nFAILED: required beat(s) showed nothing: ${failures.join(", ")}.`);
    console.error("This clip does not demonstrate the skill - fix the beat or the runtime before publishing.");
    process.exitCode = 1;
  }
}

// node-pty spawns the file it is given verbatim, so a bare name like `copilot` or `powershell` fails
// with "File not found". Resolve it the way a shell would - across PATH, and on Windows across
// PATHEXT too, which is what makes a `.cmd`/`.ps1` shim (how most CLIs install there) launchable.
function resolveExecutable(command) {
  if (command.includes(path.sep) || command.includes("/")) {
    return fs.existsSync(command) ? path.resolve(command) : command;
  }
  const dirs = (process.env.PATH || "").split(path.delimiter).filter(Boolean);
  const exts = process.platform === "win32"
    ? (process.env.PATHEXT || ".COM;.EXE;.BAT;.CMD").split(";").filter(Boolean)
    : [""];
  for (const dir of dirs) {
    for (const ext of ["", ...exts]) {
      const candidate = path.join(dir, command + ext);
      try {
        if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
      } catch (e) { /* unreadable PATH entry */ }
    }
  }
  throw new Error(`command not found on PATH: ${command}`);
}

// Resolving the shim is only half the job on Windows: a `.cmd`/`.bat` is not directly executable and
// a `.ps1` is not executable at all, so handing either to node-pty fails even though the file is
// right there. Most CLIs install as one of those, so wrap them in their interpreter.
export function launchSpec(executable, args, platform = process.platform) {
  if (platform !== "win32") return { file: executable, args };
  const ext = path.extname(executable).toLowerCase();
  if (ext === ".cmd" || ext === ".bat") {
    return { file: process.env.COMSPEC || "cmd.exe", args: ["/d", "/s", "/c", executable, ...args] };
  }
  if (ext === ".ps1") {
    return {
      file: "powershell.exe",
      args: ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", executable, ...args],
    };
  }
  return { file: executable, args };
}

async function captureTerminal(args) {
  const command = args.passthrough;
  if (!command.length) throw new Error("capture needs a command after --, e.g. -- copilot");
  const pty = loadOptional("node-pty");
  const executable = resolveExecutable(command[0]);
  const launch = launchSpec(executable, command.slice(1));
  const cols = Math.round(numberOpt(args, "cols", 120));
  const rows = Math.round(numberOpt(args, "rows", 30));
  const outFile = args.out
    ? path.resolve(String(args.out))
    : path.join(OUT_ROOT, `session-${stamp()}.cast.json`);
  ensureDir(path.dirname(outFile));

  const rules = rulesForThisMachine();
  // A second scrubber for the LIVE stream, kept separate from the one that cleans the cast so the
  // two never share carry state.
  const liveScrubber = createScrubber({ rules });
  const started = Date.now();
  const events = [];
  const child = pty.spawn(launch.file, launch.args, {
    name: "xterm-256color",
    cols,
    rows,
    cwd: process.cwd(),
    env: process.env,
  });

  const wasRaw = process.stdin.isRaw;
  const script = args.script ? readScript(String(args.script)) : null;
  // A scripted capture drives the session itself, and the marks it records are what a later render
  // uses to find each turn - the point where the report was generated, the point where the review
  // was pasted back - so a composite clip can splice the browser phase between them.
  const marks = [];
  let buffer = "";
  let lastDataAt = Date.now();
  // The driver waits on the session; if the session ends, every wait it is in must end too.
  let childExited = false;
  let driverError = null;
  const onInput = (data) => { try { child.write(data.toString("utf8")); } catch (e) { /* child is gone */ } };
  const onResize = () => { try { child.resize(process.stdout.columns || cols, process.stdout.rows || rows); } catch (e) { /* child is gone */ } };
  // Raw mode belongs to the CALLER's terminal, so it must be handed back on every path - a throw, a
  // Ctrl+C, a child that dies badly - or the operator is left with an unusable shell.
  let restored = false;
  const restore = () => {
    if (restored) return;
    restored = true;
    process.stdin.off("data", onInput);
    process.stdout.off("resize", onResize);
    if (process.stdin.isTTY) { try { process.stdin.setRawMode(!!wasRaw); } catch (e) { /* already closed */ } }
    process.stdin.pause();
  };
  const onSignal = () => {
    restore();
    // The scrubber holds a whitespace-free run back until it can prove it is not a credential.
    // Exiting without flushing loses that text from the operator's own terminal for good.
    if (!process.stdout.isTTY) { try { process.stdout.write(liveScrubber.end()); } catch (e) { /* closed */ } }
    try { child.kill(); } catch (e) { /* already gone */ }
    process.exit(130);
  };
  process.once("SIGINT", onSignal);
  process.once("SIGTERM", onSignal);

  let exitCode = 0;
  try {
    if (process.stdin.isTTY) process.stdin.setRawMode(true);
    process.stdin.resume();
    process.stdin.on("data", onInput);
    process.stdout.on("resize", onResize);
    child.onData((data) => {
      // The operator's own terminal shows the session RAW, because they are interacting with it.
      // Anything else - a pipe, a CI log, an agent transcript - gets the scrubbed stream, since a
      // credential printed to a persisted log leaks just as surely as one written into the cast.
      process.stdout.write(process.stdout.isTTY ? data : liveScrubber.push(data));
      events.push({ t: Date.now() - started, data });
      // The driver below waits on what the session has PRINTED, so the buffer it reads is kept
      // here rather than re-derived. It is capped because a long agent run prints megabytes and the
      // only thing a step ever looks for is a recent marker.
      buffer = (buffer + data).slice(-65536);
      lastDataAt = Date.now();
    });
    // Scripted turns are driven from here, alongside the live stdin forwarding above (an operator
    // watching can still intervene). Each step waits for its own condition, sends, and records a
    // mark at the moment it sent.
    const driver = script ? (async () => {
      for (const step of script.steps) {
        const startedAt = Date.now();
        // Each step only reads output produced SINCE IT BEGAN. Sharing one buffer let a step whose
        // marker had already appeared for an earlier step fire immediately, before the session had
        // done anything the step was waiting on.
        const from = buffer.length;
        let skipped = false;
        for (;;) {
          if (childExited) throw new Error(`session ended while step "${step.mark}" was waiting`);
          const state = stepReady(step, {
            buffer: buffer.slice(from),
            lastDataAt,
            now: Date.now(),
            startedAt,
            fileExists: step.expectFile ? fs.existsSync(step.expectFile) : false,
          });
          if (state.skip) {
            console.warn(`  script: optional step "${step.mark}" ${state.reason}; skipping`);
            skipped = true;
            break;
          }
          if (state.ready) {
            if (state.timedOut) console.warn(`  script: step "${step.mark}" ${state.reason}; sending anyway`);
            break;
          }
          await sleep(200);
        }
        if (skipped) continue;
        if (step.delayMs) await sleep(step.delayMs);
        if (childExited) throw new Error(`session ended before step "${step.mark}" could be sent`);
        const payload = stepPayload(step);
        // Record WHAT WAS TYPED alongside the mark, so a render can put the real prompt on its
        // title card instead of a paraphrase somebody has to keep in sync by hand. Scrubbed like
        // everything else, and capped because one of these steps pastes a whole review bundle.
        marks.push({
          label: step.mark,
          t: Date.now() - started,
          eventIndex: events.length,
          text: scrubText(payload.replace(/\u001b\[20[01]~/g, ""), rules).slice(0, 2000),
        });
        child.write(payload);
        const submit = stepSubmit(step);
        if (submit) { await sleep(step.submitMs); child.write(submit); }
      }
    })().catch((e) => {
      // A driver that gives up must not leave the session sitting on a prompt forever - a capture
      // waiting on a step that can no longer be satisfied would otherwise hang for the whole of
      // every remaining timeout, which the shipped script measures in tens of minutes.
      driverError = e;
      console.warn(`  script: ${e.message}; ending the session`);
      try { child.kill(); } catch (killErr) { /* already gone */ }
    }) : null;
    exitCode = await new Promise((resolve) => child.onExit(({ exitCode: code }) => {
      childExited = true;
      resolve(code);
    }));
    if (driver) await driver;
    // onExit can fire while the pty still has buffered output in flight, and the tail of a session
    // (the final result, the closing prompt) is exactly what a demo wants to show. Let it land.
    await sleep(250);
  } finally {
    restore();
    // Never orphan the child. The happy path leaves through onExit, but a setup throw or a signal
    // would otherwise leave a pty running with nobody reading it.
    try { child.kill(); } catch (e) { /* already gone */ }
    // Whatever the live scrubber was holding back belongs on the operator's stream too.
    if (!process.stdout.isTTY) { try { process.stdout.write(liveScrubber.end()); } catch (e) { /* closed */ } }
    process.off("SIGINT", onSignal);
    process.off("SIGTERM", onSignal);
  }

  // The COMMAND is part of the clip too - it is the title bar of the render - and a real invocation
  // can carry a credential (`curl -H "Authorization: Bearer ..."`), so it is scrubbed like output.
  const commandLine = scrubText(command.join(" "), rules);

  // Scrub BEFORE anything touches the disk: the raw stream is never persisted.
  const scrubbed = scrubEvents(events, { rules });
  const cast = {
    version: 1,
    recordedAt: new Date().toISOString(),
    command: commandLine,
    cols,
    rows,
    // Provenance, NOT identity: the machine-specific rules (home path, account name) are built from
    // whoever is running, so a cast captured elsewhere would be scanned at render time with the
    // WRONG rules and pass clean. Recording the operator's home path here to close that gap would
    // put the very thing being redacted into the file, so the cast records only that it was scrubbed
    // by this tool - and render says so loudly when that mark is missing.
    scrubbedBy: "demo-video",
    durationMs: events.length ? events[events.length - 1].t : 0,
    // Named split points, in the same clock as the events. A composite render reads these to find
    // where one turn ends and the next begins without pattern-matching the output.
    marks,
    events: scrubbed.events.map((e) => ({ t: e.t, data: e.data })),
  };
  fs.writeFileSync(outFile, JSON.stringify(cast));
  const transcriptFile = outFile.replace(/\.cast\.json$/, "") + ".transcript.txt";
  fs.writeFileSync(transcriptFile, scrubbed.transcript);

  console.log(`\ncast:       ${outFile}`);
  console.log(`transcript: ${transcriptFile}`);
  console.log(`redacted:   ${scrubbed.redactions} match(es) scrubbed before writing`);
  const leftover = scanText(castText(cast), rules);
  if (leftover.length) console.warn(`  WARNING: ${leftover.length} finding(s) survived scrubbing - render will refuse this cast`);
  console.log("READ THE TRANSCRIPT before you render or publish: automated redaction is a net, not a gate.");
  // node-pty keeps handles alive after the child exits, so the process would hang on its own - but
  // exiting outright can truncate a piped stdout, losing the paths just printed. Flush, then go.
  await new Promise((done) => process.stdout.write("", done));
  process.exit(exitCode || 0);
}

// A cast's COMMAND is shown in the clip's title bar, so the gate has to read it too - scanning only
// the output would wave through a credential passed on the command line.
function castText(cast) {
  return `${cast.command || ""}\n${cast.events.map((e) => e.data).join("")}`;
}

function readCast(args) {
  if (!args.cast) throw new Error("--cast <file.cast.json> is required");
  const file = path.resolve(String(args.cast));
  if (!fs.existsSync(file)) throw new Error(`cast not found: ${file}`);
  const cast = JSON.parse(fs.readFileSync(file, "utf8"));
  if (!Array.isArray(cast.events)) throw new Error(`${file} is not a cast (no events array)`);
  return { file, cast };
}

function scanCast(args) {
  const { file, cast } = readCast(args);
  const text = castText(cast);
  const findings = scanText(text, rulesForThisMachine());
  console.log(`cast:     ${file}`);
  console.log(`events:   ${cast.events.length}`);
  console.log(`findings: ${findings.length}`);
  for (const finding of findings.slice(0, 25)) {
    const start = Math.max(0, finding.index - 20);
    console.log(`  ${finding.rule} @${finding.index}: ${JSON.stringify(text.slice(start, start + 70))}`);
  }
  if (findings.length) {
    console.error("This cast must not be filmed as-is. Re-capture, or add a rule to tools/redact.mjs.");
    process.exitCode = 1;
  }
  return findings;
}

function terminalPage({ cast, timeline, fontSize, endHoldMs, introMs, ask }) {
  const xtermJs = fs.readFileSync(resolveOptionalPath("@xterm/xterm", "lib", "xterm.js"), "utf8");
  const xtermCss = fs.readFileSync(resolveOptionalPath("@xterm/xterm", "css", "xterm.css"), "utf8");
  const payload = scriptJson({
    cols: cast.cols || 120,
    rows: cast.rows || 30,
    fontSize,
    endHoldMs,
    introMs,
    ask,
    askFontPx: askFontPx(ask),
    // Merged at the last moment, so the schedule above is computed on the real event stream and
    // only the PLAYER sees the cheaper one.
    events: coalesceEvents(timeline.events, 45).map((e) => ({ t: e.t, d: e.data, f: e.fastForward, s: e.skippedMs })),
  });
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>demo</title>
<style>${xtermCss}</style>
<style>
  html, body { margin: 0; height: 100%; background: #0b0f16; color: #e6edf3;
    font: 13px/1.4 "Segoe UI", system-ui, sans-serif; }
  .wrap { height: 100%; display: flex; flex-direction: column; padding: 18px 20px; box-sizing: border-box; }
  .chrome { display: flex; align-items: center; gap: 8px; padding-bottom: 12px; }
  .dot { width: 11px; height: 11px; border-radius: 50%; }
  .title { margin-left: 8px; opacity: .75; font-size: 12px; letter-spacing: .2px; }
  .term { flex: 1; min-height: 0; }
  #ff { position: fixed; right: 26px; bottom: 24px; padding: 7px 13px; border-radius: 999px;
    background: rgba(56,139,253,.16); border: 1px solid rgba(56,139,253,.5); color: #9ecbff;
    font-size: 12px; letter-spacing: .3px; opacity: 0; transition: opacity 120ms linear; }
  #ff.on { opacity: 1; }
  /* The title card. A viewer needs to know what was ASKED before any output means anything, and the
     command in the window chrome is far too small to read. This states the ask in large type, holds,
     then fades into the session. */
  #intro { position: fixed; inset: 0; background: #0b0f16; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 22px; padding: 8%; text-align: center;
    transition: opacity 420ms ease; z-index: 5; }
  #intro.gone { opacity: 0; pointer-events: none; }
  #intro .who { color: #7d8590; font-size: 15px; letter-spacing: 2.4px; text-transform: uppercase; }
  #intro .ask { color: #e6edf3; line-height: 1.45; max-width: 32em; text-align: left;
    font-family: "Cascadia Mono", Consolas, monospace; }
  #intro .ask::before { content: "> "; color: #58a6ff; }
</style></head>
<body><div class="wrap">
  <div class="chrome">
    <span class="dot" style="background:#ff5f57"></span>
    <span class="dot" style="background:#febc2e"></span>
    <span class="dot" style="background:#28c840"></span>
    <span class="title" id="title"></span>
  </div>
  <div class="term" id="term"></div>
</div>
<div id="ff">fast-forward</div>
<div id="intro"><div class="who">asked of copilot</div><div class="ask" id="introAsk"></div></div>
<script>${xtermJs}</script>
<script>
  const DATA = ${payload};
  document.getElementById("title").textContent = ${scriptJson(String(cast.command || "session"))};
  const term = new Terminal({
    cols: DATA.cols, rows: DATA.rows, fontSize: DATA.fontSize, convertEol: false,
    fontFamily: 'Cascadia Mono, Consolas, "DejaVu Sans Mono", monospace',
    theme: { background: "#0b0f16", foreground: "#e6edf3" }, cursorBlink: false, scrollback: 0,
  });
  term.open(document.getElementById("term"));
  const badge = document.getElementById("ff");
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  window.__demoDone = false;
  (async () => {
    // Hold the title card first, so the ask is read before any output appears, then fade it out.
    const intro = document.getElementById("intro");
    document.getElementById("introAsk").textContent = DATA.ask;
    document.getElementById("introAsk").style.fontSize = DATA.askFontPx + "px";
    if (DATA.introMs > 0) {
      await sleep(DATA.introMs);
      intro.classList.add("gone");
      await sleep(420);
    } else {
      intro.classList.add("gone");
    }
    // Schedule against a REAL clock, not a running total of planned gaps. term.write and the paint
    // it triggers cost real milliseconds, and adding the next planned gap on top of the previous
    // PLANNED time lets that cost accumulate: a long session drifted ~50% past its requested length.
    // Sleeping until start plus the event time self-corrects - a slow write shortens the next wait.
    const start = performance.now();
    const write = (data) => new Promise((done) => term.write(data, done));
    const frame = () => new Promise((done) => requestAnimationFrame(() => done()));
    for (const event of DATA.events) {
      // Raise the badge BEFORE waiting out a fast-forward, not after. Showing it once the hold has
      // already elapsed means the viewer sits through an unexplained pause and then sees the badge
      // land over the output that FOLLOWS the wait, labelling the wrong moment.
      if (event.f) {
        badge.textContent = "skipping ahead " + Math.round(event.s / 1000) + "s";
        badge.classList.add("on");
      }
      await sleep(start + event.t - performance.now());
      if (event.f) setTimeout(() => badge.classList.remove("on"), 450);
      await write(event.d);
    }
    await frame();
    await frame();
    // Hold the closing frame. The panel summary is the point of the clip and it streams fast, so
    // without this the verdict is on screen for a blink before the recording stops.
    await sleep(DATA.endHoldMs);
    window.__demoDone = true;
  })();
</script></body></html>`;
}

// Wipe the reviewer's stored comments before the ANSWERED report loads. The runtime keeps comments
// in localStorage under the document's comment key, and the review phase of this very clip just put
// a fresh set there - with new ids the agent's `handledCommentIds` (recorded during the real
// session) cannot match. Left alone, the closing shot shows the same outstanding comments as the
// review phase and the round trip looks like nothing happened. Clearing them shows what the agent
// actually left behind: its answers in the document and nothing still open.
const CLEAR_COMMENTS_SCRIPT = `(() => {
  try {
    // The store key is derived from the document's own comment key, not a fixed prefix, so the only
    // reliable move is to clear the lot and put the demo identity back.
    const author = localStorage.getItem("cmh::author");
    localStorage.clear();
    if (author != null) localStorage.setItem("cmh::author", author);
  } catch (e) { /* storage is not available on this origin */ }
})();`;

// What the title card should say: the prompt that was ACTUALLY typed. A hand-written summary drifts
// from the session the moment either changes, and a viewer comparing the card with the terminal
// underneath it will spot the difference immediately. `--ask` stays as an override for a cast
// captured before marks carried their text.
function askFromCast(cast, args, preferredMark = "ask") {
  if (args.ask) return String(args.ask);
  const marks = Array.isArray(cast.marks) ? cast.marks : [];
  const chosen = marks.find((m) => m.label === preferredMark && m.text) || marks.find((m) => m.text);
  if (chosen) return String(chosen.text).trim();
  const fromCommand = /(?:^|\s)-p\s+(.+)$/s.exec(String(cast.command || ""));
  if (fromCommand) return fromCommand[1].replace(/^["']|["']$/g, "");
  return String(cast.command || "session");
}

// The card has to hold whatever the real prompt turned out to be, and a real prompt is often a
// paragraph. Step the type size down as it grows rather than letting it overflow the screen.
function askFontPx(ask) {
  const n = String(ask || "").length;
  if (n <= 90) return 30;
  if (n <= 200) return 27;
  if (n <= 340) return 24;
  if (n <= 560) return 21;
  if (n <= 900) return 19;
  return 17;
}

// The stage for the loop clip: ONE page that holds both the terminal and the report, because
// Playwright records per page and a clip that cut between two pages would be two videos. The
// terminal is an xterm exactly like the standalone render; the report lives in a full-viewport
// iframe on top of it. Node drives the phases through `window.__stage`, and because page.evaluate
// awaits a returned promise, the handshake needs no polling.
function stagePage({ cast, segments, fontSize, introMs, endHoldMs, ask, reportUrl }) {
  const xtermJs = fs.readFileSync(resolveOptionalPath("@xterm/xterm", "lib", "xterm.js"), "utf8");
  const xtermCss = fs.readFileSync(resolveOptionalPath("@xterm/xterm", "css", "xterm.css"), "utf8");
  const payload = scriptJson({
    cols: cast.cols || 120,
    rows: cast.rows || 30,
    fontSize,
    introMs,
    endHoldMs,
    ask,
    askFontPx: askFontPx(ask),
    reportUrl,
    segments: segments.map((timeline) =>
      coalesceEvents(timeline.events, 45).map((e) => ({ t: e.t, d: e.data, f: e.fastForward, s: e.skippedMs }))),
  });
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>demo</title>
<style>${xtermCss}</style>
<style>
  html, body { margin: 0; height: 100%; background: #0b0f16; color: #e6edf3;
    font: 13px/1.4 "Segoe UI", system-ui, sans-serif; overflow: hidden; }
  .wrap { height: 100%; display: flex; flex-direction: column; padding: 18px 20px; box-sizing: border-box; }
  .chrome { display: flex; align-items: center; gap: 8px; padding-bottom: 12px; }
  .dot { width: 11px; height: 11px; border-radius: 50%; }
  .title { margin-left: 8px; opacity: .75; font-size: 12px; letter-spacing: .2px; }
  .term { flex: 1; min-height: 0; }
  #ff { position: fixed; right: 26px; bottom: 24px; padding: 7px 13px; border-radius: 999px;
    background: rgba(56,139,253,.16); border: 1px solid rgba(56,139,253,.5); color: #9ecbff;
    font-size: 12px; letter-spacing: .3px; opacity: 0; transition: opacity 120ms linear; z-index: 6; }
  #ff.on { opacity: 1; }
  /* The report sits ON TOP of the terminal at full size, so montage coordinates are page
     coordinates and every beat works unchanged. */
  #report { position: fixed; inset: 0; width: 100%; height: 100%; border: 0; background: #fff;
    opacity: 0; pointer-events: none; transition: opacity 380ms ease; z-index: 4; }
  #report.on { opacity: 1; pointer-events: auto; }
  /* A caption for each phase, so a viewer knows they are watching one loop rather than three
     unrelated clips spliced together. */
  #phase { position: fixed; left: 50%; top: 26px; transform: translateX(-50%); z-index: 7;
    padding: 14px 30px; border-radius: 999px; background: #0d1117; color: #e6edf3;
    border: 2px solid rgba(240,246,252,0.34); font-size: 24px; font-weight: 700; letter-spacing: .3px;
    box-shadow: 0 14px 40px rgba(0,0,0,.5); opacity: 0; transition: opacity 300ms ease;
    white-space: nowrap; }
  #phase.on { opacity: 1; }
  #intro { position: fixed; inset: 0; background: #0b0f16; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 22px; padding: 8%; text-align: center;
    transition: opacity 420ms ease; z-index: 8; }
  #intro.gone { opacity: 0; pointer-events: none; }
  #intro .who { color: #7d8590; font-size: 15px; letter-spacing: 2.4px; text-transform: uppercase; }
  #intro .ask { color: #e6edf3; line-height: 1.45; max-width: 32em; text-align: left;
    font-family: "Cascadia Mono", Consolas, monospace; }
  #intro .ask::before { content: "> "; color: #58a6ff; }
</style></head>
<body><div class="wrap">
  <div class="chrome">
    <span class="dot" style="background:#ff5f57"></span>
    <span class="dot" style="background:#febc2e"></span>
    <span class="dot" style="background:#28c840"></span>
    <span class="title" id="title"></span>
  </div>
  <div class="term" id="term"></div>
</div>
<iframe id="report" title="report"></iframe>
<div id="ff">fast-forward</div>
<div id="phase"></div>
<div id="intro"><div class="who">asked of copilot</div><div class="ask" id="introAsk"></div></div>
<script>${xtermJs}</script>
<script>
  const DATA = ${payload};
  document.getElementById("title").textContent = ${scriptJson(String(cast.command || "session"))};
  const term = new Terminal({
    cols: DATA.cols, rows: DATA.rows, fontSize: DATA.fontSize, convertEol: false,
    fontFamily: 'Cascadia Mono, Consolas, "DejaVu Sans Mono", monospace',
    theme: { background: "#0b0f16", foreground: "#e6edf3" }, cursorBlink: false, scrollback: 0,
  });
  term.open(document.getElementById("term"));
  const badge = document.getElementById("ff");
  const phase = document.getElementById("phase");
  const report = document.getElementById("report");
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const write = (data) => new Promise((done) => term.write(data, done));

  async function playSegment(index) {
    const events = DATA.segments[index] || [];
    // Each segment schedules against its own real clock, for the same reason the single-segment
    // render does: adding planned gaps to planned time lets write cost accumulate into drift.
    const start = performance.now();
    for (const event of events) {
      if (event.f) {
        badge.textContent = "skipping ahead " + Math.round(event.s / 1000) + "s";
        badge.classList.add("on");
      }
      await sleep(start + event.t - performance.now());
      if (event.f) setTimeout(() => badge.classList.remove("on"), 450);
      await write(event.d);
    }
  }

  window.__stage = {
    playSegment,
    async caption(text) {
      if (!text) { phase.classList.remove("on"); await sleep(300); return; }
      phase.textContent = text;
      phase.classList.add("on");
    },
    async showReport(url) {
      // The waiter is attached BEFORE the navigation starts. Checking readyState after assigning
      // src can observe the PREVIOUS document still sitting at "complete", so the handshake
      // resolves before the new page exists and the montage drives whatever is still on screen.
      const loaded = new Promise((done) => {
        report.addEventListener("load", done, { once: true });
        setTimeout(done, 15000);
      });
      report.src = url || DATA.reportUrl;
      await loaded;
      report.classList.add("on");
      await sleep(420);
    },
    async hideReport() {
      report.classList.remove("on");
      await sleep(420);
    },
    async hold(ms) { await sleep(ms); },
  };

  window.__stageReady = false;
  (async () => {
    document.getElementById("introAsk").textContent = DATA.ask;
    document.getElementById("introAsk").style.fontSize = DATA.askFontPx + "px";
    const intro = document.getElementById("intro");
    if (DATA.introMs > 0) {
      await sleep(DATA.introMs);
      intro.classList.add("gone");
      await sleep(420);
    } else {
      intro.classList.add("gone");
    }
    window.__stageReady = true;
  })();
</script></body></html>`;
}

// What the reviewer says when handing the bundle back. The clip needs the agent to visibly ACT on
// the review, and it needs a marker the capture script can wait for to know the turn finished.
function reviewPreamble() {
  return "Here is my review of report.html from the browser. Apply every comment: make the change "
    + "each one asks for, and reply to it in the report. When you are done, print exactly "
    + "REVIEW-APPLIED on its own line and end your turn.\n\n";
}

// The full loop: an agent generates the report, a reviewer works it over in the browser, the review
// goes back to the same session. One continuous clip, because the point is the ROUND TRIP - three
// separate videos would not make it.
//
// The montage in the middle is not restated here: it is the same REPORT_BEATS driven through the
// same runBeats, just scoped to the iframe, so a beat added to the standalone montage appears in
// this clip too.
async function recordLoop(args) {
  const { cast } = readCast(args);
  const rules = rulesForThisMachine();
  const findings = scanText(castText(cast), rules);
  if (findings.length && !args["allow-findings"]) {
    throw new Error(
      `this cast still scans dirty (${findings.length} finding(s)); run 'scan --cast <file>' to see them. `
      + "Re-capture or add a rule to tools/redact.mjs rather than publishing it.",
    );
  }
  if (cast.scrubbedBy !== "demo-video") {
    console.warn("WARNING: this cast was not captured by demo-video, so it was never scrubbed at source.");
  }

  const splitLabel = args.split ? String(args.split) : "paste";
  const mark = (cast.marks || []).find((m) => m.label === splitLabel);
  if (!mark) {
    const have = (cast.marks || []).map((m) => m.label).join(", ") || "none";
    throw new Error(`the cast has no mark "${splitLabel}" to split on (marks: ${have}). `
      + "Capture with --script so the turns are marked.");
  }
  const example = args.example ? path.resolve(String(args.example)) : path.join("C:", "demo", "report.html");
  if (!fs.existsSync(example)) throw new Error(`example not found: ${example}`);
  // The report AFTER the agent answered the review. Optional, because a cast whose second turn did
  // not touch the file has nothing to show; when it is given the clip ends where it should.
  const afterExample = args["example-after"] ? path.resolve(String(args["example-after"])) : null;
  if (afterExample && !fs.existsSync(afterExample)) throw new Error(`example-after not found: ${afterExample}`);
  const resolvedMs = Math.round(numberOpt(args, "seconds-resolved", 7) * 1000);

  // Split at the mark: everything the agent did to PRODUCE the report, then everything it did with
  // the review that came back. The two halves are fitted independently, because they are different
  // kinds of moment - the first is setup a viewer only needs the gist of, the second is the payoff.
  const before = cast.events.slice(0, mark.eventIndex);
  const after = cast.events.slice(mark.eventIndex).map((e) => ({ ...e, t: e.t - mark.t }));
  if (!before.length || !after.length) throw new Error(`the mark "${splitLabel}" leaves one half empty`);

  const fitFor = (events, seconds, tailSeconds) => fitTimeline(events, Math.round(seconds * 1000), {
    holdMs: numberOpt(args, "hold", undefined),
    pinHold: args.hold != null,
    idleMs: args.idle == null ? undefined : Math.round(numberOpt(args, "idle", 0)),
    tailMs: Math.round(tailSeconds * 1000),
  });
  const genSeconds = numberOpt(args, "seconds-gen", 9);
  const applySeconds = numberOpt(args, "seconds-apply", 12);
  const reviewSeconds = numberOpt(args, "seconds-review", 24);
  const segments = [
    fitFor(before, genSeconds, numberOpt(args, "tail-gen", 12)),
    fitFor(after, applySeconds, numberOpt(args, "tail-apply", 25)),
  ];

  const cols = cast.cols || 120;
  const rows = cast.rows || 30;
  const width = Math.round(numberOpt(args, "width", 1440));
  const height = Math.round(numberOpt(args, "height", 900));
  // The terminal has to fit the REPORT's viewport, since one page serves both phases: size the font
  // from the column count rather than the other way round.
  const fontSize = Math.round(numberOpt(args, "font", Math.floor((width - 56) / (cols * 0.605))));
  const introMs = Math.round(numberOpt(args, "intro", 3.5) * 1000);
  const endHoldMs = Math.round(numberOpt(args, "end-hold", 3.5) * 1000);
  const ask = askFromCast(cast, args);
  const unsafe = findings.length > 0;
  const outFile = args.out
    ? path.resolve(String(args.out))
    : path.join(OUT_ROOT, `loop-${unsafe ? "UNSAFE-" : ""}${stamp()}.webm`);
  const markedOut = unsafe && !path.basename(outFile).includes("UNSAFE")
    ? path.join(path.dirname(outFile), `UNSAFE-${path.basename(outFile)}`)
    : outFile;

  const chromium = loadPlaywright();
  const videoDir = path.join(OUT_ROOT, "raw", `loop-${process.pid}`);
  let browser = null;
  let context = null;
  let stageFile = null;
  const warnings = [];
  const failures = [];
  let bundle = "";
  // The stage file is written into the USER's directory, so a Ctrl+C must not leave it there.
  // `finally` alone does not run when a default signal handler exits the process.
  const cleanStage = () => {
    if (!stageFile) return;
    try { fs.rmSync(stageFile, { force: true }); } catch (e) { /* best effort */ }
    stageFile = null;
  };
  const onSignal = () => { cleanStage(); process.exit(130); };
  process.once("SIGINT", onSignal);
  process.once("SIGTERM", onSignal);
  try {
    const reportName = path.basename(example);
    const stageHtml = stagePage({
      cast,
      segments,
      fontSize,
      introMs,
      endHoldMs,
      ask,
      reportUrl: `./${encodeURIComponent(reportName)}`,
    });
    // The stage is written NEXT TO the report and loaded from file://, for the same reason the
    // standalone montage is: a generated report links its runtime with absolute `file:///` URLs, and
    // an http page may not load those. A file:// page may not embed an http frame either, so the
    // stage has to live on the same protocol as the document it frames. Playwright drives frames
    // over the debugging protocol rather than through JS, so the frame being a separate opaque
    // origin costs nothing.
    stageFile = path.join(path.dirname(example), `__demo-stage-${process.pid}.html`);
    fs.writeFileSync(stageFile, stageHtml);
    ensureDir(videoDir);
    browser = await chromium.launch();
    context = await browser.newContext({
      viewport: { width, height },
      deviceScaleFactor: Number(numberOpt(args, "dpr", 2)),
      recordVideo: { dir: videoDir, size: videoSize(width, height, args) },
    });
    const reportUrl = pathToFileURL(example).href;
    // Pay the report's load and diagram cost off camera, exactly as the standalone montage does.
    const warmup = await context.newPage();
    await warmup.goto(reportUrl, { waitUntil: "load" }).catch(() => {});
    await warmup.waitForFunction(() => window.__commentableHtmlReady === true, null, { timeout: 15000 })
      .catch(() => {});
    await warmup.close().catch(() => {});

    const page = await context.newPage();
    page.on("dialog", (dialog) => { dialog.accept().catch(() => {}); });
    await page.addInitScript(`try { localStorage.setItem("cmh::author", ${JSON.stringify(DEMO_AUTHOR)}); } catch (e) {}`);
    await page.addInitScript(CURSOR_SCRIPT);
    await page.addInitScript(OVERLAY_SCRIPT);
    await page.goto(pathToFileURL(stageFile).href, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => window.__stageReady === true, null, { timeout: 30000 })
      .catch(() => warnings.push("the stage never signalled ready"));

    await page.evaluate((t) => window.__stage.caption(t), "1. The agent builds the review report");
    await page.evaluate(() => window.__stage.playSegment(0));
    await page.evaluate(() => window.__stage.caption(""));

    await page.evaluate((t) => window.__stage.caption(t), "2. You review it in the browser");
    await page.evaluate(() => window.__stage.showReport());
    const frame = findFrame(page, reportUrl);
    if (!frame) throw new Error("the report frame never attached to the stage");
    await waitForRuntime(frame, warnings, page);
    await page.evaluate(() => window.__stage.caption(""));

    const floor = MIN_BEAT_MS * REPORT_BEATS.length;
    const paced = planBeats(REPORT_BEATS, Math.max(floor, Math.round(reviewSeconds * 1000)));
    await runBeats({ page, scope: frame, paced, warnings, failures });

    // Copy all is the hand-off: it is what turns a browser review into something an agent can read.
    await page.evaluate((t) => window.__stage.caption(t), "3. Copy all - hand the review back");
    bundle = await copyAllBundle(page, frame, warnings);
    await page.evaluate(() => window.__stage.hold(900));
    // Clear the beat caption before the report leaves: a toast still reading "Exporting for
    // sharing" over the terminal phase labels the wrong thing entirely.
    await frame.evaluate(() => { if (window.__demoToast) window.__demoToast(""); }).catch(() => {});
    await page.evaluate(() => { if (window.__demoToast) window.__demoToast(""); }).catch(() => {});
    await page.evaluate(() => window.__stage.hideReport());
    await page.evaluate(() => window.__stage.caption(""));

    await page.evaluate((t) => window.__stage.caption(t), "4. Paste it back - the agent applies it");
    await page.evaluate(() => window.__stage.playSegment(1));
    await page.evaluate(() => window.__stage.caption(""));

    // The point of the whole loop is that the review CAME BACK. Reopening the report the agent just
    // edited is what shows it: the runtime itself announces the comments it handled, and the
    // answers are now in the document.
    if (afterExample) {
      await page.evaluate((t) => window.__stage.caption(t), "5. Back in the report - the comments are resolved");
      // Registered now, so it runs on the iframe's NEXT navigation and not on the review phase.
      await page.addInitScript(CLEAR_COMMENTS_SCRIPT);
      // A cache-busting query forces a real reload rather than a repaint of what is already there.
      const afterUrl = `${pathToFileURL(afterExample).href}?resolved=${Date.now()}`;
      await page.evaluate((u) => window.__stage.showReport(u), afterUrl);
      const done = findFrame(page, afterUrl);
      if (done) {
        await waitForRuntime(done, warnings, page);
        const ctx = makeContext(page, resolvedMs, warnings, done);
        await ctx.toast("Comments resolved");
        // Drift down the answered document rather than sitting on one screen, so a viewer sees the
        // agent's replies in place instead of just a settled sidebar.
        await ctx.glideTo(700, Math.max(600, resolvedMs * 0.45));
        await ctx.holdRemaining(200);
        await ctx.toast("");
      } else {
        warnings.push("the answered report never attached to the stage");
      }
      await page.evaluate(() => window.__stage.caption(""));
    }
    await page.evaluate((ms) => window.__stage.hold(ms), endHoldMs);
    await saveVideo(page, context, markedOut);
  } finally {
    if (browser) await browser.close().catch(() => {});
    cleanStage();
    process.off("SIGINT", onSignal);
    process.off("SIGTERM", onSignal);
    try { fs.rmSync(videoDir, { recursive: true, force: true }); } catch (e) { /* best effort */ }
  }

  console.log(`clip:  ${markedOut}`);
  console.log(`split: "${splitLabel}" at ${(mark.t / 1000).toFixed(1)}s of the session`);
  if (bundle) {
    const bundleFile = path.join(OUT_ROOT, "review.md");
    fs.writeFileSync(bundleFile, bundle);
    console.log(`review bundle (${bundle.length} chars) also written to ${bundleFile}`);
  }
  for (const warning of warnings) console.warn(`  warning: ${warning}`);
  if (failures.length) {
    console.error(`\nFAILED: required beat(s) showed nothing: ${failures.join(", ")}.`);
    process.exitCode = 1;
  }
}

// Click Copy all and read what it put on the clipboard. The clip needs the CLICK, and a re-record
// needs the TEXT: the same bundle is what a capture pastes back into the session, so producing it
// here is what makes the loop reproducible instead of hand-assembled.
async function copyAllBundle(page, scope, warnings) {
  const button = scope.locator("#btnCopyAll");
  const ctx = makeContext(page, 1200, warnings, scope);
  if (!(await ctx.waitVisible(button, 2500))) {
    warnings.push("Copy all was not visible; the hand-off beat filmed nothing");
    return "";
  }
  await ctx.click(button);
  await sleep(500);
  // Read what the page RECORDED being copied rather than the real clipboard: clipboard-read needs a
  // permission grant, and there is no origin to grant it to when the report is loaded from file://
  // - which is exactly where a generated report has to be loaded from.
  await sleep(250);
  // Read it from the SCOPE. Copy all runs in the document being reviewed, so in the loop clip the
  // recorded value lives in the iframe, not on the stage page that owns the mouse.
  const text = await scope.evaluate(() => window.__demoCopied || "").catch(() => "");
  if (!text) warnings.push("Copy all left the clipboard empty");
  return text;
}

async function renderTerminal(args) {
  const { cast } = readCast(args);
  const rules = rulesForThisMachine();
  const findings = scanText(castText(cast), rules);
  if (findings.length && !args["allow-findings"]) {
    throw new Error(
      `this cast still scans dirty (${findings.length} finding(s)); run 'scan --cast <file>' to see them. `
      + "Re-capture or add a rule to tools/redact.mjs rather than publishing it.",
    );
  }
  // A cast this tool did not capture was never scrubbed at capture time, and the machine-specific
  // rules here cannot know another operator's home path or account name - so a clean scan says much
  // less than it appears to.
  if (cast.scrubbedBy !== "demo-video") {
    console.warn("WARNING: this cast was not captured by demo-video, so it was never scrubbed at");
    console.warn("         source, and the home/account rules used here are THIS machine's. Read the");
    console.warn("         whole transcript before publishing anything rendered from it.");
  }

  const cols = cast.cols || 120;
  const rows = cast.rows || 30;
  const timeline = args.seconds
    ? fitTimeline(cast.events, Math.round(numberOpt(args, "seconds", 45) * 1000), {
      holdMs: numberOpt(args, "hold", undefined),
      // An explicit --hold is an instruction, not a starting point for the solver.
      pinHold: args.hold != null,
      // Same for --idle: pinning it keeps the source pacing (and so a protected head or tail) at
      // the threshold that was asked for, instead of whichever one happens to fit the target.
      idleMs: args.idle == null ? undefined : Math.round(numberOpt(args, "idle", 0)),
      // The closing stretch of a session is usually the whole point - the consolidated summary, the
      // verdict - and the opening is where the ask is read. Both are exempt from the speed-up.
      tailMs: args.tail == null ? 0 : Math.round(numberOpt(args, "tail", 0) * 1000),
      headMs: args.head == null ? 0 : Math.round(numberOpt(args, "head", 0) * 1000),
    })
    : compressTimeline(cast.events, { idleMs: numberOpt(args, "idle", undefined), holdMs: numberOpt(args, "hold", undefined) });

  // Size the viewport from the terminal grid so no column is clipped and no space is wasted. The
  // font is deliberately large, because the VIEWPORT is what sets the video's resolution: Playwright
  // records the page at its CSS size and will not upscale it, so asking for a bigger video than the
  // viewport just pads it with grey. A 2x device scale still sharpens the glyphs within that size.
  const fontSize = Math.round(numberOpt(args, "font", 24));
  // The panel summary is the point of a review clip and it streams fast, so the closing frame is
  // held rather than cut the moment the last byte lands.
  const endHoldMs = Math.round(numberOpt(args, "end-hold", 2.5) * 1000);
  // The title card states what was asked. A capture's `command` is the whole invocation - flags and
  // a paragraph-long prompt - which is unreadable on screen, so the prompt is extracted from it and
  // can be replaced outright with something short enough to read in a couple of seconds.
  const introMs = Math.round(numberOpt(args, "intro", 3) * 1000);
  // A note like "20 to 27 drags" is about the CLIP, which begins with the title card - so windows
  // are given in clip seconds and shifted onto the schedule's own clock here.
  // Shifted onto the schedule's clock and clipped to it. A window that reaches back into the title
  // card would otherwise become negative and pull the opening events to time zero, silently
  // re-timing output the caller never pointed at - while the card itself, which is not on this
  // clock, played its full length regardless.
  const speedWindows = parseSpeedWindows(args["speed-windows"])
    .map((w) => ({ ...w, fromMs: Math.max(0, w.fromMs - introMs), toMs: w.toMs - introMs }))
    .filter((w) => w.toMs > w.fromMs);
  if (speedWindows.length) {
    timeline.events = applySpeedWindows(timeline.events, speedWindows);
    timeline.durationMs = timeline.events.length ? timeline.events[timeline.events.length - 1].t : 0;
  }
  const ask = askFromCast(cast, args);
  const width = Math.round(numberOpt(args, "width", Math.ceil(cols * fontSize * 0.605) + 56));
  const height = Math.round(numberOpt(args, "height", Math.ceil(rows * fontSize * 1.32) + 84));
  // A clip rendered over the gate's objection must be impossible to mistake for a clean one later,
  // when nobody remembers which flag was passed - including when the caller named the file itself.
  const unsafe = findings.length > 0;
  const outFile = args.out
    ? path.resolve(String(args.out))
    : path.join(OUT_ROOT, `terminal-${unsafe ? "UNSAFE-" : ""}${stamp()}.webm`);
  const markedOut = unsafe && !path.basename(outFile).includes("UNSAFE")
    ? path.join(path.dirname(outFile), `UNSAFE-${path.basename(outFile)}`)
    : outFile;

  const chromium = loadPlaywright();
  const stageDir = path.join(OUT_ROOT, "raw", `terminal-${process.pid}`);
  let browser = null;
  let context = null;
  try {
    ensureDir(stageDir);
    const pageFile = path.join(stageDir, "player.html");
    fs.writeFileSync(pageFile, terminalPage({ cast, timeline, fontSize, endHoldMs, introMs, ask }));
    const videoDir = path.join(stageDir, "video");
    ensureDir(videoDir);
    browser = await chromium.launch();
    context = await browser.newContext({
      viewport: { width, height },
      deviceScaleFactor: 2,
      recordVideo: { dir: videoDir, size: videoSize(width, height, args) },
    });
    const page = await context.newPage();
    await page.goto(pathToFileURL(pageFile).href, { waitUntil: "load" });
    await page.waitForFunction(() => window.__demoDone === true, null,
      { timeout: timeline.durationMs + 60000 });
    await saveVideo(page, context, markedOut);
  } finally {
    if (browser) await browser.close().catch(() => {});
    try { fs.rmSync(stageDir, { recursive: true, force: true }); } catch (e) { /* best effort */ }
  }

  console.log(`clip:     ${markedOut}`);
  console.log(`length:   ${(timeline.durationMs / 1000).toFixed(1)}s from a ${(timeline.sourceDurationMs / 1000).toFixed(1)}s session`);
  console.log(`skipped:  ${(timeline.skippedMs / 1000).toFixed(1)}s of waiting across ${timeline.fastForwards} fast-forward(s)`);
  if (timeline.speed && timeline.speed > 1.01) {
    console.log(`speed:    the remaining output plays at ${timeline.speed.toFixed(1)}x`);
  }
  if (unsafe) {
    console.error(`\nWARNING: rendered despite ${findings.length} finding(s) because --allow-findings was passed.`);
    console.error("This clip is NOT publish-safe. Run 'scan' and look at every finding before it goes anywhere.");
  }
  console.log("WATCH THE CLIP before publishing it.");
}

// Pull stills out of a finished clip. A video is the one artifact you cannot grep, so this is how a
// human (or an agent) checks what actually got filmed - including that nothing sensitive is on
// screen - without scrubbing through a player.
async function extractFrames(args) {
  const clip = args.clip || args.out;
  if (!clip) throw new Error("--clip <file.webm> is required");
  const file = path.resolve(String(clip));
  if (!fs.existsSync(file)) throw new Error(`clip not found: ${file}`);
  const count = Math.max(1, Math.round(numberOpt(args, "count", 12)));
  const outDir = args["frames-dir"]
    ? path.resolve(String(args["frames-dir"]))
    : path.join(path.dirname(file), path.basename(file, path.extname(file)) + "-frames");
  ensureDir(outDir);

  const chromium = loadPlaywright();
  // Chromium will not let a page at an opaque origin decode a file:// video, so the clip is served
  // over the same local origin as the page that reads it. Both handles are acquired inside the try.
  let server = null;
  let browser = null;
  try {
    server = await startStaticServer(path.dirname(file), {
      "/__frames.html": { body: "<!doctype html><meta charset=utf-8><body style=margin:0>" },
    });
    browser = await chromium.launch();
    const page = await browser.newPage();
    await page.goto(`${server.origin}/__frames.html`);
    const meta = await page.evaluate(async (src) => {
      const video = document.createElement("video");
      video.src = src;
      video.muted = true;
      video.preload = "auto";
      // A video with no layout box is not guaranteed to decode, and drawImage on an element that
      // only reached loadedmetadata paints nothing - wait for real decoded data.
      video.style.cssText = "position:fixed;left:0;top:0;width:320px;opacity:0.01";
      document.body.style.margin = "0";
      document.body.appendChild(video);
      await new Promise((done, fail) => {
        video.onloadeddata = done;
        video.onerror = () => fail(new Error("the clip could not be decoded"));
      });
      window.__video = video;
      return { duration: video.duration, width: video.videoWidth, height: video.videoHeight };
    }, `/${encodeURIComponent(path.basename(file))}`);

    const written = [];
    // Playwright writes its webm with no seek index, so `currentTime = t` does not reliably
    // reposition it - every "seek" returns the same first frame. Playing the clip through and
    // grabbing a frame as each target time passes is the only dependable way to sample it.
    const targets = Array.from({ length: count }, (_, i) => ((i + 0.5) / count) * meta.duration);
    const shots = await page.evaluate(async (times) => {
      const video = window.__video;
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const ctx = canvas.getContext("2d");
      const out = [];
      let next = 0;
      await new Promise((done) => {
        const grab = () => {
          while (next < times.length && video.currentTime >= times[next]) {
            ctx.drawImage(video, 0, 0);
            out.push(canvas.toDataURL("image/png"));
            next += 1;
          }
          if (next >= times.length || video.ended) { done(); return; }
          if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(grab);
          else requestAnimationFrame(grab);
        };
        video.onended = () => {
          // Whatever is left was never reached; pad with the final frame so the count is stable.
          while (out.length < times.length) {
            ctx.drawImage(video, 0, 0);
            out.push(canvas.toDataURL("image/png"));
          }
          done();
        };
        video.play().then(grab, () => done());
      });
      return out;
    }, targets);

    if (!shots.length) {
      throw new Error(`frame extraction produced 0 frames from ${file}; the clip may be unplayable`);
    }
    for (let i = 0; i < shots.length; i++) {
      const out = path.join(outDir, `${String(i + 1).padStart(2, "0")}-${targets[i].toFixed(2)}s.png`);
      fs.writeFileSync(out, Buffer.from(shots[i].split(",")[1], "base64"));
      written.push(out);
    }
    console.log(`clip:     ${file}`);
    console.log(`duration: ${meta.duration.toFixed(2)}s at ${meta.width}x${meta.height}`);
    console.log(`frames:   ${written.length} in ${outDir}`);
    return written;
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) await server.close().catch(() => {});
  }
}

const USAGE = `demo-video recorder

  node record_demo.mjs report  [--seconds 10] [--example <file>] [--out <file.webm>] [--list]
  node record_demo.mjs loop    --cast <file.cast.json> --example <report.html> [--split paste]
  node record_demo.mjs capture [--out <file.cast.json>] [--cols 120] [--rows 30] [--script <f.json>] -- <command...>
  node record_demo.mjs render  --cast <file.cast.json> [--seconds 45] [--idle 900] [--out <file.webm>]
  node record_demo.mjs scan    --cast <file.cast.json>
  node record_demo.mjs frames  --clip <file.webm> [--count 12]

Everything is written under tmp/demo-video (gitignored). Nothing is committed.`;

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const subject = args._[0];
  if (args.help || subject === "help") { console.log(USAGE); return undefined; }
  // A stray positional is a typo that would otherwise be ignored, and the whole point of the
  // argument contract is that the recorder never quietly records something else.
  if (args._.length > 1) {
    console.error(`unexpected argument: ${args._[1]}`);
    process.exitCode = 2;
    return undefined;
  }
  if (subject) checkSubjectFlags(args, subject);
  switch (subject) {
    case "report": return recordReport(args);
    case "loop": return recordLoop(args);
    case "capture": return captureTerminal(args);
    case "render": return renderTerminal(args);
    case "scan": return void scanCast(args);
    case "frames": return void (await extractFrames(args));
    default:
      console.log(USAGE);
      if (subject) { console.error(`\nunknown subject: ${subject}`); process.exitCode = 2; }
      return undefined;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  main().catch((e) => {
    console.error(String(e && e.message ? e.message : e));
    process.exit(1);
  });
}
