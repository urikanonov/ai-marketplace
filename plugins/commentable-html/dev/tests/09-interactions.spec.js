import { test, expect } from "@playwright/test";
import { openKitchenSink, addTextComment, openComposerFor, selectText, distinctCids, realDragSelect, allCids } from "./helpers.js";

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
    const composer = page.locator(".cm-composer").last();
    await expect(composer.locator("textarea")).toHaveValue("original note");
    await composer.locator("textarea").fill("edited note");
    await composer.locator('[data-act="save"]').click();
    await expect(page.locator("#commentList")).toContainText("edited note");
    await expect(page.locator("#commentList")).not.toContainText("original note");
    await expect(page.locator(".cm-card .meta")).toContainText(/edited/i);
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
