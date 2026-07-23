import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import os from "os";
import {
  openInline, addTextComment, openToolbarMenu, readDownload, fileUrl, ready,
  stageContent, stageNonPortable,
  openSidebarExportMenu, installClipboardCapture, lastCopied,
  clickSidebarExport, startStaticServer,
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
      clickSidebarExport(page, "#btnSaveHtml"),
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
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const html = await readDownload(download);
    const m = html.match(/id="embeddedComments">([\s\S]*?)<\/script>/);
    expect(m).toBeTruthy();
    expect(JSON.parse(m[1].trim())[0].note).toBe("embed this note");
  });

  test("Copy all and Portable export expose only the source basename (CMH-SEC-03)", async ({ page }) => {
    const sensitiveSource = String.raw`C:\Users\alice\Internal Project\reports\quarterly.html`;
    const staged = stageContent(
      '<section><p id="provenance">Review this provenance.</p></section>',
      { key: "cmh-provenance-basename", source: sensitiveSource },
    );
    try {
      const authored = fs.readFileSync(staged.html, "utf8").replace(
        '<main id="commentRoot"',
        `<meta content=' id="commentRoot"'>\n`
          + `<main title='Section > Overview data-doc-source="C:\\\\Template\\\\literal.html"' `
          + 'id="comment&#82;oot"',
      ).replace(
        `data-doc-source="${sensitiveSource}"`,
        "data-doc-source=\"C:&#92;Users&#92;alice&#92;Internal Project&#92;reports&#92;quarterly.html\"",
      );
      const bodyEnd = authored.toLowerCase().lastIndexOf("</body>");
      const withLiteral = authored.slice(0, bodyEnd)
        + `<script>window.__sourceLiteral = '<main id="commentRoot" data-doc-source="C:\\\\Template\\\\literal.html">';</script>\n`
        + authored.slice(bodyEnd);
      const withSentinels = "<!--license-sentinel-->\n" + withLiteral + "\n<!--tail-sentinel-->\n";
      fs.writeFileSync(staged.html, withSentinels);
      const server = await startStaticServer(staged.dir);
      try {
        await installClipboardCapture(page);
        await page.goto(server.url + "/test-doc.html");
        await ready(page);
        await addTextComment(page, "#provenance", "check provenance");
        await page.click("#btnCopyAll");
        const bundle = await lastCopied(page);
        expect(bundle).toContain("Source: quarterly.html");
        expect(bundle).not.toContain("alice");
        expect(bundle).not.toContain("Internal Project");

        const [download] = await Promise.all([
          page.waitForEvent("download"),
          clickSidebarExport(page, "#btnSaveHtml"),
        ]);
        const html = await readDownload(download);
        expect(html).toContain('data-doc-source="quarterly.html"');
        expect(html).toContain(`title='Section > Overview data-doc-source="C:\\\\Template\\\\literal.html"'`);
        expect(html).toContain("<!--license-sentinel-->");
        expect(html).toContain("<!--tail-sentinel-->");
        expect(html).toContain(String.raw`data-doc-source="C:\\Template\\literal.html"`);
        expect(html).not.toContain("alice");
        expect(html).not.toContain("Internal Project");
      } finally {
        await server.close();
      }
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("HTML exports strip authoring session provenance by default (CMH-SEC-05)", async ({ page }) => {
    const sessionId = "private-session-622";
    const staged = stageContent("<section><p>Private provenance.</p></section>", {
      key: "cmh-session-provenance-export",
      source: "private-provenance.html",
    });
    try {
      const authored = fs.readFileSync(staged.html, "utf8").replace("</head>",
        `<meta name="commentable-html-session&#45;id" content="${sessionId}">\n`
          + '<meta name="commentable-html-agent" content="copilot">\n</head>');
      fs.writeFileSync(staged.html, authored);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addTextComment(page, "#commentRoot p", "export this review");

      for (const selector of ["#btnSaveHtml", "#btnExportOffline", "#btnSavePlain"]) {
        const [download] = await Promise.all([
          page.waitForEvent("download"),
          clickSidebarExport(page, selector),
        ]);
        expect(await readDownload(download)).not.toContain(sessionId);
      }
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("a reviewer can explicitly retain session provenance in an HTML export (CMH-SEC-05)", async ({ page }) => {
    const sessionId = "private-session-retained-622";
    const staged = stageContent("<section><p>Private provenance.</p></section>", {
      key: "cmh-session-provenance-retain",
      source: "private-provenance.html",
    });
    try {
      const authored = fs.readFileSync(staged.html, "utf8").replace("</head>",
        `<meta name="commentable-html-session-id" content="${sessionId}">\n</head>`);
      fs.writeFileSync(staged.html, authored);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addTextComment(page, "#commentRoot p", "retain this provenance");
      await openSidebarExportMenu(page);
      await page.locator("[data-cmh-retain-session-provenance]").last().check();
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        clickSidebarExport(page, "#btnSaveHtml"),
      ]);
      expect(await readDownload(download)).toContain(sessionId);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("sidebar export actions live in a single disclosure and Portable still downloads (CMH-EXP-13)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "menu export note");
    await expect(page.locator("#btnSidebarExportMenu")).toBeVisible();
    await expect(page.locator("#btnSidebarExportMenu")).toHaveAttribute("aria-expanded", "false");
    for (const id of ["btnSaveHtml", "btnExportOffline", "btnSavePlain", "btnExportMd", "btnPrint"]) {
      await expect(page.locator("#" + id)).toBeHidden();
    }
    const roles = await page.locator("#sidebarExportMenu, #sidebarExportMenu button").evaluateAll((els) =>
      els.map((el) => el.getAttribute("role")));
    expect(roles.every((role) => role !== "menu" && role !== "menuitem")).toBe(true);
    await openSidebarExportMenu(page);
    await expect(page.locator("#btnSidebarExportMenu")).toHaveAttribute("aria-expanded", "true");
    await expect(page.locator("#sidebarExportMenu")).toBeVisible();
    for (const id of ["btnSaveHtml", "btnExportOffline", "btnSavePlain", "btnExportMd", "btnPrint"]) {
      await expect(page.locator("#" + id)).toBeVisible();
    }
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const html = await readDownload(download);
    expect(embeddedComments(html)[0].note).toBe("menu export note");
  });

  test("Escape closes only the sidebar export disclosure before a composer draft (CMH-EXP-13)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "menu priority note");
    await page.locator('.cm-card [data-act="edit"]').first().click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("draft kept behind export menu");
    await openSidebarExportMenu(page);
    await page.keyboard.press("Escape");
    await expect(page.locator("#sidebarExportMenu")).toBeHidden();
    await expect(page.locator("#btnSidebarExportMenu")).toHaveAttribute("aria-expanded", "false");
    await expect(composer).toBeVisible();
    await expect(composer.locator("textarea")).toHaveValue("draft kept behind export menu");
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
        clickSidebarExport(page, "#btnSaveHtml"),
      ]);
      const savedHtml = await readDownload(saveDownload);
      expect(embeddedComments(savedHtml)).toEqual([]);
      expect(savedHtml).not.toContain(inlineCid);
      expect(savedHtml).not.toContain("handled inline note");

      const [offlineDownload] = await Promise.all([
        page.waitForEvent("download"),
        clickSidebarExport(page, "#btnExportOffline"),
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
        clickSidebarExport(page, "#btnSaveHtml"),
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
      clickSidebarExport(page, "#btnSaveHtml"),
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
