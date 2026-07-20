// Single source of truth for which specs are "heavy" (they spawn browser-launching subprocesses
// like capture_tutorial.mjs and cannot parallelize past a few concurrent browsers without OS
// thrash). The Playwright config routes these into the `heavy` project (its own CI job, few
// workers) and everything else into the `fast` project (sharded across runners at workers=4), so
// one serial screenshot block no longer gates a shard. A guard spec imports this list and asserts
// every spec file lands in exactly one project, so the split can never silently drop coverage.
export const HEAVY_SPEC_FILES = ["54-tutorial-shots.spec.js"];

export const heavyGlobs = HEAVY_SPEC_FILES.map((f) => `**/${f}`);
