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
// CMH-DEMO-06: the visuals-matrix Mermaid gallery must render every diagram at a readable size with
// no marooning (a short/narrow diagram stranded in a tall empty box) and no slivers, on a wide
// screen where the layout is multi-column. A CSS *grid* row is as tall as its tallest cell, so the
// one very tall diagram (the state diagram) would either strand short siblings in empty space
// (marooning) or, if each cell is height-bounded to avoid that, squash tall-narrow diagrams into
// thin slivers. The gallery uses a masonry (CSS multi-column) flow instead, so each cell hugs its
// own diagram and columns pack independently. On a single-column mobile viewport the layer's own
// wide-diagram scroll behavior is left intact (covered by CMH-RESP-01 in 51-charts-mobile.spec.js).
test.describe("commentable visuals matrix: mermaid gallery layout (CMH-DEMO-06)", () => {
  // Measure every gallery cell and its rendered diagram (host + svg box rects).
  const measureGallery = (page) => page.evaluate(() => {
    const hosts = [...document.querySelectorAll("#commentRoot .visual-grid > pre.mermaid")];
    return hosts.map((el) => {
      const svg = el.querySelector("svg");
      const hr = el.getBoundingClientRect();
      const sr = svg ? svg.getBoundingClientRect() : null;
      return {
        src: (el.getAttribute("data-cmh-md-src") || "").split("\n")[0].trim(),
        hostW: Math.round(hr.width), hostH: Math.round(hr.height),
        svgW: sr ? Math.round(sr.width) : 0, svgH: sr ? Math.round(sr.height) : 0,
        overRight: sr ? Math.round(sr.right - hr.right) : 0,
        overLeft: sr ? Math.round(hr.left - sr.left) : 0,
      };
    });
  });

  test("gallery diagrams render un-marooned (each cell hugs its diagram) on a wide screen", async ({ page }) => {
    test.setTimeout(60000);
    // A wide viewport makes the gallery multi-column, so the very tall state diagram shares a row
    // (grid) or a set of columns (masonry) with short diagrams - the condition that produced the
    // marooning / sliver failures.
    await page.setViewportSize({ width: 1600, height: 1000 });
    const server = await startStaticServer(PLUGIN);
    const errors = watchErrors(page);
    try {
      await routeMermaidLocal(page);
      await page.goto(`${server.url}/examples/report-metrics.html`);
      await ready(page);
      // Every gallery diagram renders its SVG (served over http so mermaid runs).
      await expect(page.locator("#commentRoot .visual-grid > pre.mermaid svg")).toHaveCount(7, { timeout: 20000 });

      const cells = await measureGallery(page);

      // The mermaid gallery must actually be in the masonry (multi-column block) layout, not the grid
      // - the `#commentRoot`-specificity override is load-bearing (without it the base grid rule wins
      // and the marooning silently returns). Query the mermaid gallery specifically (not the first
      // `.visual-grid`, which only happens to be the mermaid one today), and confirm the CHART gallery
      // is untouched (still a grid), so the masonry change stays scoped.
      const displays = await page.evaluate(() => ({
        mermaid: getComputedStyle(document.querySelector('#commentRoot section[aria-labelledby="mermaid-gallery"] .visual-grid')).display,
        chart: getComputedStyle(document.querySelector('#commentRoot section[aria-labelledby="chart-gallery"] .visual-grid')).display,
      }));
      expect(displays.mermaid, "mermaid gallery uses the masonry (block/columns) layout, not a grid").not.toBe("grid");
      expect(displays.chart, "chart gallery is untouched (still a grid) - masonry is scoped to the mermaid gallery").toBe("grid");

      for (const c of cells) {
        expect(c.svgW, `diagram "${c.src}" actually rendered`).toBeGreaterThan(0);
        expect(c.svgH, `diagram "${c.src}" actually rendered`).toBeGreaterThan(0);
        // The box hugs its diagram in BOTH directions: not a tall frame around a small svg (marooning)
        // and not shorter than its svg (which `overflow` would clip). Two-sided on purpose.
        expect(Math.abs(c.hostH - c.svgH), `box for "${c.src}" hugs its diagram`).toBeLessThanOrEqual(24);
        // The diagram stays inside its column (no horizontal overflow / clipping).
        expect(c.svgW, `diagram "${c.src}" fits its column`).toBeLessThanOrEqual(c.hostW + 2);
        expect(c.overRight, `diagram "${c.src}" not clipped on the right`).toBeLessThanOrEqual(1);
        expect(c.overLeft, `diagram "${c.src}" not clipped on the left`).toBeLessThanOrEqual(1);
      }

      // No diagram towers absurdly tall. This is the guard for the un-capped-narrow regression: if the
      // portrait state diagram were stretched to full column width (instead of staying capped by the
      // layer's CMH-MMD-10 rule), it balloons to a >1400px tower. Every gallery diagram stays modest.
      const tallest = Math.max(...cells.map((c) => c.svgH));
      expect(tallest, "no gallery diagram towers absurdly tall (narrow cap intact)").toBeLessThanOrEqual(900);

      // The columns are real and used, not collapsed to slivers: at least the wide diagrams span
      // essentially their whole column.
      const maxFill = Math.max(...cells.map((c) => (c.hostW ? c.svgW / c.hostW : 0)));
      expect(maxFill, "the widest gallery diagram fills its column").toBeGreaterThanOrEqual(0.85);
      // No marooning: a short diagram must not be stranded above a large vertical gap. In a CSS grid
      // the row height equals the tallest cell, so a short diagram sitting in that row (with the next
      // row far below) leaves a big gap to the diagram beneath it in the same column - even though
      // each box hugs its own svg. A masonry column packs diagrams tightly, so the gap from any
      // diagram to the nearest diagram below it (overlapping horizontally) stays small. Measure the
      // actual laid-out boxes and assert the largest such gap is small.
      const boxes = await page.evaluate(() => {
        const hosts = [...document.querySelectorAll("#commentRoot .visual-grid > pre.mermaid")];
        return hosts.map((el) => {
          const r = el.getBoundingClientRect();
          return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
        });
      });
      let maxGapBelow = 0;
      for (const a of boxes) {
        let nearestBelow = Infinity;
        for (const b of boxes) {
          if (b === a) continue;
          const xOverlap = Math.min(a.right, b.right) - Math.max(a.left, b.left);
          if (xOverlap <= 4) continue; // different column
          if (b.top >= a.bottom - 2) nearestBelow = Math.min(nearestBelow, b.top - a.bottom);
        }
        if (nearestBelow !== Infinity) maxGapBelow = Math.max(maxGapBelow, nearestBelow);
      }
      // Pre-fix the marooned grid left ~500px gaps below the short diagrams; the masonry gap is the
      // ~1.25rem column margin (~20px). 80px comfortably separates the two.
      expect(Math.round(maxGapBelow), "no diagram is marooned above a large vertical gap").toBeLessThanOrEqual(80);

      // The masonry actually forms MULTIPLE columns on a wide screen (a plain single-column
      // `display:block` fallback - columns dropped - would satisfy every other assertion). Distinct
      // left edges among the laid-out diagrams prove real columns.
      const distinctColumns = new Set(boxes.map((b) => Math.round(b.left / 5))).size;
      expect(distinctColumns, "the wide-screen mermaid gallery lays out in multiple columns").toBeGreaterThanOrEqual(2);
      expect(errors, "no uncaught errors").toEqual([]);
    } finally {
      await server.close();
    }
  });
});
