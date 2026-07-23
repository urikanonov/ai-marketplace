import { test, expect } from "@playwright/test";
import { ready, startStaticServer, routeMermaidLocal, stageContent } from "./helpers.js";

// Hermetic coverage for the shipped `.cmh-diagram-gallery` helper (CMH-CONTENT-19), decoupled from
// any demo report: a staged document with exactly the diagrams each case needs. Everything is served
// over http with mermaid routed to the local vendored copy, so the diagrams actually render and the
// run stays network-isolated.

const FLOW = 'flowchart LR\n  A["Start"] --> B["End"]';
// A vertical state machine renders tall-and-narrow, so it overflows a bounded card and scrolls.
const STATE = "stateDiagram-v2\n  [*] --> S1\n  S1 --> S2\n  S2 --> S3\n  S3 --> S4\n  S4 --> S5\n  S5 --> [*]";
const GANTT = "gantt\n  title Schedule\n  dateFormat YYYY-MM-DD\n  section S\n  T1 :a1, 2024-01-01, 30d\n  T2 :after a1, 20d";
// A pie renders in TWO phases (empty <g> then slices), so it exercises the content-readiness gate.
const PIE = "pie title Mix\n  \"A\" : 40\n  \"B\" : 35\n  \"C\" : 25";

async function stageGallery(page, inner, key) {
  // Trailing spacer so the document is taller than the viewport: the clip-aware button test scrolls
  // the gallery off the top of the viewport to assert the button hides.
  const content = `<section id="g"><h2>Gallery</h2><div class="cmh-diagram-gallery">${inner}</div></section>` +
    `<section id="spacer"><p>spacer</p><div style="height:1600px"></div></section>`;
  const { dir } = stageContent(content, { key, source: key + ".html" });
  const server = await startStaticServer(dir);
  await routeMermaidLocal(page);
  await page.goto(server.url + "/test-doc.html");
  await ready(page);
  return server;
}

// The card frame + overflow are applied by CSS once the mermaid host has been indexed and laid out
// (a rAF pass), and mermaid populates some diagrams (e.g. a pie) in TWO phases - an empty
// `<svg><g></g></svg>` first, then the real content a few hundred ms later. Under heavy parallel load
// the SVG can exist a frame or two before either settles, so gate the layout measurements on the
// SETTLED state (every diagram card framed, scrollable, AND with real rendered content) rather than
// measuring mid-render. This asserts the real contract; if a regression drops the frame or the content
// it never settles and the poll times out (the test still fails).
async function waitGalleryFramed(page, cardSel) {
  await expect.poll(async () => page.evaluate((s) => {
    const cards = [...document.querySelectorAll(s)];
    if (!cards.length) return false;
    return cards.every((c) => {
      const cs = getComputedStyle(c);
      const svg = c.querySelector("svg");
      return (parseFloat(cs.borderTopWidth) || 0) >= 1 && /auto|scroll/.test(cs.overflowY) &&
        svg && svg.querySelectorAll("*").length >= 5;
    });
  }, cardSel), { timeout: 15000 }).toBe(true);
}

test.describe("diagram gallery helper (CMH-CONTENT-19)", () => {
  test("frames only diagram containers and leaves a stray table alone (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1400, height: 1000 });
    const inner =
      `<pre class="mermaid cm-skip">${PIE}</pre>` +
      `<div class="mermaid cm-skip">${FLOW}</div>` +
      `<table id="stray"><thead><tr><th>a</th><th>b</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>`;
    const server = await stageGallery(page, inner, "cmh-gallery-scope");
    try {
      await expect(page.locator(".cmh-diagram-gallery > pre.mermaid svg")).toHaveCount(1, { timeout: 20000 });
      await expect(page.locator(".cmh-diagram-gallery > div.mermaid svg")).toHaveCount(1, { timeout: 20000 });
      await waitGalleryFramed(page, ".cmh-diagram-gallery > pre.mermaid, .cmh-diagram-gallery > div.mermaid");
      const styles = await page.evaluate(() => {
        const g = document.querySelector(".cmh-diagram-gallery");
        const pre = g.querySelector(":scope > pre.mermaid");
        const div = g.querySelector(":scope > div.mermaid");
        const table = g.querySelector(":scope > table#stray");
        const card = (el) => {
          const cs = getComputedStyle(el);
          return { display: cs.display, overflowY: cs.overflowY, border: Math.round(parseFloat(cs.borderTopWidth) || 0), h: Math.round(el.getBoundingClientRect().height) };
        };
        return { gallery: getComputedStyle(g).display, pre: card(pre), div: card(div), table: card(table) };
      });
      // The gallery is a grid, and the two DIAGRAM containers are framed, bounded, scrollable cards.
      expect(styles.gallery, "gallery is a grid").toBe("grid");
      for (const kind of ["pre", "div"]) {
        expect(styles[kind].border, `${kind}.mermaid card is framed`).toBeGreaterThanOrEqual(1);
        expect(styles[kind].overflowY, `${kind}.mermaid card scrolls`).toMatch(/auto|scroll/);
        expect(styles[kind].display, `${kind}.mermaid card is a grid card`).toBe("grid");
      }
      // The stray table is NOT turned into a card: it keeps table layout (not display:grid), gets no
      // 25rem bounded-card height, and no auto-scroll frame - the exact breakage that targeting `> *`
      // (instead of the diagram containers) would have caused.
      expect(styles.table.display, "stray table keeps table layout (not a grid card)").not.toBe("grid");
      expect(styles.table.overflowY, "stray table is not given the card scroll frame").not.toMatch(/auto|scroll/);
      expect(styles.table.h, "stray table is not forced to the 25rem card height").toBeLessThan(360);
      expect(styles.table.border, "stray table is not given the card frame border").toBe(0);
    } finally {
      await server.close();
    }
  });

  test("a tall diagram scrolls inside a bounded uniform card and an overflowing card is keyboard-focusable (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1400, height: 1000 });
    const inner = `<pre class="mermaid cm-skip">${FLOW}</pre><pre class="mermaid cm-skip">${STATE}</pre>`;
    const server = await stageGallery(page, inner, "cmh-gallery-scroll");
    try {
      await expect(page.locator(".cmh-diagram-gallery > pre.mermaid svg")).toHaveCount(2, { timeout: 20000 });
      await waitGalleryFramed(page, ".cmh-diagram-gallery > pre.mermaid");
      const cards = page.locator(".cmh-diagram-gallery > pre.mermaid");
      const shortCard = cards.nth(0), tallCard = cards.nth(1);

      // Uniform, bounded heights (no marooning): both cards are the same height near the 25rem contract.
      const heights = await page.evaluate(() =>
        [...document.querySelectorAll(".cmh-diagram-gallery > pre.mermaid")].map((el) => Math.round(el.getBoundingClientRect().height)));
      expect(Math.max(...heights) - Math.min(...heights), "cards are uniform height").toBeLessThanOrEqual(2);
      expect(Math.min(...heights), "card height is bounded near 25rem, not collapsed").toBeGreaterThanOrEqual(360);
      expect(Math.max(...heights), "card height is bounded, not a marooning tower").toBeLessThanOrEqual(520);

      // The tall card is GENUINELY scrollable (not merely scrollHeight>clientHeight, which is also true
      // under overflow:hidden): overflow-y is auto/scroll AND setting scrollTop actually moves it.
      const tall = await tallCard.evaluate((el) => {
        const overflowY = getComputedStyle(el).overflowY;
        el.scrollTop = 120;
        return { overflowY, scrollTop: el.scrollTop, overflows: el.scrollHeight > el.clientHeight + 1 };
      });
      expect(tall.overflows, "the tall state diagram overflows its bounded card").toBe(true);
      expect(tall.overflowY, "the tall card's overflow-y is scrollable (not clipped)").toMatch(/auto|scroll/);
      expect(tall.scrollTop, "the tall card actually scrolls (clipped content is reachable)").toBeGreaterThan(0);

      // The overflowing card is keyboard-focusable so a sighted keyboard-only user can scroll to the
      // clipped bottom (WCAG 2.1.1); the card that fits gets NO tab stop.
      await expect(tallCard, "overflowing card is keyboard-focusable").toHaveAttribute("tabindex", "0", { timeout: 10000 });
      await expect(tallCard).toHaveAttribute("role", "figure");
      expect(await tallCard.getAttribute("aria-label"), "focusable card is labelled").toMatch(/scroll/i);
      expect(await shortCard.getAttribute("tabindex"), "a card that fits gets no tab stop").toBeNull();

      // Removal path: once a card no longer overflows (here we grow its height so the diagram fits),
      // the resize re-sync removes the tab stop, role and label we added.
      await tallCard.evaluate((el) => { el.style.height = "2400px"; });
      await page.evaluate(() => window.dispatchEvent(new Event("resize")));
      await expect.poll(async () => tallCard.getAttribute("tabindex"), { timeout: 10000 }).toBeNull();
      expect(await tallCard.getAttribute("role"), "role removed with the tab stop").toBeNull();
      expect(await tallCard.getAttribute("aria-label"), "label removed with the tab stop").toBeNull();
    } finally {
      await server.close();
    }
  });

  test("a captioned figure card is framed and focusable but keeps its figcaption accessible name (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1400, height: 1000 });
    // A `> figure` card wrapping a tall mermaid diagram with a caption: the figure is the scroll card
    // (the inner pre is not a direct gallery child, so it is not itself framed). It must be framed and
    // keyboard-focusable, but must NOT get our scroll aria-label - that would clobber the figcaption's
    // native accessible name for screen readers.
    const inner = `<figure style="height:80px"><pre class="mermaid cm-skip">${STATE}</pre><figcaption>State machine</figcaption></figure>`;
    const server = await stageGallery(page, inner, "cmh-gallery-figcap");
    try {
      await expect(page.locator(".cmh-diagram-gallery > figure svg")).toHaveCount(1, { timeout: 20000 });
      await waitGalleryFramed(page, ".cmh-diagram-gallery > figure");
      const fig = page.locator(".cmh-diagram-gallery > figure");
      const info = await fig.evaluate((el) => ({
        border: Math.round(parseFloat(getComputedStyle(el).borderTopWidth) || 0),
        overflowY: getComputedStyle(el).overflowY,
        overflows: el.scrollHeight > el.clientHeight + 1,
        hasCaption: !!el.querySelector("figcaption"),
      }));
      expect(info.border, "figure card is framed").toBeGreaterThanOrEqual(1);
      expect(info.overflowY, "figure card scrolls").toMatch(/auto|scroll/);
      expect(info.overflows, "the tall diagram overflows the figure card").toBe(true);
      // Focusable for keyboard scrolling...
      await expect(fig, "overflowing figure card is keyboard-focusable").toHaveAttribute("tabindex", "0", { timeout: 10000 });
      // ...but the figcaption is preserved as the accessible name (no generic scroll aria-label).
      expect(info.hasCaption, "figcaption is preserved").toBe(true);
      expect(await fig.getAttribute("aria-label"), "no scroll aria-label clobbers the figcaption").toBeNull();
    } finally {
      await server.close();
    }
  });

  test("on a phone the gallery is a frameless single-column flow with no tab stop (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 400, height: 800 });
    const inner = `<pre class="mermaid cm-skip">${FLOW}</pre><pre class="mermaid cm-skip">${STATE}</pre>`;
    const server = await stageGallery(page, inner, "cmh-gallery-mobile");
    try {
      await expect(page.locator(".cmh-diagram-gallery > pre.mermaid svg")).toHaveCount(2, { timeout: 20000 });
      const info = await page.evaluate(() => {
        const g = document.querySelector(".cmh-diagram-gallery");
        const cards = [...g.querySelectorAll(":scope > pre.mermaid")];
        return {
          galleryDisplay: getComputedStyle(g).display,
          cards: cards.map((c) => ({ display: getComputedStyle(c).display, tabindex: c.getAttribute("tabindex") })),
        };
      });
      // Below the 481px breakpoint the grid does not apply: the gallery is a plain single-column flow
      // (the diagram uses the layer's own responsive handling, CMH-RESP-01), and no card is a bounded
      // scroll card, so none is given a tab stop.
      expect(info.galleryDisplay, "gallery is a plain block flow on mobile").toBe("block");
      for (const c of info.cards) {
        expect(c.display, "a mobile card is not a bounded grid card").not.toBe("grid");
        expect(c.tabindex, "a mobile card gets no tab stop").toBeNull();
      }
    } finally {
      await server.close();
    }
  });

  test("print stacks the gallery single-column and unframes each card (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1400, height: 1000 });
    const inner = `<pre class="mermaid cm-skip">${FLOW}</pre><pre class="mermaid cm-skip">${STATE}</pre>`;
    const server = await stageGallery(page, inner, "cmh-gallery-print");
    try {
      await expect(page.locator(".cmh-diagram-gallery > pre.mermaid svg")).toHaveCount(2, { timeout: 20000 });
      await waitGalleryFramed(page, ".cmh-diagram-gallery > pre.mermaid");
      await page.emulateMedia({ media: "print" });
      const info = await page.evaluate(() => {
        const g = document.querySelector(".cmh-diagram-gallery");
        const cards = [...g.querySelectorAll(":scope > pre.mermaid")];
        return {
          galleryDisplay: getComputedStyle(g).display,
          cards: cards.map((c) => {
            const cs = getComputedStyle(c);
            return { display: cs.display, overflow: cs.overflow, border: Math.round(parseFloat(cs.borderTopWidth) || 0) };
          }),
        };
      });
      // In print the gallery stacks to a single column and each card is unframed with the scroll bound
      // dropped, so the WHOLE diagram prints (not just the 25rem scroll window).
      expect(info.galleryDisplay, "gallery stacks to a single column in print").toBe("block");
      for (const c of info.cards) {
        expect(c.display, "a card is a plain block in print (grid context stripped)").toBe("block");
        expect(c.overflow, "a card's overflow is visible in print (whole diagram prints)").toMatch(/visible/);
        expect(c.border, "a card is unframed in print").toBe(0);
      }
    } finally {
      await server.close();
    }
  });

  test("the clip-aware whole-diagram button stays inside a scrolled card and hides when it scrolls off (CMH-CONTENT-19 / CMH-MMD-06)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1200, height: 900 });
    // Force the gantt's card short so a fitting diagram overflows and scrolls; the gantt title text is
    // an empty (non-node) area, so hovering it reliably offers the WHOLE-diagram button.
    const inner = `<pre class="mermaid" style="height:120px">${GANTT}</pre>`;
    const server = await stageGallery(page, inner, "cmh-gallery-clip");
    try {
      const host = page.locator(".cmh-diagram-gallery > pre.mermaid").first();
      await expect(host.locator("svg .titleText").first()).toBeVisible({ timeout: 20000 });
      await host.locator("svg .titleText").first().hover();
      const btn = page.locator("#mermaidAddBtn");
      await expect(btn).toBeVisible();
      await expect(btn).toHaveText(/diagram/i);

      const rects = () => page.evaluate(() => {
        const b = document.getElementById("mermaidAddBtn");
        const card = document.querySelector(".cmh-diagram-gallery > pre.mermaid");
        return { hidden: b.hidden, b: b.getBoundingClientRect(), c: card.getBoundingClientRect() };
      });
      const within = (r) => r.b.top >= r.c.top - 2 && r.b.bottom <= r.c.bottom + 2 &&
                            r.b.left >= r.c.left - 2 && r.b.right <= r.c.right + 2;

      // At rest the button sits inside the bounded card.
      expect(within(await rects()), "button starts inside the card").toBe(true);

      // Scroll the diagram UP inside the card. The raw svg top now sits ABOVE the card top; a
      // viewport-only clamp (the old bug) would place the button above the card. The clip-aware path
      // keeps it pinned to the visible card. The capture-phase scroll listener repositions it.
      await host.evaluate((el) => { el.scrollTop = 70; });
      await expect.poll(async () => within(await rects()), { timeout: 5000 }).toBe(true);
      const scrolled = await rects();
      expect(scrolled.b.top, "button stays at/below the card top after an internal scroll (not detached above)")
        .toBeGreaterThanOrEqual(scrolled.c.top - 2);

      // Scroll the whole card off the top of the viewport: the button hides rather than clamping to a
      // viewport edge detached from the diagram.
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await expect.poll(async () => (await rects()).hidden, { timeout: 5000 }).toBe(true);
    } finally {
      await server.close();
    }
  });
});
