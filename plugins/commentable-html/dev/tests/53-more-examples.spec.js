import { test, expect } from "@playwright/test";
import {
  SKILL, PLUGIN, ready, installClipboardCapture, storedComments, distinctCids,
  startStaticServer, routeMermaidLocal,
} from "./helpers.js";

// The two remaining showcase examples (the incident triage board and the visuals matrix)
// must be exercised end to end by commenting + clicking + a short randomized monkey pass,
// matching the coverage the community-garden (25/30) and taxi (35) reports already carry.
// Everything is served over http so the metrics report's mermaid diagrams render;
// routeMermaidLocal also blocks every non-local host, so each run is hermetic.
const REPORTS = [
  {
    name: "incident triage board",
    file: "report-triage.html",
    partSel: '[data-cm-part-label="API saturation"]',
    minDistinct: 4,
  },
  {
    name: "commentable visuals matrix",
    file: "report-metrics.html",
    partSel: '[data-cm-part-label="Ingest node"]',
    minDistinct: 4,
  },
];

// Seeded PRNG so any failure replays deterministically (same generator as 30-monkey).
const prngInit = (seed) => `
  let s = ${seed} >>> 0;
  window.__rng = () => {
    s |= 0; s = (s + 0x6D2B79F5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };`;

// Any uncaught exception or genuine console error is a failure; network/asset noise is not.
function watchErrors(page) {
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + (e && e.stack ? e.stack : e)));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    if (/favicon|Failed to load resource|net::ERR|ERR_|ResizeObserver loop limit|access to font|CORS/i.test(t)) return;
    errors.push("console.error: " + t);
  });
  return errors;
}

const ACTIONS = [
  "sort", "codecopy", "kqlcopy", "diffsyntax", "caret", "expandall", "collapseall",
  "scrolltop", "scrollbottom", "sidebar", "menu", "copyall", "help", "closemodal",
  "scroll", "mermaidhover", "charthover", "themetoggle",
];

// Fire a real handler on a random visible target; a missing target is a no-op. Returns any
// SYNCHRONOUS throw (async throws surface via the pageerror listener) plus whether it hit.
async function doAction(page, name) {
  return page.evaluate((action) => {
    const rng = window.__rng || Math.random;
    const vis = (sel) => [...document.querySelectorAll(sel)].filter((e) => e.getClientRects().length);
    const pick = (list) => (list.length ? list[Math.floor(rng() * list.length)] : null);
    const byText = (sel, txt) => vis(sel).filter((e) => (e.textContent || "").trim() === txt);
    let hit = false;
    const clk = (e) => { if (e) { e.click(); hit = true; } };
    const hover = (e) => { if (e) { const r = e.getBoundingClientRect(); e.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 })); hit = true; } };
    try {
      switch (action) {
        case "sort": clk(pick(vis("table.cmh-sortable th"))); break;
        case "codecopy": clk(pick(vis(".cm-code-copy"))); break;
        case "kqlcopy": clk(pick(vis(".cmh-kql-title"))); break;
        case "diffsyntax": clk(pick(vis(".cmh-diff-toggle"))); break;
        case "caret": clk(pick(vis(".cmh-sec-caret"))); break;
        case "expandall": clk(pick(byText(".cm-side-toc-top", "Expand All"))); break;
        case "collapseall": clk(pick(byText(".cm-side-toc-top", "Collapse All"))); break;
        case "scrolltop": clk(pick(byText(".cm-side-toc-top", "Scroll to Top"))); break;
        case "scrollbottom": clk(pick(vis(".cm-side-toc-bottom"))); break;
        case "sidebar": clk(document.getElementById("btnToggleSidebar")); break;
        case "menu": { const e = document.getElementById("btnToolbarMenu"); if (e && e.getClientRects().length) clk(e); break; }
        case "copyall": { const e = document.getElementById("btnCopyAll") || document.getElementById("btnCopyAllTop"); if (e && e.getClientRects().length) clk(e); break; }
        case "help": { const e = document.getElementById("btnHelpTop") || document.getElementById("btnHelp"); if (e && e.getClientRects().length) clk(e); break; }
        case "closemodal": clk(document.querySelector(".cm-modal .cm-x, .cm-modal [data-act='close'], .cm-help .cm-x")); break;
        case "scroll": window.scrollTo(0, Math.floor(rng() * Math.max(1, document.body.scrollHeight))); hit = true; break;
        case "themetoggle": { const e = document.getElementById("btnTheme") || document.getElementById("btnThemeTop"); if (e && e.getClientRects().length) clk(e); break; }
        case "mermaidhover": hover(pick(vis(".cm-mermaid-host .node, .cm-mermaid-host .actor, .cm-mermaid-host g.task, .cm-mermaid-host rect"))); break;
        case "charthover": hover(pick(vis("canvas"))); break;
      }
      return { err: null, hit };
    } catch (err) {
      return { err: "sync throw in '" + action + "': " + (err && err.stack ? err.stack : err), hit };
    }
  }, name);
}

async function waitForAnimationFrame(page) {
  await page.evaluate(() => new Promise((resolve) => {
    if (typeof requestAnimationFrame !== "function") { resolve(); return; }
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  }));
}

// Best-effort comment on a random not-yet-highlighted paragraph, interleaved with the
// chrome fuzz. It NEVER asserts success; it only proves the flow throws nothing.
async function tryAddComment(page, note) {
  const popped = await page.evaluate(() => {
    const root = document.getElementById("commentRoot");
    const ps = [...root.querySelectorAll("p, li")].filter((p) => {
      if (p.closest(".cm-skip") || p.closest("mark.cm-hl")) return false;
      return (p.textContent || "").trim().length >= 8 && p.getClientRects().length;
    });
    if (!ps.length) return false;
    const p = ps[Math.floor((window.__rng || Math.random)() * ps.length)];
    const tn = [...p.childNodes].find((n) => n.nodeType === 3 && n.data.trim().length >= 6);
    if (!tn) return false;
    const r = document.createRange();
    r.setStart(tn, 1); r.setEnd(tn, Math.min(tn.data.length, 5));
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
    p.scrollIntoView({ block: "center" });
    p.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    return true;
  });
  if (!popped) return;
  const menu = page.locator("#menuComment");
  await menu.waitFor({ state: "visible", timeout: 1000 }).catch(() => {});
  if (!(await menu.isVisible().catch(() => false))) return;
  await menu.click().catch(() => {});
  const composer = page.locator(".cm-composer").last();
  if (!(await composer.count())) return;
  await composer.locator("textarea").fill(note).catch(() => {});
  await composer.locator('[data-act="save"]').click().catch(() => {});
}

async function closeAnyComposer(page) {
  await page.evaluate(() => {
    document.querySelectorAll(".cm-composer [data-act='cancel']").forEach((b) => b.click());
    document.querySelectorAll(".cm-modal .cm-x, .cm-help .cm-x").forEach((b) => b.click());
  });
}

// Deterministic prose comment that ASSERTS success: it selects the first commentable
// paragraph and drives the menu -> composer -> save flow.
async function addProseComment(page, note) {
  const ok = await page.evaluate(() => {
    const root = document.getElementById("commentRoot");
    const ps = [...root.querySelectorAll("p, li")].filter((p) => {
      if (p.closest(".cm-skip") || p.closest(".cm-toc") || p.closest("mark.cm-hl")) return false;
      return (p.textContent || "").trim().length >= 12 && p.getClientRects().length;
    });
    for (const p of ps) {
      const tn = [...p.childNodes].find((n) => n.nodeType === 3 && n.data.trim().length >= 8);
      if (!tn) continue;
      const r = document.createRange();
      r.setStart(tn, 1); r.setEnd(tn, Math.min(tn.data.length, 8));
      const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
      p.scrollIntoView({ block: "center" });
      p.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
      return true;
    }
    return false;
  });
  expect(ok, "found a commentable prose paragraph").toBe(true);
  const menu = page.locator("#menuComment");
  await expect(menu).toBeVisible();
  await menu.click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toHaveCount(0);
}

// Comment on a widget part. The primary interaction is hover -> #widgetAddBtn (kanban
// cards); SVG nodes fall back to the keyboard path (focus + Enter). Both open the composer.
async function commentOnPart(page, partSel, note) {
  const part = page.locator(partSel).first();
  await part.scrollIntoViewIfNeeded();
  await part.hover();
  const addBtn = page.locator("#widgetAddBtn");
  if (await addBtn.isVisible().catch(() => false)) {
    await addBtn.click();
  } else {
    await part.focus();
    await page.keyboard.press("Enter");
  }
  const composer = page.locator(".cm-composer").last();
  await expect(composer).toBeVisible();
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toHaveCount(0);
}

for (const rpt of REPORTS) {
  test.describe(`showcase example: ${rpt.name}`, () => {
    test("boots over http with its attribution footer", async ({ page }) => {
      test.setTimeout(60000);
      const server = await startStaticServer(PLUGIN);
      const errors = watchErrors(page);
      try {
        await routeMermaidLocal(page);
        await installClipboardCapture(page);
        await page.goto(`${server.url}/examples/${rpt.file}`);
        await ready(page);
        await expect(page.locator("#commentRoot")).toHaveCount(1);
        await expect(page.locator("#cmFooter")).toBeVisible();
        await expect(page.locator("#cmFooter")).toContainText(/Commentable HTML v\d+\.\d+\.\d+/);
        expect(errors, "no uncaught errors on load").toEqual([]);
      } finally {
        await server.close();
      }
    });

    test("commenting on prose and a widget part works and survives reload", async ({ page }) => {
      test.setTimeout(60000);
      const server = await startStaticServer(PLUGIN);
      const errors = watchErrors(page);
      try {
        await routeMermaidLocal(page);
        await installClipboardCapture(page);
        await page.goto(`${server.url}/examples/${rpt.file}`);
        await ready(page);

        // A prose comment appears in the sidebar as a card.
        await addProseComment(page, "Please double-check this section.");
        await expect(page.locator(".cm-card")).toHaveCount(1);
        expect(await distinctCids(page)).toBe(1);

        // A widget part (kanban card / SVG node) is commentable via the same layer.
        await commentOnPart(page, rpt.partSel, "Reassess this part.");
        const afterWidget = await storedComments(page);
        expect(afterWidget.length).toBe(2);
        const widgetComment = afterWidget.find((c) => c.anchorType === "widget");
        expect(widgetComment, "a widget-anchored comment was saved").toBeTruthy();
        await expect(page.locator(".cm-card")).toHaveCount(2);

        // Both comments survive a reload.
        await page.reload();
        await ready(page);
        expect(await storedComments(page)).toHaveLength(2);
        await expect(page.locator("#commentRoot mark.cm-hl")).toHaveCount(1);
        await expect(page.locator(`${rpt.partSel}.cm-part-hl`)).toHaveCount(1);
        expect(errors, "no uncaught errors during commenting").toEqual([]);
      } finally {
        await server.close();
      }
    });

    test("clicking UI controls and a randomized monkey pass never crash", async ({ page }) => {
      test.setTimeout(90000);
      const server = await startStaticServer(PLUGIN);
      const errors = watchErrors(page);
      try {
        await routeMermaidLocal(page);
        await installClipboardCapture(page);
        await page.addInitScript(prngInit(0xd0c5));
        await page.goto(`${server.url}/examples/${rpt.file}`);
        await ready(page);
        page.on("dialog", (d) => d.accept().catch(() => {}));

        // A canvas chart is indexed as commentable media on both reports.
        await expect(page.locator("canvas").first()).toHaveClass(/cm-img-commentable/, { timeout: 20000 });

        // Explicit UI-control interaction: toggle the comments sidebar twice via its
        // toolbar button (driven through the DOM so viewport chrome layout cannot flake).
        await page.evaluate(() => document.getElementById("btnToggleSidebar")?.click());
        await page.evaluate(() => document.getElementById("btnToggleSidebar")?.click());

        const exercised = new Set();
        const steps = 24;
        for (let i = 0; i < steps; i++) {
          const action = ACTIONS[Math.floor((await page.evaluate(() => (window.__rng || Math.random)())) * ACTIONS.length)];
          const { err, hit } = await doAction(page, action);
          expect(err, `step ${i} (${action}) threw synchronously`).toBeNull();
          if (hit) exercised.add(action);
          if (i % 5 === 4) await tryAddComment(page, "monkey " + i);
          await waitForAnimationFrame(page);
          expect(errors, `hard error after step ${i} (${action})`).toEqual([]);
          const alive = await page.evaluate(() => window.__commentableHtmlReady === true);
          expect(alive, `layer still alive after step ${i} (${action})`).toBe(true);
        }
        expect(exercised.size, `distinct controls exercised (${[...exercised].join(",")})`).toBeGreaterThanOrEqual(rpt.minDistinct);

        await closeAnyComposer(page);
        const before = await distinctCids(page);
        await page.reload();
        await ready(page);
        expect(errors, "no uncaught errors after reload").toEqual([]);
        expect(await distinctCids(page), "comments survive the reload").toBe(before);
      } finally {
        await server.close();
      }
    });
  });
}
// CMH-DEMO-06 / CMH-CONTENT-19: the visuals-matrix Mermaid gallery uses the shipped
// `.cmh-diagram-gallery` layout helper (layer CSS), which is robust BY CONSTRUCTION against the
// failure modes this gallery hit repeatedly: marooning (a plain grid row is as tall as its tallest
// cell, stranding short diagrams beside a tall one), slivers (a tall-narrow diagram left as a thin
// ribbon in a wide card - whether by shrinking the SVG width or by contain-fitting it into a wide
// uniform card), and the multi-column/mermaid fragility (tiny/empty diagrams in a real browser). The
// helper lays the cards out as a centred FLEX-WRAP of UNIFORM-HEIGHT, content-HUGGING cards: every
// diagram is one fixed height with its width derived from the viewBox aspect ratio, and each card
// shrinks to hug that width - so a tall-narrow diagram gets a narrow full-height card (no sliver, no
// marooning) and a wide diagram a wide card, all deterministic pure CSS (pixel-identical across
// engines). On a single-column mobile viewport the layer's natural diagram flow is left intact
// (CMH-RESP-01 in 51-charts-mobile.spec.js).
test.describe("commentable visuals matrix: diagram gallery layout (CMH-DEMO-06 / CMH-CONTENT-19)", () => {
  const GALLERY = "#commentRoot section[aria-labelledby=\"mermaid-gallery\"] .cmh-diagram-gallery";
  const measureGallery = (page) => page.evaluate((gallerySel) => {
    const hosts = [...document.querySelectorAll(gallerySel + " > pre.mermaid")];
    return hosts.map((el) => {
      const svg = el.querySelector("svg");
      const cr = el.getBoundingClientRect();
      const innerW = cr.width - 28, innerH = cr.height - 28;
      const cs = getComputedStyle(el);
      let fillW = 0, fillH = 0, within = true, clip = 0, minTextH = Infinity, nText = 0, textInvisible = 0, hasPositiveViewBox = false;
      let svgBoxW = 0, svgBoxH = 0;
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
          if (nr.left < sr.left - 1 || nr.right > sr.right + 1 || nr.top < sr.top - 1 || nr.bottom > sr.bottom + 1) clip++;
        });
        if (r > l) fillW = (r - l) / innerW;
        if (b > t) fillH = (b - t) / innerH;
        svg.querySelectorAll("text").forEach((n) => { const nr = n.getBoundingClientRect(); if (nr.height > 0) { minTextH = Math.min(minTextH, nr.height); nText++; } });
        svg.querySelectorAll("text").forEach((n) => {
          const ts = getComputedStyle(n), f = ts.fill, fo = parseFloat(ts.fillOpacity), o = parseFloat(ts.opacity);
          if (f === "rgba(0, 0, 0, 0)" || f === "transparent" || fo === 0 || o === 0 || ts.visibility === "hidden") textInvisible++;
        });
        // Non-deck mermaid (flowchart, state, class, er, ...) renders node labels as HTML in
        // <foreignObject>, not as svg <text>, so the <text> checks above miss them. Several live demo
        // diagrams use HTML labels, so a broken HTML label would look empty in a real browser while every
        // svg-geometry/text check stays green. Measure the HTML label content too: its rendered height (a
        // legibility floor) and its paint visibility (transparent color / zero opacity / hidden).
        svg.querySelectorAll("foreignObject").forEach((foEl) => {
          // Prefer the nested SEMANTIC label element explicitly: a comma selector returns the first DOM
          // match, which is mermaid's OUTER wrapper div (full box height), not the nested .nodeLabel -
          // measuring the wrapper would overstate a crushed inner label and let it pass.
          const label = foEl.querySelector(".nodeLabel") || foEl.querySelector(".edgeLabel") ||
            foEl.querySelector("span") || foEl.querySelector("p") || foEl.querySelector("div") || foEl;
          // Count every label that carries TEXT (skip structural/empty foreignObjects) REGARDLESS of
          // size, so a label that COLLAPSED to zero height - the exact regression this guards - is
          // counted and fails the floor/visibility checks below, instead of being skipped (which would
          // drop nHtmlLabel to 0 and let the assertions be vacuously skipped).
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
        left: Math.round(cr.left), hostH: Math.round(cr.height), cardW: Math.round(cr.width),
        borderPx: Math.round(parseFloat(cs.borderTopWidth) || 0),
        nodeCount: svg ? svg.querySelectorAll("*").length : 0,
        svgBoxW, svgBoxH, fillArea: fillW * fillH, clip,
        minTextH: isFinite(minTextH) ? minTextH : null, nText, textInvisible, hasPositiveViewBox,
        htmlLabelMinH: isFinite(htmlLabelMinH) ? htmlLabelMinH : null, nHtmlLabel, htmlLabelInvisible,
        within, scrolls: el.scrollHeight > el.clientHeight + 1,
      };
    });
  }, GALLERY);

  test("gallery renders every diagram whole and well-filled in hugging uniform-height cards - no tiny, no sliver, no clip, no marooning", async ({ page }) => {
    test.setTimeout(60000);
    // A wide viewport makes the gallery multi-row; the mix of aspect ratios (a tall state diagram
    // beside short-wide flowchart/gantt/pie) is exactly what used to maroon, sliver, clip, or render
    // tiny. The helper must render each diagram whole and well-filled in its hugging card.
    await page.setViewportSize({ width: 1600, height: 1000 });
    const server = await startStaticServer(PLUGIN);
    const errors = watchErrors(page);
    try {
      await routeMermaidLocal(page);
      await page.goto(`${server.url}/examples/report-metrics.html`);
      await ready(page);
      // The demo actually uses the shipped helper class (not a hand-rolled per-example layout).
      await expect(page.locator(GALLERY)).toHaveCount(1);
      // Every gallery diagram renders its SVG (served over http so mermaid runs).
      await expect(page.locator(`${GALLERY} > pre.mermaid svg`)).toHaveCount(7, { timeout: 20000 });
      // Gate on the SETTLED layout AND settled mermaid CONTENT: the card frame + svg sizing are applied
      // by CSS in a rAF, and mermaid populates some diagrams (a pie) in TWO phases (an empty
      // `<svg><g></g></svg>` first, then the slices a few hundred ms later). So wait for every card
      // framed AND with real content AND the svg box dimensions UNCHANGED across two consecutive polls,
      // so a measurement can never land on a mid-render transient; a regression that drops the frame or
      // never settles times out and the test still fails.
      let prevSig = null;
      await expect.poll(async () => {
        const sig = await page.evaluate((s) => {
          const cards = [...document.querySelectorAll(s + " > pre.mermaid")];
          if (cards.length !== 7) return null;
          const ok = cards.every((c) => {
            const svg = c.querySelector("svg");
            return (parseFloat(getComputedStyle(c).borderTopWidth) || 0) >= 1 && svg && svg.querySelectorAll("*").length >= 5;
          });
          if (!ok) return null;
          return cards.map((c) => { const r = c.querySelector("svg").getBoundingClientRect(); return Math.round(r.width) + "x" + Math.round(r.height); }).join(",");
        }, GALLERY);
        const stable = sig !== null && sig === prevSig;
        prevSig = sig;
        return stable;
      }, { timeout: 15000, intervals: [250] }).toBe(true);

      // The gallery is a FLEX-WRAP (not a fragile multi-column block, and not the old marooning
      // grid-that-strands, and not a single-column fallback): a block fallback or a multicol would
      // each break a promise.
      const displays = await page.evaluate((gallerySel) => {
        const g = document.querySelector(gallerySel);
        const chartEl = document.querySelector('#commentRoot section[aria-labelledby="chart-gallery"] .visual-grid');
        return {
          gallery: getComputedStyle(g).display,
          galleryWrap: getComputedStyle(g).flexWrap,
          chart: chartEl ? getComputedStyle(chartEl).display : null,
        };
      }, GALLERY);
      expect(displays.gallery, "diagram gallery is a flex container").toBe("flex");
      expect(displays.galleryWrap, "diagram gallery wraps its cards").toBe("wrap");
      expect(displays.chart, "chart gallery is untouched (still a grid)").toBe("grid");

      const cells = await measureGallery(page);
      expect(cells.length).toBe(7);

      // UNIFORM card heights => tidy rows, no marooning and no tall tower; pinned to the ~15rem design
      // within a tight band, so a uniform downscale that keeps proportions is caught, not passed.
      const heights = cells.map((c) => c.hostH);
      expect(Math.max(...heights) - Math.min(...heights), "gallery cards are uniform height (no marooning)").toBeLessThanOrEqual(2);
      expect(Math.min(...heights), "gallery card height matches the ~15rem design (not shrunk)").toBeGreaterThanOrEqual(255);
      expect(Math.max(...heights), "gallery card height matches the ~15rem design (not grown)").toBeLessThanOrEqual(285);

      // Cards wrap onto multiple rows (some share a left edge, some do not) on a wide screen.
      const distinctLefts = new Set(cells.map((c) => Math.round(c.left / 5))).size;
      expect(distinctLefts, "wide-screen gallery lays out across multiple columns/rows").toBeGreaterThanOrEqual(2);

      for (const c of cells) {
        expect(c.borderPx, `card for "${c.src}" is framed`).toBeGreaterThanOrEqual(1);
        // Not empty (the two-phase pie / a failed render would leave an empty box).
        expect(c.nodeCount, `diagram "${c.src}" has real rendered content (not an empty box)`).toBeGreaterThanOrEqual(5);
        // Hug-fit depends on mermaid emitting a positive viewBox (so `width:auto` derives the width).
        expect(c.hasPositiveViewBox, `diagram "${c.src}" has a positive viewBox (aspect-sizing works)`).toBe(true);
        // The card HUGS the diagram (svg box fills the card in both dimensions: fixed height honoured +
        // card shrunk to the aspect-derived width). If a regression put the diagram in a wider fixed
        // card, the svg box no longer fills the card width and this fails.
        expect(c.svgBoxW, `diagram "${c.src}" svg box fills the card width (card hugs it)`).toBeGreaterThanOrEqual((c.cardW - 28) * 0.85);
        expect(c.svgBoxH, `diagram "${c.src}" svg box fills the card height (fixed height honoured)`).toBeGreaterThanOrEqual((c.hostH - 28) * 0.85);
        // The painted CONTENT fills a real fraction of the card AREA - the anti-sliver / anti-`Math.max`
        // check: a thin band or narrow strip has one collapsed dimension so its AREA drops (the old
        // contain-fit state sliver scored ~0.04-0.18 here) even though one axis is full.
        expect(c.fillArea, `diagram "${c.src}" content fills the card area (not a sliver/band/tiny)`).toBeGreaterThanOrEqual(0.35);
        // No painted node spills outside the (overflow:hidden) svg box - a shifted/overflowing diagram
        // would be silently clipped.
        expect(c.clip, `diagram "${c.src}" has no clipped/overflowing content`).toBe(0);
        // Legibility floor: the smallest rendered text is not crushed to microscopic, and no text is
        // painted invisible (transparent fill / zero opacity) - a geometric-only check would miss that.
        if (c.nText > 0) {
          expect(c.minTextH, `diagram "${c.src}" text is legible, not crushed`).toBeGreaterThanOrEqual(6);
          expect(c.textInvisible, `diagram "${c.src}" text is painted (not transparent/hidden)`).toBe(0);
        }
        // Same legibility floor for HTML labels: non-deck mermaid (flowchart/state/class/er) renders its
        // node labels as HTML in <foreignObject>, which the svg-<text> checks above do NOT see. A broken
        // HTML label (crushed to microscopic, or painted transparent/hidden) would look empty in a real
        // browser while every geometry + svg-text check stayed green - exactly the "green headless,
        // broken live" failure this gallery exists to prevent - so assert the HTML label content too.
        if (c.nHtmlLabel > 0) {
          expect(c.htmlLabelMinH, `diagram "${c.src}" HTML labels are legible, not crushed`).toBeGreaterThanOrEqual(6);
          expect(c.htmlLabelInvisible, `diagram "${c.src}" HTML labels are painted (not transparent/hidden)`).toBe(0);
        }
        // The diagram is WHOLE inside its card and the card never scrolls vertically. (The demo's
        // diagrams all fit under the card cap, so none scroll horizontally either.)
        expect(c.within, `diagram "${c.src}" is whole inside its card (not clipped)`).toBe(true);
        expect(c.scrolls, `card "${c.src}" does not scroll (hug-fit)`).toBe(false);
      }

      // The demo genuinely exercises HTML-label (foreignObject) diagrams, so the per-card HTML-label
      // legibility assertions above are not vacuously skipped: at least one live card must have them.
      expect(cells.some((c) => c.nHtmlLabel > 0), "the demo gallery includes HTML-label (foreignObject) diagrams").toBe(true);

      // The tall state diagram is present, shown WHOLE, and gets a NARROW hugging card (not a wide card
      // it slivers inside): its card is markedly narrower than the widest card.
      const tall = cells.find((c) => c.src.startsWith("stateDiagram"));
      const widest = Math.max(...cells.map((c) => c.cardW));
      expect(tall, "found the state diagram").toBeTruthy();
      expect(tall.cardW, "the tall state diagram gets a narrow hugging card (not a wide one it slivers in)").toBeLessThan(widest * 0.7);
      expect(tall.fillArea, "the tall state diagram fills its hugging card (whole, not slivered)").toBeGreaterThanOrEqual(0.35);
      expect(tall.within, "the tall state diagram is whole inside its card (not clipped)").toBe(true);

      expect(errors, "no uncaught errors").toEqual([]);
    } finally {
      await server.close();
    }
  });
});
