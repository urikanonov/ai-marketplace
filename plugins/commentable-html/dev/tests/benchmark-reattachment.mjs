import { chromium } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createHash } from "node:crypto";

const dev = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const option = (name, fallback) => {
  const i = args.indexOf(name);
  return i < 0 ? fallback : args[i + 1];
};
const baseline = option("--baseline");
const output = option("--output");
const samples = Number(option("--samples", "15"));
const filter = option("--filter", "");
const baselineTemplate = option("--baseline-template");
const startupOnly = args.includes("--startup-only");
if (!baseline || !output || !Number.isInteger(samples) || samples < 3) {
  throw new Error("Usage: node tests/benchmark-reattachment.mjs --baseline <16-reattachment.js> --output <JSON> [--samples 15] [--filter name]");
}
const read = name => fs.readFileSync(path.join(dev, "assets", "js", name), "utf8");
const versions = [
  { name: "baseline", source: fs.readFileSync(path.resolve(baseline), "utf8") },
  { name: "candidate", source: read("16-reattachment.js") },
];
const prefix = read("10-offsets.js") + read("15-context.js");
fs.mkdirSync(path.dirname(path.resolve(output)), { recursive: true });
const fixtures = [];
function report(name, blocks, padding, count, operation = "resolve", revision = "same") {
  const paragraphs = Array.from({ length: blocks }, (_, i) =>
    `<p id="p${i}">Introduction ${i}. A selected review passage number ${i}. `
      + "Context for careful review. ".repeat(padding) + ` Conclusion ${i}.</p>`);
  const original = paragraphs.join("");
  let revised = revision === "insert" ? "<p>New agent introduction.</p>" + original : original;
  if (revision === "normalize") revised = revised.replaceAll("selected review", "selected  \nreview");
  if (revision === "fuzzy") revised = revised.replaceAll("selected review", "selected useful review");
  const quotes = Array.from({ length: count }, (_, i) => {
    const block = Math.floor(i * blocks / count);
    return `A selected review passage number ${block}.`;
  });
  fixtures.push({ name, original, revised, quotes, operation });
}
report("unchanged-small", 100, 2, 20);
report("unchanged-medium", 1000, 8, 200);
report("unchanged-large", 3000, 10, 500);
report("upgrade-large", 3000, 10, 500);
fixtures[fixtures.length - 1].migration = true;
report("inserted-large", 3000, 10, 30, "resolve", "insert");
report("mixed-id-large", 3000, 10, 30, "resolve", "insert");
for (const key of ["original", "revised"]) fixtures[fixtures.length - 1][key] =
  fixtures[fixtures.length - 1][key].replace(/<p id="p(\d+)">/g,
    (match, i) => Number(i) < 1000 && Number(i) % 100 === 0 ? match : "<p>");
report("normalized-medium", 1000, 8, 30, "resolve", "normalize");
report("edited-small", 100, 2, 20, "resolve", "fuzzy");
report("capture-large", 3000, 10, 1, "capture");
report("block-lookups-large", 10000, 0, 1, "blocks");
fixtures.push({ name: "alignment-near-cell-limit", original: "<p>" + "Context ".repeat(100) + "</p>",
  revised: "<p>" + "Context ".repeat(100) + "</p>", quotes: [], operation: "align" });
fixtures.push({
  name: "duplicates",
  original: "<p>A repeated indistinguishable review passage.</p>".repeat(1000),
  revised: "<p>New introduction.</p>" + "<p>A repeated indistinguishable review passage.</p>".repeat(999),
  quotes: ["A repeated indistinguishable review passage."],
  operation: "resolve",
});
fixtures.push({
  name: "normalization-limit",
  original: "<p>" + "Regular prose with spaces. ".repeat(280000) + "</p>",
  revised: "<p>" + "Regular prose with spaces. ".repeat(280000) + "</p>",
  quotes: [],
  operation: "normalize",
});
fixtures.push({
  name: "collapsed-space-limit",
  original: "<p>" + "Regular  prose  with  spaces. ".repeat(250000) + "</p>",
  revised: "<p>" + "Regular  prose  with  spaces. ".repeat(250000) + "</p>",
  quotes: [],
  operation: "normalize",
});
const selected = startupOnly ? [] : fixtures.filter(f => f.name.includes(filter));
if (!selected.length && !(startupOnly && baselineTemplate)) throw new Error("No matching benchmark fixtures");
const browser = await chromium.launch();
const result = {
  environment: { platform: os.platform(), arch: os.arch(), cpu: os.cpus()[0].model,
    logicalCpus: os.cpus().length, node: process.version, browser: browser.version(),
    samples, warmups: 3, timestamp: new Date().toISOString() },
  sources: versions.map(v => ({ name: v.name, sha256: createHash("sha256").update(v.source).digest("hex") })),
  sharedHelpersSha256: createHash("sha256").update(prefix).digest("hex"),
  driverSha256: createHash("sha256").update(fs.readFileSync(fileURLToPath(import.meta.url))).digest("hex"),
  method: "Serial alternating baseline/candidate browser contexts. The cold field is the first invocation in a fresh document after selector seeding in a discarded document and requested GC, NOT a cold isolate/process: the Page/context is reused and JIT/code caches can remain warm. Warm samples follow three warmups. DOM setup, selector seeding, IPC and profiling are outside timed intervals. Each version captures its own selectors from identical original content; the unchanged-upgrade case removes additive basis evidence. Seeding resets the fixture's scan budget between independent comments (as independent saves do), reusing immutable text to avoid timing fixture generation. Timing is resolver/capture/index work, not whole-page startup. Profiled work/allocation and heap deltas are diagnostic, not latency samples.",
  fixtures: [],
};
try {
  for (const fixture of selected) {
    const runs = new Map();
    for (const version of versions) {
      const context = await browser.newContext();
      const page = await context.newPage();
      await page.route("**/*", route => route.abort());
      await page.setContent(`<main id="commentRoot">${fixture.original}</main>`);
      const script = `
        const root = document.getElementById("commentRoot");
        let comments = [], saved = 0, lastIndex = null;
        const CMH_MAX_OFFSET = 1000000000, CMH_MAX_COMMENTS = 1000;
        function saveComments() { saved++; return true; }
        function showStartupDiagnostic() {}
        ${prefix}
        ${version.source}
        window.bench = {
          prepare(fixture, seed) {
            if (seed) this.seed = seed;
            else {
              const text = getTextNodes().map(n => n.nodeValue).join("");
              const index = cmhAnchorIndex();
              this.seed = fixture.quotes.map((quote, i) => {
                const start = text.indexOf(quote);
                if (start < 0) throw new Error("Missing seed quote");
                const c = { id: "cbench" + String(i).padStart(6, "0"), quote, start, end: start + quote.length,
                  note: "Reviewer question", createdAt: "2025-01-01", updatedAt: "2025-02-01" };
                index.budget = CMH_ANCHOR_SCAN_BUDGET;
                cmhCaptureTextAnchor(c, index);
                if (fixture.migration) delete c.cmAnchor.basis;
                return c;
              });
            }
            root.innerHTML = fixture.revised;
            cmhAuthoredIds.clear();
            root.querySelectorAll("[id]").forEach(el => cmhAuthoredIds.add(el.id));
            this.operation = fixture.operation;
          },
          run() {
            comments = structuredClone(this.seed); saved = 0;
            let alignment = null;
            const begin = performance.now();
            if (this.operation === "capture") {
              delete comments[0].cmAnchor;
              cmhCaptureTextAnchor(comments[0]);
            } else if (this.operation === "blocks") {
              const index = cmhAnchorIndex();
              for (let i = 0; i < 1000; i++) {
                const block = index.blocks[(i * 997) % index.blocks.length];
                if (cmhAnchorBlock(index, block.start, block.end) !== block)
                  throw new Error("Wrong block");
              }
            } else if (this.operation === "align") {
              const index = cmhAnchorIndex(), old = index.text;
              const revised = old.slice(0, 400) + "z" + old.slice(401);
              for (let i = 0; i < 8; i++) {
                alignment = cmhAnchorEditMap(old, revised, index);
                if (!alignment || alignment[0] !== 0 || alignment[400] !== -1 || alignment[799] !== 799)
                  throw new Error("Incorrect bounded alignment");
              }
            } else if (this.operation === "normalize") {
              const index = cmhAnchorIndex();
              if (index.limited) throw new Error("Normalization fixture exceeds source limit");
              index.normalized = cmhAnchorNormalize(index.text, false, true);
              lastIndex = index;
            } else cmhReattachComments();
            const ms = performance.now() - begin;
            return { ms, saved, attached: comments.filter(c => !cmhIsDetached(c)).length,
              offsets: comments.map(c => [c.start, c.end, !!c.detached]),
              bytes: lastIndex && lastIndex.normalized
                ? (lastIndex.normalized.starts?.byteLength || 0) + (lastIndex.normalized.ends?.byteLength || 0)
                  + (lastIndex.normalized.positions?.byteLength || 0) + (lastIndex.normalized.omitted?.byteLength || 0) : 0 };
          },
          profile() {
            this.stats = {};
            for (const name of ["cmhAnchorIndex", "cmhAnchorBlock", "cmhAnchorOccurrences",
              "cmhCaptureTextAnchor", "cmhAnchorNormalize", "cmhAnchorEditMap"]) {
              const original = eval(name), stats = this.stats;
              eval(name + " = function(...args) { const t = performance.now(); const value = original(...args); "
                + "const row = stats[name] || (stats[name] = { calls: 0, ms: 0 }); row.calls++; row.ms += performance.now() - t; "
                + "if (name === 'cmhAnchorIndex') lastIndex = value; return value; }");
            }
            const outcome = this.run();
            return { ...outcome, stats: this.stats,
              normalized: lastIndex?.normalized ? { length: lastIndex.normalized.text.length,
                hash: cmhAnchorHash(lastIndex.normalized.text) } : null,
              chars: lastIndex?.text.length, blocks: lastIndex?.blocks.length };
          }
        };
      `;
      await page.addScriptTag({ content: script });
      await page.evaluate(f => bench.prepare(f), fixture);
      const seed = await page.evaluate(() => bench.seed);
      await page.goto("about:blank");
      await page.setContent(`<main id="commentRoot">${fixture.revised}</main>`);
      await page.addScriptTag({ content: script });
      await page.evaluate(({ fixture, seed }) => bench.prepare(fixture, seed), { fixture, seed });
      const cdp = await context.newCDPSession(page);
      await cdp.send("HeapProfiler.collectGarbage");
      const heapBefore = await cdp.send("Runtime.getHeapUsage");
      const cold = await page.evaluate(() => bench.run());
      const heapAfter = await cdp.send("Runtime.getHeapUsage");
      for (let i = 0; i < 3; i++) await page.evaluate(() => bench.run());
      runs.set(version.name, { context, page, cold, heapBefore, heapAfter, samples: [] });
    }
    for (let i = 0; i < samples; i++) {
      for (const version of i % 2 ? [...versions].reverse() : versions) {
        const run = runs.get(version.name);
        run.samples.push(await run.page.evaluate(() => bench.run()));
      }
    }
    const row = { name: fixture.name, operation: fixture.operation, comments: fixture.quotes.length,
      htmlBytes: Buffer.byteLength(fixture.original), versions: {} };
    for (const version of versions) {
      const run = runs.get(version.name);
      const sorted = run.samples.map(s => s.ms).sort((a, b) => a - b);
      const outcomes = [run.cold, ...run.samples];
      if (new Set(outcomes.map(s => JSON.stringify(s.offsets))).size !== 1)
        throw new Error(`${fixture.name}/${version.name}: nondeterministic attachment outcomes`);
      const profile = await run.page.evaluate(() => bench.profile());
      row.versions[version.name] = { cold: run.cold, median: sorted[Math.floor(sorted.length / 2)],
        p95: sorted[Math.ceil(sorted.length * 0.95) - 1], samples: run.samples, profile,
        heapDelta: { used: run.heapAfter.usedSize - run.heapBefore.usedSize,
          embedder: run.heapAfter.embedderHeapUsedSize - run.heapBefore.embedderHeapUsedSize,
          backing: run.heapAfter.backingStorageSize - run.heapBefore.backingStorageSize } };
      await run.context.close();
    }
    if (JSON.stringify(row.versions.baseline.cold.offsets) !== JSON.stringify(row.versions.candidate.cold.offsets))
      row.outcomeDifference = true;
    if (row.versions.baseline.profile.normalized && row.versions.candidate.profile.normalized
      && JSON.stringify(row.versions.baseline.profile.normalized) !== JSON.stringify(row.versions.candidate.profile.normalized))
      throw new Error(`${fixture.name}: normalization output changed`);
    result.fixtures.push(row);
    fs.mkdirSync(path.dirname(path.resolve(output)), { recursive: true });
    fs.writeFileSync(path.resolve(output), JSON.stringify(result, null, 2) + "\n");
    console.log(`${fixture.name}: ${row.versions.baseline.median.toFixed(2)} -> ${row.versions.candidate.median.toFixed(2)} ms; `
      + `attached ${row.versions.baseline.cold.attached} -> ${row.versions.candidate.cold.attached}; `
      + `map ${row.versions.baseline.profile.bytes} -> ${row.versions.candidate.profile.bytes} bytes`);
  }
  if (baselineTemplate) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh-recovery-benchmark-"));
    const templates = {
      baseline: fs.readFileSync(path.resolve(baselineTemplate), "utf8"),
      candidate: fs.readFileSync(path.join(dev, "skill", "dist", "SHAREABLE.html"), "utf8"),
    };
    result.startupSources = Object.entries(templates).map(([name, source]) =>
      ({ name, sha256: createHash("sha256").update(source).digest("hex") }));
    result.startupMethod = "Genuine baseline and rebuilt candidate Shareable templates, fresh browser contexts, serial alternating order, at most five samples per version and no warmups. Readiness is navigation-to-runtime-ready (performance.now), including parsing and runtime startup. Selector/context seeding is outside timing and uses each actual runtime. Native saved comments have captured context; legacy-context-medium deliberately omits it. Every loaded root and attached highlight is counted. HTTP(S) requests are denied.";
    result.startup = [];
    function html(version, content, comments = []) {
      let text = templates[version]
        .replace(/(<!-- BEGIN: commentable-html - CONTENT[^>]*-->)[\s\S]*?(<!-- END: commentable-html - CONTENT -->)/,
          (_m, a, b) => a + "\n" + content + "\n" + b)
        .replace(/(<script[^>]*\bid="embeddedComments"[^>]*>)[\s\S]*?(<\/script>)/,
          (_m, a, b) => a + JSON.stringify(comments) + b);
      for (const [call, name] of [["cmhReattachComments();", "recovery"],
        ["backfillContext();", "backfill"], ["restoreHighlights();", "highlights"]]) {
        if (text.split(call).length !== 2) throw new Error("Ambiguous startup instrumentation: " + call);
        text = text.replace(call, `const bench_${name} = performance.now(); ${call}
          window.__bench_${name} = performance.now() - bench_${name};`);
      }
      text = text.replace(/window\.__commentableHtmlReady\s*=\s*true;/,
        `window.__commentableHtmlReady = true; window.__bench_ready = performance.now();
        window.__bench_api = {
          seed(quotes, legacy) {
            const index = cmhAnchorIndex();
            const context = !legacy && typeof cmhContextIndex === "function" ? cmhContextIndex() : null;
            return quotes.map((quote, i) => {
              const start = index.text.indexOf(quote);
              if (start < 0) throw new Error("Missing startup seed quote");
              const c = { id: "cbench" + String(i).padStart(6, "0"), quote, start, end: start + quote.length,
                note: "Reviewer question", author: "Benchmark", createdAt: "2025-01-01", updatedAt: "2025-02-01" };
              if (!legacy) Object.assign(c, captureContext(c.start, c.end,
                rangeFromOffsets(c.start, c.end, index.nodes), context));
              index.budget = CMH_ANCHOR_SCAN_BUDGET;
              cmhCaptureTextAnchor(c, index);
              return c;
            });
          },
          state() {
            const roots = comments.filter(cmhIsTextAnchor), attached = roots.filter(c => !cmhIsDetached(c));
            const marks = [...root.querySelectorAll("mark.cm-hl")], ids = new Set(marks.map(m => m.dataset.cid));
            return { roots: roots.length, attached: attached.length, marks: ids.size, markNodes: marks.length,
              missingMarks: attached.filter(c => !ids.has(c.id)).length };
          }
        };`);
      if (!text.includes("window.__bench_api")) throw new Error("Missing runtime readiness hook");
      return text;
    }
    async function open(version, content) {
      const file = path.join(dir, version + ".html");
      fs.writeFileSync(file, content);
      const context = await browser.newContext();
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", error => errors.push(String(error)));
      await page.route(/^https?:\/\//, route => route.abort());
      await page.goto(pathToFileURL(file).href, { waitUntil: "load", timeout: 60000 });
      await page.waitForFunction(() => window.__commentableHtmlReady === true, null, { timeout: 60000 });
      if (errors.length) throw new Error(errors.join("\n"));
      return { context, page };
    }
    try {
      const startupFixtures = fixtures.filter(f => ["unchanged-medium", "unchanged-large", "inserted-large", "mixed-id-large"].includes(f.name))
        .map(f => ({ ...f, quotes: f.name === "unchanged-large" ? f.quotes.slice(0, 100) : f.quotes }));
      startupFixtures.push({ ...fixtures.find(f => f.name === "unchanged-large"), name: "unchanged-large-500" });
      startupFixtures.push({ ...fixtures.find(f => f.name === "unchanged-medium"),
        name: "legacy-context-medium", legacy: true });
      const broad = "<p>A<b>B</b><span class=\"cm-skip\">private</span>C</p>".repeat(5000);
      startupFixtures.push({ name: "broad-highlight-15000", original: broad, revised: broad,
        quotes: ["ABC".repeat(5000)], minMarkNodes: 15000 });
      const selectedStartup = startupFixtures.filter(f => f.name.includes(filter));
      if (startupOnly && !selectedStartup.length) throw new Error("No matching startup fixtures");
      for (const fixture of selectedStartup) {
        const pages = {};
        for (const version of versions) {
          const prepared = await open(version.name, html(version.name, fixture.original));
          const seed = await prepared.page.evaluate(({ quotes, legacy }) => window.__bench_api.seed(quotes, legacy),
            { quotes: fixture.quotes, legacy: !!fixture.legacy });
          await prepared.context.close();
          pages[version.name] = html(version.name, fixture.revised, seed);
        }
        const row = { name: fixture.name, comments: fixture.quotes.length, samples: { baseline: [], candidate: [] } };
        for (let i = 0; i < Math.min(samples, 5); i++) {
          for (const version of i % 2 ? [...versions].reverse() : versions) {
            const run = await open(version.name, pages[version.name]);
            const sample = await run.page.evaluate(() => ({
              ready: window.__bench_ready, recovery: window.__bench_recovery,
              backfill: window.__bench_backfill, highlights: window.__bench_highlights,
              ...window.__bench_api.state(),
            }));
            if (sample.roots !== fixture.quotes.length)
              throw new Error("Startup did not load every fixture comment");
            if (sample.marks !== sample.attached || sample.missingMarks)
              throw new Error("Startup failed to highlight its attached comments");
            if (fixture.minMarkNodes && sample.markNodes < fixture.minMarkNodes)
              throw new Error("Startup did not exercise the broad multi-node highlight");
            row.samples[version.name].push(sample);
            await run.context.close();
          }
        }
        result.startup.push(row);
        fs.writeFileSync(path.resolve(output), JSON.stringify(result, null, 2) + "\n");
        const median = name => row.samples[name].map(s => s.ready).sort((a, b) => a - b)[Math.floor(row.samples[name].length / 2)];
        console.log(`full-startup/${fixture.name}: ${median("baseline").toFixed(2)} -> ${median("candidate").toFixed(2)} ms`);
      }
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  }
} finally {
  await browser.close();
}
