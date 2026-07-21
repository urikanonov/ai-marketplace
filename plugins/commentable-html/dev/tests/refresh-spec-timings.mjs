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

// Run the full fast project (PLAYWRIGHT_FAST_SHARD unset => all specs) with the JSON reporter.
const run = spawnSync("npx", ["playwright", "test", "--project=fast", "--reporter=json"], {
  cwd: DEV,
  encoding: "utf8",
  stdio: ["ignore", "ignore", "inherit"],
  env: { ...process.env, PLAYWRIGHT_JSON_OUTPUT_NAME: jsonOut, PLAYWRIGHT_FAST_SHARD: "" },
  shell: process.platform === "win32",
});
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
    for (const t of spec.tests || []) for (const res of t.results || []) {
      agg[file] = (agg[file] || 0) + (res.duration || 0);
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
// A non-zero playwright exit (a spec failed - e.g. the guard tripping on a brand-new untimed spec)
// still yields usable timings; surface it but do not fail, since writing the timings is the fix.
if (run.status !== 0) {
  console.error(`refresh-spec-timings: note - the fast suite exited ${run.status} (some specs failed); timings were still written.`);
}
