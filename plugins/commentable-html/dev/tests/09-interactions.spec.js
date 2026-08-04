import { test, expect } from "@playwright/test";
import fs from "fs";
import {
  openKitchenSink, addTextComment, openComposerFor, selectText, distinctCids, realDragSelect,
  allCids, stageContent, stageInline, fileUrl, ready, storedComments,
  installClipboardCapture, lastCopied,
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

  test("CMH-CORE-18: the dialog fits a short viewport and keeps Save and Cancel reachable", async ({ page }) => {
    await openKitchenSink(page);
    // A note long enough that the note view must scroll internally rather than grow the dialog.
    const longNote = Array.from({ length: 12 }, (_, i) => `note line ${i + 1} with enough text to wrap`).join(" ");
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", longNote);
    const cid = (await allCids(page))[0];
    // The cap must not depend on the HOST document's box-sizing reset: with a content box it would
    // exclude the dialog's own padding and border and overflow the viewport again.
    await page.addStyleTag({ content: "* { box-sizing: content-box; }" });
    // A phone-width, very short viewport (the reproduction in issue #825). The comments pane is a
    // full-width sheet at that width, so close it before reaching for the highlight.
    await page.setViewportSize({ width: 390, height: 200 });
    if (await page.evaluate(() => document.body.classList.contains("sidebar-open"))) {
      await page.locator("#btnCloseSidebar").click();
      await expect(page.locator("body")).not.toHaveClass(/sidebar-open/);
    }
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();

    const boxOf = (loc) => loc.evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { top: r.top, bottom: r.bottom, vh: window.innerHeight, hidden: el.scrollHeight - el.clientHeight };
    });
    const fitsViewport = (b) => {
      expect(b.top).toBeGreaterThanOrEqual(-0.5);
      expect(b.bottom).toBeLessThanOrEqual(b.vh + 0.5);
    };

    // The note view is capped inside the viewport, and the cap is the RUNTIME's measured-viewport
    // px value (which tracks a dynamic mobile browser toolbar), not only the static `vh` fallback -
    // which is asserted separately, by reading what the dialog falls back to without the inline cap.
    fitsViewport(await boxOf(pop));
    const caps = await pop.evaluate((el) => {
      const inline = el.style.maxHeight;
      el.style.maxHeight = "";
      const css = getComputedStyle(el).maxHeight;
      el.style.maxHeight = inline;
      return { inline, css, vh: window.innerHeight };
    });
    expect(caps.inline).toBe(`${caps.vh - 16}px`);
    expect(caps.css).not.toBe("none");
    // The overflowing note scrolls INSIDE its own region, and both actions stay on screen with the
    // note scrolled to the bottom.
    const note = pop.locator(".cm-comment-popover-note");
    expect((await boxOf(note)).hidden).toBeGreaterThan(1);
    await note.evaluate((el) => { el.scrollTop = el.scrollHeight; });
    expect(await note.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
    fitsViewport(await boxOf(pop));
    fitsViewport(await boxOf(pop.locator('[data-act="close"]')));
    fitsViewport(await boxOf(pop.locator('[data-act="edit"]')));

    // So is the edit form, whose toolbar + textarea + actions row are what used to overflow.
    await pop.locator('[data-act="edit"]').click();
    await expect(pop.locator("textarea.cm-comment-popover-input")).toBeVisible();
    fitsViewport(await boxOf(pop));
    // The dialog itself never grows past the cap - the content that does not fit scrolls inside it.
    const dialog = await boxOf(pop);
    expect(dialog.hidden).toBeLessThanOrEqual(1);

    // Cancel and Save are both on screen, and reachable by real Tab navigation from the textarea.
    fitsViewport(await boxOf(pop.locator('[data-act="edit-cancel"]')));
    fitsViewport(await boxOf(pop.locator('[data-act="edit-save"]')));
    await pop.locator("textarea.cm-comment-popover-input").focus();
    for (const act of ["edit-cancel", "edit-save"]) {
      await page.keyboard.press("Tab");
      const btn = pop.locator(`[data-act="${act}"]`);
      await expect(btn).toBeFocused();
      fitsViewport(await boxOf(btn));
    }

    // Growing the textarea (it is user-resizable) scrolls the edit region INSIDE the dialog rather
    // than pushing the actions row off the bottom edge.
    await pop.locator("textarea.cm-comment-popover-input").evaluate((el) => { el.style.height = "400px"; });
    const wrap = await boxOf(pop.locator(".cm-comment-popover-edit"));
    expect(wrap.hidden).toBeGreaterThan(1);
    fitsViewport(await boxOf(pop));
    fitsViewport(await boxOf(pop.locator('[data-act="edit-save"]')));

    await pop.locator("textarea.cm-comment-popover-input").fill("saved from a short viewport");
    await pop.locator('[data-act="edit-save"]').click();
    await expect(pop.locator(".cm-comment-popover-note")).toContainText("saved from a short viewport");
    expect((await storedComments(page))[0].note).toBe("saved from a short viewport");
  });

  test("CMH-CORE-18: a mid-edit viewport shrink re-fits the dialog even with its anchor scrolled away", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "resize me mid-edit");
    const cid = (await allCids(page))[0];
    await page.setViewportSize({ width: 390, height: 700 });
    if (await page.evaluate(() => document.body.classList.contains("sidebar-open"))) {
      await page.locator("#btnCloseSidebar").click();
      await expect(page.locator("body")).not.toHaveClass(/sidebar-open/);
    }
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();
    await pop.locator('[data-act="edit"]').click();
    await expect(pop.locator("textarea.cm-comment-popover-input")).toBeVisible();

    // An in-progress edit deliberately survives its anchor scrolling out of view, so the dialog is
    // then re-fitted on its own rather than left with a stale cap and position.
    await page.evaluate(() => window.scrollBy(0, 2000));
    // Precondition: the anchor really is off screen, so this exercises the unanchored re-fit and
    // not the ordinary anchored reposition.
    expect(await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().evaluate((el) => {
      const r = el.getBoundingClientRect();
      return r.bottom < 0 || r.top > window.innerHeight;
    })).toBe(true);
    await expect(pop).toBeVisible();
    await page.setViewportSize({ width: 390, height: 200 });
    await expect(pop).toBeVisible();
    // The runtime re-capped from the new measured viewport (not just the CSS fallback).
    await expect.poll(() => pop.evaluate((el) => el.style.maxHeight)).toBe("184px");

    const boxOf = (loc) => loc.evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { top: r.top, bottom: r.bottom, vh: window.innerHeight };
    });
    for (const b of [await boxOf(pop), await boxOf(pop.locator('[data-act="edit-cancel"]')), await boxOf(pop.locator('[data-act="edit-save"]'))]) {
      expect(b.top).toBeGreaterThanOrEqual(-0.5);
      expect(b.bottom).toBeLessThanOrEqual(b.vh + 0.5);
    }
    // The draft is intact and still savable from the shrunken viewport.
    await pop.locator("textarea.cm-comment-popover-input").fill("saved after the shrink");
    await pop.locator('[data-act="edit-save"]').click();
    expect((await storedComments(page))[0].note).toBe("saved after the shrink");
  });

  test("CMH-CORE-18: growing the textarea after the dialog is placed re-fits it instead of pushing Save off screen", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "grow me after placement");
    const cid = (await allCids(page))[0];
    // A viewport where the cap is NOT binding, so only the re-fit on content growth can keep the
    // dialog inside it: the edit form starts well under the cap and then grows past the bottom.
    await page.setViewportSize({ width: 390, height: 700 });
    if (await page.evaluate(() => document.body.classList.contains("sidebar-open"))) {
      await page.locator("#btnCloseSidebar").click();
      await expect(page.locator("body")).not.toHaveClass(/sidebar-open/);
    }
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();
    await pop.locator('[data-act="edit"]').click();
    const ta = pop.locator("textarea.cm-comment-popover-input");
    await expect(ta).toBeVisible();

    // The reviewer drags the textarea's resize handle (it is `resize: vertical`) well past the
    // space left below the dialog's top edge.
    await ta.evaluate((el) => { el.style.height = "600px"; });
    const bottoms = async () => await pop.evaluate((el) => {
      const d = el.getBoundingClientRect();
      const save = el.querySelector('[data-act="edit-save"]').getBoundingClientRect();
      return { dialog: d.bottom, top: d.top, save: save.bottom, vh: window.innerHeight };
    });
    await expect.poll(async () => (await bottoms()).save <= (await bottoms()).vh + 0.5).toBe(true);
    const b = await bottoms();
    expect(b.top).toBeGreaterThanOrEqual(-0.5);
    expect(b.dialog).toBeLessThanOrEqual(b.vh + 0.5);
    await pop.locator('[data-act="edit-save"]').click();
    await expect(pop.locator(".cm-comment-popover-note")).toContainText("grow me after placement");
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

  test("CMH-CORE-16: clicking elsewhere in the annotated document closes the inline dialog and swallows the click", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "swallow me");
    const cid = (await allCids(page))[0];
    // A probe link in the ANNOTATED DOCUMENT - the only place the swallow applies - whose
    // activation would change the URL hash. It carries no text, so it cannot perturb the
    // document's text-offset space.
    await page.evaluate(() => {
      const a = document.createElement("a");
      a.id = "cmh-probe"; a.href = "#navigated";
      a.style.position = "fixed"; a.style.top = "4px"; a.style.left = "4px"; a.style.zIndex = "5";
      a.style.display = "block"; a.style.width = "60px"; a.style.height = "20px";
      document.getElementById("commentRoot").appendChild(a);
    });
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();

    const url = page.url();
    await page.locator("#cmh-probe").click();
    await expect(pop).toBeHidden();
    expect(page.url()).toBe(url); // the outside click did NOT activate the probe link

    // The deliberate flip side: author page furniture OUTSIDE the content root (a wrapping site
    // nav or footer that a retrofitted document keeps) is not the annotated document, so the
    // dismiss click closes the dialog AND activates it.
    await page.evaluate(() => {
      const a = document.createElement("a");
      a.id = "cmh-outside"; a.href = "#outside";
      a.style.position = "fixed"; a.style.top = "40px"; a.style.left = "4px"; a.style.zIndex = "5";
      a.style.display = "block"; a.style.width = "60px"; a.style.height = "20px";
      document.body.appendChild(a);
    });
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await expect(page.locator("#hlBubble")).toBeVisible();
    await page.locator("#hlBubble").click();
    await expect(pop).toBeVisible();
    await page.locator("#cmh-outside").click();
    await expect(pop).toBeHidden();
    await expect.poll(() => page.evaluate(() => location.hash)).toBe("#outside");
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

  // A document whose content root holds EVERY kind of in-root layer control the runtime injects: a
  // sortable table (a `.cmh-sort-ctrl` per header cell), a draggable widget (a `.cm-widget-reset`
  // once a card moves), a checklist (`.cmh-check`), an editable note (`.cmh-note-head` +
  // `.cmh-note-input`), a code block (`.cm-code-tools` with Copy), a `<section>` heading (a
  // `.cmh-sec-caret` and a `.cmh-review-badge`), and a diff block (`.cmh-diff-bar` with its view
  // toggle). Containment cannot tell any of them from author content, so only the identity registry
  // can spare them.
  const IN_ROOT_CHROME = `
    <section id="chrome-sec">
      <h2 id="chrome-head">In-root chrome</h2>
      <p>Reviewable paragraph text here for anchoring a comment.</p>
      <div class="cm-skip" style="height:340px"></div>
      <table>
        <thead><tr><th>Service</th><th>Requests</th></tr></thead>
        <tbody>
          <tr><td>gateway</td><td>1200</td></tr>
          <tr><td>auth</td><td>340</td></tr>
          <tr><td>catalog</td><td>9800</td></tr>
        </tbody>
      </table>
      <div class="board cm-skip" data-cm-widget="triage" data-cm-draggable aria-label="Triage board" id="board">
        <div class="col" data-cm-slot="Now" id="now"><div class="card" data-cm-part="a" data-cm-part-label="Card A">Card A</div></div>
        <div class="col" data-cm-slot="Later" id="later"></div>
      </div>
      <ul class="cmh-checklist" data-cmh-checklist="rel" data-cmh-checklist-label="Release">
        <li data-cmh-item="backend" data-cmh-state="blank">Backend</li>
      </ul>
      <div class="cmh-note" data-cmh-note="risk" data-cmh-note-label="Risk">No blocking risks yet.</div>
      <pre><code class="language-python">print("hello")</code></pre>
      <pre class="cmh-diff" data-diff-label="probe.sql">--- a/probe.sql
+++ b/probe.sql
@@ -1,2 +1,2 @@
-old line
+new line
 context line
</pre>
    </section>
    <section id="chrome-sec2">
      <h2 id="chrome-head2">Second section</h2>
      <p>A section with no comment in it, so its review badge is plainly unreviewed.</p>
    </section>`;

  async function widgetMutationFrame(page) {
    await page.evaluate(() => new Promise((resolve) => {
      if (typeof requestAnimationFrame !== "function") { resolve(); return; }
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    }));
  }

  test("CMH-CORE-16: the dialog does not swallow the first click on a layer control inside the content root", async ({ page }) => {
    await installClipboardCapture(page);
    const { html } = stageContent(IN_ROOT_CHROME, { key: "cmh-inroot-chrome" });
    await page.goto(fileUrl(html));
    await ready(page);
    await addTextComment(page, "#commentRoot section p", "in-root chrome note");
    const cid = (await allCids(page))[0];
    const pop = page.locator(".cm-comment-popover");
    const openDialog = async () => {
      await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
      await expect(page.locator("#hlBubble")).toBeVisible();
      await page.locator("#hlBubble").click();
      await expect(pop).toBeVisible();
    };
    const services = () => page.$$eval("#commentRoot table tbody tr td:first-child", (tds) => tds.map((t) => t.textContent.trim()));

    // A sortable-table sort control lives INSIDE the content root, so containment calls it document
    // content - but it is the layer's own chrome, and the reviewer's FIRST click must sort.
    expect(await services()).toEqual(["gateway", "auth", "catalog"]);
    await openDialog();
    const ctrl = page.locator("#commentRoot table thead th", { hasText: "Requests" }).locator(".cmh-sort-ctrl");
    await ctrl.click();
    await expect(ctrl).toHaveAttribute("data-dir", "asc");
    expect(await services()).toEqual(["auth", "gateway", "catalog"]);
    await expect(pop).toBeHidden();

    // Same for a widget's "Reset moves", which the runtime injects into the widget itself.
    await page.evaluate(() => document.getElementById("later").appendChild(document.querySelector('[data-cm-part="a"]')));
    await widgetMutationFrame(page);
    const reset = page.locator("#board .cm-widget-reset");
    await expect(reset).toHaveCount(1);
    await openDialog();
    await reset.click();
    await widgetMutationFrame(page);
    await expect(page.locator('#now [data-cm-part="a"]')).toHaveCount(1);
    await expect(reset).toHaveCount(0);
    await expect(pop).toBeHidden();

    // ...and every other control the layer injects into the root, so the registry's coverage is
    // pinned per control rather than asserted once and claimed for the rest: deleting any single
    // `cmhMarkLayerChrome` call reds exactly the leg below that covers it.
    const check = page.locator('[data-cmh-item="backend"] .cmh-check');
    await expect(check).toHaveAttribute("data-cmh-check-state", "blank");
    await openDialog();
    await check.click();
    await expect(check).toHaveAttribute("data-cmh-check-state", "check");
    await expect(pop).toBeHidden();

    // The editable note is two registrations: its mode toggle and the textarea itself. Focus is
    // committed at mousedown, which the capture-phase swallow never sees, so the textarea leg is
    // pinned by a bubble-phase probe instead: it records whether the click actually reached the
    // field un-prevented, which is true only when the carve-out spared it.
    const noteToggle = page.locator('[data-cmh-note="risk"] .cmh-note-toggle');
    const noteField = page.locator('[data-cmh-note="risk"] .cmh-note-input');
    const toggleLabelBefore = (await noteToggle.textContent()).trim();
    await openDialog();
    await noteToggle.click();
    await expect(noteToggle).not.toHaveText(toggleLabelBefore);
    await expect(pop).toBeHidden();
    await page.evaluate(() => {
      window.__cmhNoteFieldReached = false;
      document.querySelector('[data-cmh-note="risk"] .cmh-note-input')
        .addEventListener("click", (e) => { window.__cmhNoteFieldReached = !e.defaultPrevented; });
    });
    await openDialog();
    await noteField.click();
    expect(await page.evaluate(() => window.__cmhNoteFieldReached)).toBe(true);
    await expect(noteField).toBeFocused();
    await expect(pop).toBeHidden();

    // The code block's Copy button.
    await openDialog();
    await page.locator("#commentRoot .cmh-code-wrap .cm-code-copy").first().click();
    await expect.poll(() => lastCopied(page)).toContain('print("hello")');
    await expect(pop).toBeHidden();

    // The collapsible-section caret and the section-review badge are both injected into a heading.
    // Both act on a SECOND section, so collapsing it cannot hide the anchor highlight the remaining
    // legs hover, and its badge is plainly unreviewed (no comment in that section outranking it).
    const section = page.locator("#chrome-sec2");
    await openDialog();
    await page.locator("#chrome-head2 .cmh-sec-caret").click();
    await expect(section).toHaveClass(/cmh-section-collapsed/);
    await expect(pop).toBeHidden();
    const badge = page.locator("#chrome-head2 .cmh-review-badge");
    await expect(badge).toHaveClass(/cmh-review-unreviewed/);
    await openDialog();
    await badge.click();
    await expect(badge).toHaveClass(/cmh-review-reviewed/);
    await expect(pop).toBeHidden();

    // ...and the rendered diff's view toolbar, whose toggle switches the layout.
    const view = page.locator(".cmh-diff-view").first();
    const layoutBefore = await view.getAttribute("class");
    await openDialog();
    await page.locator(".cmh-diff-bar .cmh-diff-toggle").first().click();
    await expect(view).not.toHaveClass(layoutBefore);
    await expect(pop).toBeHidden();
  });

  test("CMH-CORE-16: an in-root layer control keeps its first click in the body-fallback root too", async ({ page }) => {
    // The carve-out is identity- not containment-based, so it is the one thing that still works in
    // the CMH-CORE-15 `<body>` fallback, where EVERY click counts as the annotated document. Without
    // it a sort control would be unusable there for as long as a dialog is open.
    const { html } = stageContent(IN_ROOT_CHROME, { key: "cmh-inroot-fallback" });
    // Strip the content-root id ON DISK, not in the live page: the layer resolves its root during
    // parse, so a post-load rename would not reach it (and a reload would restore the file anyway).
    fs.writeFileSync(html, fs.readFileSync(html, "utf8")
      .replace('<main id="commentRoot"', '<main id="contentWithoutCommentRoot"'));
    await page.goto(fileUrl(html));
    await ready(page);
    await expect(page.locator("#commentRoot")).toHaveCount(0);
    await addTextComment(page, "#contentWithoutCommentRoot section p", "body fallback chrome note");
    const cid = (await allCids(page))[0];
    const pop = page.locator(".cm-comment-popover");
    const openDialog = async () => {
      await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
      await expect(page.locator("#hlBubble")).toBeVisible();
      await page.locator("#hlBubble").click();
      await expect(pop).toBeVisible();
    };

    await openDialog();
    const ctrl = page.locator("table thead th", { hasText: "Requests" }).locator(".cmh-sort-ctrl");
    await ctrl.click();
    await expect(ctrl).toHaveAttribute("data-dir", "asc");
    expect(await page.$$eval("table tbody tr td:first-child", (tds) => tds.map((t) => t.textContent.trim())))
      .toEqual(["auth", "gateway", "catalog"]);
    await expect(pop).toBeHidden();

    // ...while document content in that same fallback root is still swallowed, so this is a carve-out
    // and not a hole: the identical probe click activates only once no dialog is open.
    await page.evaluate(() => {
      const a = document.createElement("a");
      a.id = "cmh-fprobe"; a.href = "#fallbacknav";
      a.style.position = "fixed"; a.style.top = "4px"; a.style.left = "4px"; a.style.zIndex = "5";
      a.style.display = "block"; a.style.width = "60px"; a.style.height = "20px";
      document.getElementById("contentWithoutCommentRoot").appendChild(a);
    });
    await openDialog();
    const url = page.url();
    await page.locator("#cmh-fprobe").click();
    await expect(pop).toBeHidden();
    expect(page.url()).toBe(url);
    await page.locator("#cmh-fprobe").click();
    await expect.poll(() => page.evaluate(() => location.hash)).toBe("#fallbacknav");
  });

  test("CMH-CORE-16: the dialog still swallows a click on document content that spoofs an in-root control class", async ({ page }) => {
    const { html } = stageContent(IN_ROOT_CHROME, { key: "cmh-inroot-spoof" });
    await page.goto(fileUrl(html));
    await ready(page);
    await addTextComment(page, "#commentRoot section p", "in-root spoof note");
    const cid = (await allCids(page))[0];
    // The carve-out is the layer's REGISTERED control, never the class name it happens to carry:
    // author content wearing `cmh-sort-ctrl` or `cm-widget-reset` is still document content and is
    // still swallowed. The probes carry no text, so the document's offset space is unchanged.
    await page.evaluate(() => {
      [["cmh-sort-ctrl", "cmh-sort-spoof", "#sortspoofed", 4], ["cm-widget-reset", "cmh-reset-spoof", "#resetspoofed", 40]]
        .forEach(([cls, id, href, top]) => {
          const wrap = document.createElement("div");
          wrap.className = cls;
          wrap.innerHTML = '<a id="' + id + '" href="' + href + '" style="display:block;width:60px;height:20px"></a>';
          wrap.style.position = "fixed"; wrap.style.left = "4px"; wrap.style.top = top + "px"; wrap.style.zIndex = "5";
          document.getElementById("commentRoot").appendChild(wrap);
        });
    });
    const pop = page.locator(".cm-comment-popover");
    const url = page.url();
    for (const id of ["cmh-sort-spoof", "cmh-reset-spoof"]) {
      await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
      await expect(page.locator("#hlBubble")).toBeVisible();
      await page.locator("#hlBubble").click();
      await expect(pop).toBeVisible();
      await page.locator(`#${id}`).click();
      await expect(pop).toBeHidden();
      expect(page.url()).toBe(url);
    }
    // Non-vacuous: with no dialog open the identical click DOES activate each spoof probe, so the
    // assertions above pin the swallow rather than an inert probe.
    await page.locator("#cmh-sort-spoof").click();
    await expect.poll(() => page.evaluate(() => location.hash)).toBe("#sortspoofed");
    await page.locator("#cmh-reset-spoof").click();
    await expect.poll(() => page.evaluate(() => location.hash)).toBe("#resetspoofed");
  });

  // The same in-root controls, except the AUTHOR document already ships an element wearing each
  // control's class before the layer runs. A guard that decides "a control already exists here"
  // from a bare class match skips creating the real control in every one of these headings, cells,
  // and widgets - a silent denial of the affordance. The spoofs carry no text, so the document's
  // offset space is unchanged, and each is sized so it can be clicked.
  const SPOOF_BOX = ' style="display:inline-block;width:40px;height:16px;vertical-align:middle"';
  const SPOOFED_CHROME = `
    <section id="spoof-sec1">
      <h2 id="spoof-head1">Spoofed chrome</h2>
      <p>Reviewable paragraph text here for anchoring a comment.</p>
      <div class="cm-skip" style="height:340px"></div>
      <table>
        <thead><tr><th>Service</th><th id="spoof-th">Requests<button type="button" class="cmh-sort-ctrl" id="author-sort"${SPOOF_BOX}></button></th></tr></thead>
        <tbody>
          <tr><td>gateway</td><td>1200</td></tr>
          <tr><td>auth</td><td>340</td></tr>
          <tr><td>catalog</td><td>9800</td></tr>
        </tbody>
      </table>
      <div class="board cm-skip" data-cm-widget="triage" data-cm-draggable aria-label="Triage board" id="board">
        <button type="button" class="cm-widget-reset" id="author-reset"${SPOOF_BOX}></button>
        <div class="col" data-cm-slot="Now" id="now"><div class="card" data-cm-part="a" data-cm-part-label="Card A">Card A</div></div>
        <div class="col" data-cm-slot="Later" id="later"></div>
      </div>
    </section>
    <section id="spoof-sec2">
      <h2 id="spoof-head2"><button type="button" class="cmh-sec-caret" id="author-caret"${SPOOF_BOX}></button>Second section<button type="button" class="cmh-review-badge" id="author-badge"${SPOOF_BOX}></button></h2>
      <p>A second section with its own reviewable paragraph.</p>
    </section>`;

  test("CMH-CORE-21: an author element wearing a layer control's class does not suppress the real control", async ({ page }) => {
    const { html } = stageContent(SPOOFED_CHROME, { key: "cmh-chrome-spoof-suppress" });
    await page.goto(fileUrl(html));
    await ready(page);
    const services = () => page.$$eval("#commentRoot table tbody tr td:first-child", (tds) => tds.map((t) => t.textContent.trim()));

    // 62-sortable-tables.js: the header cell already carries an author `.cmh-sort-ctrl`.
    const sortCtrl = page.locator("#spoof-th .cmh-sort-ctrl:not(#author-sort)");
    await expect(sortCtrl).toHaveCount(1);
    expect(await services()).toEqual(["gateway", "auth", "catalog"]);
    await sortCtrl.click();
    await expect(sortCtrl).toHaveAttribute("data-dir", "asc");
    expect(await services()).toEqual(["auth", "gateway", "catalog"]);

    // 82-toc.js: the heading already carries an author `.cmh-sec-caret`.
    const caret = page.locator("#spoof-head2 .cmh-sec-caret:not(#author-caret)");
    const section = page.locator("#spoof-sec2");
    await expect(caret).toHaveCount(1);
    await caret.click();
    await expect(section).toHaveClass(/cmh-section-collapsed/);
    await caret.click();
    await expect(section).not.toHaveClass(/cmh-section-collapsed/);
    // The delegated heading click defers to the caret by IDENTITY too: an author element merely
    // wearing the caret class is not the caret, so clicking it still expands a collapsed section.
    await caret.click();
    await expect(section).toHaveClass(/cmh-section-collapsed/);
    await page.locator("#author-caret").click();
    await expect(section).not.toHaveClass(/cmh-section-collapsed/);

    // 84-section-review.js: the heading already carries an author `.cmh-review-badge`.
    const badge = page.locator("#spoof-head2 .cmh-review-badge:not(#author-badge)");
    await expect(badge).toHaveCount(1);
    await expect(badge).toHaveClass(/cmh-review-unreviewed/);
    await badge.click();
    await expect(badge).toHaveClass(/cmh-review-reviewed/);

    // 35-widgets.js: the widget already carries an author `.cm-widget-reset`.
    await page.evaluate(() => document.getElementById("later").appendChild(document.querySelector('[data-cm-part="a"]')));
    await widgetMutationFrame(page);
    const reset = page.locator("#board .cm-widget-reset:not(#author-reset)");
    await expect(reset).toHaveCount(1);
    await reset.click();
    await widgetMutationFrame(page);
    await expect(page.locator('#now [data-cm-part="a"]')).toHaveCount(1);
    await expect(reset).toHaveCount(0);
    // Symmetrically, the author's element is never the layer's to REMOVE either.
    await expect(page.locator("#author-reset")).toHaveCount(1);
    // ...nor to MEASURE: the widget Add button dodges the layer's own "Reset moves", so with the
    // widget clean again (no real reset) the author's element must not be measured in its place.
    // Move the pointer clear first so the hover below raises a REAL mouseenter and repositions.
    await page.mouse.move(2, 2);
    await expect(page.locator("#widgetAddBtn")).toBeHidden();
    await page.evaluate(() => {
      window.__authorResetMeasured = false;
      const el = document.getElementById("author-reset");
      const orig = Element.prototype.getBoundingClientRect;
      el.getBoundingClientRect = function () { window.__authorResetMeasured = true; return orig.call(this); };
    });
    await page.hover('[data-cm-part="a"]');
    await expect(page.locator("#widgetAddBtn")).toBeVisible();
    expect(await page.evaluate(() => window.__authorResetMeasured), "the author's spoof must never be measured").toBe(false);
  });

  test("CMH-CORE-21: an author element that spoofs a control class gains nothing and is still swallowed", async ({ page }) => {
    // A viewport tall enough for the whole staged document, so clicking a spoof near its foot never
    // auto-scrolls: a scroll would close the dialog clip-awarely BEFORE the click, and the probe
    // would then read a legitimately un-swallowed click as a chrome-identity regression.
    await page.setViewportSize({ width: 1280, height: 1200 });
    const { html } = stageContent(SPOOFED_CHROME, { key: "cmh-chrome-spoof-unregistered" });
    await page.goto(fileUrl(html));
    await ready(page);
    await addTextComment(page, "#commentRoot #spoof-sec1 p", "spoofed chrome note");
    const cid = (await allCids(page))[0];
    const pop = page.locator(".cm-comment-popover");
    const ids = ["author-sort", "author-reset", "author-caret", "author-badge"];
    // Every spoof must still be in the document: an "already created?" guard that matched the
    // author's element by class would also have REMOVED it (the widget reset's clean-up branch).
    for (const id of ids) await expect(page.locator(`#${id}`)).toHaveCount(1);
    // Record whether the click actually REACHED each spoof un-prevented; the capture-phase swallow
    // stops it before the target listener, so a swallowed click leaves the flag false.
    await page.evaluate((names) => {
      window.__cmhSpoofReached = {};
      names.forEach((id) => {
        window.__cmhSpoofReached[id] = false;
        document.getElementById(id).addEventListener("click", (e) => { window.__cmhSpoofReached[id] = !e.defaultPrevented; });
      });
    }, ids);

    for (const id of ids) {
      await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
      await expect(page.locator("#hlBubble")).toBeVisible();
      await page.locator("#hlBubble").click();
      await expect(pop).toBeVisible();
      // The dismiss guard arms on the next tick (so the opening click cannot close the dialog), so
      // cross a macrotask boundary in the page before probing: our timer was scheduled after the
      // layer's, and equal-delay timers fire in scheduling order.
      await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 0)));
      await expect(pop, "the dialog must still be open when the probe click lands").toBeVisible();
      await page.locator(`#${id}`).click();
      // The dialog must still have been OPEN when the click landed, or "not swallowed" would mean
      // nothing; assert the close was caused by this click rather than an earlier scroll.
      await expect(pop).toBeHidden();
      expect(await page.evaluate((n) => window.__cmhSpoofReached[n], id), `${id} must not be carved out as layer chrome`).toBe(false);
    }
    // Non-vacuous: with no dialog open the identical click DOES reach each spoof, so the assertions
    // above pin the swallow rather than an inert probe.
    for (const id of ids) {
      await page.locator(`#${id}`).click();
      expect(await page.evaluate((n) => window.__cmhSpoofReached[n], id), `${id} probe is inert`).toBe(true);
    }
  });

  test("CMH-CORE-21: expanding a collapsed section from the sidebar restamps the layer's own caret", async ({ page }) => {
    const { html } = stageContent(SPOOFED_CHROME, { key: "cmh-chrome-spoof-expand" });
    await page.goto(fileUrl(html));
    await ready(page);
    await addTextComment(page, "#commentRoot #spoof-sec2 p", "collapsed section note");
    const caret = page.locator("#spoof-head2 .cmh-sec-caret:not(#author-caret)");
    await caret.click();
    await expect(page.locator("#spoof-sec2")).toHaveClass(/cmh-section-collapsed/);
    await expect(caret).toHaveAttribute("aria-expanded", "false");
    // Jumping to the comment expands the ancestor section, and must put the expanded state back on
    // the caret the LAYER created - name, title, and aria-expanded together - never on the author's.
    await page.locator('.cm-card [data-act="jump"]').first().click();
    await expect(page.locator("#spoof-sec2")).not.toHaveClass(/cmh-section-collapsed/);
    await expect(caret).toHaveAttribute("aria-expanded", "true");
    await expect(caret).toHaveAttribute("aria-label", "Collapse section");
    // The tooltip layer moves `title` into `data-cmh-tip` on first hover, so assert the effective
    // tooltip rather than the raw attribute.
    expect(await caret.evaluate((el) => el.getAttribute("title") || el.getAttribute("data-cmh-tip"))).toBe("Collapse section");
    expect(await page.locator("#author-caret").getAttribute("aria-expanded")).toBeNull();
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

  test("CMH-CORE-16: with a dialog open, another highlight's bubble opens THAT comment on the first click", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(1) p", "first note");
    await addTextComment(page, "#commentRoot section:nth-of-type(3) p", "second note");
    const stored = await storedComments(page);
    const first = stored.find((c) => c.note === "first note").id;
    const second = stored.find((c) => c.note === "second note").id;

    await page.locator(`mark.cm-hl[data-cid="${first}"]`).first().hover();
    await expect(page.locator("#hlBubble")).toBeVisible();
    await page.locator("#hlBubble").click();
    await expect(page.locator(`.cm-comment-popover[data-cid="${first}"]`)).toBeVisible();

    // The bubble is the layer's OWN chrome, not document content, so the open dialog must not eat
    // the click: one click switches to the other comment instead of only closing the first dialog.
    await page.locator(`mark.cm-hl[data-cid="${second}"]`).first().hover();
    await expect(page.locator("#hlBubble")).toBeVisible();
    await page.locator("#hlBubble").click();
    await expect(page.locator(`.cm-comment-popover[data-cid="${second}"]`)).toBeVisible();
    await expect(page.locator(`.cm-comment-popover[data-cid="${first}"]`)).toHaveCount(0);

    // Re-clicking the SAME highlight's bubble no longer toggles the dialog shut (that only happened
    // because the click was eaten): the bubble means "open this comment", so it closes and reopens
    // and the reviewer is left looking at the same comment. The rendered note carries a per-opening
    // id, so a genuine close-and-reopen is observable - a silent no-op would keep the old one.
    const noteIdBefore = await page.locator(`.cm-comment-popover[data-cid="${second}"] .cm-comment-popover-note`).getAttribute("id");
    expect(noteIdBefore).toBeTruthy();
    await page.locator(`mark.cm-hl[data-cid="${second}"]`).first().hover();
    await expect(page.locator("#hlBubble")).toBeVisible();
    await page.locator("#hlBubble").click();
    const reopened = page.locator(`.cm-comment-popover[data-cid="${second}"]`);
    await expect(reopened).toBeVisible();
    await expect.poll(async () => reopened.locator(".cm-comment-popover-note").getAttribute("id"))
      .not.toBe(noteIdBefore);
  });

  test("CMH-CORE-16: an overlay or toast the dialog's own Save raised acts on the first click", async ({ page }) => {
    const key = "cmh-popover-quota";
    const { html } = stageContent("<section><p>reviewable paragraph text here for anchoring.</p></section>",
      { key, source: "popover-quota.html" });
    // Stateful quota: the comment write throws only while the bloat document's data is present, so
    // the first comment saves normally and it is the DIALOG'S OWN Save that trips the quota.
    await page.addInitScript((k) => {
      const bloat = "commentable-html:/reports/popbloat.html::z";
      const orig = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) {
        if (key === k + "::z" && localStorage.getItem(bloat) !== null) {
          throw new DOMException("quota", "QuotaExceededError");
        }
        return orig.call(this, key, value);
      };
    }, key);
    await page.goto(fileUrl(html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "note that stores fine");
    await page.evaluate(() => localStorage.setItem("commentable-html:/reports/popbloat.html::z",
      "\u0001z" + "x".repeat(200)));

    const cid = (await allCids(page))[0];
    const openDialog = async () => {
      await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
      await expect(page.locator("#hlBubble")).toBeVisible();
      await page.locator("#hlBubble").click();
      await expect(page.locator(".cm-comment-popover")).toBeVisible();
    };
    const pop = page.locator(".cm-comment-popover");
    const saveQuotaEdit = async (note) => {
      await pop.locator('[data-act="edit"]').click();
      await pop.locator("textarea").fill(note);
      await pop.locator('[data-act="edit-save"]').click();
    };
    await openDialog();
    await saveQuotaEdit("edited note that cannot be stored");

    // Save raised the storage manager while the dialog is still open and armed. The overlay is the
    // layer's own chrome, so the reviewer's FIRST click on its controls must act on it.
    const manager = page.locator(".cm-storage-manager");
    await expect(manager).toBeVisible();
    await expect(pop).toBeVisible();
    await manager.locator(".cm-storage-foot-close").click();
    await expect(manager).toHaveCount(0);
    await expect(pop).toHaveCount(0);

    // With the write still pending the manager will not re-open itself for the same quota episode,
    // so the next Save from the dialog raises an ACTIONABLE TOAST instead - again while the dialog
    // is open and armed. Its first click must run the action, not be spent closing the dialog.
    await openDialog();
    await saveQuotaEdit("edited again, still unstorable");
    const toast = page.locator("#toast");
    await expect(toast).toContainText("is shown but this browser's storage is full");
    await expect(pop).toBeVisible();
    await toast.locator(".cm-toast-action").click();
    await expect(page.locator(".cm-storage-manager")).toBeVisible();
    await expect(pop).toHaveCount(0);
  });

  test("CMH-CORE-16: the body-fallback root still swallows document clicks and still spares the editors", async ({ page }) => {
    // With no #commentRoot the layer anchors to <body> (CMH-CORE-15), which contains the layer's own
    // chrome too - so the inverted "swallow only inside the annotated document" rule must not start
    // swallowing every click there: the editor carve-outs still apply, and document content is still
    // swallowed exactly as before.
    const { html } = stageInline({
      mutate: (doc) => doc.replace(/<main id="commentRoot"(?=[^>]*data-comment-key="commentable-html-demo")[^>]*>/,
        '<main id="contentWithoutCommentRoot">'),
    });
    await page.goto(fileUrl(html));
    await ready(page);
    await expect(page.locator("#commentRoot")).toHaveCount(0);
    await addTextComment(page, "main p", "body fallback swallow", 0);
    const cid = (await allCids(page))[0];

    await page.evaluate(() => {
      const a = document.createElement("a");
      a.id = "cmh-bprobe"; a.href = "#bodynav"; a.textContent = "probe";
      a.style.position = "fixed"; a.style.top = "4px"; a.style.left = "4px"; a.style.zIndex = "5";
      document.body.appendChild(a);
    });
    const pop = page.locator(".cm-comment-popover");
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    await expect(pop).toBeVisible();

    const url = page.url();
    await page.locator("#cmh-bprobe").click();
    await expect(pop).toBeHidden();
    expect(page.url()).toBe(url); // still swallowed in the fallback

    // The fallback root is `<body>`, so a click whose target is OUTSIDE it (`<html>`, the page
    // gutter) must still be swallowed exactly as it was before the rule was inverted. The window
    // bubble-phase counter observes it: capture-phase stopPropagation never reaches window.
    await page.evaluate(() => {
      window.__reached = 0;
      window.addEventListener("click", () => { window.__reached += 1; });
    });
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await expect(page.locator("#hlBubble")).toBeVisible();
    await page.locator("#hlBubble").click();
    await expect(pop).toBeVisible();
    // The dismiss listener is registered a tick after the dialog opens, so let that tick pass before
    // dispatching synthetically (a real Playwright click takes long enough on its own).
    await page.evaluate(() => new Promise((r) => setTimeout(r, 0)));
    await page.evaluate(() => {
      document.documentElement.dispatchEvent(
        new MouseEvent("click", { bubbles: true, cancelable: true, detail: 1 }));
    });
    await expect(pop).toBeHidden();
    expect(await page.evaluate(() => window.__reached)).toBe(0);
    // Non-vacuous: the identical dispatch reaches window once no dialog is open.
    await page.evaluate(() => {
      document.documentElement.dispatchEvent(
        new MouseEvent("click", { bubbles: true, cancelable: true, detail: 1 }));
    });
    expect(await page.evaluate(() => window.__reached)).toBe(1);

    // ...and the side-pane editor, which lives inside the fallback root, still owns its first click.
    await page.locator(`.cm-card[data-cid="${cid}"] .cm-reply-btn`).click();
    const editor = page.locator(`.cm-card[data-cid="${cid}"] .cm-reply-compose`);
    const ta = editor.locator("textarea");
    await ta.fill("pick me");
    await ta.evaluate((el) => el.setSelectionRange(0, 4));
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await page.locator("#hlBubble").click();
    await expect(pop).toBeVisible();
    await editor.locator('.cm-format-bar button[data-fmt="bold"]').click();
    await expect(ta).toHaveValue("**pick** me");
    await expect(pop).toBeHidden();

    // ...and so does a floating composer, the other half of the identity-resolved carve-out. It is
    // appended to `document.body`, which IS the root here, so this is the only mode in which that
    // branch of the predicate decides anything.
    const composer = await openComposerFor(page, "main p", { index: 1 });
    const cta = composer.locator("textarea");
    await cta.fill("pick me");
    await cta.evaluate((el) => el.setSelectionRange(0, 4));
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await expect(page.locator("#hlBubble")).toBeVisible();
    await page.locator("#hlBubble").click();
    await expect(pop).toBeVisible();
    await composer.locator('.cm-format-bar button[data-fmt="bold"]').click();
    await expect(cta).toHaveValue("**pick** me");
    await expect(pop).toBeHidden();
    await composer.locator('[data-act="cancel"]').click();
    await expect(composer).toHaveCount(0);

    // Documented limitation of this mode (tracked separately): because the layer's chrome is inside
    // the fallback root, another highlight's bubble is still swallowed here, so switching comments
    // still takes two clicks. Pinned so the prose cannot drift from the behavior.
    await addTextComment(page, "main p", "second fallback note", 3);
    const other = (await storedComments(page)).find((c) => c.note === "second fallback note").id;
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await expect(page.locator("#hlBubble")).toBeVisible();
    await page.locator("#hlBubble").click();
    await expect(page.locator(`.cm-comment-popover[data-cid="${cid}"]`)).toBeVisible();
    await page.locator(`mark.cm-hl[data-cid="${other}"]`).first().hover();
    await expect(page.locator("#hlBubble")).toBeVisible();
    await page.locator("#hlBubble").click();
    await expect(page.locator(".cm-comment-popover")).toHaveCount(0);
  });

  test("CMH-CORE-16: a document click whose node is detached mid-dispatch is still swallowed", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "detach me");
    const cid = (await allCids(page))[0];
    // An EARLIER capture-phase listener (registered before the dialog arms its own) removes the
    // clicked node mid-dispatch. The click still landed in the annotated document, so it must still
    // be swallowed - a live-tree containment test would answer "outside" and let it act. The window
    // bubble-phase counter observes the swallow directly: capture-phase stopPropagation on
    // `document` means the event never reaches it.
    // ORDER MATTERS: this evaluate must run BEFORE the bubble click below. Same-node capture
    // listeners fire in registration order, so registering the detacher first is what puts it ahead
    // of the dialog's dismiss listener; move it after and the node is never detached in time and
    // the test passes for the wrong reason.
    await page.evaluate(() => {
      const a = document.createElement("a");
      a.id = "cmh-dprobe"; a.href = "#detached";
      a.style.position = "fixed"; a.style.top = "4px"; a.style.left = "4px"; a.style.zIndex = "5";
      a.style.display = "block"; a.style.width = "60px"; a.style.height = "20px";
      document.getElementById("commentRoot").appendChild(a);
      window.__reached = 0;
      window.addEventListener("click", () => { window.__reached += 1; });
      document.addEventListener("click", (e) => {
        const t = e.target;
        if (t && t.id === "cmh-dprobe" && t.parentNode) t.parentNode.removeChild(t);
      }, true);
    });
    const pop = page.locator(".cm-comment-popover");
    await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
    await expect(page.locator("#hlBubble")).toBeVisible();
    await page.locator("#hlBubble").click();
    await expect(pop).toBeVisible();

    await page.locator("#cmh-dprobe").click();
    await expect(pop).toBeHidden();
    expect(await page.evaluate(() => window.__reached)).toBe(0);

    // Non-vacuous: with no dialog open the same detached-node click propagates normally.
    await page.evaluate(() => {
      const a = document.createElement("a");
      a.id = "cmh-dprobe"; a.href = "#detached2";
      a.style.position = "fixed"; a.style.top = "4px"; a.style.left = "4px"; a.style.zIndex = "5";
      a.style.display = "block"; a.style.width = "60px"; a.style.height = "20px";
      document.getElementById("commentRoot").appendChild(a);
    });
    await page.locator("#cmh-dprobe").click();
    expect(await page.evaluate(() => window.__reached)).toBe(1);
  });

  test("CMH-CORE-16: a keyboard-activated outside click closes the dialog but is not swallowed", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section:nth-of-type(2) p", "keyboard me");
    const cid = (await allCids(page))[0];
    // A probe link in the annotated document (where the swallow applies); activating it by
    // keyboard should still work. No text, so the document's offset space is unchanged.
    await page.evaluate(() => {
      const a = document.createElement("a");
      a.id = "cmh-kprobe"; a.href = "#navk";
      a.style.position = "fixed"; a.style.top = "4px"; a.style.left = "4px"; a.style.zIndex = "5";
      a.style.display = "block"; a.style.width = "60px"; a.style.height = "20px";
      document.getElementById("commentRoot").appendChild(a);
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
