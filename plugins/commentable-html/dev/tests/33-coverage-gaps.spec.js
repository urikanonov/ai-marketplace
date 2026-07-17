import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import {
  openInline, ready, openComposerFor, fileUrl, INLINE, SKILL,
  installClipboardCapture, stageInline, startStaticServer, routeMermaidLocal,
} from "./helpers.js";

const EXAMPLE = path.join(SKILL, "..", "..", "examples", "report-community-garden.html");

// Fills SPEC coverage gaps that were previously manual-only.

test("composers coexist, stagger by 28px on overlap, and focus raises z-order (CMH-CORE-09)", async ({ page }) => {
  await openInline(page);
  // two composers anchored on the SAME selection collide, so the second is offset
  await openComposerFor(page, "#commentRoot p", { index: 0 });
  await openComposerFor(page, "#commentRoot p", { index: 0 });
  const composers = page.locator(".cm-composer");
  await expect(composers).toHaveCount(2);
  const pos = await page.evaluate(() => [...document.querySelectorAll(".cm-composer")].map((c) => ({
    left: parseFloat(c.style.left), top: parseFloat(c.style.top), z: parseInt(getComputedStyle(c).zIndex, 10),
  })));
  expect(Math.round(Math.abs(pos[1].left - pos[0].left))).toBe(28); // exact stagger step
  expect(Math.round(Math.abs(pos[1].top - pos[0].top))).toBe(28);
  // focusing the first composer raises it above the second (focus works even though
  // the second composer overlaps and covers it)
  await composers.nth(0).locator("textarea").focus();
  const z = await page.evaluate(() => [...document.querySelectorAll(".cm-composer")].map((c) => parseInt(getComputedStyle(c).zIndex, 10)));
  expect(z[0]).toBeGreaterThan(z[1]);
});

test("clawpilotTheme=auto follows the OS color scheme (CMH-THEME-01)", async ({ page }) => {
  await installClipboardCapture(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto(fileUrl(INLINE) + "?clawpilotTheme=auto");
  await ready(page);
  expect(await page.evaluate(() => document.documentElement.getAttribute("data-theme"))).toBe("dark");
  await page.emulateMedia({ colorScheme: "light" });
  await page.reload();
  await ready(page);
  expect(await page.evaluate(() => document.documentElement.getAttribute("data-theme"))).toBe("light");
});

test("the example Chart.js chart renders a working tooltip (CMH-CHART-04)", async ({ page }) => {
  const { html, dir } = stageInline({ source: EXAMPLE });
  const server = await startStaticServer(dir);
  try {
    await routeMermaidLocal(page);
    await page.goto(`${server.url}/${path.basename(html)}`);
    await ready(page);
    const chartSelector = "#wateringNeedsChart";
    await page.locator(chartSelector).scrollIntoViewIfNeeded();
    await page.waitForFunction((sel) => {
      const cv = document.querySelector(sel);
      const chart = cv && window.Chart && window.Chart.getChart && window.Chart.getChart(cv);
      return !!(chart && chart.getDatasetMeta(0).data[0]);
    }, chartSelector, { timeout: 10000 });
    await expect.poll(async () => {
      const point = await page.evaluate((sel) => {
        const cv = document.querySelector(sel);
        const chart = cv && window.Chart && window.Chart.getChart && window.Chart.getChart(cv);
        const pt = chart && chart.getDatasetMeta(0).data[0];
        if (!cv || !pt) return null;
        const r = cv.getBoundingClientRect();
        return { x: r.left + pt.x, y: r.top + pt.y };
      }, chartSelector);
      if (!point) return 0;
      await page.mouse.move(Math.max(1, point.x - 24), Math.max(1, point.y - 24));
      await page.mouse.move(point.x, point.y);
      return page.evaluate((sel) => {
        const cv = document.querySelector(sel);
        const chart = cv && window.Chart && window.Chart.getChart && window.Chart.getChart(cv);
        return chart ? chart.tooltip.getActiveElements().length : 0;
      }, chartSelector);
    }, { timeout: 6000 }).toBeGreaterThan(0);
  } finally {
    await server.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("the composer exposes group semantics and a labelled textarea (CMH-A11Y-02)", async ({ page }) => {
  await openInline(page);
  const composer = await openComposerFor(page, "#commentRoot p", { index: 0 });
  await expect(composer).toHaveAttribute("role", "group");
  await expect(composer).toHaveAttribute("aria-label", /composer/i);
  const ta = composer.locator("textarea");
  await expect(ta).toHaveAttribute("aria-label", /comment/i);
  const describedby = await ta.getAttribute("aria-describedby");
  expect(describedby).toBeTruthy();
  await expect(composer.locator("#" + describedby)).toHaveCount(1);
});

test("saving a blank note marks the textarea invalid and keeps the composer open (CMH-A11Y-02)", async ({ page }) => {
  await openInline(page);
  const composer = await openComposerFor(page, "#commentRoot p", { index: 0 });
  await composer.locator('[data-act="save"]').click();
  await expect(composer.locator("textarea")).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator(".cm-composer")).toHaveCount(1); // still open, nothing saved
  await composer.locator("textarea").fill("now it has content");
  expect(await composer.locator("textarea").getAttribute("aria-invalid")).toBeNull(); // cleared on input
});

test("closing a composer returns focus to the diff line that opened it (CMH-A11Y-02)", async ({ page }) => {
  await page.goto(fileUrl(EXAMPLE));
  await ready(page);
  const line = page.locator(".cmh-dl-add").first();
  await line.scrollIntoViewIfNeeded();
  await line.focus();
  await expect(line).toBeFocused();
  await line.press("Enter"); // opener captured = this diff line
  const composer = page.locator(".cm-composer").last();
  await expect(composer).toBeVisible();
  await composer.locator("textarea").press("Escape"); // cancel path
  await expect(page.locator(".cm-composer")).toHaveCount(0);
  await expect(line).toBeFocused(); // focus returned to the opener
});
