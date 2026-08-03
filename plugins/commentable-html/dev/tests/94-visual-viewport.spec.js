import { test, expect } from "@playwright/test";
import { openInline, addTextComment, openComposerFor, selectText, storedComments } from "./helpers.js";

// Issue #880: every floating affordance used to measure the LAYOUT viewport
// (`window.innerWidth`/`innerHeight`) and to listen only on `window`. An on-screen keyboard and a
// pinch zoom shrink and move the VISUAL viewport without changing either, and they fire on
// `window.visualViewport` rather than on `window` - so a control the layer believed fitted could
// sit behind the keyboard, and nothing re-positioned it.
//
// The tests drive a FAKE `window.visualViewport` installed before the layer loads: it is the only
// way to make a headless browser report a visual viewport that differs from its layout viewport.

const VW = 1280;
const VH = 800;

// Install a scriptable stand-in for `window.visualViewport`, starting as the whole layout viewport
// (so nothing changes until a test moves it). `window.__cmhFakeVV` drives it from the test.
async function installFakeVisualViewport(page, initial) {
  await page.addInitScript((box) => {
    const listeners = { resize: new Set(), scroll: new Set() };
    const vv = {
      offsetLeft: box.left,
      offsetTop: box.top,
      pageLeft: box.left,
      pageTop: box.top,
      width: box.width,
      height: box.height,
      scale: box.scale || 1,
      onresize: null,
      onscroll: null,
      addEventListener(type, fn) { if (listeners[type] && fn) listeners[type].add(fn); },
      removeEventListener(type, fn) { if (listeners[type] && fn) listeners[type].delete(fn); },
      dispatchEvent() { return true; },
    };
    window.__cmhFakeVV = {
      set(next) {
        if (next.left != null) { vv.offsetLeft = next.left; vv.pageLeft = next.left; }
        if (next.top != null) { vv.offsetTop = next.top; vv.pageTop = next.top; }
        if (next.width != null) vv.width = next.width;
        if (next.height != null) vv.height = next.height;
        if (next.scale != null) vv.scale = next.scale;
      },
      fire(type) {
        listeners[type].forEach((fn) => {
          if (typeof fn === "function") fn({ type, target: vv });
          else if (fn && typeof fn.handleEvent === "function") fn.handleEvent({ type, target: vv });
        });
      },
      counts() { return { resize: listeners.resize.size, scroll: listeners.scroll.size }; },
    };
    Object.defineProperty(window, "visualViewport", { configurable: true, get() { return vv; } });
  }, initial || { left: 0, top: 0, width: VW, height: VH });
}

// Move the visible box and fire the event a real browser would fire for that change.
async function moveVisualViewport(page, box, event) {
  await page.evaluate(([next, type]) => {
    window.__cmhFakeVV.set(next);
    if (type) window.__cmhFakeVV.fire(type);
  }, [box, event || null]);
}

const boxOf = async (locator) => {
  const b = await locator.boundingBox();
  expect(b, "the surface should have a measurable box").not.toBeNull();
  return b;
};

async function firstCid(page) {
  return (await storedComments(page))[0].id;
}

test.describe("floating affordances measure the visual viewport (CMH-CORE-19)", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: VW, height: VH });
  });

  test("the hover bubble stays inside the visual viewport, and hides when its highlight leaves it (CMH-CORE-19)", async ({ page }) => {
    await installFakeVisualViewport(page);
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "a note near the top", 0);
    const cid = await firstCid(page);
    const mark = page.locator(`mark.cm-hl[data-cid="${cid}"]`).first();
    const anchor = await boxOf(mark);

    // The visible box still contains the highlight: the bubble shows, fully inside that box.
    const visible = { left: 0, top: Math.max(0, Math.round(anchor.y) - 40), width: VW, height: 220 };
    await moveVisualViewport(page, visible, "resize");
    await mark.hover();
    const bubble = page.locator("#hlBubble");
    await expect(bubble).toBeVisible();
    const bb = await boxOf(bubble);
    expect(bb.y).toBeGreaterThanOrEqual(visible.top - 1);
    expect(bb.y + bb.height).toBeLessThanOrEqual(visible.top + visible.height + 1);

    // Now the on-screen keyboard covers the highlight: the visible box ends above it. The bubble
    // must not be left floating over the keyboard pointing at content nobody can see.
    await page.mouse.move(5, 5);
    await moveVisualViewport(page, { left: 0, top: 0, width: VW, height: Math.max(60, Math.round(anchor.y) - 40) }, "resize");
    await mark.hover();
    await expect(bubble).toBeHidden();
  });

  test("the in-document dialog fits the visual viewport, not the layout viewport (CMH-CORE-19)", async ({ page }) => {
    await installFakeVisualViewport(page);
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "a note to open in place", 0);
    const cid = await firstCid(page);
    const mark = page.locator(`mark.cm-hl[data-cid="${cid}"]`).first();
    const anchor = await boxOf(mark);

    // A soft keyboard leaves a short visible box that still shows the highlight near its top.
    const visible = { left: 0, top: Math.max(0, Math.round(anchor.y) - 30), width: VW, height: 240 };
    await moveVisualViewport(page, visible, "resize");
    await mark.hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();

    const pb = await boxOf(pop);
    expect(pb.y).toBeGreaterThanOrEqual(visible.top - 1);
    expect(pb.y + pb.height).toBeLessThanOrEqual(visible.top + visible.height + 1);
    // The height cap follows the VISIBLE box too, so a long note scrolls inside the dialog rather
    // than pushing its actions row behind the keyboard.
    const cap = await pop.evaluate((el) => parseFloat(el.style.maxHeight));
    expect(cap).toBeLessThanOrEqual(visible.height - 15);
  });

  test("a visualViewport resize re-fits the open dialog with no window resize (CMH-CORE-19)", async ({ page }) => {
    await installFakeVisualViewport(page);
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "a note the keyboard will cover", 0);
    const cid = await firstCid(page);
    const mark = page.locator(`mark.cm-hl[data-cid="${cid}"]`).first();
    const anchor = await boxOf(mark);
    await mark.hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();

    // Focusing the note is what opens the keyboard: only `visualViewport` reports it, and only
    // `visualViewport` fires. The dialog must still pull itself back into what is left on screen.
    // The visible box is sized from the dialog itself, so it is only tall enough to hold the
    // dialog ABOVE the highlight - a dialog left where it was opened cannot satisfy the assertion.
    const dh = Math.round((await boxOf(pop)).height);
    const visible = { left: 0, top: Math.max(0, Math.round(anchor.y) - 30), width: VW, height: dh + 20 };
    await moveVisualViewport(page, visible, "resize");
    await expect.poll(async () => {
      const b = await pop.boundingBox();
      return b ? Math.round(b.y + b.height) : -1;
    }).toBeLessThanOrEqual(visible.top + visible.height + 1);
    const after = await boxOf(pop);
    expect(after.y).toBeGreaterThanOrEqual(visible.top - 1);
  });

  test("panning a pinch-zoomed page (a visualViewport scroll) re-fits the dialog (CMH-CORE-19)", async ({ page }) => {
    await installFakeVisualViewport(page);
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "a note on a zoomed page", 0);
    const cid = await firstCid(page);
    const mark = page.locator(`mark.cm-hl[data-cid="${cid}"]`).first();
    const anchor = await boxOf(mark);
    await mark.hover();
    await page.locator("#hlBubble").click();
    const pop = page.locator(".cm-comment-popover");
    await expect(pop).toBeVisible();

    // A pinch zoom shrinks the visible box (`scale > 1`); the reader then PANS it, which changes
    // only the offsets and fires `scroll` alone. Zoom first...
    const dh = Math.round((await boxOf(pop)).height);
    const zoomed = { left: 0, top: Math.max(0, Math.round(anchor.y) - 30), width: VW / 2, height: dh + 20, scale: 2 };
    await moveVisualViewport(page, zoomed, "resize");
    await expect.poll(async () => {
      const b = await pop.boundingBox();
      return b ? Math.round(b.y + b.height) : -1;
    }).toBeLessThanOrEqual(zoomed.top + zoomed.height + 1);

    // ...then pan upwards with the SAME size, firing only `scroll`.
    const panned = { top: Math.max(0, Math.round(anchor.y) - 100) };
    await moveVisualViewport(page, panned, "scroll");
    await expect.poll(async () => {
      const b = await pop.boundingBox();
      return b ? Math.round(b.y + b.height) : -1;
    }).toBeLessThanOrEqual(panned.top + zoomed.height + 1);
    expect((await boxOf(pop)).y).toBeGreaterThanOrEqual(panned.top - 1);
  });

  test("the Add-comment menu is clamped into the visual viewport (CMH-CORE-19)", async ({ page }) => {
    await installFakeVisualViewport(page);
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "seed so the paragraph is anchored", 0);

    // Only a narrow band near the bottom-right of the layout viewport is actually on screen.
    const visible = { left: 400, top: 420, width: 420, height: 300 };
    await moveVisualViewport(page, visible, "resize");
    await selectText(page, "#commentRoot p", { index: 1 });
    const menu = page.locator("#contextMenu");
    await expect(menu).toBeVisible();
    const mb = await boxOf(menu);
    expect(mb.x).toBeGreaterThanOrEqual(visible.left - 1);
    expect(mb.y).toBeGreaterThanOrEqual(visible.top - 1);
    expect(mb.x + mb.width).toBeLessThanOrEqual(visible.left + visible.width + 1);
    expect(mb.y + mb.height).toBeLessThanOrEqual(visible.top + visible.height + 1);
  });

  test("a dragged composer cannot be parked outside the visual viewport (CMH-CORE-19)", async ({ page }) => {
    await installFakeVisualViewport(page);
    await openInline(page);
    const composer = await openComposerFor(page, "#commentRoot p");
    await expect(composer).toBeVisible();

    const visible = { left: 120, top: 60, width: 520, height: 340 };
    await moveVisualViewport(page, visible, "resize");

    // Drag the composer by its handle towards the bottom-right of the LAYOUT viewport. The clamp
    // has to stop it at the edge of what is actually on screen.
    const handle = composer.locator(".cm-composer-handle");
    const hb = await boxOf(handle);
    await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
    await page.mouse.down();
    await page.mouse.move(VW - 30, VH - 30, { steps: 8 });
    await page.mouse.up();

    const cb = await boxOf(composer);
    expect(cb.x).toBeGreaterThanOrEqual(visible.left - 1);
    expect(cb.y).toBeGreaterThanOrEqual(visible.top - 1);
    expect(cb.x + cb.width).toBeLessThanOrEqual(visible.left + visible.width + 1);
    expect(cb.y + cb.height).toBeLessThanOrEqual(visible.top + visible.height + 1);
  });

  test("opening and closing surfaces does not accumulate visualViewport listeners (CMH-CORE-19)", async ({ page }) => {
    await installFakeVisualViewport(page);
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "a note opened many times", 0);
    const cid = await firstCid(page);
    const mark = page.locator(`mark.cm-hl[data-cid="${cid}"]`).first();
    const pop = page.locator(".cm-comment-popover");

    const counts = () => page.evaluate(() => window.__cmhFakeVV.counts());
    // The layer listens on the visual viewport at all (this is the wiring the fix adds).
    const baseline = await counts();
    expect(baseline.resize).toBeGreaterThan(0);
    expect(baseline.scroll).toBeGreaterThan(0);

    for (let i = 0; i < 4; i++) {
      await mark.hover();
      await page.locator("#hlBubble").click();
      await expect(pop).toBeVisible();
      await pop.locator('[data-act="close"]').click();
      await expect(pop).toHaveCount(0);
      const composer = await openComposerFor(page, "#commentRoot p", { index: 1 });
      await composer.locator('[data-act="cancel"]').click();
      await expect(composer).toHaveCount(0);
    }
    expect(await counts()).toEqual(baseline);
  });
});
