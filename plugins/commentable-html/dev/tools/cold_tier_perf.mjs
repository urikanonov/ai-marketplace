#!/usr/bin/env node
// cold_tier_perf.mjs - measure first paint and time-to-interactive for the COLD TIER (CMH-COLD-09).
//
// The cold tier (CMH-COLD-01..CMH-COLD-08) trades one cost against another: a compressed document
// parses far LESS DOM up front, which should make first paint arrive sooner, but it pays a
// SYNCHRONOUS inflate before the comment layer boots, which pushes interactivity later. #1263 left
// two acceptance criteria open precisely because nobody had measured both halves on the same
// documents. This harness is that measurement, and it is repeatable rather than a one-off run.
//
// What it measures, and how the numbers are defined:
//
//   FMP (first meaningful paint) - the browser's own `first-contentful-paint` paint-timing entry,
//     falling back to `first-paint`. WHICH of the two produced each sample is recorded, because a
//     median that silently mixes the two would be averaging different metrics.
//   TTI (time to fully interactive) - the instant the layer sets `window.__commentableHtmlReady`,
//     its documented public ready hook (95-startup.js). That is the moment every control, anchor
//     and comment thread is live. It is captured EXACTLY, by an init script that installs an
//     accessor on that property and stamps `performance.now()` on assignment - not by polling,
//     which would quantise the number to the poll interval.
//   BLANK (`deferredPaints`) - the loads whose first paint landed at or after `domInteractive`,
//     i.e. that showed the reader NOTHING until the parser had finished the document. On a
//     compressed document the paint result is BIMODAL, so this rate - not the median - is the
//     statistic that describes it.
//
//   COLD - a FRESHLY LAUNCHED browser loading the file for the first time. WARM - a reload of the
//     same document in the same page immediately afterwards.
//
// Two methodology rules the numbers depend on, both learned the hard way:
//
//   ORDER IS COUNTERBALANCED. Measuring OFF then ON every iteration hands ON a systematic
//   second-run advantage (warmed OS file cache, warmed machine), which is exactly the direction
//   that would flatter the tier. Iterations alternate ON-first and OFF-first, and the reported
//   delta is the median of PER-ITERATION PAIRED differences, so a drift shared by both variants
//   cancels instead of accumulating.
//
//   PAINT IS OBSERVED, NOT POLLED AT THE END. With the tier ON the `load` event can fire BEFORE
//   the first paint, so reading `performance.getEntriesByType("paint")` at `load` found NOTHING
//   and scored exactly the worst documents as "not measured". A `PerformanceObserver` records the
//   entry whenever it lands and `measureLoad` waits for it.
//
// Usage (run from plugins/commentable-html/dev):
//   node tools/cold_tier_perf.mjs [--iterations N] [--corpus a,b] [--out report.json]
//                                 [--min-rows N] [--keep-rows N] [--tti-budget-ms N] [--quiet]
//
// Exit code is 0 when every bound holds, 1 when a bound is missed or a document could not be
// measured (the numbers are still written and printed - a miss is a RESULT, and CMH-COLD-09 says
// what to do with it), and 2 when the harness itself could not run.

import { chromium } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const DEV = path.resolve(HERE, "..");
export const REPO_ROOT = path.resolve(DEV, "..", "..", "..");
export const SHAREABLE = path.join(DEV, "skill", "dist", "SHAREABLE.html");
export const COLD_TIER_PY = path.join(DEV, "skill", "tools", "authoring", "cold_tier.py");

// The bound #1263 set for interactivity: the tier may cost up to this much extra time to ready on
// any document, and nothing at all on the largest one.
export const DEFAULT_TTI_BUDGET_MS = 150;

// The corpus. `xl-tree` is the shape the #1250 survey measured as the largest real document (about
// 3.2 MB of body, a deep generated tree flattened into one long table), which is the document both
// halves of the trade are sharpest on; the smaller two exist so a regression that only shows up
// below the threshold cannot hide. Sizes are deterministic, so a rerun measures the same bytes.
export const CORPUS = [
  { name: "sm-report", tables: 1, rows: 200, cols: 4, cellWords: 3, paragraphs: 6 },
  { name: "md-report", tables: 4, rows: 900, cols: 5, cellWords: 4, paragraphs: 20 },
  { name: "xl-tree", tables: 1, rows: 11500, cols: 6, cellWords: 5, paragraphs: 40, largest: true },
];

const WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
  "india", "juliett", "kilo", "lima", "mike", "november", "oscar", "papa", "quebec", "romeo",
  "sierra", "tango", "uniform", "victor", "whiskey", "xray", "yankee", "zulu", "anvil", "beacon",
  "cinder", "dovetail", "ember", "fathom", "gantry", "harrow", "ingot", "jetty", "kernel",
  "lantern", "mortar", "nozzle", "obelisk", "pylon", "quarry", "ratchet", "sextant", "trestle"];

// A deterministic 32-bit mixer. Filler text is index-driven so two runs build byte-identical
// documents, but it must not be a short repeating cycle: a corpus of 16 rotating words gzips far
// better than a real report, which would flatter every byte ratio the conclusions rest on.
function mix(n) {
  let x = (n + 0x9e3779b9) >>> 0;
  x = Math.imul(x ^ (x >>> 16), 0x85ebca6b) >>> 0;
  x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0;
  return (x ^ (x >>> 16)) >>> 0;
}

function words(seed, count) {
  const out = [];
  for (let i = 0; i < count; i += 1) {
    const r = mix(seed * 131 + i);
    out.push(WORDS[r % WORDS.length] + (r % 7 === 0 ? "-" + (r % 9973) : ""));
  }
  return out.join(" ");
}

/** Build a document body for a corpus entry.
 *
 * The tables are TREE-SHAPED the way the surveyed documents are - each row carries a depth class
 * and an indent span - but they deliberately contain nothing `cold_tier.py` refuses (no heading,
 * script, nested table, diagram class or `on*` handler), so the tier engages on the tail rows and
 * the ON/OFF pair differs by the compression alone rather than by what was eligible.
 */
export function buildBody(spec) {
  const parts = [`<h1>${spec.name} performance corpus</h1>`];
  for (let p = 0; p < spec.paragraphs; p += 1) {
    parts.push(`<p>${words(p, 40)}.</p>`);
  }
  for (let t = 0; t < spec.tables; t += 1) {
    parts.push(`<h2>Table ${t + 1}</h2>`);
    parts.push("<table>");
    parts.push(`  <caption>Generated tree ${t + 1}</caption>`);
    const head = [];
    for (let c = 0; c < spec.cols; c += 1) head.push(`<th>col ${c + 1}</th>`);
    parts.push(`  <thead><tr>${head.join("")}</tr></thead>`);
    parts.push("  <tbody>");
    for (let r = 0; r < spec.rows; r += 1) {
      const depth = mix(t * 7919 + r) % 4;
      const cells = [`<td><span class="depth-${depth}">${"- ".repeat(depth)}node ${t}.${r}</span></td>`];
      for (let c = 1; c < spec.cols; c += 1) {
        cells.push(`<td>${words(r * 31 + c * 3 + t * 977, spec.cellWords)}</td>`);
      }
      parts.push(`    <tr>${cells.join("")}</tr>`);
    }
    parts.push("  </tbody>");
    parts.push("</table>");
  }
  return parts.join("\n");
}

const CONTENT_RE =
  /(<!-- BEGIN: commentable-html - CONTENT[^>]*-->)[\s\S]*?(<!-- END: commentable-html - CONTENT -->)/;

/** Write a real layer document (dist/SHAREABLE.html with `body` spliced into its CONTENT region). */
export function stageDocument(body, outPath, { source = SHAREABLE } = {}) {
  if (!fs.existsSync(source)) {
    throw new Error(`no built stage at ${source} - run tools/build.py first`);
  }
  let html = fs.readFileSync(source, "utf8");
  if (!CONTENT_RE.test(html)) throw new Error(`no CONTENT region in ${source}`);
  html = html.replace(CONTENT_RE, (_m, a, b) => `${a}\n${body}\n${b}`);
  html = html.replace('data-comment-key="commentable-html-demo"', 'data-comment-key="cmh-perf-doc"');
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, html);
  return outPath;
}

// The interpreter name differs by platform (Linux/macOS expose `python3`, Windows dev boxes
// usually `python`), so probe rather than guess - a static name ENOENTs on a runner where the
// rest of the suite is fine. Same resolution the test helpers use.
export const PYTHON = (() => {
  if (process.env.CMH_PYTHON) return process.env.CMH_PYTHON;
  for (const cmd of ["python3", "python"]) {
    try { if (spawnSync(cmd, ["--version"]).status === 0) return cmd; } catch (_e) { /* try next */ }
  }
  return "python";
})();

/** Compress a staged document in place with the REAL shipped tool, and report what it took.
 *
 * Running the shipped `cold_tier.py` rather than a fixture is the point: the measurement has to be
 * of the tier that ships, including its eligibility rules, or the numbers say nothing.
 */
export function compressDocument(file, { minRows, keepRows } = {}) {
  const args = [COLD_TIER_PY, file];
  if (minRows != null) args.push("--min-rows", String(minRows));
  if (keepRows != null) args.push("--keep-rows", String(keepRows));
  const before = fs.statSync(file).size;
  const run = spawnSync(PYTHON, args, { encoding: "utf8" });
  if (run.error) throw new Error(`cold_tier.py could not be launched: ${run.error.message}`);
  if (run.status !== 0) {
    throw new Error(`cold_tier.py failed (${run.status}): ${(run.stderr || run.stdout || "").trim()}`);
  }
  const after = fs.statSync(file).size;
  const html = fs.readFileSync(file, "utf8");
  return {
    compressed: html.includes('id="cmhColdTier"'),
    bytesBefore: before,
    bytesAfter: after,
    stdout: (run.stdout || "").trim(),
  };
}

/** Install the exact probes on a page, before any document script runs.
 *
 * The layer sets `window.__commentableHtmlReady = true` as its last startup statement. Defining an
 * accessor for that property ahead of time turns the assignment itself into the timestamp, so TTI
 * is the layer's own ready instant rather than "the next time we happened to look".
 */
export async function instrumentPage(page) {
  await page.addInitScript(() => {
    let value;
    const probe = { ready: null, firstPaint: null, firstContentfulPaint: null };
    Object.defineProperty(window, "__cmhPerfProbe", { value: probe, configurable: true });
    Object.defineProperty(window, "__commentableHtmlReady", {
      configurable: true,
      get() { return value; },
      set(next) {
        value = next;
        if (next === true && probe.ready === null) probe.ready = performance.now();
      },
    });
    const record = (entry) => {
      if (entry.name === "first-paint" && probe.firstPaint === null) probe.firstPaint = entry.startTime;
      if (entry.name === "first-contentful-paint" && probe.firstContentfulPaint === null) {
        probe.firstContentfulPaint = entry.startTime;
      }
    };
    new PerformanceObserver((list) => list.getEntries().forEach(record)).observe({ type: "paint", buffered: true });
    // The main-thread blocking window. Hydration is parser-blocking by construction, so the
    // longest task IS the inflate-plus-insert cost plus whatever script ran with it - which is
    // what bounds any claim about how much a faster decoder could buy.
    probe.longTaskTotal = 0;
    probe.longTaskMax = 0;
    try {
      new PerformanceObserver((list) => {
        for (const e of list.getEntries()) {
          probe.longTaskTotal += e.duration;
          if (e.duration > probe.longTaskMax) probe.longTaskMax = e.duration;
        }
      }).observe({ type: "longtask", buffered: true });
    } catch (_e) { probe.longTaskTotal = null; probe.longTaskMax = null; }
  });
}

/** Read the timings out of a loaded page. Call after the probes have fired.
 *
 * Sourced from the PROBE, never from `performance.getEntriesByType("paint")` at read time: on a
 * compressed document `load` fires before the paint, so a read-at-the-end would report nothing.
 * `fmpSource` records which entry produced the number, so a run that silently switched between
 * `first-contentful-paint` and `first-paint` is visible instead of being averaged together.
 */
export async function readTimings(page) {
  return page.evaluate(() => {
    const probe = window.__cmhPerfProbe || {};
    const nav = performance.getEntriesByType("navigation")[0];
    const fcp = probe.firstContentfulPaint != null ? probe.firstContentfulPaint : null;
    const fp = probe.firstPaint != null ? probe.firstPaint : null;
    return {
      fmp: fcp != null ? fcp : fp,
      fmpSource: fcp != null ? "first-contentful-paint" : (fp != null ? "first-paint" : null),
      firstContentfulPaint: fcp,
      firstPaint: fp,
      tti: probe.ready != null ? probe.ready : null,
      longTaskMax: probe.longTaskMax != null ? probe.longTaskMax : null,
      longTaskTotal: probe.longTaskTotal != null ? probe.longTaskTotal : null,
      domInteractive: nav ? nav.domInteractive : null,
      domContentLoaded: nav ? nav.domContentLoadedEventEnd : null,
      rows: document.querySelectorAll("tbody tr").length,
    };
  });
}

const EMPTY_SAMPLE = {
  fmp: null, fmpSource: null, firstContentfulPaint: null, firstPaint: null,
  tti: null, longTaskMax: null, longTaskTotal: null,
  domInteractive: null, domContentLoaded: null, rows: null,
};

/** Load `url` in `page` (a fresh navigation or a reload) and return its timings.
 *
 * Waits for BOTH the layer's ready hook and a first paint: either one can land after the other (a
 * compressed document is regularly ready before it has painted), so waiting for only one of them
 * reports the other as missing. A load that never satisfies both yields an EMPTY sample rather
 * than throwing, so one flaky load costs a data point instead of discarding a multi-minute run -
 * and `evaluateDocument` then reports it as an incomplete measurement (a FAILURE, never a pass).
 * The wait polls on a timer, not on `requestAnimationFrame`: asking a not-yet-painted page for
 * animation frames can itself provoke the very frame being timed.
 */
export async function measureLoad(page, url, { reload = false, timeout = 60000 } = {}) {
  try {
    if (reload) await page.reload({ waitUntil: "load", timeout });
    else await page.goto(url, { waitUntil: "load", timeout });
    await page.waitForFunction(() => {
      const p = window.__cmhPerfProbe;
      return !!p && p.ready !== null && (p.firstContentfulPaint !== null || p.firstPaint !== null);
    }, null, { timeout, polling: 25 });
    return await readTimings(page);
  } catch (err) {
    // Only a TIMEOUT is data (a load that was too slow to report both numbers). Anything else - a
    // crashed renderer, a missing file, a bug in this harness - is a harness failure, and turning
    // it into an empty sample would hide it behind a "measurement was incomplete" verdict.
    const name = (err && (err.name || "")) + " " + (err && err.message ? err.message : "");
    if (!/Timeout|timeout/.test(name)) throw err;
    process.stderr.write(`cold_tier_perf: load timed out, recording an empty sample (${url})\n`);
    return { ...EMPTY_SAMPLE };
  }
}

/** One iteration: a brand-new browser (COLD), then a reload of the same page (WARM). */
export async function measureIteration(url, { timeout = 60000 } = {}) {
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    await instrumentPage(page);
    const cold = await measureLoad(page, url, { timeout });
    const warm = await measureLoad(page, url, { reload: true, timeout });
    await context.close();
    return { cold, warm };
  } finally {
    await browser.close();
  }
}

export function median(values) {
  const nums = values.filter((v) => typeof v === "number" && Number.isFinite(v)).slice().sort((a, b) => a - b);
  if (!nums.length) return null;
  const mid = nums.length >> 1;
  return nums.length % 2 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2;
}

/** The `q`-quantile (0..1) by nearest-rank, over the finite values only. */
export function quantile(values, q) {
  const nums = values.filter((v) => typeof v === "number" && Number.isFinite(v)).slice().sort((a, b) => a - b);
  if (!nums.length) return null;
  const rank = Math.min(nums.length - 1, Math.max(0, Math.ceil(q * nums.length) - 1));
  return nums[rank];
}

/** Per-iteration ON-minus-OFF differences, for the iterations where BOTH sides measured.
 *
 * Pairing is what makes a drift shared by the two variants (a busy machine, a thermal ramp)
 * cancel instead of landing on whichever variant ran second.
 */
export function pairedDeltas(offSamples, onSamples, key, { matchKey = null } = {}) {
  const out = [];
  const n = Math.min(offSamples.length, onSamples.length);
  for (let i = 0; i < n; i += 1) {
    const offSample = offSamples[i];
    const onSample = onSamples[i];
    const a = offSample ? offSample[key] : null;
    const b = onSample ? onSample[key] : null;
    // A pair whose two sides came from DIFFERENT metrics is not a difference, it is a category
    // error: `first-paint` can fire on a frame with no content in it, so subtracting it from a
    // `first-contentful-paint` would quietly manufacture a delta.
    if (matchKey && (!offSample || !onSample || offSample[matchKey] !== onSample[matchKey])) continue;
    if (Number.isFinite(a) && Number.isFinite(b)) out.push(b - a);
  }
  return out;
}

/** Whether a load painted nothing until the parser had finished the document. */
export function isBlank(sample) {
  return !!sample && Number.isFinite(sample.fmp) && Number.isFinite(sample.domInteractive)
    && sample.fmp >= sample.domInteractive;
}

/** McNemar-style paired counts: iterations where exactly ONE variant went blank.
 *
 * Comparing two independent RATES ignores that the pair shares a machine and a moment; the
 * discordant pairs are what carry the signal, and they are what the sign test is run over.
 */
export function pairedBlankness(offSamples, onSamples) {
  let onlyOn = 0;
  let onlyOff = 0;
  const n = Math.min(offSamples.length, onSamples.length);
  for (let i = 0; i < n; i += 1) {
    const a = isBlank(offSamples[i]);
    const b = isBlank(onSamples[i]);
    if (b && !a) onlyOn += 1;
    if (a && !b) onlyOff += 1;
  }
  return { onlyOn, onlyOff, pairs: n };
}

/** Which variant loads FIRST in iteration `i`.
 *
 * Exported so the counterbalancing is a testable decision rather than an inline expression a
 * revert could quietly delete: a fixed OFF-then-ON order hands ON a warmed machine, which is the
 * direction that would flatter the tier.
 */
export function onLoadsFirst(i) {
  return i % 2 === 1;
}

/** Median/quantile summary over a set of per-iteration samples.
 *
 * `deferredPaints` counts the loads whose first paint landed at or after `domInteractive` - that
 * is, loads that showed the reader NOTHING until the parser had finished the document. A median
 * hides that shape, and on a compressed document the shape IS the finding: paint is a race, not a
 * uniformly slower number. `fmpN` / `ttiN` are the counts that actually fed those statistics, so
 * a run with missing samples cannot present a median over 3 loads as if it were over 7.
 */
export function summarize(samples) {
  const fmp = samples.map((s) => s.fmp);
  const tti = samples.map((s) => s.tti);
  const finite = (v) => v.filter((n) => Number.isFinite(n));
  const spread = (v) => (finite(v).length ? Math.max(...finite(v)) - Math.min(...finite(v)) : null);
  const deferred = samples.filter((s) => isBlank(s)).length;
  const margins = samples
    .filter((s) => Number.isFinite(s.fmp) && Number.isFinite(s.domInteractive))
    .map((s) => s.fmp - s.domInteractive);
  const rowCounts = finite(samples.map((s) => s.rows));
  const sources = Array.from(new Set(samples.map((s) => s.fmpSource).filter(Boolean))).sort();
  return {
    n: samples.length,
    fmpN: finite(fmp).length,
    ttiN: finite(tti).length,
    fmp: median(fmp),
    fmpP75: quantile(fmp, 0.75),
    tti: median(tti),
    longTaskMax: median(samples.map((s) => s.longTaskMax)),
    longTaskTotal: median(samples.map((s) => s.longTaskTotal)),
    domContentLoaded: median(samples.map((s) => s.domContentLoaded)),
    domInteractive: median(samples.map((s) => s.domInteractive)),
    paintMargin: median(margins),
    fmpSpread: spread(fmp),
    ttiSpread: spread(tti),
    deferredPaints: deferred,
    fmpSources: sources,
    rowsMin: rowCounts.length ? Math.min(...rowCounts) : null,
    rowsMax: rowCounts.length ? Math.max(...rowCounts) : null,
  };
}

const round = (v) => (typeof v === "number" && Number.isFinite(v) ? Math.round(v * 10) / 10 : null);

/** Exact one-sided binomial tail: P(X >= hits) for X ~ Binomial(n, 1/2).
 *
 * The paint distribution is bimodal and noisy, so "is this delta real?" cannot be answered by
 * comparing a statistic to zero - a NULL control (pairing a document's own OFF samples against a
 * rotation of themselves) produces p75 deltas of +12..+132 ms, so a zero-tolerance rule fails a
 * document compared with ITSELF and the gate can never return PASS. A paired sign test needs no
 * distributional assumption, which is what a bimodal race calls for.
 */
export function signTestP(hits, n) {
  if (!n) return 1;
  let c = 1;
  let total = 0;
  for (let k = 0; k <= n; k += 1) {
    if (k >= hits) total += c;
    c = (c * (n - k)) / (k + 1);
  }
  return total / Math.pow(2, n);
}

export const ALPHA = 0.05;

/** Is the ON side significantly worse across paired observations? */
export function regressed(deltas, { alpha = ALPHA } = {}) {
  const nonZero = deltas.filter((d) => d !== 0);
  const worse = nonZero.filter((d) => d > 0).length;
  const p = signTestP(worse, nonZero.length);
  return { worse, pairs: nonZero.length, p, significant: nonZero.length > 0 && p <= alpha };
}

/** Judge one document's ON/OFF result against #1263's two bounds.
 *
 * Bound 1 (paint): the tier must not make paint worse, warm AND cold. Judged on the PAIRED sign
 *   test over per-iteration deltas AND on the blank-until-parsed rate (a paired, McNemar-style
 *   sign test over the loads where exactly one variant went blank), because the row's own finding
 *   is that the compressed paint distribution is bimodal: a median over it is a coin flip, and a
 *   zero-tolerance threshold is below the measurement's noise floor. A delta that is positive but
 *   NOT significant is reported as INCONCLUSIVE rather than counted as a regression - a gate that
 *   fails a document compared with itself is not a gate.
 * Bound 2 (interactivity): the median paired TTI delta must be within the budget, and the budget
 *   is 0 for the largest document - it must not be worse than today at all.
 *
 * A document that was not really measured FAILS, never passes: a tier that declined to compress
 * (so both files are identical), a hydration that did not restore every row (so the two documents
 * are not comparable), or a load that never reported both numbers. Each of those would otherwise
 * produce a flattering delta from a comparison that never happened - and a declined document
 * short-circuits, so the artifact does not also carry paint numbers derived from noise between two
 * identical files.
 */
export function evaluateDocument(row, { ttiBudgetMs = DEFAULT_TTI_BUDGET_MS, alpha = ALPHA } = {}) {
  const failures = [];
  const notes = [];
  const stats = {};
  const budget = row.largest ? 0 : ttiBudgetMs;
  if (row.compressed === false) {
    failures.push(`${row.name}: the tier declined to compress this document, so nothing was measured`);
    return { name: row.name, largest: !!row.largest, budget, stats, notes, failures, ok: false };
  }
  for (const state of ["cold", "warm"]) {
    const off = row.off && row.off[state];
    const on = row.on && row.on[state];
    if (!off || !on) {
      failures.push(`${row.name} ${state}: no measurement`);
      continue;
    }
    if (off.fmpN !== off.n || off.ttiN !== off.n || on.fmpN !== on.n || on.ttiN !== on.n) {
      failures.push(`${row.name} ${state}: incomplete measurement - `
        + `${off.n - Math.min(off.fmpN, off.ttiN)} of ${off.n} OFF and `
        + `${on.n - Math.min(on.fmpN, on.ttiN)} of ${on.n} ON loads never reported both FMP and TTI`);
    }
    if (Number.isFinite(off.rowsMax) && Number.isFinite(on.rowsMin)
      && (on.rowsMin !== on.rowsMax || off.rowsMin !== off.rowsMax || on.rowsMin !== off.rowsMin)) {
      failures.push(`${row.name} ${state}: the two documents are not comparable - `
        + `OFF rendered ${off.rowsMin}..${off.rowsMax} rows, ON rendered ${on.rowsMin}..${on.rowsMax}`);
    }
    const samples = row.samples || {};
    const offSamples = (samples.off && samples.off[state]) || [];
    const onSamples = (samples.on && samples.on[state]) || [];
    // Paint numbers are only comparable when both sides came from the SAME paint entry.
    // `readTimings` falls back from `first-contentful-paint` to `first-paint`, and `first-paint`
    // can fire on a frame carrying no content, so a run that mixed the two would be averaging
    // different metrics - and a mixed PAIR would be subtracting them from each other.
    const sources = new Set([...(off.fmpSources || []), ...(on.fmpSources || [])]);
    if (sources.size > 1) {
      failures.push(`${row.name} ${state}: the run mixed paint metrics (${[...sources].join(", ")}) - `
        + "`first-paint` and `first-contentful-paint` are not comparable, so these samples cannot be "
        + "differenced");
    }
    const dFmp = pairedDeltas(offSamples, onSamples, "fmp", { matchKey: "fmpSource" });
    const dTti = pairedDeltas(offSamples, onSamples, "tti");
    if (!dFmp.length || !dTti.length) {
      failures.push(`${row.name} ${state}: no paired iteration measured both variants`);
      continue;
    }
    const blank = pairedBlankness(offSamples, onSamples);
    const paint = regressed(dFmp, { alpha });
    const blankSign = signTestP(blank.onlyOn, blank.onlyOn + blank.onlyOff);
    const s = {
      fmpDelta: round(median(dFmp)),
      fmpDeltaP75: round(quantile(dFmp, 0.75)),
      fmpWorsePairs: `${paint.worse}/${paint.pairs}`,
      fmpSignP: Math.round(paint.p * 10000) / 10000,
      ttiDelta: round(median(dTti)),
      pairs: dFmp.length,
      blankOff: off.deferredPaints,
      blankOn: on.deferredPaints,
      blankOnlyOn: blank.onlyOn,
      blankOnlyOff: blank.onlyOff,
      blankSignP: Math.round(blankSign * 10000) / 10000,
    };
    stats[state] = s;
    const paintWorse = paint.significant && s.fmpDelta > 0;
    const blankWorse = blank.onlyOn + blank.onlyOff > 0 && blankSign <= alpha;
    if (paintWorse) {
      failures.push(`${row.name} ${state}: first meaningful paint regressed - ${paint.worse} of `
        + `${paint.pairs} paired loads were slower (sign test p=${s.fmpSignP}), paired median `
        + `${s.fmpDelta} ms; the bound is equal or better`);
    }
    if (blankWorse) {
      failures.push(`${row.name} ${state}: blank-until-parsed loads rose from ${off.deferredPaints}/${off.n} `
        + `to ${on.deferredPaints}/${on.n} (${blank.onlyOn} loads blank only with the tier on, `
        + `${blank.onlyOff} only with it off, sign test p=${s.blankSignP}) - the reader saw nothing `
        + "until the document was parsed");
    }
    if (!paintWorse && !blankWorse && (s.fmpDelta > 0 || s.fmpDeltaP75 > 0)) {
      notes.push(`${row.name} ${state}: paint is nominally slower (paired median ${s.fmpDelta} ms, `
        + `p75 ${s.fmpDeltaP75} ms) but not significantly so (${paint.worse}/${paint.pairs} slower, `
        + `p=${s.fmpSignP}) - inconclusive at this sample size, not counted as a regression`);
    }
    if (off.deferredPaints === off.n && on.deferredPaints === on.n) {
      notes.push(`${row.name} ${state}: the blank-until-parsed rate is saturated on BOTH variants `
        + `(${off.n}/${off.n}) - on a document this small the paint and domInteractive coincide, so `
        + "that half of the paint bound carries no information here");
    }
    if (s.ttiDelta > budget) {
      failures.push(`${row.name} ${state}: time to interactive regressed by ${s.ttiDelta} ms `
        + `(paired median over ${s.pairs} pairs); the budget is ${budget} ms`);
    }
  }
  return { name: row.name, largest: !!row.largest, budget, stats, notes, failures, ok: failures.length === 0 };
}

/** Judge every document. `ok` is the harness's verdict on #1263's two open criteria. */
export function evaluateBounds(rows, opts = {}) {
  const documents = rows.map((r) => evaluateDocument(r, opts));
  const failures = documents.flatMap((d) => d.failures);
  const notes = documents.flatMap((d) => d.notes || []);
  return { ok: failures.length === 0, alpha: opts.alpha || ALPHA, documents, failures, notes };
}

const ms = (v) => (typeof v === "number" && Number.isFinite(v) ? `${round(v)}` : "n/a");

/** A plain-text table of the run, suitable for pasting into a spec row or a PR body. */
export function formatReport(result) {
  const lines = [];
  lines.push(`cold-tier perf: ${result.iterations} iteration(s), tti budget ${result.ttiBudgetMs} ms`
    + `${result.chromium ? `, chromium ${result.chromium}` : ""}`);
  lines.push("");
  const head = ["document", "state", "FMP off", "FMP on", "dFMP", "worse", "p", "DCL off", "DCL on",
    "TTI off", "TTI on", "dTTI", "block off", "block on", "total off", "total on", "blank off", "blank on"];
  lines.push(head.join(" | "));
  lines.push(head.map((h) => "-".repeat(h.length)).join(" | "));
  for (const row of result.rows) {
    const verdict = (result.verdict.documents || []).find((d) => d.name === row.name);
    for (const state of ["cold", "warm"]) {
      const off = (row.off && row.off[state]) || {};
      const on = (row.on && row.on[state]) || {};
      const s = (verdict && verdict.stats && verdict.stats[state]) || {};
      const blank = (x) => (x.n ? `${x.deferredPaints}/${x.n}` : "n/a");
      lines.push([row.name, state, ms(off.fmp), ms(on.fmp), ms(s.fmpDelta), s.fmpWorsePairs || "n/a",
        s.fmpSignP == null ? "n/a" : String(s.fmpSignP),
        ms(off.domContentLoaded), ms(on.domContentLoaded), ms(off.tti), ms(on.tti), ms(s.ttiDelta),
        ms(off.longTaskMax), ms(on.longTaskMax), ms(off.longTaskTotal), ms(on.longTaskTotal),
        blank(off), blank(on)].join(" | "));
    }
  }
  lines.push("");
  lines.push("dFMP / dTTI are the MEDIAN of per-iteration PAIRED (on minus off) differences, not a "
    + "difference of medians. \"worse\" is how many paired loads were slower and \"p\" the one-sided "
    + "sign-test p-value, so a nominally slower but non-significant result is reported as "
    + "inconclusive rather than as a regression. \"block\" is the longest main-thread task (the "
    + "parser-blocking window hydration runs in) and \"total\" the total long-task time. \"blank\" "
    + "counts the loads whose first paint landed at or after domInteractive (the reader saw nothing "
    + "until the document was parsed).");
  lines.push("");
  for (const row of result.rows) {
    lines.push(`${row.name}: ${row.bytesOff} bytes OFF, ${row.bytesOn} bytes ON`
      + `${row.compressed ? "" : " (NOT compressed - the tier declined this document)"}`);
  }
  lines.push("");
  lines.push(result.verdict.ok ? "PASS: every bound holds." : "FAIL:");
  for (const f of result.verdict.failures) lines.push(`  - ${f}`);
  for (const n of result.verdict.notes || []) lines.push(`  note: ${n}`);
  return lines.join("\n");
}

/** Read a numeric option, rejecting a missing value, a flag-shaped value, or a non-number.
 *
 * A silently-NaN option is the worst failure this tool can have: `delta > NaN` is always false, so
 * a typo'd `--tti-budget-ms` would DISABLE the interactivity bound and print `PASS`.
 */
function numberAt(argv, i, flag, { min = 0 } = {}) {
  const raw = argv[i];
  if (raw === undefined || String(raw).startsWith("--")) throw new Error(`${flag} needs a value`);
  const n = Number(raw);
  if (!Number.isFinite(n) || !Number.isInteger(n) || n < min) {
    throw new Error(`${flag} must be an integer >= ${min} (got ${JSON.stringify(raw)})`);
  }
  return n;
}

function stringAt(argv, i, flag) {
  const raw = argv[i];
  if (raw === undefined || String(raw).startsWith("--")) throw new Error(`${flag} needs a value`);
  return raw;
}

export function parseArgs(argv) {
  const a = {
    iterations: 5, corpus: null, out: null, minRows: null, keepRows: null,
    ttiBudgetMs: DEFAULT_TTI_BUDGET_MS, quiet: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const k = argv[i];
    if (k === "--iterations") a.iterations = numberAt(argv, ++i, k, { min: 1 });
    else if (k === "--corpus") a.corpus = stringAt(argv, ++i, k).split(",").map((s) => s.trim()).filter(Boolean);
    else if (k === "--out") a.out = stringAt(argv, ++i, k);
    else if (k === "--min-rows") a.minRows = numberAt(argv, ++i, k, { min: 1 });
    else if (k === "--keep-rows") a.keepRows = numberAt(argv, ++i, k, { min: 0 });
    else if (k === "--tti-budget-ms") a.ttiBudgetMs = numberAt(argv, ++i, k, { min: 0 });
    else if (k === "--quiet") a.quiet = true;
    else throw new Error(`unknown option: ${k}`);
  }
  return a;
}

/** Refuse an `--out` that would drop a scratch artifact into the tracked worktree.
 *
 * The repo requires every scratch file under the OS temp dir or a gitignored `tmp/`; a committed
 * `report.json` is exactly the tracked scratch dump its guards refuse.
 */
export function checkOutPath(out, { root = REPO_ROOT } = {}) {
  const abs = path.resolve(out);
  const rel = path.relative(root, abs);
  const inside = rel && !rel.startsWith("..") && !path.isAbsolute(rel);
  if (!inside) return abs;
  // Only the ROOT `tmp/` is gitignored here; a nested `plugins/<x>/tmp/` is NOT, so "a segment
  // named tmp somewhere" would still leave an untracked scratch dump inside the worktree.
  const segments = rel.split(/[\\/]/);
  if (segments[0] === "tmp") return abs;
  throw new Error(`--out ${out} would write inside the repository; use the OS temp dir or a root tmp/ path`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.out) checkOutPath(args.out);
  const specs = args.corpus ? CORPUS.filter((c) => args.corpus.includes(c.name)) : CORPUS;
  if (!specs.length) throw new Error(`no corpus entries matched: ${args.corpus}`);
  if (!fs.existsSync(SHAREABLE)) {
    throw new Error(`no built stage at ${SHAREABLE} - run tools/build.py first`);
  }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_cold_perf_"));
  const log = (m) => { if (!args.quiet) process.stdout.write(`${m}\n`); };
  const rows = [];
  // Recorded FIRST: a probe that threw after the measurements would discard a multi-minute run
  // (and never write --out) for the sake of a version string.
  let chromiumVersion = null;
  try {
    const probe = await chromium.launch();
    chromiumVersion = probe.version();
    await probe.close();
  } catch (_e) { chromiumVersion = null; }
  const schedule = [];
  try {
    for (const spec of specs) {
      const body = buildBody(spec);
      const offPath = stageDocument(body, path.join(dir, `${spec.name}-off.html`));
      const onPath = stageDocument(body, path.join(dir, `${spec.name}-on.html`));
      const packed = compressDocument(onPath, { minRows: args.minRows, keepRows: args.keepRows });
      log(`${spec.name}: ${packed.bytesBefore} -> ${packed.bytesAfter} bytes`
        + `${packed.compressed ? "" : " (tier declined)"}`);
      const offSamples = { cold: [], warm: [] };
      const onSamples = { cold: [], warm: [] };
      for (let i = 0; i < args.iterations; i += 1) {
        // Counterbalanced: alternate which variant loads first, so a machine that gets warmer (or
        // busier) through the run does not hand the second-placed variant a standing advantage.
        const onFirst = onLoadsFirst(i);
        schedule.push(onFirst ? "on-first" : "off-first");
        const first = onFirst ? onPath : offPath;
        const second = onFirst ? offPath : onPath;
        const firstRun = await measureIteration(pathToFileURL(first).href);
        const secondRun = await measureIteration(pathToFileURL(second).href);
        const offRun = onFirst ? secondRun : firstRun;
        const onRun = onFirst ? firstRun : secondRun;
        offSamples.cold.push(offRun.cold); offSamples.warm.push(offRun.warm);
        onSamples.cold.push(onRun.cold); onSamples.warm.push(onRun.warm);
        log(`  iteration ${i + 1}/${args.iterations} (${onFirst ? "on first" : "off first"}): `
          + `off cold fmp ${ms(offRun.cold.fmp)} tti ${ms(offRun.cold.tti)}; `
          + `on cold fmp ${ms(onRun.cold.fmp)} tti ${ms(onRun.cold.tti)}`);
      }
      rows.push({
        name: spec.name,
        largest: !!spec.largest,
        compressed: packed.compressed,
        bytesOff: packed.bytesBefore,
        bytesOn: packed.bytesAfter,
        bodyBytes: Buffer.byteLength(body, "utf8"),
        off: { cold: summarize(offSamples.cold), warm: summarize(offSamples.warm) },
        on: { cold: summarize(onSamples.cold), warm: summarize(onSamples.warm) },
        samples: { off: offSamples, on: onSamples },
      });
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true, maxRetries: 3 });
  }
  const verdict = evaluateBounds(rows, { ttiBudgetMs: args.ttiBudgetMs });
  const result = {
    generatedBy: "tools/cold_tier_perf.mjs",
    recordedAt: new Date().toISOString(),
    iterations: args.iterations,
    ttiBudgetMs: args.ttiBudgetMs,
    alpha: ALPHA,
    minRows: args.minRows,
    keepRows: args.keepRows,
    platform: `${process.platform} ${process.arch}`,
    cpus: `${os.cpus().length} x ${(os.cpus()[0] || {}).model || "unknown"}`,
    node: process.version,
    chromium: chromiumVersion,
    schedule: `${schedule.filter((s) => s === "off-first").length} off-first, `
      + `${schedule.filter((s) => s === "on-first").length} on-first`,
    rows,
    verdict,
  };
  if (args.out) fs.writeFileSync(args.out, `${JSON.stringify(result, null, 2)}\n`);
  process.stdout.write(`${formatReport(result)}\n`);
  process.exitCode = verdict.ok ? 0 : 1;
}

// Only the CLI runs main; importing this module (the spec does) must have no side effects.
if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  main().catch((err) => {
    process.stderr.write(`cold_tier_perf: ${err && err.message ? err.message : err}\n`);
    process.exitCode = 2;
  });
}
