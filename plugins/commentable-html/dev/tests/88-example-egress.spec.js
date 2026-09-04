import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { EXAMPLES, fileUrl, ready, routeExampleLibsLocal } from "./helpers.js";

// CMH-BUILD-30: a spec that opens a shipped example must reach NOTHING. The examples load mermaid
// and Chart.js from a pinned CDN by design (CMH-SIZE-08/09), so such a spec is only hermetic if
// every one of those requests is answered locally. That was silently untrue: the export-scoped
// helper routes the UMD `mermaid.min.js` the Offline export downloads, while the VIEWER imports
// `mermaid.esm.min.mjs`, so two specs fetched mermaid (and its ~20 chunks) from jsDelivr on every
// run and a diagram could land after their measurements (#1305).
//
// `routeExampleLibsLocal` is the one supported way to open a shipped example. This sweep drives
// every shipped example through it and pins both halves of the promise: mermaid renders from the
// local copy, and nothing else escapes to the network - so a library added to an example later, or
// a local route that stops matching after a version bump, fails here rather than turning into a
// timing flake.
const DOCS = fs.readdirSync(EXAMPLES).filter((f) => f.endsWith(".html")).sort();

// A denial is allowed only where NO local copy could satisfy the request's `integrity` pin: the
// vendored Chart.js is the MINIFIED `chart.umd.min.js`, so a document pinned to the unminified
// `chart.umd.js` (what `tools/blocks/chart_block.py` emits) cannot be served without failing SRI
// and blanking the canvas anyway. Aborting is the honest outcome there - `tools/chartjs_pin.mjs`
// argues the same for the tutorial capture's route. Everything else would be real egress.
const UNSERVEABLE = /^https:\/\/cdn\.jsdelivr\.net\/npm\/chart\.js@[^/]+\/dist\/chart\.umd\.js$/;

test.describe("a spec that opens a shipped example reaches no network (CMH-BUILD-30)", () => {
  for (const name of DOCS) {
    test(`${name} serves its vendored libraries locally and reaches nothing (CMH-BUILD-30)`, async ({ page }) => {
      const file = path.join(EXAMPLES, name);
      const asked = [];
      page.on("request", (r) => {
        if (/^https?:\/\//.test(r.url())) asked.push(r.url());
      });

      await routeExampleLibsLocal(page);
      await page.goto(fileUrl(file));
      await ready(page);

      const hasDiagram = await page.evaluate(() => !!document.querySelector("pre.mermaid, div.mermaid"));
      // Mermaid's entry point pulls its own chunks after it loads, so wait for the requests to stop
      // arriving rather than for a fixed delay.
      let seen = -1;
      for (let i = 0; i < 40 && seen !== asked.length; i += 1) {
        seen = asked.length;
        await page.waitForTimeout(250);
      }

      expect((page.__external || []).filter((u) => /mermaid/.test(u)),
        "every mermaid request is answered locally").toEqual([]);
      expect((page.__external || []).filter((u) => !UNSERVEABLE.test(u)),
        `${name} asked for something no local copy answered`).toEqual([]);

      if (hasDiagram) {
        const mermaidAsked = asked.filter((u) => /\/npm\/mermaid@[^/]+\/dist\//.test(u));
        expect(mermaidAsked.length, "the viewer imported mermaid, so the sweep is not vacuous").toBeGreaterThan(0);
        expect(mermaidAsked.some((u) => /mermaid\.esm\.min\.mjs$/.test(u)),
          "the viewer's ESM entry point is what was requested").toBe(true);
        // Rendering is the proof the local bytes were usable, not merely that the URL was matched.
        // Presence, not visibility: a deck renders its diagrams on slides that are not the active
        // one, so the SVG is legitimately hidden there.
        await expect.poll(() => page.locator("pre.mermaid svg, div.mermaid svg").count(), { timeout: 15000 })
          .toBeGreaterThan(0);
      }
    });
  }
});
