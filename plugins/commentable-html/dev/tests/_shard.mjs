// Duration-balanced sharding for the `fast` Playwright project.
//
// Playwright's native `--shard=i/N` splits by test COUNT, which piles the few slow specs onto one
// shard (they sorted early and filled the first chunk), so one fast shard ran far longer than the
// rest. Instead the CI `playwright` job passes PLAYWRIGHT_FAST_SHARD=i/N and playwright.config.js
// restricts the `fast` project to the specs this module assigns to shard i by longest-processing-time
// (LPT) bin-packing over committed per-spec timings (tests/spec-timings.json). LPT keeps every shard's
// total run time within ~1% of the others, so the fast job is no longer bottlenecked by one shard, and
// balance is maintained automatically: refresh the timings (npm run shard:timings) after adding or
// materially changing a spec and the assignment rebalances itself. A guard spec
// (00-shard-balance.spec.js) fails if a spec is missing a timing or the packing goes grossly uneven.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { HEAVY_SPEC_FILES } from "./_projects.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const TIMINGS_PATH = path.join(HERE, "spec-timings.json");

// Every fast spec: every *.spec.js under tests/ except the heavy-project specs.
export function discoverFastSpecs(testsDir = HERE) {
  return fs.readdirSync(testsDir)
    .filter((f) => f.endsWith(".spec.js") && !HEAVY_SPEC_FILES.includes(f))
    .sort();
}

export function loadTimings(file = TIMINGS_PATH) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

// Greedy longest-processing-time bin-packing: assign each spec (heaviest first) to the currently
// lightest shard. Deterministic - ties in weight break by filename, ties in shard load by lowest
// index - so the same inputs always yield the same assignment. Returns `total` arrays of spec
// basenames (each array sorted), together covering every input spec exactly once.
export function lptAssign(specs, timings, total) {
  if (!Number.isInteger(total) || total < 1) throw new Error(`shard total must be a positive integer, got ${total}`);
  const shards = Array.from({ length: total }, () => []);
  const load = new Array(total).fill(0);
  const ordered = [...specs].sort((a, b) => (timings[b] ?? 0) - (timings[a] ?? 0) || a.localeCompare(b));
  for (const spec of ordered) {
    let lightest = 0;
    for (let i = 1; i < total; i++) if (load[i] < load[lightest]) lightest = i;
    shards[lightest].push(spec);
    load[lightest] += timings[spec] ?? 0;
  }
  return shards.map((list) => list.sort());
}

// The spec basenames assigned to shard `index` (1-based) of `total`.
export function specsForShard(index, total, specs = discoverFastSpecs(), timings = loadTimings()) {
  if (!Number.isInteger(index) || index < 1 || index > total) {
    throw new Error(`shard index must be in 1..${total}, got ${index}`);
  }
  return lptAssign(specs, timings, total)[index - 1];
}

// Parse a "i/N" shard string (e.g. from PLAYWRIGHT_FAST_SHARD); returns null for unset/blank.
export function parseShardEnv(value) {
  if (!value || !value.trim()) return null;
  const m = /^(\d+)\/(\d+)$/.exec(value.trim());
  if (!m) throw new Error(`shard spec must look like "i/N", got ${JSON.stringify(value)}`);
  const index = Number(m[1]);
  const total = Number(m[2]);
  if (index < 1 || total < 1 || index > total) throw new Error(`shard spec out of range: ${value}`);
  return { index, total };
}
