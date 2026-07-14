// CMH-SYN-04 / CMH-SYN-05: the repo-side real-parser oracle.
//
// This is the maximal-fidelity gate the user asked for: every mermaid diagram
// and Chart.js config in the SHIPPED example reports is parsed by the REAL
// mermaid and Chart.js (the same versions the runtime loads), so the repo can
// never ship a diagram or chart that renders as mermaid's "Syntax error" bomb.
// It also re-verifies the differential corpus labels against the real parser so
// the shipped Python checker's zero-false-positive guarantee can never rest on a
// stale label.
//
// The oracle injects mermaid/Chart.js from local node_modules and parses in a
// real Chromium page; it reaches no network.

import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { SKILL, FIXTURES } from "./helpers.js";
import { makeValidator } from "../tools/validate_render.mjs";
import { extractMermaid, extractCharts } from "../tools/diagram_extract.mjs";

let oracle;

test.beforeAll(async () => { oracle = await makeValidator(); });
test.afterAll(async () => { if (oracle) await oracle.close(); });

const EXAMPLES = path.join(SKILL, "examples");
const exampleFiles = fs
  .readdirSync(EXAMPLES)
  .filter((f) => f.endsWith(".html"))
  .sort()
  .map((f) => path.join(EXAMPLES, f));

test("CMH-SYN-04: every mermaid diagram and chart in the shipped example reports parses with the real parser", async () => {
  const findings = [];
  for (const file of exampleFiles) {
    const html = fs.readFileSync(file, "utf8");
    for (const d of extractMermaid(html)) {
      const r = await oracle.mermaid(d.src);
      if (!r.ok) findings.push(`${path.basename(file)} mermaid #${d.index}: ${r.error.split("\n")[0]}`);
    }
    for (const c of extractCharts(html)) {
      const r = await oracle.chart(c.text);
      if (!r.ok) findings.push(`${path.basename(file)} chart ${c.id || `#${c.index}`}: ${r.error}`);
    }
  }
  expect(findings.length, findings.join("\n")).toBe(0);
});

test("CMH-SYN-04: the oracle catches the semicolon-splits-a-message bug (and accepts the valid twin)", async () => {
  const good = await oracle.mermaid("sequenceDiagram\n  A->>B: hi; C->>D: bye");
  expect(good.ok).toBe(true);
  const bad = await oracle.mermaid("sequenceDiagram\n  A->>B: validate; map X -> Y CLR type(s)");
  expect(bad.ok).toBe(false);
});

test("CMH-SYN-04: the oracle rejects an unknown Chart.js type", async () => {
  const ok = await oracle.chart('{"type":"bar","data":{"labels":["a"],"datasets":[{"data":[1]}]}}');
  expect(ok.ok).toBe(true);
  const bad = await oracle.chart('{"type":"definitely-not-a-chart","data":{"labels":[],"datasets":[]}}');
  expect(bad.ok).toBe(false);
});

test("CMH-SYN-05: the differential corpus labels match the real parser (no stale labels)", async () => {
  const corpus = JSON.parse(fs.readFileSync(path.join(FIXTURES, "mermaid-corpus.json"), "utf8"));
  expect(corpus.length).toBeGreaterThanOrEqual(40);
  const mismatches = [];
  for (const e of corpus) {
    const r = e.kind === "chart" ? await oracle.chart(e.src) : await oracle.mermaid(e.src);
    if (r.ok !== e.valid) {
      mismatches.push(`${e.name}: corpus valid=${e.valid} but real parser ok=${r.ok}`);
    }
    // A py_flag entry must be genuinely invalid, or the Python checker would be a
    // false positive.
    if (e.py_flag && r.ok) mismatches.push(`${e.name}: py_flag but the real parser accepts it`);
  }
  expect(mismatches.length, mismatches.join("\n")).toBe(0);
});
