import { test, expect } from "@playwright/test";
import path from "path";
import fs from "fs";
import { EXAMPLES, INLINE, fileUrl, ready, stageContent, stageDeck, addTextComment, openComposerFor } from "./helpers.js";

// Follow-up polish (issue #360). Mobile viewport unless noted.
const MOBILE = { width: 390, height: 844 };

test.describe("visual-audit follow-ups", () => {
  test.use({ viewport: MOBILE });

  test("a leading lede/card also clears the fixed toolbar on mobile (CMH-RESP-03)", async ({ page }) => {
    const staged = stageContent(`<header class="cmh-lede"><h1>Carded title</h1></header><section><h2>Body</h2><p>Text.</p></section>`,
      { key: "cmh-lede-clear", source: "lede-clear.html" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      const r = await page.evaluate(() => {
        const first = document.querySelector("#commentRoot > *");
        const tb = document.querySelector(".cm-toolbar");
        return {
          tag: first ? first.tagName.toLowerCase() : null,
          marginTop: first ? parseFloat(getComputedStyle(first).marginTop) : 0,
          firstTop: first ? first.getBoundingClientRect().top : 0,
          toolbarBottom: tb ? tb.getBoundingClientRect().bottom : 0,
        };
      });
      expect(r.tag, "the leading element is the lede header").toBe("header");
      expect(r.marginTop, "the leading card reserves space under the toolbar").toBeGreaterThanOrEqual(40);
      expect(r.firstTop, "the leading card starts below the toolbar pill").toBeGreaterThanOrEqual(r.toolbarBottom - 1);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("the notes fold control has a >=44px touch target on mobile (CMH-RESP-07)", async ({ page }) => {
    const staged = stageContent(`<h1>Notes touch</h1><div class="cmh-note"><button type="button" class="cmh-note-fold" id="fold"></button></div>`,
      { key: "cmh-note-touch", source: "note-touch.html" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      const size = await page.evaluate(() => {
        const a = getComputedStyle(document.getElementById("fold"), "::after");
        return { w: parseFloat(a.width), h: parseFloat(a.height) };
      });
      expect(size.w, "fold tap target width >=44px").toBeGreaterThanOrEqual(44);
      expect(size.h, "fold tap target height >=44px").toBeGreaterThanOrEqual(44);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("sidebar comment-card action buttons are >=44px tall on mobile (CMH-RESP-07)", async ({ page }) => {
    await page.goto(fileUrl(INLINE));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "touch target check");
    const minH = await page.evaluate(() => {
      const btns = [...document.querySelectorAll(".cm-card .meta .acts button")];
      if (!btns.length) return 0;
      return Math.min(...btns.map((b) => b.getBoundingClientRect().height));
    });
    expect(minH, "jump/edit/delete are comfortable touch targets").toBeGreaterThanOrEqual(44);
  });

  // Measures an action row's buttons against the CONTENT box of the surface that owns it (inside
  // that surface's padding and border), so a button merely painted over the surface's edge still
  // counts as clipped. The surface is derived FROM the row rather than queried independently, so a
  // document holding several cards can never measure a button against a box that does not own it.
  // Floating surfaces are re-clamped from a ResizeObserver, so settle two frames first.
  async function measureActionRow(page, rowSel, surfaceSel) {
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
    return page.evaluate(({ q, s }) => {
      const row = document.querySelector(q);
      if (!row) throw new Error("missing row " + q);
      const surface = row.closest(s);
      if (!surface) throw new Error("row " + q + " has no " + s + " ancestor");
      const cs = getComputedStyle(surface);
      const rs = getComputedStyle(row);
      const box = surface.getBoundingClientRect();
      return {
        left: box.left + parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth),
        right: box.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth),
        top: box.top + parseFloat(cs.paddingTop) + parseFloat(cs.borderTopWidth),
        bottom: box.bottom - parseFloat(cs.paddingBottom) - parseFloat(cs.borderBottomWidth),
        vw: window.innerWidth,
        vh: window.innerHeight,
        rowGap: parseFloat(rs.rowGap),
        columnGap: parseFloat(rs.columnGap),
        boxes: Array.from(row.querySelectorAll("button")).map((b) => {
          const r = b.getBoundingClientRect();
          // A button narrower than its label either truncates an unbreakable token (which
          // `scrollWidth` sees) or WRAPS the label onto extra lines (which it does not - these
          // buttons do not carry `white-space: nowrap`). Count the label's line boxes so the
          // squeeze is caught either way.
          const range = document.createRange();
          range.selectNodeContents(b);
          return {
            act: b.getAttribute("data-act") || b.classList[0] || (b.textContent || "").trim(),
            label: (b.textContent || "").trim(),
            w: r.width, h: r.height, top: r.top, bottom: r.bottom, left: r.left, right: r.right,
            // Rounded separately: the line grouping needs a stable key, but a rounded coordinate
            // would eat the sub-pixel tolerance the containment checks rely on.
            line: Math.round(r.top),
            overflowX: b.scrollWidth - b.clientWidth,
            labelLines: range.getClientRects().length,
          };
        }),
      };
    }, { q: rowSel, s: surfaceSel });
  }

  // Every button in the row is a >=44px target that stays inside its surface, on screen, with its
  // label on one line. The rows are right-aligned, so an overflowing line spills past the START
  // edge - the containment checks, not a scrollWidth probe on the surface, are what catch that.
  // `onScreenY` is only asserted for a FIXED floating surface: the side pane's cards live in a
  // scrolling list (`.cm-sidebar .list`), where a row below the fold is reached by scrolling and is
  // not a defect - there, containment within the composer is the meaningful bound.
  function expectRowFits(info, label, count, { onScreenY = false } = {}) {
    expect(info.boxes.length, `${label}: the row holds all of its actions`).toBe(count);
    for (const b of info.boxes) {
      expect(b.h, `${label}: '${b.label}' height`).toBeGreaterThanOrEqual(44);
      expect(b.w, `${label}: '${b.label}' width`).toBeGreaterThanOrEqual(44);
      expect(b.left, `${label}: '${b.label}' clipped at the start edge`).toBeGreaterThanOrEqual(info.left - 0.5);
      expect(b.right, `${label}: '${b.label}' clipped at the end edge`).toBeLessThanOrEqual(info.right + 0.5);
      expect(b.top, `${label}: '${b.label}' above its surface`).toBeGreaterThanOrEqual(info.top - 0.5);
      expect(b.bottom, `${label}: '${b.label}' below its surface`).toBeLessThanOrEqual(info.bottom + 0.5);
      expect(b.left, `${label}: '${b.label}' off the left of the screen`).toBeGreaterThanOrEqual(-0.5);
      expect(b.right, `${label}: '${b.label}' off the right of the screen`).toBeLessThanOrEqual(info.vw + 0.5);
      if (onScreenY) {
        expect(b.top, `${label}: '${b.label}' off the top of the screen`).toBeGreaterThanOrEqual(-0.5);
        expect(b.bottom, `${label}: '${b.label}' off the bottom of the screen`).toBeLessThanOrEqual(info.vh + 0.5);
      }
      expect(b.overflowX, `${label}: '${b.label}' truncates its own label`).toBeLessThanOrEqual(1);
      // Exactly one line box: zero would mean an empty label (which every size check would pass
      // vacuously), more than one means the button was squeezed until its label wrapped.
      expect(b.labelLines, `${label}: '${b.label}' does not render on exactly one line`).toBe(1);
    }
    // Neither axis may close up between an enlarged Save and the Cancel beside it, which discards
    // the draft with no confirmation.
    expect(info.rowGap, `${label}: wrapped lines keep a deliberate gap`).toBeGreaterThanOrEqual(12);
    expect(info.columnGap, `${label}: neighbours on one line keep a deliberate gap`).toBeGreaterThanOrEqual(12);
  }

  // Pins WHICH buttons a row holds, by selector rather than by a class string, so an added modifier
  // class or a reordering cannot break it while a dropped or relocated button still fails.
  async function expectRowHolds(page, rowSel, acts) {
    await expect(page.locator(`${rowSel} button`)).toHaveCount(acts.length);
    for (const sel of acts) await expect(page.locator(`${rowSel} button${sel}`)).toHaveCount(1);
  }

  const rowLines = (info) => new Set(info.boxes.map((b) => b.line)).size;

  // The shipped density presets each redefine the control padding, font size and gap
  // (`assets/css/00-base.css`), so each row is measured under all three, not just the default.
  const DENSITIES = ["", "compact", "comfortable"];
  const setDensity = (page, d) => page.evaluate((v) => {
    if (v) document.body.setAttribute("data-cm-density", v);
    else document.body.removeAttribute("data-cm-density");
  }, d);

  // Measure one action row under every density preset, asserting it fits and stays on one line.
  async function expectRowFitsEveryDensity(page, rowSel, surfaceSel, label, acts, opts) {
    await expectRowHolds(page, rowSel, acts);
    for (const density of DENSITIES) {
      await setDensity(page, density);
      const info = await measureActionRow(page, rowSel, surfaceSel);
      expectRowFits(info, `${label} [density=${density || "default"}]`, acts.length, opts);
      // With the shipped labels the enlarged row still fits ONE line at 320px in every preset, so
      // the wrap below is a fallback rather than the everyday layout.
      expect(rowLines(info), `${label} [density=${density || "default"}] fits one line at 320px`).toBe(1);
    }
    await setDensity(page, "");
  }

  test("the composer action rows are >=44px touch targets on mobile (CMH-RESP-13)", async ({ page }) => {
    // 320px is the narrowest phone the repo targets, so measure the tightest case, not just 390px.
    await page.setViewportSize({ width: 320, height: 720 });
    await page.goto(fileUrl(INLINE));
    await ready(page);

    // The FLOATING composer is the surface a reviewer touches first.
    await openComposerFor(page, "#commentRoot p");
    await expect(page.locator(".cm-composer")).toHaveCount(1);
    await expectRowFitsEveryDensity(page, ".cm-composer .row", ".cm-composer", "floating composer",
      ['[data-act="cancel"]', '[data-act="save"]'], { onScreenY: true });
    // The enlarged buttons still do their job at that size.
    await page.locator(".cm-composer textarea").fill("phone touch targets");
    await page.locator('.cm-composer .row [data-act="save"]').click();
    await expect(page.locator(".cm-composer")).toHaveCount(0);

    // The side pane's REPLY composer, on the same surface a reviewer answers a thread from. The
    // surface measured against is `.cm-reply-compose`, the row's own flex-column parent, whose
    // content box is exactly the width available to the row - strictly tighter than the card, and
    // the only box that reflects the extra inset a reply's editor sits behind.
    const REPLY_ACTS = [".cm-reply-cancel", ".cm-reply-save"];
    await page.locator(".cm-card .cm-reply-btn").first().click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(1);
    await expectRowFitsEveryDensity(page, ".cm-reply-compose-actions", ".cm-reply-compose",
      "side pane reply composer", REPLY_ACTS);
    await page.locator(".cm-reply-compose textarea").fill("a reply from a phone");
    await page.locator(".cm-reply-compose .cm-reply-save").click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(0);
    await expect(page.locator(".cm-card .cm-reply")).toContainText("a reply from a phone");

    // The ROOT entry's EDIT composer, which reuses the same actions row.
    await page.locator('.cm-card .cm-entry-root [data-act="edit"]').first().click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(1);
    await expectRowFitsEveryDensity(page, ".cm-reply-compose-actions", ".cm-reply-compose",
      "side pane root edit composer", REPLY_ACTS);
    await page.locator(".cm-reply-compose .cm-reply-cancel").click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(0);

    // A REPLY's edit composer is the narrowest instance of the row: `.cm-replies` insets it by its
    // own padding and border, so it is measured too rather than left to the wrap fallback.
    await page.locator('.cm-card .cm-reply [data-act="reply-edit"]').first().click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(1);
    await expectRowFitsEveryDensity(page, ".cm-reply-compose-actions", ".cm-reply-compose",
      "side pane reply edit composer", REPLY_ACTS);
    await page.locator(".cm-reply-compose .cm-reply-save").click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(0);
  });

  test("an over-wide composer action row wraps instead of clipping (CMH-RESP-13)", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 720 });
    await page.goto(fileUrl(INLINE));
    await ready(page);
    // Stand in for the thing that would actually overflow these rows - a localized label set, or a
    // host document with a larger root font - by widening the buttons themselves, so the wrap
    // fallback is exercised rather than merely declared.
    await page.addStyleTag({
      content: ".cm-composer .row button, .cm-reply-compose-actions button"
        + " { padding-left: 60px !important; padding-right: 60px !important; }",
    });

    await openComposerFor(page, "#commentRoot p");
    await expect(page.locator(".cm-composer")).toHaveCount(1);
    const composer = await measureActionRow(page, ".cm-composer .row", ".cm-composer");
    expectRowFits(composer, "wrapped floating composer", 2, { onScreenY: true });
    expect(rowLines(composer), "the floating composer row wraps rather than clipping").toBeGreaterThan(1);

    // The gaps are a FLOOR in an absolute unit, so no host document's root font-size can close the
    // lines (or the neighbours) up. Pin that at BOTH ends rather than only reading the computed px
    // once at the default root: a `rem` gap passes a single default-root reading, and a plain
    // absolute value would lose the roomier density-scaled gap a large-root host already had.
    try {
      for (const rootFont of ["8px", "32px"]) {
        await page.evaluate((v) => { document.documentElement.style.fontSize = v; }, rootFont);
        const scaled = await measureActionRow(page, ".cm-composer .row", ".cm-composer");
        expect(scaled.rowGap, `row gap floor at a ${rootFont} root`).toBeGreaterThanOrEqual(12);
        expect(scaled.columnGap, `column gap floor at a ${rootFont} root`).toBeGreaterThanOrEqual(12);
        // ...and at a large root the density-scaled gap is kept rather than capped back to 12px.
        if (rootFont === "32px") {
          expect(scaled.rowGap, "a large root keeps its roomier density gap").toBeGreaterThan(composer.rowGap);
        }
      }
    } finally {
      await page.evaluate(() => { document.documentElement.style.fontSize = ""; });
    }

    await page.locator(".cm-composer textarea").fill("wrapped actions row");
    await page.locator('.cm-composer .row [data-act="save"]').click();
    await expect(page.locator(".cm-composer")).toHaveCount(0);

    await page.locator(".cm-card .cm-reply-btn").first().click();
    await expect(page.locator(".cm-reply-compose")).toHaveCount(1);
    const reply = await measureActionRow(page, ".cm-reply-compose-actions", ".cm-reply-compose");
    expectRowFits(reply, "wrapped side pane reply composer", 2);
    expect(rowLines(reply), "the reply row wraps rather than clipping").toBeGreaterThan(1);
  });

  test("table-mode checklist rows keep their 44px tap targets from overlapping (CMH-RESP-06)", async ({ page }) => {
    const table =
      '<h1>Audit</h1>' +
      '<table class="cmh-checklist" data-cmh-checklist="audit" data-cmh-checklist-label="Audit">' +
      '<thead><tr><th></th><th>Control</th></tr></thead><tbody>' +
      '<tr data-cmh-item="a" data-cmh-state="blank"><td class="st"></td><td>Alpha</td></tr>' +
      '<tr data-cmh-item="b" data-cmh-state="blank"><td></td><td>Bravo</td></tr>' +
      '<tr data-cmh-item="c" data-cmh-state="blank"><td></td><td>Charlie</td></tr>' +
      '</tbody></table>';
    const staged = stageContent(table, { key: "cmh-resp06-table", source: "resp06-table.html" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("table.cmh-checklist.cmh-checklist-ready")).toHaveCount(1);
      const gap = await page.evaluate(() => {
        const checks = [...document.querySelectorAll("table.cmh-checklist .cmh-check")];
        const centers = checks.map((c) => { const r = c.getBoundingClientRect(); return r.top + r.height / 2; });
        let minGap = Infinity;
        for (let i = 1; i < centers.length; i++) minGap = Math.min(minGap, centers[i] - centers[i - 1]);
        return { count: checks.length, minGap };
      });
      expect(gap.count, "every authored row has a state control").toBeGreaterThanOrEqual(3);
      // The 44px tap overlays are centred on these controls; a center-to-center gap of
      // >=44px keeps a row's overlay out of its neighbour's hit area.
      expect(gap.minGap, "adjacent row tap targets do not overlap").toBeGreaterThanOrEqual(44);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });
});

test("small charts fit the mobile viewport instead of being force-widened (CMH-RESP-08)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const staged = stageContent(
    `<h1>Chart fit</h1><figure class="chart" id="c"><div class="chart-wrap"><canvas width="280" height="180" role="img" aria-label="small chart"></canvas></div><figcaption>small</figcaption></figure>`,
    { key: "cmh-chart-fit", source: "chart-fit.html" });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const m = await page.evaluate(() => {
      const fig = document.getElementById("c");
      const wrap = fig.querySelector(".chart-wrap");
      return {
        vw: document.documentElement.clientWidth,
        wrapW: wrap.getBoundingClientRect().width,
        figScroll: fig.scrollWidth - fig.clientWidth,
      };
    });
    expect(m.wrapW, "the chart wrap is not force-widened past the viewport").toBeLessThanOrEqual(m.vw + 1);
    expect(m.figScroll, "a small chart does not need horizontal scrolling").toBeLessThanOrEqual(1);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("sidebar context preview inserts separators at block boundaries (CMH-CTX-01)", async ({ page }) => {
  const staged = stageContent(
    `<h1>Ctx doc</h1><div class="cmh-callout"><div>18</div><div>open incidents</div></div>` +
    `<p id="t">Target sentence to anchor the comment for the context separator test.</p>`,
    { key: "cmh-ctx-sep", source: "ctx-sep.html" });
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await addTextComment(page, "#t", "context separator check");
    const before = await page.evaluate(() => {
      const arr = window.__cmhStorageCodec.read();
      return (arr[0] && arr[0].before) || "";
    });
    expect(before, "adjacent block texts are not glued into a run-on").not.toContain("18open");
    expect(before, "the numbers and label read as separate words").toContain("18 open incidents");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("deck mode does not inherit the report title toolbar-clearance margin on mobile (CMH-RESP-03)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { dir, html } = stageDeck('<section class="slide active" data-slide-id="s1"><h2>One</h2><p>content</p></section>', { key: "cmh-deck-margin" });
  try {
    await page.goto(fileUrl(html));
    await ready(page);
    const mt = await page.evaluate(() => {
      const fc = document.querySelector("#commentRoot > :first-child");
      return fc ? parseFloat(getComputedStyle(fc).marginTop) : -1;
    });
    expect(mt, "the deck viewport is not pushed down by the report toolbar-clearance margin (the deck toolbar is hidden)").toBeLessThanOrEqual(1);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
