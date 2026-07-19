import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import { PYTHON } from "./helpers.js";
import fs from "fs";
import path from "path";
import {
  openInline, addTextComment, installClipboardCapture, ready,
  startStaticServer, routeMermaidLocal, stageInline, stageContent, SKILL,
} from "./helpers.js";

test.describe("code comments", () => {
  test("commenting on a code block tags the card as code", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot pre code", "tighten this loop");
    await expect(page.locator("#commentList")).toContainText("tighten this loop");
    // The demo code block is class="language-python" -> pin reads "code (python)".
    await expect(page.locator(".cm-card .pin")).toContainText(/code/i);
  });
});

// Mermaid's CDN ES-module import is blocked over file://, so serve over http; the
// jsdelivr request is intercepted and served from the locally vendored mermaid,
// so the diagram render path stays deterministic.
test.describe("mermaid node comments (local vendored mermaid)", () => {
  test("hovering a node reveals + Add comment; saving anchors and rings the node", async ({ page }) => {
    const server = await startStaticServer(SKILL);
    try {
      await routeMermaidLocal(page);
      await installClipboardCapture(page);
      await page.goto(server.url + "/dist/PORTABLE.html?mermaid=1");
      await ready(page);

      const node = page.locator("#commentRoot .mermaid svg g.node").first();
      await expect(node).toBeVisible({ timeout: 20000 });

      await node.hover();
      await expect(page.locator("#mermaidAddBtn")).toBeVisible();
      await page.locator("#mermaidAddBtn").click();

      const composer = page.locator(".cm-composer").last();
      await expect(composer).toBeVisible();
      await composer.locator("textarea").fill("rename this node");
      await composer.locator('[data-act="save"]').click();
      await expect(composer).toHaveCount(0);

      await expect(page.locator("#commentList")).toContainText("rename this node");
      await expect(page.locator(".cm-card .pin")).toContainText(/mermaid diagram/i);
      await expect(page.locator("#commentRoot .mermaid .cm-mermaid-hl").first()).toBeVisible();
    } finally {
      await server.close();
    }
  });

  test("a mermaid node can carry multiple comments; delete-one keeps the ring, reload restores both", async ({ page }) => {
    const server = await startStaticServer(SKILL);
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/dist/PORTABLE.html?mermaid=1");
      await ready(page);
      page.on("dialog", (d) => d.accept());
      const node = page.locator("#commentRoot .mermaid svg g.node").first();
      await expect(node).toBeVisible({ timeout: 20000 });

      const addOn = async (note) => {
        await node.hover();
        await expect(page.locator("#mermaidAddBtn")).toBeVisible();
        await page.locator("#mermaidAddBtn").click();
        const composer = page.locator(".cm-composer").last();
        await composer.locator("textarea").fill(note);
        await composer.locator('[data-act="save"]').click();
        await expect(composer).toHaveCount(0);
      };
      await addOn("first mermaid note");
      await addOn("second mermaid note");

      const cids = (await page.locator("#commentRoot .mermaid .cm-mermaid-hl").first()
        .getAttribute("data-cids")).split(/\s+/).filter(Boolean);
      expect(cids).toHaveLength(2);
      await expect(page.locator(".cm-card")).toHaveCount(2);

      // Delete one -> the ring remains for the survivor.
      await page.locator(".cm-card").filter({ hasText: "first mermaid note" }).locator('[data-act="del"]').click();
      await expect(page.locator("#commentRoot .mermaid .cm-mermaid-hl")).toHaveCount(1);
      await expect(page.locator(".cm-card")).toHaveCount(1);

      // Two comments on the node again -> both survive reload/re-render.
      await addOn("third mermaid note");
      await page.reload();
      await ready(page);
      await expect(page.locator("#commentRoot .mermaid svg g.node").first()).toBeVisible({ timeout: 20000 });
      await expect(page.locator(".cm-card")).toHaveCount(2);
      const after = (await page.locator("#commentRoot .mermaid .cm-mermaid-hl").first()
        .getAttribute("data-cids")).split(/\s+/).filter(Boolean);
      expect(after).toHaveLength(2);
    } finally {
      await server.close();
    }
  });

  test("a mermaid comment prunes on reload once marked handled", async ({ page }) => {
    let server, dir, html;
    try {
      const staged = stageInline();
      dir = staged.dir; html = staged.html;
      server = await startStaticServer(dir);
      await routeMermaidLocal(page);
      await installClipboardCapture(page);
      await page.goto(server.url + "/" + path.basename(html) + "?mermaid=1");
      await ready(page);

      const node = page.locator("#commentRoot .mermaid svg g.node").first();
      await expect(node).toBeVisible({ timeout: 20000 });
      await node.hover();
      await page.locator("#mermaidAddBtn").click();
      const composer = page.locator(".cm-composer").last();
      await composer.locator("textarea").fill("mermaid to prune");
      await composer.locator('[data-act="save"]').click();
      await expect(composer).toHaveCount(0);

      const cid = await page.locator(".cm-card").first().getAttribute("data-cid");
      execFileSync(PYTHON, ["tools/authoring/mark_handled.py", html, cid], { cwd: SKILL });

      await page.reload();
      await ready(page);
      await expect(page.locator("#commentRoot .mermaid svg g.node").first()).toBeVisible({ timeout: 20000 });
      await expect(page.locator("#commentList")).not.toContainText("mermaid to prune");
      await expect(page.locator("#toolbarCount")).toHaveText("0");
      await expect(page.locator("#commentRoot .mermaid .cm-mermaid-hl")).toHaveCount(0);
      await expect(page.locator("#cmhAssetBanner")).toBeHidden();
    } finally {
      if (server) await server.close();
      if (dir) fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});

// A diagram authored inside a collapsible section must NOT be rendered by mermaid.run() while that
// section is collapsed (display:none): an in-place render measures a zero-size layout and produces a
// tiny, broken SVG (a degenerate ~16px viewBox with the nodes collapsed on top of each other) that
// never re-measures. The loader instead renders a hidden diagram off-screen with mermaid.render(),
// which measures in its own sandbox, so the diagram is laid out correctly AT LOAD - correct the moment
// its section is revealed on screen and also correct if the (collapsed) section is printed (CMH-MMD-07).
test.describe("mermaid diagram sizing (report / non-deck)", () => {
  const measure = () => {
    const svg = document.querySelector("#sec-diagram pre.mermaid svg");
    const vb = (svg.getAttribute("viewBox") || "").split(/\s+/).map(Number);
    const rects = [...svg.querySelectorAll("g.node")].map((n) => n.getBoundingClientRect());
    const left = Math.min(...rects.map((r) => r.left));
    const right = Math.max(...rects.map((r) => r.right));
    return { nodeCount: rects.length, viewBoxWidth: vb.length === 4 ? vb[2] : 0, nodeSpan: right - left };
  };
  test("CMH-MMD-07: a report diagram in a collapsed section is rendered correctly at load, before and after reveal", async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 900 });
    const content =
      '<section><h2>Intro</h2><p>lead-in prose so the content column is wide.</p></section>'
      + '<section class="cmh-section-collapsed" id="sec-diagram"><h2>Narrative arc</h2>'
      + '<pre class="mermaid cm-skip">flowchart LR\n'
      + '  A["Act 1<br/>The Gap"] --> B["Act 2<br/>Flagship"] --> C["Act 3<br/>Tour"]'
      + ' --> D["Act 4<br/>Dev"] --> E["Act 5<br/>Hood"] --> F["Act 6<br/>Close"]</pre></section>';
    const { dir } = stageContent(content, { key: "cmh-mmd-report-width", source: "report-width.html" });
    const server = await startStaticServer(dir);
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/test-doc.html");
      await ready(page);
      // The diagram is rendered off-screen at load even though its section is still collapsed, so its
      // nodes exist and are correctly laid out BEFORE any reveal (this is what makes it print-safe).
      await expect
        .poll(() => page.locator("#sec-diagram pre.mermaid svg g.node").count(), { timeout: 20000 })
        .toBe(6);
      const atLoad = await page.evaluate(measure);
      // A correctly laid-out 6-node flowchart has a wide, non-degenerate viewBox. The old
      // in-place-render-while-hidden bug produced a ~16px viewBox with the nodes collapsed on top of
      // each other, so this fails on the unfixed code. (nodeSpan is client-rect based and is 0 while
      // the section is display:none, so it is only meaningful after the reveal below.)
      expect(atLoad.nodeCount).toBe(6);
      expect(atLoad.viewBoxWidth).toBeGreaterThan(200);
      // Revealing the section keeps the (already-correct) diagram; its nodes now lay out spread wide.
      await page.locator("#sec-diagram .cmh-sec-caret").click();
      await expect(page.locator("#sec-diagram")).not.toHaveClass(/cmh-section-collapsed/);
      const afterReveal = await page.evaluate(measure);
      expect(afterReveal.nodeCount).toBe(6);
      expect(afterReveal.viewBoxWidth).toBeGreaterThan(200);
      expect(afterReveal.nodeSpan).toBeGreaterThan(200);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-MMD-07: many diagrams in collapsed sections all render correctly at load (serialized, no corruption)", async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 900 });
    const N = 10;
    let body = '<section><h2>Intro</h2><p>lead</p></section>';
    for (let i = 0; i < N; i++) {
      body += `<section class="cmh-section-collapsed" id="d${i}"><h2>Diagram ${i}</h2>`
        + `<pre class="mermaid cm-skip">flowchart LR\n  A${i}["Start ${i}"]-->B${i}["Middle ${i}"]-->C${i}["End ${i}"]</pre></section>`;
    }
    const { dir } = stageContent(body, { key: "cmh-mmd-many", source: "many-diagrams.html" });
    const server = await startStaticServer(dir);
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/test-doc.html");
      await ready(page);
      // Rendering many hidden diagrams at once must not corrupt any of them (mermaid shares internal
      // state, so the renders are serialized). Each must end up as a correct 3-node flowchart.
      await expect
        .poll(() => page.locator("pre.mermaid svg g.node").count(), { timeout: 30000 })
        .toBe(N * 3);
      const widths = await page.evaluate((n) => {
        const out = [];
        for (let i = 0; i < n; i++) {
          const svg = document.querySelector(`#d${i} pre.mermaid svg`);
          const vb = svg ? (svg.getAttribute("viewBox") || "").split(/\s+/).map(Number) : [];
          out.push(vb.length === 4 ? vb[2] : 0);
        }
        return out;
      }, N);
      // Every diagram is non-degenerate (the concurrent-render corruption produced ~16px error SVGs).
      expect(widths.every((w) => w > 200)).toBe(true);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-MMD-07: a malformed diagram in a collapsed section leaves no stray render node and does not break siblings", async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 900 });
    const content =
      '<section><h2>Intro</h2><p>lead</p></section>'
      + '<section class="cmh-section-collapsed" id="bad"><h2>Bad</h2>'
      + '<pre class="mermaid cm-skip">flowchart LR\n  A[[[ broken syntax )))</pre></section>'
      + '<section class="cmh-section-collapsed" id="good"><h2>Good</h2>'
      + '<pre class="mermaid cm-skip">flowchart LR\n  X[One]-->Y[Two]</pre></section>';
    const { dir } = stageContent(content, { key: "cmh-mmd-bad", source: "bad.html" });
    const server = await startStaticServer(dir);
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/test-doc.html");
      await ready(page);
      // The valid sibling still renders (one malformed diagram must not starve the serialized chain).
      await expect
        .poll(() => page.locator("#good pre.mermaid svg g.node").count(), { timeout: 20000 })
        .toBe(2);
      const state = await page.evaluate(() => ({
        badHasSvg: !!document.querySelector("#bad pre.mermaid svg"),
        // A mermaid diagram/error SVG (it carries g.node or an error marker) rendered OUTSIDE the
        // content root would be an orphan leaked into <body>; the off-screen clone is cleaned up so
        // there should be none, and the leftover render sandbox must also be gone.
        orphanDiagrams: [...document.querySelectorAll("svg")].filter(
          (s) => (s.querySelector("g.node") || s.getAttribute("aria-roledescription") === "error")
            && !s.closest("#commentRoot")).length,
        leftoverSandbox: document.querySelectorAll('body > div[style*="-99999px"]').length,
      }));
      // The malformed host stays as source text (no SVG), with no leaked orphan and no leftover sandbox.
      expect(state.badHasSvg).toBe(false);
      expect(state.orphanDiagrams).toBe(0);
      expect(state.leftoverSandbox).toBe(0);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-MMD-07: a revealed collapsed diagram is commentable and its markdown source is preserved", async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 900 });
    const content =
      '<section><h2>Intro</h2><p>lead</p></section>'
      + '<section class="cmh-section-collapsed" id="sec"><h2>Diagram</h2>'
      + '<pre class="mermaid cm-skip">flowchart LR\n  Alpha["Alpha node"]-->Beta["Beta node"]</pre></section>';
    const { dir } = stageContent(content, { key: "cmh-mmd-comment", source: "comment.html" });
    const server = await startStaticServer(dir);
    try {
      await routeMermaidLocal(page);
      await installClipboardCapture(page);
      await page.goto(server.url + "/test-doc.html");
      await ready(page);
      // The layer captures the diagram SOURCE (for Markdown export) before the off-screen render
      // replaces the element content, so a collapsed diagram still exports its source, not the SVG.
      const mdSrc = await page.locator("#sec pre.mermaid").getAttribute("data-cmh-md-src");
      expect(mdSrc).toContain("flowchart LR");
      expect(mdSrc).toContain("Alpha");
      // After reveal a node is commentable: hover shows the Add button and saving anchors a comment.
      await page.locator("#sec .cmh-sec-caret").click();
      await expect(page.locator("#sec pre.mermaid svg g.node").first()).toBeVisible({ timeout: 20000 });
      await page.locator("#sec pre.mermaid svg g.node").first().hover();
      await page.locator("#mermaidAddBtn").click();
      const composer = page.locator(".cm-composer").last();
      await composer.locator("textarea").fill("comment on a revealed collapsed diagram");
      await composer.locator('[data-act="save"]').click();
      await expect(composer).toHaveCount(0);
      await expect(page.locator("#commentList")).toContainText("comment on a revealed collapsed diagram");
      await expect(page.locator("#sec pre.mermaid .cm-mermaid-hl")).toHaveCount(1);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-MMD-07: a collapsed-section diagram is already rendered under print media (print-safe)", async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 900 });
    const content =
      '<section><h2>Intro</h2><p>lead</p></section>'
      + '<section class="cmh-section-collapsed" id="sec"><h2>Diagram</h2>'
      + '<pre class="mermaid cm-skip">flowchart LR\n  A["Act 1"]-->B["Act 2"]-->C["Act 3"]</pre></section>';
    const { dir } = stageContent(content, { key: "cmh-mmd-print", source: "print.html" });
    const server = await startStaticServer(dir);
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/test-doc.html");
      await ready(page);
      // The diagram is rendered off-screen at load, so it exists before any print, without expanding.
      await expect
        .poll(() => page.locator("#sec pre.mermaid svg g.node").count(), { timeout: 20000 })
        .toBe(3);
      // Print CSS reveals the collapsed section; the already-rendered diagram stays non-degenerate
      // (the old in-place-hidden render would print a ~16px broken graph or raw source).
      await page.emulateMedia({ media: "print" });
      const printVb = await page.evaluate(() => {
        const svg = document.querySelector("#sec pre.mermaid svg");
        const vb = (svg.getAttribute("viewBox") || "").split(/\s+/).map(Number);
        return { width: vb.length === 4 ? vb[2] : 0, nodes: svg.querySelectorAll("g.node").length };
      });
      expect(printVb.nodes).toBe(3);
      expect(printVb.width).toBeGreaterThan(200);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-MMD-07: a wide diagram revealed from a collapsed section is classified like a visible twin", async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 900 });
    let nodes = "flowchart LR\n";
    for (let i = 0; i < 12; i++) nodes += `  N${i}["Node ${i} label"]-->N${i + 1}["Node ${i + 1} label"]\n`;
    const content =
      `<section id="vis"><h2>Visible</h2><pre class="mermaid cm-skip">${nodes}</pre></section>`
      + `<section class="cmh-section-collapsed" id="hid"><h2>Hidden</h2><pre class="mermaid cm-skip">${nodes}</pre></section>`;
    const { dir } = stageContent(content, { key: "cmh-mmd-wideclass", source: "wideclass.html" });
    const server = await startStaticServer(dir);
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/test-doc.html");
      await ready(page);
      await expect
        .poll(() => page.locator("#vis pre.mermaid svg g.node").count(), { timeout: 20000 })
        .toBeGreaterThan(0);
      // Reveal the collapsed twin. Its wide/scroll classification is computed while collapsed against a
      // window-fallback width; the layer must recompute it on reveal so it matches the visible twin
      // (which is classified against the real content column). Same diagram -> same class.
      await page.locator("#hid .cmh-sec-caret").click();
      await expect(page.locator("#hid")).not.toHaveClass(/cmh-section-collapsed/);
      await expect
        .poll(async () => {
          const vis = await page.locator("#vis pre.mermaid").evaluate((el) => el.classList.contains("cmh-diagram-wide"));
          const hid = await page.locator("#hid pre.mermaid").evaluate((el) => el.classList.contains("cmh-diagram-wide"));
          return vis === hid;
        }, { timeout: 5000 })
        .toBe(true);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
