// Section review must reach ANY existing document after upgrade.py runs (CMH-REVIEW-09).
// upgrade.py swaps the CSS / COMMENT UI / JS regions from the current template, and the
// section-review runtime + CSS live in those regions, so a document produced before the feature
// existed gains a working review UI on upgrade - with no baked reviewedSections block (the runtime
// is localStorage-first and null-safe). The real pre-feature snapshot dev/upgrade-corpus/v1.117.0.html
// is the red baseline: it must show NO review chrome before upgrade, and a fully working one after.
import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { spawnSync } from "child_process";
import { fileUrl, ready, denyExternalNetwork, DEV, SKILL, DIST, PYTHON } from "./helpers.js";

const SNAPSHOT = path.join(DEV, "upgrade-corpus", "v1.117.0.html");
const TEMPLATE = path.join(DIST, "PORTABLE.html");
const UPGRADE = path.join(SKILL, "tools", "authoring", "upgrade.py");
const TMP = path.join(DEV, "..", "..", "..", "tmp", "upgrade-review-spec");

test.beforeAll(() => {
  fs.mkdirSync(TMP, { recursive: true });
});
test.afterAll(() => {
  fs.rmSync(TMP, { recursive: true, force: true });
});

// A real section heading (prefer h2/h3) inside #commentRoot - more representative than the H1
// document title, which can sit in a sticky header. Falls back to any heading with an id.
const reviewableHeadingId = (page) => page.evaluate(() => {
  const pick = (sel) => {
    const el = Array.prototype.find.call(document.querySelectorAll(sel), (h) => h.id);
    return el ? el.id : null;
  };
  return pick("#commentRoot h2, #commentRoot h3")
    || pick("#commentRoot h1, #commentRoot h2, #commentRoot h3, #commentRoot h4, #commentRoot h5, #commentRoot h6");
});

test("a pre-feature document gains a working section-review UI after upgrade.py (CMH-REVIEW-09)", async ({ page }) => {
  test.setTimeout(60000);

  // Red baseline: the shipped pre-feature snapshot has no section-review chrome at all.
  await denyExternalNetwork(page);
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto(fileUrl(SNAPSHOT));
  await ready(page);
  expect(await page.locator(".cmh-review-badge").count()).toBe(0);
  expect(await page.locator(".cm-side-toc-review").count()).toBe(0);
  expect(await page.evaluate(() => typeof window.__cmhReview)).toBe("undefined");

  // Upgrade a copy with the current template (dist/PORTABLE.html).
  const target = path.join(TMP, "upgraded.html");
  fs.copyFileSync(SNAPSHOT, target);
  const r = spawnSync(PYTHON, [UPGRADE, target, "--template", TEMPLATE],
    { encoding: "utf8", timeout: 60000, killSignal: "SIGKILL" });
  expect(r.error, String(r.error)).toBeFalsy();
  expect(r.status, r.stderr).toBe(0);
  expect(r.stdout).toMatch(/Upgraded/);

  // The upgraded document now has a working review UI.
  await page.goto(fileUrl(target));
  await ready(page);
  expect(await page.evaluate(() => typeof window.__cmhReview)).toBe("object");
  // Assert the side-TOC review filter is actually VISIBLE (not merely attached): the swapped-in CSS
  // must render it, which is the user-facing promise of the feature reaching an upgraded document.
  await expect(page.locator(".cm-side-toc-review")).toBeVisible();
  // The upgrade brings the runtime but never re-adds document state, so the upgraded file carries
  // NO baked reviewedSections block: the feature works purely from the swapped-in runtime. Assert on
  // the parsed DOM (robust to attribute quoting/order), not a single serialization of the raw text.
  await expect(page.locator('[id="reviewedSections"]')).toHaveCount(0);

  const id = await reviewableHeadingId(page);
  expect(id, "the upgraded document has a heading to review").toBeTruthy();
  const heading = page.locator(`[id="${id}"]`);
  await heading.scrollIntoViewIfNeeded();
  const badge = page.locator(`[id="${id}"] .cmh-review-badge`);
  await expect(badge).toHaveCount(1);
  await expect(badge).toHaveClass(/cmh-review-unreviewed/);

  await heading.hover();
  await badge.click();
  await expect(badge).toHaveClass(/cmh-review-reviewed/);
  expect(await page.evaluate((i) => window.__cmhReview.stateOf(i), id)).toBe("reviewed");

  // The marker persists across reload (localStorage), proving the feature is fully live post-upgrade.
  await page.reload();
  await ready(page);
  expect(await page.evaluate((i) => window.__cmhReview.stateOf(i), id)).toBe("reviewed");
});
