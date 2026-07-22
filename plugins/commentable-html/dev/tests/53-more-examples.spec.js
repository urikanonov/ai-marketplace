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

// CMH-DEMO-06: the visuals-matrix Mermaid gallery must not maroon short diagrams in tall empty
// cells on a wide screen, and each diagram must fit inside its cell (never clipped) at both wide
// and narrow/mobile widths. Before the fix, the gallery `.visual-grid` used `align-items: stretch`,
// so one naturally tall, portrait diagram (the state diagram, which the narrow scale-up grows even
// taller) forced its whole grid row tall and stranded the short diagrams (flowchart, sequence,
// gantt) in big empty boxes. The gallery now boxes each diagram to a uniform, bounded height and
// fits the SVG inside it (resetting the layer wide-diagram `min-width` so a wide diagram is not
// clipped by the cell's `overflow: hidden` on mobile).
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

  test("gallery diagrams stay bounded and uniform, not marooned in tall empty cells on wide screens", async ({ page }) => {
    test.setTimeout(60000);
    // A wide viewport gives the auto-fit grid several columns, so the tall portrait diagram shares
    // a row with short diagrams - the exact condition that produced the marooning.
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

      // Each gallery cell is height-bounded (the pre-fix stretch produced ~637px cells).
      const MAX_CELL = 400;
      for (const c of cells) {
        expect(c.svgH, `diagram "${c.src}" actually rendered`).toBeGreaterThan(0);
        expect(c.hostH, `gallery cell for "${c.src}" is height-bounded`).toBeLessThanOrEqual(MAX_CELL);
        // The rendered diagram fits inside its cell (fit, not clipped away or overflowing) - both axes.
        expect(c.svgH, `diagram "${c.src}" fits its cell vertically`).toBeLessThanOrEqual(c.hostH + 2);
        expect(c.svgW, `diagram "${c.src}" fits its cell horizontally`).toBeLessThanOrEqual(c.hostW + 2);
        // ...and does not overhang either edge (would be clipped by the cell's overflow: hidden).
        expect(c.overRight, `diagram "${c.src}" not clipped on the right`).toBeLessThanOrEqual(1);
        expect(c.overLeft, `diagram "${c.src}" not clipped on the left`).toBeLessThanOrEqual(1);
      }

      // The cells are uniform: one tall sibling cannot balloon a whole row (pre-fix range ~158px).
      const heights = cells.map((c) => c.hostH);
      expect(Math.max(...heights) - Math.min(...heights), "gallery cells are uniform height").toBeLessThanOrEqual(8);
      expect(errors, "no uncaught errors").toEqual([]);
    } finally {
      await server.close();
    }
  });

  test("gallery wide diagrams are not clipped by the cell on a mobile viewport", async ({ page }) => {
    test.setTimeout(60000);
    // On <=480px the layer forces `min-width: 560px` on a wide diagram's SVG; without resetting it,
    // the gallery cell's `overflow: hidden` clips wide diagrams (sequence, pie). Assert each diagram
    // stays inside its cell horizontally so the clip regression stays fixed.
    await page.setViewportSize({ width: 390, height: 800 });
    const server = await startStaticServer(PLUGIN);
    const errors = watchErrors(page);
    try {
      await routeMermaidLocal(page);
      await page.goto(`${server.url}/examples/report-metrics.html`);
      await ready(page);
      await expect(page.locator("#commentRoot .visual-grid > pre.mermaid svg")).toHaveCount(7, { timeout: 20000 });

      const cells = await measureGallery(page);
      for (const c of cells) {
        expect(c.svgW, `diagram "${c.src}" actually rendered`).toBeGreaterThan(0);
        // The SVG box must not extend past either edge of its cell (would be clipped by overflow:hidden).
        expect(c.svgW, `diagram "${c.src}" fits the mobile cell width`).toBeLessThanOrEqual(c.hostW + 2);
        expect(c.overRight, `diagram "${c.src}" not clipped on the right`).toBeLessThanOrEqual(1);
        expect(c.overLeft, `diagram "${c.src}" not clipped on the left`).toBeLessThanOrEqual(1);
      }
      expect(errors, "no uncaught errors").toEqual([]);
    } finally {
      await server.close();
    }
  });
});
