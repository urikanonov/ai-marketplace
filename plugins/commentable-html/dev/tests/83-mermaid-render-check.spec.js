import { test, expect } from "@playwright/test";
import fs from "fs";
import {
  ready, startStaticServer, stageContent, routeMermaidLocal, PLUGIN,
} from "./helpers.js";

// CMH-MMD-12: a report diagram is verified AFTER mermaid renders it. Two invariants are measured -
// every label's laid-out box fits the box that was sized for it (an HTML label inside its
// <foreignObject>, an SVG <text> label inside its node shape), and the drawn content (getBBox)
// actually fills the SVG's viewBox - and a diagram that fails either is repaired once by re-rendering
// that single host with htmlLabels:false (the deck-proven path that cannot re-flow) plus, if the
// bounds are still wrong, a viewBox re-fit to the measured content bbox.

// The reported failure shape: a wide flowchart whose nodes carry multi-line HTML labels. The <br/>
// line breaks matter - mermaid reads the diagram source from innerHTML, so a repair that re-rendered
// from textContent would silently collapse these labels to one line.
const DIAGRAM =
  '<section><h2>Pipeline</h2><p>lead-in prose so the content column is wide.</p>'
  + '<pre class="mermaid cm-skip">flowchart LR\n'
  + '  A["Source sensor"] --> B["Ingest queue / front end"]\n'
  + '  B --> C["Preprocessor<br/>(stamps attributes)"]\n'
  + '  C --> D["Consumer job<br/>(shared filtering code)"]\n'
  + '  D --> E["Role one<br/>Bucket: Store A tag<br/>queue: queue-a"]\n'
  + '  D --> F["Role two<br/>Bucket: Store B tag<br/>queue: queue-b"]\n'
  + '  E --> H["Store A<br/>query surface"]\n'
  + '  F --> I["Store B"]</pre></section>';

// Measured independently of the runtime helpers, so the spec cannot pass just because the runtime
// agrees with itself. `overflow` is the worst laid-out label box minus the box sized for it, in SVG
// user units (HTML labels via the screen-CTM scale, SVG <text> labels directly against their node
// shape). `fill` is how much of the viewBox the drawn content actually covers per axis, using the
// INTERSECTION of the content bbox with the viewBox and allowing 24 user units for mermaid's own
// 8-unit inset. `bounded` is false when the SVG's bounds could not be measured at all, so an
// unmeasurable diagram can never satisfy the bounds invariant vacuously.
const MEASURE = () => {
  const out = [];
  document.querySelectorAll("#commentRoot .mermaid").forEach((host) => {
    const svg = host.querySelector("svg");
    if (!svg) return;
    const ctm = svg.getScreenCTM && svg.getScreenCTM();
    const scale = ctm && isFinite(ctm.a) && ctm.a > 0 ? ctm.a : 1;
    let overflow = 0;
    let boxesSeen = 0;
    svg.querySelectorAll("foreignObject").forEach((fo) => {
      const bw = fo.width && fo.width.baseVal ? fo.width.baseVal.value : 0;
      const bh = fo.height && fo.height.baseVal ? fo.height.baseVal.value : 0;
      const kid = fo.firstElementChild;
      if (!kid || !(bw > 0) || !(bh > 0)) return;
      const r = kid.getBoundingClientRect();
      if (!(r.width > 0) && !(r.height > 0)) return;
      boxesSeen += 1;
      overflow = Math.max(overflow, r.width / scale - bw, r.height / scale - bh);
    });
    svg.querySelectorAll("g.node").forEach((node) => {
      if (node.querySelector("foreignObject")) return;
      const label = node.querySelector(":scope > g.label text");
      const shape = node.querySelector(":scope > rect, :scope > polygon, :scope > circle, :scope > ellipse");
      if (!label || !shape || !label.getBBox || !shape.getBBox) return;
      let lb, sb;
      try { lb = label.getBBox(); sb = shape.getBBox(); } catch (e) { return; }
      if (!(sb.width > 0) || !(lb.width > 0)) return;
      boxesSeen += 1;
      overflow = Math.max(overflow, lb.width - sb.width, lb.height - sb.height);
    });
    const vb = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
    let fillW = 0, fillH = 0, bounded = false;
    try {
      const box = svg.getBBox();
      if (vb.length === 4 && vb.every(isFinite) && vb[2] > 0 && vb[3] > 0 && box.width > 0 && box.height > 0) {
        const ow = Math.max(0, Math.min(box.x + box.width, vb[0] + vb[2]) - Math.max(box.x, vb[0]));
        const oh = Math.max(0, Math.min(box.y + box.height, vb[1] + vb[3]) - Math.max(box.y, vb[1]));
        fillW = (ow + 24) / vb[2];
        fillH = (oh + 24) / vb[3];
        bounded = true;
      }
    } catch (e) { /* not laid out */ }
    out.push({
      overflow,
      fillW,
      fillH,
      // The bounds are measurable for every laid-out diagram; label boxes are not (a sequence or
      // gantt diagram has neither a <foreignObject> nor a g.node), so they are counted rather than
      // required per diagram - the corpus-level assertion below is what stops a vacuous pass.
      bounded,
      labelBoxes: boxesSeen,
      foreignObjects: svg.querySelectorAll("foreignObject").length,
      nodes: svg.querySelectorAll("g.node").length,
    });
  });
  return out;
};

// Every node label's rendered rows joined by "|", so a lost <br/> - which would merge two authored
// lines into one - is directly visible in both label modes.
const NODE_LABEL_LINES = () => {
  const svg = document.querySelector("#commentRoot .mermaid svg");
  return [...svg.querySelectorAll("g.node")].map((n) => {
    const rows = n.querySelectorAll("tspan.text-outer-tspan, foreignObject p, foreignObject br");
    if (!rows.length) return (n.textContent || "").trim();
    const parts = [...rows]
      .filter((r) => r.tagName.toLowerCase() !== "br")
      .map((r) => (r.textContent || "").trim())
      .filter(Boolean);
    // A <br/> inside a single <p> is a line break with no extra element to read, so count it too.
    const brs = n.querySelectorAll("foreignObject br").length;
    return parts.length > 1 || brs > 0 ? parts.join("|") + (brs > 0 && parts.length <= 1 ? "|" : "") : parts.join("|");
  }).filter(Boolean);
};

async function stageAndServe(key, source) {
  const { dir } = stageContent(DIAGRAM, { key, source });
  const server = await startStaticServer(dir);
  return { dir, server };
}

test.describe("mermaid render self-check (CMH-MMD-12)", () => {
  test("CMH-MMD-12: a report diagram with under-sized label boxes and an inflated viewBox is repaired once", async ({ page }) => {
    test.setTimeout(120000);
    await page.setViewportSize({ width: 1280, height: 900 });
    const { dir, server } = await stageAndServe("cmh-mmd-selfcheck", "self-check.html");
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/test-doc.html");
      await ready(page);
      await expect
        .poll(() => page.locator("#commentRoot .mermaid svg g.node").count(), { timeout: 30000 })
        .toBeGreaterThanOrEqual(8);

      // The healthy render satisfies both invariants and needed no repair.
      const before = await page.evaluate(MEASURE);
      expect(before.length).toBe(1);
      expect(before[0].bounded).toBe(true);
      expect(before[0].foreignObjects).toBeGreaterThan(0);
      expect(before[0].overflow).toBeLessThan(4);
      expect(Math.min(before[0].fillW, before[0].fillH)).toBeGreaterThan(0.8);
      expect(await page.evaluate(() => window.__cmhMermaidRepairs)).toBe(0);

      // The measurement is scale-invariant: narrowing the column CSS-scales the diagram down, and a
      // healthy render must still measure as fitting (otherwise the check would repair good
      // diagrams). Checked at a moderate and at a hard shrink, since the conversion from client px
      // back to SVG user units is where a scale-sensitive measure would break down.
      for (const width of [900, 560]) {
        await page.setViewportSize({ width, height: 900 });
        await page.waitForTimeout(400);
        await page.evaluate(() => window.__cmhMermaidAuditsSettled);
        const scaled = await page.evaluate(MEASURE);
        expect(scaled[0].bounded).toBe(true);
        expect(scaled[0].overflow, `a CSS-scaled healthy diagram still fits at ${width}px`).toBeLessThan(4);
        expect(await page.evaluate(() => window.__cmhMermaidRepairs), `a rescale to ${width}px does not repair a healthy diagram`).toBe(0);
      }
      await page.setViewportSize({ width: 1280, height: 900 });
      await page.waitForTimeout(400);

      // The authored <br/> line breaks are present before the repair.
      const linesBefore = await page.evaluate(NODE_LABEL_LINES);
      expect(linesBefore.some((l) => l.includes("|")), "multi-line labels render as separate rows").toBe(true);

      // A node comment anchored before the repair must survive it: the repair replaces the SVG, so
      // the ring has to be re-applied to the freshly rendered node.
      await page.locator("#commentRoot .mermaid svg g.node").first().hover();
      await expect(page.locator("#mermaidAddBtn")).toBeVisible();
      await page.locator("#mermaidAddBtn").click();
      const composer = page.locator(".cm-composer").last();
      await composer.locator("textarea").fill("check this node after the repair");
      await composer.locator('[data-act="save"]').click();
      await expect(page.locator("#commentRoot .mermaid .cm-mermaid-hl")).toHaveCount(1);

      // Force the reported failure onto the rendered SVG: halve every label box so the labels no
      // longer fit, and double the viewBox so the drawn content occupies a quarter of it.
      await page.evaluate(() => {
        const svg = document.querySelector("#commentRoot .mermaid svg");
        svg.querySelectorAll("foreignObject").forEach((fo) => {
          fo.setAttribute("width", String(fo.width.baseVal.value / 2));
          fo.setAttribute("height", String(fo.height.baseVal.value / 2));
        });
        const vb = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
        svg.setAttribute("viewBox", `0 0 ${vb[2] * 2} ${vb[3] * 2}`);
      });
      const broken = await page.evaluate(MEASURE);
      expect(broken[0].overflow).toBeGreaterThan(4);
      expect(Math.max(broken[0].fillW, broken[0].fillH)).toBeLessThan(0.7);

      // The self-check repairs it: one bounded re-render of THIS host with SVG <text> labels.
      const repaired = await page.evaluate(async () => {
        const host = document.querySelector("#commentRoot .mermaid");
        return await window.__cmhMermaidAudit(host);
      });
      expect(repaired).toBe(true);
      expect(await page.evaluate(() => window.__cmhMermaidRepairs)).toBe(1);

      const after = await page.evaluate(MEASURE);
      expect(after[0].bounded).toBe(true);
      expect(after[0].nodes).toBeGreaterThanOrEqual(8);
      // htmlLabels:false: labels are SVG <text>, which scale with the diagram and never re-flow.
      expect(after[0].foreignObjects).toBe(0);
      // The SVG-<text> arm of the measure actually compared boxes here - without that the
      // post-repair "does it still clip" comparison would be measuring nothing.
      expect(after[0].labelBoxes, "the SVG <text> label measure compared real boxes").toBeGreaterThanOrEqual(8);
      expect(after[0].overflow).toBeLessThan(4);
      expect(Math.min(after[0].fillW, after[0].fillH)).toBeGreaterThan(0.8);

      // The repair re-rendered the AUTHORED diagram: every <br/> line break is still a line break.
      // Compared by COUNT, not "at least one survived", so a partial collapse fails too.
      const linesAfter = await page.evaluate(NODE_LABEL_LINES);
      const multiBefore = linesBefore.filter((l) => l.includes("|")).length;
      const multiAfter = linesAfter.filter((l) => l.includes("|")).length;
      expect(multiBefore, "the fixture has several multi-line labels").toBeGreaterThanOrEqual(4);
      expect(multiAfter, "the repair kept every authored <br/> line break").toBe(multiBefore);
      expect(linesAfter.join(" ")).toContain("Preprocessor");

      // The node comment still rings a node after the repair.
      await expect(page.locator("#commentRoot .mermaid .cm-mermaid-hl")).toHaveCount(1);
      await expect(page.locator("#commentList")).toContainText("check this node after the repair");

      // The repair is bounded to one attempt per diagram: a second audit does nothing.
      const again = await page.evaluate(async () => {
        const host = document.querySelector("#commentRoot .mermaid");
        return await window.__cmhMermaidAudit(host);
      });
      expect(again).toBe(false);
      expect(await page.evaluate(() => window.__cmhMermaidRepairs)).toBe(1);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-MMD-12: a diagram that goes bad after load is repaired through the automatic resize path", async ({ page }) => {
    test.setTimeout(120000);
    await page.setViewportSize({ width: 1280, height: 900 });
    const { dir, server } = await stageAndServe("cmh-mmd-auto", "auto.html");
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/test-doc.html");
      await ready(page);
      await expect
        .poll(() => page.locator("#commentRoot .mermaid svg g.node").count(), { timeout: 30000 })
        .toBeGreaterThanOrEqual(8);
      await page.evaluate(() => window.__cmhMermaidReady);
      await page.evaluate(() => window.__cmhMermaidAuditsSettled);
      expect(await page.evaluate(() => window.__cmhMermaidRepairs)).toBe(0);

      // Break the rendered SVG, then let the RUNTIME notice it on its own. Nothing here calls the
      // automation hook: the repair has to come through the production wiring (the reveal/resize
      // ResizeObserver -> maybeAuditMermaidRender re-arm on a material scale change), so removing or
      // breaking that wiring fails this test even though the direct-hook specs would still pass.
      await page.evaluate(() => {
        const svg = document.querySelector("#commentRoot .mermaid svg");
        svg.querySelectorAll("foreignObject").forEach((fo) => {
          fo.setAttribute("width", String(fo.width.baseVal.value / 2));
          fo.setAttribute("height", String(fo.height.baseVal.value / 2));
        });
        const vb = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
        svg.setAttribute("viewBox", `0 0 ${vb[2] * 2} ${vb[3] * 2}`);
      });
      await page.setViewportSize({ width: 860, height: 900 });

      await expect
        .poll(async () => {
          await page.evaluate(() => window.__cmhMermaidAuditsSettled);
          return page.evaluate(() => window.__cmhMermaidRepairs);
        }, { timeout: 30000 })
        .toBe(1);
      const after = await page.evaluate(MEASURE);
      expect(after[0].bounded).toBe(true);
      expect(after[0].foreignObjects).toBe(0);
      expect(after[0].nodes).toBeGreaterThanOrEqual(8);
      expect(after[0].overflow).toBeLessThan(4);
      expect(Math.min(after[0].fillW, after[0].fillH)).toBeGreaterThan(0.8);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-MMD-12: a re-render that comes out worse is rolled back to the original SVG", async ({ page }) => {
    test.setTimeout(120000);
    await page.setViewportSize({ width: 1280, height: 900 });
    const { dir, server } = await stageAndServe("cmh-mmd-rollback", "rollback.html");
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/test-doc.html");
      await ready(page);
      await expect
        .poll(() => page.locator("#commentRoot .mermaid svg g.node").count(), { timeout: 30000 })
        .toBeGreaterThanOrEqual(8);

      // Break the render, then make the repair hook install a DELIBERATELY WORSE SVG. Two variants,
      // so each arm of the keep/rollback comparison is exercised on its own: `lost-content` trips
      // the node-count arm, and `same-nodes-worse-fill` keeps every node but strands the content in
      // a huge viewBox, so the FILL comparison is what has to force the rollback.
      const run = async (variant) => page.evaluate(async (kind) => {
        const host = document.querySelector("#commentRoot .mermaid");
        const original = host.querySelector("svg");
        const originalNodes = host.querySelectorAll("g.node").length;
        original.querySelectorAll("foreignObject").forEach((fo) => {
          fo.setAttribute("width", String(fo.width.baseVal.value / 2));
        });
        const ns = "http://www.w3.org/2000/svg";
        window.__cmhMermaidRerender = (el) => {
          const svg = document.createElementNS(ns, "svg");
          svg.setAttribute("viewBox", "0 0 6000 6000");
          const nodes = kind === "lost-content" ? 1 : originalNodes;
          for (let i = 0; i < nodes; i++) {
            const g = document.createElementNS(ns, "g");
            g.setAttribute("class", "node");
            const r = document.createElementNS(ns, "rect");
            r.setAttribute("x", String(i * 12));
            r.setAttribute("width", "40");
            r.setAttribute("height", "20");
            g.appendChild(r);
            svg.appendChild(g);
          }
          el.textContent = "";
          el.appendChild(svg);
          return Promise.resolve(true);
        };
        const repaired = await window.__cmhMermaidAudit(host);
        return {
          repaired,
          sameSvg: host.querySelector("svg") === original,
          nodes: host.querySelectorAll("g.node").length,
          originalNodes,
          repairs: window.__cmhMermaidRepairs,
        };
      }, variant);

      for (const variant of ["lost-content", "same-nodes-worse-fill"]) {
        const result = await run(variant);
        expect(result.repaired, `${variant}: a worse re-render is not accepted as a repair`).toBe(false);
        expect(result.sameSvg, `${variant}: the original SVG node is put back`).toBe(true);
        expect(result.nodes, `${variant}: no node is lost`).toBe(result.originalNodes);
        expect(result.repairs, `${variant}: a rolled-back attempt is not counted as a repair`).toBe(0);
        // The one attempt is spent, so re-arm the guard to exercise the next variant.
        await page.evaluate(() => {
          document.querySelector("#commentRoot .mermaid")._cmhMmdRepairTried = false;
        });
      }
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("CMH-MMD-12: with no re-render hook a diagram keeps its original render", async ({ page }) => {
    test.setTimeout(120000);
    await page.setViewportSize({ width: 1280, height: 900 });
    const { dir, server } = await stageAndServe("cmh-mmd-selfcheck-fail", "self-check-fail.html");
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/test-doc.html");
      await ready(page);
      await expect
        .poll(() => page.locator("#commentRoot .mermaid svg g.node").count(), { timeout: 30000 })
        .toBeGreaterThanOrEqual(8);

      // With the re-render hook unavailable the label repair cannot run; the original SVG must
      // survive untouched rather than being blanked or left half-replaced.
      const result = await page.evaluate(async () => {
        const host = document.querySelector("#commentRoot .mermaid");
        const svgBefore = host.querySelector("svg");
        host.querySelectorAll("foreignObject").forEach((fo) => {
          fo.setAttribute("width", String(fo.width.baseVal.value / 2));
        });
        const saved = window.__cmhMermaidRerender;
        window.__cmhMermaidRerender = null;
        const repaired = await window.__cmhMermaidAudit(host);
        window.__cmhMermaidRerender = saved;
        return {
          repaired,
          sameSvg: host.querySelector("svg") === svgBefore,
          nodes: host.querySelectorAll("g.node").length,
          repairs: window.__cmhMermaidRepairs,
        };
      });
      expect(result.repaired).toBe(false);
      expect(result.sameSvg).toBe(true);
      expect(result.nodes).toBeGreaterThanOrEqual(8);
      expect(result.repairs).toBe(0);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
  test("CMH-MMD-12: diagram families that render SVG text labels natively are not false-positived", async ({ page }) => {
    test.setTimeout(120000);
    await page.setViewportSize({ width: 1280, height: 900 });
    // class / state / ER diagrams lay their text out against composite or path-backed shapes rather
    // than a single tight-fitting node box, and sequence / gantt / pie place free text with no
    // owning shape at all. The SVG-<text> label measure must leave all of them alone: a false
    // positive here would re-render a healthy diagram and throw away its richer HTML labels.
    const content =
      '<section><h2>Families</h2><p>lead-in prose so the content column is wide.</p>'
      + '<pre class="mermaid cm-skip" id="d-class">classDiagram\n'
      + '  class IngestQueue {\n    +String topicName\n    +int partitions\n    +publish(payload)\n  }\n'
      + '  class Preprocessor {\n    +stampAttributes()\n  }\n'
      + '  IngestQueue --> Preprocessor</pre>'
      + '<pre class="mermaid cm-skip" id="d-state">stateDiagram-v2\n'
      + '  [*] --> AwaitingReview\n  AwaitingReview --> ChangesRequested: reviewer comments\n'
      + '  ChangesRequested --> AwaitingReview: author pushes\n  AwaitingReview --> [*]</pre>'
      + '<pre class="mermaid cm-skip" id="d-er">erDiagram\n'
      + '  REPORT ||--o{ COMMENT : carries\n  COMMENT }o--|| REVIEWER : "written by"</pre>'
      + '<pre class="mermaid cm-skip" id="d-seq">sequenceDiagram\n'
      + '  participant Author\n  participant Reviewer\n  Author->>Reviewer: sends the report\n'
      + '  Reviewer-->>Author: leaves a comment</pre>'
      + '<pre class="mermaid cm-skip" id="d-flow">flowchart TB\n'
      + '  A["Draft"] --> B["Review"] --> C["Ship"]</pre></section>';
    const { dir } = stageContent(content, { key: "cmh-mmd-families", source: "families.html" });
    const server = await startStaticServer(dir);
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/test-doc.html");
      await ready(page);
      await expect
        .poll(() => page.evaluate(() => document.querySelectorAll("#commentRoot .mermaid svg").length), { timeout: 30000 })
        .toBe(5);
      await page.evaluate(() => window.__cmhMermaidReady);
      await page.evaluate(() => window.__cmhMermaidAuditsSettled);

      const measured = await page.evaluate(MEASURE);
      expect(measured.length).toBe(5);
      for (const m of measured) {
        expect(m.bounded).toBe(true);
        expect(m.overflow, "no diagram family false-positives the label measure").toBeLessThan(4);
        expect(Math.min(m.fillW, m.fillH)).toBeGreaterThan(0.7);
      }
      expect(await page.evaluate(() => window.__cmhMermaidRepairs), "no family is repaired").toBe(0);
    } finally {
      await server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});

// The shipped example reports are the standing proof that the invariants hold on real content AND
// that the self-check does not false-positive on a healthy render (zero repairs fired).
const EXAMPLE_REPORTS = fs
  .readdirSync(`${PLUGIN}/examples`)
  .filter((f) => /^report-.*\.html$/.test(f))
  .sort();

test.describe("shipped example reports satisfy the mermaid render invariants (CMH-MMD-12)", () => {
  test("CMH-MMD-12: every shipped example report renders its diagrams with fitting labels and honest bounds, and fires no repair", async ({ page }) => {
    test.setTimeout(240000);
    await page.setViewportSize({ width: 1280, height: 900 });
    const server = await startStaticServer(PLUGIN);
    const seen = [];
    let diagrams = 0;
    let labelBoxes = 0;
    try {
      await routeMermaidLocal(page);
      for (const file of EXAMPLE_REPORTS) {
        await page.goto(`${server.url}/examples/${file}`);
        await ready(page);
        const hosts = await page.locator("#commentRoot .mermaid").count();
        if (!hosts) continue;
        await expect
          .poll(() => page.evaluate(() => document.querySelectorAll("#commentRoot .mermaid svg").length), { timeout: 30000 })
          .toBe(hosts);
        // Await the RENDER chain and then every audit issued off it, so the repair counter is read
        // after the self-check has settled rather than racing it.
        await page.evaluate(() => window.__cmhMermaidReady);
        await page.evaluate(() => window.__cmhMermaidAuditsSettled);
        const measured = await page.evaluate(MEASURE);
        expect(measured.length, `rendered diagram count in ${file}`).toBe(hosts);
        for (const m of measured) {
          expect(m.bounded, `a diagram in ${file} has no measurable bounds`).toBe(true);
          expect(m.overflow, `label overflow in ${file}`).toBeLessThan(4);
          // Mirror the runtime rule (an under-fill in BOTH axes is what counts as broken) and, on
          // top of it, require one axis to be well filled. The worst healthy axis pair across the
          // shipped examples is 0.88 / 0.96, so this has real margin and never contradicts the
          // runtime's own MMD_FILL_MIN of 0.7.
          expect(Math.min(m.fillW, m.fillH), `viewBox fill in ${file}`).toBeGreaterThan(0.7);
          expect(Math.max(m.fillW, m.fillH), `best-axis viewBox fill in ${file}`).toBeGreaterThan(0.8);
          diagrams += 1;
          labelBoxes += m.labelBoxes;
        }
        // No false positives: a healthy shipped report is never re-rendered by the self-check.
        expect(await page.evaluate(() => window.__cmhMermaidRepairs), `repairs fired in ${file}`).toBe(0);
        seen.push(file);
      }
      // The invariant has to have been exercised on real shipped content, not skipped away: real
      // reports, real diagrams, and a real population of label boxes actually compared.
      expect(seen.length, "example reports carrying a diagram").toBeGreaterThanOrEqual(3);
      expect(diagrams, "diagrams actually measured").toBeGreaterThanOrEqual(10);
      expect(labelBoxes, "label boxes actually compared").toBeGreaterThanOrEqual(50);
    } finally {
      await server.close();
    }
  });
});
