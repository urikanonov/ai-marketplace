import { test, expect } from "@playwright/test";
import {
  openKitchenSink, addTextComment, openComposerFor, selectText, distinctCids, realDragSelect,
  allCids, stageContent, fileUrl, ready, storedComments,
} from "./helpers.js";

test.describe("comment interactions", () => {
  // Select EXACTLY an existing highlight's text and pop the menu, so the layer resolves it to that
  // comment (the same stored offsets) and re-opens it for editing instead of starting a new one.
  async function reselectHighlight(page, cid) {
    await page.evaluate((id) => {
      // A comment's range can span several inline elements, so it paints as SEVERAL marks sharing
      // the cid: select from the first one's first text node to the last one's last text node.
      const marks = Array.prototype.slice.call(document.querySelectorAll(`mark.cm-hl[data-cid="${id}"]`));
      if (!marks.length) throw new Error("no highlight for cid " + id);
      const textIn = (el, last) => {
        const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        let n = w.nextNode(), found = n;
        while (last && (n = w.nextNode())) found = n;
        return found;
      };
      marks[0].scrollIntoView({ block: "center" });
      const first = textIn(marks[0], false);
      const end = textIn(marks[marks.length - 1], true);
      const range = document.createRange();
      range.setStart(first, 0);
      range.setEnd(end, end.data.length);
      const s = window.getSelection();
      s.removeAllRanges();
      s.addRange(range);
      marks[0].dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 40, clientY: 40 }));
    }, cid);
  }

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
    // The editor replaces the described note, so the stale description is dropped; the field carries
    // its own accessible name instead.
    await expect(pop).not.toHaveAttribute("aria-describedby", /.*/);
    await expect(ta).toHaveAttribute("aria-label", "Edit comment");
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
    await expect(pop).toHaveAttribute("aria-describedby", /.+/);
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

  test("CMH-CORE-16: a dirty in-place edit is not swallowed, switched away, or duplicated (CMH-THREAD-10)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "first note", 0);
    await addTextComment(page, "#commentRoot section p", "second note", 1);
    const cids = await allCids(page);
    expect(cids.length).toBe(2);
    // A probe link outside the dialog whose activation is observable.
    await page.evaluate(() => {
      const a = document.createElement("a");
      a.id = "cmh-eprobe"; a.href = "#edited-probe"; a.textContent = "probe";
      a.style.position = "fixed"; a.style.top = "4px"; a.style.left = "4px"; a.style.zIndex = "5";
      document.body.appendChild(a);
    });
    await page.locator(`mark.cm-hl[data-cid="${cids[0]}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await pop.locator('[data-act="edit"]').click();
    const ta = pop.locator(".cm-comment-popover-edit textarea");
    await ta.fill("dirty draft");

    // An outside click mid-edit keeps the draft AND is not swallowed (the probe link activates).
    await page.locator("#cmh-eprobe").click();
    await expect.poll(() => page.evaluate(() => location.hash)).toBe("#edited-probe");
    await expect(ta).toHaveValue("dirty draft");

    // Clicking another highlight's bubble does not silently discard the draft.
    await page.locator(`mark.cm-hl[data-cid="${cids[1]}"]`).first().hover();
    await page.locator("#hlBubble").click();
    await expect(ta).toHaveValue("dirty draft");
    await expect(pop.locator(".cm-comment-popover-edit")).toHaveCount(1);

    // Nor does the panel's own edit action: it hands the draft back instead of opening a second editor.
    await page.locator(`.cm-card[data-cid="${cids[0]}"] .cm-entry-root [data-act="edit"]`).click();
    await expect(page.locator(".cm-entry-root .cm-reply-compose")).toHaveCount(0);
    await expect(ta).toHaveValue("dirty draft");

    // Saving from the dialog is what commits it.
    await pop.locator('[data-act="edit-save"]').click();
    expect((await storedComments(page)).find((c) => c.id === cids[0]).note).toBe("dirty draft");
  });

  test("CMH-CORE-16: a dirty panel edit is not duplicated by the in-document dialog (CMH-THREAD-10)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "panel owns this", 0);
    const cid = (await allCids(page))[0];
    const card = page.locator(`.cm-card[data-cid="${cid}"]`);
    await card.locator('.cm-entry-root [data-act="edit"]').click();
    await card.locator(".cm-entry-root .cm-reply-compose textarea").fill("panel draft");

    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await pop.locator('[data-act="edit"]').click();
    // The dialog defers to the panel's dirty draft rather than opening a second editor, and closes
    // so it cannot swallow the reader's next click in the panel.
    await expect(pop).toBeHidden();
    await expect(card.locator(".cm-entry-root .cm-reply-compose textarea")).toHaveValue("panel draft");
    await expect(card.locator(".cm-entry-root .cm-reply-compose textarea")).toBeFocused();
    await card.locator(".cm-entry-root .cm-reply-compose .cm-reply-save").click();
    expect((await storedComments(page))[0].note).toBe("panel draft");
  });

  test("CMH-CORE-16: the dialog defers to an open floating edit composer for the same note (CMH-THREAD-10)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "composer owns this", 0);
    const cid = (await allCids(page))[0];
    // Re-selecting exactly the commented text re-opens that comment in the floating composer.
    await reselectHighlight(page, cid);
    await page.locator("#menuComment").click();
    const composer = page.locator(".cm-composer");
    await expect(composer).toHaveCount(1);
    await expect(composer.locator("textarea")).toHaveValue("composer owns this");
    await composer.locator("textarea").fill("composer draft");
    // Move it clear of the highlight so the dialog below can be clicked.
    const handle = composer.locator(".cm-composer-handle");
    const box = await handle.boundingBox();
    await page.mouse.move(box.x + 5, box.y + 5);
    await page.mouse.down();
    await page.mouse.move(900, 560, { steps: 5 });
    await page.mouse.up();

    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await pop.locator('[data-act="edit"]').click();
    // The dialog hands back to the composer instead of opening a second editor of the same note.
    await expect(pop).toBeHidden();
    await expect(page.locator(".cm-comment-popover-edit")).toHaveCount(0);
    await expect(composer).toHaveCount(1);
    await expect(composer.locator("textarea")).toHaveValue("composer draft");
    await composer.locator('[data-act="save"]').click();
    expect((await storedComments(page))[0].note).toBe("composer draft");
  });

  test("CMH-CORE-16: a dirty inline draft is not duplicated by the floating composer (CMH-THREAD-10)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "panel holds it", 0);
    const cid = (await allCids(page))[0];
    const card = page.locator(".cm-card[data-cid]").first();
    await card.locator('.cm-entry-root [data-act="edit"]').click();
    await card.locator(".cm-entry-root .cm-reply-compose textarea").fill("inline draft");
    // Re-selecting the commented text would open the floating editor; the dirty inline draft wins.
    await reselectHighlight(page, cid);
    await page.locator("#menuComment").click();
    await expect(page.locator(".cm-composer")).toHaveCount(0);
    await expect(card.locator(".cm-entry-root .cm-reply-compose textarea")).toHaveValue("inline draft");
    await expect(page.locator(".cm-toast")).toContainText("already open for editing");
    await card.locator(".cm-entry-root .cm-reply-compose .cm-reply-save").click();
    expect((await storedComments(page))[0].note).toBe("inline draft");
  });

  test("CMH-CORE-16: deleting a comment closes the dialog that is editing it", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "delete under edit", 0);
    const cid = (await allCids(page))[0];
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await pop.locator('[data-act="edit"]').click();
    await pop.locator(".cm-comment-popover-edit textarea").fill("doomed draft");
    page.once("dialog", (d) => d.accept());
    await page.locator(`.cm-card[data-cid="${cid}"] [data-act="del"]`).click();
    await expect(pop).toBeHidden();
    expect((await storedComments(page)).length).toBe(0);
  });

  test("CMH-CORE-16: an Escape meant for another overlay does not discard the dialog draft", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "keep my draft", 0);
    const cid = (await allCids(page))[0];
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await pop.locator('[data-act="edit"]').click();
    const ta = pop.locator(".cm-comment-popover-edit textarea");
    await ta.fill("draft behind the help panel");

    // Opening Help mid-edit is an outside click: it works, and the editor stays.
    await page.click("#btnHelp");
    await expect(page.locator(".cm-help")).toBeVisible();
    // Escape belongs to the panel in front; the draft behind it must survive.
    await page.keyboard.press("Escape");
    await expect(page.locator(".cm-help")).toHaveCount(0);
    await expect(pop).toBeVisible();
    await expect(ta).toHaveValue("draft behind the help panel");
    await pop.locator('[data-act="edit-save"]').click();
    expect((await storedComments(page))[0].note).toBe("draft behind the help panel");
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

  test("CMH-CORE-16: the dialog does not swallow the first click on a side-pane editor control", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "editor owns its clicks");
    const cid = (await allCids(page))[0];
    await page.locator(`.cm-card[data-cid="${cid}"] .cm-reply-btn`).click();
    const editor = page.locator(`.cm-card[data-cid="${cid}"] .cm-reply-compose`);
    const ta = editor.locator("textarea");
    await ta.fill("pick me");
    await ta.evaluate((el) => el.setSelectionRange(0, 4));

    // Opening the dialog from the hover bubble leaves the side-pane editor up (unlike the panel
    // note-edit path, which closes it), so the outside-click swallow must not eat the reviewer's
    // first click on one of that editor's controls.
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();
    await expect(editor).toHaveCount(1);

    await editor.locator('.cm-format-bar button[data-fmt="bold"]').click();
    await expect(ta).toHaveValue("**pick** me");
    await expect(pop).toBeHidden();

    // Save is the same carve-out, and it is the one that has to survive the dialog being torn down
    // mid-click: reopen the dialog and let the FIRST click on Save commit the reply.
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    await expect(pop).toBeVisible();
    await editor.locator(".cm-reply-save").click();
    await expect(pop).toBeHidden();
    await expect.poll(async () => (await storedComments(page)).some((c) => c.parentId === cid)).toBe(true);
  });

  test("CMH-CORE-16: the dialog still swallows a click on document content that spoofs the editor class", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "spoof me");
    const cid = (await allCids(page))[0];
    // The annotated document is author content, so it can carry the layer's own class names. A
    // class match alone must NOT buy a link in the document its way out of the swallow - only an
    // editor the layer actually opened counts. The probe carries no text, so it cannot perturb the
    // document's text-offset space.
    await page.evaluate(() => {
      const wrap = document.createElement("div");
      wrap.className = "cm-reply-compose";
      wrap.innerHTML = '<a id="cmh-spoof" href="#spoofed" style="display:block;width:60px;height:20px"></a>';
      wrap.style.position = "fixed"; wrap.style.top = "4px"; wrap.style.left = "4px"; wrap.style.zIndex = "5";
      document.getElementById("commentRoot").appendChild(wrap);
    });
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover[data-cid]");
    await expect(pop).toBeVisible();

    const url = page.url();
    await page.locator("#cmh-spoof").click();
    await expect(pop).toBeHidden();
    expect(page.url()).toBe(url);
  });

  test("CMH-CORE-16: the dialog still swallows a click on document content that spoofs the dialog class", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "dialog spoof me");
    const cid = (await allCids(page))[0];
    // Same trust boundary for the dialog's OWN class: an author element carrying it must not be
    // mistaken for the live dialog, which would leave the real one open AND let the click act.
    await page.evaluate(() => {
      const wrap = document.createElement("div");
      wrap.className = "cm-comment-popover";
      wrap.innerHTML = '<a id="cmh-pspoof" href="#pspoofed" style="display:block;width:60px;height:20px"></a>';
      wrap.style.position = "fixed"; wrap.style.top = "4px"; wrap.style.left = "4px"; wrap.style.zIndex = "5";
      document.getElementById("commentRoot").appendChild(wrap);
    });
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const real = page.locator(`.cm-comment-popover[data-cid="${cid}"]`);
    await expect(real).toBeVisible();

    const url = page.url();
    await page.locator("#cmh-pspoof").click();
    await expect(real).toHaveCount(0);
    expect(page.url()).toBe(url);
  });

  test("CMH-CORE-16: the dialog does not swallow the first click on a floating composer control", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(1) p", "anchor note");
    const cid = (await allCids(page))[0];
    // A new-comment composer holds an unsaved draft and stays open when the dialog opens, so its
    // controls are exposed to exactly the same swallow.
    const composer = await openComposerFor(page, "#commentRoot section:nth-of-type(2) p");
    const ta = composer.locator("textarea");
    await ta.fill("pick me");
    await ta.evaluate((el) => el.setSelectionRange(0, 4));

    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();
    await expect(composer).toHaveCount(1);

    await composer.locator('.cm-format-bar button[data-fmt="bold"]').click();
    await expect(ta).toHaveValue("**pick** me");
    await expect(pop).toBeHidden();
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
