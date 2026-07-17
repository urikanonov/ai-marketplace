import { test, expect } from "@playwright/test";
import path from "path";
import fs from "fs";
import { EXAMPLES, INLINE, fileUrl, ready, stageContent, stageDeck, addTextComment } from "./helpers.js";

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

test("the deck comment-mode toggle and brand link use distinct icons (CMH-DECK-23)", async ({ page }) => {
  await page.setViewportSize({ width: 1200, height: 800 });
  await page.goto(fileUrl(path.join(EXAMPLES, "deck-showcase.html")));
  await ready(page);
  const icons = await page.evaluate(() => {
    const modeSvg = document.querySelector(".cmh-deck-mode-toggle svg");
    const brandSvg = document.querySelector(".cmh-deck-brand-link svg");
    return {
      modeClass: modeSvg ? modeSvg.getAttribute("class") : null,
      brandClass: brandSvg ? brandSvg.getAttribute("class") : null,
      same: modeSvg && brandSvg ? modeSvg.innerHTML === brandSvg.innerHTML : true,
    };
  });
  expect(icons.modeClass, "the comment-mode toggle uses the distinct annotate icon").toBe("cmh-deck-mode-icon");
  expect(icons.brandClass, "the brand link keeps the brand logo").toBe("cm-brand-icon");
  expect(icons.same, "the two top-corner controls no longer render identical icons").toBe(false);
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
      const key = (document.getElementById("commentRoot") || document.body).dataset.commentKey;
      const arr = JSON.parse(localStorage.getItem(key) || "[]");
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

test("deck overview snapshots canvases and namespaces cloned SVG ids (CMH-DECK-24)", async ({ page }) => {
  const slides =
    '<style>#commentRoot[data-cmh-mode="deck"] .t-shape { fill: rgb(10, 20, 30); }</style>' +
    '<section class="slide active" data-slide-id="slide-1"><h2>Chart</h2><canvas id="oc" width="120" height="80"></canvas></section>' +
    '<section class="slide" data-slide-id="slide-2"><h2>Logo A</h2><svg viewBox="0 0 24 24" width="40" height="40">' +
    '<defs><linearGradient id="grad"><stop offset="0" stop-color="#ff0000"/><stop offset="1" stop-color="#0000ff"/></linearGradient></defs>' +
    '<rect width="24" height="24" fill="url(#grad)"/><rect class="t-shape" x="0" y="0" width="8" height="8"/></svg></section>' +
    '<section class="slide" data-slide-id="slide-3"><h2>Logo B</h2><svg viewBox="0 0 24 24" width="40" height="40">' +
    '<defs><linearGradient id="grad"><stop offset="0" stop-color="#00aa00"/><stop offset="1" stop-color="#00ffff"/></linearGradient></defs>' +
    '<rect width="24" height="24" fill="url(#grad)"/></svg></section>';
  const { dir, html } = stageDeck(slides, { key: "cmh-ov-f7" });
  try {
    await page.goto(fileUrl(html));
    await ready(page);
    await page.evaluate(() => {
      const c = document.getElementById("oc");
      const g = c.getContext("2d");
      g.fillStyle = "#00aa00";
      g.fillRect(0, 0, 120, 80);
    });
    await page.locator(".cmh-deck-nav").getByRole("button", { name: "Slide overview", exact: true }).click();
    await expect(page.locator(".cmh-deck-overview")).toBeVisible();
    const r = await page.evaluate(() => {
      const cards = [...document.querySelectorAll(".cmh-deck-overview .cmh-deck-overview-card")];
      const scale = (i) => cards[i].querySelector(".cmh-deck-overview-scale");
      const c0 = scale(0), c1 = scale(1), c2 = scale(2);
      const img = c0.querySelector("img");
      const shape = c1.querySelector(".t-shape");
      const fillIdOf = (sc) => {
        const rect = sc.querySelector('rect[fill^="url(#"]');
        return rect ? rect.getAttribute("fill").replace(/^url\(#/, "").replace(/\)$/, "") : null;
      };
      const stopColorWithin = (sc, id) => {
        const grad = id ? sc.querySelector("#" + CSS.escape(id)) : null;
        const stop = grad ? grad.querySelector("stop") : null;
        return stop ? stop.getAttribute("stop-color") : null;
      };
      const id1 = fillIdOf(c1), id2 = fillIdOf(c2);
      const idCount = (id) => document.querySelectorAll('[id="' + id + '"]').length;
      return {
        canvasReplacedByImg: !c0.querySelector("canvas") && !!img,
        imgHasData: !!img && String(img.getAttribute("src") || "").startsWith("data:image"),
        scopedFill: shape ? getComputedStyle(shape).fill : "",
        overviewHasRawGrad: !!document.querySelector('.cmh-deck-overview [id="grad"]'),
        id1Unique: id1 ? idCount(id1) === 1 : false,
        id2Unique: id2 ? idCount(id2) === 1 : false,
        idsDiffer: !!id1 && !!id2 && id1 !== id2,
        stop1: stopColorWithin(c1, id1),
        stop2: stopColorWithin(c2, id2),
        liveStillGrad: !!document.querySelector('.slide[data-slide-id="slide-2"] #grad'),
      };
    });
    expect(r.canvasReplacedByImg, "the cloned canvas is replaced by a snapshot image").toBe(true);
    expect(r.imgHasData, "the snapshot is a data URL of the drawn canvas").toBe(true);
    expect(r.scopedFill, "deck-scoped SVG fills are inlined so the thumbnail is not black").toBe("rgb(10, 20, 30)");
    // The thumbnails must not keep the raw authored id (that duplicates the live slide's
    // id and makes url(#grad) resolve to the wrong gradient) - ids are namespaced.
    expect(r.overviewHasRawGrad, "cloned SVG ids are namespaced, not left as raw duplicates").toBe(false);
    expect(r.id1Unique, "thumbnail 1 gradient id is unique in the document").toBe(true);
    expect(r.id2Unique, "thumbnail 2 gradient id is unique in the document").toBe(true);
    expect(r.idsDiffer, "two slides reusing id 'grad' get distinct namespaced ids").toBe(true);
    // ...and each thumbnail resolves to ITS OWN gradient, so the logo is not black.
    expect(r.stop1, "thumbnail 1 resolves its own red gradient").toBe("#ff0000");
    expect(r.stop2, "thumbnail 2 resolves its own green gradient").toBe("#00aa00");
    expect(r.liveStillGrad, "the live slide keeps its original id").toBe(true);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
