import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { HEAVY_SPEC_FILES } from "./_projects.mjs";
import { discoverFastSpecs, loadTimings, lptAssign } from "./_shard.mjs";

const TESTS_DIR = path.dirname(fileURLToPath(import.meta.url));

// The fast/heavy Playwright project split (playwright.config.js) routes specs by filename: the
// `heavy` project is exactly HEAVY_SPEC_FILES, the `fast` project is everything else. The two are
// complements, so every spec runs in exactly one project - EXCEPT that a typo in HEAVY_SPEC_FILES
// (a name matching no file) would make the heavy CI job silently run zero tutorial-shots tests while
// that spec quietly ran in the fast project (where its subprocess-browser thrashes). Guard against
// that: every heavy entry must resolve to a real, unique tests/*.spec.js file.
test("every heavy-project spec name resolves to a real, unique spec file (CMH-BUILD-12)", () => {
  const allSpecs = fs.readdirSync(TESTS_DIR).filter((f) => f.endsWith(".spec.js"));
  expect(HEAVY_SPEC_FILES.length, "expected at least one heavy spec").toBeGreaterThan(0);
  for (const name of HEAVY_SPEC_FILES) {
    expect(allSpecs, `heavy spec '${name}' is not an existing tests/*.spec.js file`).toContain(name);
  }
  expect(new Set(HEAVY_SPEC_FILES).size, "duplicate entry in HEAVY_SPEC_FILES").toBe(HEAVY_SPEC_FILES.length);
});

// The `fast` project is sharded by duration (tests/_shard.mjs LPT bin-packing over
// tests/spec-timings.json), not by Playwright's count-based --shard. Three failure modes would
// silently unbalance or drop coverage, so guard all three: (1) every fast spec must live DIRECTLY
// under tests/ (the flat convention) - a spec nested in a subdirectory would be run unsharded by
// Playwright's recursive discovery but omitted from every shard, since sharding keys by basename;
// (2) the committed timings must list exactly the fast specs (a spec with no timing gets weight 0
// and packs blind; an orphan timing means a deleted spec) - refresh with `npm run shard:timings`;
// (3) for every plausible shard count the LPT partition must cover every fast spec exactly once AND
// stay near-balanced (a single spec too slow to fit a shard's fair share trips this, signalling it
// should be split like the triage screenshot test was).
test("fast-project spec timings are complete and shard-balanced (CMH-BUILD-13)", () => {
  const nested = fs.readdirSync(TESTS_DIR, { recursive: true })
    .map((f) => String(f).split(path.sep).join("/"))
    .filter((f) => f.endsWith(".spec.js") && f.includes("/"));
  expect(nested, "duration sharding requires flat tests/*.spec.js - move these up, or extend tests/_shard.mjs to key specs by their path relative to tests/").toEqual([]);

  const specs = discoverFastSpecs(TESTS_DIR);
  const timings = loadTimings();
  const missing = specs.filter((s) => !(s in timings));
  const orphan = Object.keys(timings).filter((k) => !specs.includes(k));
  expect(missing, `specs missing a timing (run 'npm run shard:timings'): ${missing.join(", ")}`).toEqual([]);
  expect(orphan, `orphan timings for deleted specs (run 'npm run shard:timings'): ${orphan.join(", ")}`).toEqual([]);

  const total = specs.reduce((a, s) => a + (timings[s] || 0), 0);
  for (let n = 4; n <= 8; n++) {
    const shards = lptAssign(specs, timings, n);
    const covered = shards.flat();
    expect(new Set(covered).size, `shard partition (N=${n}) does not cover every fast spec once`).toBe(specs.length);
    expect(covered.length, `shard partition (N=${n}) duplicated a spec`).toBe(specs.length);
    const loads = shards.map((sh) => sh.reduce((a, s) => a + (timings[s] || 0), 0));
    const ideal = total / n;
    // Worst shard within 1.5x of a perfectly even split. LPT holds this comfortably unless one spec
    // alone exceeds ~1.5x the fair share, which is the signal to split that spec.
    expect(Math.max(...loads) / ideal, `shard load imbalance at N=${n} (a spec may be too slow to balance - split it)`).toBeLessThanOrEqual(1.5);
  }
});

// Unit coverage for the pure LPT packer, independent of the real specs/timings: it must lose or
// duplicate nothing, be deterministic (same inputs -> same output, so CI shards never disagree on who
// runs a spec), and greedily keep the heaviest items apart.
test("LPT shard assignment is deterministic and lossless (CMH-BUILD-13)", () => {
  const specs = ["a", "b", "c", "d", "e"];
  const timings = { a: 100, b: 90, c: 80, d: 20, e: 10 };
  const first = lptAssign(specs, timings, 3);
  expect(first.flat().sort()).toEqual([...specs].sort());
  expect(new Set(first.flat()).size).toBe(specs.length);
  // Deterministic: re-running (and shuffling the input order) yields the identical partition.
  expect(lptAssign([...specs].reverse(), timings, 3)).toEqual(first);
  // The three heaviest (a,b,c) each land on their own shard (LPT seeds the empty bins by size),
  // and the small items top the shards up to a perfectly even 100 each.
  const loads = first.map((sh) => sh.reduce((t, s) => t + timings[s], 0)).sort((x, y) => x - y);
  expect(loads).toEqual([100, 100, 100]);
  // A spec with no timing is still placed (weight 0), never dropped.
  const withUntimed = lptAssign([...specs, "z"], timings, 3);
  expect(withUntimed.flat()).toContain("z");
  expect(withUntimed.flat().length).toBe(specs.length + 1);
  // A single shard gets everything; a bad total is rejected.
  expect(lptAssign(specs, timings, 1)).toEqual([[...specs].sort()]);
  expect(() => lptAssign(specs, timings, 0)).toThrow();
});
