import { test, expect } from "@playwright/test";
import fs from "fs";
import os from "os";
import path from "path";
import { pathToFileURL, fileURLToPath } from "url";
import {
  CORPUS, DEFAULT_TTI_BUDGET_MS, buildBody, stageDocument, compressDocument, checkOutPath,
  instrumentPage, measureLoad, readTimings, median, quantile, pairedDeltas, summarize,
  evaluateBounds, formatReport, parseArgs, signTestP, pairedBlankness, isBlank, onLoadsFirst,
} from "../tools/cold_tier_perf.mjs";

// CMH-COLD-09: the cold tier's paint / time-to-interactive measurement harness.
//
// The harness itself is the deliverable, so what is tested here is the harness: that its numbers
// are really measured in a browser (not inferred), that a compressed document is really what gets
// measured, that a document which was NOT measured fails instead of scoring a flattering zero, and
// that its verdict is the bound #1263 stated rather than a softer one it could always pass. The
// recorded RESULT lives in the spec row and in tools/cold-tier-perf-baseline.json - a timing
// threshold asserted on a shared CI runner would be a flake, not a gate.

/** A deliberately small corpus shape: enough rows for the tier to engage, small enough to be fast. */
const TINY = { name: "tiny", tables: 1, rows: 80, cols: 3, cellWords: 2, paragraphs: 2 };

const BASELINE = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  "..", "tools", "cold-tier-perf-baseline.json");

/** A summary shaped like `summarize` output, for the pure verdict tests. */
function stat(fmp, tti, { n = 3, blank = 0, rows = 100 } = {}) {
  return {
    n, fmpN: n, ttiN: n, fmp, fmpP75: fmp, tti, domContentLoaded: tti + 100, domInteractive: 900,
    longTaskMax: 50, longTaskTotal: 80, paintMargin: fmp - 900,
    fmpSpread: 0, ttiSpread: 0, deferredPaints: blank, fmpSources: ["first-contentful-paint"],
    rowsMin: rows, rowsMax: rows,
  };
}

/** A full row shaped like the harness emits, with paired samples that reproduce the given deltas.
 *
 * `fmpDeltas` takes an explicit per-iteration list so a test can build a BIMODAL pair (most loads
 * equal, a few catastrophically slower) - the shape the real compressed documents produce, and the
 * one a fixture of identical samples can never exercise.
 */
function row(name, { fmpDelta = 0, fmpDeltas = null, ttiDelta = 0, n = 3, largest = false,
  compressed = true, blankOff = 0, blankOn = 0, offRows = 100, onRows = 100 } = {}) {
  const deltas = fmpDeltas || Array.from({ length: n }, () => fmpDelta);
  const count = deltas.length;
  const sample = (fmp, tti, rows, blank) => ({
    fmp, tti, domInteractive: blank ? fmp - 1 : 900, domContentLoaded: 1000, rows,
    longTaskMax: 50, longTaskTotal: 80, fmpSource: "first-contentful-paint",
  });
  const offSamples = Array.from({ length: count }, (_, i) => sample(200, 900, offRows, i < blankOff));
  const onSamples = deltas.map((d, i) => sample(200 + d, 900 + ttiDelta, onRows, i < blankOn));
  const summary = (fmp, tti, blank, rows) => stat(fmp, tti, { n: count, blank, rows });
  return {
    name, largest, compressed,
    off: { cold: summary(200, 900, blankOff, offRows), warm: summary(200, 900, blankOff, offRows) },
    on: {
      cold: summary(200 + median(deltas), 900 + ttiDelta, blankOn, onRows),
      warm: summary(200 + median(deltas), 900 + ttiDelta, blankOn, onRows),
    },
    samples: { off: { cold: offSamples, warm: offSamples }, on: { cold: onSamples, warm: onSamples } },
  };
}

/** A delta list that is significantly worse by the sign test: every paired load slower. */
const ALL_WORSE = (n, by) => Array.from({ length: n }, () => by);

test.describe("cold-tier perf harness", () => {
  test("measures paint and time-to-interactive on a real compressed document (CMH-COLD-09)", async ({ page }) => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_perf_spec_"));
    try {
      const body = buildBody(TINY);
      const off = stageDocument(body, path.join(dir, "tiny-off.html"));
      const on = stageDocument(body, path.join(dir, "tiny-on.html"));
      const packed = compressDocument(on);
      // The ON document must really be compressed, or the harness would be comparing a document
      // with itself and reporting a flattering zero delta forever.
      expect(packed.compressed, "the shipped cold_tier.py declined to compress the corpus shape").toBe(true);
      expect(packed.bytesAfter).toBeLessThan(packed.bytesBefore);
      expect(fs.readFileSync(on, "utf8")).toContain('id="cmhColdTier"');
      // The two files really are different documents on disk, so the measurement is a comparison.
      expect(fs.readFileSync(on, "utf8")).not.toBe(fs.readFileSync(off, "utf8"));

      await instrumentPage(page);
      const offTimings = await measureLoad(page, pathToFileURL(off).href);
      const onTimings = await measureLoad(page, pathToFileURL(on).href);

      for (const [label, t] of [["off", offTimings], ["on", onTimings]]) {
        expect(Number.isFinite(t.fmp), `${label}: no paint was observed`).toBe(true);
        expect(Number.isFinite(t.tti), `${label}: the layer never signalled ready`).toBe(true);
        expect(t.fmp).toBeGreaterThan(0);
        expect(t.tti).toBeGreaterThan(0);
        expect(t.fmpSource, `${label}: the paint metric's provenance is unrecorded`).toBeTruthy();
      }
      // The numbers move with the document rather than being constants: a second, independent
      // navigation reports its own timings, so a harness that returned a fixed value would fail.
      expect(onTimings.tti).not.toBe(offTimings.tti);
      // The measured pair is the SAME document either way: hydration restores every cold row, so a
      // paint/TTI comparison between them is like for like rather than "fewer rows are faster".
      expect(onTimings.rows).toBe(TINY.rows);
      expect(onTimings.rows).toBe(offTimings.rows);
      // Leave the file:// document before the temp tree is removed: Chromium holds a lock on
      // Windows, and rmSync would then throw EBUSY out of a passing test.
      await page.goto("about:blank");
    } finally {
      fs.rmSync(dir, { recursive: true, force: true, maxRetries: 3 });
    }
  });

  test("sources every timing from the pre-load probe, not from a read at load (CMH-COLD-09)", async ({ page }) => {
    // The methodology bug this harness was built around: with the tier ON, `load` can fire BEFORE
    // the first paint, so reading `performance.getEntriesByType("paint")` at that moment finds
    // nothing and scores the worst documents as "not measured". `readTimings` must therefore take
    // its numbers from the OBSERVER-fed probe. Pinning that here means a revert to a load-time
    // read is caught by a fast test instead of by a future reader wondering why the slowest
    // documents have no numbers.
    await page.goto("about:blank");
    await page.evaluate(() => {
      Object.defineProperty(window, "__cmhPerfProbe", {
        value: { ready: 1234, firstPaint: 111, firstContentfulPaint: 222, longTaskMax: 40, longTaskTotal: 90 },
        configurable: true,
      });
    });
    const t = await readTimings(page);
    // about:blank has painted nothing, so any value here can only have come from the probe.
    expect(t.tti).toBe(1234);
    expect(t.fmp).toBe(222);
    expect(t.fmpSource).toBe("first-contentful-paint");
    expect(t.firstPaint).toBe(111);
    expect(t.longTaskMax).toBe(40);

    // With no contentful paint recorded, the fallback is used AND named, so a run cannot silently
    // average `first-contentful-paint` and `first-paint` samples together.
    await page.evaluate(() => {
      Object.defineProperty(window, "__cmhPerfProbe", {
        value: { ready: 5, firstPaint: 99, firstContentfulPaint: null },
        configurable: true,
      });
    });
    const fallback = await readTimings(page);
    expect(fallback.fmp).toBe(99);
    expect(fallback.fmpSource).toBe("first-paint");
  });

  test("observes the main-thread blocking window in a real browser (CMH-COLD-09)", async ({ page }) => {
    // The spec quotes the longest-task figures when it says a faster decoder is not the lever, so
    // the observer that produces them has to be wired to a real browser, not just passed through
    // `readTimings`. A page that blocks its main thread for a known span must show up.
    await instrumentPage(page);
    await page.goto("about:blank");
    // Scheduled as a page TASK (a `page.evaluate` block runs through the debugger protocol and is
    // not attributed to the page), so this is the same kind of task hydration runs in.
    await page.evaluate(() => {
      setTimeout(() => {
        const end = performance.now() + 200;
        while (performance.now() < end) { /* block the main thread */ }
      }, 0);
    });
    await page.waitForFunction(() => window.__cmhPerfProbe && window.__cmhPerfProbe.longTaskMax > 0,
      null, { timeout: 10000 });
    const probe = await page.evaluate(() => ({
      max: window.__cmhPerfProbe.longTaskMax, total: window.__cmhPerfProbe.longTaskTotal,
    }));
    expect(probe.max).toBeGreaterThan(50);
    expect(probe.total).toBeGreaterThanOrEqual(probe.max);
  });

  test("records an empty sample instead of losing the run when a load times out (CMH-COLD-09)", async ({ page }) => {
    // A single flaky load used to throw out of `measureLoad` and kill a multi-minute run with exit
    // 2, which also made the "incomplete measurement" verdict unreachable from the CLI. A TIMEOUT
    // is now data; anything else (a crashed renderer, a bug in this harness) still throws, so a
    // real failure cannot hide behind an empty sample.
    await instrumentPage(page);
    const timedOut = await measureLoad(page, "about:blank", { timeout: 500 });
    expect(timedOut.fmp).toBe(null);
    expect(timedOut.tti).toBe(null);
    expect(timedOut.rows).toBe(null);

    // A navigation error is NOT a timeout, so it propagates.
    await expect(measureLoad(page, "http://127.0.0.1:1/never", { timeout: 5000 })).rejects.toThrow();
  });

  test("the corpus carries the largest surveyed shape and stages real layer documents (CMH-COLD-09)", () => {
    const largest = CORPUS.filter((c) => c.largest);
    expect(largest.length, "exactly one corpus entry is the largest document").toBe(1);
    // #1250's largest tree-heavy document was about 3.2 MiB of body; the corpus has to reach it or
    // the measurement is not of the case the tier exists for. The window is wide enough that a
    // filler tweak does not red CI, and tight enough that the size the spec quotes stays true.
    const bytes = Buffer.byteLength(buildBody(largest[0]), "utf8");
    expect(bytes).toBeGreaterThan(3.1 * 1024 * 1024);
    expect(bytes).toBeLessThan(3.4 * 1024 * 1024);
    // Deterministic: two builds of the same spec are byte-identical, so a rerun measures the same
    // document rather than a fresh random one.
    expect(buildBody(CORPUS[0])).toBe(buildBody(CORPUS[0]));

    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_perf_stage_"));
    try {
      const staged = stageDocument(buildBody(TINY), path.join(dir, "doc.html"));
      const html = fs.readFileSync(staged, "utf8");
      expect(html).toContain("__commentableHtmlReady");
      expect(html).toContain("tiny performance corpus");
      // An unbuilt stage is named, not an ENOENT from deep inside fs.
      expect(() => stageDocument("x", path.join(dir, "y.html"), { source: path.join(dir, "missing.html") }))
        .toThrow(/no built stage/);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true, maxRetries: 3 });
    }
  });

  test("the verdict enforces the paint and interactivity bounds #1263 set (CMH-COLD-09)", () => {
    // Paint equal or better, interactivity inside the budget: a pass.
    expect(evaluateBounds([row("ok", { fmpDelta: -20, ttiDelta: 100, n: 8 })]).ok).toBe(true);
    // A consistent paint regression across every paired load IS significant, and fails - the bound
    // is "equal or better", not "close enough".
    const paint = evaluateBounds([row("paint", { fmpDeltas: ALL_WORSE(8, 40) })]);
    expect(paint.ok).toBe(false);
    expect(paint.failures.join("\n")).toContain("first meaningful paint regressed");
    // A rise in blank-until-parsed loads is a paint miss on its own, even when the timing median is
    // flat: that rate, not the median, is what the bimodal compressed distribution actually does.
    // This is the BIMODAL shape - most loads identical, a few catastrophically slower - which a
    // fixture of identical samples could never exercise.
    const bimodal = row("bimodal", {
      fmpDeltas: [0, 0, 0, 0, 0, 5000, 5100, 5200], blankOff: 0, blankOn: 5,
    });
    const blank = evaluateBounds([bimodal]);
    expect(blank.ok).toBe(false);
    expect(blank.failures.join("\n")).toContain("blank-until-parsed loads rose");
    // Interactivity just inside and just outside the 150 ms budget.
    expect(evaluateBounds([row("edge", { ttiDelta: DEFAULT_TTI_BUDGET_MS, n: 8 })]).ok).toBe(true);
    const tti = evaluateBounds([row("over", { ttiDelta: DEFAULT_TTI_BUDGET_MS + 1, n: 8 })]);
    expect(tti.ok).toBe(false);
    expect(tti.failures.join("\n")).toContain("time to interactive regressed");
    // The largest document gets NO interactivity budget at all: it must not be worse than today.
    expect(evaluateBounds([row("big", { ttiDelta: 1, largest: true, n: 8 })]).ok).toBe(false);
    expect(evaluateBounds([row("big", { ttiDelta: 0, largest: true, n: 8 })]).ok).toBe(true);
  });

  test("a nominally slower but insignificant result is inconclusive, not a regression (CMH-COLD-09)", () => {
    // The load-bearing statistical property. A zero-tolerance rule was measured against a NULL
    // control - a document's own OFF samples paired against a rotation of themselves - and failed
    // it, which would make the gate unreachable and would fail a document compared with ITSELF.
    // So paint is judged by a one-sided sign test, and a small nominal slowdown that could easily
    // be noise is reported rather than counted.
    expect(signTestP(9, 9)).toBeCloseTo(0.00195, 4);
    expect(signTestP(8, 9)).toBeCloseTo(0.01953, 4);
    // 7 of 9 slower is p = 0.09: NOT significant at alpha 0.05, so it must not fail the run.
    expect(signTestP(7, 9)).toBeGreaterThan(0.05);
    expect(signTestP(0, 0)).toBe(1);

    const noisy = row("noisy", { fmpDeltas: [-40, -30, -10, 5, 10, 20, 30, 40, 60] });
    const verdict = evaluateBounds([noisy]);
    expect(verdict.ok, "a nominally slower but insignificant result must not fail the run").toBe(true);
    expect(verdict.notes.join("\n")).toContain("inconclusive");

    // The blank half is a PAIRED (McNemar-style) comparison, not two independent rates: only the
    // loads where exactly one variant went blank carry signal.
    const off = [{ fmp: 100, domInteractive: 500 }, { fmp: 900, domInteractive: 500 }];
    const on = [{ fmp: 900, domInteractive: 500 }, { fmp: 900, domInteractive: 500 }];
    expect(isBlank(off[0])).toBe(false);
    expect(isBlank(off[1])).toBe(true);
    expect(pairedBlankness(off, on)).toEqual({ onlyOn: 1, onlyOff: 0, pairs: 2 });
    // A single discordant load is not significant; five in the same direction are.
    expect(signTestP(1, 1)).toBeGreaterThan(0.05);
    expect(signTestP(5, 5)).toBeLessThan(0.05);

    // A saturated blank rate (every load blank on BOTH variants) is called out as uninformative
    // instead of silently passing that half of the bound.
    const saturated = row("tiny", { n: 4, blankOff: 4, blankOn: 4 });
    const sat = evaluateBounds([saturated]);
    expect(sat.notes.join("\n")).toContain("saturated");
  });

  test("an unmeasured document fails instead of scoring a flattering zero (CMH-COLD-09)", () => {
    // A tier that DECLINED to compress leaves two identical files, so every delta is zero and the
    // bounds all "hold". That is a non-measurement, and the verdict has to say so - the guard
    // cannot live only in this test file, because the spec row cites the harness as the gate. It
    // also SHORT-CIRCUITS, so the artifact does not carry paint numbers derived from noise between
    // two identical documents.
    const declined = evaluateBounds([row("declined", { compressed: false, fmpDeltas: ALL_WORSE(8, 40) })]);
    expect(declined.ok).toBe(false);
    expect(declined.failures.length).toBe(1);
    expect(declined.failures.join("\n")).toContain("declined to compress");
    expect(declined.failures.join("\n")).not.toContain("first meaningful paint");

    // A hydration that did not restore every row is NON-BLOCKING by design (CMH-COLD-06), so the
    // ON document would render fewer rows and look dramatically faster. Not comparable, not a pass.
    const short = evaluateBounds([row("short", { onRows: 20, offRows: 100 })]);
    expect(short.ok).toBe(false);
    expect(short.failures.join("\n")).toContain("not comparable");

    // A load that never reported both numbers is a failure, not a silently smaller sample.
    const gappy = row("gappy");
    gappy.on.cold.fmpN = gappy.on.cold.n - 1;
    gappy.samples.on.cold[0] = { fmp: null, tti: null, domInteractive: null, domContentLoaded: null, rows: 100 };
    const incomplete = evaluateBounds([gappy]);
    expect(incomplete.ok).toBe(false);
    expect(incomplete.failures.join("\n")).toContain("incomplete measurement");

    // `readTimings` falls back from `first-contentful-paint` to `first-paint`, and `first-paint`
    // can fire on a frame carrying no content - so a run that mixed the two would be differencing
    // two different metrics, and a MIXED PAIR would subtract one from the other.
    const mixed = row("mixed", { n: 4 });
    mixed.on.cold.fmpSources = ["first-paint"];
    mixed.samples.on.cold = mixed.samples.on.cold.map((s) => ({ ...s, fmpSource: "first-paint" }));
    const verdict = evaluateBounds([mixed]);
    expect(verdict.ok).toBe(false);
    expect(verdict.failures.join("\n")).toContain("mixed paint metrics");
    // The mismatched pairs are dropped rather than differenced.
    expect(pairedDeltas(mixed.samples.off.cold, mixed.samples.on.cold, "fmp",
      { matchKey: "fmpSource" })).toEqual([]);
  });

  test("deltas are paired per iteration and the run is counterbalanced (CMH-COLD-09)", () => {
    // Pairing is what makes a drift shared by both variants cancel. Here every ON sample is 10 ms
    // slower than its OFF partner, but the two sets also drift upward together by 1000 ms; a
    // difference of medians would report the drift, a paired median reports the 10 ms.
    const off = [{ fmp: 100 }, { fmp: 600 }, { fmp: 1100 }];
    const on = [{ fmp: 110 }, { fmp: 610 }, { fmp: 1110 }];
    expect(pairedDeltas(off, on, "fmp")).toEqual([10, 10, 10]);
    expect(median(pairedDeltas(off, on, "fmp"))).toBe(10);
    // An iteration where either side is missing is dropped from the pairing rather than compared
    // against an unrelated iteration.
    expect(pairedDeltas([{ fmp: 1 }, { fmp: null }], [{ fmp: 3 }, { fmp: 9 }], "fmp")).toEqual([2]);
    expect(pairedDeltas([], [], "fmp")).toEqual([]);

    // The counterbalancing is the EXPORTED decision the CLI loop calls, not a rule restated here:
    // a revert to a fixed OFF-then-ON order (which hands ON a warmed machine) has to fail a test,
    // and it does only if the test exercises the real function.
    expect([0, 1, 2, 3].map(onLoadsFirst)).toEqual([false, true, false, true]);
    const schedule = Array.from({ length: 8 }, (_, i) => onLoadsFirst(i));
    expect(schedule.filter(Boolean).length).toBe(4);
  });

  test("a mistyped numeric option is refused rather than silently disabling a bound (CMH-COLD-09)", () => {
    // `delta > NaN` is always false, so a typo'd budget would DISABLE the interactivity bound and
    // print PASS. Every numeric option is therefore validated, and a flag-shaped or missing value
    // is refused rather than swallowed as the value.
    expect(() => parseArgs(["--tti-budget-ms", "nope"])).toThrow(/must be an integer/);
    expect(() => parseArgs(["--tti-budget-ms"])).toThrow(/needs a value/);
    expect(() => parseArgs(["--out", "--quiet"])).toThrow(/needs a value/);
    expect(() => parseArgs(["--iterations", "0"])).toThrow(/must be an integer/);
    expect(() => parseArgs(["--min-rows", "-4"])).toThrow(/must be an integer/);
    expect(() => parseArgs(["--nope"])).toThrow(/unknown option/);
    expect(parseArgs(["--tti-budget-ms", "0"]).ttiBudgetMs).toBe(0);
    expect(parseArgs([]).ttiBudgetMs).toBe(DEFAULT_TTI_BUDGET_MS);

    // A report written into the tracked worktree is exactly the committed scratch dump the repo's
    // guards refuse, so `--out` is confined to a temp dir or the gitignored ROOT `tmp/`. A nested
    // `plugins/<x>/tmp/` is NOT gitignored here, so "a segment named tmp" would not be enough.
    expect(() => checkOutPath("report.json")).toThrow(/inside the repository/);
    const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
    expect(() => checkOutPath(path.join(root, "plugins", "commentable-html", "tmp", "r.json")))
      .toThrow(/inside the repository/);
    expect(checkOutPath(path.join(os.tmpdir(), "r.json"))).toContain("r.json");
    expect(checkOutPath(path.join(root, "tmp", "r.json"))).toContain("r.json");
  });

  test("the summary reports the median, the spread and the blank-until-parsed loads (CMH-COLD-09)", () => {
    expect(median([3, 1, 2])).toBe(2);
    expect(median([4, 1, 2, 3])).toBe(2.5);
    expect(median([null, undefined, NaN])).toBe(null);
    expect(quantile([1, 2, 3, 4], 0.75)).toBe(3);
    expect(quantile([], 0.75)).toBe(null);

    const s = summarize([
      { fmp: 100, tti: 300, domInteractive: 500, domContentLoaded: 700, rows: 9, longTaskMax: 60, longTaskTotal: 90, fmpSource: "first-contentful-paint" },
      { fmp: 600, tti: 320, domInteractive: 500, domContentLoaded: 700, rows: 9, longTaskMax: 55, longTaskTotal: 80, fmpSource: "first-contentful-paint" },
      { fmp: 120, tti: null, domInteractive: 500, domContentLoaded: 700, rows: 9, longTaskMax: 70, longTaskTotal: 95, fmpSource: "first-contentful-paint" },
    ]);
    expect(s.n).toBe(3);
    expect(s.fmp).toBe(120);
    expect(s.fmpSpread).toBe(500);
    // The counts that actually fed each statistic are reported, so a median over 2 loads can never
    // be presented as if it were over 3.
    expect(s.fmpN).toBe(3);
    expect(s.ttiN).toBe(2);
    // One of the three loads painted nothing until the parser had finished. That count is the
    // shape of the cold-tier result, and a median alone would hide it.
    expect(s.deferredPaints).toBe(1);
    expect(s.rowsMin).toBe(9);
    expect(s.rowsMax).toBe(9);
    // The blocking window CMH-COLD-05 quotes: BOTH the longest task and the total, because the
    // two move in opposite directions and quoting only the first misstates the tier's cost.
    expect(s.longTaskMax).toBe(60);
    expect(s.longTaskTotal).toBe(90);
    // The margin behind `deferredPaints`, so a saturated rate can be recognised rather than read
    // as a real regression.
    expect(s.paintMargin).toBe(-380);

    const rows = [row("doc")];
    const verdict = evaluateBounds(rows);
    const report = formatReport({
      iterations: 3, ttiBudgetMs: DEFAULT_TTI_BUDGET_MS, chromium: "149.0", rows, verdict,
    });
    expect(report).toContain("doc");
    expect(report).toContain("blank");
    expect(report).toContain("PASS");
  });

  test("the recorded baseline is a real harness result and backs the figures the spec quotes (CMH-COLD-09)", () => {
    // The spec row quotes figures from this artifact, so it has to stay a real harness result
    // rather than hand-typed prose that drifts from the tool that produced it - and it has to
    // carry the fields those figures come from, or a future `summarize` change silently strands it.
    const baseline = JSON.parse(fs.readFileSync(BASELINE, "utf8"));
    expect(baseline.generatedBy).toBe("tools/cold_tier_perf.mjs");
    expect(baseline.runs.length).toBeGreaterThanOrEqual(2);
    const [main, sweep] = baseline.runs;
    const summaryKeys = Object.keys(summarize([{
      fmp: 1, tti: 2, domInteractive: 1, domContentLoaded: 3, rows: 1,
      longTaskMax: 1, longTaskTotal: 1, fmpSource: "first-contentful-paint",
    }]));
    for (const run of baseline.runs) {
      expect(run.chromium, "the baseline records the browser it was measured with").toBeTruthy();
      expect(run.recordedAt, "the baseline records when it was measured").toBeTruthy();
      expect(run.platform).toBeTruthy();
      expect(run.cpus, "the baseline names the reference machine").toBeTruthy();
      expect(run.rows.length).toBeGreaterThan(0);
      for (const r of run.rows) {
        for (const state of ["cold", "warm"]) {
          expect(r.off[state].n).toBe(run.iterations);
          expect(r.on[state].n).toBe(run.iterations);
          // Every field `summarize` emits is present, so the artifact cannot silently lose the
          // statistic a spec sentence rests on.
          expect(Object.keys(r.off[state]).sort()).toEqual(summaryKeys.sort());
        }
      }
    }
    // The main run used the SHIPPED defaults, and the sweep is the threshold experiment the spec
    // row cites when it says the row thresholds are the lever that moves the paint result.
    expect(main.minRows).toBe(null);
    expect(main.keepRows).toBe(null);
    expect(sweep.keepRows).toBeGreaterThan(0);
    expect(main.rows.some((r) => r.largest && r.compressed)).toBe(true);

    // The two headline conclusions are read back OUT of the artifact rather than trusted from the
    // prose: the largest document fails the paint bound at the defaults and passes it in the sweep.
    const xlMain = main.rows.find((r) => r.largest);
    const xlSweep = sweep.rows.find((r) => r.largest);
    const verdictFor = (run, name) => run.verdict.documents.find((d) => d.name === name);
    expect(verdictFor(main, xlMain.name).failures.join("\n")).toContain("blank-until-parsed");
    expect(verdictFor(sweep, xlSweep.name).failures).toEqual([]);
    // And the sweep really does cost compression rather than being free.
    expect(xlSweep.bytesOn).toBeGreaterThan(xlMain.bytesOn);
    expect(xlMain.bytesOn).toBeLessThan(xlMain.bytesOff);
    // Total main-thread blocking FALLS with the tier on, which is the basis for CMH-COLD-05 saying
    // the decoder is not the lever.
    expect(xlMain.on.cold.longTaskTotal).toBeLessThan(xlMain.off.cold.longTaskTotal);
    expect(xlMain.on.cold.longTaskMax).toBeGreaterThan(xlMain.off.cold.longTaskMax);
    // TTI is the criterion that was TICKED on #1263: better than plain on the largest document.
    expect(verdictFor(main, xlMain.name).stats.cold.ttiDelta).toBeLessThan(0);
    expect(verdictFor(main, xlMain.name).stats.warm.ttiDelta).toBeLessThan(0);
  });
});
