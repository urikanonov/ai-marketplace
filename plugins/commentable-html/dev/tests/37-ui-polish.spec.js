// UI polish batch: language pills on code blocks, the diff toggle's action-labelled
// button, the "Help & About" buttons, the default-open review-workflow help topic, and
// click-to-expand on a collapsed section title.
import { test, expect } from "@playwright/test";
import { openInline, openNonPortable } from "./helpers.js";

test("code blocks show a language pill beside the Copy button (CMH-CODEPILL-01)", async ({ page }) => {
  await openInline(page);
  // The demo ships a python code block and a kusto (KQL) block; each pill reads its language.
  await expect(page.locator(".cm-code-lang", { hasText: "Python" })).toHaveCount(1);
  await expect(page.locator(".cm-code-lang", { hasText: "KQL" })).toHaveCount(1);
  // The pill and the Copy button share one tools container.
  const tools = page.locator(".cm-code-tools").first();
  await expect(tools.locator(".cm-code-lang")).toHaveCount(1);
  await expect(tools.locator(".cm-code-copy")).toHaveCount(1);
});

test("the diff toggle button label names the action it performs (CMH-DIFF-LABEL-01)", async ({ page }) => {
  await openInline(page);
  // Diffs default to side-by-side, so the toggle offers to switch TO inline.
  const toggle = page.locator(".cmh-diff-toggle").first();
  await expect(toggle).toHaveText("To inline view");
  await toggle.click();
  await expect(toggle).toHaveText("To side-by-side view");
});

test("the help buttons are labelled Help & About (CMH-HELP-LABEL-01)", async ({ page }) => {
  await openInline(page);
  for (const id of ["btnHelp", "btnHelpTop"]) {
    const txt = await page.locator("#" + id).evaluate((el) => el.textContent.trim());
    expect(txt, id + " label").toBe("Help & About");
  }
});

test("help opens with the 4-step review workflow in the Getting started topic (CMH-WF-HELP-01)", async ({ page }) => {
  await openInline(page);
  await page.locator("#btnHelp").evaluate((el) => el.click());
  const help = page.locator(".cm-help");
  await expect(help).toBeVisible();
  const first = help.locator("details.cm-help-topic").first();
  await expect(first.locator("summary")).toHaveText(/Getting started/);
  await expect(first).toHaveAttribute("open", "");
  for (const step of [/Generate/, /Review/, /Hand back/, /Refresh and repeat/]) {
    await expect(first).toContainText(step);
  }
  // The review-loop diagram is embedded below the steps.
  await expect(first.locator(".cm-loop-figure svg")).toHaveCount(1);
});

test("clicking a collapsed section title expands it (CMH-SECEXPAND-01)", async ({ page }) => {
  await openInline(page);
  const section = page.locator("section:has(> h2#callouts)");
  await section.locator(".cmh-sec-caret").first().click(); // collapse
  await expect(section).toHaveClass(/cmh-section-collapsed/);
  await page.locator("h2#callouts").click(); // plain click on the title expands it
  await expect(section).not.toHaveClass(/cmh-section-collapsed/);
});

test("a Portable doc-type badge is green (CMH-BADGE-COLOR-01)", async ({ page }) => {
  await openInline(page);
  const badge = page.locator("#cmTypeBadge");
  await expect(badge).toHaveAttribute("data-doc-type", "Portable");
  const c = (await badge.evaluate((el) => getComputedStyle(el).color)).match(/\d+/g).map(Number);
  expect(c[1], "green channel dominates").toBeGreaterThan(c[0]);
  expect(c[1]).toBeGreaterThan(c[2]);
});

test("a Not-portable badge is orange and its tooltip says how to share (CMH-BADGE-COLOR-01)", async ({ page }) => {
  await openNonPortable(page);
  const badge = page.locator("#cmTypeBadge");
  await expect(badge).toHaveAttribute("data-doc-type", "Not portable");
  const title = await badge.getAttribute("title");
  expect(title).toMatch(/Export as Portable/);
  expect(title).toMatch(/to share it/);
  const c = (await badge.evaluate((el) => getComputedStyle(el).color)).match(/\d+/g).map(Number);
  // Orange: red and green both well above blue, red at or above green.
  expect(c[0], "red above blue").toBeGreaterThan(c[2]);
  expect(c[1], "green above blue").toBeGreaterThan(c[2]);
  expect(c[0], "red at or above green").toBeGreaterThanOrEqual(c[1]);
});
