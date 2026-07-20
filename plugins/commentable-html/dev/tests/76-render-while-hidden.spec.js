import { test, expect } from "@playwright/test";
import fs from "fs";
import { fileUrl, ready, stageContent } from "./helpers.js";

// Render-while-hidden class (issue #442): content authored inside a collapsible <section> that is
// collapsed (display:none) at load is measured against a zero-size layout. #430 fixed this for
// Mermaid; these specs cover the two other renderers the review flagged.

test.describe("render-while-hidden renderers", () => {
  // CMH-CHART-09: a built-in canvas chart drawn while its section is collapsed reads clientWidth 0 and
  // falls back to the width attribute (760), so its bitmap is wrong for the real column width. Only a
  // window resize used to re-draw it; on the unfixed code the chart stays at the 760 fallback after
  // reveal (blurry). The reveal ResizeObserver re-renders it at the real width.
  test("CMH-CHART-09: a canvas chart in a collapsed section re-renders at its real width on reveal", async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 900 });
    const points = '[{"label":"A","value":10},{"label":"B","value":24},{"label":"C","value":16}]';
    const content =
      '<section><h2>Intro</h2><p>Lead-in prose so the column has width.</p></section>'
      + '<section class="cmh-section-collapsed" id="sec-chart"><h2>Metrics</h2>'
      + '<figure class="chart" id="chartFig" style="width:420px">'
      + '<div class="chart-wrap cm-skip">'
      + '<canvas id="revealChart" class="cmh-chart" width="760" height="340" role="img"'
      + ' aria-label="Reveal chart" data-cmh-chart-points=\'' + points + '\'></canvas>'
      + '</div><figcaption>Chart in a collapsed section.</figcaption></figure></section>';
    const { dir, html } = stageContent(content, { key: "cmh-chart-hidden", source: "chart-hidden.html" });
    try {
      await page.goto(fileUrl(html));
      await ready(page);

      // While collapsed the canvas has zero client width and rendered to the 760 width-attr fallback.
      const collapsed = await page.evaluate(() => {
        const c = document.getElementById("revealChart");
        return { clientWidth: c.clientWidth, bitmap: c.width, dpr: window.devicePixelRatio || 1 };
      });
      expect(collapsed.clientWidth).toBe(0);
      expect(collapsed.bitmap).toBe(Math.round(760 * collapsed.dpr));

      await page.locator("#sec-chart .cmh-sec-caret").click();
      await expect(page.locator("#sec-chart")).not.toHaveClass(/cmh-section-collapsed/);

      // On reveal the chart re-renders so its bitmap matches its real (narrower) column width.
      await expect
        .poll(() => page.evaluate(() => {
          const c = document.getElementById("revealChart");
          const dpr = window.devicePixelRatio || 1;
          return Math.abs(c.width / dpr - c.clientWidth);
        }), { timeout: 5000 })
        .toBeLessThanOrEqual(2);

      const after = await page.evaluate(() => {
        const c = document.getElementById("revealChart");
        return { clientWidth: c.clientWidth, bitmap: c.width, dpr: window.devicePixelRatio || 1 };
      });
      // Premise: the real width is clearly different from the 760 fallback, so a chart left at 760
      // would be visibly blurry after reveal (this is what makes the test genuinely red pre-fix).
      expect(after.clientWidth).toBeGreaterThan(60);
      expect(after.clientWidth).toBeLessThan(700);
      expect(Math.abs(after.bitmap / after.dpr - after.clientWidth)).toBeLessThanOrEqual(2);

      // Re-collapse and re-reveal: the one-shot observer must re-arm and re-render on a SECOND reveal
      // (not just the first), so a fresh render matches the real width again.
      await page.locator("#sec-chart .cmh-sec-caret").click();
      await expect(page.locator("#sec-chart")).toHaveClass(/cmh-section-collapsed/);
      await expect
        .poll(() => page.evaluate(() => document.getElementById("revealChart").clientWidth), { timeout: 5000 })
        .toBe(0);
      await page.locator("#sec-chart .cmh-sec-caret").click();
      await expect(page.locator("#sec-chart")).not.toHaveClass(/cmh-section-collapsed/);
      await expect
        .poll(() => page.evaluate(() => {
          const c = document.getElementById("revealChart");
          const dpr = window.devicePixelRatio || 1;
          return Math.abs(c.width / dpr - c.clientWidth);
        }), { timeout: 5000 })
        .toBeLessThanOrEqual(2);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  // CMH-CODE-06: sibling guarantee to the chart above. A code/KQL block's line-number gutter is laid
  // out from getComputedStyle(target).lineHeight, which resolves to a px value even while the block is
  // display:none (the browser computes the numeric line-height without layout), so unlike the canvas
  // chart the gutter is already aligned when a collapsed section is revealed - each line row sits at
  // N * lineHeight and the gutter spans the block's real text height. This pins that alignment (against
  // the actually-rendered geometry, not just the computed style) so a future change cannot make the
  // gutter reveal-sensitive, and covers both a plain code block and a KQL figure.
  test("CMH-CODE-06: code and KQL line gutters stay aligned when their collapsed section is revealed", async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 900 });
    const js = "const a = 1;\nconst b = 2;\nconst c = 3;\nconst d = 4;";
    const content =
      '<section><h2>Intro</h2><p>Lead-in.</p></section>'
      + '<section class="cmh-section-collapsed" id="sec-code"><h2>Snippet</h2>'
      + '<pre><code class="language-js" id="revealCode">' + js + '</code></pre></section>'
      + '<section class="cmh-section-collapsed" id="sec-kql"><h2>Query</h2>'
      + '<figure class="cmh-kql"><figcaption class="cm-skip cmh-kql-cap">'
      + '<span class="cmh-kql-title">help / Samples</span></figcaption>'
      + '<pre><code class="language-kusto" id="revealKql">StormEvents\n| take 3\n| project State</code></pre>'
      + '</figure></section>';
    const { dir, html } = stageContent(content, { key: "cmh-code-hidden", source: "code-hidden.html" });
    try {
      await page.goto(fileUrl(html));
      await ready(page);

      const read = (id) => page.evaluate((id) => {
        const el = document.getElementById(id);
        const cs = getComputedStyle(el);
        const gutter = el.querySelector(".cmh-code-gutter");
        const lines = gutter ? [...gutter.querySelectorAll(".cmh-code-line")] : [];
        const lh = parseFloat(cs.lineHeight);
        return {
          lh,
          tops: lines.map((l) => parseFloat(l.style.top)),
          gutterHeight: parseFloat(gutter.style.height),
          codeHeight: el.clientHeight, // real rendered content height
          vPad: parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom),
        };
      }, id);

      // Built while collapsed: the gutter already resolves the real line-height (not the 20px fallback).
      const jsCollapsed = await read("revealCode");
      expect(jsCollapsed.tops.length).toBe(4);
      expect(jsCollapsed.lh).toBeGreaterThan(0);
      expect(jsCollapsed.tops[1]).toBeCloseTo(jsCollapsed.lh, 1);

      await page.locator("#sec-code .cmh-sec-caret").click();
      await page.locator("#sec-kql .cmh-sec-caret").click();
      await expect(page.locator("#sec-code")).not.toHaveClass(/cmh-section-collapsed/);
      await expect(page.locator("#sec-kql")).not.toHaveClass(/cmh-section-collapsed/);

      // After reveal the alignment holds for both blocks: rows at multiples of the line-height, the
      // line-height unchanged from the collapsed measurement, and - the non-tautological check - the
      // gutter height matches the block's ACTUAL rendered text height (which would diverge if the
      // gutter had been laid out on the 20px fallback while the real line-height differs).
      const assertAligned = (m, lineCount) => {
        expect(m.tops.length).toBe(lineCount);
        for (let i = 0; i < lineCount; i++) expect(m.tops[i]).toBeCloseTo(m.lh * i, 1);
        expect(m.gutterHeight).toBeCloseTo(m.lh * lineCount, 1);
        // The gutter spans the block's real text height. Guard the premise (no vertical padding on
        // the target, so clientHeight == the text height) so a padding change gives a clear failure
        // rather than looking like a gutter mis-alignment; allow 1px for integer clientHeight rounding.
        expect(m.vPad).toBeCloseTo(0, 1);
        expect(Math.abs(m.gutterHeight - m.codeHeight)).toBeLessThanOrEqual(1);
      };

      const jsAfter = await read("revealCode");
      expect(jsAfter.lh).toBeCloseTo(jsCollapsed.lh, 1);
      assertAligned(jsAfter, 4);

      const kqlAfter = await read("revealKql");
      assertAligned(kqlAfter, 3);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
