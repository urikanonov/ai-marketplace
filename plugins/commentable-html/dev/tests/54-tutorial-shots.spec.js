import { test, expect } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import path from "path";
import { DEV, SKILL } from "./helpers.js";

// These tests each spawn the capture tool (a browser-launching subprocess). They are data-safe to
// run in parallel - the tool isolates its own scratch per process id, and each test below writes to
// its own uniquely named out dir under a per-worker TEST_TMP root - so they run in the `heavy`
// Playwright project (its own CI job with a small worker count) rather than serially. Do NOT wipe a
// SHARED tmp parent here: a per-worker afterAll wiping a dir another worker's subprocess is still
// writing into is the race the old `mode: serial` guarded; per-worker roots remove that need.

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
// Per-worker scratch root (process id) so parallel workers never share a dir - and so this file's
// afterAll only ever removes ITS OWN worker's tree, never a dir another worker is writing into.
const TEST_TMP = path.join(REPO, "tmp", "tutorial-shots-spec", String(process.pid));
const PIXEL_CHANNEL_TOLERANCE = 96;
// Match the tool's --check budget exactly (capture_tutorial.mjs MAX_PIXEL_DIFF_RATIO / MAX_DIMENSION_DELTA)
// so this cross-run determinism assertion is never STRICTER than the freshness gate it mirrors: a
// sub-pixel layout jitter that --check tolerates must not fail here.
const MAX_PIXEL_DIFF_RATIO = 0.2;
const MAX_DIMENSION_DELTA = 2;
// The tool degrades BOTH images the same way before diffing (downsample by 2 then upsample nearest,
// plus a step-64 color quantize) so cross-platform font antialiasing cannot fail the check. The
// committed PNGs are saved raw/crisp now, so mirror that normalization here to keep this determinism
// assertion aligned with (never stricter than) the tool's --check budget.
const PNG_DOWNSAMPLE = 2;
const PNG_QUANTIZE_STEP = 64;

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
  const ratio = await comparePage.evaluate(async ({ expectedBase64, actualBase64, tolerance, maxDimensionDelta, scale, step }) => {
    async function decode(base64) {
      const img = new Image();
      img.src = "data:image/png;base64," + base64;
      await img.decode();
      return img;
    }
    // Degrade both images identically (downsample then upsample nearest + color-quantize) before
    // diffing, exactly like capture_tutorial.mjs, so this determinism check is never stricter than
    // the tool's --check even though the committed PNGs are now saved raw and crisp.
    function normalize(img, width, height) {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      if (scale > 1) {
        const small = document.createElement("canvas");
        small.width = Math.max(1, Math.ceil(width / scale));
        small.height = Math.max(1, Math.ceil(height / scale));
        const sctx = small.getContext("2d");
        sctx.imageSmoothingEnabled = true;
        sctx.drawImage(canvas, 0, 0, small.width, small.height);
        ctx.clearRect(0, 0, width, height);
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(small, 0, 0, width, height);
      }
      const image = ctx.getImageData(0, 0, width, height);
      const d = image.data;
      for (let i = 0; i < d.length; i += 4) {
        d[i] = Math.round(d[i] / step) * step;
        d[i + 1] = Math.round(d[i + 1] / step) * step;
        d[i + 2] = Math.round(d[i + 2] / step) * step;
        if (d[i] === d[i + 1] && d[i + 1] === d[i + 2] && d[i] >= 192) {
          d[i] = 255;
          d[i + 1] = 255;
          d[i + 2] = 255;
        }
      }
      return d;
    }
    try {
      const expectedImg = await decode(expectedBase64);
      const actualImg = await decode(actualBase64);
      if (Math.abs(expectedImg.naturalWidth - actualImg.naturalWidth) > maxDimensionDelta
        || Math.abs(expectedImg.naturalHeight - actualImg.naturalHeight) > maxDimensionDelta) return 1;
      const width = Math.min(expectedImg.naturalWidth, actualImg.naturalWidth);
      const height = Math.min(expectedImg.naturalHeight, actualImg.naturalHeight);
      const expectedData = normalize(expectedImg, width, height);
      const actualData = normalize(actualImg, width, height);
      let different = 0;
      const total = width * height;
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
    scale: PNG_DOWNSAMPLE,
    step: PNG_QUANTIZE_STEP,
  });
  return ratio <= MAX_PIXEL_DIFF_RATIO;
}

test.afterAll(() => {
  // Only this worker's own scratch tree. The capture tool cleans its own per-process check/generate
  // scratch (tmp/tutorial-shots-check/<pid>, tmp/tutorial-shots-generate/<pid>) on success, so do
  // NOT wipe those shared parents here - that would race a sibling worker's in-flight subprocess.
  fs.rmSync(TEST_TMP, { recursive: true, force: true });
});

// dev/tools/capture_tutorial.mjs must regenerate every tutorial screenshot with one easy command
// and do it reproducibly. These behaviors were one monolithic (~5-capture, serial) test; they are
// split into focused tests, each with its OWN out dir, so the `heavy` project can run them in
// parallel across a few workers instead of one long serial block. They keep the same CMH-TUT-SHOTS-01
// coverage: default resolution, regenerate + clean --check, cross-run determinism, and stale detection.
test("--print-paths resolves the shipped tutorial defaults (CMH-TUT-SHOTS-01)", async () => {
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
});

test("regenerates every garden shot into a nested out dir, and --check passes on fresh output (CMH-TUT-SHOTS-01)", async () => {
  test.setTimeout(180000);
  // A nonexistent NESTED output dir also exercises recursive out-dir creation.
  const outA = path.join(freshDir("regen"), "nested", "assets");
  const r1 = capture(EXAMPLE, outA);
  expect(r1.error, String(r1.error)).toBeFalsy();
  expect(r1.status, r1.stderr).toBe(0);
  for (const name of SHOTS) {
    expect(fs.existsSync(path.join(outA, `garden-${name}.png`)), `missing garden-${name}.png`).toBe(true);
  }
  // Re-run into the SAME populated dir: `npm run shots` regenerates over the committed images, so
  // the tool must overwrite an existing populated out dir without erroring (idempotency/overwrite).
  const r2 = capture(EXAMPLE, outA);
  expect(r2.error, String(r2.error)).toBeFalsy();
  expect(r2.status, r2.stderr).toBe(0);
  const clean = check(EXAMPLE, outA);
  expect(clean.error, String(clean.error)).toBeFalsy();
  expect(clean.status, clean.stderr).toBe(0);
  expect(clean.stdout).toContain("tutorial screenshots are in sync");
});

test("garden capture is deterministic across two independent runs (CMH-TUT-SHOTS-01)", async ({ browser }) => {
  test.setTimeout(180000);
  const comparePage = await browser.newPage();
  try {
    const outA = path.join(freshDir("det-a"), "nested", "assets");
    const outB = path.join(freshDir("det-b"), "nested", "assets");
    for (const [dir, label] of [[outA, "A"], [outB, "B"]]) {
      const r = capture(EXAMPLE, dir);
      expect(r.error, String(r.error)).toBeFalsy();
      expect(r.status, `capture ${label}: ${r.stderr}`).toBe(0);
    }
    for (const name of SHOTS) {
      expect(await imagesMatch(
        comparePage,
        path.join(outA, `garden-${name}.png`),
        path.join(outB, `garden-${name}.png`),
      ), `${name} drifted beyond the normalized screenshot diff budget`).toBe(true);
    }
  } finally {
    await comparePage.close();
  }
});

test("--check flags a stale garden shot (CMH-TUT-SHOTS-01)", async () => {
  test.setTimeout(180000);
  const outA = path.join(freshDir("stale"), "nested", "assets");
  const r1 = capture(EXAMPLE, outA);
  expect(r1.error, String(r1.error)).toBeFalsy();
  expect(r1.status, r1.stderr).toBe(0);
  fs.writeFileSync(path.join(outA, "garden-01-top-light.png"), Buffer.from("stale screenshot"));
  const stale = check(EXAMPLE, outA);
  expect(stale.error, String(stale.error)).toBeFalsy();
  expect(stale.status, stale.stdout + stale.stderr).toBe(1);
  expect(stale.stderr).toContain("garden-01-top-light.png differs");
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

// The no-positional default run (`npm run shots` / rebuild_all) drives ALL scenes at once. This test
// guards the tool/spec shot contract: a SCENE_ORDER drift that dropped a scene, or a shot added to
// the tool but not the spec (or vice versa), is caught here. The actual all-scenes `--check` freshness
// run is NOT repeated here (it would re-capture every scene, the heaviest single step): the required
// `plugin-tests` fast-shard-1 step already runs `capture_tutorial.mjs --check`, so duplicating it in
// the suite only slowed the heavy job.
test("the no-arg default run's shot registry matches the spec's scene lists (CMH-TUT-SHOTS-01)", async () => {
  const dry = spawnSync("node", [path.join(DEV, "tools", "capture_tutorial.mjs"), "--print-paths"], { encoding: "utf8" });
  expect(dry.error, String(dry.error)).toBeFalsy();
  expect(dry.status, dry.stderr).toBe(0);
  const registry = JSON.parse(dry.stdout).scenes;
  // The spec's own shot lists are the tool's authoritative lists - no silent drift either way.
  expect(registry.garden).toEqual(SHOTS);
  for (const scene of EXTRA_SCENES) expect(registry[scene.prefix]).toEqual(scene.shots);
  expect(Object.keys(registry).sort()).toEqual(["checklist", "garden", "note", "triage"]);
});
