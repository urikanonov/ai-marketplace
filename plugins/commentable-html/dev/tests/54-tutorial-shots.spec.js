import { test, expect } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import path from "path";
import { DEV, SKILL } from "./helpers.js";

// These tests each spawn the capture tool, which writes into shared tmp/ scratch dirs, and the
// afterAll cleanup removes those dirs. Run them serially so one worker's cleanup never wipes a
// scratch dir another parallel worker's capture subprocess is still writing into.
test.describe.configure({ mode: "serial" });

// The thirteen screenshots the tutorial (docs/TUTORIAL.md) embeds as garden-*.png.
const SHOTS = [
  "01-top-light", "02-kql", "03-chart", "04-diff", "05-composer",
  "06-comment-saved", "07-help", "08-top-dark", "09-copyall",
  "10-review-badge", "11-side-toc", "12-export-menu", "13-comment-search",
];

const EXAMPLES = path.join(SKILL, "..", "..", "examples");
const EXAMPLE = path.join(EXAMPLES, "report-community-garden.html");
// Checklists, notes, and the incident triage board render in their own example reports, so each is
// captured as a small scene of its own (checklist-*.png, note-*.png, triage-*.png).
const EXTRA_SCENES = [
  { prefix: "triage", example: path.join(EXAMPLES, "report-triage.html"), shots: ["01-board"] },
  { prefix: "checklist", example: path.join(EXAMPLES, "report-checklist.html"), shots: ["01-checklist"] },
  { prefix: "note", example: path.join(EXAMPLES, "report-notes.html"), shots: ["01-note"] },
];
const REPO = path.resolve(DEV, "..", "..", "..");
const TEST_TMP = path.join(REPO, "tmp", "tutorial-shots-spec");
const PIXEL_CHANNEL_TOLERANCE = 96;
// Match the tool's --check budget exactly (capture_tutorial.mjs MAX_PIXEL_DIFF_RATIO / MAX_DIMENSION_DELTA)
// so this cross-run determinism assertion is never STRICTER than the freshness gate it mirrors: a
// sub-pixel layout jitter that --check tolerates must not fail here.
const MAX_PIXEL_DIFF_RATIO = 0.2;
const MAX_DIMENSION_DELTA = 2;

// Run the capture tool with the example + output dir (and, for the extra scenes, an explicit
// prefix). With no prefix the tool defaults to "garden", so regenerating the garden tutorial
// screenshots stays a single, argument-light command.
function capture(example, outDir, prefix) {
  const args = [path.join(DEV, "tools", "capture_tutorial.mjs"), example, outDir];
  if (prefix) args.push(prefix);
  return spawnSync("node", args, { encoding: "utf8", timeout: 150000, killSignal: "SIGKILL" });
}

function check(example, outDir, prefix) {
  const args = [path.join(DEV, "tools", "capture_tutorial.mjs"), "--check", example, outDir];
  if (prefix) args.push(prefix);
  return spawnSync("node", args, { encoding: "utf8", timeout: 150000, killSignal: "SIGKILL" });
}

function freshDir(name) {
  const dir = path.join(TEST_TMP, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

async function imagesMatch(comparePage, expected, actual) {
  if (!fs.existsSync(expected) || !fs.existsSync(actual)) return false;
  const ratio = await comparePage.evaluate(async ({ expectedBase64, actualBase64, tolerance, maxDimensionDelta }) => {
    async function decode(base64) {
      const img = new Image();
      img.src = "data:image/png;base64," + base64;
      await img.decode();
      return img;
    }
    try {
      const expectedImg = await decode(expectedBase64);
      const actualImg = await decode(actualBase64);
      if (Math.abs(expectedImg.naturalWidth - actualImg.naturalWidth) > maxDimensionDelta
        || Math.abs(expectedImg.naturalHeight - actualImg.naturalHeight) > maxDimensionDelta) return 1;
      const canvas = document.createElement("canvas");
      canvas.width = Math.min(expectedImg.naturalWidth, actualImg.naturalWidth);
      canvas.height = Math.min(expectedImg.naturalHeight, actualImg.naturalHeight);
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
    maxDimensionDelta: MAX_DIMENSION_DELTA,
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
  expect(defaults.example.replace(/\\/g, "/")).toMatch(/plugins\/commentable-html\/examples\/report-community-garden\.html$/);
  expect(defaults.outDir.replace(/\\/g, "/")).toMatch(/plugins\/commentable-html\/docs\/assets$/);
  expect(defaults.prefix).toBe("garden");
  expect(defaults.check).toBe(false);

  // A nonexistent NESTED output dir also exercises recursive out-dir creation.
  const outA = path.join(freshDir("a"), "nested", "assets");
  const r1 = capture(EXAMPLE, outA);
  expect(r1.error, String(r1.error)).toBeFalsy();
  expect(r1.status, r1.stderr).toBe(0);
  for (const name of SHOTS) {
    expect(fs.existsSync(path.join(outA, `garden-${name}.png`)), `missing garden-${name}.png`).toBe(true);
  }
  const r1b = capture(EXAMPLE, outA);
  expect(r1b.error, String(r1b.error)).toBeFalsy();
  expect(r1b.status, r1b.stderr).toBe(0);

  const clean = check(EXAMPLE, outA);
  expect(clean.error, String(clean.error)).toBeFalsy();
  expect(clean.status, clean.stderr).toBe(0);
  expect(clean.stdout).toContain("tutorial screenshots are in sync");

  const outB = path.join(freshDir("b"), "nested", "assets");
  const r2 = capture(EXAMPLE, outB);
  expect(r2.error, String(r2.error)).toBeFalsy();
  expect(r2.status, r2.stderr).toBe(0);
  for (const name of SHOTS) {
    expect(await imagesMatch(
      comparePage,
      path.join(outA, `garden-${name}.png`),
      path.join(outB, `garden-${name}.png`),
    ), `${name} drifted beyond the normalized screenshot diff budget`).toBe(true);
  }
  const cleanB = check(EXAMPLE, outB);
  expect(cleanB.error, String(cleanB.error)).toBeFalsy();
  expect(cleanB.status, cleanB.stderr).toBe(0);

  fs.writeFileSync(path.join(outA, "garden-01-top-light.png"), Buffer.from("stale screenshot"));
  const stale = check(EXAMPLE, outA);
  expect(stale.error, String(stale.error)).toBeFalsy();
  expect(stale.status, stale.stdout + stale.stderr).toBe(1);
  expect(stale.stderr).toContain("garden-01-top-light.png differs");
  } finally {
    await comparePage.close();
  }
});

// The board, checklist, and note features render only in their own example reports, so the tool
// captures each as a prefixed scene. The same regenerate/check/deterministic/stale guarantees the
// garden scene has must hold for these scenes too.
for (const scene of EXTRA_SCENES) {
  test(`regenerates and checks the ${scene.prefix} scene deterministically (CMH-TUT-SHOTS-01)`, async ({ browser }) => {
    test.setTimeout(180000);
    const comparePage = await browser.newPage();
    try {
      const outA = path.join(freshDir(`${scene.prefix}-a`), "nested", "assets");
      const r1 = capture(scene.example, outA, scene.prefix);
      expect(r1.error, String(r1.error)).toBeFalsy();
      expect(r1.status, r1.stderr).toBe(0);
      for (const name of scene.shots) {
        expect(fs.existsSync(path.join(outA, `${scene.prefix}-${name}.png`)),
          `missing ${scene.prefix}-${name}.png`).toBe(true);
      }

      const clean = check(scene.example, outA, scene.prefix);
      expect(clean.error, String(clean.error)).toBeFalsy();
      expect(clean.status, clean.stderr).toBe(0);
      expect(clean.stdout).toContain("tutorial screenshots are in sync");

      const outB = path.join(freshDir(`${scene.prefix}-b`), "nested", "assets");
      const r2 = capture(scene.example, outB, scene.prefix);
      expect(r2.error, String(r2.error)).toBeFalsy();
      expect(r2.status, r2.stderr).toBe(0);
      for (const name of scene.shots) {
        expect(await imagesMatch(
          comparePage,
          path.join(outA, `${scene.prefix}-${name}.png`),
          path.join(outB, `${scene.prefix}-${name}.png`),
        ), `${scene.prefix}-${name} drifted beyond the normalized screenshot diff budget`).toBe(true);
      }

      const firstShot = `${scene.prefix}-${scene.shots[0]}.png`;
      fs.writeFileSync(path.join(outA, firstShot), Buffer.from("stale screenshot"));
      const stale = check(scene.example, outA, scene.prefix);
      expect(stale.error, String(stale.error)).toBeFalsy();
      expect(stale.status, stale.stdout + stale.stderr).toBe(1);
      expect(stale.stderr).toContain(`${firstShot} differs`);
    } finally {
      await comparePage.close();
    }
  });
}

// The no-positional default run (`npm run shots` / rebuild_all) drives ALL scenes at once. The
// per-scene tests above only exercise the single-scene positional path, so this test guards the
// multi-scene orchestration and the tool/spec shot contract: a SCENE_ORDER drift that dropped a
// scene, or a shot added to the tool but not the spec (or vice versa), is caught here.
test("the no-arg default run orchestrates every scene and matches the tool's shot registry (CMH-TUT-SHOTS-01)", async () => {
  test.setTimeout(240000);
  const dry = spawnSync("node", [path.join(DEV, "tools", "capture_tutorial.mjs"), "--print-paths"], { encoding: "utf8" });
  expect(dry.error, String(dry.error)).toBeFalsy();
  expect(dry.status, dry.stderr).toBe(0);
  const registry = JSON.parse(dry.stdout).scenes;
  // The spec's own shot lists are the tool's authoritative lists - no silent drift either way.
  expect(registry.garden).toEqual(SHOTS);
  for (const scene of EXTRA_SCENES) expect(registry[scene.prefix]).toEqual(scene.shots);
  expect(Object.keys(registry).sort()).toEqual(["checklist", "garden", "note", "triage"]);
  // The no-positional --check run captures every scene fresh and compares to the committed
  // docs/assets images; a dropped scene would capture fewer files or fall out of sync.
  const all = spawnSync("node", [path.join(DEV, "tools", "capture_tutorial.mjs"), "--check"],
    { encoding: "utf8", timeout: 220000, killSignal: "SIGKILL" });
  expect(all.error, String(all.error)).toBeFalsy();
  expect(all.status, all.stdout + all.stderr).toBe(0);
  expect(all.stdout).toContain("tutorial screenshots are in sync");
});
