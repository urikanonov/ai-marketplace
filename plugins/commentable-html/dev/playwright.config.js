import { defineConfig, devices } from "@playwright/test";

// E2E regression suite for the commentable-html layer. Fixtures are the skill's
// own generated artifacts (dist/PORTABLE.html, dist/NONPORTABLE.html), opened over file://
// so the suite matches how users actually open these documents (double-click).
export default defineConfig({
  testDir: "./tests",
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
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
