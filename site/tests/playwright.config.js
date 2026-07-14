const { defineConfig, devices } = require("@playwright/test");

// The suite is hermetic: it serves the static site/ folder locally and (in the
// spec) blocks every non-local host, so it never depends on GitHub, the star
// widget CDN, or the mermaid CDN. It validates the built static output only.
module.exports = defineConfig({
  testDir: "./tests",
  timeout: 30000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4173/",
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    command: "node serve.js",
    url: "http://127.0.0.1:4173/",
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
  },
});
