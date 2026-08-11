import { test, expect } from "@playwright/test";
import fs from "fs";
import os from "os";
import path from "path";
import { DIST, EXAMPLES, fileUrl, ready, denyExternalNetwork, openInline, openNonShareable } from "./helpers.js";

// CMH-SIZE-05/04: the authored content now comes FIRST in source order and every generated
// machinery block - the layer stylesheet included - follows it. These specs pin the part a text
// assertion cannot see: the document still paints correctly, nothing is left hidden by the
// first-paint guard, and the layer boots with its stylesheet applied.

function strippedRuntime(html) {
  // Everything from the JS region's opening comment through its END marker. The runtime quotes the
  // marker text in its own strings, so the REAL end is the LAST occurrence (a documented footgun).
  const begin = html.indexOf("BEGIN: commentable-html - JS");
  const open = html.lastIndexOf("<!--", begin);
  const end = html.lastIndexOf("END: commentable-html - JS");
  const close = html.indexOf("-->", end);
  expect(begin).toBeGreaterThan(-1);
  expect(open).toBeGreaterThan(-1);
  expect(close).toBeGreaterThan(end);
  return html.slice(0, open) + html.slice(close + 3);
}

test.describe("content-first document layout", () => {
  test("CMH-SIZE-07: the shareable template paints styled, with nothing left hidden", async ({ page }) => {
    await openInline(page);
    // The guard class is removed the moment the trailing stylesheet is parsed, so by the time the
    // layer is ready the document is visible - not left blank by a guard that never cleared.
    await expect(page.locator("html")).not.toHaveClass(/cmh-awaiting-style/);
    await expect(page.locator("#commentRoot h1").first()).toBeVisible();
    // The layer stylesheet really is in force (it comes after the content now): the comments
    // sidebar is a fixed-position panel, which only the layer CSS makes it.
    const position = await page.evaluate(() =>
      getComputedStyle(document.querySelector(".cm-sidebar")).position);
    expect(position).toBe("fixed");
  });

  test("CMH-SIZE-07: the reveal survives a document whose runtime never runs", async ({ page }) => {
    // A broken or absent runtime must not leave the reader with a blank page: the reveal script
    // sits with the stylesheet, ahead of the runtime, and the guard also clears on DOMContentLoaded.
    const html = fs.readFileSync(path.join(DIST, "SHAREABLE.html"), "utf8");
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh-firstpaint-"));
    const file = path.join(dir, "no-runtime.html");
    fs.writeFileSync(file, strippedRuntime(html), "utf8");
    try {
      await page.goto(fileUrl(file));
      await expect(page.locator("#commentRoot h1").first()).toBeVisible();
      await expect(page.locator("html")).not.toHaveClass(/cmh-awaiting-style/);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-SIZE-05: the nonshareable template still loads its companion stylesheet", async ({ page }) => {
    // The companion <link> moved out of <head> and into the machinery fence. A pending stylesheet
    // blocks the scripts that follow it, so the reveal still waits for the CSS to load.
    await openNonShareable(page);
    await expect(page.locator("html")).not.toHaveClass(/cmh-awaiting-style/);
    const position = await page.evaluate(() =>
      getComputedStyle(document.querySelector(".cm-sidebar")).position);
    expect(position).toBe("fixed");
    await expect(page.locator("#cmhAssetBanner")).toBeHidden();
  });

  test("CMH-SIZE-05: a shipped example opens with zero network and its content first", async ({ page }) => {
    await denyExternalNetwork(page);
    const file = path.join(EXAMPLES, "report-triage.html");
    const html = fs.readFileSync(file, "utf8");
    expect(html.indexOf("BEGIN: commentable-html - CONTENT"))
      .toBeLessThan(html.indexOf("BEGIN: commentable-html - MACHINERY"));
    await page.goto(fileUrl(file));
    await ready(page);
    await expect(page.locator("html")).not.toHaveClass(/cmh-awaiting-style/);
    await expect(page.locator("#commentRoot h1").first()).toBeVisible();
  });
});
