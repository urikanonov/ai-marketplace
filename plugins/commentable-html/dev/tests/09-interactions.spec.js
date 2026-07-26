import { test, expect } from "@playwright/test";
import {
  openKitchenSink, addTextComment, openComposerFor, selectText, distinctCids, realDragSelect,
  allCids, stageContent, fileUrl, ready, storedComments,
} from "./helpers.js";

test.describe("comment interactions", () => {
  test("a genuine pointer drag selects text and pops the Add-comment menu", async ({ page }) => {
    await openKitchenSink(page);
    // No synthetic selection: a real mouse down/move/up produces the browser
    // selection and the native mouseup that the layer listens for.
    await realDragSelect(page, "#commentRoot section p");
    await expect(page.locator("#menuComment")).toBeVisible();
    await page.locator("#menuComment").click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("added via a real drag");
    await composer.locator('[data-act="save"]').click();
    await expect(page.locator("#commentList")).toContainText("added via a real drag");
    expect(await distinctCids(page)).toBe(1);
  });

  test("a native right-click on a real drag selection opens the Add-comment menu", async ({ page }) => {
    await openKitchenSink(page);
    const { midX, midY } = await realDragSelect(page, "#commentRoot section p");
    // Wait for the drag's own mouseup to pop the menu, then hide it (selection is
    // kept) so the assertion below proves the native right-click path re-opened it.
    await expect(page.locator("#menuComment")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator("#menuComment")).toBeHidden();
    await page.mouse.click(midX, midY, { button: "right" });
    await expect(page.locator("#menuComment")).toBeVisible();
    await page.locator("#menuComment").click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("added via native right-click");
    await composer.locator('[data-act="save"]').click();
    await expect(page.locator("#commentList")).toContainText("added via native right-click");
    expect(await distinctCids(page)).toBe(1);
  });

  test("right-click on a selection opens the Add-comment menu", async ({ page }) => {
    await openKitchenSink(page);
    const composer = await openComposerFor(page, "#commentRoot section p", { event: "contextmenu" });
    await expect(composer).toBeVisible();
    await composer.locator("textarea").fill("added via right-click");
    await composer.locator('[data-act="save"]').click();
    await expect(page.locator("#commentList")).toContainText("added via right-click");
    expect(await distinctCids(page)).toBe(1);
  });

  test("editing a comment updates its note and marks it edited", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "original note");
    await page.locator('.cm-card [data-act="edit"]').first().click();
    const editor = page.locator(".cm-card .cm-entry-root .cm-reply-compose");
    await expect(editor.locator("textarea")).toHaveValue("original note");
    await editor.locator("textarea").fill("edited note");
    await editor.locator(".cm-reply-save").click();
    await expect(page.locator("#commentList")).toContainText("edited note");
    await expect(page.locator("#commentList")).not.toContainText("original note");
    await expect(page.locator(".cm-card .meta")).toContainText(/edited/i);
  });

  test("RTL timestamps isolate dates in cards, replies, popovers, and board summaries (CMH-SIDE-10)", async ({ page }) => {
    const { html } = stageContent(`
      <section><h2>RTL timestamps</h2><p>Comment target text.</p></section>
      <div class="board cm-skip" data-cm-widget="rtl-board" data-cm-draggable aria-label="RTL board">
        <div data-cm-slot="Now"><div data-cm-part="rtl-card">Card</div></div>
        <div data-cm-slot="Later" id="rtl-later"></div>
      </div>`, { key: "cmh-rtl-timestamps" });
    await page.goto(fileUrl(html));
    await ready(page);
    await page.evaluate(() => { document.documentElement.dir = "rtl"; });
    await addTextComment(page, "#commentRoot section p", "RTL timestamp");
    await page.locator('.cm-card [data-act="edit"]').first().click();
    const rtlEditor = page.locator(".cm-card .cm-entry-root .cm-reply-compose");
    await rtlEditor.locator("textarea").fill("RTL timestamp edited");
    await rtlEditor.locator(".cm-reply-save").click();

    const cardMeta = page.locator(".cm-card .meta > span").first();
    await expect(cardMeta.locator("bdi")).toHaveCount(1);
    await expect(cardMeta.locator("bdi")).not.toContainText("edited");
    expect(await cardMeta.locator("bdi").evaluate((el) => el.nextSibling && el.nextSibling.textContent)).toBe(" (edited)");

    await page.locator(".cm-card .cm-reply-btn").first().click();
    await page.locator(".cm-reply-compose").last().locator("textarea").fill("RTL reply");
    await page.locator(".cm-reply-compose").last().locator(".cm-reply-save").click();
    await page.locator('.cm-reply [data-act="reply-edit"]').click();
    await page.locator(".cm-reply-compose").last().locator("textarea").fill("RTL reply edited");
    await page.locator(".cm-reply-compose").last().locator(".cm-reply-save").click();
    const replyMeta = page.locator(".cm-reply .meta > span").first();
    await expect(replyMeta.locator("bdi")).toHaveCount(1);
    await expect(replyMeta.locator("bdi")).not.toContainText("edited");
    expect(await replyMeta.locator("bdi").evaluate((el) => el.nextSibling && el.nextSibling.textContent)).toBe(" (edited)");

    const cid = (await allCids(page))[0];
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const popMeta = page.locator(".cm-comment-popover-meta");
    await expect(popMeta.locator("bdi")).toHaveCount(1);
    await expect(popMeta.locator("bdi")).not.toContainText("edited");
    expect(await popMeta.locator("bdi").evaluate((el) => el.nextSibling && el.nextSibling.textContent)).toBe(" (edited)");

    await page.evaluate(() => new Promise((resolve) => {
      document.getElementById("rtl-later").appendChild(document.querySelector('[data-cm-part="rtl-card"]'));
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    }));
    const summaryMeta = page.locator(".cm-card-state .meta > span").first();
    await expect(summaryMeta.locator("bdi")).toHaveCount(1);
    await expect(summaryMeta.locator("bdi")).toContainText(/\d{4}/);
  });

  test("deleting one comment leaves the others", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "keep me", 0);
    await addTextComment(page, "#commentRoot section p", "delete me", 1);
    expect(await distinctCids(page)).toBe(2);
    page.on("dialog", (d) => d.accept());
    const del = page.locator('.cm-card', { hasText: "delete me" }).locator('[data-act="del"]');
    await del.click();
    expect(await distinctCids(page)).toBe(1);
    await expect(page.locator("#commentList")).toContainText("keep me");
    await expect(page.locator("#commentList")).not.toContainText("delete me");
  });

  test("clicking a highlight activates its card", async ({ page }) => {
    await openKitchenSink(page);
    // Comment on the entities paragraph (plain text, no link).
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "activate me");
    const cid = (await allCids(page))[0];
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().click();
    // The activated card is exactly the clicked comment's card (cid-mapped).
    await expect(page.locator(`.cm-card.active[data-cid="${cid}"]`)).toHaveCount(1);
    await expect(page.locator(".cm-card.active")).toContainText("activate me");
  });

  test("the comment bubble opens a comment on a link-wrapped highlight without navigating", async ({ page }) => {
    await openKitchenSink(page);
    // The first inline-soup paragraph contains a real <a>; the highlight wraps its text.
    await addTextComment(page, "#commentRoot section:nth-of-type(1) p", "on a link");
    const url = page.url();
    const linkMark = page.locator('a[data-testid="sample-link"] mark.cm-hl');
    await expect(linkMark).toHaveCount(1); // the highlight actually wraps the link text
    await linkMark.hover();
    const bubble = page.locator("#hlBubble");
    await expect(bubble).toBeVisible();
    await bubble.click();
    await expect(page.locator(".cm-card.active")).toContainText("on a link");
    expect(page.url()).toBe(url); // did NOT follow the link
  });

  test("CMH-CORE-16: the bubble opens an inline comment dialog with an Edit button and still opens the sidebar", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "inline dialog note");
    const cid = (await allCids(page))[0];
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    const bubble = page.locator("#hlBubble");
    await expect(bubble).toBeVisible();
    await bubble.click();

    // The inline on-screen dialog shows the note and an Edit button.
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();
    await expect(pop).toContainText("inline dialog note");
    await expect(pop.locator('[data-act="edit"]')).toBeVisible();
    // Focus moves into the dialog (its Edit button) on open.
    await expect(pop.locator('[data-act="edit"]')).toBeFocused();
    // The dialog is a labelled dialog whose note is associated via aria-describedby.
    await expect(pop).toHaveAttribute("role", "dialog");
    const noteId = await pop.locator(".cm-comment-popover-note").getAttribute("id");
    expect(noteId).toBeTruthy();
    expect(await pop.getAttribute("aria-describedby")).toBe(noteId);

    // The existing sidebar jump still fires alongside the dialog.
    await expect(page.locator(".cm-card.active")).toContainText("inline dialog note");

    // Edit turns the dialog into an editor IN PLACE - it does not close, and no floating composer opens.
    await pop.locator('[data-act="edit"]').click();
    await expect(pop).toBeVisible();
    await expect(page.locator(".cm-composer")).toHaveCount(0);
    await expect(pop.locator(".cm-comment-popover-edit textarea")).toHaveValue("inline dialog note");
  });

  test("CMH-CORE-16: the dialog Edit edits in place, stays put, and Escape cancels back to the note", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "edit me in place");
    const cid = (await allCids(page))[0];
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();
    const before = await pop.boundingBox();
    const scrollBefore = await page.evaluate(() => window.scrollY);

    await pop.locator('[data-act="edit"]').click();
    const ta = pop.locator(".cm-comment-popover-edit textarea");
    await expect(ta).toBeFocused();
    // The editor opens WHERE the reader clicked: same dialog, same anchor column, no scrolling.
    const after = await pop.boundingBox();
    expect(Math.abs(after.x - before.x)).toBeLessThan(2);
    expect(await page.evaluate(() => window.scrollY)).toBe(scrollBefore);

    // A click outside does not close (or discard) the dialog while it is being edited.
    await ta.fill("dialog draft");
    await page.mouse.click(5, 5);
    await expect(pop).toBeVisible();
    await expect(ta).toHaveValue("dialog draft");

    // Escape cancels the edit back to the note view (the dialog stays open); Escape again closes it.
    await ta.focus();
    await page.keyboard.press("Escape");
    await expect(pop).toBeVisible();
    await expect(pop.locator(".cm-comment-popover-edit")).toHaveCount(0);
    await expect(pop.locator(".cm-comment-popover-note")).toContainText("edit me in place");
    await expect(pop.locator('[data-act="edit"]')).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(pop).toBeHidden();

    // Saving in place updates the note, the sidebar card, and storage, and returns to the note view.
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    await pop.locator('[data-act="edit"]').click();
    await pop.locator(".cm-comment-popover-edit textarea").fill("edited in the dialog");
    await pop.locator('[data-act="edit-save"]').click();
    await expect(pop).toBeVisible();
    await expect(pop.locator(".cm-comment-popover-edit")).toHaveCount(0);
    await expect(pop.locator(".cm-comment-popover-note")).toContainText("edited in the dialog");
    await expect(pop.locator(".cm-comment-popover-meta")).toContainText("(edited)");
    await expect(page.locator("#commentList")).toContainText("edited in the dialog");
    expect((await storedComments(page))[0].note).toBe("edited in the dialog");
  });

  test("CMH-UI-12: the Open comment hover bubble is a comfortably large click target", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "bubble target");
    const cid = (await allCids(page))[0];
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    const bubble = page.locator("#hlBubble");
    await expect(bubble).toBeVisible();
    const box = await bubble.boundingBox();
    expect(box.width).toBeGreaterThanOrEqual(28);
    expect(box.height).toBeGreaterThanOrEqual(28);
    // The glyph grows with it, so the bigger button is not a small icon in a large disc.
    const icon = await bubble.locator("svg").boundingBox();
    expect(icon.width).toBeGreaterThanOrEqual(15);
  });

  test("CMH-CORE-16: clicking anywhere else closes the inline dialog and swallows the click", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "swallow me");
    const cid = (await allCids(page))[0];
    // A probe link outside the dialog whose activation would change the URL hash.
    await page.evaluate(() => {
      const a = document.createElement("a");
      a.id = "cmh-probe"; a.href = "#navigated"; a.textContent = "probe";
      a.style.position = "fixed"; a.style.top = "4px"; a.style.left = "4px"; a.style.zIndex = "5";
      document.body.appendChild(a);
    });
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();

    const url = page.url();
    await page.locator("#cmh-probe").click();
    await expect(pop).toBeHidden();
    expect(page.url()).toBe(url); // the outside click did NOT activate the probe link
  });

  test("CMH-CORE-16: a keyboard-activated outside click closes the dialog but is not swallowed", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "keyboard me");
    const cid = (await allCids(page))[0];
    // A probe link outside the dialog; activating it by keyboard should still work.
    await page.evaluate(() => {
      const a = document.createElement("a");
      a.id = "cmh-kprobe"; a.href = "#navk"; a.textContent = "probe";
      a.style.position = "fixed"; a.style.top = "4px"; a.style.left = "4px"; a.style.zIndex = "5";
      document.body.appendChild(a);
    });
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();

    // A keyboard activation (Enter on a focused link) is a detail-0 click: it closes the dialog
    // but is NOT swallowed, so the link still activates (keyboard users are not blocked).
    await page.locator("#cmh-kprobe").focus();
    await page.keyboard.press("Enter");
    await expect(pop).toBeHidden();
    await expect.poll(() => page.evaluate(() => location.hash)).toBe("#navk");
  });

  test("CMH-CORE-16: Escape and scrolling the anchor out of view close the inline dialog", async ({ page }) => {    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(1) p", "escape me");
    const cid = (await allCids(page))[0];
    const openPop = async () => {
      await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
      await page.locator("#hlBubble").click();
      await expect(page.locator(".cm-comment-popover")).toBeVisible();
    };
    const pop = page.locator(".cm-comment-popover");

    await openPop();
    await page.keyboard.press("Escape");
    await expect(pop).toBeHidden();

    // Scrolling the anchored highlight out of view closes the dialog instead of leaving it
    // stuck clamped to a viewport edge.
    await page.evaluate(() => window.scrollTo(0, 0));
    await openPop();
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(pop).toBeHidden();
  });

  test("jump scrolls the document to a highlight that is off-screen", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(1) p", "top comment");
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    // Precondition: after scrolling to the bottom the highlight is actually off-screen,
    // so the post-jump visibility assertion proves jump did the scrolling.
    const offBefore = await page.locator("mark.cm-hl").first().evaluate((el) => {
      const r = el.getBoundingClientRect();
      return r.bottom < 0 || r.top > window.innerHeight;
    });
    expect(offBefore, "highlight is off-screen before jump").toBe(true);
    await page.locator('.cm-card [data-act="jump"]').first().click();
    await expect.poll(async () =>
      page.locator("mark.cm-hl").first().evaluate((el) => {
        const r = el.getBoundingClientRect();
        return r.top >= 0 && r.top <= window.innerHeight;
      })).toBe(true);
  });

  test("two composers can be open at once", async ({ page }) => {
    await openKitchenSink(page);
    await selectText(page, "#commentRoot section p", { index: 0 });
    await page.locator("#menuComment").click();
    const first = page.locator(".cm-composer").first();
    await expect(first).toBeVisible();
    // Drag the first composer to a corner so it does not sit over the next menu.
    const handle = first.locator(".cm-composer-handle");
    const box = await handle.boundingBox();
    await page.mouse.move(box.x + 5, box.y + 5);
    await page.mouse.down();
    await page.mouse.move(30, 60, { steps: 5 });
    await page.mouse.up();

    await selectText(page, "#commentRoot section p", { index: 1 });
    await page.locator("#menuComment").click();
    await expect(page.locator(".cm-composer")).toHaveCount(2);
    const composers = page.locator(".cm-composer");
    await composers.nth(0).locator("textarea").fill("first composer");
    await composers.nth(1).locator("textarea").fill("second composer");
    // Save the second while both exist, then the first (indices shift as each closes).
    await composers.nth(1).locator('[data-act="save"]').click();
    await page.locator(".cm-composer").locator('[data-act="save"]').click();
    await expect(page.locator(".cm-composer")).toHaveCount(0);
    expect(await distinctCids(page)).toBe(2);
    await expect(page.locator("#commentList")).toContainText("first composer");
    await expect(page.locator("#commentList")).toContainText("second composer");
  });
});
