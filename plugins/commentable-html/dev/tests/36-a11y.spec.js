import { test, expect } from "@playwright/test";
import { openInline, ready, fileUrl, INLINE, addTextComment } from "./helpers.js";

// Accessibility + honesty of runtime feedback: toasts are announced to screen readers,
// and Copy all never claims success when it actually fell back to a manual prompt.

test("toasts carry a live-region role so screen readers announce them", async ({ page }) => {
  await openInline(page);
  await addTextComment(page, "#commentRoot p", "announce me");
  await page.click("#btnCopyAll").catch(() => {});
  const toast = page.locator("#toast");
  await expect(toast).toHaveAttribute("role", /status|alert/);
  await expect(toast).toHaveAttribute("aria-live", /polite|assertive/);
});

test("Copy all does NOT claim success when it falls back to a manual prompt", async ({ page }) => {
  await page.addInitScript(() => {
    try {
      Object.defineProperty(navigator, "clipboard", {
        value: { writeText: () => Promise.reject(new Error("blocked")) }, configurable: true,
      });
    } catch (e) {}
    document.execCommand = () => false;   // execCommand copy fails too
    window.prompt = () => null;           // the reviewer cancels the manual prompt
  });
  await page.goto(fileUrl(INLINE));
  await ready(page);
  await addTextComment(page, "#commentRoot p", "no false success");
  await page.click("#btnCopyAll");
  const txt = (await page.locator("#toast").textContent()) || "";
  expect(txt).not.toMatch(/Copied \d+ comment/); // must not lie about success
  expect(txt).toMatch(/blocked|manual/i);        // tells the reviewer what actually happened
  await expect(page.locator("#toast")).toHaveAttribute("role", "alert");
});
