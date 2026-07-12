import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import os from "os";
import {
  openInline, addTextComment, openToolbarMenu, readDownload, fileUrl, ready,
  stageContent, stageNonPortable,
} from "./helpers.js";

// Once a comment exists the panel is open (the floating toolbar is hidden), so
// these tests drive the panel-header buttons. Export plain adds no comment, so it
// uses the toolbar overflow menu.
test.describe("Save comments / Export plain", () => {
  async function markLiveCommentHandled(page, note) {
    await addTextComment(page, "#commentRoot section p", note);
    const cid = await page.locator("mark.cm-hl").first().getAttribute("data-cid");
    await page.evaluate((id) => {
      document.getElementById("handledCommentIds").textContent = JSON.stringify([id]);
    }, cid);
    return cid;
  }

  function embeddedComments(html) {
    const m = html.match(/id="embeddedComments">([\s\S]*?)<\/script>/);
    expect(m).toBeTruthy();
    return JSON.parse(m[1].trim() || "[]");
  }

  test("a comment note with a closing-script tag is escaped and round-trips decoded", async ({ page, browser }) => {
    await openInline(page);
    const evil = "evil </" + "script><img src=x onerror=alert(1)>";
    await addTextComment(page, "#commentRoot section p", evil);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnSaveHtml").click(),
    ]);
    const html = await readDownload(download);
    const block = html.match(/id="embeddedComments">([\s\S]*?)<\/script>/)[1];
    // No raw breakout survives, and "<" is encoded as \u003c.
    expect(block).not.toContain("</" + "script>");
    expect(block).not.toContain("<img");
    expect(block).toContain("\\u003c");
    // The stored JSON decodes back to the EXACT original note (no truncation/mangling).
    expect(JSON.parse(block.trim())[0].note).toBe(evil);

    // Re-open in a fresh browser: the note round-trips fully and the layer still loads.
    const saved = path.join(os.tmpdir(), "cmh_xss_" + Date.now() + ".html");
    fs.writeFileSync(saved, html);
    const ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    try {
      await page2.goto(fileUrl(saved));
      await ready(page2);
      await expect(page2.locator(".cm-card .note")).toHaveText(evil);
      expect(await page2.evaluate(() => window.__commentableHtmlReady === true)).toBe(true);
    } finally {
      await ctx2.close();
      fs.unlinkSync(saved);
    }
  });

  test("Save comments embeds the comment into the downloaded copy", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "embed this note");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnSaveHtml").click(),
    ]);
    const html = await readDownload(download);
    const m = html.match(/id="embeddedComments">([\s\S]*?)<\/script>/);
    expect(m).toBeTruthy();
    expect(JSON.parse(m[1].trim())[0].note).toBe("embed this note");
  });

  test("Save, Portable, and Offline exports exclude comments already listed as handled", async ({ page }) => {
    const inline = stageContent("<section><p>Handled comments must stay gone.</p></section>", {
      key: "cmh-handled-export-inline",
      source: "handled-inline.html",
    });
    const nonportable = stageNonPortable({
      mutate: (html) => html.replace('data-comment-key="commentable-html-nonportable-demo"',
        'data-comment-key="cmh-handled-export-nonportable"'),
    });
    try {
      await page.goto(fileUrl(inline.html));
      await ready(page);
      const inlineCid = await markLiveCommentHandled(page, "handled inline note");
      const [saveDownload] = await Promise.all([
        page.waitForEvent("download"),
        page.locator("#btnSaveHtml").click(),
      ]);
      const savedHtml = await readDownload(saveDownload);
      expect(embeddedComments(savedHtml)).toEqual([]);
      expect(savedHtml).not.toContain(inlineCid);
      expect(savedHtml).not.toContain("handled inline note");

      const [offlineDownload] = await Promise.all([
        page.waitForEvent("download"),
        page.locator("#btnExportOffline").click(),
      ]);
      const offlineHtml = await readDownload(offlineDownload);
      expect(embeddedComments(offlineHtml)).toEqual([]);
      expect(offlineHtml).not.toContain(inlineCid);
      expect(offlineHtml).not.toContain("handled inline note");

      await page.goto(fileUrl(nonportable.html));
      await ready(page);
      const portableCid = await markLiveCommentHandled(page, "handled nonportable note");
      const [portableDownload] = await Promise.all([
        page.waitForEvent("download"),
        page.locator("#btnSaveHtml").click(),
      ]);
      const portableHtml = await readDownload(portableDownload);
      expect(embeddedComments(portableHtml)).toEqual([]);
      expect(portableHtml).not.toContain(portableCid);
      expect(portableHtml).not.toContain("handled nonportable note");
    } finally {
      fs.rmSync(inline.dir, { recursive: true, force: true });
      fs.rmSync(nonportable.dir, { recursive: true, force: true });
    }
  });

  test("embedded comments travel: a shared copy shows them in a fresh browser (no localStorage)", async ({ page, browser }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "traveling comment");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnSaveHtml").click(),
    ]);
    const shared = path.join(os.tmpdir(), "cmh_shared_" + Date.now() + ".html");
    fs.writeFileSync(shared, await readDownload(download));
    const ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    try {
      await page2.goto(fileUrl(shared));
      await page2.waitForFunction(() => window.__commentableHtmlReady === true);
      await expect(page2.locator("#commentList")).toContainText("traveling comment");
    } finally {
      await ctx2.close();
      fs.unlinkSync(shared);
    }
  });

  test("Export plain strips the layer but keeps the content", async ({ page }) => {
    await openInline(page); // 0 comments -> panel closed -> use the toolbar overflow menu
    await openToolbarMenu(page);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.click("#btnSavePlainTop"),
    ]);
    const html = await readDownload(download);
    expect(html).not.toContain('class="cm-toolbar');   // the toolbar DOM is gone
    expect(html).not.toContain('id="sidebar"');         // the sidebar DOM is gone
    expect(html).not.toContain('id="handledCommentIds"');
    expect(html).not.toContain("__commentableHtmlReady"); // the runtime JS is gone
    expect(html).toContain("Commentable HTML demo"); // host content survives
    expect(html).toContain("--cp-bg"); // theme variables kept so it is not unstyled
    // The content styling the skill ships (tables, sections, code, diff, KQL) must
    // survive - "plain" removes the commenting ability, not the styling.
    expect(html).toContain("Default content styling");
    expect(html).toMatch(/#commentRoot\s+table\s*\{/); // an actual content rule, not just the banner comment
  });
});
