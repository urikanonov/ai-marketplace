// Real-parser oracle (DEV ONLY - never shipped). Loads the SAME mermaid and
// Chart.js versions the runtime uses, in a real Chromium page, and validates
// every mermaid diagram and Chart.js config in a commentable-html document with
// the authoritative parsers. This is the maximal-fidelity gate that the CI
// `plugin-tests` job runs over the shipped example reports, and the tool that
// (re)labels the differential corpus the shipped Python checker is calibrated
// against.
//
// Usage:
//   node tools/validate_render.mjs <file.html> [more.html ...]   # validate files
//   node tools/validate_render.mjs --corpus tests/fixtures/mermaid-corpus.json
//
// Exit code 0 when everything the oracle parsed is valid, 1 on any parse error,
// 2 on a usage error.

import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { extractMermaid, extractCharts } from "./diagram_extract.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const NM = path.join(__dirname, "..", "node_modules");
const MERMAID_JS = fs.readFileSync(path.join(NM, "mermaid", "dist", "mermaid.min.js"), "utf8");
const CHART_JS = fs.readFileSync(path.join(NM, "chart.js", "dist", "chart.umd.js"), "utf8");

async function makeValidator() {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.on("console", () => {}); // swallow Chart.js/mermaid console noise
  await page.setContent("<!doctype html><html><body></body></html>");
  await page.addScriptTag({ content: MERMAID_JS });
  await page.addScriptTag({ content: CHART_JS });
  await page.evaluate(() => window.mermaid.initialize({ startOnLoad: false, securityLevel: "loose" }));

  return {
    async mermaid(src) {
      return page.evaluate(async (s) => {
        try { await window.mermaid.parse(s); return { ok: true }; }
        catch (e) { return { ok: false, error: String((e && e.message) || e) }; }
      }, src);
    },
    async chart(text) {
      return page.evaluate((t) => {
        let cfg;
        try { cfg = JSON.parse(t); }
        catch (e) { return { ok: false, error: "invalid JSON: " + e.message }; }
        if (!cfg || typeof cfg !== "object" || typeof cfg.type !== "string" || !("data" in cfg)) {
          // Not a full Chart.js config (a bare data array, or unrelated JSON that
          // merely has a "type" field) - JSON validity is all the oracle asserts.
          return { ok: true, note: "not-a-chart-config" };
        }
        // Chart.js does NOT throw for an unknown type in the constructor (it fails
        // silently at render), so check the controller registry explicitly.
        let ctrl = null;
        try { ctrl = window.Chart.registry.getController(cfg.type); } catch (e) { ctrl = null; }
        if (!ctrl) {
          return { ok: false, error: `unknown chart type "${cfg.type}" (not a registered Chart.js controller)` };
        }
        const cv = document.createElement("canvas");
        cv.width = 300; cv.height = 200;
        document.body.appendChild(cv);
        try {
          const ch = new window.Chart(cv, cfg);
          ch.destroy();
          return { ok: true };
        } catch (e) {
          return { ok: false, error: String((e && e.message) || e) };
        } finally {
          cv.remove();
        }
      }, text);
    },
    async close() { await browser.close(); },
  };
}

async function validateFiles(files, v) {
  let errors = 0;
  for (const file of files) {
    const html = fs.readFileSync(file, "utf8");
    const diagrams = extractMermaid(html);
    const charts = extractCharts(html);
    const findings = [];
    for (const d of diagrams) {
      const r = await v.mermaid(d.src);
      if (!r.ok) findings.push(`mermaid diagram #${d.index}: ${r.error.split("\n").join(" ")}`);
    }
    for (const c of charts) {
      const r = await v.chart(c.text);
      if (!r.ok) findings.push(`chart ${c.id ? `#${c.id}` : `#${c.index}`}: ${r.error}`);
    }
    console.log(`oracle: ${file}  (${diagrams.length} mermaid, ${charts.length} chart)`);
    for (const f of findings) console.log(`  ERROR: ${f}`);
    errors += findings.length;
  }
  return errors;
}

async function runCorpus(corpusPath, v) {
  const corpus = JSON.parse(fs.readFileSync(corpusPath, "utf8"));
  let mismatches = 0;
  for (const entry of corpus) {
    const kind = entry.kind || "mermaid";
    const r = kind === "chart" ? await v.chart(entry.src) : await v.mermaid(entry.src);
    // Each corpus entry declares an expected `valid` (the real-parser verdict).
    // The oracle re-verifies it so a stale label fails CI instead of silently
    // weakening the differential test.
    if (typeof entry.valid === "boolean" && entry.valid !== r.ok) {
      mismatches++;
      console.log(`  LABEL MISMATCH [${entry.name}]: corpus says valid=${entry.valid}, real parser says ok=${r.ok}`);
      if (!r.ok) console.log(`    parser: ${(r.error || "").split("\n")[0]}`);
    }
  }
  if (mismatches === 0) console.log(`oracle: corpus labels verified (${corpus.length} entries) - all match the real parser`);
  return mismatches;
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv.length === 0 || argv.includes("-h") || argv.includes("--help")) {
    console.log("usage: node tools/validate_render.mjs <file.html ...> | --corpus <corpus.json>");
    return argv.length === 0 ? 2 : 0;
  }
  const v = await makeValidator();
  try {
    if (argv[0] === "--corpus") {
      if (!argv[1]) { console.error("--corpus needs a path"); return 2; }
      return (await runCorpus(argv[1], v)) === 0 ? 0 : 1;
    }
    return (await validateFiles(argv, v)) === 0 ? 0 : 1;
  } finally {
    await v.close();
  }
}

export { makeValidator, validateFiles, runCorpus };

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(await main());
}
