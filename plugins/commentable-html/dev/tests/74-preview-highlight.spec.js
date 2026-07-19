import { test, expect } from "@playwright/test";
import { openInline, openComposerFor, distinctCids, storedComments, addTextComment, clickSidebarExport, readDownload } from "./helpers.js";

// CMH-CORE-17: while a NEW text-comment composer is open, the selected text is shown as a
// live preview highlight (mark.cm-preview) so the reviewer sees exactly what the comment
// will anchor to. Saving turns the preview into the real, persisted highlight; cancelling
// (Cancel button or Escape) removes it and stores nothing.
test.describe("composing preview highlight (CMH-CORE-17)", () => {
  test("opening a new-comment composer previews the selection and does not persist it (CMH-CORE-17)", async ({ page }) => {
    await openInline(page);
    const composer = await openComposerFor(page, "#commentRoot section p");

    // A preview highlight appears immediately, before any Save, over the selected text.
    const previewText = await page.$$eval("mark.cm-preview", (els) => els.map((e) => e.textContent).join(""));
    expect(previewText.length).toBeGreaterThan(0);
    // The preview is inert: it carries no data-cid (no comment exists yet) and is not
    // itself a saved highlight, so nothing is stored while composing.
    expect(await page.$$eval("mark.cm-preview", (els) => els.every((e) => !e.dataset.cid))).toBe(true);
    expect(await distinctCids(page)).toBe(0);
    expect(await storedComments(page)).toEqual([]);

    // Saving converts the preview into the real, persisted highlight (one cid group) and
    // the saved highlight covers exactly the text the preview showed (the feature's contract).
    await composer.locator("textarea").fill("preview then keep");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);
    await expect(page.locator("mark.cm-preview")).toHaveCount(0);
    expect(await distinctCids(page)).toBe(1);
    expect((await storedComments(page)).length).toBe(1);
    // The saved highlight covers exactly the previewed text (whitespace-normalized, since a
    // gap-spanning save wraps transparent cm-hl-gap spans the preview omits).
    const norm = (s) => s.replace(/\s+/g, " ").trim();
    const savedText = await page.$$eval("mark.cm-hl", (els) => els.map((e) => e.textContent).join(""));
    expect(norm(savedText)).toBe(norm(previewText));
  });

  test("cancelling the composer removes the preview highlight and stores nothing (CMH-CORE-17)", async ({ page }) => {
    await openInline(page);
    const composer = await openComposerFor(page, "#commentRoot section p");
    await expect(page.locator("mark.cm-preview")).not.toHaveCount(0);

    await composer.locator('[data-act="cancel"]').click();
    await expect(composer).toHaveCount(0);
    await expect(page.locator("mark.cm-preview")).toHaveCount(0);
    await expect(page.locator("mark.cm-hl")).toHaveCount(0);
    expect(await distinctCids(page)).toBe(0);
    expect(await storedComments(page)).toEqual([]);
  });

  test("Escape removes the preview highlight without saving (CMH-CORE-17)", async ({ page }) => {
    await openInline(page);
    const composer = await openComposerFor(page, "#commentRoot section p");
    await expect(page.locator("mark.cm-preview")).not.toHaveCount(0);

    await composer.locator("textarea").press("Escape");
    await expect(composer).toHaveCount(0);
    await expect(page.locator("mark.cm-preview")).toHaveCount(0);
    expect(await distinctCids(page)).toBe(0);
    expect(await storedComments(page)).toEqual([]);
  });

  test("two composers preview at once and each saves to its own anchor (CMH-CORE-17)", async ({ page }) => {
    await openInline(page);
    // Two composers on DIFFERENT paragraphs preview simultaneously. This exercises the core
    // invariant that a preview (which wraps text and splits nodes) stays in the text-offset
    // space so a concurrent composer's stored offsets never cross.
    await openComposerFor(page, "#commentRoot section p", { index: 0 });
    await openComposerFor(page, "#commentRoot section p", { index: 1 });
    const composers = page.locator(".cm-composer");
    await expect(composers).toHaveCount(2);
    await expect(page.locator("mark.cm-preview")).not.toHaveCount(0);
    expect(await distinctCids(page)).toBe(0);

    await composers.nth(0).locator("textarea").fill("first anchor");
    await composers.nth(1).locator("textarea").fill("second anchor");
    // Save the second (last) composer first; the first composer's preview must survive it.
    await composers.nth(1).locator('[data-act="save"]').click();
    await expect(composers).toHaveCount(1);
    await expect(page.locator("mark.cm-preview")).not.toHaveCount(0);
    expect(await distinctCids(page)).toBe(1);

    await composers.nth(0).locator('[data-act="save"]').click();
    await expect(composers).toHaveCount(0);
    await expect(page.locator("mark.cm-preview")).toHaveCount(0);
    expect(await distinctCids(page)).toBe(2);

    // Each comment anchored to its OWN composer's paragraph - the offsets never crossed. Bind
    // by note so a swapped anchor (first note ending up on the second paragraph) fails.
    const stored = await storedComments(page);
    const first = stored.find((c) => c.note === "first anchor");
    const second = stored.find((c) => c.note === "second anchor");
    const paras = await page.$$eval("#commentRoot section p", (els) => els.map((e) => e.textContent));
    expect(first.quote.length).toBeGreaterThan(0);
    expect(second.quote.length).toBeGreaterThan(0);
    expect(paras[0]).toContain(first.quote);
    expect(paras[1]).toContain(second.quote);
    expect(first.quote).not.toBe(second.quote);
  });

  test("an export taken while a composer is open excludes the live preview (CMH-CORE-17)", async ({ page }) => {
    await openInline(page);
    // Save one comment (opens the sidebar), then open a second composer so its preview is
    // live in the DOM at export time.
    await addTextComment(page, "#commentRoot section p", "saved one", 0);
    await openComposerFor(page, "#commentRoot section p", { index: 1 });
    await expect(page.locator("mark.cm-preview")).not.toHaveCount(0);

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const html = await readDownload(download);
    // The transient preview never bakes into the exported file (exports rebuild from a
    // pristine pre-mutation snapshot), while the saved comment does travel with it.
    expect(html).not.toContain('class="cm-preview"');
    expect(html).toContain("saved one");
    // The export did not disturb the live preview - the composer is still open.
    await expect(page.locator("mark.cm-preview")).not.toHaveCount(0);
  });

  test("print media renders the previewed text plainly, not amber (CMH-CORE-17)", async ({ page }) => {
    await openInline(page);
    await openComposerFor(page, "#commentRoot section p");
    await expect(page.locator("mark.cm-preview")).not.toHaveCount(0);

    await page.emulateMedia({ media: "print" });
    // 92-print.css neutralizes the preview highlight to a transparent background in print.
    const bg = await page.locator("mark.cm-preview").first().evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(bg).toBe("rgba(0, 0, 0, 0)");
  });
});
