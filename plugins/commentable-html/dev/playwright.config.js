import { defineConfig, devices } from "@playwright/test";

// E2E regression suite for the commentable-html layer. Fixtures are the skill's
// own generated artifacts (TEMPLATE.html, dist/ECONOMY.html), opened over file://
// so the suite matches how users actually open these documents (double-click).
export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  // Cap parallelism: several specs spawn a static server and a synchronous python
  // subprocess (validate.py / mark_handled.py), which thrash the OS at full core
  // count and can time out. A small worker count keeps the suite fast and stable.
  workers: process.env.CI ? 4 : 4,
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
