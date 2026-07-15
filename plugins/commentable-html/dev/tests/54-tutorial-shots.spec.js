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

const EXAMPLE = path.join(SKILL, "examples", "report-community-garden.html");

// Run the capture tool with only the example + output dir (no prefix): the tool defaults the
// prefix to "garden", so regenerating the tutorial screenshots is a single, argument-light command.
function capture(outDir) {
  return spawnSync("node", [path.join(DEV, "tools", "capture_tutorial.mjs"), EXAMPLE, outDir],
    { encoding: "utf8" });
}

// dev/tools/capture_tutorial.mjs must regenerate every tutorial screenshot with one easy command
// and do it deterministically, so refreshing the tutorial images is reproducible and reviewable.
test("CMH-TUT-SHOTS-01: one command regenerates all tutorial screenshots, deterministically", async () => {
  test.setTimeout(180000);
  const outA = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_shots_a_"));
  const r1 = capture(outA);
  expect(r1.status, r1.stderr).toBe(0);
  for (const name of SHOTS) {
    expect(fs.existsSync(path.join(outA, `garden-${name}.png`)), `missing garden-${name}.png`).toBe(true);
  }

  // Deterministic: a second run produces a byte-identical static top-of-document shot.
  const outB = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_shots_b_"));
  const r2 = capture(outB);
  expect(r2.status, r2.stderr).toBe(0);
  const first = fs.readFileSync(path.join(outA, "garden-01-top-light.png"));
  const second = fs.readFileSync(path.join(outB, "garden-01-top-light.png"));
  expect(Buffer.compare(first, second), "the top-of-document shot is not byte-identical across runs").toBe(0);
});
