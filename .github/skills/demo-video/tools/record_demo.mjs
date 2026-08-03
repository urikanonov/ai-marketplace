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
//   node record_demo.mjs capture [--out <f.cast.json>] [--cols 120] [--rows 30] [--script <f.json>] [--max-mb 48] -- <cmd...>
//                                [--exit-grace 120] [--progress 60]
//   node record_demo.mjs render  --cast <file.cast.json> [--seconds 45] [--out <file.webm>]
//   node record_demo.mjs scan    --cast <file.cast.json> [--ask "<text>"]

import { pathToFileURL, fileURLToPath } from "url";
import { createRequire } from "module";
import path from "path";
import fs from "fs";
import os from "os";
import http from "http";

import { planBeats, fitTimeline, compressTimeline, coalesceEvents, applySpeedWindows, parseSpeedWindows, MIN_BEAT_MS } from "./timeline.mjs";
import { REPORT_BEATS } from "./report-beats.mjs";
import { DEFAULT_RULES, homeRules, scanText, stripOsc, scrubEvents, scrubText, createScrubber } from "./redact.mjs";
import { readScript, stepReady, stepPayload, stepSubmit, fileReady, stepGaveUpNotice, makeSizeGuard, captureLimitBytes, sessionEndState, progressLine, stallNotice, DEFAULT_EXIT_GRACE_MS, DEFAULT_KILL_GRACE_MS, DEFAULT_PROGRESS_MS } from "./script.mjs";
import { recordCapture, wasCapturedHere } from "./provenance.mjs";
import { trimCast } from "./trim.mjs";

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
  "script", "review-out", "snapshot-out", "split", "speed-windows", "example-after", "seconds-resolved", "max-mb", "seconds-gen", "seconds-apply", "seconds-review", "tail-gen", "tail-apply", "dpr",
  "until", "until-after", "until-gap", "exit-grace", "progress",
]);
const KNOWN_FLAGS = new Set([...STRING_KEYS, "list", "allow-findings", "show-command", "help"]);
// Flags that never take a value. Without this, `--show-command yes` swallows `yes` as the value and
// the strict boolean check below then falls back to the SAFE label - the operator asked to publish
// the command and silently did not get it.
const BOOLEAN_FLAGS = new Set(["list", "allow-findings", "show-command", "help"]);
// Which options each subject actually reads. Validating against the union instead means
// `scan --out x` or `capture --seconds 10` is accepted and then silently ignored - the caller is
// told nothing, and gets a clip that is not what they asked for.
const SUBJECT_FLAGS = {
  report: ["example", "out", "seconds", "width", "height", "scale", "list", "review-out", "snapshot-out"],
  capture: ["out", "cols", "rows", "script", "max-mb", "exit-grace", "progress"],
  render: ["cast", "out", "seconds", "idle", "hold", "width", "height", "font", "scale", "tail", "head", "end-hold", "intro", "ask", "speed-windows", "allow-findings", "show-command", "until", "until-after", "until-gap"],
  loop: ["cast", "example", "example-after", "seconds-resolved", "out", "split", "seconds-gen", "seconds-apply", "seconds-review", "tail-gen", "tail-apply", "idle", "hold", "width", "height", "font", "scale", "dpr", "intro", "end-hold", "ask", "allow-findings", "show-command"],
  scan: ["cast", "ask"],
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
  // An EMPTY `--ask` is silently ignored downstream - `askFromCast` falls back to the cast's own
  // prompt - so an operator blanking a dirty title card would be told to re-capture instead, with
  // no sign their override did nothing. Say so rather than guessing which they meant.
  if ("ask" in args && !String(args.ask).trim()) {
    throw new Error("--ask needs text; omit it entirely to use the prompt the cast already carries");
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
    if (BOOLEAN_FLAGS.has(key)) { out[key] = true; }
    else if (next !== undefined && !next.startsWith("--")) { out[key] = argv[++i]; }
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

// A capture watchdog is given in SECONDS on the command line and used in MILLISECONDS inside, and
// both ends of that conversion have to be refused rather than silently accepted: `1e308` seconds
// becomes Infinity milliseconds, and `0.0004` seconds rounds to zero - each of which turns a
// watchdog the operator explicitly asked for into no watchdog at all, which is the failure the
// watchdogs exist to prevent.
export function watchdogMs(args, key, defaultMs, { allowZero = false } = {}) {
  const seconds = args[key] == null ? defaultMs / 1000 : Number(args[key]);
  if (!Number.isFinite(seconds) || seconds < 0 || (!allowZero && seconds <= 0)) {
    throw new Error(allowZero
      ? `Option --${key} must be a non-negative number of seconds (0 turns it off)`
      : `Option --${key} must be a positive number of seconds`);
  }
  const ms = seconds === 0 ? 0 : Math.max(1, Math.round(seconds * 1000));
  if (!Number.isFinite(ms)) throw new Error(`Option --${key} is too large: ${args[key]} seconds`);
  return ms;
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

// What the terminal window chrome may say. The launch command is what the operator TYPED, and on a
// real machine that is an inventory of internal tooling - MCP server names, hosts, org-specific
// flags. None of it is a secret by any rule, so it survives every redaction pass and then plays in
// every frame, including the poster. The program name alone carries the whole meaning a viewer
// needs, so that is the default and the full command is opt-in.
// Join argv back into the string a cast stores, re-quoting any element that holds whitespace so the
// result round-trips. Joining bare loses the boundary, and a path with spaces then reads as several
// tokens - which is how a directory name reached the window chrome.
export function joinCommand(argv) {
  return (Array.isArray(argv) ? argv : [])
    // Backslashes are escaped BEFORE quotes, or a value ending in one would emit `\"` and be read
    // back as an escaped quote - the token would then swallow the rest of the line. This form is
    // for STORAGE (it must round-trip through tokenizeCommand); use displayCommand for the screen.
    .map((a) => (/\s/.test(String(a))
      ? '"' + String(a).replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"'
      : String(a)))
    .join(" ");
}

// The same invocation as a human reads it. Storage has to escape backslashes so the string parses
// back exactly; a viewer should just see the path they typed, so this quotes without doubling.
export function displayCommand(argv) {
  return (Array.isArray(argv) ? argv : [])
    .map((a) => (/\s/.test(String(a)) ? '"' + String(a) + '"' : String(a)))
    .join(" ");
}

// Split a stored command string back into argv, tracking which tokens were QUOTED. Reverse
// engineering a joined string is inherently lossy, which is why a cast now stores `argv` too and
// the helpers below prefer it; this is the fallback for a legacy or foreign cast.
export function tokenizeCommand(raw) {
  const tokens = [];
  let current = "";
  let quote = null;
  let quoted = false;
  let started = false;
  const push = () => {
    if (started) tokens.push({ value: current, quoted, closed: quote === null });
    current = "";
    quoted = false;
    started = false;
  };
  for (let i = 0; i < String(raw == null ? "" : raw).length; i++) {
    const ch = raw[i];
    if (quote) {
      // Backslash escaping is a double-quote convention, and it covers a literal backslash as well
      // as a quote - joinCommand escapes both, so a value ending in a separator round-trips instead
      // of turning its closing quote into an escaped one.
      if (ch === "\\" && quote === '"' && (raw[i + 1] === quote || raw[i + 1] === "\\")) {
        current += raw[i + 1];
        i += 1;
        continue;
      }
      if (ch === quote) { quote = null; continue; }
      current += ch;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      // Only a token that BEGINS with a quote is a quoted value. `-p="x y"` starts bare, so the
      // flag is still recognised; `"value -p hidden"` starts quoted, so its inner -p is not.
      if (!started) quoted = true;
      started = true;
      continue;
    }
    if (/\s/.test(ch)) { push(); continue; }
    current += ch;
    started = true;
  }
  push();
  return tokens;
}

// What the terminal window chrome may say. The launch command is what the operator TYPED, and on a
// real machine that is an inventory of internal tooling - MCP server names, hosts, org-specific
// flags. None of it is a secret by any rule, so it survives every redaction pass and then plays in
// every frame, including the poster. The program name alone carries the whole meaning a viewer
// needs, so that is the default and the full command is opt-in.
export function windowLabel(command, options = {}) {
  // A cast stores argv, so the program is known EXACTLY and nothing has to be guessed back out of
  // a joined string. Everything below is the fallback for a cast that predates that.
  const isArgv = Array.isArray(command);
  const raw = isArgv ? displayCommand(command).trim() : String(command == null ? "" : command).trim();
  if (!raw) return "session";
  // parseArgs stores the CLI spelling; a direct caller uses the camelCase one.
  if (options.showCommand === true || options["show-command"] === true) return raw;

  let first;
  if (isArgv) {
    first = String(command[0] == null ? "" : command[0]).trim();
  } else {
    // Leading NAME=value assignments are the shell's, not the program - and one can carry a token.
    // They are stripped off the STRING first so everything below, including the path recovery,
    // operates on the actual command; checking the raw string would skip a command that opens with
    // an assignment and fall back to the leaky first token.
    let rest = raw;
    let assignment = /^[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S*)\s+/.exec(rest);
    while (assignment) {
      rest = rest.slice(assignment[0].length);
      assignment = /^[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|\S*)\s+/.exec(rest);
    }
    const tokens = tokenizeCommand(rest);
    // An unterminated quote swallowed the rest of the line, so the token is not a value at all -
    // trusting it published the whole flag tail as the window title.
    if (tokens.some((t) => !t.closed)) return "session";
    first = tokens.length ? tokens[0].value : "";
    // An UNQUOTED path with spaces was flattened by an older capture, so the first token is only a
    // FRAGMENT of it. Recover the whole path - but ONLY when the command starts at a path root, or
    // the scan would run across argument boundaries and republish a flag ("copilot --config x.exe").
    // Greedy, so a directory that merely CONTAINS a dotted name ("contoso.com Projects") does not
    // end the match early.
    if ((!tokens[0] || !tokens[0].quoted)
        && /^(?:[A-Za-z]:[\\/]|[\\/]|\.{1,2}[\\/]|~[\\/])/.test(rest)) {
      const whole = /^(.*\.(?:exe|cmd|bat|ps1))(?=\s|$)/i.exec(rest);
      // With no recognisable executable extension the path cannot be reassembled. The first token
      // is the whole program only when what FOLLOWS it is a flag (or nothing); anything else means
      // the path was split across tokens, and publishing the first one would leak a directory name.
      const next = tokens[1];
      if (whole) first = whole[1];
      else if (next && !next.value.startsWith("-")) return "session";
    }
  }
  // Anything that is not a plausible bare program name - a flag, a leftover assignment, an empty
  // token - is NOT published. The whole premise here is that a command's shape cannot be trusted.
  if (!first || first.startsWith("-") || first.includes("=")) return "session";
  // A token ending in a path separator has no basename; falling back to the whole token published
  // the entire path. Every other rejection here fails closed, and so does this one.
  const base = first.split(/[\\/]/).pop();
  if (!base) return "session";
  const label = base.replace(/\.(exe|cmd|bat|ps1|com)$/i, "");
  return label && !label.startsWith("-") ? label : "session";
}

// The prompt a `-p` invocation carried, and NOTHING after it. The extraction used to run to the end
// of the string, so `copilot -p "review this" --disable-mcp-server kusto` painted the flags across
// the title card in the largest type in the clip - the same leak the window chrome had, on a louder
// surface. Matching is done on TOKENS, so a `-p` sitting inside another argument's quoted value is
// not mistaken for the flag.
export function promptFromCommand(command) {
  // An argv element IS an exact token, so it is treated as quoted: a prompt may then legitimately
  // begin with a dash, and a following positional argument is never joined onto it.
  const tokens = Array.isArray(command)
    ? command.map((a) => ({ value: String(a), quoted: true, closed: true }))
    : tokenizeCommand(command);
  if (tokens.some((t) => !t.closed)) return null;
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (token.quoted && !token.value.startsWith("-p")) continue;
    let rest = null;
    if (token.value === "-p") rest = tokens.slice(i + 1);
    else if (token.value.startsWith("-p=")) return token.value.slice(3).trim() || null;
    if (!rest) continue;
    if (!rest.length) return null;
    // A quoted prompt is exactly one token, so it may legitimately begin with a dash.
    if (rest[0].quoted) return rest[0].value.trim() || null;
    const words = [];
    for (const word of rest) {
      if (!word.quoted && word.value.startsWith("-")) break;
      words.push(word.value);
    }
    return words.join(" ").trim() || null;
  }
  return null;
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
    // Loaded from FILE, not from a local http server. A report the skill generates in "not shareable"
    // mode links its runtime with absolute `file:///` URLs into the installed plugin, and an http
    // page is not allowed to load a file:// subresource - so the layer never booted, every beat
    // found nothing, and the only clue was one "never signalled ready" line. A shareable report works
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

// The step driver: it decides WHEN to send each turn, and nothing else. The clock, the sleeper and
// the session are injected, so the whole of it - including the paths that only happen after an hour
// of waiting - is exercised deterministically instead of by trying to reproduce a wedge.
export async function driveScript(script, session, hooks = {}) {
  const {
    now = Date.now,
    nap = sleep,
    pollMs = 200,
    warn = (line) => console.warn(line),
    onWaiting = () => {},
    onTimeout = () => {},
  } = hooks;
  // Sleeps are taken in poll-sized pieces so an ended session does not have to be waited out: a
  // step may legitimately ask for a long delay, and the whole point of an interrupt is that the
  // operator gets the cast now rather than after the recipe's next timer.
  const napChunked = async (ms) => {
    const until = now() + ms;
    while (now() < until) {
      if (session.exited()) return;
      await nap(Math.min(pollMs, until - now()));
    }
  };
  for (const step of script.steps) {
    const startedAt = now();
    // Each step only reads output produced SINCE IT BEGAN. Sharing one buffer let a step whose
    // marker had already appeared for an earlier step fire immediately, before the session had
    // done anything the step was waiting on.
    const from = session.seen();
    let skipped = false;
    for (;;) {
      if (session.exited()) throw new Error(`session ended while step "${step.mark}" was waiting`);
      const state = stepReady(step, {
        buffer: session.since(from),
        lastDataAt: session.lastDataAt(),
        now: now(),
        startedAt,
        fileExists: step.expectFile ? fileReady(step.expectFile, startedAt) : false,
      });
      if (state.skip) {
        warn(`  script: optional step "${step.mark}" ${state.reason}; skipping`);
        skipped = true;
        break;
      }
      if (state.ready) {
        if (state.timedOut) {
          // A non-optional step that gives up is NOT a clean run: the session did not do the
          // thing the recipe waited for. Send anyway (the alternative is hanging), but remember
          // it - a warning that scrolled past forty minutes ago is a warning nobody saw, and the
          // shipped loop recipe really did time out waiting for a marker the agent never printed
          // while its summary line still read like a clean capture.
          onTimeout({ mark: step.mark, reason: state.reason });
          warn(`  script: step "${step.mark}" ${state.reason}; sending anyway`);
        }
        break;
      }
      onWaiting(`step "${step.mark}" ${state.reason}`);
      await nap(pollMs);
    }
    onWaiting(null);
    if (skipped) continue;
    if (step.delayMs) await napChunked(step.delayMs);
    if (session.exited()) throw new Error(`session ended before step "${step.mark}" could be sent`);
    const payload = stepPayload(step);
    // Record WHAT WAS TYPED alongside the mark, so a render can put the real prompt on its
    // title card instead of a paraphrase somebody has to keep in sync by hand.
    session.mark(step.mark, payload.replace(/\u001b\[20[01]~/g, ""));
    session.write(payload);
    const submit = stepSubmit(step);
    if (submit) { await napChunked(step.submitMs); session.write(submit); }
  }
}

// The capture's control core: collect the stream, drive the script, decide when the session is over,
// and WRITE THE CAST. The pty, the clock and the sleeper are parameters so this whole path is
// testable without either - which matters because the expensive failures here are the ones that only
// appear after an hour.
//
// The rule this exists to enforce: a capture ALWAYS finalizes. It used to wait on `child.onExit`
// with no bound at all, so a TUI that printed its answer and then never exited held a ninety minute
// session in memory forever and wrote nothing (one such capture sat for seventeen hours), and the
// only way out - Ctrl+C - exited before writing anything, losing the lot. Now the wall clock ends
// the session, an interrupt ends it too, and both still produce the cast.
export async function captureSession({
  child,
  script = null,
  outFile,
  outRoot = OUT_ROOT,
  rules = rulesForThisMachine(),
  command = [],
  cols = 120,
  rows = 30,
  maxMb = 48,
  maxBytes = null,
  exitGraceMs = DEFAULT_EXIT_GRACE_MS,
  killGraceMs = DEFAULT_KILL_GRACE_MS,
  progressMs = DEFAULT_PROGRESS_MS,
  pollMs = 200,
  tailMs = 250,
  now = Date.now,
  nap = sleep,
  onData = () => {},
  onEnd = () => {},
  warn = (line) => console.warn(line),
  progress = () => {},
  attachInterrupt = () => {},
}) {
  const started = now();
  const events = [];
  const marks = [];
  const timedOutSteps = [];
  let buffer = "";
  // Total bytes ever seen, which never rewinds. `buffer` keeps only a recent window, so a plain
  // index into it goes stale the moment that window slides - see `since` below.
  let seen = 0;
  let bytes = 0;
  let lastDataAt = started;
  let childExited = false;
  let exitCode = null;
  let driverError = null;
  let overflowed = false;
  let waiting = null;
  // The session is over once the supervisor says so, not only when the child dies. Without this the
  // driver would keep waiting out a step's timeout after an interrupt had already ended the session
  // - re-creating, on the very path that exists to stop a hang, a wait measured in tens of minutes.
  let sessionOver = false;
  // Output produced since a step began, as much of it as is still retained. Slicing `buffer` by a
  // recorded LENGTH breaks once the window slides: the offset then points past what is kept, and a
  // step whose buffer was already full when it started would slice an empty string and wait for its
  // marker forever - which for the shipped script is a twenty-five minute hang.
  const since = (fromSeen) => buffer.slice(Math.max(0, buffer.length - (seen - fromSeen)));

  // How the session was ENDED by something other than the session itself. Every forced ending goes
  // through here so the supervisor is the one place that decides when to stop waiting: an ending
  // that only killed the child (as the size guard used to) leaves a child that ignores the kill
  // holding the recording forever, which is the very failure this file exists to prevent.
  let forcedAt = null;
  let forcedReason = "interrupt";
  let killedAt = null;
  // Recorded when the ending is FORCED, not when the supervisor kills: a child that dies obediently
  // would otherwise be reported as a clean exit, which is the common case in production and exactly
  // the ending the operator must not be told was clean.
  let gaveUpBecause = null;
  const forceEnd = (reason) => {
    if (forcedAt !== null) return false;
    forcedAt = now();
    forcedReason = reason;
    gaveUpBecause = reason;
    return true;
  };

  // 48MB of captured BYTES, not code units. The binding constraint is not the capture, it is
  // FINALISATION: scrubbing builds a projection, an offset map and a second copy of every event,
  // then JSON.stringify builds another - measured at roughly 25x the captured size in resident
  // memory. A limit that only bounded the capture would still run out of memory in the step that
  // writes the cast, losing the recording this exists to save.
  const guardSize = makeSizeGuard(maxBytes == null ? captureLimitBytes(maxMb) : maxBytes, () => {
    overflowed = true;
    warn(`\n  capture: reached the ${maxMb}MB limit (--max-mb); ending the session and `
      + "keeping what was recorded so far.");
    forceEnd("overflow");
    killedAt = now();
    try { child.kill(); } catch (e) { /* already gone */ }
  });

  child.onExit(({ exitCode: code }) => {
    childExited = true;
    exitCode = code == null ? 0 : code;
  });
  child.onData((data) => {
    onData(data);
    events.push({ t: now() - started, data });
    // The driver waits on what the session has PRINTED, so the buffer it reads is kept here rather
    // than re-derived. It is capped because a long agent run prints megabytes and the only thing a
    // step ever looks for is a recent marker.
    buffer = (buffer + data).slice(-65536);
    seen += data.length;
    const length = Buffer.byteLength(data, "utf8");
    bytes += length;
    lastDataAt = now();
    // Everything captured is held in memory until the child exits, because the raw stream is never
    // written to disk unscrubbed. So the size is bounded and the capture is ENDED cleanly at the
    // limit - the operator keeps what was recorded up to that point and is told plainly why it
    // stopped, instead of the process dying with nothing.
    guardSize(length);
  });

  // The operator's escape hatch, handed straight back to the caller so a signal handler can use it.
  // It reports whether it was the operator's FIRST interrupt: a second one means they will not wait
  // for the write either, and the caller is free to exit hard. Counted SEPARATELY from the forced-end
  // latch - an overflow or a failed script has already forced the ending, and if that consumed the
  // latch the operator's first Ctrl+C would be treated as their second and throw the session away,
  // which is the exact loss this whole change exists to prevent.
  let interrupts = 0;
  attachInterrupt(() => {
    interrupts += 1;
    forceEnd("interrupt");
    return interrupts === 1;
  });

  // Scripted turns are driven alongside the live stdin forwarding the caller wires up, so an
  // operator watching can still intervene.
  let driverDoneAt = null;
  const driver = script
    ? driveScript(script, {
      exited: () => childExited || sessionOver,
      since,
      seen: () => seen,
      lastDataAt: () => lastDataAt,
      write: (text) => child.write(text),
      mark: (label, text) => marks.push({
        label,
        t: now() - started,
        eventIndex: events.length,
        // Scrubbed like everything else, and capped because one of these steps pastes a whole
        // review bundle.
        text: scrubText(text, rules).slice(0, 2000),
      }),
    }, {
      now,
      nap,
      pollMs,
      warn,
      onWaiting: (text) => { waiting = text; },
      onTimeout: (entry) => timedOutSteps.push(entry),
    })
      .catch((e) => {
        // A driver that gives up must not leave the session sitting on a prompt forever - a capture
        // waiting on a step that can no longer be satisfied would otherwise hang for the whole of
        // every remaining timeout, which the shipped script measures in tens of minutes. The
        // supervisor is told the session is ending so it finalizes on the KILL grace rather than
        // sitting out the whole exit grace waiting for a child it has already killed.
        driverError = e;
        warn(`  script: ${e.message}; ending the session`);
        if (!childExited && forceEnd("driver-error")) killedAt = now();
        try { child.kill(); } catch (killErr) { /* already gone */ }
      })
      .finally(() => { driverDoneAt = now(); waiting = null; })
    : null;

  // The supervisor. Nothing here trusts the stream: a TUI repaints, goes quiet mid-thought, and can
  // fall silent for an hour while the child stays alive, so the decision to stop is the clock's.
  let ended = null;
  let quietMs = 0;
  let nextProgressAt = started + progressMs;
  // Between steps, and for the whole exit grace after the last turn, there is no step to name - but
  // "no script; the operator is driving" would be a lie during exactly the wedge this line exists to
  // diagnose, so a scripted capture says where the SCRIPT is instead.
  const scriptState = () => {
    if (!script) return null;
    return driverDoneAt !== null
      ? "the script has sent its last turn; waiting for the session to exit"
      : "between steps";
  };
  for (;;) {
    if (childExited) { ended = gaveUpBecause || "exit"; break; }
    const at = now();
    const state = sessionEndState({ now: at, driverDoneAt, interruptedAt: forcedAt, killedAt, exitGraceMs, killGraceMs });
    // `sessionEndState` knows only that something forced the ending; which something it was is the
    // supervisor's to say, so the cast reports being cut short at its size limit as exactly that.
    const reason = state.reason === "interrupt" ? forcedReason : state.reason;
    if (state.action === "kill") {
      killedAt = at;
      gaveUpBecause = reason;
      quietMs = at - lastDataAt;
      warn(`\n  WARNING: ${stallNotice({ ended: reason, quietMs, graceMs: exitGraceMs })}`);
      try { child.kill(); } catch (e) { /* already gone */ }
    } else if (state.action === "finalize") {
      // The child ignored the kill. Stop waiting for it rather than let it hold the recording.
      ended = reason;
      break;
    }
    if (progressMs > 0 && at >= nextProgressAt) {
      progress(progressLine({ now: at, startedAt: started, lastDataAt, bytes, waiting: waiting || scriptState() }));
      nextProgressAt = at + progressMs;
    }
    await nap(pollMs);
  }
  sessionOver = true;
  // onExit can fire while the pty still has buffered output in flight, and the tail of a session
  // (the final result, the closing prompt) is exactly what a demo wants to show. Let it land.
  if (tailMs) await nap(tailMs);
  if (driver) await driver;
  onEnd({ ended });

  // The COMMAND is part of the clip too - it is the title bar of the render - and a real invocation
  // can carry a credential (`curl -H "Authorization: ******"`), so it is scrubbed like output.
  // Argv elements holding whitespace are re-quoted so the stored string round-trips: joining them
  // bare loses the boundary, and a Windows path with a space then reads as several tokens.
  const commandLine = scrubText(joinCommand(command), rules);

  // Scrub BEFORE anything touches the disk: the raw stream is never persisted.
  const scrubbed = scrubEvents(events, { rules });
  const cast = {
    version: 1,
    recordedAt: new Date().toISOString(),
    command: commandLine,
    // The SAME invocation as argv, so the program name is known exactly rather than reverse
    // engineered out of a joined string (a path with spaces, or a value ending in .exe, cannot be
    // told apart once flattened). DERIVED FROM the scrubbed line rather than scrubbed element-wise:
    // a rule that spans argument boundaries only fires on the joined text, so splitting first could
    // let something through that `command` itself would have caught.
    argv: tokenizeCommand(commandLine).map((t) => t.value),
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
  const castBytes = JSON.stringify(cast);
  ensureDir(path.dirname(outFile));
  fs.writeFileSync(outFile, castBytes);
  // Provenance is recorded OUT OF BAND - see tools/provenance.mjs. The `scrubbedBy` field above is
  // a claim the file makes about itself and is never trusted for this decision.
  recordCapture(outRoot, castBytes);
  const transcriptFile = outFile.replace(/\.cast\.json$/, "") + ".transcript.txt";
  fs.writeFileSync(transcriptFile, scrubbed.transcript);

  return {
    outFile,
    transcriptFile,
    cast,
    marks,
    timedOutSteps,
    overflowed,
    driverError,
    ended,
    quietMs,
    exitCode,
    redactions: scrubbed.redactions,
    leftover: scanText(castText(cast), rules),
  };
}

// In RAW MODE Ctrl+C is a byte the session receives, not a signal to this process - and that is
// deliberate: the operator has to be able to cancel a turn inside the TUI being filmed. So Ctrl+C
// can never end a wedged interactive capture, and the escape hatch is Ctrl+\ (0x1c, the terminal's
// traditional quit key), which nothing in these sessions uses. Kept separate from the pty so the
// decision is testable without one.
export const QUIT_KEY = 0x1c;

export function isQuitKey(data) {
  if (data == null) return false;
  if (Buffer.isBuffer(data)) return data.includes(QUIT_KEY);
  return String(data).includes(String.fromCharCode(QUIT_KEY));
}

// What a keystroke does. Kept out of the pty wiring so the one decision that must never drift -
// Ctrl+C reaches the session, Ctrl+\ ends the capture - is pinned by a test rather than by reading.
export function handleCaptureInput(data, { isTTY = false, onQuit = () => {}, write = () => {} } = {}) {
  if (isTTY && isQuitKey(data)) {
    onQuit();
    return "quit";
  }
  try { write(data.toString("utf8")); } catch (e) { /* the child is gone */ }
  return "forwarded";
}

// The closing summary, built as DATA so the one place that has to repeat what the supervisor
// measured is testable without a pty. Both halves of that matter: a summary that reads like a clean
// take is how a wrong ending gets published, and one that invents a number (it claimed the session
// had been quiet for 0s while the supervisor's own warning carried the real figure) is how an
// accurate warning stops being believed.
export function captureSummaryLines(outcome, { maxMb = 48, exitGraceMs = DEFAULT_EXIT_GRACE_MS } = {}) {
  const lines = [];
  // A script that could not finish means the session is NOT the one the recipe describes - a turn
  // may never have been sent. The cast is still written, because a long capture is expensive and the
  // partial recording may be worth keeping, but it must never look like a clean run.
  if (outcome.driverError) {
    lines.push({ level: "error", text: `\nFAILED: the capture script did not complete: ${outcome.driverError.message}` });
    lines.push({ level: "error", text: "The cast below is PARTIAL - it does not contain every turn the script asked for." });
  }
  lines.push({ level: "log", text: `\ncast:       ${outcome.outFile}` });
  lines.push({ level: "log", text: `transcript: ${outcome.transcriptFile}` });
  lines.push({ level: "log", text: `redacted:   ${outcome.redactions} match(es) scrubbed before writing` });
  if (outcome.overflowed) {
    lines.push({ level: "warn", text: `  NOTE: the session was cut short at the ${maxMb}MB capture limit, so this cast is `
      + "not the whole session." });
  }
  // The expensive silent miss: a step waited its whole timeout, the session never produced what the
  // recipe asked for, and the closing summary still read like a clean take. Say it here, where it
  // cannot scroll away, because deciding to re-run is a lot cheaper than publishing the wrong clip.
  for (const step of outcome.timedOutSteps) {
    lines.push({ level: "warn", text: `  WARNING: ${stepGaveUpNotice(step)}` });
  }
  // The ENDING itself, for the same reason. An overflow and a failed script already have their own
  // messages above, so only the two endings that would otherwise pass silently are named here.
  if (outcome.ended === "interrupt" || outcome.ended === "no-exit") {
    lines.push({ level: "warn", text: `  WARNING: ${stallNotice({ ended: outcome.ended, quietMs: outcome.quietMs, graceMs: exitGraceMs })}` });
  }
  if (outcome.leftover && outcome.leftover.length) {
    lines.push({ level: "warn", text: `  WARNING: ${outcome.leftover.length} finding(s) survived scrubbing - render will refuse this cast` });
  }
  lines.push({ level: "log", text: "READ THE TRANSCRIPT before you render or publish: automated redaction is a net, not a gate." });
  return lines;
}

// An ending that was not the session's own is a FAILED capture, whatever landed on disk - the cast
// is kept, but a caller must be able to tell without parsing the summary.
export function captureExitCode(outcome) {
  if (outcome.ended === "interrupt") return 130;
  if (outcome.driverError || outcome.overflowed || outcome.ended !== "exit") return 1;
  return outcome.exitCode || 0;
}

async function captureTerminal(args) {
  const command = args.passthrough;
  if (!command.length) throw new Error("capture needs a command after --, e.g. -- copilot");
  const cols = Math.round(numberOpt(args, "cols", 120));
  const rows = Math.round(numberOpt(args, "rows", 30));
  const maxMb = args["max-mb"] == null ? 48 : args["max-mb"];
  const maxBytes = captureLimitBytes(maxMb);
  const exitGraceMs = watchdogMs(args, "exit-grace", DEFAULT_EXIT_GRACE_MS);
  const progressMs = watchdogMs(args, "progress", DEFAULT_PROGRESS_MS, { allowZero: true });
  // Every option is settled BEFORE the pty is loaded and the session spawned: a typo should cost a
  // second, not a session that is already running with a child attached.
  const script = args.script ? readScript(String(args.script)) : null;
  const pty = loadOptional("node-pty");
  const executable = resolveExecutable(command[0]);
  const launch = launchSpec(executable, command.slice(1));
  const outFile = args.out
    ? path.resolve(String(args.out))
    : path.join(OUT_ROOT, `session-${stamp()}.cast.json`);
  ensureDir(path.dirname(outFile));

  const rules = rulesForThisMachine();
  // A second scrubber for the LIVE stream, kept separate from the one that cleans the cast so the
  // two never share carry state.
  const liveScrubber = createScrubber({ rules });
  const child = pty.spawn(launch.file, launch.args, {
    name: "xterm-256color",
    cols,
    rows,
    cwd: process.cwd(),
    env: process.env,
  });

  const wasRaw = process.stdin.isRaw;
  const onInput = (data) => handleCaptureInput(data, {
    isTTY: process.stdin.isTTY,
    onQuit: () => onSignal(),
    write: (text) => child.write(text),
  });
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
  // The FIRST signal (or Ctrl+\ from a raw-mode terminal) ends the session and lets the capture
  // finalize. It used to kill the child and exit(130) without writing anything, so stopping a wedged
  // capture by hand - the operator's only option - threw away the entire session. A SECOND one is
  // the operator saying they will not wait for the write either, and only then is the process torn
  // down.
  let interrupt = null;
  const onSignal = () => {
    if (interrupt && interrupt()) {
      restore();
      console.warn("\n  capture: interrupted; ending the session and writing what was recorded...");
      return;
    }
    restore();
    // The scrubber holds a whitespace-free run back until it can prove it is not a credential.
    // Exiting without flushing loses that text from the operator's own terminal for good.
    if (!process.stdout.isTTY) { try { process.stdout.write(liveScrubber.end()); } catch (e) { /* closed */ } }
    try { child.kill(); } catch (e) { /* already gone */ }
    process.exit(130);
  };
  process.on("SIGINT", onSignal);
  process.on("SIGTERM", onSignal);
  // Ctrl+\ is what the docs tell an interactive operator to press, and once the first one has put
  // the terminal back out of raw mode a second one is a real SIGQUIT - which Node terminates on by
  // default, mid-finalization, while the cast is still being scrubbed and serialised.
  process.on("SIGQUIT", onSignal);

  let outcome;
  try {
    if (process.stdin.isTTY) process.stdin.setRawMode(true);
    process.stdin.resume();
    process.stdin.on("data", onInput);
    process.stdout.on("resize", onResize);
    outcome = await captureSession({
      child,
      script,
      outFile,
      rules,
      command,
      cols,
      rows,
      maxMb,
      maxBytes,
      exitGraceMs,
      progressMs,
      // The operator's own terminal shows the session RAW, because they are interacting with it.
      // Anything else - a pipe, a CI log, an agent transcript - gets the scrubbed stream, since a
      // credential printed to a persisted log leaks just as surely as one written into the cast.
      onData: (data) => process.stdout.write(process.stdout.isTTY ? data : liveScrubber.push(data)),
      // Progress goes to stderr, and only when stdout is NOT a terminal. An operator sitting in
      // front of the TUI can already see it is stuck, and a status line drawn into a live TUI
      // corrupts the very screen the clip is of; the unattended run whose log nobody is watching is
      // the case that needs it.
      progress: process.stdout.isTTY
        ? () => {}
        : (line) => { try { process.stderr.write(`  ${line}\n`); } catch (e) { /* closed */ } },
      attachInterrupt: (fn) => { interrupt = fn; },
      onEnd: () => restore(),
    });
  } finally {
    restore();
    // Never orphan the child. The happy path leaves through onExit, but a setup throw or a signal
    // would otherwise leave a pty running with nobody reading it.
    try { child.kill(); } catch (e) { /* already gone */ }
    // Whatever the live scrubber was holding back belongs on the operator's stream too.
    if (!process.stdout.isTTY) { try { process.stdout.write(liveScrubber.end()); } catch (e) { /* closed */ } }
    process.off("SIGINT", onSignal);
    process.off("SIGTERM", onSignal);
    process.off("SIGQUIT", onSignal);
  }

  for (const line of captureSummaryLines(outcome, { maxMb, exitGraceMs })) {
    if (line.level === "error") console.error(line.text);
    else if (line.level === "warn") console.warn(line.text);
    else console.log(line.text);
  }
  // node-pty keeps handles alive after the child exits, so the process would hang on its own - but
  // exiting outright can truncate a piped stdout, losing the paths just printed. Flush, then go.
  await new Promise((done) => process.stdout.write("", done));
  process.exit(captureExitCode(outcome));
}

// A cast's COMMAND is shown in the clip's title bar, so the gate has to read it too - scanning only
// the output would wave through a credential passed on the command line. `argv` carries the same
// invocation and is what the label now reads, so it is scanned as well: a cast whose two forms ever
// diverge must not have an unscanned half.
// Everything a cast can put ON SCREEN, so the credential gate scans no less than the render draws.
// The marks matter as much as the stream: `askFromCast` fills the title card - the largest type in
// the clip - from a mark's text, so a foreign, legacy or hand-edited cast whose mark carries the
// launch command (or a host, a home path, a token) would otherwise pass every gate and be published
// in the opening frames. For a cast this tool captured the ask was also typed into the terminal, so
// it is in `events` too; that is exactly why the omission was invisible.
export function castText(cast) {
  const argv = Array.isArray(cast.argv) ? cast.argv.join("\n") : "";
  const marks = Array.isArray(cast.marks)
    ? cast.marks.map((m) => (m && m.text ? String(m.text) : "")).join("\n")
    : "";
  return `${cast.command || ""}\n${argv}\n${marks}\n${cast.events.map((e) => e.data).join("")}`;
}

// Everything that will be RENDERED, kept as SEPARATE surfaces because that is how they are fixed.
// The cast is fixed by re-capturing or by adding a redaction rule; the `--ask` is operator-supplied,
// never touches the cast, and is fixed by retyping it. Scanning the two as one string could only
// report an undifferentiated count, which sent an operator whose ask was dirty to `scan --cast`
// (findings: 0) and to a re-capture that changes nothing.
export function publishedSurfaces(cast, args = {}) {
  return { cast: castText(cast), ask: askFromCast(cast, args) };
}

// The gate, per surface. The ask counts as its OWN surface only when the operator supplied it:
// every other ask is drawn FROM the cast, so attributing it to `--ask` would be the same dead end
// pointing the other way - telling the operator to edit a flag they never passed.
//
// A derived ask is still SCANNED, in its own `card` bucket. It is RECONSTRUCTED from the cast
// rather than copied out of it - `promptFromCommand` drops the quotes around a `-p` value, so
// `-p ghp_"0123..."` scans clean as cast text and dirty the moment the title card renders it - so
// skipping it would publish a credential the old single scan caught. Its remedy is the cast's, and
// a rule the cast scan already reported is not repeated.
//
// `boundary` keeps what only the JOINED text catches. `scanText` rejoins a hard-wrapped value
// across a line break, so a credential whose halves land at the end of the cast and the start of
// the ask fired when the two were scanned as one string and fires in neither half alone - both
// halves are still published, and both are still legible. A finding that belongs to neither
// surface alone belongs to both. The join is made from the STRIPPED surfaces so no OSC sequence
// can span it: an unterminated one at the end of the cast would otherwise swallow the start of the
// ask and hide exactly the finding this bucket exists to keep.
export function gateFindings(cast, args = {}, rules = undefined) {
  const surfaces = publishedSurfaces(cast, args);
  const castFindings = scanText(surfaces.cast, rules);
  const askFindings = scanText(surfaces.ask, rules);
  // Truthiness, matching `askFromCast`: an empty `--ask` falls back to the cast-derived ask there,
  // so the two must agree about what "the operator supplied it" means or the message names the
  // wrong surface.
  const supplied = Boolean(args.ask);
  // Findings are indexed into the OSC-STRIPPED text, so every coordinate here is measured there:
  // a cast carrying a shell title or a hyperlink is shorter to the scanner than it is on disk, and
  // a raw-length offset files an ordinary ask finding as a boundary one - handing the operator the
  // re-capture instruction this whole gate exists to stop giving them.
  const castPlain = stripOsc(surfaces.cast);
  const askPlain = stripOsc(surfaces.ask);
  // A derived ask that is a literal SLICE of the cast reports the same findings twice, so it is
  // dropped. A REBUILT one (quotes stripped from a `-p` value) is kept whole - deduping it by rule
  // name would hide a second, different credential of a rule the cast already reported.
  const card = supplied || castPlain.includes(askPlain) ? [] : askFindings;
  const offset = castPlain.length + 1;
  const seen = new Set([
    ...castFindings.map((f) => `${f.rule}@${f.index}`),
    ...askFindings.map((f) => `${f.rule}@${f.index + offset}`),
  ]);
  const boundary = scanText(joinSurfaces(castPlain, askPlain), rules)
    .filter((f) => !seen.has(`${f.rule}@${f.index}`));
  return { cast: castFindings, ask: supplied ? askFindings : [], card, boundary, supplied };
}

// The two published surfaces, laid end to end for the boundary scan. Both are stripped FIRST so no
// OSC sequence can span the join, and a dangling introducer left at the end of the cast (a capture
// cut at the size limit ends mid-escape) is blanked: joined, the ask could supply the terminator it
// is missing and the sequence would swallow the very text this join exists to examine. The blank is
// the same width as the introducer, so every index the scanner reports still lines up.
function joinSurfaces(castPlain, askPlain) {
  const at = castPlain.lastIndexOf("\u001b]");
  const closed = at < 0 || /\u0007|\u001b\\/.test(castPlain.slice(at))
    ? castPlain
    : `${castPlain.slice(0, at)}  ${castPlain.slice(at + 2)}`;
  return `${closed}\n${askPlain}`;
}

// How many findings the gate has, across every surface. The clip is marked UNSAFE and the warning
// counts from this, so a surface added later cannot be left out of the count by accident.
export function findingCount(found) {
  return found.cast.length + found.ask.length + found.card.length + found.boundary.length;
}

function ruleNames(findings) {
  return [...new Set(findings.map((f) => f.rule))].join(", ");
}

// A path with a space is one argument, not two: unquoted, the command the refusal tells the
// operator to run is a command that cannot reproduce anything. Escaping is deliberately NOT
// attempted - the quoting rules differ between cmd, PowerShell and a POSIX shell, and a
// half-escaped string is worse than an honest placeholder - so a path carrying a quote or ending
// in a backslash (neither of which a real cast path does) is advertised as `<file>` instead.
function quoteArg(value) {
  const text = String(value);
  if (!/[\s"]/.test(text)) return text;
  if (text.includes('"') || text.endsWith("\\")) return "<file>";
  return `"${text}"`;
}

// What the refusal SAYS, per dirty surface. Each half names an action that can actually reproduce
// and fix that surface, and neither prescribes the other's remedy.
export function dirtyGateMessage(found, file = "<file>") {
  const at = quoteArg(file);
  const parts = [];
  if (found.cast.length) {
    parts.push(`this cast still scans dirty (${found.cast.length} finding(s): ${ruleNames(found.cast)}); `
      + `run 'scan --cast ${at}' to see them. `
      + "Re-capture or add a rule to tools/redact.mjs rather than publishing it.");
  }
  if (found.ask.length) {
    parts.push(`the --ask you passed scans dirty (${found.ask.length} finding(s): ${ruleNames(found.ask)}); `
      + "it is the text on your command line, not the cast, so re-capturing cannot change it and a "
      + "bare 'scan --cast' cannot see it. Retype the --ask, or reproduce the finding with "
      + `'scan --cast ${at} --ask "<text>"'.`);
  }
  if (found.card.length) {
    parts.push(`the title card this cast renders scans dirty (${found.card.length} finding(s): `
      + `${ruleNames(found.card)}); it is REBUILT from the cast (its ask mark, or the -p prompt in `
      + `its command), so the raw stream can read clean. Run 'scan --cast ${at}' to see it, then `
      + "re-capture or add a rule to tools/redact.mjs.");
  }
  if (found.boundary.length) {
    const remedy = found.supplied
      ? "Fix BOTH ends - retype the --ask and re-capture (or add a rule to tools/redact.mjs)."
      : "Both ends come from this cast (its stream and the title card it rebuilds), so re-capture "
        + "or add a rule to tools/redact.mjs.";
    parts.push(`${found.boundary.length} finding(s) (${ruleNames(found.boundary)}) span the cast and `
      + `the ask: neither half matches alone, so both are published and together they read as one `
      + `credential. ${remedy}`);
  }
  return parts.join("\n");
}

// The tail of a real capture is dead air: the session keeps recording until the recipe's quit step
// fires, so without this the clip spends its ending on an empty prompt and the exit screen. Says
// what it dropped, because silently shortening someone's session is its own kind of surprise.
function trimForRender(cast, args) {
  if (args.until == null && args["until-gap"] == null) {
    // Accepting an option and then ignoring it is the same failure the argument contract exists to
    // prevent: the operator asked for something and got a clip of the whole session instead.
    if (args["until-after"] != null) {
      throw new Error("--until-after only means something alongside --until or --until-gap");
    }
    return cast;
  }
  const out = trimCast(cast, {
    until: args.until == null ? null : String(args.until),
    untilGap: args["until-gap"] == null ? null : numberOpt(args, "until-gap", 0),
    after: args["until-after"] == null ? null : String(args["until-after"]),
  });
  console.log(`trimmed:  ${out.kept} of ${out.kept + out.dropped} events `
    + `(${(out.cutAtMs / 1000).toFixed(1)}s of a ${(out.sourceMs / 1000).toFixed(1)}s session)`);
  // A gap threshold is a value to STOP at, so one LARGER than the silence before the driver's
  // /exit never stops the walk and the trim runs on through the dead air it was asked to remove.
  // That failure is invisible until someone watches the ending, so say it here.
  if (out.dropped === 0) {
    console.warn("  NOTE: this trim dropped nothing. If the session has an idle tail, --until-gap is "
      + "probably LARGER than the silence before it - lower it below the recipe's quit idleMs.");
  }
  if (out.searchedWholeCast) {
    console.warn("  NOTE: this cast has no \"ask\" mark, so --until searched the WHOLE session - "
      + "including the prompt, which usually contains the marker word itself. Check the ending.");
  }
  return out.cast;
}

// This machine's ledger has no record of capturing this cast, so it was scrubbed with SOMEONE ELSE'S
// home path and account name - a clean scan here says very little. Said once, in one place.
function warnForeignCast(capturedHere) {
  if (capturedHere) return;
  console.warn("WARNING: this machine did not capture this cast, so it was never scrubbed at source,");
  console.warn("         and the home/account rules used here are THIS machine's. Read the whole");
  console.warn("         transcript before publishing anything rendered from it.");
}

function readCast(args) {
  if (!args.cast) throw new Error("--cast <file.cast.json> is required");
  const file = path.resolve(String(args.cast));
  if (!fs.existsSync(file)) throw new Error(`cast not found: ${file}`);
  const bytes = fs.readFileSync(file, "utf8");
  const cast = JSON.parse(bytes);
  if (!Array.isArray(cast.events)) throw new Error(`${file} is not a cast (no events array)`);
  // Decided from the BYTES against this machine's ledger, never from anything the cast says about
  // itself. A `scrubbedBy` field is a claim the file makes, and a forged one would suppress exactly
  // the warning that says the scan used the wrong machine's home/account rules.
  return { file, cast, capturedHere: wasCapturedHere(OUT_ROOT, bytes) };
}

function scanCast(args) {
  const { file, cast, capturedHere } = readCast(args);
  warnForeignCast(capturedHere);
  const rules = rulesForThisMachine();
  const surfaces = publishedSurfaces(cast, args);
  const found = gateFindings(cast, args, rules);
  const total = findingCount(found);
  console.log(`cast:     ${file}`);
  console.log(`events:   ${cast.events.length}`);
  console.log(`findings: ${total}${total
    ? ` (cast ${found.cast.length}, ask ${found.ask.length}, card ${found.card.length}, `
      + `boundary ${found.boundary.length})`
    : ""}`);
  // Every index is counted against the OSC-STRIPPED text the rules actually ran over, so the
  // excerpt has to be sliced from that same projection or it quotes the wrong 70 characters.
  const shown = {
    cast: stripOsc(surfaces.cast),
    ask: stripOsc(surfaces.ask),
    card: stripOsc(surfaces.ask),
    boundary: joinSurfaces(stripOsc(surfaces.cast), stripOsc(surfaces.ask)),
  };
  for (const surface of ["cast", "ask", "card", "boundary"]) {
    for (const finding of found[surface].slice(0, 25)) {
      const start = Math.max(0, finding.index - 20);
      console.log(`  ${surface}: ${finding.rule} @${finding.index}: `
        + `${JSON.stringify(shown[surface].slice(start, start + 70))}`);
    }
  }
  if (found.cast.length) {
    console.error("This cast must not be filmed as-is. Re-capture, or add a rule to tools/redact.mjs.");
  }
  if (found.ask.length) {
    console.error("This --ask must not be published as-is. Retype it; it is not in the cast, so "
      + "re-capturing cannot change it.");
  }
  if (found.card.length) {
    console.error("The title card this cast renders must not be published as-is. It is rebuilt from "
      + "the cast, so re-capture or add a rule to tools/redact.mjs.");
  }
  if (found.boundary.length) {
    console.error(`A finding spans the cast and the ask. Neither half matches alone, so fix BOTH ends${found.supplied ? "" : " (both come from this cast)"}.`);
  }
  if (total) process.exitCode = 1;
  return found;
}

// The invocation to reason about: `argv` when it is actually there, otherwise the flattened string.
// `[]` is TRUTHY in JavaScript, so a bare `cast.argv || cast.command` picks an empty argv over a
// perfectly good command and silently reports "session"; an `argv` of `""` does the opposite and
// falls through to the lossy string path. Neither is what the caller means.
function castInvocation(cast) {
  return Array.isArray(cast.argv) && cast.argv.length ? cast.argv : cast.command;
}

// What the chrome DRAWS. `windowLabel` decides what it may SAY, and its answer is still what the
// title card falls back to - but the strip itself stays empty, because `scripts/check_clip_chrome.py`
// fails a published clip whose terminal title bar is not FLAT. That gate is deliberately not a text
// recogniser: "the strip is not flat" is the property that cannot be argued with. Drawing even a safe
// label there would mean masking every clip by hand before publishing, and that hand mask is exactly
// what shipped ten leaking frames when it stopped 0.44s before its segment ended (#815). Rendering
// nothing makes a clip born flat, so a re-record needs no manual patching to be publishable.
function chromeTitle(cast, args = {}) {
  const opted = args.showCommand === true || args["show-command"] === true;
  return opted ? windowLabel(castInvocation(cast), args) : "";
}

export function terminalPage({ cast, timeline, fontSize, endHoldMs, introMs, ask, args = {}, xterm = null }) {
  // The label is computed HERE, from the cast, so a caller cannot pass the raw command by mistake
  // or by a revert. That bypass is exactly how this leak shipped, one layer up.
  const title = chromeTitle(cast, args);
  const xtermJs = xterm ? xterm.js : fs.readFileSync(resolveOptionalPath("@xterm/xterm", "lib", "xterm.js"), "utf8");
  const xtermCss = xterm ? xterm.css : fs.readFileSync(resolveOptionalPath("@xterm/xterm", "css", "xterm.css"), "utf8");
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
  .chrome { display: flex; align-items: center; gap: 8px; padding-bottom: 20px; }
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
  document.getElementById("title").textContent = ${scriptJson(title)};
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
export function askFromCast(cast, args, preferredMark = "ask") {
  if (args.ask) return String(args.ask);
  const marks = Array.isArray(cast.marks) ? cast.marks : [];
  // ONLY the mark that is meant to state the ask. Falling back to "any mark with text" published
  // whatever the next step happened to carry - a `paste` step's payload is a whole review bundle,
  // and it would be painted across the card in the largest type in the clip.
  const chosen = marks.find((m) => m.label === preferredMark && m.text);
  if (chosen) return String(chosen.text).trim();
  const fromCommand = promptFromCommand(castInvocation(cast));
  if (fromCommand) return fromCommand;
  // NOT the raw command. With no prompt to state there is nothing worth reading here, and the
  // invocation would be painted across the card in the largest type in the clip - a louder leak
  // than the window chrome that prompted this. `--show-command` reaches this fallback too, so
  // opting in publishes the command on the CARD as well as in the chrome (DEMO-SAFE-43).
  return windowLabel(castInvocation(cast), args);
}

// `--show-command` reads as a chrome control, and since the chrome stopped drawing anything the
// operator reaching for it is picturing a title bar. Its loudest effect is the CARD: with nothing
// else to state, the card falls back to the same label, so the flag paints the whole invocation in
// the largest type in the clip. Say so at render time - documentation only reaches whoever read it.
// Null when the flag changes nothing on the card, so the warning always names a real consequence.
export function showCommandCardNotice(cast, args = {}) {
  if (!(args.showCommand === true || args["show-command"] === true)) return null;
  // Ask the real resolver both ways rather than restating its precedence here, which would drift.
  const safe = askFromCast(cast, { ...args, showCommand: false, "show-command": false });
  const published = askFromCast(cast, args);
  if (published === safe) return null;
  return "--show-command fills the TITLE CARD too, not just the window chrome: with no --ask, no "
    + `"ask" mark and no -p prompt the card will read "${published}". `
    + 'Pass --ask "<the ask>" to keep the command off the card.';
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
export function stagePage({ cast, segments, fontSize, introMs, endHoldMs, ask, reportUrl, args = {}, xterm = null }) {
  const title = chromeTitle(cast, args);
  const xtermJs = xterm ? xterm.js : fs.readFileSync(resolveOptionalPath("@xterm/xterm", "lib", "xterm.js"), "utf8");
  const xtermCss = xterm ? xterm.css : fs.readFileSync(resolveOptionalPath("@xterm/xterm", "css", "xterm.css"), "utf8");
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
  .chrome { display: flex; align-items: center; gap: 8px; padding-bottom: 20px; }
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
     unrelated clips spliced together. The shadow is kept TIGHT on purpose: a blur radius is a
     Gaussian parameter, so the renderer paints out to roughly 1.5 radii beyond the box, and at
     40px that reached over the window chrome the flatness gate inspects. */
  #phase { position: fixed; left: 50%; top: 80px; transform: translateX(-50%); z-index: 7;
    padding: 14px 30px; border-radius: 999px; background: #0d1117; color: #e6edf3;
    border: 2px solid rgba(240,246,252,0.34); font-size: 24px; font-weight: 700; letter-spacing: .3px;
    box-shadow: 0 14px 20px rgba(0,0,0,.5); opacity: 0; transition: opacity 300ms ease;
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
  document.getElementById("title").textContent = ${scriptJson(title)};
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
  const { file: castFile, cast, capturedHere } = readCast(args);
  const rules = rulesForThisMachine();
  const found = gateFindings(cast, args, rules);
  const findingsTotal = findingCount(found);
  if (findingsTotal && !args["allow-findings"]) {
    throw new Error(dirtyGateMessage(found, castFile));
  }
  warnForeignCast(capturedHere);

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
  const cardNotice = showCommandCardNotice(cast, args);
  if (cardNotice) console.warn(`  WARNING: ${cardNotice}`);
  const unsafe = findingsTotal > 0;
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
      args,
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
  // The same warning `render` prints: the UNSAFE filename says a clip is not publish-safe, but only
  // to whoever reads the path. Say it in words too, where the operator is already looking.
  if (unsafe) {
    console.error(`\nWARNING: rendered despite ${findingsTotal} finding(s) because --allow-findings was passed.`);
    console.error("This clip is NOT publish-safe. Run 'scan' and look at every finding before it goes anywhere.");
  }
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
  const { file: castFile, cast: fullCast, capturedHere } = readCast(args);
  const rules = rulesForThisMachine();
  // Scanned BEFORE any trim, deliberately. The gate exists to stop a secret reaching a published
  // clip, and scanning only the kept span would let a trim decide what the gate gets to see.
  const found = gateFindings(fullCast, args, rules);
  const findingsTotal = findingCount(found);
  if (findingsTotal && !args["allow-findings"]) {
    throw new Error(dirtyGateMessage(found, castFile));
  }
  // A cast this tool did not capture was never scrubbed at capture time, and the machine-specific
  // rules here cannot know another operator's home path or account name - so a clean scan says much
  // less than it appears to.
  warnForeignCast(capturedHere);

  const cast = trimForRender(fullCast, args);

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
  const cardNotice = showCommandCardNotice(cast, args);
  if (cardNotice) console.warn(`  WARNING: ${cardNotice}`);
  const width = Math.round(numberOpt(args, "width", Math.ceil(cols * fontSize * 0.605) + 56));
  const height = Math.round(numberOpt(args, "height", Math.ceil(rows * fontSize * 1.32) + 84));
  // A clip rendered over the gate's objection must be impossible to mistake for a clean one later,
  // when nobody remembers which flag was passed - including when the caller named the file itself.
  const unsafe = findingsTotal > 0;
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
    fs.writeFileSync(pageFile, terminalPage({ cast, timeline, fontSize, endHoldMs, introMs, ask, args }));
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
    console.error(`\nWARNING: rendered despite ${findingsTotal} finding(s) because --allow-findings was passed.`);
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
                               [--show-command]
  node record_demo.mjs capture [--out <f.cast.json>] [--cols 120] [--rows 30] [--script <f.json>] [--max-mb 48] -- <cmd...>
                               [--exit-grace 120] [--progress 60]
  node record_demo.mjs render  --cast <file.cast.json> [--seconds 45] [--idle 900] [--out <file.webm>]
                               [--until "<marker>"] [--until-after <mark>] [--until-gap <seconds>]
                               [--show-command]
  node record_demo.mjs scan    --cast <file.cast.json> [--ask "<the ask you will render with>"]
  node record_demo.mjs frames  --clip <file.webm> [--count 12]

The window chrome draws no title, so a clip is born flat; --show-command publishes the whole launch
command - in the chrome AND on the title card, which falls back to that label when a cast has no ask.

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
