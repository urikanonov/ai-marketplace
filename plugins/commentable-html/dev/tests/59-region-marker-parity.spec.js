import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { openInline } from "./helpers.js";

// CMH-VAL-22: the runtime's region locator (_cmhRegionMarkerMatches, assets/js/67-export-standalone.js)
// and the three Python copies of the same rule must answer ONE canonical corpus identically. They
// cannot share a helper (the build tool, the shipped validator package and the shipped authoring
// tools are separate distributions), so tests/fixtures/region_marker_parity.json is the contract:
// tests/test_region_marker_parity.py pins the Python side, this spec pins the runtime side.

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = JSON.parse(
  fs.readFileSync(path.join(__dirname, "fixtures", "region_marker_parity.json"), "utf8"),
);
const CASES = FIXTURE.cases;

test("the runtime region locator matches the shared parity fixture (CMH-VAL-22)", async ({ page }) => {
  await openInline(page);
  const got = await page.evaluate((cases) => {
    if (typeof window.__cmhRegionMarkerMatches !== "function") return null;
    return cases.map((c) => window.__cmhRegionMarkerMatches(c.text, c.kind, c.region));
  }, CASES);
  expect(got, "the runtime must expose __cmhRegionMarkerMatches").not.toBeNull();
  for (let i = 0; i < CASES.length; i++) {
    expect(got[i], CASES[i].id).toEqual(CASES[i].expected);
  }
});

test("the runtime breaks marker lines on newlines only, like the Python copies (CMH-VAL-22)", async ({ page }) => {
  // Python's str.splitlines() also breaks on these, which is exactly how the two views used to
  // disagree about which comment IS the boundary. Pin the runtime answer directly so a future
  // change to either side has to face the same corpus.
  await openInline(page);
  const seps = ["\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029", "\r"];
  const got = await page.evaluate((separators) => separators.map(
    (sep) => window.__cmhRegionMarkerMatches("<!--" + sep + "BEGIN: commentable-html - CSS" + sep + "-->\n", "BEGIN", "CSS"),
  ), seps);
  for (let i = 0; i < seps.length; i++) {
    expect(got[i], JSON.stringify(seps[i])).toEqual([]);
  }
});
