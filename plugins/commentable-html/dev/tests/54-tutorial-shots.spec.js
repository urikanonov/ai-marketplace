import { test, expect } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import path from "path";
import { DEV, SKILL } from "./helpers.js";

// The nine screenshots the tutorial (docs/TUTORIAL.md) embeds as garden-*.png.
const SHOTS = [
  "01-top-light", "02-kql", "03-chart", "04-diff", "05-composer",
  "06-comment-saved", "07-help", "08-top-dark", "09-copyall",
];

const EXAMPLE = path.join(SKILL, "examples", "report-community-garden.html");
const REPO = path.resolve(DEV, "..", "..", "..");
const TEST_TMP = path.join(REPO, "tmp", "tutorial-shots-spec");
const PIXEL_CHANNEL_TOLERANCE = 96;
const MAX_PIXEL_DIFF_RATIO = 0.15;

// Run the capture tool with only the example + output dir (no prefix): the tool defaults the
// prefix to "garden", so regenerating the tutorial screenshots is a single, argument-light command.
function capture(outDir) {
  return spawnSync("node", [path.join(DEV, "tools", "capture_tutorial.mjs"), EXAMPLE, outDir],
    { encoding: "utf8", timeout: 150000, killSignal: "SIGKILL" });
}

function check(outDir) {
  return spawnSync("node", [path.join(DEV, "tools", "capture_tutorial.mjs"), "--check", EXAMPLE, outDir],
    { encoding: "utf8", timeout: 150000, killSignal: "SIGKILL" });
}

function freshDir(name) {
  const dir = path.join(TEST_TMP, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

async function imagesMatch(comparePage, expected, actual) {
  if (!fs.existsSync(expected) || !fs.existsSync(actual)) return false;
  const ratio = await comparePage.evaluate(async ({ expectedBase64, actualBase64, tolerance }) => {
    async function decode(base64) {
      const img = new Image();
      img.src = "data:image/png;base64," + base64;
      await img.decode();
      return img;
    }
    try {
      const expectedImg = await decode(expectedBase64);
      const actualImg = await decode(actualBase64);
      if (expectedImg.naturalWidth !== actualImg.naturalWidth || expectedImg.naturalHeight !== actualImg.naturalHeight) return 1;
      const canvas = document.createElement("canvas");
      canvas.width = expectedImg.naturalWidth;
      canvas.height = expectedImg.naturalHeight;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(expectedImg, 0, 0);
      const expectedData = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(actualImg, 0, 0);
      const actualData = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      let different = 0;
      const total = canvas.width * canvas.height;
      for (let i = 0; i < expectedData.length; i += 4) {
        const maxChannelDelta = Math.max(
          Math.abs(expectedData[i] - actualData[i]),
          Math.abs(expectedData[i + 1] - actualData[i + 1]),
          Math.abs(expectedData[i + 2] - actualData[i + 2]),
          Math.abs(expectedData[i + 3] - actualData[i + 3]),
        );
        if (maxChannelDelta > tolerance) different += 1;
      }
      return different / total;
    } catch {
      return 1;
    }
  }, {
    expectedBase64: fs.readFileSync(expected).toString("base64"),
    actualBase64: fs.readFileSync(actual).toString("base64"),
    tolerance: PIXEL_CHANNEL_TOLERANCE,
  });
  return ratio <= MAX_PIXEL_DIFF_RATIO;
}

test.afterAll(() => {
  fs.rmSync(TEST_TMP, { recursive: true, force: true });
  fs.rmSync(path.join(REPO, "tmp", "tutorial-shots-check"), { recursive: true, force: true });
});

// dev/tools/capture_tutorial.mjs must regenerate every tutorial screenshot with one easy command
// and do it reproducibly, so refreshing the tutorial images is deterministic and reviewable.
test("one command regenerates and checks all tutorial screenshots, deterministically (CMH-TUT-SHOTS-01)", async ({ browser }) => {
  test.setTimeout(240000);
  const comparePage = await browser.newPage();
  try {

  // The no-argument invocation (what `npm run shots` runs) resolves to the shipped tutorial defaults.
  const dry = spawnSync("node", [path.join(DEV, "tools", "capture_tutorial.mjs"), "--print-paths"],
    { encoding: "utf8" });
  expect(dry.error, String(dry.error)).toBeFalsy();
  expect(dry.status, dry.stderr).toBe(0);
  const defaults = JSON.parse(dry.stdout);
  expect(defaults.example.replace(/\\/g, "/")).toMatch(/pkg\/skills\/commentable-html\/examples\/report-community-garden\.html$/);
  expect(defaults.outDir.replace(/\\/g, "/")).toMatch(/pkg\/skills\/commentable-html\/docs\/assets$/);
  expect(defaults.prefix).toBe("garden");
  expect(defaults.check).toBe(false);

  // A nonexistent NESTED output dir also exercises recursive out-dir creation.
  const outA = path.join(freshDir("a"), "nested", "assets");
  const r1 = capture(outA);
  expect(r1.error, String(r1.error)).toBeFalsy();
  expect(r1.status, r1.stderr).toBe(0);
  for (const name of SHOTS) {
    expect(fs.existsSync(path.join(outA, `garden-${name}.png`)), `missing garden-${name}.png`).toBe(true);
  }
  const r1b = capture(outA);
  expect(r1b.error, String(r1b.error)).toBeFalsy();
  expect(r1b.status, r1b.stderr).toBe(0);

  const clean = check(outA);
  expect(clean.error, String(clean.error)).toBeFalsy();
  expect(clean.status, clean.stderr).toBe(0);
  expect(clean.stdout).toContain("tutorial screenshots are in sync");

  const outB = path.join(freshDir("b"), "nested", "assets");
  const r2 = capture(outB);
  expect(r2.error, String(r2.error)).toBeFalsy();
  expect(r2.status, r2.stderr).toBe(0);
  for (const name of SHOTS) {
    expect(await imagesMatch(
      comparePage,
      path.join(outA, `garden-${name}.png`),
      path.join(outB, `garden-${name}.png`),
    ), `${name} drifted beyond the normalized screenshot diff budget`).toBe(true);
  }
  const cleanB = check(outB);
  expect(cleanB.error, String(cleanB.error)).toBeFalsy();
  expect(cleanB.status, cleanB.stderr).toBe(0);

  fs.writeFileSync(path.join(outA, "garden-01-top-light.png"), Buffer.from("stale screenshot"));
  const stale = check(outA);
  expect(stale.error, String(stale.error)).toBeFalsy();
  expect(stale.status, stale.stdout + stale.stderr).toBe(1);
  expect(stale.stderr).toContain("garden-01-top-light.png differs");
  } finally {
    await comparePage.close();
  }
});
