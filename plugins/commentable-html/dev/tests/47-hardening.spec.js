// Hardening batch: export/markdown/persistence and keyboard/tooltip fixes adjudicated for
// this release. Each test maps to a SPEC row (CMH-EXP-07, CMH-MODE-07, CMH-MD-03/04,
// CMH-IMG-06, CMH-PERSIST-03, CMH-UI-08/09/10/11, CMH-A11Y-04/05, CMH-TOC-07).
import { test, expect } from "@playwright/test";
import {
  fileUrl, ready, installClipboardCapture, stageContent, stageInline,
  openInline, openNonPortable, openComposerFor, addTextComment, selectText,
  openToolbarMenu, readDownload, currentToast, storedComments,
  clickSidebarExport,
} from "./helpers.js";

async function openRich(page, content, key) {
  await installClipboardCapture(page);
  const { html } = stageContent(content, { key });
  await page.goto(fileUrl(html));
  await ready(page);
}

// C3 - CMH-EXP-07
test("embedded-comments script is found regardless of attribute order (CMH-EXP-07)", async ({ page }) => {
  const { html } = stageInline({
    mutate: (h) => h.replace(
      '<script type="application/json" id="embeddedComments">',
      '<script id="embeddedComments" type="application/json">'),
  });
  await installClipboardCapture(page);
  await page.goto(fileUrl(html));
  await ready(page);
  await addTextComment(page, "#commentRoot p", "order-independent note");
  const [dl] = await Promise.all([page.waitForEvent("download"), clickSidebarExport(page, "#btnSaveHtml")]);
  const out = await readDownload(dl);
  expect(out).toContain("order-independent note");
  expect(out).toContain('id="embeddedComments"');
});

// C3 - CMH-EXP-07: a decoy data-id must not be mistaken for the real id attribute
test("export updates the real embeddedComments block, not a decoy data-id script (CMH-EXP-07)", async ({ page }) => {
  const DECOY = '<script data-id="embeddedComments" type="application/json">"DECOY_SENTINEL_MUST_SURVIVE"</scr' + 'ipt>\n';
  const { html } = stageInline({
    mutate: (h) => h.replace(
      '<script type="application/json" id="embeddedComments">',
      DECOY + '<script type="application/json" id="embeddedComments">'),
  });
  await installClipboardCapture(page);
  await page.goto(fileUrl(html));
  await ready(page);
  await addTextComment(page, "#commentRoot p", "real-block note");
  const [dl] = await Promise.all([page.waitForEvent("download"), clickSidebarExport(page, "#btnSaveHtml")]);
  const out = await readDownload(dl);
  expect(out).toContain("real-block note");
  expect(out).toContain("DECOY_SENTINEL_MUST_SURVIVE");
});

// C4 - CMH-MODE-07
test("standalone export aborts when the companion assets version mismatches the runtime (CMH-MODE-07)", async ({ page }) => {
  await openNonPortable(page);
  await page.evaluate(() => { window.__COMMENTABLE_ASSETS__.version = "9.9.9"; });
  await openToolbarMenu(page);
  let gotDownload = false;
  page.once("download", () => { gotDownload = true; });
  await page.click("#btnSaveHtmlTop");
  await expect.poll(() => currentToast(page)).toContain("Cannot export standalone");
  expect(await currentToast(page)).toContain("9.9.9");
  expect(gotDownload).toBe(false);
});

// C5 - CMH-MD-03
test("Markdown export serializes strong/link/code that are direct list-item children (CMH-MD-03)", async ({ page }) => {
  const LIST = '<h1>L</h1><ul><li><strong>bold</strong> then <a href="https://e.com/p">lnk</a> then <code>x&lt;1</code></li></ul>';
  await openRich(page, LIST, "cmh-md-list");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("**bold**");
  expect(md).toContain("[lnk](https://e.com/p)");
  expect(md).toContain("`x<1`");
});

// C8 - CMH-MD-04
test("Markdown export drops a bare data: URL but keeps a data:image URL (CMH-MD-04)", async ({ page }) => {
  const U = '<h1>U</h1><p><a href="data:text/html;base64,PHNjcmlwdD4=">bad</a> '
    + '<img alt="ok" src="data:image/png;base64,iVBORw0KGgo="></p>';
  await openRich(page, U, "cmh-md-data");
  const md = await page.evaluate(() => window.__cmhToMarkdown());
  expect(md).toContain("[bad](about:blank)");
  expect(md).toContain("![ok](data:image/png;base64,iVBORw0KGgo=)");
});

// C6 - CMH-IMG-06
test("clearing and flashing a canvas comment finds the canvas, not just <img> (CMH-IMG-06)", async ({ page }) => {
  const CHART = '<h1>C</h1><figure class="chart"><canvas id="c1" class="cmh-chart" width="320" height="160" aria-label="Trend"></canvas></figure>';
  await openRich(page, CHART, "cmh-canvas-hl");
  await page.locator("canvas#c1").hover();
  await page.locator("#imageAddBtn").click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("chart note");
  await composer.locator('[data-act="save"]').click();
  await expect(page.locator("canvas#c1.cm-img-hl")).toHaveCount(1);
  await page.locator("canvas#c1").click();
  await expect(page.locator("canvas#c1.cm-img-active")).toHaveCount(1);
  page.once("dialog", (d) => d.accept());   // card delete uses a native confirm()
  await page.locator(".cm-card").first().locator('[data-act="del"]').click();
  await expect(page.locator("canvas#c1.cm-img-hl")).toHaveCount(0);
});

// C7 - CMH-PERSIST-03
test("duplicate persisted comment ids dedupe and the newest-timestamp entry wins (CMH-PERSIST-03)", async ({ page }) => {
  const { html } = stageContent('<h1>D</h1><p>Some target text here.</p>', { key: "cmh-dedup" });
  await installClipboardCapture(page);
  await page.goto(fileUrl(html));
  await ready(page);
  await page.evaluate(() => {
    const older = { id: "cdup000001", note: "OLD-NOTE", anchorType: "document",
                    createdAt: "2024-01-01T00:00:00Z", updatedAt: "2024-01-01T00:00:00Z" };
    const newer = { id: "cdup000001", note: "NEW-NOTE", anchorType: "document",
                    createdAt: "2024-01-01T00:00:00Z", updatedAt: "2024-06-01T00:00:00Z" };
    // Older first, newer second: the merge must replace with the later updatedAt.
    window.__cmhStorageCodec.write([older, newer]);
  });
  await page.reload();
  await ready(page);
  await expect(page.locator(".cm-card")).toHaveCount(1);
  const stored = await storedComments(page);
  const dupes = stored.filter((c) => c.id === "cdup000001");
  expect(dupes.length).toBe(1);
  expect(dupes[0].note).toBe("NEW-NOTE");
});

// C7 - CMH-PERSIST-03: newest wins regardless of array order
test("the newest duplicate wins even when it appears first (CMH-PERSIST-03)", async ({ page }) => {
  const { html } = stageContent('<h1>D</h1><p>Some target text here.</p>', { key: "cmh-dedup2" });
  await installClipboardCapture(page);
  await page.goto(fileUrl(html));
  await ready(page);
  await page.evaluate(() => {
    const newer = { id: "cdup000002", note: "NEW-NOTE", anchorType: "document",
                    createdAt: "2024-01-01T00:00:00Z", updatedAt: "2024-06-01T00:00:00Z" };
    const older = { id: "cdup000002", note: "OLD-NOTE", anchorType: "document",
                    createdAt: "2024-01-01T00:00:00Z", updatedAt: "2024-01-01T00:00:00Z" };
    window.__cmhStorageCodec.write([newer, older]);
  });
  await page.reload();
  await ready(page);
  const stored = await storedComments(page);
  const dupes = stored.filter((c) => c.id === "cdup000002");
  expect(dupes.length).toBe(1);
  expect(dupes[0].note).toBe("NEW-NOTE");
});

// U1 - CMH-UI-08
test("Escape dismissing the Add-Comment menu does not close an open composer draft (CMH-UI-08)", async ({ page }) => {
  await openInline(page);
  const composer = await openComposerFor(page, "#commentRoot p", { index: 0 });
  await composer.locator("textarea").fill("draft in progress");
  await selectText(page, "#commentRoot p", { index: 1 });
  await expect(page.locator("#contextMenu")).toBeVisible();
  await page.evaluate(() => { const a = document.activeElement; if (a && a.blur) a.blur(); });
  await page.keyboard.press("Escape");
  await expect(page.locator("#contextMenu")).toBeHidden();
  await expect(composer).toHaveCount(1);
  await expect(composer.locator("textarea")).toHaveValue("draft in progress");
});

// U3 - CMH-A11Y-04
test("the confirm dialog always traps Tab and pulls escaped focus back to Cancel (CMH-A11Y-04)", async ({ page }) => {
  await openInline(page);
  await addTextComment(page, "#commentRoot p", "to be cleared");
  await page.click("#btnClearAll");
  await expect(page.locator(".cm-modal-overlay")).toBeVisible();
  await page.evaluate(() => document.activeElement && document.activeElement.blur());
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => document.activeElement.className)).toContain("cm-modal-default");
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => (document.activeElement.textContent || "").trim())).toBe("OK");
  await page.keyboard.press("Escape");
});

// U5 - CMH-UI-09
test("updateDocTypeUi updates the managed tooltip in place without a native-title flash (CMH-UI-09)", async ({ page }) => {
  await openInline(page);
  // Reproduce the state the tooltip layer leaves after it adopts the control, and seed an
  // EXISTING aria-label carrying the current reason so we can prove it is updated in place.
  await page.evaluate(() => {
    const el = document.getElementById("cmhModeBadge");
    el.setAttribute("data-cmh-tip", el.getAttribute("title") || "");
    el.setAttribute("aria-label", "STALE-ARIA-REASON");
    el.removeAttribute("title");
  });
  await addTextComment(page, "#commentRoot p", "flips to not portable");
  const badge = page.locator("#cmhModeBadge");
  expect(await badge.getAttribute("title")).toBeNull();
  expect(await badge.getAttribute("data-cmh-tip")).toContain("Not portable");
  // The pre-existing aria-label is rewritten to the new reason, not left stale.
  const aria = await badge.getAttribute("aria-label");
  expect(aria).not.toBe("STALE-ARIA-REASON");
  expect(aria).toContain("Not portable");
});

// U6 - CMH-TOC-07
test("the side-TOC highlights the last section once the page is fully scrolled (CMH-TOC-07)", async ({ page }) => {
  const SECS = [0, 1, 2].map((i) =>
    `<section><h2 id="s${i}">Section ${i}</h2><p style="display:block;height:1200px">body ${i}</p></section>`).join("");
  await openRich(page, SECS, "cmh-toc-bottom");
  await expect(page.locator("#cmSideToc")).toHaveCount(1);
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect.poll(async () =>
    page.$$eval("#cmSideToc .cm-side-toc-list a.is-active", (els) => els.map((e) => e.getAttribute("href")))
  ).toEqual(["#s2"]);
});

// U7 - CMH-UI-10
test("Escape closing the toolbar overflow menu restores focus to its trigger (CMH-UI-10)", async ({ page }) => {
  await openInline(page);
  await page.click("#btnToolbarMenu");
  await expect(page.locator("#toolbarMenu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#toolbarMenu")).toBeHidden();
  expect(await page.evaluate(() => document.activeElement.id)).toBe("btnToolbarMenu");
});

// P5 - CMH-A11Y-05
test("the composer placeholder documents the Ctrl/Cmd+Enter save shortcut (CMH-A11Y-05)", async ({ page }) => {
  await openInline(page);
  const composer = await openComposerFor(page, "#commentRoot p", { index: 0 });
  expect(await composer.locator("textarea").getAttribute("placeholder")).toContain("Ctrl/Cmd+Enter");
});

// U2 - CMH-UI-11
test("the composer is clamped fully inside the viewport even when small (CMH-UI-11)", async ({ page }) => {
  await openInline(page);
  await page.setViewportSize({ width: 460, height: 340 });
  const composer = await openComposerFor(page, "#commentRoot p", { index: 0 });
  const box = await composer.boundingBox();
  const vw = await page.evaluate(() => window.innerWidth);
  const vh = await page.evaluate(() => window.innerHeight);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(vw + 1);
  expect(box.y + box.height).toBeLessThanOrEqual(vh + 1);
});
