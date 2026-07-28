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
//   node record_demo.mjs capture [--out <file.cast.json>] [--cols 120] [--rows 30] -- <command...>
//   node record_demo.mjs render  --cast <file.cast.json> [--seconds 45] [--out <file.webm>]
//   node record_demo.mjs scan    --cast <file.cast.json>

import { pathToFileURL, fileURLToPath } from "url";
import { createRequire } from "module";
import path from "path";
import fs from "fs";
import os from "os";
import http from "http";

import { planBeats, fitTimeline, compressTimeline, MIN_BEAT_MS } from "./timeline.mjs";
import { REPORT_BEATS } from "./report-beats.mjs";
import { DEFAULT_RULES, homeRules, scanText, scrubEvents, scrubText } from "./redact.mjs";

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
  "width", "height", "count", "font", "frames-dir",
]);
const KNOWN_FLAGS = new Set([...STRING_KEYS, "list", "allow-findings"]);
// Which options each subject actually reads. Validating against the union instead means
// `scan --out x` or `capture --seconds 10` is accepted and then silently ignored - the caller is
// told nothing, and gets a clip that is not what they asked for.
const SUBJECT_FLAGS = {
  report: ["example", "out", "seconds", "width", "height", "list"],
  capture: ["out", "cols", "rows"],
  render: ["cast", "out", "seconds", "idle", "hold", "width", "height", "font", "allow-findings"],
  scan: ["cast"],
  frames: ["clip", "out", "count", "frames-dir"],
};

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
    const file = path.join(root, rel.replace(/^\/+/, ""));
    // `startsWith(root)` alone lets a SIBLING through: with a root of /x/examples, the path
    // /x/examples-private/secret resolves outside the root yet still starts with it. Compare the
    // relative path instead, which is empty or non-escaping only for a genuine descendant.
    const within = path.relative(path.resolve(root), path.resolve(file));
    if (within.startsWith("..") || path.isAbsolute(within)) { res.writeHead(403).end(); return; }
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

function makeContext(page, budgetMs, warnings) {
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
    async scrollTo(y) {
      await page.evaluate((to) => window.scrollTo(0, to), y).catch(() => {});
    },
    // A jump cut is unreadable at speed; a short eased glide reads as a real person scrolling.
    async glideTo(y, durationMs) {
      await page.evaluate(async ([to, ms]) => {
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
      return page.evaluate(([sels, floor]) => {
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
    async waitVisible(target, timeout = 2000) {
      const locator = typeof target === "string" ? page.locator(target) : target;
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
      const box = await page.evaluate(([sel, nth]) => {
        const els = [...document.querySelectorAll(sel)];
        const candidates = els.filter((e) => (e.textContent || "").trim().length > 80);
        const el = (candidates.length ? candidates : els)[nth % Math.max(1, candidates.length || els.length)];
        if (!el) return null;
        el.scrollIntoView({ block: "center" });
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
      }, [selector, index]).catch(() => null);
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
  try {
    server = await startStaticServer(path.dirname(example));
    ensureDir(videoDir);
    browser = await chromium.launch();
    context = await browser.newContext({
      viewport: { width, height },
      deviceScaleFactor: 1,
      recordVideo: { dir: videoDir, size: { width, height } },
    });
    // Playwright records PER PAGE, starting when the page is created. Warming the document in a
    // throwaway page first fills the HTTP cache and pays the one-off font/diagram cost off camera,
    // so the filmed page opens fast and the clip is mostly montage rather than loading.
    const url = `${server.origin}/${encodeURIComponent(path.basename(example))}`;
    const warmup = await context.newPage();
    await warmup.goto(url, { waitUntil: "load" }).catch(() => {});
    await warmup.waitForFunction(() => window.__commentableHtmlReady === true, null, { timeout: 15000 })
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
    await page.goto(url, { waitUntil: "load" });
    await page.waitForFunction(() => window.__commentableHtmlReady === true, null, { timeout: 15000 })
      .catch(() => warnings.push("the runtime never signalled ready"));
    // Give diagrams a chance to finish rendering, so the tour beat is not filming a loading state.
    await page.waitForFunction(() => {
      const figs = document.querySelectorAll(".mermaid, figure.cmh-mermaid, .cmh-diagram");
      return !figs.length || [...figs].every((f) => f.querySelector("svg"));
    }, null, { timeout: 9000 }).catch(() => {});
    await sleep(250);

    const preludeMs = Date.now() - recordingStarted;
    // Closing the context and finalizing the file also lands in the clip, so hold a little back.
    const tailMs = 350;
    const beatBudget = totalMs - preludeMs - tailMs;
    const floor = MIN_BEAT_MS * REPORT_BEATS.length;
    if (beatBudget < floor) {
      warnings.push(`the ${(preludeMs / 1000).toFixed(1)}s page load leaves too little of a ${seconds}s clip; the montage will overrun`);
    }
    const paced = planBeats(REPORT_BEATS, Math.max(floor, beatBudget));

    for (const beat of REPORT_BEATS) {
      const budgetMs = paced.find((p) => p.id === beat.id).budgetMs;
      const before = warnings.length;
      const ctx = makeContext(page, budgetMs, warnings);
      const started = Date.now();
      try {
        await beat.run(page, ctx);
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
  const onSignal = () => { restore(); process.exit(130); };
  process.once("SIGINT", onSignal);
  process.once("SIGTERM", onSignal);

  let exitCode = 0;
  try {
    if (process.stdin.isTTY) process.stdin.setRawMode(true);
    process.stdin.resume();
    process.stdin.on("data", onInput);
    process.stdout.on("resize", onResize);
    child.onData((data) => {
      process.stdout.write(data);
      events.push({ t: Date.now() - started, data });
    });
    exitCode = await new Promise((resolve) => child.onExit(({ exitCode: code }) => resolve(code)));
    // onExit can fire while the pty still has buffered output in flight, and the tail of a session
    // (the final result, the closing prompt) is exactly what a demo wants to show. Let it land.
    await sleep(250);
  } finally {
    restore();
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

function terminalPage({ cast, timeline, fontSize }) {
  const xtermJs = fs.readFileSync(resolveOptionalPath("@xterm/xterm", "lib", "xterm.js"), "utf8");
  const xtermCss = fs.readFileSync(resolveOptionalPath("@xterm/xterm", "css", "xterm.css"), "utf8");
  const payload = scriptJson({
    cols: cast.cols || 120,
    rows: cast.rows || 30,
    fontSize,
    events: timeline.events.map((e) => ({ t: e.t, d: e.data, f: e.fastForward, s: e.skippedMs })),
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
    let clock = 0;
    // term.write is ASYNCHRONOUS: signalling done on a fixed delay can cut the recording before the
    // last chunk is parsed and painted, which is exactly the frame the clip exists to show.
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
      await sleep(Math.max(0, event.t - clock));
      clock = event.t;
      if (event.f) setTimeout(() => badge.classList.remove("on"), 450);
      await write(event.d);
    }
    await frame();
    await frame();
    await sleep(700);
    window.__demoDone = true;
  })();
</script></body></html>`;
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
    })
    : compressTimeline(cast.events, { idleMs: numberOpt(args, "idle", undefined), holdMs: numberOpt(args, "hold", undefined) });

  // Size the viewport from the terminal grid so no column is clipped and no space is wasted. The
  // font is deliberately large, because the VIEWPORT is what sets the video's resolution: Playwright
  // records the page at its CSS size and will not upscale it, so asking for a bigger video than the
  // viewport just pads it with grey. A 2x device scale still sharpens the glyphs within that size.
  const fontSize = Math.round(numberOpt(args, "font", 24));
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
    fs.writeFileSync(pageFile, terminalPage({ cast, timeline, fontSize }));
    const videoDir = path.join(stageDir, "video");
    ensureDir(videoDir);
    browser = await chromium.launch();
    context = await browser.newContext({
      viewport: { width, height },
      deviceScaleFactor: 2,
      recordVideo: { dir: videoDir, size: { width, height } },
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
  node record_demo.mjs capture [--out <file.cast.json>] [--cols 120] [--rows 30] -- <command...>
  node record_demo.mjs render  --cast <file.cast.json> [--seconds 45] [--idle 900] [--out <file.webm>]
  node record_demo.mjs scan    --cast <file.cast.json>
  node record_demo.mjs frames  --clip <file.webm> [--count 12]

Everything is written under tmp/demo-video (gitignored). Nothing is committed.`;

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const subject = args._[0];
  if (subject) checkSubjectFlags(args, subject);
  switch (subject) {
    case "report": return recordReport(args);
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
