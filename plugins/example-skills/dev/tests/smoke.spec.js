const { test, expect } = require("@playwright/test");

// Minimal end-to-end check that the CI Playwright pipeline works. Real plugins put their browser
// regression suites here; nothing under dev/ is distributed to users.
test("renders inline content in a browser", async ({ page }) => {
  await page.setContent(
    '<main id="commentRoot"><h1>Hello from urikan-ai-marketplace</h1></main>'
  );
  await expect(page.locator("#commentRoot h1")).toHaveText(
    "Hello from urikan-ai-marketplace"
  );
});
