import { test, expect } from "@playwright/test";
import fs from "fs";
import os from "os";
import path from "path";
import {
  openInline, ready, fileUrl, lastCopied, addTextComment, readDownload, installClipboardCapture,
} from "./helpers.js";

test.describe("UI batch 3: collapsible sections, portable-stale, KQL title copy, chart box", () => {
  test("sections are collapsible; Expand All / Collapse All toggle every section", async ({ page }) => {
    await page.setViewportSize({ width: 1500, height: 900 });
    await openInline(page);
    const sec = page.locator("#commentRoot section:has(.cmh-sec-caret)").first();
    const caret = sec.locator(".cmh-sec-caret").first();
    const body = sec.locator("p").first();
    await expect(body).toBeVisible();
    await caret.click();
    await expect(sec).toHaveClass(/cmh-section-collapsed/);
    await expect(body).toBeHidden();
    await caret.click();
    await expect(body).toBeVisible();
    // Collapse All / Expand All from the side TOC.
    await page.locator("#cmSideToc .cm-side-toc-top", { hasText: "Collapse All" }).click();
    expect(await page.locator("#commentRoot section.cmh-section-collapsed").count()).toBeGreaterThan(1);
    await page.locator("#cmSideToc .cm-side-toc-top", { hasText: "Expand All" }).click();
    expect(await page.locator("#commentRoot section.cmh-section-collapsed").count()).toBe(0);
  });

  test("the section caret does not carry into the heading text or offsets", async ({ page }) => {
    await openInline(page);
    // The caret is text-free (pseudo-element glyph), so the heading's textContent is clean.
    const txt = await page.locator("#commentRoot h2.cmh-section-heading").first().evaluate((h) => h.textContent.trim());
    expect(txt).not.toMatch(/[\u25B8\u25BE]/);
  });

  test("the KQL caption title copies the cluster name", async ({ page }) => {
    await openInline(page);
    const title = page.locator(".cmh-kql-title").first();
    await expect(title).toBeVisible();
    await expect(title).toHaveAttribute("data-cmh-copy", "help.kusto.windows.net");
    await title.click();
    expect(await lastCopied(page)).toBe("help.kusto.windows.net");
    // There is no separate middle chip anymore.
    await expect(page.locator(".cmh-kql-cap .cmh-kql-cluster:not(.cmh-kql-title)")).toHaveCount(0);
  });

  test("chart figures are boxed", async ({ page }) => {
    await openInline(page);
    const fig = page.locator("#commentRoot figure.chart").first();
    const border = await fig.evaluate((el) => getComputedStyle(el).borderTopWidth);
    expect(parseFloat(border)).toBeGreaterThan(0);
  });

  test("the diff Syntax toggle is green when on and red when off", async ({ page }) => {
    await openInline(page);
    const t = page.locator(".cmh-diff-hltoggle").first();
    await expect(t).toHaveText("Syntax: on");
    const onBg = await t.evaluate((el) => getComputedStyle(el).backgroundColor);
    await t.click();
    const offBg = await page.locator(".cmh-diff-hltoggle").first().evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(onBg).not.toBe(offBg);
    // Rough channel check: green dominant when on, red dominant when off.
    const nums = (s) => (s.match(/[\d.]+/g) || []).map(Number);
    const on = nums(onBg), off = nums(offBg);
    expect(on[1]).toBeGreaterThan(on[0]); // green > red when on
    expect(off[0]).toBeGreaterThan(off[1]); // red > green when off
  });

  test("a Portable file becomes Not portable after deleting an embedded comment", async ({ page, context }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "embed me into the file");
    await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable"); // unembedded yet
    const [dl] = await Promise.all([
      page.waitForEvent("download"),
      page.click("#btnSaveHtml"),
    ]);
    const html = await readDownload(dl);
    const tmp = path.join(os.tmpdir(), "cmh_portable_" + Date.now() + ".html");
    fs.writeFileSync(tmp, html);
    let p2;
    try {
      p2 = await context.newPage();
      p2.on("dialog", (d) => d.accept());
      await installClipboardCapture(p2);
      await p2.goto(fileUrl(tmp));
      await ready(p2);
      await expect(p2.locator("#cmTypeBadge")).toHaveText("Portable");
      // Deleting the comment leaves it embedded in the file on disk -> Not portable.
      await p2.locator(".cm-card [data-act='del']").first().click();
      await expect(p2.locator("#cmTypeBadge")).toHaveText("Not portable");
    } finally {
      if (p2) await p2.close();
      fs.rmSync(tmp, { force: true });
    }
  });
});
