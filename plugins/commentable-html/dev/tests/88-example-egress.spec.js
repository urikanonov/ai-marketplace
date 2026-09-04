import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { DEV, EXAMPLES, fileUrl, ready, awaitMermaidRendered, routeExampleLibsLocal } from "./helpers.js";

// CMH-BUILD-30: a spec that opens a shipped example must reach NOTHING. The examples load mermaid
// and Chart.js from a pinned CDN by design (CMH-SIZE-08/09), so such a spec is only hermetic if
// every one of those requests is answered locally. That was silently untrue: the export-scoped
// helper routes the UMD `mermaid.min.js` the Offline export downloads, while the VIEWER imports
// `mermaid.esm.min.mjs`, so specs fetched mermaid (and its ~20 chunks) from jsDelivr on every run
// and a diagram could land after their measurements (#1305).
//
// `routeExampleLibsLocal` is the one supported way to open a shipped example. This file pins both
// halves of that: the SWEEP drives every shipped example through the helper and proves nothing
// escapes, and the STATIC guard at the bottom proves every other spec that opens an example
// installs a hermetic deny-all - the sweep alone cannot see how other specs open these documents,
// which is how two specs kept fetching from the CDN after the helper itself was fixed.
const DOCS = fs.readdirSync(EXAMPLES).filter((f) => f.endsWith(".html")).sort();

// Every URL a shipped example is ALLOWED to ask for, and where it must come from.
const MERMAID_DIST = /^https:\/\/cdn\.jsdelivr\.net\/npm\/mermaid@[^/]+\/dist\//;
const CHART_VENDORED = /^https:\/\/cdn\.jsdelivr\.net\/npm\/chart\.js@[^/]+\/dist\/chart\.umd\.min\.js$/;

// A DENIAL is permitted only where NO local copy could satisfy the request's `integrity` pin: the
// vendored Chart.js is the MINIFIED `chart.umd.min.js`, so a document pinned to the unminified
// `chart.umd.js` (what `tools/blocks/chart_block.py` emits) cannot be served without failing SRI
// and blanking the canvas anyway. Aborting is the honest outcome there - `tools/chartjs_pin.mjs`
// argues the same for the tutorial capture's route. Parsed rather than pattern-matched so a query
// string or a floating tag cannot smuggle another URL through this hole.
function isUnserveableChartPin(url) {
  let u;
  try { u = new URL(url); } catch (e) { return false; }
  return u.protocol === "https:" && u.host === "cdn.jsdelivr.net" && !u.search && !u.hash
    && /^\/npm\/chart\.js@\d+\.\d+\.\d+\/dist\/chart\.umd\.js$/.test(u.pathname);
}

test.describe("a spec that opens a shipped example reaches no network (CMH-BUILD-30)", () => {
  test("the sweep covers every shipped example (CMH-BUILD-30)", () => {
    // A directory rename or a moved build output would otherwise leave this file generating zero
    // tests, and a guard that quietly stops running is worse than no guard.
    expect(DOCS.length, "shipped examples were discovered to sweep").toBeGreaterThanOrEqual(5);
    expect(DOCS.filter((f) => f.startsWith("report-")).length,
      "the shipped example reports are in the sweep").toBeGreaterThanOrEqual(4);
    expect(DOCS, "the showcase deck is in the sweep").toContain("deck-showcase.html");
  });

  for (const name of DOCS) {
    test(`${name} serves its vendored libraries locally and reaches nothing (CMH-BUILD-30)`, async ({ page }) => {
      // The document load, every library request, mermaid's serialized renders and its render
      // audits all happen inside this one test, so it needs a real budget rather than the default.
      test.setTimeout(90000);
      const file = path.join(EXAMPLES, name);
      const asked = [];
      page.on("request", (r) => {
        if (/^https?:\/\//.test(r.url())) asked.push(r.url());
      });

      await routeExampleLibsLocal(page);
      await page.goto(fileUrl(file));
      await ready(page);

      // Fail CLOSED on the recorder itself. Every assertion below reads `page.__external`, so if
      // the deny-all ever stopped being installed, an `|| []` fallback would turn "nothing was
      // denied" into "nothing was recorded" and the guard would pass while the page fetched from
      // the live CDN.
      expect(Array.isArray(page.__external),
        "routeExampleLibsLocal installed the recording deny-all").toBe(true);

      // Wait for the WHOLE load, not just for `ready`: the layer sets `__commentableHtmlReady` from
      // a classic inline script during parsing, while the mermaid import lives in a deferred module
      // that runs afterwards and then pulls its own chunks. Asserting before that finishes would
      // leave every render-triggered request outside the assertion window.
      const hasDiagram = await page.evaluate(() => !!document.querySelector("pre.mermaid, div.mermaid"));
      if (hasDiagram) await awaitMermaidRendered(page);
      let seen = -1;
      for (let i = 0; i < 40 && seen !== asked.length; i += 1) {
        seen = asked.length;
        await page.waitForTimeout(250);
      }

      // Nothing escaped: every request was answered from a local copy, except the one denial no
      // local copy can satisfy.
      expect(page.__external.filter((u) => !isUnserveableChartPin(u)),
        `${name} asked for something no local copy answered`).toEqual([]);
      expect(page.__external.filter((u) => /mermaid/.test(u)),
        "every mermaid request is answered locally").toEqual([]);
      // A library added to an example later would otherwise be silently tolerated the moment it
      // happened to be denied rather than served.
      expect(asked.filter((u) => !MERMAID_DIST.test(u) && !CHART_VENDORED.test(u) && !isUnserveableChartPin(u)),
        `${name} requested a library this guard does not know how to serve locally`).toEqual([]);

      if (hasDiagram) {
        const mermaidAsked = asked.filter((u) => MERMAID_DIST.test(u));
        expect(mermaidAsked.length, "the viewer imported mermaid, so the sweep is not vacuous").toBeGreaterThan(0);
        expect(mermaidAsked.some((u) => /mermaid\.esm\.min\.mjs$/.test(u)),
          "the viewer's ESM entry point is what was requested").toBe(true);
        // Rendering EVERY diagram is the proof the local bytes were usable, not merely that the
        // URL was matched: one rendered diagram would still pass with a chunk missing. Presence,
        // not visibility - a deck renders its diagrams on slides that are not the active one.
        const hosts = await page.locator("pre.mermaid, div.mermaid").count();
        expect(await page.locator("pre.mermaid svg, div.mermaid svg").count(),
          "every diagram rendered from the local copy").toBe(hosts);
      }
    });
  }

  test("every spec that opens a shipped example installs a hermetic deny-all (CMH-BUILD-30)", () => {
    // The sweep above proves the HELPER is complete; it cannot see how OTHER specs open these same
    // documents. That gap is the actual #1305 defect, so it is checked here at the source level.
    // This is a net, not a proof (it cannot tell a conditional call from an unconditional one), so
    // keep the call unconditional in the spec you write.
    const dir = path.join(DEV, "tests");
    const HERMETIC = ["routeExampleLibsLocal(", "routeMermaidLocal(", "denyExternalNetwork("];
    const shipped = new Set(DOCS);
    const offenders = [];
    for (const f of fs.readdirSync(dir).filter((f) => f.endsWith(".spec.js")).sort()) {
      if (f === path.basename(new URL(import.meta.url).pathname)) continue;
      const src = fs.readFileSync(path.join(dir, f), "utf8");
      // Require BOTH the shipped examples DIRECTORY and a shipped example's filename, so a staged
      // fixture or a download's `suggestedFilename` that merely looks like `report-*.html` is not
      // mistaken for one of these documents.
      const usesExamplesDir = /\bEXAMPLES\b/.test(src) || /["']examples["']/.test(src) || /\/examples\//.test(src);
      const namesShipped = [...shipped].some((d) => src.includes(d));
      if (!(/\.goto\(/.test(src) && usesExamplesDir && namesShipped)) continue;
      // A spec may instead install its own catch-all deny (the offline-export specs do).
      const ownCatchAll = /route\(\s*\/\^https\?/.test(src);
      if (ownCatchAll || HERMETIC.some((h) => src.includes(h))) continue;
      offenders.push(f);
    }
    expect(offenders, "these specs open a shipped example without routing its CDN libraries locally").toEqual([]);
  });
});
