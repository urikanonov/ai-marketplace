// CMH-SYN-04 / CMH-SYN-05: the repo-side real-parser oracle gate.
//
// The real mermaid + Chart.js run in a headless browser that the standalone node
// tools launch themselves (dev/tools/validate_render.mjs and the corpus
// generator). Launching a browser from INSIDE the @playwright/test worker
// deadlocks, so this spec shells out to those standalone tools and asserts they
// exit clean - the tools own the browser, the test owns the assertion.
//
//   - validate_render.mjs validates every mermaid diagram + Chart.js config in the
//     shipped example reports with the real libraries (exit != 0 on any error).
//   - build_mermaid_corpus.mjs --check regenerates the differential corpus labels
//     from the REAL parser and the REAL Python checker and fails on any false
//     positive (the checker flags a parser-valid diagram) or label drift.

import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";
import { SKILL, DEV } from "./helpers.js";

function runNode(args, timeoutMs) {
  try {
    return execFileSync("node", args, { cwd: DEV, stdio: "pipe", timeout: timeoutMs, encoding: "utf8" });
  } catch (e) {
    const out = `${e.stdout || ""}\n${e.stderr || ""}`.trim();
    throw new Error(`node ${args.join(" ")} failed:\n${out || e.message}`);
  }
}

const exampleFiles = fs
  .readdirSync(path.join(SKILL, "examples"))
  .filter((f) => f.endsWith(".html"))
  .sort()
  .map((f) => path.join(SKILL, "examples", f));

test("CMH-SYN-04: every mermaid diagram and chart in the shipped example reports parses with the real parser", () => {
  test.setTimeout(120000);
  // validate_render.mjs launches its own headless browser and exits non-zero on
  // any real-parser error in a shipped example report.
  const out = runNode([path.join(DEV, "tools", "validate_render.mjs"), ...exampleFiles], 110000);
  expect(out).toContain("oracle:");
});

test("CMH-SYN-05: the differential corpus is in sync with the real parser and Python checker (no false positives)", () => {
  test.setTimeout(180000);
  // Regenerates every label from the REAL mermaid parser and the REAL Python
  // checker; --check fails on any false positive or drift versus the committed file.
  const out = runNode([path.join(DEV, "tests", "fixtures", "build_mermaid_corpus.mjs"), "--check"], 170000);
  expect(out).toContain("up to date");
});
