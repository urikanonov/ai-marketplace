// CMH-DECK-EXPORT-01: all four exports (Portable, Offline, Plain, Markdown) on the SHIPPED
// showcase deck (examples/deck-showcase.html, a kind=slides deck). Each test serves the real
// deck over http with mermaid routed to the vendored copy (a runtime CDN import browsers block
// over file://) so the suite stays fully self-contained, exercises the sidebar export button
// reached through comment mode, and asserts the deck contract survives the export.
import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";
import {
  DEV, SKILL, PYTHON, fileUrl, ready, readDownload, startStaticServer,
  installClipboardCapture, openComposerFor, routeMermaidLocal,
} from "./helpers.js";

const DECK = path.join(SKILL, "examples", "deck-showcase.html");
// The first slide of the shipped deck carries a commentable prose paragraph.
const COMMENT_TARGET = ".slide.active p.showcase-comment-target";

function makeTmpDir(prefix) {
  const repoRoot = path.resolve(DEV, "..", "..", "..");
  const tmpRoot = path.join(repoRoot, "tmp");
  fs.mkdirSync(tmpRoot, { recursive: true });
  return fs.mkdtempSync(path.join(tmpRoot, prefix));
}

// Any absolute-scheme URL still referenced by a media/load attribute in the exported HTML,
// used to prove the offline file reaches out to nothing.
function networkLoadRefs(html) {
  const refs = [];
  const tagRe = /<(script|link|img|source|iframe|video|audio|object|embed|track|image|use|input|meta|body|table|td|th|form|button)\b[^>]*>/gi;
  for (const tag of html.matchAll(tagRe)) {
    for (const attr of tag[0].matchAll(/\s(href|xlink:href|src|srcset|poster|data|background|content|action|formaction)\s*=\s*["']([^"']+)["']/gi)) {
      const values = attr[1].toLowerCase() === "srcset"
        ? attr[2].split(",").map((part) => part.trim().split(/\s+/)[0])
        : [attr[2]];
      for (const value of values) {
        if (/^(?:https?:)?\/\//i.test(value)) refs.push(value);
      }
    }
  }
  return refs;
}

// Serve a private copy of the shipped deck over http with mermaid routed locally, wait for the
// layer to be ready, then return handles plus a cleanup that stops the server and removes the dir.
async function openDeck(page) {
  const dir = makeTmpDir("cmh_deck_exports_");
  fs.copyFileSync(DECK, path.join(dir, "deck-showcase.html"));
  const server = await startStaticServer(dir);
  await installClipboardCapture(page);
  await routeMermaidLocal(page);
  await page.goto(server.url + "/deck-showcase.html");
  await ready(page);
  const cleanup = async () => {
    await server.close();
    fs.rmSync(dir, { recursive: true, force: true });
  };
  return { dir, server, cleanup };
}

// Enter comment mode and add one comment on the first slide, which reveals the sidebar and its
// export buttons (the proven deck export entry point, mirroring 52-deck.spec.js).
async function enterCommentModeAndComment(page, note) {
  await page.locator(".cmh-deck-mode-toggle").click();
  const composer = await openComposerFor(page, COMMENT_TARGET);
  const textarea = composer.locator("textarea");
  await textarea.fill(note);
  await textarea.press("Control+Enter");
  await expect(composer).toHaveCount(0);
}

test("CMH-DECK-EXPORT-01: Export Portable round-trips the showcase deck and reopens self-contained", async ({ page, browser }) => {
  test.setTimeout(60000);
  const { dir, cleanup } = await openDeck(page);
  let ctx2;
  try {
    await enterCommentModeAndComment(page, "portable deck note");
    await expect(page.locator("#btnSaveHtml")).toBeVisible();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnSaveHtml").click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/-portable\.html$/);
    const exportedHtml = await readDownload(download);

    // The deck contract and the embedded comment survive; the layer is inlined (self-contained),
    // never split into an external companion stylesheet.
    expect(exportedHtml).toContain('data-cmh-mode="deck"');
    expect(exportedHtml).toMatch(/<meta[^>]+name="commentable-html-kind"[^>]+content="slides"/);
    expect(exportedHtml).toContain("__commentableHtmlReady");
    expect(exportedHtml).not.toMatch(/<link\b[^>]+commentable-html\.css/);
    expect(exportedHtml).toContain('id="embeddedComments"');
    expect(exportedHtml).toContain("portable deck note");
    const ids = [...exportedHtml.matchAll(/data-slide-id="([^"]+)"/g)].map((m) => m[1]);
    expect(ids.length).toBeGreaterThan(3);
    expect(new Set(ids).size).toBe(ids.length);
    const firstId = ids[0];

    const exportedPath = path.join(dir, "deck-portable.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    const external = [];
    await page2.route(/^https?:\/\//, async (route) => { external.push(route.request().url()); await route.abort(); });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    // The deck runtime re-activates on slide 1 and the comment is restored, all with no network.
    expect(await page2.evaluate(() => typeof window.__cmhDeck)).toBe("object");
    expect(await page2.evaluate(() => window.__cmhDeck.activeSlideId())).toBe(firstId);
    await expect.poll(() => page2.locator("mark.cm-hl").count()).toBeGreaterThan(0);
    await page2.locator(".cmh-deck-mode-toggle").click();
    await expect(page2.locator("#commentList")).toContainText("portable deck note");
    // A Portable deck keeps only the optional mermaid library loader; the sole permitted network
    // is that CDN, never the content, comments, or a companion asset file.
    expect(external.every((u) => /cdn\.jsdelivr\.net\/npm\/mermaid@/.test(u))).toBe(true);
  } finally {
    if (ctx2) await ctx2.close();
    await cleanup();
  }
});

test("CMH-DECK-EXPORT-01: Export Offline keeps the deck mermaid + chart live, validates strict, and reopens with zero network", async ({ page, browser }) => {
  test.setTimeout(90000);
  const { dir, cleanup } = await openDeck(page);
  let ctx2;
  try {
    // Wait for the rich content to render before exporting so the offline copy reopens with the
    // same live diagram and canvas behavior.
    await page.waitForFunction(() => !!document.querySelector("#commentRoot pre.mermaid svg"), null, { timeout: 20000 });
    await page.waitForFunction(() => {
      const c = document.getElementById("showcaseChart");
      return !!(c && c.getContext && c.width > 0);
    }, null, { timeout: 20000 });

    await enterCommentModeAndComment(page, "offline deck note");
    await expect(page.locator("#btnExportOffline")).toBeVisible();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOffline").click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/-offline\.html$/);
    const exportedHtml = await readDownload(download);

    // No remote loaders remain: the mermaid CDN import is stripped, the deck stays a deck, and
    // the live mermaid/chart surfaces stay in the file instead of being flattened.
    expect(exportedHtml).not.toContain("cdn.jsdelivr.net/npm/mermaid");
    expect(networkLoadRefs(exportedHtml)).toEqual([]);
    expect(exportedHtml).not.toContain('data-cm-offline-chart="true"');
    expect(exportedHtml).toContain('<canvas id="showcaseChart"');
    // The deck contract survives; the transient present-mode body class is NOT baked in.
    expect(exportedHtml).toContain('data-cmh-mode="deck"');
    expect(/<body[^>]*class="[^"]*cmh-deck-present/.test(exportedHtml)).toBe(false);
    expect(exportedHtml).not.toMatch(/<section\b[^>]*\bcmh-deck-overview\b/);

    const exportedPath = path.join(dir, "deck-offline.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    // The offline deck passes BOTH the base strict validator and the strict deck validator.
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });
    execFileSync(PYTHON, ["tools/deck/deck_validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });

    ctx2 = await browser.newContext({ offline: true });
    const page2 = await ctx2.newPage();
    const external = [];
    page2.on("request", (request) => {
      if (/^https?:\/\//.test(request.url())) external.push(request.url());
    });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    await expect(page2.locator("#cmTypeBadge")).toHaveText("Offline");
    expect(await page2.evaluate(() => typeof window.__cmhDeck)).toBe("object");
    // The mermaid lives on a non-active slide, so assert it is attached with rendered graphics
    // rather than visible in present mode.
    await expect(page2.locator("#commentRoot pre.mermaid svg").first()).toBeAttached();
    expect(await page2.locator("#commentRoot pre.mermaid svg g").count()).toBeGreaterThan(0);
    const chartState = await page2.evaluate(() => {
      const canvas = document.getElementById("showcaseChart");
      if (!canvas) return null;
      const pixel = Array.from(canvas.getContext("2d").getImageData(120, 120, 1, 1).data);
      return { tag: canvas.tagName, pixel };
    });
    expect(chartState).toBeTruthy();
    expect(chartState.tag).toBe("CANVAS");
    expect(chartState.pixel.some((value) => value !== 0)).toBe(true);
    await expect.poll(() => page2.locator("mark.cm-hl").count()).toBeGreaterThan(0);
    await page2.locator(".cmh-deck-mode-toggle").click();
    await expect(page2.locator("#commentList")).toContainText("offline deck note");
    expect(external).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    await cleanup();
  }
});

test("CMH-DECK-EXPORT-01: Export Plain strips the layer but keeps the showcase deck slides and styling", async ({ page }) => {
  test.setTimeout(60000);
  const { cleanup } = await openDeck(page);
  try {
    await enterCommentModeAndComment(page, "plain deck note");
    await expect(page.locator("#btnSavePlain")).toBeVisible();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnSavePlain").click(),
    ]);
    const html = await readDownload(download);

    // The commenting layer is gone: no runtime, no sidebar, no handled-id store, no toolbar.
    expect(html).not.toContain("__commentableHtmlReady");
    expect(html).not.toContain('id="sidebar"');
    expect(html).not.toContain('id="handledCommentIds"');
    expect(html).not.toContain('class="cm-toolbar');
    // The deck content and its styling survive - "plain" removes the commenting ability, not the deck.
    const ids = [...html.matchAll(/data-slide-id="([^"]+)"/g)].map((m) => m[1]);
    expect(ids.length).toBeGreaterThan(3);
    expect(html).toContain("watering");
    expect(html).toContain("--cp-bg");
  } finally {
    await cleanup();
  }
});

test("CMH-DECK-EXPORT-01: Export Markdown produces a deterministic structural export of the showcase deck", async ({ page }) => {
  test.setTimeout(60000);
  const { cleanup } = await openDeck(page);
  try {
    // The structural conversion is a pure function of the current DOM, so two calls are byte-equal.
    expect(await page.evaluate(() => typeof window.__cmhToMarkdown)).toBe("function");
    const [a, b] = await page.evaluate(() => [window.__cmhToMarkdown(), window.__cmhToMarkdown()]);
    expect(a).toBe(b);
    // Structure survives: slide headings, fenced mermaid source, a rendered diff, syntax-highlighted
    // KQL/code, and a chart placeholder - with no raw slide markup leaking through.
    expect(a).toMatch(/^## /m);
    expect(a).toContain("garden plan");
    expect(a).toContain("```mermaid");
    expect(a).toContain("flowchart LR");
    expect(a).toContain("```diff");
    expect(a).toContain("```kusto");
    expect(a).toContain("_[Chart");
    // The slide wrappers were converted to markdown, not dumped as raw HTML: their
    // data-slide-id attribute never appears (a literal `<section>` only shows up inside a
    // fenced code sample, which is legitimate content).
    expect(a).not.toContain("data-slide-id");

    // The Export Markdown button downloads a .md file that also carries the review comment.
    await enterCommentModeAndComment(page, "markdown deck note");
    await expect(page.locator("#btnExportMd")).toBeVisible();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportMd").click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.md$/);
    const md = await readDownload(download);
    expect(md).toContain("```mermaid");
    expect(md).toContain("## Review comments");
    expect(md).toContain("markdown deck note");
  } finally {
    await cleanup();
  }
});
