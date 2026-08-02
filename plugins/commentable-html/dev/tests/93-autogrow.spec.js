import { test, expect } from "@playwright/test";
import { openInline, addTextComment, openComposerFor, storedComments, setStoredComments, ready } from "./helpers.js";

// Issue #851: the authoring textareas (the floating composer, the side-pane inline reply/edit
// editor, and the in-document popover editor) grow to fit what the reviewer writes instead of
// staying a line and a half tall, and the reply input is no longer typed a font-size step smaller
// than the comment it answers.

async function openSidebarPanel(page) {
  if (!(await page.evaluate(() => document.body.classList.contains("sidebar-open")))) {
    await page.click("#btnToggleSidebar");
  }
  await expect(page.locator("body")).toHaveClass(/sidebar-open/);
}

// Open a reply editor on the first comment card and return its textarea locator.
async function openReplyEditor(page) {
  await openSidebarPanel(page);
  await page.locator(".cm-card .cm-reply-btn").first().click();
  const ta = page.locator(".cm-card .cm-reply-compose textarea").last();
  await expect(ta).toBeVisible();
  return ta;
}

function lines(n, word) {
  return Array.from({ length: n }, (_, i) => `${word} line ${i + 1}`).join("\n");
}

// Open the in-document comment dialog on the first comment and switch it to its edit form.
async function openPopoverEditor(page) {
  const cid = (await storedComments(page))[0].id;
  await page.locator(`mark.cm-hl[data-cid="${cid}"]`).first().hover();
  await page.locator("#hlBubble").click();
  const pop = page.locator(".cm-comment-popover");
  await expect(pop).toBeVisible();
  await pop.locator('[data-act="edit"]').click();
  await expect(pop.locator("textarea.cm-comment-popover-input")).toBeVisible();
  return pop;
}

const heightOf = (ta) => ta.evaluate((el) => el.getBoundingClientRect().height);

test.describe("authoring inputs: autogrow and readable size", () => {
  // Every height assertion below depends on the viewport (the caps are vh-relative), so pin one
  // where the premise holds rather than inheriting the project default.
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
  });

  test("the side-pane reply input grows to fit what is typed and shrinks back (CMH-GROW-01)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "the initial point", 0);
    const ta = await openReplyEditor(page);

    const empty = await heightOf(ta);
    await ta.fill(lines(10, "reply"));
    const grown = await heightOf(ta);
    // Ten lines are visible without scrolling inside the box.
    expect(grown).toBeGreaterThan(empty + 60);
    expect(await ta.evaluate((el) => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(2);

    // Deleting the text shrinks the box back, so a short draft leaves no tall gap.
    await ta.fill("one short line");
    expect(await heightOf(ta)).toBeLessThanOrEqual(empty + 2);
  });

  test("a replacement that is longer but wraps to fewer lines still shrinks the box (CMH-GROW-01)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "the initial point", 0);
    const ta = await openReplyEditor(page);
    await ta.fill(lines(10, "reply"));
    const tall = await heightOf(ta);

    // Pasting over the whole draft with text that is LONGER in characters but occupies fewer
    // lines must still shrink the box - growth cannot be inferred from the text length.
    await ta.fill("filler ".repeat(30).trim());
    expect(await heightOf(ta)).toBeLessThan(tall - 40);
  });

  test("a restored draft comes back at content size, not collapsed (CMH-GROW-01)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "the initial point", 0);
    const ta = await openReplyEditor(page);
    await ta.fill(lines(10, "a long draft"));
    const tall = await heightOf(ta);

    await page.click("#btnSort");
    const reopened = page.locator(".cm-card .cm-reply-compose textarea").last();
    await expect(reopened).toHaveValue(/a long draft line 10/);
    expect(Math.abs((await heightOf(reopened)) - tall)).toBeLessThanOrEqual(2);
    expect(await reopened.evaluate((el) => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(2);
  });

  test("shrinking a draft does not scroll the comments list under the reviewer (CMH-GROW-01)", async ({ page }) => {
    await openInline(page);
    // Enough cards for the panel list to scroll, seeded directly so the test stays quick.
    const now = new Date().toISOString();
    await setStoredComments(page, Array.from({ length: 14 }, (_, i) => ({
      id: "cseed" + String(i).padStart(5, "0"), anchorType: "document",
      note: "seeded comment " + (i + 1), createdAt: now,
    })));
    await page.reload();
    await ready(page);
    await openSidebarPanel(page);

    const list = page.locator(".cm-sidebar .list");
    await list.evaluate((el) => { el.scrollTop = el.scrollHeight; });
    await page.locator(".cm-card .cm-reply-btn").last().click();
    const ta = page.locator(".cm-card .cm-reply-compose textarea").last();
    await ta.fill(lines(10, "a long draft"));
    const before = await list.evaluate((el) => el.scrollTop);

    // Measuring a shrink collapses the box for an instant; the panel must not jump while it does.
    await ta.fill("one short line");
    expect(await list.evaluate((el) => el.scrollTop)).toBe(before);
  });

  test("an existing reply opens its editor already sized to the reply (CMH-GROW-01)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "the initial point", 0);
    const ta = await openReplyEditor(page);
    await ta.fill(lines(8, "long"));
    await page.locator(".cm-card .cm-reply-save").last().click();
    await expect(page.locator(".cm-card .cm-reply")).toHaveCount(1);

    // Re-open that saved reply for editing: it is prefilled, so it must open at content size
    // rather than as a two-line box the reviewer has to drag open again.
    await page.locator('.cm-card .cm-reply [data-act="reply-edit"]').first().click();
    const editor = page.locator(".cm-card .cm-reply-compose textarea").last();
    await expect(editor).toBeVisible();
    await expect(editor).toHaveValue(/long line 8/);
    expect(await heightOf(editor)).toBeGreaterThan(100);
  });

  test("the floating composer textarea autogrows the same way (CMH-GROW-01)", async ({ page }) => {
    await openInline(page);
    const composer = await openComposerFor(page, "#commentRoot p");
    const ta = composer.locator("textarea");
    const empty = await heightOf(ta);
    await ta.fill(lines(12, "composed"));
    expect(await heightOf(ta)).toBeGreaterThan(empty + 60);
    await ta.fill("back to one");
    expect(await heightOf(ta)).toBeLessThanOrEqual(empty + 2);
  });

  test("the in-document popover editor autogrows too, and opens sized to the note (CMH-GROW-01)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "a note to edit", 0);
    const pop = await openPopoverEditor(page);
    const ta = pop.locator("textarea.cm-comment-popover-input");

    const start = await heightOf(ta);
    await ta.fill(lines(12, "edited"));
    expect(await heightOf(ta)).toBeGreaterThan(start + 60);

    // Re-opening the dialog on that now-long note must present it at content size, not collapsed.
    await pop.locator('[data-act="edit-save"]').click();
    await page.keyboard.press("Escape");
    const reopened = await openPopoverEditor(page);
    expect(await heightOf(reopened.locator("textarea.cm-comment-popover-input"))).toBeGreaterThan(start + 60);
  });

  test("growth stops at a cap and the box scrolls instead (CMH-GROW-02)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "the initial point", 0);
    const ta = await openReplyEditor(page);

    const empty = await heightOf(ta);
    await ta.fill(lines(200, "very long reply"));
    const capped = await heightOf(ta);
    // It grew a long way, but no further than the cap the stylesheet declares.
    expect(capped).toBeGreaterThan(empty + 120);
    const cap = await ta.evaluate((el) => {
      const raw = getComputedStyle(el).getPropertyValue("--cmh-grow-max").trim();
      return raw.endsWith("vh") ? window.innerHeight * parseFloat(raw) / 100 : parseFloat(raw);
    });
    expect(cap).toBeGreaterThan(0);
    expect(capped).toBeLessThanOrEqual(cap + 1);
    // Past the cap the box scrolls rather than pushing Cancel/Save out of the card.
    expect(await ta.evaluate((el) => el.scrollHeight)).toBeGreaterThan(capped + 10);
    await expect(page.locator(".cm-card .cm-reply-save").last()).toBeInViewport();
  });

  test("a grown composer stays fully on screen so Save is still reachable (CMH-GROW-02)", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 700 });
    await openInline(page);
    const composer = await openComposerFor(page, "#commentRoot p");
    // Park it against the bottom edge (where a reviewer may drag it), then write a long note.
    await composer.evaluate((el) => { el.style.top = (window.innerHeight - el.offsetHeight - 8) + "px"; });
    await composer.locator("textarea").fill(lines(60, "a very long draft"));

    // Growing a floating surface that was positioned before it grew must not push its actions
    // below the fold - it pulls itself back into the viewport instead.
    await expect(composer.locator('[data-act="save"]')).toBeInViewport();
    const box = await composer.boundingBox();
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.y + box.height).toBeLessThanOrEqual(700);
  });

  test("a grown in-document dialog stays fully on screen too (CMH-GROW-02)", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 700 });
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "a note to edit", 0);
    const pop = await openPopoverEditor(page);
    await pop.evaluate((el) => { el.style.top = (window.innerHeight - el.offsetHeight - 8) + "px"; });
    await pop.locator("textarea.cm-comment-popover-input").fill(lines(60, "a very long edit"));

    await expect(pop.locator('[data-act="edit-save"]')).toBeInViewport();
    const box = await pop.boundingBox();
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.y + box.height).toBeLessThanOrEqual(700);
  });

  test("a short viewport never leaves a grown composer taller than the screen (CMH-GROW-02)", async ({ page }) => {
    // A landscape phone: the surface must bound itself to the viewport (and scroll inside) rather
    // than growing past a height no clamp could pull back.
    await page.setViewportSize({ width: 740, height: 380 });
    await openInline(page);
    const composer = await openComposerFor(page, "#commentRoot p");
    await composer.locator("textarea").fill(lines(80, "a long draft on a small screen"));

    const box = await composer.boundingBox();
    expect(box.height).toBeLessThanOrEqual(380 - 16 + 1);
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.y + box.height).toBeLessThanOrEqual(380);
    // Bounded is not enough on its own - Save has to be genuinely reachable.
    await expect(composer.locator('[data-act="save"]')).toBeInViewport();
  });

  test("a manual resize wins - autogrow stops for that editor (CMH-GROW-02)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "the initial point", 0);
    const ta = await openReplyEditor(page);
    await ta.fill("first line");
    const base = await heightOf(ta);
    await ta.fill(lines(6, "growing"));
    expect(await heightOf(ta)).toBeGreaterThan(base + 40);

    // Dragging the native `resize: vertical` handle writes an inline height the runtime did not
    // set; that is exactly what this simulates (the native handle cannot be dragged from a script).
    // 420px is well clear of the height any of these drafts would autogrow to, so only the manual
    // latch - not a numeric coincidence - can satisfy the assertions below.
    await ta.evaluate((el) => { el.style.height = "420px"; });
    await ta.fill(lines(12, "after the drag"));
    expect(Math.round(await heightOf(ta))).toBe(420);
    await ta.fill("back to one line");
    expect(Math.round(await heightOf(ta))).toBe(420);
  });

  test("a hand-sized reply editor keeps its height across a sidebar re-render (CMH-GROW-02)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "the initial point", 0);
    const ta = await openReplyEditor(page);
    await ta.fill("a draft in progress");
    await ta.evaluate((el) => { el.style.height = "420px"; });
    await ta.fill("a draft in progress, still");
    expect(Math.round(await heightOf(ta))).toBe(420);

    // Sorting re-renders the list and rebuilds the editor; the draft AND the reviewer's own size
    // must both come back, or an unrelated re-render silently undoes their drag.
    await page.click("#btnSort");
    const reopened = page.locator(".cm-card .cm-reply-compose textarea").last();
    await expect(reopened).toHaveValue("a draft in progress, still");
    expect(Math.round(await heightOf(reopened))).toBe(420);
    await reopened.fill(lines(12, "typing on"));
    expect(Math.round(await heightOf(reopened))).toBe(420);
  });

  test("a drag with no typing after it still survives a re-render (CMH-GROW-02)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "the initial point", 0);
    const ta = await openReplyEditor(page);
    await ta.fill("a draft in progress");
    // No input event follows the drag here, so the layer has not latched the manual size yet - the
    // re-render snapshot has to recognise the hand-set height on its own.
    await ta.evaluate((el) => { el.style.height = "420px"; });

    await page.click("#btnSort");
    const reopened = page.locator(".cm-card .cm-reply-compose textarea").last();
    await expect(reopened).toHaveValue("a draft in progress");
    expect(Math.round(await heightOf(reopened))).toBe(420);
  });

  test("the reply input renders at the same font size as the composer (CMH-GROW-03)", async ({ page }) => {
    await openInline(page);
    const composer = await openComposerFor(page, "#commentRoot p");
    const composerFont = await composer.locator("textarea").evaluate((el) => getComputedStyle(el).fontSize);
    await composer.locator('[data-act="cancel"]').click();
    await expect(page.locator(".cm-composer")).toHaveCount(0);

    await addTextComment(page, "#commentRoot p", "the initial point", 0);
    const ta = await openReplyEditor(page);
    expect(await ta.evaluate((el) => getComputedStyle(el).fontSize)).toBe(composerFont);
    // And the same size as the note it is answering, not the small metadata token.
    const noteFont = await page.locator(".cm-card .cm-entry-root .note").first()
      .evaluate((el) => getComputedStyle(el).fontSize);
    expect(await ta.evaluate((el) => getComputedStyle(el).fontSize)).toBe(noteFont);
  });
});
