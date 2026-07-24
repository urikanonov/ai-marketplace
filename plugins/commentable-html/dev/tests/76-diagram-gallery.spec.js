import { test, expect } from "@playwright/test";
import { ready, startStaticServer, routeMermaidLocal, stageContent } from "./helpers.js";

// Hermetic coverage for the shipped `.cmh-diagram-gallery` helper (CMH-CONTENT-19), decoupled from any
// demo report: a staged document with exactly the diagrams each case needs. Everything is served over
// http with mermaid routed to the local vendored copy, so the diagrams actually render and the run
// stays network-isolated.

// A representative multi-node flowchart (a decision with two branches), like the demo's - wide but with
// real vertical extent, so it is not a degenerate thin band.
const FLOW = 'flowchart LR\n  A["Signal"] --> B{"Known issue?"}\n  B -->|yes| C["Runbook"]\n  B -->|no| D["Triage"]';
// A vertical state machine renders TALL and NARROW - the aspect ratio that used to be clipped/scrolled
// or slivered; the gallery must show it whole in a hugging, full-height card.
const STATE = "stateDiagram-v2\n  [*] --> S1\n  S1 --> S2\n  S2 --> S3\n  S3 --> S4\n  S4 --> S5\n  S5 --> [*]";
const GANTT = "gantt\n  title Schedule\n  dateFormat YYYY-MM-DD\n  section S\n  T1 :a1, 2024-01-01, 30d\n  T2 :after a1, 20d";
// A pie renders in TWO phases (an empty <g> first, then slices), so it exercises the content-readiness
// gate; it is short-wide with text labels (a legibility-floor check).
const PIE = "pie title Mix\n  \"A\" : 40\n  \"B\" : 35\n  \"C\" : 25";

async function stageGallery(page, inner, key) {
  // Trailing spacer so the document is taller than the viewport for the button test that scrolls the
  // page.
  const content = `<section id="g"><h2>Gallery</h2><div class="cmh-diagram-gallery">${inner}</div></section>` +
    `<section id="spacer"><p>spacer</p><div style="height:1600px"></div></section>`;
  const { dir } = stageContent(content, { key, source: key + ".html" });
  const server = await startStaticServer(dir);
  await routeMermaidLocal(page);
  await page.goto(server.url + "/test-doc.html");
  await ready(page);
  return server;
}

// Gate measurements on the SETTLED and STABLE state: the card frame + svg sizing are applied in a rAF,
// and mermaid populates some diagrams (a pie) in two phases (empty <g> then real content). So wait
// until every card is framed AND its svg has real content AND the svg box dimensions are UNCHANGED
// across two consecutive polls - so a measurement can never land on a mid-render transient (a re-layout
// still in flight). If a regression drops the frame/content or never stabilises, the poll times out.
async function waitGalleryReady(page, cardSel) {
  let prev = null;
  await expect.poll(async () => {
    const sig = await page.evaluate((s) => {
      const cards = [...document.querySelectorAll(s)];
      if (!cards.length) return null;
      const ok = cards.every((c) => {
        const cs = getComputedStyle(c);
        const svg = c.querySelector("svg");
        return (parseFloat(cs.borderTopWidth) || 0) >= 1 && svg && svg.querySelectorAll("*").length >= 5;
      });
      if (!ok) return null;
      return cards.map((c) => {
        const r = c.querySelector("svg").getBoundingClientRect();
        return Math.round(r.width) + "x" + Math.round(r.height);
      }).join(",");
    }, cardSel);
    const stable = sig !== null && sig === prev;
    prev = sig;
    return stable;
  }, { timeout: 15000, intervals: [250] }).toBe(true);
}

// Measure each card and how well the diagram fills it. Because the cards HUG their diagram (uniform
// height, aspect-derived width), a correct render fills the card in BOTH dimensions, so we measure the
// painted CONTENT fill on each axis independently and assert the WEAKER one - `Math.max`/`svgFillW`
// alone are near-tautological (one axis is always ~full under a fixed height + hug), so they cannot
// catch a thin band / sliver / crushed diagram; `min(fillW,fillH)` and the area can. `contentW/H` is
// the on-screen union of the svg's painted leaf elements (text/shapes) clipped to the svg box; `clip`
// counts painted nodes that spill OUTSIDE the svg box (a shifted/overflowing diagram that overflow
// then hides - the clipping hole); `minTextH` is the smallest rendered text height (a legibility floor
// that catches a crushed-tiny diagram even when its bbox still spans the box).
function measureCards(page, cardSel) {
  return page.evaluate((s) => [...document.querySelectorAll(s)].map((el) => {
    const svg = el.querySelector("svg");
    const cr = el.getBoundingClientRect();
    const innerW = cr.width - 28, innerH = cr.height - 28; // card minus ~0.85rem padding each side
    const cs = getComputedStyle(el);
    let fillW = 0, fillH = 0, within = true, clip = 0, minTextH = Infinity, nText = 0, textInvisible = 0;
    let svgBoxW = 0, svgBoxH = 0, hasPositiveViewBox = false;
    let htmlLabelMinH = Infinity, nHtmlLabel = 0, htmlLabelInvisible = 0;
    if (svg) {
      const vb = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
      hasPositiveViewBox = vb.length === 4 && isFinite(vb[2]) && isFinite(vb[3]) && vb[2] > 0 && vb[3] > 0;
      const sr = svg.getBoundingClientRect();
      svgBoxW = Math.round(sr.width); svgBoxH = Math.round(sr.height);
      within = sr.left >= cr.left - 2 && sr.right <= cr.right + 2 && sr.top >= cr.top - 2 && sr.bottom <= cr.bottom + 2;
      const clipL = Math.max(sr.left, cr.left), clipR = Math.min(sr.right, cr.right);
      const clipT = Math.max(sr.top, cr.top), clipB = Math.min(sr.bottom, cr.bottom);
      let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity;
      svg.querySelectorAll("text, rect, circle, ellipse, path, polygon, line, image").forEach((n) => {
        const nr = n.getBoundingClientRect();
        if (nr.width <= 0 || nr.height <= 0) return;
        l = Math.min(l, Math.max(nr.left, clipL)); t = Math.min(t, Math.max(nr.top, clipT));
        r = Math.max(r, Math.min(nr.right, clipR)); b = Math.max(b, Math.min(nr.bottom, clipB));
        // A painted node that extends beyond the svg box (which is overflow:hidden) is clipped content.
        if (nr.left < sr.left - 1 || nr.right > sr.right + 1 || nr.top < sr.top - 1 || nr.bottom > sr.bottom + 1) clip++;
      });
      if (r > l) fillW = (r - l) / innerW;
      if (b > t) fillH = (b - t) / innerH;
      svg.querySelectorAll("text").forEach((n) => {
        const nr = n.getBoundingClientRect();
        if (nr.height > 0) { minTextH = Math.min(minTextH, nr.height); nText++; }
      });
      svg.querySelectorAll("text").forEach((n) => {
        const ts = getComputedStyle(n);
        const f = ts.fill, fo = parseFloat(ts.fillOpacity), o = parseFloat(ts.opacity);
        if (f === "rgba(0, 0, 0, 0)" || f === "transparent" || fo === 0 || o === 0 || ts.visibility === "hidden") textInvisible++;
      });
      // Non-deck mermaid (flowchart, class, ...) renders node labels as HTML in <foreignObject>, not as
      // svg <text>, so the <text> checks above miss them. Measure the HTML label content too: its
      // rendered height (a legibility floor) and its paint visibility (transparent color / zero opacity
      // / hidden - a broken HTML label would look empty while all the svg-geometry checks stay green).
      svg.querySelectorAll("foreignObject").forEach((fo) => {
        // Prefer the nested SEMANTIC label element explicitly: a comma selector returns the first DOM
        // match, which is mermaid's OUTER wrapper div (full box height), not the nested .nodeLabel -
        // measuring the wrapper would overstate a crushed inner label and let it pass.
        const label = fo.querySelector(".nodeLabel") || fo.querySelector(".edgeLabel") ||
          fo.querySelector("span") || fo.querySelector("p") || fo.querySelector("div") || fo;
        // Count every label that carries TEXT (skip structural/empty foreignObjects) REGARDLESS of
        // size, so a label that COLLAPSED to zero height - the exact regression this guards - is counted
        // and fails the floor/visibility checks, instead of being skipped (vacuous guard).
        if (!label.textContent || !label.textContent.trim()) return;
        nHtmlLabel++;
        const nr = label.getBoundingClientRect();
        htmlLabelMinH = Math.min(htmlLabelMinH, nr.height);
        const ls = getComputedStyle(label);
        let hidden = nr.width <= 0 || nr.height <= 0 || ls.color === "rgba(0, 0, 0, 0)" || ls.color === "transparent" || parseFloat(ls.opacity) === 0 || ls.visibility === "hidden" || ls.display === "none";
        // A hidden ANCESTOR (opacity/visibility/display) hides the label too, so fold the chain in.
        for (let a = label.parentElement; !hidden && a && svg.contains(a); a = a.parentElement) {
          const as = getComputedStyle(a);
          if (parseFloat(as.opacity) === 0 || as.visibility === "hidden" || as.display === "none") hidden = true;
        }
        if (hidden) htmlLabelInvisible++;
      });
    }
    return {
      src: (el.getAttribute("data-cmh-md-src") || "").split("\n")[0].trim(),
      cardH: Math.round(cr.height), cardW: Math.round(cr.width),
      border: Math.round(parseFloat(cs.borderTopWidth) || 0),
      overflowY: cs.overflowY, display: cs.display,
      svgBoxW, svgBoxH, fillW, fillH, fillMin: Math.min(fillW, fillH), fillArea: fillW * fillH,
      within, clip, minTextH: isFinite(minTextH) ? minTextH : null, nText, textInvisible, hasPositiveViewBox,
      nHtmlLabel, htmlLabelMinH: isFinite(htmlLabelMinH) ? htmlLabelMinH : null, htmlLabelInvisible,
      nodes: svg ? svg.querySelectorAll("*").length : 0,
      scrolls: el.scrollHeight > el.clientHeight + 1,
      scrollsX: el.scrollWidth > el.clientWidth + 1,
    };
  }), cardSel);
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
      await waitGalleryReady(page, ".cmh-diagram-gallery > pre.mermaid, .cmh-diagram-gallery > div.mermaid");
      const styles = await page.evaluate(() => {
        const g = document.querySelector(".cmh-diagram-gallery");
        const pre = g.querySelector(":scope > pre.mermaid");
        const div = g.querySelector(":scope > div.mermaid");
        const table = g.querySelector(":scope > table#stray");
        const card = (el) => {
          const cs = getComputedStyle(el);
          return { display: cs.display, overflowX: cs.overflowX, overflowY: cs.overflowY, border: Math.round(parseFloat(cs.borderTopWidth) || 0), h: Math.round(el.getBoundingClientRect().height) };
        };
        return { gallery: getComputedStyle(g).display, pre: card(pre), div: card(div), table: card(table) };
      });
      // The gallery is a flex-wrap, and the two DIAGRAM containers are framed, hugging cards.
      expect(styles.gallery, "gallery is a flex container").toBe("flex");
      for (const kind of ["pre", "div"]) {
        expect(styles[kind].border, `${kind}.mermaid card is framed`).toBeGreaterThanOrEqual(1);
        expect(styles[kind].display, `${kind}.mermaid card is a flex card`).toBe("flex");
        // The card scrolls horizontally for an over-wide diagram but is exactly one row tall
        // (overflow-y hidden), so it never grows vertically or scrolls up/down.
        expect(styles[kind].overflowX, `${kind}.mermaid card scrolls horizontally when needed`).toMatch(/auto|scroll/);
        expect(styles[kind].overflowY, `${kind}.mermaid card does not scroll vertically`).toMatch(/hidden/);
      }
      // The stray table is NOT turned into a card: it keeps table layout (not display:flex), gets no
      // card frame - the breakage that targeting `> *` would have caused.
      expect(styles.table.display, "stray table keeps table layout (not a flex card)").not.toBe("flex");
      expect(styles.table.h, "stray table is not forced to the card height").toBeLessThan(200);
      expect(styles.table.border, "stray table is not given the card frame border").toBe(0);
    } finally {
      await server.close();
    }
  });

  test("every diagram fills its hugging, uniform-height card - no tiny, no sliver, no clip, no marooning (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1600, height: 1000 });
    // A representative mix of aspect ratios: short-wide (flowchart, gantt, pie) and tall-narrow (state).
    const inner = [FLOW, GANTT, PIE, STATE].map((d) => `<pre class="mermaid cm-skip">${d}</pre>`).join("");
    const CARDS = ".cmh-diagram-gallery > pre.mermaid";
    const server = await stageGallery(page, inner, "cmh-gallery-fit");
    try {
      await expect(page.locator(CARDS + " svg")).toHaveCount(4, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
      const cells = await measureCards(page, CARDS);
      expect(cells.length).toBe(4);
      const heights = cells.map((c) => c.cardH);
      // Uniform card height => tidy rows, no marooning and no tall tower.
      expect(Math.max(...heights) - Math.min(...heights), "cards are uniform height").toBeLessThanOrEqual(2);
      // Pin the height to the expected ~15rem card (240px svg + ~28px padding + border) within a tight
      // band, so a uniform DOWNSCALE (e.g. a stray transform:scale on the cards) that keeps proportions
      // but shrinks everything is caught here, not silently passed by a loose >=200 floor.
      expect(Math.min(...heights), "card height matches the ~15rem design (not shrunk)").toBeGreaterThanOrEqual(255);
      expect(Math.max(...heights), "card height matches the ~15rem design (not grown)").toBeLessThanOrEqual(285);
      // The cards HUG their diagrams, so the tall-narrow state card must be markedly NARROWER than the
      // wide flowchart card. If a regression stopped the hug (e.g. a fixed-width/grid card came back),
      // the state diagram would sliver inside a wide card and this fails.
      const tall = cells.find((c) => c.src.startsWith("stateDiagram"));
      const wide = cells.find((c) => c.src.startsWith("flowchart"));
      expect(tall, "found the tall state diagram").toBeTruthy();
      expect(wide, "found the wide flowchart").toBeTruthy();
      expect(tall.cardW, "the tall diagram gets a narrow hugging card, not a wide one").toBeLessThan(wide.cardW * 0.6);
      for (const c of cells) {
        expect(c.border, `card "${c.src}" is framed`).toBeGreaterThanOrEqual(1);
        // Not empty (the two-phase pie / a failed render would leave an empty <g>).
        expect(c.nodes, `diagram "${c.src}" has real rendered content`).toBeGreaterThanOrEqual(5);
        // The whole hug-fit design depends on mermaid emitting a positive viewBox (so `width:auto`
        // derives the width from the aspect ratio); assert it, so a diagram type/version that omitted it
        // (which would collapse `width:auto`) is caught here rather than in a real browser.
        expect(c.hasPositiveViewBox, `diagram "${c.src}" has a positive viewBox (aspect-sizing works)`).toBe(true);
        // The card HUGS the svg box: the svg box fills the card in BOTH dimensions (definite height +
        // aspect-derived width, card shrinks to it). If the card is wider than the diagram (a sliver
        // regression) the svg box no longer fills the card width and this fails.
        expect(c.svgBoxW, `diagram "${c.src}" svg box fills the card width (card hugs it)`).toBeGreaterThanOrEqual((c.cardW - 28) * 0.85);
        expect(c.svgBoxH, `diagram "${c.src}" svg box fills the card height (fixed height honoured)`).toBeGreaterThanOrEqual((c.cardH - 28) * 0.85);
        // The painted CONTENT fills a real fraction of the card AREA. This is the anti-sliver /
        // anti-`Math.max` check: a thin band or a narrow strip has one tiny dimension, so its AREA
        // collapses (the old contain-fit state sliver scored ~0.04-0.18 here) even though one axis is full.
        expect(c.fillArea, `diagram "${c.src}" content fills the card area (not a sliver/band/tiny)`).toBeGreaterThanOrEqual(0.35);
        // No painted node spills outside the svg box - catches a shifted/overflowing diagram that would
        // be silently clipped.
        expect(c.clip, `diagram "${c.src}" has no clipped/overflowing content`).toBe(0);
        // Legibility floor: the smallest rendered text is not crushed to microscopic, and no text is
        // painted invisible (transparent fill / zero opacity) - a geometric-only check would miss that.
        if (c.nText > 0) {
          expect(c.minTextH, `diagram "${c.src}" text is legible, not crushed`).toBeGreaterThanOrEqual(6);
          expect(c.textInvisible, `diagram "${c.src}" text is painted (not transparent/hidden)`).toBe(0);
        }
        // The same legibility floor for HTML (foreignObject) node labels - flowchart/class labels are
        // HTML, not svg <text>, so they need their own check.
        if (c.nHtmlLabel > 0) {
          expect(c.htmlLabelMinH, `diagram "${c.src}" HTML label is legible, not crushed`).toBeGreaterThanOrEqual(6);
          expect(c.htmlLabelInvisible, `diagram "${c.src}" HTML labels are painted (not transparent/hidden)`).toBe(0);
        }
        // These representative diagrams all fit under the card cap, so the diagram is WHOLE inside its
        // card (not cropped) and the card does not scroll in either axis.
        expect(c.within, `diagram "${c.src}" is whole inside its card (not clipped)`).toBe(true);
        expect(c.scrolls, `card "${c.src}" does not scroll vertically`).toBe(false);
        expect(c.scrollsX, `card "${c.src}" does not scroll horizontally (fits the cap)`).toBe(false);
      }
    } finally {
      await server.close();
    }
  });

  test("an extreme-wide diagram keeps full height and scrolls horizontally instead of being crushed to a strip (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1400, height: 1000 });
    // A 10-node LR flowchart is far wider than the card cap. Forcing it to fit the card width (the old
    // contain-fit / max-width approach) crushed it into an unreadable ~14px-tall horizontal strip - the
    // sliver, rotated. Hug-fit renders it at FULL height and lets the card scroll horizontally, so it
    // stays readable.
    const WIDE = "flowchart LR\n  A[Ingest] --> B[Parse] --> C[Validate] --> D[Enrich] --> E[Score] --> F[Route] --> G[Notify] --> H[Store] --> I[Audit] --> J[Archive]";
    const inner = `<pre class="mermaid cm-skip">${WIDE}</pre>`;
    const CARDS = ".cmh-diagram-gallery > pre.mermaid";
    const server = await stageGallery(page, inner, "cmh-gallery-wide");
    try {
      await expect(page.locator(CARDS + " svg")).toHaveCount(1, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
      const [c] = await measureCards(page, CARDS);
      // FULL height (not a crushed strip): the svg box is the fixed card height and the visible content
      // fills that height.
      expect(c.svgBoxH, "extreme-wide diagram keeps the full fixed height").toBeGreaterThanOrEqual((c.cardH - 28) * 0.85);
      expect(c.fillH, "extreme-wide diagram content fills the card height (readable, not a strip)").toBeGreaterThanOrEqual(0.5);
      // It is WIDER than the card and the card provides HORIZONTAL scroll (so the whole diagram is
      // reachable), rather than being squeezed to fit.
      expect(c.svgBoxW, "the diagram is wider than the card (rendered at natural width)").toBeGreaterThan(c.cardW);
      expect(c.scrollsX, "the card scrolls horizontally to reveal the whole wide diagram").toBe(true);
      // Nothing is lost: every painted node is inside the (wide, scrollable) svg box, not clipped away.
      expect(c.clip, "no diagram content is clipped out of the scrollable svg box").toBe(0);
      // The card is still one row tall (uniform height); allow headroom for a classic (non-overlay,
      // e.g. Windows) horizontal scrollbar that adds ~17px to a scrolling card.
      expect(c.cardH, "the wide card is still ~one row tall (lower)").toBeGreaterThanOrEqual(255);
      expect(c.cardH, "the wide card is still ~one row tall (upper, allows a classic scrollbar)").toBeLessThanOrEqual(305);
      expect(c.scrolls, "the wide card does not scroll vertically").toBe(false);
      // The WHOLE diagram must be REACHABLE by scrolling: scroll fully left and confirm the diagram's
      // left edge comes into view inside the card, and that the scroll range spans the whole width. A
      // centered (non-`safe`) over-wide flex item puts the left edge at a large NEGATIVE offset that the
      // browser excludes from the scroll range, so the diagram's start is permanently clipped and
      // unreachable - a real-browser breakage a within/clip check against the svg's own box misses.
      const reach = await page.locator(CARDS).first().evaluate((card) => {
        card.scrollLeft = -1e9;
        const svg = card.querySelector("svg");
        const leftGap = svg.getBoundingClientRect().left - card.getBoundingClientRect().left;
        return { leftGap: Math.round(leftGap), coversWidth: card.scrollWidth >= Math.round(svg.getBoundingClientRect().width) - 4 };
      });
      expect(reach.leftGap, "the wide diagram's left edge is reachable by scrolling (not clipped off-screen)").toBeGreaterThanOrEqual(-4);
      expect(reach.coversWidth, "the horizontal scroll range covers the whole diagram width").toBe(true);
    } finally {
      await server.close();
    }
  });

  test("a div.mermaid card is sized and hugs its diagram just like a pre card (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1600, height: 1000 });
    // A `<div class="mermaid">` is a valid gallery diagram container alongside `<pre class="mermaid">`,
    // so it must get the SAME hug-fit sizing (fixed height, aspect-derived width, fills its card) - not
    // be left at some default size (which would sliver a tall diagram or leave one tiny).
    const inner = [FLOW, STATE].map((d) => `<div class="mermaid cm-skip">${d}</div>`).join("");
    const CARDS = ".cmh-diagram-gallery > div.mermaid";
    const server = await stageGallery(page, inner, "cmh-gallery-div");
    try {
      await expect(page.locator(CARDS + " svg")).toHaveCount(2, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
      const cells = await measureCards(page, CARDS);
      expect(cells.length).toBe(2);
      const heights = cells.map((c) => c.cardH);
      expect(Math.max(...heights) - Math.min(...heights), "div cards are uniform height").toBeLessThanOrEqual(2);
      for (const c of cells) {
        expect(c.cardH, `div card "${c.src}" is ~15rem tall (lower)`).toBeGreaterThanOrEqual(255);
        expect(c.cardH, `div card "${c.src}" is ~15rem tall (upper)`).toBeLessThanOrEqual(305);
        expect(c.svgBoxH, `div card "${c.src}" svg fills the card height`).toBeGreaterThanOrEqual((c.cardH - 28) * 0.85);
        expect(c.svgBoxW, `div card "${c.src}" card hugs the svg width`).toBeGreaterThanOrEqual((c.cardW - 28) * 0.85);
        expect(c.fillArea, `div card "${c.src}" fills its card`).toBeGreaterThanOrEqual(0.35);
        expect(c.within, `div card "${c.src}" is whole inside its card`).toBe(true);
      }
      // The tall div hugs narrow (like a pre), not a wide sliver.
      const tall = cells.find((c) => c.src.startsWith("stateDiagram"));
      const wide = cells.find((c) => c.src.startsWith("flowchart"));
      expect(tall.cardW, "the tall div card is markedly narrower than the wide div card").toBeLessThan(wide.cardW * 0.6);
    } finally {
      await server.close();
    }
  });

  test("a figure wrapping a div.mermaid is sized and hugs like a figure wrapping a pre (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1400, height: 1000 });
    // A `<figure><div class="mermaid">` is as valid as `<figure><pre class="mermaid">`, so it must get
    // the same hug-fit sizing (fixed height, aspect-derived width, whole) - not a tiny/slivered render.
    const inner = `<figure><div class="mermaid cm-skip">${STATE}</div><figcaption>State</figcaption></figure>`;
    const CARDS = ".cmh-diagram-gallery > figure";
    const server = await stageGallery(page, inner, "cmh-gallery-figdiv");
    try {
      await expect(page.locator(CARDS + " svg")).toHaveCount(1, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
      const [c] = await measureCards(page, CARDS);
      expect(c.border, "figure(div) card is framed").toBeGreaterThanOrEqual(1);
      expect(c.svgBoxH, "figure(div) diagram is rendered at full height (not slivered/tiny)").toBeGreaterThanOrEqual(200);
      expect(c.within, "figure(div) diagram is whole inside its card").toBe(true);
      expect(c.clip, "figure(div) diagram has no clipped content").toBe(0);
      expect(await page.locator(CARDS + " figcaption").count(), "figcaption preserved").toBe(1);
    } finally {
      await server.close();
    }
  });

  test("just above the mobile breakpoint the gallery is framed and the layer gate agrees (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    // At a viewport just above 481px, the CSS framed gallery must be active AND the JS gate must agree
    // (the layer's narrow/wide sizing classes are cleared for a gallery host). This couples the CSS
    // `@media screen and (min-width:481px)` and the JS `matchMedia("screen and (min-width:481px)")` at
    // the boundary: a desync (e.g. one moved to 600px) would leave an unguarded band where the framed
    // CSS drops but the JS still gates as desktop, and this canary catches it.
    await page.setViewportSize({ width: 520, height: 900 });
    const inner = `<pre class="mermaid cm-skip">${FLOW}</pre>`;
    const CARDS = ".cmh-diagram-gallery > pre.mermaid";
    const server = await stageGallery(page, inner, "cmh-gallery-bp");
    try {
      await expect(page.locator(CARDS + " svg")).toHaveCount(1, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
      const info = await page.evaluate((s) => {
        const g = document.querySelector(".cmh-diagram-gallery");
        const card = document.querySelector(s);
        return {
          galleryDisplay: getComputedStyle(g).display,
          cardDisplay: getComputedStyle(card).display,
          cardBorder: Math.round(parseFloat(getComputedStyle(card).borderTopWidth) || 0),
          hasLayerSizingClass: card.classList.contains("cmh-diagram-wide") || card.classList.contains("cmh-diagram-narrow"),
        };
      }, CARDS);
      // The CSS framed state is active just above the breakpoint...
      expect(info.galleryDisplay, "gallery is framed (flex) just above the breakpoint").toBe("flex");
      expect(info.cardDisplay, "card is a flex card just above the breakpoint").toBe("flex");
      expect(info.cardBorder, "card is framed just above the breakpoint").toBeGreaterThanOrEqual(1);
      // ...and the JS gate agrees: the layer's sizing classes are cleared for a gallery host (the CSS,
      // not the layer, sizes it) - proving the two breakpoints stay coupled.
      expect(info.hasLayerSizingClass, "layer sizing class is cleared (JS gate agrees with the framed CSS)").toBe(false);
    } finally {
      await server.close();
    }
  });

  test("diverse mermaid diagram types each emit a positive viewBox and fill their hugging card (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1600, height: 1000 });
    // Beyond the flowchart/gantt/pie/state set, exercise more diagram TYPES so the hug-fit contract (a
    // positive viewBox drives `width:auto`, the card hugs, both dimensions fill) is not silently
    // specific to a few kinds. Each is a distinct renderer with its own sizing path.
    const TYPES = {
      classDiagram: "classDiagram\n  class Router {\n    +route(sig)\n    +dedupe()\n  }\n  class Queue\n  Router --> Queue",
      erDiagram: "erDiagram\n  INCIDENT ||--o{ SIGNAL : has\n  INCIDENT ||--|| OWNER : assigned_to\n  SIGNAL ||--o{ SERVICE : emitted_by",
      journey: "journey\n  title Ops\n  section Triage\n    Detect: 5: On-call\n    Assess: 3: On-call\n  section Fix\n    Patch: 4: On-call",
      mindmap: "mindmap\n  root((Incident))\n    Detect\n      Alert\n    Respond\n      Mitigate\n      Resolve",
    };
    const keys = Object.keys(TYPES);
    const inner = keys.map((k) => `<pre class="mermaid cm-skip">${TYPES[k]}</pre>`).join("");
    const CARDS = ".cmh-diagram-gallery > pre.mermaid";
    const server = await stageGallery(page, inner, "cmh-gallery-types");
    try {
      await expect(page.locator(CARDS + " svg")).toHaveCount(keys.length, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
      const cells = await measureCards(page, CARDS);
      expect(cells.length).toBe(keys.length);
      for (const c of cells) {
        expect(c.hasPositiveViewBox, `diagram "${c.src}" emits a positive viewBox`).toBe(true);
        expect(c.nodes, `diagram "${c.src}" rendered real content`).toBeGreaterThanOrEqual(5);
        expect(c.svgBoxH, `diagram "${c.src}" is rendered at the fixed height`).toBeGreaterThanOrEqual((c.cardH - 28) * 0.85);
        expect(c.svgBoxW, `diagram "${c.src}" card hugs the diagram width`).toBeGreaterThanOrEqual((c.cardW - 28) * 0.85);
        expect(c.fillArea, `diagram "${c.src}" fills its card area (not tiny/sliver)`).toBeGreaterThanOrEqual(0.3);
        expect(c.clip, `diagram "${c.src}" has no clipped content`).toBe(0);
        expect(c.within, `diagram "${c.src}" is whole inside its card`).toBe(true);
        // These types (classDiagram/erDiagram/...) render their labels as HTML in <foreignObject>, which
        // the svg-geometry checks do not measure; assert the HTML labels are legible and painted so a
        // crushed/transparent label can't slip through green.
        if (c.nHtmlLabel > 0) {
          expect(c.htmlLabelMinH, `diagram "${c.src}" HTML labels are legible`).toBeGreaterThanOrEqual(6);
          expect(c.htmlLabelInvisible, `diagram "${c.src}" HTML labels are painted (not transparent/hidden)`).toBe(0);
        }
      }
      // The per-card HTML-label guard above is NON-VACUOUS: the classDiagram and erDiagram cards render
      // their labels as HTML in <foreignObject>, so each must report at least one measured HTML label -
      // otherwise a future mermaid change that stopped emitting HTML labels would silently make the
      // legibility guard vacuous (nHtmlLabel 0 => the assertions are skipped) with no signal.
      const byType = (needle) => cells.find((c) => c.src.startsWith(needle));
      expect(byType("classDiagram").nHtmlLabel, "the classDiagram card renders HTML labels (guard is not vacuous)").toBeGreaterThan(0);
      expect(byType("erDiagram").nHtmlLabel, "the erDiagram card renders HTML labels (guard is not vacuous)").toBeGreaterThan(0);
      // Uniform height across these different renderers too.
      const hs = cells.map((c) => c.cardH);
      expect(Math.max(...hs) - Math.min(...hs), "different diagram types share the uniform card height").toBeLessThanOrEqual(2);
    } finally {
      await server.close();
    }
  });

  test("an overflowing (extreme-wide) gallery card is keyboard-focusable but a fitting one is not (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1400, height: 1000 });
    // A card whose diagram overflows into the horizontal scroll must be keyboard-focusable so a
    // keyboard-only user can scroll to the clipped content (WCAG 2.1.1); a card that fits must NOT get a
    // spurious tab stop. Stage every card TYPE overflowing (a wide pre, a wide div, a wide CAPTIONED
    // figure, a wide UNCAPTIONED figure) plus a small fitting pre - so the a11y helper is proven to
    // cover pre/div/figure and both figure naming paths, not just one.
    const WIDE = "flowchart LR\n  A[Ingest] --> B[Parse] --> C[Validate] --> D[Enrich] --> E[Score] --> F[Route] --> G[Notify] --> H[Store] --> I[Audit] --> J[Archive]";
    const SMALL = "stateDiagram-v2\n  [*] --> S1\n  S1 --> [*]";
    const inner = `<pre class="mermaid cm-skip">${WIDE}</pre><pre class="mermaid cm-skip">${SMALL}</pre>` +
      `<div class="mermaid cm-skip">${WIDE}</div>` +
      `<figure><pre class="mermaid cm-skip">${WIDE}</pre><figcaption>Wide fig</figcaption></figure>` +
      `<figure><pre class="mermaid cm-skip">${WIDE}</pre></figure>`;
    const CARDS = ".cmh-diagram-gallery > pre.mermaid, .cmh-diagram-gallery > div.mermaid, .cmh-diagram-gallery > figure";
    const server = await stageGallery(page, inner, "cmh-gallery-a11y");
    try {
      await expect(page.locator(".cmh-diagram-gallery svg")).toHaveCount(5, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
      // Poll: the a11y marker is applied in a rAF after the card overflows.
      await expect.poll(async () => page.evaluate((s) => {
        const cards = [...document.querySelectorAll(s)];
        const wide = cards.find((c) => c.scrollWidth > c.clientWidth + 1);
        return wide ? wide.getAttribute("tabindex") : null;
      }, CARDS), { timeout: 5000 }).toBe("0");
      const info = await page.evaluate((s) => {
        const cards = [...document.querySelectorAll(s)];
        const overflowing = cards.filter((c) => c.scrollWidth > c.clientWidth + 1);
        const fit = cards.find((c) => c.scrollWidth <= c.clientWidth + 1);
        const desc = (c) => c ? { tag: c.tagName.toLowerCase(), hasCaption: !!c.querySelector("figcaption"), tabindex: c.getAttribute("tabindex"), role: c.getAttribute("role"), ariaLabel: c.getAttribute("aria-label"), ariaDesc: c.getAttribute("aria-description") } : null;
        return {
          overflowing: overflowing.map(desc),
          tags: overflowing.map((c) => c.tagName.toLowerCase()),
          fit: desc(fit),
        };
      }, CARDS);
      // Every overflowing card TYPE is present and keyboard-focusable.
      expect(info.tags.includes("pre"), "found an overflowing pre card").toBe(true);
      expect(info.tags.includes("div"), "found an overflowing div card").toBe(true);
      expect(info.overflowing.filter((c) => c.tag === "figure").length, "found both figure cards overflowing").toBe(2);
      for (const c of info.overflowing) {
        expect(c.tabindex, `overflowing ${c.tag} card is keyboard-focusable`).toBe("0");
      }
      // A pre/div card gets an explicit `group` role plus an aria-label hint; a native <figure> keeps
      // its implicit figure role and gets the hint via aria-description when captioned, aria-label when
      // not (so a screen-reader user is always told the card scrolls).
      const widePre = info.overflowing.find((c) => c.tag === "pre");
      const wideDiv = info.overflowing.find((c) => c.tag === "div");
      const capFigure = info.overflowing.find((c) => c.tag === "figure" && c.hasCaption);
      const noCapFigure = info.overflowing.find((c) => c.tag === "figure" && !c.hasCaption);
      for (const c of [widePre, wideDiv]) {
        expect(c.role, `overflowing ${c.tag} card has an explicit group role`).toBe("group");
        expect((c.ariaLabel || "").trim().length, `overflowing ${c.tag} card has a non-empty aria-label scroll hint`).toBeGreaterThan(0);
      }
      expect(capFigure.role, "captioned figure keeps its native figure role (no redundant explicit role)").toBeNull();
      expect((capFigure.ariaDesc || "").trim().length, "captioned overflowing figure has a non-empty aria-description scroll hint").toBeGreaterThan(0);
      expect(noCapFigure.role, "uncaptioned figure keeps its native figure role").toBeNull();
      expect((noCapFigure.ariaLabel || "").trim().length, "uncaptioned overflowing figure has a non-empty aria-label scroll hint").toBeGreaterThan(0);
      // The fitting card is NOT given a spurious tab stop.
      expect(info.fit.tabindex, "fitting card is not a spurious tab stop").toBeNull();
      // The focusable scroll card has a VISIBLE focus indicator (WCAG 2.4.7): the :focus-visible rule
      // for a scroll-a11y card must resolve to a real outline, not `outline:none`, so a keyboard user
      // can see which card they are on.
      const focusRing = await page.evaluate(() => {
        const find = (rules) => {
          for (const r of rules) {
            if (r.selectorText && r.selectorText.indexOf("data-cmh-scroll-a11y") >= 0 && r.selectorText.indexOf(":focus-visible") >= 0) return r;
            if (r.cssRules) { const inner = find(r.cssRules); if (inner) return inner; }
          }
          return null;
        };
        for (const sheet of document.styleSheets) {
          let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
          const r = find(rules);
          if (r) return { found: true, outlineStyle: r.style.outlineStyle, outlineWidth: r.style.outlineWidth };
        }
        return { found: false };
      });
      expect(focusRing.found, "a :focus-visible rule exists for a scroll-a11y gallery card").toBe(true);
      expect(focusRing.outlineStyle, "the focus ring has a visible outline style (not none)").not.toBe("none");
      expect(focusRing.outlineWidth, "the focus ring has a non-zero outline width").not.toBe("0px");
      // Resizing from desktop to mobile must CLEAR the tab stop (the card is no longer a bounded scroll
      // container below the breakpoint) - not leak it. This guards the a11y-helper being run on every
      // update, not only inside the desktop branch.
      await page.setViewportSize({ width: 400, height: 800 });
      await page.evaluate(() => window.dispatchEvent(new Event("resize")));
      await expect.poll(async () => page.evaluate((s) => {
        const cards = [...document.querySelectorAll(s)];
        return cards.some((c) => c.getAttribute("tabindex") === "0");
      }, CARDS), { timeout: 5000 }).toBe(false);
    } finally {
      await server.close();
    }
  });

  test("a long caption on a narrow diagram wraps to a bounded readable width - no tower, no marooning, diagram centred (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1400, height: 1000 });
    // A NARROW diagram with a caption far longer than it forces a design tension. Two failure modes:
    //   (a) MAROONING: if the figure stretched to the caption's full essay length, the tiny diagram is
    //       stranded in a huge card of horizontal dead space; and
    //   (b) TOWER: if the figure hugged the caption to the TINY diagram width, the caption wraps into a
    //       many-line vertical strip (e.g. a 40px-wide, 26-line, ~880px-tall card) - unreadable, and it
    //       breaks the uniform row height while every WIDTH-only test still passes ("green but broken").
    // The design threads between them: `figure{width:fit-content}` + `figcaption{max-width:22rem}` grow
    // the card only up to a readable prose width and wrap the caption there, and `margin-inline:auto`
    // on the diagram host CENTRES the narrow diagram within that widened card. So compare a SHORT-caption
    // sibling (which must still hug tight) against the LONG-caption card (bounded, not a tower).
    const NARROW = "stateDiagram-v2\n  [*] --> S1\n  S1 --> S2\n  S2 --> [*]";
    // Includes a LONG UNBREAKABLE token (a service/URL/identifier): with `overflow-wrap:anywhere` it
    // breaks rather than forcing the card wider than the 22rem caption bound. Also a long run of words.
    const LONGCAP = "ProductCatalogDeploymentPipelineOrchestratorServiceEndpoint is a rather long descriptive caption much wider than the narrow diagram";
    const inner = `<figure><pre class="mermaid cm-skip">${NARROW}</pre><figcaption>Short</figcaption></figure>` +
                  `<figure><pre class="mermaid cm-skip">${NARROW}</pre><figcaption>${LONGCAP}</figcaption></figure>`;
    const CARDS = ".cmh-diagram-gallery > figure";
    const server = await stageGallery(page, inner, "cmh-gallery-longcap");
    try {
      await expect(page.locator(CARDS + " svg")).toHaveCount(2, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
      const m = await page.locator(".cmh-diagram-gallery").first().evaluate((gal) => {
        const figs = [...gal.querySelectorAll(":scope > figure")];
        return figs.map((fig) => {
          const svg = fig.querySelector("svg"), cap = fig.querySelector("figcaption");
          const fr = fig.getBoundingClientRect(), sr = svg.getBoundingClientRect();
          const cs = getComputedStyle(fig);
          const contentL = fr.left + parseFloat(cs.paddingLeft), contentR = fr.right - parseFloat(cs.paddingRight);
          return {
            figW: Math.round(fr.width), figH: Math.round(fr.height), svgW: Math.round(sr.width),
            capH: Math.round(cap.getBoundingClientRect().height),
            // svg centre offset vs the card's content-box centre (0 == centred).
            svgCenterOffset: Math.round((sr.left + sr.width / 2) - (contentL + contentR) / 2),
          };
        });
      });
      const [short, long] = m;
      // The SHORT-caption card still HUGS the narrow diagram (no widening/marooning for the common case).
      expect(short.figW, `short-caption figure hugs the narrow diagram (${short.figW}px)`).toBeLessThan(short.svgW + 120);
      // The LONG-caption card grows only to a BOUNDED readable width - not the tiny diagram width
      // (tower) and not the caption's full length (marooning). 22rem cap + ~2*0.85rem padding ~= 27rem.
      expect(long.figW, `long-caption figure widens for readability (${long.figW}px), not a tiny tower`).toBeGreaterThan(short.figW + 80);
      expect(long.figW, `long-caption figure width is bounded to a readable cap (${long.figW}px <= ~27rem)`).toBeLessThanOrEqual(27 * 16 + 8);
      // NO TOWER: the caption wraps to a few readable lines, so the card height stays close to the
      // short-caption sibling's - nowhere near the ~880px many-line tower the old tight-hug produced.
      expect(long.capH, `long caption wraps to a few lines, not a tall tower (capH ${long.capH}px)`).toBeLessThan(160);
      expect(long.figH, `long-caption card height stays bounded (${long.figH}px), no vertical tower`).toBeLessThan(short.figH + 120);
      // The narrow diagram is CENTRED within the widened card, not stranded at the start edge.
      expect(Math.abs(long.svgCenterOffset), `narrow diagram is centred in the widened card (offset ${long.svgCenterOffset}px)`).toBeLessThanOrEqual(6);
    } finally {
      await server.close();
    }
  });

  test("a wide figure's caption stays pinned in view while the diagram scrolls horizontally (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1400, height: 1000 });
    // When a diagram is wider than the card cap, the <figure> itself is the horizontal scroll container.
    // A statically-positioned figcaption scrolls out of view along with the diagram, so a reader who
    // scrolls right to see the end of the diagram loses the caption (its only label/context). The
    // caption is `position: sticky; inset-inline-start: 0`, so it stays pinned within the visible card
    // while the diagram scrolls beneath it. Without sticky, scrolling to the end pushes the caption to a
    // large negative offset (off the start edge) - this test measures the caption at both scroll
    // extremes, and also asserts the sticky caption does not vertically OVERLAP the diagram (a `top`
    // offset regression would keep the horizontal checks green while covering diagram content).
    const WIDE = "flowchart LR\n  A[Ingest] --> B[Parse] --> C[Validate] --> D[Enrich] --> E[Score] --> F[Route] --> G[Notify] --> H[Store] --> I[Audit] --> J[Archive]";
    const inner = `<figure><pre class="mermaid cm-skip">${WIDE}</pre><figcaption>Pipeline stages</figcaption></figure>`;
    const CARDS = ".cmh-diagram-gallery > figure";
    const server = await stageGallery(page, inner, "cmh-gallery-cappin");
    try {
      await expect(page.locator(CARDS + " svg")).toHaveCount(1, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
      const m = await page.locator(CARDS).first().evaluate((fig) => {
        const cap = fig.querySelector("figcaption"), svg = fig.querySelector("svg");
        const inView = () => {
          const fr = fig.getBoundingClientRect(), cr = cap.getBoundingClientRect();
          // The caption's box lies within the figure's visible box (a small tolerance for sub-pixel).
          return cr.left >= fr.left - 2 && cr.right <= fr.right + 2;
        };
        // The caption must sit BELOW the diagram, not overlap it (a stacked column, no vertical cover).
        const noOverlap = () => cap.getBoundingClientRect().top >= svg.getBoundingClientRect().bottom - 2;
        fig.scrollLeft = 0;
        const visAt0 = inView(), sepAt0 = noOverlap();
        fig.scrollLeft = fig.scrollWidth; // scroll fully right to the diagram's end
        const visAtMax = inView(), sepAtMax = noOverlap();
        return { scrollsX: fig.scrollWidth > fig.clientWidth + 1, visAt0, visAtMax, sepAt0, sepAtMax, sticky: getComputedStyle(cap).position === "sticky" };
      });
      // Precondition: the diagram is genuinely wider than the card (otherwise the test is vacuous).
      expect(m.scrollsX, "the wide figure actually scrolls horizontally (test precondition)").toBe(true);
      expect(m.sticky, "the figcaption is sticky-positioned").toBe(true);
      expect(m.visAt0, "caption is visible before scrolling").toBe(true);
      // The real assertion: the caption is STILL visible after scrolling to the diagram's far end.
      expect(m.visAtMax, "caption stays pinned in view after scrolling to the end of a wide diagram").toBe(true);
      // And it never covers the diagram (guards a `top`-offset sticky regression).
      expect(m.sepAt0, "caption sits below the diagram (no overlap) before scrolling").toBe(true);
      expect(m.sepAtMax, "caption sits below the diagram (no overlap) after scrolling").toBe(true);
    } finally {
      await server.close();
    }
  });

  test("a short caption under a wide figure is centred, not pinned to the card's start edge (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1400, height: 1000 });
    // A wide diagram (wider than the 22rem caption cap but NOT wide enough to scroll) with a SHORT
    // caption: the caption is bounded to 22rem, so `align-self:stretch` would clamp it and fall back to
    // start-alignment, leaving the short caption pinned to the card's LEFT edge instead of centred under
    // the diagram (an off-centre regression). `margin-inline:auto` centres the bounded caption box, so
    // it sits under the diagram's centre. This staged flowchart is wide but fits the card without
    // scrolling, so the caption box is genuinely narrower than the card and the centring is meaningful.
    const inner = `<figure><pre class="mermaid cm-skip">${FLOW}</pre><figcaption>Flow</figcaption></figure>`;
    const CARDS = ".cmh-diagram-gallery > figure";
    const server = await stageGallery(page, inner, "cmh-gallery-widecap");
    try {
      await expect(page.locator(CARDS + " svg")).toHaveCount(1, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
      const m = await page.locator(CARDS).first().evaluate((fig) => {
        const cap = fig.querySelector("figcaption");
        const fr = fig.getBoundingClientRect(), cr = cap.getBoundingClientRect();
        const cs = getComputedStyle(fig);
        const contentL = fr.left + parseFloat(cs.paddingLeft), contentR = fr.right - parseFloat(cs.paddingRight);
        return {
          scrollsX: fig.scrollWidth > fig.clientWidth + 1,
          capW: Math.round(cr.width), cardContentW: Math.round(contentR - contentL),
          capCenterOffset: Math.round((cr.left + cr.width / 2) - (contentL + contentR) / 2),
        };
      });
      // Precondition: the card does not scroll and the caption box is genuinely narrower than the card
      // (otherwise the centring assertion is vacuous - a full-width caption is trivially centred).
      expect(m.scrollsX, "the wide figure fits without scrolling (test precondition)").toBe(false);
      expect(m.capW, `the short caption box (${m.capW}px) is narrower than the card (${m.cardContentW}px)`).toBeLessThan(m.cardContentW - 40);
      // The bounded short caption is CENTRED under the diagram, not pinned to the start edge.
      expect(Math.abs(m.capCenterOffset), `short caption is centred in the wide card (offset ${m.capCenterOffset}px)`).toBeLessThanOrEqual(6);
    } finally {
      await server.close();
    }
  });

  test("the figure caption pins with a LOGICAL inline-start edge (RTL-safe), not physical left (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1400, height: 1000 });
    // The sticky caption pins with `inset-inline-start:0`, NOT physical `left:0`, so it pins the correct
    // edge in a right-to-left document (where the horizontal scroll origin flips to the right). The
    // product is otherwise LTR-only, so this is a coverage guard against a silent revert to `left:0`:
    // under `dir=rtl` the used `left` must be `auto` (the logical inset maps to `right`), and the
    // caption must still stay in view when the wide diagram is scrolled to its far end.
    const WIDE = "flowchart LR\n  A[Ingest] --> B[Parse] --> C[Validate] --> D[Enrich] --> E[Score] --> F[Route] --> G[Notify] --> H[Store] --> I[Audit] --> J[Archive]";
    const inner = `<figure><pre class="mermaid cm-skip">${WIDE}</pre><figcaption>Pipeline stages</figcaption></figure>`;
    const CARDS = ".cmh-diagram-gallery > figure";
    const server = await stageGallery(page, inner, "cmh-gallery-rtl");
    try {
      await expect(page.locator(CARDS + " svg")).toHaveCount(1, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
      // Flip the document to RTL and re-settle.
      await page.evaluate(() => { document.documentElement.setAttribute("dir", "rtl"); });
      await page.waitForTimeout(150);
      const m = await page.locator(CARDS).first().evaluate((fig) => {
        const cap = fig.querySelector("figcaption");
        const cs = getComputedStyle(cap);
        const inView = () => {
          const fr = fig.getBoundingClientRect(), cr = cap.getBoundingClientRect();
          return cr.left >= fr.left - 2 && cr.right <= fr.right + 2;
        };
        fig.scrollLeft = 0; const v0 = inView();
        // RTL scroll extreme: scroll to the far (start) end in both directions to be engine-agnostic.
        fig.scrollLeft = fig.scrollWidth; const vPos = inView();
        fig.scrollLeft = -fig.scrollWidth; const vNeg = inView();
        return { scrollsX: fig.scrollWidth > fig.clientWidth + 1, usedLeft: cs.left, usedInsetInlineStart: cs.insetInlineStart, position: cs.position, v0, vPos, vNeg };
      });
      expect(m.scrollsX, "the wide RTL figure actually scrolls (test precondition)").toBe(true);
      expect(m.position, "the caption is sticky-positioned").toBe("sticky");
      // The deterministic guard: a physical `left:0` would compute `left === "0px"`. The logical
      // `inset-inline-start:0` in RTL leaves `left` as `auto` (it maps to the right edge instead).
      expect(m.usedLeft, "the caption pins via a LOGICAL edge (physical left is auto in RTL)").toBe("auto");
      expect(m.usedInsetInlineStart, "inset-inline-start resolves to 0").toBe("0px");
      // Behavioural check: the caption stays in view at both scroll extremes in RTL.
      expect(m.v0 && (m.vPos || m.vNeg), "the RTL caption stays in view when the diagram is scrolled").toBe(true);
    } finally {
      await server.close();
    }
  });

  test("a figure card is framed and its diagram is sized whole (CMH-CONTENT-19)", async ({ page }) => {
      test.setTimeout(60000);
      await page.setViewportSize({ width: 1400, height: 1000 });
    // A captioned <figure> card wrapping a tall diagram: the figure is the card (the inner pre is not a
    // direct gallery child, so it is not itself framed). The diagram is sized to a hugging full-height
    // card and the caption stays below it.
    const inner = `<figure><pre class="mermaid cm-skip">${STATE}</pre><figcaption>State machine</figcaption></figure>`;
    const CARDS = ".cmh-diagram-gallery > figure";
    const server = await stageGallery(page, inner, "cmh-gallery-figure");
    try {
      await expect(page.locator(CARDS + " svg")).toHaveCount(1, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
      const [c] = await measureCards(page, CARDS);
      expect(c.border, "figure card is framed").toBeGreaterThanOrEqual(1);
      // The diagram is rendered at the full fixed height (not collapsed), whole inside the card, and
      // unclipped. (A figure's card WIDTH can be set by a caption wider than a narrow diagram, so we do
      // not assert the svg fills the card width here - only that the diagram itself is full-size.)
      expect(c.svgBoxH, "the diagram is rendered at the full fixed height (not collapsed)").toBeGreaterThanOrEqual(200);
      expect(c.within, "the diagram is whole inside the figure card").toBe(true);
      expect(c.clip, "the diagram has no clipped content in the figure card").toBe(0);
      // The caption is not just present in the DOM but actually VISIBLE and laid out (a display:none or
      // collapsed caption is a broken figure a node-count check would miss).
      const cap = page.locator(CARDS + " figcaption");
      expect(await cap.count(), "figcaption is preserved").toBe(1);
      await expect(cap, "figcaption is visible").toBeVisible();
      const capBox = await cap.evaluate((el) => { const r = el.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) }; });
      expect(capBox.h, "figcaption has a real rendered height").toBeGreaterThan(0);
      expect(capBox.w, "figcaption has a real rendered width").toBeGreaterThan(0);
    } finally {
      await server.close();
    }
  });

  test("an extreme-wide diagram in a FIGURE card scrolls at full width with the caption preserved (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1200, height: 1000 });
    // A wide diagram wrapped in a captioned <figure>: the figure (not the inner pre) is the scroll
    // container, so the diagram must render at its FULL natural width (a row-flex inner host would
    // flex-shrink it into a letterboxed strip), be reachable by scrolling from the left, and keep its
    // caption visible.
    const WIDE = "flowchart LR\n  A[Ingest] --> B[Parse] --> C[Validate] --> D[Enrich] --> E[Score] --> F[Route] --> G[Notify] --> H[Store] --> I[Audit] --> J[Archive]";
    const inner = `<figure><pre class="mermaid cm-skip">${WIDE}</pre><figcaption>Wide pipeline</figcaption></figure>`;
    const CARDS = ".cmh-diagram-gallery > figure";
    const server = await stageGallery(page, inner, "cmh-gallery-figwide");
    try {
      await expect(page.locator(CARDS + " svg")).toHaveCount(1, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
      const info = await page.locator(CARDS).first().evaluate((fig) => {
        const svg = fig.querySelector("svg");
        fig.scrollLeft = -1e9;
        const fr = fig.getBoundingClientRect(), sr = svg.getBoundingClientRect();
        const cap = fig.querySelector("figcaption");
        return {
          leftGap: Math.round(sr.left - fr.left),
          svgW: Math.round(sr.width), figW: Math.round(fr.width),
          coversWidth: fig.scrollWidth >= Math.round(sr.width) - 4,
          capVisible: cap.getBoundingClientRect().height > 0 && getComputedStyle(cap).display !== "none",
          svgH: Math.round(sr.height),
        };
      });
      // Rendered at full natural width (not shrunk to fit the figure), at the fixed height.
      expect(info.svgW, "the wide figure diagram renders at its full natural width (not flex-shrunk)").toBeGreaterThan(info.figW);
      expect(info.svgH, "the wide figure diagram keeps the fixed height").toBeGreaterThanOrEqual(200);
      // The whole diagram is reachable by scrolling (left edge in view, scroll range spans the width).
      expect(info.leftGap, "the wide figure diagram's left edge is reachable (not clipped off-screen)").toBeGreaterThanOrEqual(-4);
      expect(info.coversWidth, "the figure scroll range covers the whole diagram width").toBe(true);
      expect(info.capVisible, "the figcaption stays visible").toBe(true);
    } finally {
      await server.close();
    }
  });

  test("a nested caption icon in a figure card is not distorted by the diagram-sizing rule (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1400, height: 1000 });
    // A figure card whose <figcaption> contains its own small inline <svg> icon. The diagram-sizing rule
    // targets only the mermaid host's ROOT svg (child combinator), so the caption icon must keep its
    // intrinsic 16x16 size - a broad descendant selector would stretch it to the card and distort it.
    const inner = `<figure><pre class="mermaid cm-skip">${FLOW}</pre>` +
      `<figcaption>Flow <svg class="cap-icon" width="16" height="16" viewBox="0 0 16 16"><rect width="16" height="16"></rect></svg></figcaption></figure>`;
    const CARDS = ".cmh-diagram-gallery > figure";
    const server = await stageGallery(page, inner, "cmh-gallery-capicon");
    try {
      await expect(page.locator(CARDS + " > pre.mermaid svg")).toHaveCount(1, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
      const icon = await page.locator(CARDS + " figcaption svg.cap-icon").evaluate((el) => {
        const r = el.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) };
      });
      expect(icon.w, "caption icon width is not stretched to the card").toBeLessThanOrEqual(28);
      expect(icon.h, "caption icon height is not stretched to the card").toBeLessThanOrEqual(28);
      // ...and the mermaid diagram still fills the figure card.
      const [c] = await measureCards(page, CARDS);
      expect(c.svgBoxW, "the mermaid diagram still fills the figure card width").toBeGreaterThanOrEqual((c.cardW - 28) * 0.85);
    } finally {
      await server.close();
    }
  });

  test("the desktop gallery disables the layer scale-up but mobile keeps it (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    // A genuinely wide diagram: the layer would classify it `cmh-diagram-wide`. On the framed desktop
    // gallery the early-return strips that class (contain-fit governs); below the 481px breakpoint the
    // early-return is skipped, so the layer re-applies its wide handling (a wide mobile diagram must
    // keep its horizontal scroll). This is the regression guard for the round-1 mobile-gate fix - the
    // original unconditional early-return would leave the class stripped on mobile and fail here.
    const WIDE = "flowchart LR\n  A-->B-->C-->D-->E-->F-->G-->H-->I-->J";
    const inner = `<pre class="mermaid cm-skip">${WIDE}</pre>`;
    await page.setViewportSize({ width: 1400, height: 900 });
    const server = await stageGallery(page, inner, "cmh-gallery-mobilegate");
    try {
      const host = page.locator(".cmh-diagram-gallery > pre.mermaid").first();
      await expect(host.locator("svg")).toBeVisible({ timeout: 20000 });
      const hasWide = () => host.evaluate((el) => el.classList.contains("cmh-diagram-wide"));
      // Desktop framed gallery: the layer's wide class is cleared by the early-return.
      await expect.poll(hasWide, { timeout: 5000 }).toBe(false);
      // Mobile: the early-return no longer fires, so the layer re-applies wide handling.
      await page.setViewportSize({ width: 400, height: 800 });
      await page.evaluate(() => window.dispatchEvent(new Event("resize")));
      await expect.poll(hasWide, { timeout: 5000 }).toBe(true);
      // Back to desktop: the early-return strips it again.
      await page.setViewportSize({ width: 1400, height: 900 });
      await page.evaluate(() => window.dispatchEvent(new Event("resize")));
      await expect.poll(hasWide, { timeout: 5000 }).toBe(false);
    } finally {
      await server.close();
    }
  });

  test("on a phone the gallery is a frameless single-column flow (CMH-CONTENT-19)", async ({ page }) => {
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
          cardDisplays: cards.map((c) => getComputedStyle(c).display),
        };
      });
      // Below the 481px breakpoint the flex + card rules do not apply: the gallery is a plain
      // single-column flow so the layer's own responsive diagram handling (CMH-RESP-01) is intact.
      expect(info.galleryDisplay, "gallery is a plain block flow on mobile").toBe("block");
      for (const d of info.cardDisplays) {
        expect(d, "a mobile card is not a bounded flex card").not.toBe("flex");
      }
    } finally {
      await server.close();
    }
  });

  test("print stacks the gallery single-column and unframes each card (CMH-CONTENT-19)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1400, height: 1000 });
    const inner = `<pre class="mermaid cm-skip">${FLOW}</pre><pre class="mermaid cm-skip">${STATE}</pre>`;
    const CARDS = ".cmh-diagram-gallery > pre.mermaid";
    const server = await stageGallery(page, inner, "cmh-gallery-print");
    try {
      await expect(page.locator(CARDS + " svg")).toHaveCount(2, { timeout: 20000 });
      await waitGalleryReady(page, CARDS);
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
      // In print the gallery stacks to a single column and each card is a plain unframed block with the
      // screen bound/frame dropped, so the WHOLE diagram prints at its natural size.
      expect(info.galleryDisplay, "gallery stacks to a single column in print").toBe("block");
      for (const c of info.cards) {
        expect(c.display, "a card is a plain block in print (flex context stripped)").toBe("block");
        expect(c.overflow, "a card's overflow is visible in print (whole diagram prints)").toMatch(/visible/);
        expect(c.border, "a card is unframed in print").toBe(0);
      }
    } finally {
      await server.close();
    }
  });

  test("a gallery diagram is commentable and the whole-diagram button stays inside its card (CMH-CONTENT-19 / CMH-MMD-06)", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1200, height: 900 });
    // The gantt title text is an empty (non-node) area, so hovering it reliably offers the WHOLE-diagram
    // "Comment on diagram" button. The card clips (overflow hidden), so the clip-aware positioner keeps
    // the button inside the card rather than floating to a viewport edge.
    const inner = `<pre class="mermaid">${GANTT}</pre>`;
    const CARD = ".cmh-diagram-gallery > pre.mermaid";
    const server = await stageGallery(page, inner, "cmh-gallery-comment");
    try {
      const host = page.locator(CARD).first();
      await expect(host.locator("svg .titleText").first()).toBeVisible({ timeout: 20000 });
      await host.locator("svg .titleText").first().hover();
      const btn = page.locator("#mermaidAddBtn");
      await expect(btn).toBeVisible();
      await expect(btn).toHaveText(/diagram/i);
      const within = await page.evaluate((sel) => {
        const b = document.getElementById("mermaidAddBtn").getBoundingClientRect();
        const c = document.querySelector(sel).getBoundingClientRect();
        return b.top >= c.top - 2 && b.bottom <= c.bottom + 2 && b.left >= c.left - 2 && b.right <= c.right + 2;
      }, CARD);
      expect(within, "the whole-diagram button is clamped inside the gallery card").toBe(true);
      // Saving anchors a whole-diagram comment on the host.
      await btn.click();
      const composer = page.locator(".cm-composer").last();
      await composer.locator("textarea").fill("gallery diagram note");
      await composer.locator('[data-act="save"]').click();
      await expect(composer).toHaveCount(0);
      await expect(host).toHaveClass(/cm-mermaid-hl/);
    } finally {
      await server.close();
    }
  });
});
