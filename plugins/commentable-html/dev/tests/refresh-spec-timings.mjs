#!/usr/bin/env node
// Regenerate tests/spec-timings.json from a fresh `fast` project run so the duration-balanced
// sharding (tests/_shard.mjs) stays accurate. Run after adding or materially changing a fast spec:
//
//   npm run shard:timings
//
// It runs the whole `fast` project once (unsharded) with the JSON reporter, sums each spec file's
// test durations, and rewrites the committed timings. Balance is otherwise self-maintaining - the
// CMH-BUILD-13 guard fails if a spec is missing a timing, which is the reminder to run this.
import { spawnSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";
import { fileURLToPath } from "url";
import { TIMINGS_PATH } from "./_shard.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DEV = path.resolve(HERE, "..");
const jsonOut = path.join(os.tmpdir(), `cmh-fast-timings-${process.pid}.json`);
// Clear any stale report at this path (e.g. left by a prior crashed run whose PID was reused) so a
// missing fresh report is never mistaken for a successful one.
fs.rmSync(jsonOut, { force: true });

// Run the full fast project (PLAYWRIGHT_FAST_SHARD unset => all specs) SERIALLY (--workers=1) with
// the JSON reporter, so each spec's recorded time is its true single-worker cost, not a
// contention-inflated parallel time. LPT balances the sum of these per shard.
const run = spawnSync("npx", ["playwright", "test", "--project=fast", "--workers=1", "--reporter=list,json"], {
  cwd: DEV,
  encoding: "utf8",
  stdio: ["ignore", "inherit", "inherit"],
  env: { ...process.env, PLAYWRIGHT_JSON_OUTPUT_NAME: jsonOut, PLAYWRIGHT_FAST_SHARD: "" },
  shell: process.platform === "win32",
});
if (run.error) {
  console.error(`refresh-spec-timings: could not launch Playwright: ${run.error.message}`);
  process.exit(1);
}
if (!fs.existsSync(jsonOut)) {
  console.error("refresh-spec-timings: no JSON report was produced; did the suite run?");
  process.exit(1);
}
const report = JSON.parse(fs.readFileSync(jsonOut, "utf8"));
fs.rmSync(jsonOut, { force: true });

const agg = {};
const walk = (suite) => {
  for (const child of suite.suites || []) walk(child);
  for (const spec of suite.specs || []) {
    const file = path.basename(suite.file || spec.file || "?");
    for (const t of spec.tests || []) {
      // A test may have several results (retries); count only the last attempt, not the sum, so a
      // retried test does not double-count into its spec's weight.
      const attempts = t.results || [];
      const last = attempts.length ? attempts[attempts.length - 1] : null;
      agg[file] = (agg[file] || 0) + ((last && last.duration) || 0);
    }
  }
};
for (const s of report.suites || []) walk(s);

const names = Object.keys(agg).sort();
if (!names.length) {
  console.error("refresh-spec-timings: the report contained no specs; refusing to write an empty file.");
  process.exit(1);
}
const body = names.map((n, i) => `  ${JSON.stringify(n)}: ${Math.round(agg[n])}${i < names.length - 1 ? "," : ""}`);
fs.writeFileSync(TIMINGS_PATH, `{\n${body.join("\n")}\n}\n`);
console.log(`refresh-spec-timings: wrote ${names.length} spec timings to ${path.relative(DEV, TIMINGS_PATH)}`);
// Surface a failing/partial run: the timings are still written (writing them is the fix for a
// brand-new untimed spec that trips the CMH-BUILD-13 guard), but a genuine spec failure must not
// look like success, so propagate the suite's exit status.
if (run.status !== 0) {
  console.error(`refresh-spec-timings: the fast suite exited ${run.status} (some specs failed); timings were written, but re-check the failures.`);
}
process.exit(run.status ?? 1);
