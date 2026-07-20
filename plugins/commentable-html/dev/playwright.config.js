import { defineConfig, devices } from "@playwright/test";
import { heavyGlobs } from "./tests/_projects.mjs";

// E2E regression suite for the commentable-html layer. Fixtures are the skill's
// own generated artifacts (dist/PORTABLE.html, dist/NONPORTABLE.html), opened over file://
// so the suite matches how users actually open these documents (double-click).
export default defineConfig({
  testDir: "./tests",
  // Prune the per-process capture scratch trees under repo-root tmp/ once, after every test
  // completes (race-free, unlike a per-worker afterAll wiping a shared parent).
  globalTeardown: "./tests/_teardown.mjs",
  fullyParallel: true,
  // Cap parallelism on CI (shared runners thrash the OS at full core count when several
  // specs spawn a static server plus a synchronous python subprocess and can time out).
  // Locally, let Playwright pick the worker count from available cores for a faster run.
  workers: process.env.CI ? 4 : undefined,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    acceptDownloads: true,
    permissions: ["clipboard-read", "clipboard-write"],
    colorScheme: "light",
    trace: "on-first-retry",
  },
  // Two projects so CI can run them as independent parallel jobs. `fast` (sharded across runners)
  // is everything except the heavy browser-subprocess specs; `heavy` is only those, run in its own
  // job with a small worker count (CLI --workers) so its concurrent capture subprocesses do not
  // thrash the runner. Splitting them stops one serial screenshot block from gating a whole shard.
  projects: [
    { name: "fast", testIgnore: heavyGlobs, use: { ...devices["Desktop Chrome"] } },
    { name: "heavy", testMatch: heavyGlobs, use: { ...devices["Desktop Chrome"] } },
  ],
});
