// Optional filename/description caption line on a code block (CMH-CODE-05). An author
// opts in with data-code-caption on the <pre>; the runtime renders a cm-skip caption
// bar above the code block, in both report and deck modes, and it survives Export
// Offline. The caption must not disturb the language pill, Copy button, highlighting,
// or commenting on the code.
import fs from "fs";
import os from "os";
import path from "path";
import { test, expect } from "@playwright/test";
import {
  fileUrl, ready, stageContent, stageDeck, installClipboardCapture,
  addTextComment, openToolbarMenu,
} from "./helpers.js";

const CAPTIONED = `
<h2>Caption demo</h2>
<pre data-code-caption="trigger.kql"><code class="language-kusto">SigninLogs
| take 10</code></pre>
<pre id="plainBlock"><code class="language-python">x = 1</code></pre>`;

async function openContent(page, content, key) {
  await installClipboardCapture(page);
  const staged = stageContent(content, { key });
  await page.goto(fileUrl(staged.html));
  await ready(page);
  return staged;
}

test("a code block with data-code-caption renders a cm-skip caption bar above the code (CMH-CODE-05)", async ({ page }) => {
  await openContent(page, CAPTIONED, "cmh-code-caption");

  const caption = page.locator(".cmh-code-caption");
  await expect(caption).toHaveCount(1);
  await expect(caption.locator(".cmh-code-caption-text")).toHaveText("trigger.kql");
  // Chrome, not content: excluded from selection/offsets like the KQL cap and Copy button.
  await expect(caption).toHaveClass(/cm-skip/);

  // The caption sits ABOVE the code block it labels.
  const wrap = page.locator(".cmh-code-wrap", { has: page.locator('pre[data-code-caption="trigger.kql"]') });
  await expect(wrap).toHaveCount(1);
  const capBox = await caption.boundingBox();
  const preBox = await wrap.locator("pre").boundingBox();
  expect(capBox.y).toBeLessThan(preBox.y);

  // The language pill and Copy button on the captioned block are untouched.
  const tools = wrap.locator(".cm-code-tools");
  await expect(tools.locator(".cm-code-lang", { hasText: "KQL" })).toHaveCount(1);
  await expect(tools.locator(".cm-code-copy")).toHaveCount(1);

  // A block WITHOUT the attribute gets no caption.
  const plainWrap = page.locator(".cmh-code-wrap", { has: page.locator("#plainBlock") });
  await expect(plainWrap.locator(".cmh-code-caption")).toHaveCount(0);
});

test("commenting on a captioned code block still tags the card as code (CMH-CODE-05)", async ({ page }) => {
  await openContent(page, CAPTIONED, "cmh-code-caption-comment");
  await addTextComment(page, 'pre[data-code-caption="trigger.kql"] code', "review this query");
  // The pinpoint names it a code block (KQL), proving the caption did not break code detection.
  await expect(page.locator("#commentList")).toContainText("code (kusto)");
  await expect(page.locator("#commentList")).toContainText("review this query");
});

test("a drag from the code up into the caption does not leak the filename into the selection (CMH-CODE-05)", async ({ page }) => {
  await openContent(page, CAPTIONED, "cmh-code-caption-drag");
  const capBox = await page.locator(".cmh-code-caption-text").boundingBox();
  const codeBox = await page.locator('pre[data-code-caption="trigger.kql"] code').boundingBox();
  // Anchor in the code and drag UP into the caption bar (whose common ancestor with the
  // code is the non-cm-skip .cmh-code-wrap, so 41-selection.js would not reject it).
  await page.mouse.move(codeBox.x + codeBox.width * 0.5, codeBox.y + codeBox.height - 6);
  await page.mouse.down();
  await page.mouse.move(capBox.x + 40, capBox.y + capBox.height / 2, { steps: 12 });
  await page.mouse.up();
  const selText = await page.evaluate(() => (window.getSelection() || "").toString());
  // The caption is user-select:none chrome, so its filename can never enter the selection
  // (and thus never a code comment's quote), even when the drag crosses into it.
  expect(selText).toContain("SigninLogs");
  expect(selText).not.toContain("trigger.kql");
});

test("a data-code-caption caption renders in deck mode (CMH-CODE-05)", async ({ page }) => {
  await installClipboardCapture(page);
  const slides = `
<section class="slide active" data-slide-title="Query"><h2>Query</h2>
<pre data-code-caption="query.kql"><code class="language-kusto">Heartbeat
| take 5</code></pre>
</section>`;
  const staged = stageDeck(slides, { key: "cmh-code-caption-deck" });
  await page.goto(fileUrl(staged.html));
  await ready(page);
  const caption = page.locator(".slide.active .cmh-code-caption");
  await expect(caption).toHaveCount(1);
  await expect(caption.locator(".cmh-code-caption-text")).toHaveText("query.kql");
});

test("an empty or whitespace-only data-code-caption renders no caption (CMH-CODE-05)", async ({ page }) => {
  await openContent(page, `
<h2>Blank caption</h2>
<pre data-code-caption="   "><code class="language-python">x = 1</code></pre>`, "cmh-code-caption-blank");
  await expect(page.locator(".cmh-code-caption")).toHaveCount(0);
  await expect(page.locator(".cmh-code-wrap.cmh-has-caption")).toHaveCount(0);
  // The block is otherwise normal: it still gets its Copy button.
  await expect(page.locator(".cmh-code-wrap .cm-code-copy")).toHaveCount(1);
});

test("data-code-caption on a KQL figure pre does not add a second caption (CMH-CODE-05)", async ({ page }) => {
  const kqlFigure = `
<h2>KQL</h2>
<figure class="cmh-kql">
<figcaption class="cm-skip cmh-kql-cap"><span class="cmh-kql-title">help / Samples</span></figcaption>
<pre data-code-caption="should-not-show.kql"><code class="language-kusto">StormEvents
| take 3</code></pre>
</figure>`;
  await openContent(page, kqlFigure, "cmh-code-caption-kql");
  // The KQL figure keeps its own caption bar and gets no standalone code caption.
  await expect(page.locator("figure.cmh-kql .cmh-kql-cap")).toHaveCount(1);
  await expect(page.locator(".cmh-code-caption")).toHaveCount(0);
  await expect(page.locator(".cmh-code-wrap.cmh-has-caption")).toHaveCount(0);
});

test("a long caption does not overlap the language pill and Copy button, even a wide one (CMH-CODE-05)", async ({ page }) => {
  await openContent(page, `
<h2>Long caption</h2>
<pre data-code-caption="src/handlers/very-long-file-name-that-reaches-the-edge.ts"><code class="language-typescript">export const run = () => 1;</code></pre>`, "cmh-code-caption-long");
  const wrap = page.locator(".cmh-code-wrap.cmh-has-caption");
  // A wide language pill (TypeScript) is the worst case for overlap.
  await expect(wrap.locator(".cm-code-tools .cm-code-lang", { hasText: "TypeScript" })).toHaveCount(1);
  const toolsBox = await wrap.locator(".cm-code-tools").boundingBox();
  const textRight = await page.locator(".cmh-code-caption-text").evaluate((el) => el.getBoundingClientRect().right);
  // The filename text (ellipsized) ends before the inline tools cluster - no overlap for any pill width.
  expect(textRight).toBeLessThanOrEqual(toolsBox.x + 1);
});

test("the code caption survives Export Offline and does not duplicate on reopen (CMH-CODE-05)", async ({ page, browser }) => {
  test.setTimeout(60000);
  await openContent(page, CAPTIONED, "cmh-code-caption-offline");

  await openToolbarMenu(page);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#btnExportOfflineTop").click(),
  ]);
  const exportedHtml = await download.path().then((p) => fs.readFileSync(p, "utf8"));
  // The opt-in attribute survives in the exported source; the runtime re-renders the caption
  // from it on reopen (exports serialize the pristine document, not the runtime-mutated DOM).
  expect(exportedHtml).toContain('data-code-caption="trigger.kql"');

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_cap_"));
  const exportedPath = path.join(dir, "offline.html");
  fs.writeFileSync(exportedPath, exportedHtml);

  const ctx2 = await browser.newContext({ offline: true });
  try {
    const page2 = await ctx2.newPage();
    const external = [];
    page2.on("request", (r) => { if (/^https?:\/\//.test(r.url())) external.push(r.url()); });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    await expect(page2.locator("#cmTypeBadge")).toHaveText("Offline");
    // Exactly one caption above the code after the runtime re-activates (idempotent wrap).
    const caption = page2.locator(".cmh-code-caption");
    await expect(caption).toHaveCount(1);
    await expect(caption.locator(".cmh-code-caption-text")).toHaveText("trigger.kql");
    await expect(page2.locator(".cmh-code-wrap .cm-code-copy").first()).toBeVisible();
    expect(external).toEqual([]);
  } finally {
    await ctx2.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
