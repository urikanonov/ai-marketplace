import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import os from "os";
import {
  openInline, addTextComment, openComposerFor, openToolbarMenu, readDownload, fileUrl, ready,
  stageContent, stageInline, stageNonShareable,
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

  // Every provenance meta tag in an exported file, in document order. Matching the whole tag (not
  // just the session id substring) keeps the CMH-SEC-05 assertions from passing because the id
  // happens to appear somewhere else, such as inside the embedded comment JSON.
  function provenanceMeta(html) {
    return (html.match(/<meta[^>]*>/gi) || [])
      .filter((tag) => /name="commentable-html-(session-id|agent)"/i.test(tag));
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

  test("Copy all and Shareable export expose only the source basename (CMH-SEC-03)", async ({ page }) => {
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

  test("every HTML export keeps the authoring session provenance and neither menu offers a strip toggle (CMH-SEC-05)", async ({ page }) => {
    const sessionId = "authoring-session-803";
    const staged = stageContent("<section><p>Authoring provenance.</p></section>", {
      key: "cmh-session-provenance-export",
      source: "authored-provenance.html",
    });
    try {
      const authored = fs.readFileSync(staged.html, "utf8").replace("</head>",
        `<meta name="commentable-html-session-id" content="${sessionId}">\n`
          + '<meta name="commentable-html-agent" content="copilot">\n</head>');
      fs.writeFileSync(staged.html, authored);
      const server = await startStaticServer(staged.dir);
      try {
        await page.goto(server.url + "/test-doc.html");
        await ready(page);
        await expect(page.locator("[data-cmh-retain-session-provenance]")).toHaveCount(0);
        await openToolbarMenu(page);
        await expect(page.locator("#toolbarMenu input")).toHaveCount(0);
        await addTextComment(page, "#commentRoot p", "export this review");
        await openSidebarExportMenu(page);
        await expect(page.locator("#sidebarExportMenu input")).toHaveCount(0);

        for (const selector of ["#btnSaveHtml", "#btnExportOffline", "#btnSavePlain"]) {
          const [download] = await Promise.all([
            page.waitForEvent("download"),
            clickSidebarExport(page, selector),
          ]);
          const html = await readDownload(download);
          expect(provenanceMeta(html), selector).toEqual([
            `<meta name="commentable-html-session-id" content="${sessionId}">`,
            '<meta name="commentable-html-agent" content="copilot">',
          ]);
        }
      } finally {
        await server.close();
      }
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("the NonShareable Shareable export also keeps the authoring session provenance (CMH-SEC-05)", async ({ page }) => {
    // NonShareable exports run through _buildStandaloneHtml, a separate build path from the
    // inline one above, so pin it too.
    const sessionId = "authoring-session-803-nonshareable";
    const staged = stageNonShareable({
      mutate: (html) => html
        .replace('data-comment-key="commentable-html-nonshareable-demo"',
          'data-comment-key="cmh-session-provenance-nonshareable"')
        .replace("</head>",
          `<meta name="commentable-html-session-id" content="${sessionId}">\n`
            + '<meta name="commentable-html-agent" content="copilot">\n</head>'),
    });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("[data-cmh-retain-session-provenance]")).toHaveCount(0);
      await addTextComment(page, "#commentRoot p", "nonshareable provenance note");
      for (const selector of ["#btnSaveHtml", "#btnExportOffline", "#btnSavePlain"]) {
        const [download] = await Promise.all([
          page.waitForEvent("download"),
          clickSidebarExport(page, selector),
        ]);
        const html = await readDownload(download);
        expect(provenanceMeta(html), selector).toEqual([
          `<meta name="commentable-html-session-id" content="${sessionId}">`,
          '<meta name="commentable-html-agent" content="copilot">',
        ]);
      }
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("sidebar export actions live in a single disclosure and Shareable still downloads (CMH-EXP-13)", async ({ page }) => {
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
    const composer = await openComposerFor(page, "#commentRoot section p", { index: 1 });
    await composer.locator("textarea").fill("draft kept behind export menu");
    await openSidebarExportMenu(page);
    await page.keyboard.press("Escape");
    await expect(page.locator("#sidebarExportMenu")).toBeHidden();
    await expect(page.locator("#btnSidebarExportMenu")).toHaveAttribute("aria-expanded", "false");
    await expect(composer).toBeVisible();
    await expect(composer.locator("textarea")).toHaveValue("draft kept behind export menu");
  });

  test("the export menu is content-width with clean menu-item buttons (CMH-EXP-13)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "styling note");
    await openSidebarExportMenu(page);
    const m = await page.evaluate(() => {
      const container = document.querySelector(".cm-sidebar .head-primary");
      const menu = document.getElementById("sidebarExportMenu");
      const btn = menu.querySelector("button");
      const menuBox = menu.getBoundingClientRect();
      const overflow = Math.max(...Array.from(menu.querySelectorAll("button"))
        .map((el) => el.getBoundingClientRect().right - menuBox.right));
      return {
        containerWidth: container.getBoundingClientRect().width,
        menuWidth: menuBox.width,
        menuRight: menuBox.right,
        menuLeft: menuBox.left,
        viewportWidth: window.innerWidth,
        btnBg: getComputedStyle(btn).backgroundColor,
        itemOverflow: overflow,
      };
    });
    // The menu is sized to its content, not stretched to fill the primary row it now lives in.
    expect(m.menuWidth).toBeLessThan(m.containerWidth - 8);
    // It stays on-screen (docked-right sidebar): right edge within the viewport, left edge >= 0.
    expect(m.menuRight).toBeLessThanOrEqual(m.viewportWidth + 1);
    expect(m.menuLeft).toBeGreaterThanOrEqual(-1);
    // No item spills out of the menu box.
    expect(m.itemOverflow).toBeLessThanOrEqual(0.5);
    // Menu-item buttons are transparent at rest (a clean dropdown item, not a bordered button).
    expect(["rgba(0, 0, 0, 0)", "transparent"]).toContain(m.btnBg);
  });

  test("each export shows a centered toast naming the export (CMH-EXP-15)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "toast note");
    // Stub window.print so the PDF export opens no real dialog, and record whether the export toast
    // was already showing (centered, naming PDF) at the moment print was invoked - proving the
    // capture-phase listener fires BEFORE the export handler.
    await page.evaluate(() => {
      window.__toastAtPrint = null;
      window.print = function () {
        const t = document.getElementById("toast");
        window.__toastAtPrint = {
          show: t.classList.contains("show"),
          center: t.classList.contains("cm-toast-center"),
          text: t.textContent || "",
        };
      };
    });
    await openSidebarExportMenu(page);
    // PDF is the one export with no success toast, so its centered "Exporting as PDF" toast (from the
    // capture-phase listener) is the ONLY toast - a non-vacuous check of the announcement itself.
    await clickSidebarExport(page, "#btnPrint");
    const toast = page.locator("#toast");
    await expect(toast).toHaveClass(/\bshow\b/);
    await expect(toast).toHaveClass(/cm-toast-center/);
    await expect(toast).toContainText("Exporting as PDF");
    const atPrint = await page.evaluate(() => window.__toastAtPrint);
    expect(atPrint, "the export toast must be showing before window.print is called").not.toBeNull();
    expect(atPrint.show).toBe(true);
    expect(atPrint.center).toBe(true);
    expect(atPrint.text).toContain("Exporting as PDF");
  });

  test("the export toast is suppressed when an open comment popover swallows the click (CMH-EXP-15)", async ({ page }) => {
    // A document with no `#commentRoot` anchors the layer to `<body>` (CMH-CORE-15), which contains
    // the layer's chrome, so THERE an export control really does sit inside the annotated root -
    // the one configuration in which an open dialog still swallows an export click. That makes this
    // the honest pin for the coupling, with no contrived duplicate-id control.
    const { html } = stageInline({
      mutate: (doc) => doc.replace(/<main id="commentRoot"(?=[^>]*data-comment-key="commentable-html-demo")[^>]*>/,
        '<main id="contentWithoutCommentRoot">'),
    });
    await page.goto(fileUrl(html));
    await ready(page);
    await expect(page.locator("#commentRoot")).toHaveCount(0);
    await addTextComment(page, "main p", "popover guard note", 0);
    // Stub window.print so a PDF export never opens a dialog, and record whether it actually ran.
    await page.evaluate(() => {
      window.__printed = 0;
      window.print = () => { window.__printed += 1; };
    });
    // Open the on-screen comment popover (hover the highlight, click its bubble).
    const cid = await page.locator("mark.cm-hl").first().getAttribute("data-cid");
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await expect(page.locator("#hlBubble")).toBeVisible();
    await page.locator("#hlBubble").click();
    await expect(page.locator(".cm-comment-popover")).toBeVisible();
    // The dismiss listener arms a tick after the dialog opens; let that tick pass before dispatching
    // synthetically, so the assertions below cannot land in the pre-arming window.
    await page.evaluate(() => new Promise((r) => setTimeout(r, 0)));

    // Dispatch and read the toast state SYNCHRONOUSLY in one task: the intent toast auto-hides after
    // 2.5s, so a retrying "not shown" assertion would also pass for a toast that DID announce.
    const suppressed = await page.evaluate(() => {
      const t = document.getElementById("toast");
      t.classList.remove("show", "cm-toast-center");
      t.textContent = "";
      document.getElementById("btnPrint").dispatchEvent(
        new MouseEvent("click", { bubbles: true, cancelable: true, detail: 1 }));
      return { show: t.classList.contains("show"), text: t.textContent || "" };
    });
    expect(suppressed).toEqual({ show: false, text: "" });
    await expect(page.locator(".cm-comment-popover")).toHaveCount(0);
    expect(await page.evaluate(() => window.__printed)).toBe(0);

    // With no popover open, the same click runs the export and the intent toast appears.
    await page.evaluate(() => {
      document.getElementById("btnPrint").dispatchEvent(
        new MouseEvent("click", { bubbles: true, cancelable: true, detail: 1 }));
    });
    expect(await page.evaluate(() => window.__printed)).toBe(1);
    await expect(page.locator("#toast")).toHaveClass(/cm-toast-center/);
    await expect(page.locator("#toast")).toContainText("Exporting as PDF");
  });

  test("an export control in the layer's own chrome is never swallowed by an open popover (CMH-EXP-15)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "chrome export note");
    await page.evaluate(() => {
      window.__printed = 0;
      window.print = () => { window.__printed += 1; };
    });
    const cid = await page.locator("mark.cm-hl").first().getAttribute("data-cid");
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await expect(page.locator("#hlBubble")).toBeVisible();
    await page.locator("#hlBubble").click();
    await expect(page.locator(".cm-comment-popover")).toBeVisible();
    // The dismiss listener arms a tick after the dialog opens; let that tick pass so this proves the
    // chrome carve-out rather than the pre-arming window.
    await page.evaluate(() => new Promise((r) => setTimeout(r, 0)));

    // In a document that HAS a `#commentRoot`, the Export controls sit outside it - layer chrome,
    // not the annotated document - so the dialog closes but the reviewer's FIRST click still runs
    // the export, and it is announced.
    await page.evaluate(() => {
      document.getElementById("btnPrint").dispatchEvent(
        new MouseEvent("click", { bubbles: true, cancelable: true, detail: 1 }));
    });
    await expect(page.locator(".cm-comment-popover")).toHaveCount(0);
    expect(await page.evaluate(() => window.__printed)).toBe(1);
    await expect(page.locator("#toast")).toHaveClass(/cm-toast-center/);
    await expect(page.locator("#toast")).toContainText("Exporting as PDF");
  });

  test("the export toast announces while the comment popover is mid-edit, which never swallows (CMH-EXP-15)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "mid-edit guard note");
    await page.evaluate(() => {
      window.__printed = 0;
      window.print = () => { window.__printed += 1; };
    });
    const cid = await page.locator("mark.cm-hl").first().getAttribute("data-cid");
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();
    // A dialog being edited in place stays open and never swallows the outside click, so the
    // export DOES run - and must therefore be announced, not silently suppressed.
    await pop.locator('[data-act="edit"]').click();
    await expect(pop.locator(".cm-comment-popover-edit")).toHaveCount(1);

    await page.evaluate(() => {
      document.getElementById("btnPrint").dispatchEvent(
        new MouseEvent("click", { bubbles: true, cancelable: true, detail: 1 }));
    });
    await expect(pop).toBeVisible();
    expect(await page.evaluate(() => window.__printed)).toBe(1);
    await expect(page.locator("#toast")).toHaveClass(/cm-toast-center/);
    await expect(page.locator("#toast")).toContainText("Exporting as PDF");
  });

  test("every export control (both menus, all five formats) announces its centered toast label (CMH-EXP-15)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "map coverage note");
    // Let the capture-phase intent-toast listener fire, then swallow the click so no real export
    // (download/print) runs - this keeps the test fast while still exercising the EXPORT_LABELS map
    // for every one of the ten controls, so a missing or wrong entry is caught.
    await page.evaluate(() => {
      document.addEventListener("click", (e) => {
        if (e.target && e.target.closest && e.target.closest("button[id]")) e.stopImmediatePropagation();
      }, true);
    });
    const cases = [
      ["btnSaveHtml", "Shareable"], ["btnSaveHtmlTop", "Shareable"],
      ["btnExportOffline", "Offline"], ["btnExportOfflineTop", "Offline"],
      ["btnExportMd", "Markdown"], ["btnExportMdTop", "Markdown"],
      ["btnSavePlain", "Plain HTML"], ["btnSavePlainTop", "Plain HTML"],
      ["btnPrint", "PDF"], ["btnPrintTop", "PDF"],
    ];
    for (const [id, label] of cases) {
      const shown = await page.evaluate((btnId) => {
        const t = document.getElementById("toast");
        t.classList.remove("show", "cm-toast-center");
        t.textContent = "";
        document.getElementById(btnId).dispatchEvent(
          new MouseEvent("click", { bubbles: true, cancelable: true, detail: 1 }));
        return { text: t.textContent || "", show: t.classList.contains("show"), center: t.classList.contains("cm-toast-center") };
      }, id);
      expect(shown.show, `${id} should show its toast`).toBe(true);
      expect(shown.center, `${id} toast should be centered`).toBe(true);
      expect(shown.text, `${id} should announce "${label}"`).toBe(`Exporting as ${label}...`);
    }
  });

  test("the export toast announces in the window before the popover's dismiss listener is armed (CMH-EXP-15)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "arming window note");
    await page.evaluate(() => {
      window.__printed = 0;
      window.print = () => { window.__printed += 1; };
    });
    const cid = await page.locator("mark.cm-hl").first().getAttribute("data-cid");
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await expect(page.locator("#hlBubble")).toBeVisible();
    // The dialog registers its dismiss listener on the NEXT tick, so a click in the same task opens
    // the dialog while nothing is listening yet: the export runs and must therefore be announced.
    // Both clicks are dispatched in one evaluate, before that timeout can fire.
    await page.evaluate(() => {
      document.getElementById("hlBubble").dispatchEvent(
        new MouseEvent("click", { bubbles: true, cancelable: true, detail: 1 }));
      document.getElementById("btnPrint").dispatchEvent(
        new MouseEvent("click", { bubbles: true, cancelable: true, detail: 1 }));
    });
    await expect(page.locator(".cm-comment-popover")).toBeVisible();
    expect(await page.evaluate(() => window.__printed)).toBe(1);
    await expect(page.locator("#toast")).toHaveClass(/cm-toast-center/);
    await expect(page.locator("#toast")).toContainText("Exporting as PDF");
  });


  test("Save, Shareable, and Offline exports exclude comments already listed as handled", async ({ page }) => {
    const inline = stageContent("<section><p>Handled comments must stay gone.</p></section>", {
      key: "cmh-handled-export-inline",
      source: "handled-inline.html",
    });
    const nonshareable = stageNonShareable({
      mutate: (html) => html.replace('data-comment-key="commentable-html-nonshareable-demo"',
        'data-comment-key="cmh-handled-export-nonshareable"'),
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

      await page.goto(fileUrl(nonshareable.html));
      await ready(page);
      const shareableCid = await markLiveCommentHandled(page, "handled nonshareable note");
      const [shareableDownload] = await Promise.all([
        page.waitForEvent("download"),
        clickSidebarExport(page, "#btnSaveHtml"),
      ]);
      const shareableHtml = await readDownload(shareableDownload);
      expect(embeddedComments(shareableHtml)).toEqual([]);
      expect(shareableHtml).not.toContain(shareableCid);
      expect(shareableHtml).not.toContain("handled nonshareable note");
    } finally {
      fs.rmSync(inline.dir, { recursive: true, force: true });
      fs.rmSync(nonshareable.dir, { recursive: true, force: true });
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
