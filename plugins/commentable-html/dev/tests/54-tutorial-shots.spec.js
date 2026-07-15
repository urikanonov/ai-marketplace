import { test, expect } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";
import { DEV, SKILL } from "./helpers.js";

// The nine screenshots the tutorial (docs/TUTORIAL.md) embeds as garden-*.png.
const SHOTS = [
  "01-top-light", "02-kql", "03-chart", "04-diff", "05-composer",
  "06-comment-saved", "07-help", "08-top-dark", "09-copyall",
];

// The full-page shots that are reproducible byte-for-byte on a given environment. With the capture
// clock pinned and CSS motion frozen these are stable run to run (verified across repeated pairs).
// Excluded: the figure crops (02/03/04) can vary by sub-pixel antialiasing on an element screenshot,
// and the dark-theme shot (08) varies for a non-clock reason - both are visually equivalent, not
// byte-stable, so they are not asserted.
const STABLE = ["01-top-light", "05-composer", "06-comment-saved", "07-help", "09-copyall"];

const EXAMPLE = path.join(SKILL, "examples", "report-community-garden.html");

// Run the capture tool with only the example + output dir (no prefix): the tool defaults the
// prefix to "garden", so regenerating the tutorial screenshots is a single, argument-light command.
function capture(outDir) {
  return spawnSync("node", [path.join(DEV, "tools", "capture_tutorial.mjs"), EXAMPLE, outDir],
    { encoding: "utf8", timeout: 150000, killSignal: "SIGKILL" });
}

// dev/tools/capture_tutorial.mjs must regenerate every tutorial screenshot with one easy command
// and do it reproducibly, so refreshing the tutorial images is deterministic and reviewable.
test("CMH-TUT-SHOTS-01: one command regenerates all tutorial screenshots, deterministically", async () => {
  test.setTimeout(180000);

  // The no-argument invocation (what `npm run shots` runs) resolves to the shipped tutorial defaults.
  const dry = spawnSync("node", [path.join(DEV, "tools", "capture_tutorial.mjs"), "--print-paths"],
    { encoding: "utf8" });
  expect(dry.error, String(dry.error)).toBeFalsy();
  expect(dry.status, dry.stderr).toBe(0);
  const defaults = JSON.parse(dry.stdout);
  expect(defaults.example.replace(/\\/g, "/")).toMatch(/pkg\/skills\/commentable-html\/examples\/report-community-garden\.html$/);
  expect(defaults.outDir.replace(/\\/g, "/")).toMatch(/pkg\/skills\/commentable-html\/docs\/assets$/);
  expect(defaults.prefix).toBe("garden");

  // A nonexistent NESTED output dir also exercises recursive out-dir creation.
  const outA = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "cmh_shots_a_")), "nested", "assets");
  const r1 = capture(outA);
  expect(r1.error, String(r1.error)).toBeFalsy();
  expect(r1.status, r1.stderr).toBe(0);
  for (const name of SHOTS) {
    expect(fs.existsSync(path.join(outA, `garden-${name}.png`)), `missing garden-${name}.png`).toBe(true);
  }

  // Deterministic: a second run produces byte-identical output for the stable full-page shots.
  const outB = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "cmh_shots_b_")), "nested", "assets");
  const r2 = capture(outB);
  expect(r2.error, String(r2.error)).toBeFalsy();
  expect(r2.status, r2.stderr).toBe(0);
  for (const name of STABLE) {
    const a = fs.readFileSync(path.join(outA, `garden-${name}.png`));
    const b = fs.readFileSync(path.join(outB, `garden-${name}.png`));
    expect(Buffer.compare(a, b), `garden-${name}.png is not byte-identical across runs`).toBe(0);
  }
});
