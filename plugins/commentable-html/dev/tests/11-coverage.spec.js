import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import { PYTHON } from "./helpers.js";
import fs from "fs";
import os from "os";
import path from "path";
import {
  openInline, openNonPortable, openKitchenSink, addTextComment, openComposerFor,
  openToolbarMenu, markTextForCid, distinctCids, ready, fileUrl, selectText,
  startStaticServer, routeMermaidLocal, installClipboardCapture, readDownload,
  stageNonPortable, SKILL,
} from "./helpers.js";

test.describe("targeted coverage gaps", () => {
  test("anchors to the correct occurrence when the same phrase repeats", async ({ page }) => {
    await openKitchenSink(page);
    // The fixture has two paragraphs (#dup-a, #dup-b) with byte-identical text.
    // Commenting the second must highlight the second, not the first.
    await addTextComment(page, "#dup-b", "second occurrence");
    expect(await distinctCids(page)).toBe(1);
    expect(await page.locator("#dup-b mark.cm-hl").count()).toBeGreaterThan(0);
    expect(await page.locator("#dup-a mark.cm-hl").count()).toBe(0);
    // Survives a reload on the same occurrence.
    await page.reload();
    await ready(page);
    expect(await page.locator("#dup-b mark.cm-hl").count()).toBeGreaterThan(0);
    expect(await page.locator("#dup-a mark.cm-hl").count()).toBe(0);
  });

  test("an RTL selection anchors to exactly the selected text", async ({ page }) => {
    await openKitchenSink(page);
    await selectText(page, '#commentRoot p[dir="rtl"]');
    // Capture the quote while the selection is live (the menu click clears it).
    const quote = await page.evaluate(() => window.getSelection().toString());
    await page.locator("#menuComment").click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("rtl note");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);
    const cid = await page.locator(".cm-card").first().getAttribute("data-cid");
    // The rtl paragraph spans a source newline that renders as a single space, so
    // selection.toString() collapses whitespace the marks preserve: compare on the
    // visible text (whitespace-normalized), which still proves the anchor is correct.
    const norm = (s) => s.replace(/\s+/g, " ").trim();
    expect(norm(await markTextForCid(page, cid))).toBe(norm(quote));
  });

  test("Escape closes the overflow menu first, leaving an open composer intact", async ({ page }) => {
    await openKitchenSink(page);
    const composer = await openComposerFor(page, "#commentRoot section p");
    await composer.locator("textarea").fill("keep me while the menu closes");
    await openToolbarMenu(page);
    await page.keyboard.press("Escape");
    // The menu closed; the composer is still open and still holds its text.
    await expect(page.locator("#toolbarMenu")).toBeHidden();
    await expect(composer).toBeVisible();
    await expect(composer.locator("textarea")).toHaveValue("keep me while the menu closes");
    // A second Escape now discards the composer.
    await page.keyboard.press("Escape");
    await expect(composer).toHaveCount(0);
    expect(await distinctCids(page)).toBe(0);
  });

  test("the sidebar shows an empty state, hides it on add, and restores it on clear", async ({ page }) => {
    await openInline(page);
    await page.locator("#btnToggleSidebar").click();
    await expect(page.locator(".cm-empty")).toBeVisible();
    await expect(page.locator(".cm-empty")).toContainText(/No comments yet/i);

    await addTextComment(page, "#commentRoot section p", "fills the list");
    await expect(page.locator(".cm-empty")).toHaveCount(0);
    await expect(page.locator("#sidebarCount")).toHaveText("1");

    await page.locator("#btnClearAll").click();
    await page.locator(".cm-modal").getByRole("button", { name: "OK" }).click();
    await expect(page.locator(".cm-card")).toHaveCount(0);
    await expect(page.locator(".cm-empty")).toBeVisible();
    await expect(page.locator("#sidebarCount")).toHaveText("0");
    await expect(page.locator("#toolbarCount")).toHaveText("0");
  });

  test("mode badge reflects document type in both directions", async ({ page }) => {
    // Inline documents are standalone; nonportable documents load assets from companions.
    await openInline(page);
    await openToolbarMenu(page);
    await expect(page.locator("#cmhModeBadge")).toHaveText("Portable");

    await openNonPortable(page);
    await openToolbarMenu(page);
    await expect(page.locator("#cmhModeBadge")).toHaveText("Not portable");
  });

  test("a mermaid comment left unhandled restores its ring on the same node on reload", async ({ page }) => {
    const server = await startStaticServer(SKILL);
    try {
      await routeMermaidLocal(page);
      await installClipboardCapture(page);
      await page.goto(server.url + "/dist/PORTABLE.html?mermaid=1");
      await ready(page);

      // Deliberately comment a NON-first node so "always rings the first node" cannot pass.
      const nodes = page.locator("#commentRoot .mermaid svg g.node");
      await expect(nodes.first()).toBeVisible({ timeout: 20000 });
      const node = nodes.nth(1);
      const label = (await node.textContent()).trim();
      await node.hover();
      await page.locator("#mermaidAddBtn").click();
      const composer = page.locator(".cm-composer").last();
      await composer.locator("textarea").fill("unhandled mermaid note");
      await composer.locator('[data-act="save"]').click();
      await expect(composer).toHaveCount(0);
      const cid = await page.locator(".cm-card").first().getAttribute("data-cid");
      const ring = page.locator(`#commentRoot .mermaid .cm-mermaid-hl[data-cid="${cid}"]`);
      await expect(ring).toBeVisible();
      expect((await ring.textContent()).trim()).toBe(label);

      await page.reload();
      await ready(page);
      await expect(page.locator("#commentRoot .mermaid svg g.node").first()).toBeVisible({ timeout: 20000 });
      // Not marked handled, so it persists: card, count and the ring return on the SAME node.
      await expect(page.locator("#commentList")).toContainText("unhandled mermaid note");
      await expect(page.locator("#toolbarCount")).toHaveText("1");
      await expect(page.locator("#commentRoot .mermaid .cm-mermaid-hl")).toHaveCount(1);
      const ring2 = page.locator(`#commentRoot .mermaid .cm-mermaid-hl[data-cid="${cid}"]`);
      await expect(ring2).toBeVisible();
      expect((await ring2.textContent()).trim()).toBe(label);
    } finally {
      await server.close();
    }
  });

  test("a whitespace-only selection is rejected (no menu, no phantom comment)", async ({ page }) => {
    await openKitchenSink(page);
    // Positive control: a real text selection DOES pop the menu, so the mouseup
    // listener is wired and the negative assertion below is meaningful.
    await selectText(page, "#commentRoot section p");
    await expect(page.locator("#menuComment")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator("#menuComment")).toBeHidden();

    // Now select a run of whitespace only and fire the same mouseup the layer listens for.
    const selected = await page.evaluate(() => {
      const root = document.getElementById("commentRoot");
      const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let n;
      while ((n = w.nextNode())) {
        const m = /\s{2,}/.exec(n.data);
        if (m && n.parentElement && !n.parentElement.closest(".cm-skip")) {
          const r = document.createRange();
          r.setStart(n, m.index);
          r.setEnd(n, m.index + m[0].length);
          const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
          n.parentElement.scrollIntoView({ block: "center" });
          n.parentElement.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 30, clientY: 30 }));
          return s.toString().trim() === "";
        }
      }
      return null;
    });
    expect(selected, "found a whitespace-only run to select").toBe(true);
    await page.evaluate(() => new Promise((r) => setTimeout(r, 0))); // drain the mouseup setTimeout(0)
    await expect(page.locator("#menuComment")).toBeHidden();
    expect(await distinctCids(page)).toBe(0);
    await expect(page.locator("#toolbarCount")).toHaveText("0");
  });

  test("Export with embedded comments produces a standalone file when the nonportable doc is served over HTTP", async ({ page, context }) => {
    test.slow(); // static server + http fetch in _getBaseHtml + python validate under parallel load
    let server, dir;
    try {
      const staged = stageNonPortable();
      dir = staged.dir;
      server = await startStaticServer(dir);
      await installClipboardCapture(page);
      await page.goto(server.url + "/" + path.basename(staged.html));
      await ready(page);
      await openToolbarMenu(page);

      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.click("#btnSaveHtmlTop"),
      ]);
      const out = await readDownload(download);
      expect(out).not.toMatch(/<script\b[^>]*\bsrc\s*=\s*["'][^"']*commentable-html/i);
      expect(out).toContain("BEGIN: commentable-html v2 - JS");

      const tmp = path.join(os.tmpdir(), "cmh_http_standalone_" + Date.now() + ".html");
      fs.writeFileSync(tmp, out);
      let page2;
      try {
        execFileSync(PYTHON, ["tools/validate.py", tmp], { cwd: SKILL });
        page2 = await context.newPage();
        await page2.goto(fileUrl(tmp));
        await ready(page2);
        expect(await page2.evaluate(() => document.body.classList.contains("cm-nonportable"))).toBe(false);
      } finally {
        if (page2) await page2.close();
        fs.rmSync(tmp, { force: true });
      }
    } finally {
      if (server) await server.close();
      if (dir) fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
